"""
cognia/compilador/evaluador.py
==============================
EL EXAMEN. Probar a fondo una herramienta recien injertada y decidir con
EVIDENCIA si se queda o se retira.

POR QUE EXISTE. El duenio lo pidio literalmente: "que las pruebe evalue y que
las pruebe bien a profundidad". El injertador ya deja el comando escrito en
los 5 sitios y con los guardianes verdes, pero eso solo demuestra que el
CATALOGO sigue sano -- no que el comando HAGA algo. Un comando que se da de
alta, sale en /ayuda y al teclearlo no imprime nada es exactamente el fallo
tipico de este repo: el vacio silencioso, que desde fuera es indistinguible de
"no lo cablearon". Este modulo es lo que separa esos dos estados.

EL PRINCIPIO. El veredicto sale de lo EJECUTADO, nunca de una opinion. Las
cinco fases corren codigo de verdad (compile, pytest en subproceso, el REPL
arrancado y tecleado). Si una fase NO se pudo ejecutar, vale ok=False y se
dice por que: ausencia de examen no es aprobado. Esa regla es el corazon del
modulo y por eso el presupuesto de tiempo agotado tambien suspende en vez de
aprobar por defecto.

POR QUE TODO VA EN SUBPROCESO. El compilador acaba de REESCRIBIR cli.py en el
mismo proceso que corre el REPL: `cognia.cli` esta cacheado en sys.modules con
el codigo VIEJO. Un pytest in-process o un import del handler nuevo juzgarian
codigo que ya no esta en disco. El unico juez honesto es un interprete nuevo
leyendo el fichero nuevo -- el mismo motivo por el que
injertador.correr_los_guardianes tampoco corre pytest por dentro.

QUE PINTA TIENE UN `espec`. Se acepta un dict o cualquier objeto con
atributos (el generador todavia puede cambiar de forma; leer por `_campo`
evita acoplarse a una clase concreta):

    {"cmd": "/clima", "nombre": "clima", "descripcion": "...",
     "modulo": "cognia/herramientas/clima.py",
     "criterios": [{"invocacion": "/clima estado", "espera": "clima"}]}

Los `criterios` son la POSTCONDICION del duenio y son los que mandan: lo que
el comando tiene que imprimir cuando se teclea de verdad.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from cognia.compilador import receta as rec

_log = logging.getLogger(__name__)

RAIZ = rec.RAIZ

# Los ficheros que el injerto puede haber tocado. Se toman de la receta si un
# dia se mueven alli, y si no se reconstruyen con sus tres constantes: leerlos
# de `injertador.TOCABLES` obligaria a importar el injertador al cargar este
# modulo, y el injertador arrastra justo el codigo que el compilador acaba de
# reescribir. Hay un test que comprueba que las dos listas siguen siendo la
# misma, para que la copia no se quede vieja en silencio.
TOCABLES = tuple(getattr(rec, "TOCABLES", (rec.CLI, rec.VISIBILIDAD, rec.AYUDA)))

# Topes por fase, en segundos. Son topes y no cuotas: cada fase recibe el
# MINIMO entre su tope y lo que quede del presupuesto global, para que una
# fase lenta no se coma el examen entero. Un comando generado que se cuelga no
# puede colgar el compilador: sin timeout, un `input()` colado en el handler
# generado dejaria el subproceso esperando para siempre.
TOPES = {
    "sintaxis": 60.0,
    "guardianes": 600.0,
    "tests": 600.0,
    "invocacion": 180.0,
    "criterios": 300.0,
}

# Fases que, al fallar, INVALIDAN el resto del examen. Sintaxis rota o
# guardianes rojos significan que el repo no esta en un estado legal: seguir a
# la fase 4 seria arrancar un CLI que ya sabemos que esta mal puesto y perder
# minutos para llegar a la misma conclusion. Las tres ultimas NO cortan a
# proposito: examinan al comando en si, y el duenio quiere ver TODA la
# evidencia de por que se rechazo, no solo el primer sintoma.
BLOQUEANTES = ("sintaxis", "guardianes")

ORDEN = ("sintaxis", "guardianes", "tests", "invocacion", "criterios")

# Cuanto texto real de cada fase se guarda. Se conserva cabeza y COLA porque
# lo que explica un fallo esta al final (el resumen de pytest, la ultima linea
# de un traceback) y lo que lo situa esta al principio.
TOPE_SALIDA = 4000

_RE_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_RE_ESPACIOS = re.compile(r"\s+")
_RE_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


# ── Lectura tolerante del espec ──────────────────────────────────────────────

def _campo(espec, *nombres, defecto=None):
    """Primer campo presente, mirando dict Y atributos.

    El generador es otro modulo y todavia puede cambiar de forma (dataclass,
    dict, SimpleNamespace). Acoplarse a una de las tres haria que el evaluador
    devolviese 'sin criterios' -- o sea SUSPENSO -- por un detalle de tipado,
    que es la peor forma de mentir: un rechazo que parece un veredicto.
    """
    for n in nombres:
        if isinstance(espec, dict):
            if n in espec and espec[n] not in (None, ""):
                return espec[n]
        else:
            v = getattr(espec, n, None)
            if v not in (None, ""):
                return v
    return defecto


def _recortar(txt: str, tope: int = TOPE_SALIDA) -> str:
    txt = txt or ""
    if len(txt) <= tope:
        return txt
    cabeza = tope // 4
    cola = tope - cabeza
    return ("%s\n... [recortado %d caracteres] ...\n%s"
            % (txt[:cabeza], len(txt) - tope, txt[-cola:]))


def _normalizar(txt: str) -> str:
    """Texto comparable: sin ANSI, en minusculas y con los espacios juntados.

    Los tres pasos estan medidos contra el REPL real: pinta el prompt con
    truecolor ('\\x1b[38;2;166;255;77m'), y rich ENVUELVE las lineas largas,
    asi que un 'espera' de tres palabras puede caer partido por un salto de
    linea. Comparar en crudo daria falsos rechazos.
    """
    return _RE_ESPACIOS.sub(" ", _RE_ANSI.sub("", txt or "")).strip().lower()


def _resultado(fase: str, ok: bool, detalle: str, salida: str = "") -> dict:
    return {"fase": fase, "ok": bool(ok), "detalle": detalle,
            "salida": _recortar(salida)}


# ── Ejecutores reales (inyectables en los tests por parametro) ───────────────

def _entorno():
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    # Efimero como en tests/test_cli_cableado.py: el examen arranca el REPL de
    # verdad, y sin esto cada evaluacion escribiria en la memoria del duenio
    # (incidente del 2026-08-25: turnos de e2e restaurados en su chat).
    env["COGNIA_EFIMERO"] = "1"
    return env


def ejecutar_proceso(cmd: list, plazo: float) -> tuple:
    """(codigo, salida) de un subproceso. codigo None = no se pudo ejecutar."""
    try:
        p = subprocess.run(cmd, cwd=str(RAIZ), env=_entorno(),
                           stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           timeout=max(1.0, plazo))
    except subprocess.TimeoutExpired as exc:
        parcial = exc.output or b""
        if isinstance(parcial, str):
            parcial = parcial.encode("utf-8", "replace")
        return None, ("TIMEOUT tras %ds\n%s"
                      % (int(plazo), parcial.decode("utf-8", "replace")))
    except OSError as exc:
        return None, "no pude lanzar %r: %s" % (cmd[:2], exc)
    return p.returncode, p.stdout.decode("utf-8", "replace")


def teclear_en_el_repl(linea: str, plazo: float) -> tuple:
    """Arranca el CLI de verdad y le TECLEA una linea. (codigo, salida).

    Mismo patron que tests/test_cli_cableado._repl y que
    scripts/e2e_happy_path.py: `python -m cognia` por subproceso, la linea por
    stdin (sin consola el REPL degrada a input()) y EOF para que salga solo.
    Es la unica prueba de que la PUERTA existe: que el comando responda algo y
    no se lleve el REPL por delante. Medido: 1,8 s por invocacion con el
    backend en :8080, o sea que teclear varios criterios es asequible.
    """
    try:
        p = subprocess.run([sys.executable, "-m", "cognia"],
                           input=(linea + "\n").encode("utf-8"),
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           cwd=str(RAIZ), env=_entorno(),
                           timeout=max(1.0, plazo))
    except subprocess.TimeoutExpired as exc:
        parcial = exc.output or b""
        if isinstance(parcial, str):
            parcial = parcial.encode("utf-8", "replace")
        return None, ("TIMEOUT: el REPL no volvio en %ds tecleando %r\n%s"
                      % (int(plazo), linea,
                         parcial.decode("utf-8", "replace")))
    except OSError as exc:
        return None, "no pude arrancar el REPL: %s" % exc
    return p.returncode, p.stdout.decode("utf-8", "replace")


def _respuesta_del_repl(salida: str) -> str:
    """Lo que imprimio EL COMANDO, sin el banner ni la despedida.

    El REPL escribe: banner, 'cognia> ', la respuesta, 'cognia> ' otra vez y
    'Hasta luego.'. Quedarse con lo de en medio es lo que permite distinguir
    'el comando no imprimio nada' de 'la pantalla estaba llena de banner'.
    """
    limpio = _RE_ANSI.sub("", salida or "")
    trozos = limpio.split("cognia>")
    if len(trozos) >= 3:
        medio = "cognia>".join(trozos[1:-1])
    elif len(trozos) == 2:
        medio = trozos[1]
    else:
        medio = limpio
    return medio.replace("Hasta luego.", "").strip()


# ── Fase 1: SINTAXIS ─────────────────────────────────────────────────────────

def fase_sintaxis(espec=None, plazo: float = TOPES["sintaxis"],
                  leer=None) -> dict:
    """compile() de los 3 ficheros tocables y del modulo de apoyo.

    Es lo primero porque es lo mas barato y lo mas fatal: si el injerto dejo
    cli.py con un parentesis abierto, ni el REPL arranca ni pytest importa
    nada, y todos los fallos posteriores serian el mismo fallo contado cinco
    veces. `leer` se inyecta en los tests para fabricar fuentes rotos sin
    tocar el repo de verdad.
    """
    leer = leer or (lambda rel: Path(rel if os.path.isabs(rel)
                                     else RAIZ / rel).read_text(
        encoding="utf-8", errors="replace"))
    objetivos = list(TOCABLES)
    modulo = _campo(espec, "modulo", "ruta_modulo", "modulo_apoyo", defecto="")
    if modulo:
        objetivos.append(str(modulo))

    lineas, malos = [], []
    for rel in objetivos:
        try:
            fuente = leer(rel)
        except OSError as exc:
            # No existe o no se puede leer: NO se puede examinar, luego no
            # aprueba. Un modulo de apoyo declarado y ausente es justo el caso
            # del comando fantasma que este modulo existe para cazar.
            malos.append(rel)
            lineas.append("%s: NO SE PUDO LEER (%s)" % (rel, exc))
            continue
        try:
            compile(fuente, rel, "exec")
        except SyntaxError as exc:
            malos.append(rel)
            lineas.append("%s: SyntaxError linea %s: %s"
                          % (rel, exc.lineno, exc.msg))
        except ValueError as exc:
            # compile() lanza ValueError con NUL en el fuente; tampoco pasa.
            malos.append(rel)
            lineas.append("%s: fuente invalido: %s" % (rel, exc))
        else:
            lineas.append("%s: compila" % rel)

    ok = not malos
    detalle = ("compilan los %d ficheros" % len(objetivos) if ok
               else "no compilan: %s" % ", ".join(malos))
    return _resultado("sintaxis", ok, detalle, "\n".join(lineas))


# ── Fase 2: GUARDIANES ───────────────────────────────────────────────────────

def fase_guardianes(espec=None, plazo: float = TOPES["guardianes"],
                    correr=None) -> dict:
    """injertador.correr_los_guardianes(). Rojos = RECHAZADA sin mas.

    Los 4 ficheros de tests del catalogo son lo que dice si el comando esta
    BIEN PUESTO (un cubo, una categoria, sin desbordes, sin taparse con otro).
    Si estan rojos, el comando esta a medias, que segun la receta es el peor
    estado posible; no tiene sentido seguir examinando lo que hace.

    El import va aqui dentro y no arriba: el injertador arrastra el modulo que
    el compilador acaba de reescribir, y un import a nivel de modulo obligaria
    a cargarlo para poder siquiera inyectar un `correr` falso en los tests.
    """
    if correr is None:
        from cognia.compilador import injertador as inj
        correr = lambda t: inj.correr_los_guardianes(timeout=t)  # noqa: E731
    try:
        r = correr(plazo) or {}
    except Exception as exc:                       # nunca en silencio
        _log.error("los guardianes no se pudieron correr: %s", exc)
        return _resultado("guardianes", False,
                          "NO SE PUDO EJECUTAR (%s: %s); sin examen no hay "
                          "aprobado" % (type(exc).__name__, exc), str(exc))
    ok = bool(r.get("ok"))
    fallos = r.get("fallos") or []
    salida = "\n".join([str(r.get("resumen", ""))] + [str(f) for f in fallos])
    detalle = ("los 4 guardianes del catalogo en verde" if ok
               else "guardianes ROJOS: %s" % str(r.get("resumen", ""))[:200])
    return _resultado("guardianes", ok, detalle, salida)


# ── Fase 3: TESTS ────────────────────────────────────────────────────────────

def fase_tests(ruta_tests: str = "", plazo: float = TOPES["tests"],
               ejecutar=None, espec=None) -> dict:
    """pytest sobre los tests generados, en SUBPROCESO y con este interprete.

    En subproceso y no in-process porque el modulo recien reescrito esta
    cacheado en sys.modules: un pytest interno importaria lo viejo y daria un
    veredicto sobre codigo que ya no existe en disco. Y con sys.executable
    porque el venv312 es el unico que corre en este repo.
    """
    ejecutar = ejecutar or ejecutar_proceso
    ruta = str(ruta_tests or _campo(espec, "ruta_tests", "tests", defecto="") or "")
    if not ruta:
        return _resultado("tests", False,
                          "NO HAY TESTS que correr: sin examen no hay "
                          "aprobado", "")
    absoluta = Path(ruta if os.path.isabs(ruta) else RAIZ / ruta)
    if not absoluta.exists():
        return _resultado("tests", False,
                          "los tests declarados no existen: %s" % ruta, "")

    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:randomly", ruta]
    codigo, salida = ejecutar(cmd, plazo)
    if codigo is None:
        return _resultado("tests", False,
                          "NO SE PUDO EJECUTAR pytest (timeout o error de "
                          "lanzamiento); sin examen no hay aprobado", salida)
    # pytest devuelve 5 cuando NO recolecto ningun test. Un fichero de tests
    # vacio saldria con 'no tests ran' y codigo 5; contarlo como aprobado
    # seria firmar un examen en blanco.
    if codigo == 5:
        return _resultado("tests", False,
                          "pytest no recolecto NINGUN test (codigo 5): "
                          "examen en blanco", salida)
    ok = codigo == 0
    detalle = ("pytest en verde" if ok
               else "pytest fallo (codigo %s)" % codigo)
    return _resultado("tests", ok, detalle, salida)


# ── Fase 4: INVOCACION REAL ──────────────────────────────────────────────────

def fase_invocacion(espec=None, plazo: float = TOPES["invocacion"],
                    teclear=None) -> dict:
    """Arranca el CLI de verdad y TECLEA el comando.

    Es la fase que el duenio exige por CLAUDE.md ("lo que no se puede teclear
    en el REPL, para el dueno no existe") y la unica que demuestra que la
    puerta existe de punta a punta: dispatch, handler, import perezoso y
    salida por pantalla. Se rechaza si el REPL no vuelve, si revienta con un
    traceback, si el comando sale por el camino de 'desconocido' o si no
    imprime absolutamente nada -- el vacio silencioso tambien es un fallo.
    """
    teclear = teclear or teclear_en_el_repl
    cmd = str(_campo(espec, "cmd", "comando", defecto="") or "")
    if not cmd:
        return _resultado("invocacion", False,
                          "el espec no dice que comando teclear: no se pudo "
                          "ejecutar", "")
    codigo, salida = teclear(cmd, plazo)
    if codigo is None:
        return _resultado("invocacion", False,
                          "NO SE PUDO EJECUTAR el REPL (timeout o error de "
                          "arranque); sin examen no hay aprobado", salida)
    limpio = _RE_ANSI.sub("", salida or "")
    respuesta = _respuesta_del_repl(salida)
    if codigo != 0:
        return _resultado("invocacion", False,
                          "el REPL murio con codigo %s al teclear %s"
                          % (codigo, cmd), salida)
    if "Traceback (most recent call last)" in limpio:
        return _resultado("invocacion", False,
                          "%s levanto un traceback: el handler puede llevarse "
                          "el REPL por delante" % cmd, salida)
    if ("Comando desconocido: %s" % cmd) in limpio or "No existe el comando" in limpio:
        return _resultado("invocacion", False,
                          "el REPL no reconoce %s: la rama del despacho no "
                          "esta puesta" % cmd, salida)
    if not respuesta:
        return _resultado("invocacion", False,
                          "%s no imprimio nada: puerta muda (indistinguible "
                          "de rota)" % cmd, salida)
    return _resultado("invocacion", True,
                      "%s responde en el REPL real (%d caracteres)"
                      % (cmd, len(respuesta)), salida)


# ── Fase 5: CRITERIOS DEL DUENIO ─────────────────────────────────────────────

def _pareja_criterio(c, cmd_defecto: str) -> tuple:
    inv = _campo(c, "invocacion", "comando", "linea", "cmd",
                 defecto=cmd_defecto)
    esp = _campo(c, "espera", "esperado", "contiene", "salida_esperada",
                 defecto="")
    if isinstance(c, str):
        # Criterio escrito como una sola cadena: es lo que se espera VER, y
        # se teclea el comando a secas.
        inv, esp = cmd_defecto, c
    esperados = list(esp) if isinstance(esp, (list, tuple)) else [esp]
    return str(inv or ""), [str(e) for e in esperados if str(e).strip()]


def fase_criterios(espec=None, plazo: float = TOPES["criterios"],
                   teclear=None) -> dict:
    """Cada criterio del duenio, TECLEADO, y su 'espera' buscado en la salida.

    Esta es la postcondicion y es la que manda: el resto de fases dicen que el
    comando esta bien puesto y no revienta; esta dice que hace LO QUE SE PIDIO.
    Sin criterios no hay postcondicion que comprobar, y eso suspende: un
    comando aprobado por no tener con que compararlo es una firma en blanco.
    """
    teclear = teclear or teclear_en_el_repl
    cmd_base = str(_campo(espec, "cmd", "comando", defecto="") or "")
    criterios = _campo(espec, "criterios", "postcondiciones", defecto=[]) or []
    if not criterios:
        return _resultado("criterios", False,
                          "el espec no trae criterios: sin postcondicion no "
                          "se puede aprobar", "")

    lineas, fallos = [], 0
    # El plazo se reparte entre los criterios para que diez criterios lentos
    # no desborden el presupuesto global del examen.
    por_criterio = max(10.0, plazo / max(1, len(criterios)))
    for i, c in enumerate(criterios, 1):
        inv, esperados = _pareja_criterio(c, cmd_base)
        if not inv or not esperados:
            fallos += 1
            lineas.append("[%d] criterio incompleto (invocacion=%r espera=%r): "
                          "no se pudo ejecutar" % (i, inv, esperados))
            continue
        codigo, salida = teclear(inv, por_criterio)
        if codigo is None:
            fallos += 1
            lineas.append("[%d] %s -> NO SE PUDO EJECUTAR: %s"
                          % (i, inv, str(salida)[:200]))
            continue
        vista = _normalizar(_respuesta_del_repl(salida))
        faltan = [e for e in esperados if _normalizar(e) not in vista]
        if faltan or codigo != 0:
            fallos += 1
            lineas.append("[%d] %s -> FALLA (codigo %s); no aparece %r\n    "
                          "visto: %s"
                          % (i, inv, codigo, faltan, _recortar(vista, 600)))
        else:
            lineas.append("[%d] %s -> OK, contiene %s" % (i, inv, esperados))

    ok = fallos == 0
    detalle = ("%d/%d criterios del duenio cumplidos"
               % (len(criterios) - fallos, len(criterios)))
    return _resultado("criterios", ok, detalle, "\n".join(lineas))


# ── El examen completo ───────────────────────────────────────────────────────

_FASES = {
    "sintaxis": fase_sintaxis,
    "guardianes": fase_guardianes,
    "tests": fase_tests,
    "invocacion": fase_invocacion,
    "criterios": fase_criterios,
}


def _sin_examen(fase: str, motivo: str) -> dict:
    return _resultado(fase, False, "NO SE PUDO EJECUTAR: %s" % motivo, "")


def evaluar(espec, ruta_tests: str = "", orch=None, timeout: float = 900,
            fases=None, reloj=None) -> dict:
    """Examen completo. {'veredicto','fases','evidencia','motivo'}.

    `veredicto` es 'aprobada' solo si LAS CINCO fases devolvieron ok=True.
    Se deriva de lo ejecutado y de nada mas: `orch`, si se pasa, solo REDACTA
    la frase del motivo -- no vota.

    `timeout` es el presupuesto TOTAL, no el de cada fase. Cuando se agota, las
    fases que quedan se marcan ok=False con el motivo, porque no examinarlas no
    puede valer lo mismo que aprobarlas.

    `fases` inyecta ejecutores en los tests: {nombre: callable(plazo) -> dict}.
    Que el evaluador acepte por parametro sus propios ejecutores es lo que lo
    hace testeable sin arrancar cuatro subprocesos por assert.
    `reloj` es la fuente de tiempo (por defecto time.monotonic), inyectable
    para poder comprobar el reparto del presupuesto sin esperar 15 minutos.
    """
    reloj = reloj or time.monotonic
    fases = dict(fases or {})
    arranque = reloj()
    resultados, evidencia = [], []
    cortado = ""

    for nombre in ORDEN:
        gastado = reloj() - arranque
        restante = timeout - gastado
        if cortado:
            r = _sin_examen(nombre, "la fase '%s' invalida el examen" % cortado)
        elif restante <= 0:
            r = _sin_examen(nombre,
                            "presupuesto de tiempo agotado (%ds de %ds)"
                            % (int(gastado), int(timeout)))
        else:
            plazo = min(TOPES[nombre], restante)
            funcion = fases.get(nombre)
            try:
                if funcion is not None:
                    r = funcion(plazo)
                elif nombre == "tests":
                    r = fase_tests(ruta_tests, plazo, espec=espec)
                else:
                    r = _FASES[nombre](espec, plazo)
            except Exception as exc:              # nunca en silencio
                _log.error("la fase %s reviento: %s", nombre, exc)
                r = _sin_examen(nombre, "%s: %s" % (type(exc).__name__, exc))
            if not isinstance(r, dict):
                r = _sin_examen(nombre, "el ejecutor devolvio %r" % type(r))
            r.setdefault("fase", nombre)
            r.setdefault("ok", False)
            r.setdefault("detalle", "")
            r.setdefault("salida", "")
        resultados.append(r)
        evidencia.append("FASE %s: %s -- %s"
                         % (nombre, "OK" if r.get("ok") else "FALLA",
                            r.get("detalle", "")))
        if not r.get("ok") and nombre in BLOQUEANTES and not cortado:
            cortado = nombre

    fallidas = [r["fase"] for r in resultados if not r.get("ok")]
    veredicto = "aprobada" if not fallidas else "rechazada"
    motivo = _motivo_base(veredicto, resultados, fallidas)
    evidencia.append("VEREDICTO: %s" % veredicto)
    evidencia.append("MOTIVO (derivado de las fases): %s" % motivo)

    redactado = _redactar_motivo(orch, veredicto, resultados, motivo)
    if redactado:
        motivo = redactado

    return {"veredicto": veredicto, "fases": resultados,
            "evidencia": evidencia, "motivo": motivo}


def _motivo_base(veredicto: str, resultados: list, fallidas: list) -> str:
    """El motivo DETERMINISTA. Existe siempre, aunque no haya modelo."""
    if veredicto == "aprobada":
        return ("aprobada: las 5 fases ejecutaron y salieron en verde (%s)"
                % "; ".join(r.get("detalle", "") for r in resultados))
    detalles = [r.get("detalle", "") for r in resultados
                if not r.get("ok") and r.get("detalle")]
    return ("rechazada por %s: %s"
            % (", ".join(fallidas), " | ".join(detalles)[:600]))


def _redactar_motivo(orch, veredicto: str, resultados: list, base: str) -> str:
    """El modelo REDACTA la frase; jamas decide. Devuelve '' si no sirve.

    Presupuesto corto a proposito y medido el 2026-08-30: este razonador con
    max_tokens grande se va a razonar y NO EMITE NADA (52.535 caracteres de
    pensamiento y cero salida con 20.000 tokens). Con 120 tokens y una tarea
    de una frase o contesta o degrada, y degradar aqui no cuesta nada porque
    el motivo determinista ya esta calculado.
    """
    if orch is None:
        return ""
    resumen = "; ".join("%s=%s" % (r.get("fase"), "ok" if r.get("ok") else "falla")
                        for r in resultados)
    prompt = ("Veredicto ya decidido: %s. Fases: %s.\n"
              "Escribe UNA frase de menos de 25 palabras, en espaniol sin "
              "acentos, diciendole al duenio por que.\nFrase:" % (veredicto, resumen))
    try:
        r = orch.infer(prompt, max_tokens=120, temperature=0.2)
        texto = (getattr(r, "text", "") or "").strip()
    except Exception as exc:                       # nunca en silencio
        _log.warning("el modelo no pudo redactar el motivo (%s); queda el "
                     "motivo determinista", exc)
        return ""
    texto = _RE_THINK.sub("", texto).strip()
    # Si volvio vacio (se fue a razonar) o desbordado, se queda el base: el
    # camino de degradacion es obligatorio, no un extra.
    if not texto or len(texto) > 400:
        _log.warning("motivo redactado inservible (%d caracteres); queda el "
                     "motivo determinista", len(texto))
        return ""
    return "%s [%s]" % (texto.splitlines()[0].strip(), base[:200])


def estado() -> dict:
    """Puerta de diagnostico: que examen aplicaria el evaluador ahora mismo."""
    return {
        "fases": list(ORDEN),
        "bloqueantes": list(BLOQUEANTES),
        "topes_segundos": dict(TOPES),
        "guardianes": list(rec.GUARDIANES),
        "tocables": list(TOCABLES),
        "interprete": sys.executable,
    }
