# -*- coding: utf-8 -*-
"""Revision profunda antes de ENTREGAR: el arnes CORRE el producto, no lo opina.

QUE RESUELVE
    El cierre caro de un trabajo COMPLEJO es el que suena bien y no se probo. El repo ya
    tiene la compuerta de POLITICA (`cognia/hermes/parada_verificada.py`: "editaste codigo
    y no hay evidencia fresca, andate a verificar") y tiene el MUSCULO de probar de punta a
    punta (`cognia/autoprueba.py`: compila -> importa -> ARRANCA con guion de teclado y
    brazo B -> sin_stubs; y para una pagina, navegador real + contrato de clics). Lo que no
    habia era el lazo que los une EN EL TURNO: nadie corria el producto recien construido
    antes de que el agente dijera "listo".

    Este modulo es ese lazo. Cuando el turno produjo un trabajo COMPLEJO, antes de entregar:
      1. SINTAXIS  -- compila() / json.loads de todo lo escrito (barato, siempre).
      2. TESTS     -- el comando canonico del proyecto sobre los tests que CUBREN lo tocado
                      (`parada_verificada.plan_verificacion` decide cual; no "corre la suite").
      3. PRODUCTO  -- de punta a punta: se ARRANCA lo construido de verdad
                      (`autoprueba.probar_producto`), con teclado guionado y brazo B, o se
                      ABRE la pagina en un navegador real y se le pasa el contrato de clics.
    Si algo falla, el fallo REAL (traceback, exit code, cola de pytest, errores de JS) vuelve
    al modelo como turno de usuario para que lo repare, con un tope de rondas. Si tras las
    rondas sigue roto, se ENTREGA IGUAL con un footer que lo dice: nunca se traga el fallo y
    nunca se secuestra el trabajo hecho.

POR QUE EJECUTA Y NO OPINA (la linea que este repo no cruza)
    `cognia/agent/candidates.py:14` lo deja escrito: la autocritica ciega como juez esta
    PROHIBIDA por diseno, y `agent/lazo_chat.py:14` lo repite -- "el critico EJECUTA, jamas
    opina". Auto-corregirse sin verificador externo EMPEORA el resultado (Huang et al., ICLR
    2024, arXiv:2310.01798). Por eso aca no hay una sola llamada al modelo: cada veredicto
    de este modulo sale de un proceso que corrio y de un exit code que se leyo. Lo unico que
    se le manda al modelo es la EVIDENCIA.

LO QUE NO HACE (limites declarados, no deuda escondida)
    - No inventa tests. Si lo editado no tiene test que lo cubra, la fase TESTS queda en
      `ok=None` y el informe NOMBRA el test que falta. Ausencia de examen no es aprobado.
    - No arranca cualquier cosa. Solo corre un artefacto ARRANCABLE de verdad entre lo que
      se escribio en ESTE turno (ver `artefacto_ejecutable`): un fichero dentro de un paquete
      (con `__init__.py` al lado) se IMPORTA, no se ejecuta, y lanzarlo seria arrancar el
      programa entero del usuario por haber tocado un modulo suyo.
    - No es un sandbox. Corre el producto con HOME/TEMP redirigidos a un temporal
      (`autoprueba._entorno_subproceso`) pero con los permisos del usuario, igual que
      /autoprueba. Es la misma decision, con el mismo limite.
    - No juzga la CALIDAD del contenido (si el informe dice la verdad, si el diseno es
      bonito). Juzga que EXISTA, que compile, que sus tests pasen y que al usarlo no reviente.

POR QUE SOLO EN TRABAJOS COMPLEJOS
    Memoria de esta casa: "un gate que no deja hacer nada acaba apagado". Correr pytest y
    arrancar un proceso tras cada `escribir_archivo` de dos lineas convierte cada turno en
    una espera y la primera reaccion del dueno es apagarlo entero. `es_compleja()` es el
    filtro, con umbrales configurables y una respuesta HONESTA cuando decide no correr (el
    informe dice `motivo`, no se queda mudo).

CONTRATO
    Ninguna publica lanza NUNCA: una compuerta que revienta mata el turno que venia a
    proteger. Todas devuelven un valor tambien en el peor caso, y el `motivo` dice por que.
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

# Nombre del subsistema para _aviso_degradado y para el render.
VIA = "revision"

# Tope de rondas de reparacion. 2 y no 3 por el mismo motivo que MAX_NUDGES de
# parada_verificada (Aider: max_reflections=3, OpenHands: action_error=3) y por la leccion
# medida del repo: "el lazo restaba" cuando el sello es al azar. Aca el sello NO es al azar
# (es un exit code), asi que las rondas se justifican, pero se acotan igual: a la tercera
# vuelta con el mismo sintoma el disyuntor de reparacion ya dice que se esta adivinando.
MAX_RONDAS = 2

# Umbrales del filtro de complejidad (env los pisa; ver es_compleja).
UMBRAL_FICHEROS = 2      # 2 ficheros verificables tocados ya es un trabajo, no un retoque
UMBRAL_LINEAS = 80       # o un solo fichero con cuerpo de verdad
UMBRAL_PASOS = 10        # o una tarea que costo muchos pasos aunque escribiera poco

# Presupuesto de PARED de la revision entera, en segundos. Se comprueba ENTRE fases (no
# puede interrumpir un subproceso ya lanzado: cada fase trae su propio timeout). Una
# revision que tarda mas que la tarea es una revision que se apaga.
PRESUPUESTO_S = 180

TIMEOUT_TESTS_S = 150

# Cuanta evidencia entra en el nudge. Mas que esto y el modelo lee un volcado en vez de un
# fallo (_MAX_CHANGED_PATHS_IN_NUDGE=8 en Hermes, por el mismo motivo).
MAX_FICHEROS_NUDGE = 8
MAX_CHARS_EVIDENCIA = 1400

_RE_MAIN_GUARD = re.compile(r"""if\s+__name__\s*==\s*['"]__main__['"]""")

# Ficheros que se ARRANCAN por convencion aunque no traigan guarda __main__.
_POR_CONVENCION_PY = ("main.py", "app.py", "run.py", "juego.py", "game.py", "programa.py")
_POR_CONVENCION_HTML = ("index.html",)

# Ultimo informe de la sesion, para la puerta `/revision` (estado e informe). En RAM del
# proceso a proposito: es diagnostico del turno, no un almacen.
_ULTIMO: dict = {}


# -- Mandos -------------------------------------------------------------------

def _env(nombre: str, default: str = "") -> str:
    return (os.environ.get(nombre, "") or "").strip()


def _apagado(valor: str) -> bool:
    return valor.lower() in ("0", "off", "false", "no")


def _entero(nombre: str, default: int) -> int:
    try:
        n = int(float(_env(nombre) or default))
        return n if n >= 0 else default
    except (TypeError, ValueError):
        return default


def activa() -> bool:
    """La compuerta entera. `COGNIA_REVISION=0` la apaga (el CLI siembra la config aca)."""
    return not _apagado(_env("COGNIA_REVISION", "1") or "1")


def max_rondas() -> int:
    """Rondas de reparacion permitidas. 0 = revisar y REPORTAR sin pedir arreglos."""
    return min(_entero("COGNIA_REVISION_RONDAS", MAX_RONDAS), 5)


def ejecutar_producto_activo() -> bool:
    """La fase de punta a punta (arrancar el producto). `COGNIA_REVISION_EJECUTAR=0` la apaga
    y deja vivas sintaxis y tests: el que no quiera que se lance su script tiene un mando,
    en vez de apagar la revision entera."""
    return not _apagado(_env("COGNIA_REVISION_EJECUTAR", "1") or "1")


def presupuesto_s() -> int:
    return max(10, _entero("COGNIA_REVISION_SEGUNDOS", PRESUPUESTO_S))


def umbrales() -> dict:
    return {
        "ficheros": max(1, _entero("COGNIA_REVISION_FICHEROS", UMBRAL_FICHEROS)),
        "lineas": max(1, _entero("COGNIA_REVISION_LINEAS", UMBRAL_LINEAS)),
        "pasos": max(1, _entero("COGNIA_REVISION_PASOS", UMBRAL_PASOS)),
    }


def mandos() -> dict:
    """Todos los mandos resueltos, para `/revision estado` (y para que un test los fije)."""
    d = {"activa": activa(), "rondas": max_rondas(),
         "ejecutar_producto": ejecutar_producto_activo(),
         "presupuesto_s": presupuesto_s()}
    d.update(umbrales())
    return d


# -- Lectura de disco (nunca lanza) -------------------------------------------

def _leer(ruta) -> str:
    try:
        return Path(ruta).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _lineas_utiles(texto: str) -> int:
    return sum(1 for l in texto.splitlines()
               if l.strip() and not l.strip().startswith("#"))


def _existentes(rutas) -> list:
    """Las rutas que EXISTEN en disco, absolutas y sin repetir. El registro de mutaciones
    trae intentos; lo borrado o lo que nunca llego a escribirse no se revisa."""
    vistas, out = set(), []
    for r in (rutas or []):
        try:
            p = Path(str(r)).expanduser()
            if not p.is_absolute():
                p = (Path.cwd() / p)
            p = p.resolve()
        except (OSError, ValueError):
            continue
        clave = str(p).lower()
        if clave in vistas:
            continue
        vistas.add(clave)
        try:
            if p.is_file():
                out.append(str(p))
        except OSError:
            continue
    return out


def _en_paquete(p: Path) -> bool:
    """True si el fichero vive dentro de un paquete Python (hay `__init__.py` al lado).

    Un modulo de paquete se IMPORTA; ejecutarlo suelto arranca el programa entero del
    usuario (tocar `cognia/cli.py` no puede significar "lanzame el REPL") y ademas suele
    reventar por imports relativos. Este es el filtro que hace que la fase de punta a punta
    sea segura de encender por defecto."""
    try:
        return (p.parent / "__init__.py").is_file()
    except OSError:
        return False


def _es_test(p: Path) -> bool:
    n = p.name.lower()
    return n.startswith("test_") or n.endswith("_test.py") or "tests" in p.parts


# -- Complejidad --------------------------------------------------------------

def es_compleja(ficheros, pasos: int = 0) -> dict:
    """Decide si el trabajo merece la revision profunda. Devuelve las SENALES, no solo el si.

    Compleja si CUALQUIERA de estas es cierta (son disyuncion a proposito: un solo fichero
    de 400 lineas es tan complejo como cuatro de 20):
        - se escribieron >= `ficheros` ficheros verificables,
        - o el total de lineas utiles escritas llega a `lineas`,
        - o hay un artefacto ARRANCABLE entre lo escrito (algo que se puede usar),
        - o la tarea costo >= `pasos` pasos del agente.
    """
    u = umbrales()
    senales = {"ficheros": 0, "lineas": 0, "pasos": int(pasos or 0),
               "arrancable": "", "umbrales": u}
    try:
        from cognia.hermes.parada_verificada import filtrar_verificables
        codigo = filtrar_verificables(ficheros)
    except Exception:
        # Sin el filtro de prosa (import roto) se sigue con todo: la revision de mas
        # cuesta segundos; la de menos cuesta un cierre que miente.
        codigo = list(ficheros or [])
    codigo = _existentes(codigo)
    senales["ficheros"] = len(codigo)
    senales["lineas"] = sum(_lineas_utiles(_leer(f)) for f in codigo)
    art = artefacto_ejecutable(codigo)
    senales["arrancable"] = (art or {}).get("entrypoint", "") or ""

    if not codigo:
        return {"compleja": False, "motivo": "sin_codigo_escrito",
                "senales": senales, "ficheros": []}
    razones = []
    if senales["ficheros"] >= u["ficheros"]:
        razones.append(f"{senales['ficheros']} ficheros de codigo")
    if senales["lineas"] >= u["lineas"]:
        razones.append(f"{senales['lineas']} lineas utiles")
    if senales["arrancable"]:
        razones.append("hay un artefacto arrancable")
    if senales["pasos"] >= u["pasos"]:
        razones.append(f"{senales['pasos']} pasos")
    if not razones:
        return {"compleja": False, "motivo": "trabajo_simple",
                "senales": senales, "ficheros": codigo}
    return {"compleja": True, "motivo": " · ".join(razones),
            "senales": senales, "ficheros": codigo}


# -- El artefacto que se puede USAR -------------------------------------------

def artefacto_ejecutable(ficheros) -> "dict | None":
    """El producto ARRANCABLE que hay entre `ficheros`, con la forma de `prod` que espera
    `autoprueba.probar_producto`. None si no hay ninguno.

    Reglas (conservadoras a proposito; ver `_en_paquete`):
      HTML  -- cualquier .html suelto; gana `index.html`.
      PY    -- .py que NO sea test, NO viva en un paquete y que ademas o se llame como los
               arrancables por convencion o traiga guarda `__main__`.
    Con varios candidatos manda el mas "entrypoint" y su carpeta es el directorio del
    producto: los demas .py de esa carpeta escritos en el turno viajan como `archivos_py`
    para que la fase `compila` los mire a todos.
    """
    try:
        rutas = [Path(f) for f in _existentes(ficheros)]
    except Exception:
        return None
    if not rutas:
        return None

    htmls = [p for p in rutas if p.suffix.lower() in (".html", ".htm")
             and not _en_paquete(p)]
    if htmls:
        elegido = next((p for p in htmls if p.name.lower() in _POR_CONVENCION_HTML), htmls[0])
        return {"id": elegido.stem, "title": elegido.stem.replace("_", " "),
                "description": "", "directorio": str(elegido.parent), "lenguaje": "html",
                "entrypoint": str(elegido), "archivos_py": []}

    pys = [p for p in rutas if p.suffix.lower() == ".py"
           and not _es_test(p) and not _en_paquete(p)]
    if not pys:
        return None
    por_nombre = [p for p in pys if p.name.lower() in _POR_CONVENCION_PY]
    con_guarda = [p for p in pys if _RE_MAIN_GUARD.search(_leer(p))]
    elegido = (por_nombre[0] if por_nombre
               else con_guarda[0] if con_guarda
               else None)
    if elegido is None:
        return None
    carpeta = elegido.parent
    hermanos = [str(p) for p in pys if p.parent == carpeta]
    return {"id": elegido.stem, "title": elegido.stem.replace("_", " "),
            "description": "", "directorio": str(carpeta), "lenguaje": "python",
            "entrypoint": str(elegido), "archivos_py": hermanos or [str(elegido)]}


# -- Fases --------------------------------------------------------------------

def fase_sintaxis(ficheros) -> dict:
    """compile() de cada .py y json.loads de cada .json escrito. Reusa
    `harness.verificacion.verificar_sintaxis` (misma regla y mismos mensajes que el
    verificador de despues-de-editar; una segunda implementacion se desincronizaria)."""
    try:
        from cognia.harness.verificacion import verificar_sintaxis
    except Exception as exc:
        return {"ok": None, "detalle": f"no evaluada (verificacion no importable: {exc})",
                "errores": [], "revisados": 0}
    errores, revisados = [], 0
    for f in ficheros:
        p = Path(f)
        if p.suffix.lower() not in (".py", ".pyi", ".json"):
            continue
        revisados += 1
        try:
            ok, mensaje = verificar_sintaxis(p, _leer(p))
        except Exception as exc:               # el verificador no puede tumbar la revision
            ok, mensaje = True, f"no evaluable ({type(exc).__name__})"
        if not ok:
            errores.append(f"{p.name}: {mensaje}")
    if revisados == 0:
        return {"ok": None, "detalle": "no evaluada (nada con sintaxis verificable)",
                "errores": [], "revisados": 0}
    return {"ok": not errores, "revisados": revisados, "errores": errores,
            "detalle": (f"{revisados - len(errores)}/{revisados} ficheros parsean"
                        + (f" | {errores[0]}" if errores else ""))}


def fase_tests(ficheros, raiz=None) -> dict:
    """Corre los tests que CUBREN lo editado, con el comando canonico del proyecto.

    `plan_verificacion` decide que correr (y si no hay test que cubra lo tocado, NOMBRA el
    que falta en vez de mandar a correr la suite entera, que es "verifica tu trabajo" con
    otro nombre). Un exito se REGISTRA en el ledger de `parada_verificada`, asi la compuerta
    de politica que corre justo despues ve evidencia fresca y no gasta un turno del modelo
    pidiendo lo que este modulo acaba de hacer.
    """
    base = {"ok": None, "detalle": "", "comando": "", "resumen": "",
            "salida": "", "tests": [], "faltan": []}
    try:
        from cognia.hermes.parada_verificada import (
            plan_verificacion, raiz_proyecto, registrar_verificacion)
        from cognia.harness.verificacion import correr_tests
    except Exception as exc:
        base["detalle"] = f"no evaluada (modulos no importables: {exc})"
        return base

    try:
        raiz = raiz_proyecto(raiz or Path.cwd())
        plan = plan_verificacion(ficheros, raiz)
    except Exception as exc:
        base["detalle"] = f"no evaluada (no se pudo planificar: {type(exc).__name__})"
        return base

    base["comando"] = plan.get("comando") or ""
    base["tests"] = list(plan.get("tests_existentes") or [])
    base["faltan"] = list(plan.get("tests_a_crear") or [])

    if not base["tests"]:
        # RESPALDO PARA UN PRODUCTO EN CARPETA SUELTA (medido 2026-08-30).
        # `plan_verificacion` se rinde antes de mirar los ficheros cuando el
        # proyecto no DECLARA ningun comando (sin pytest.ini/pyproject/Makefile
        # devuelve la lista vacia y sale). Eso es correcto para "cual es el
        # comando canonico del proyecto", pero deja sin correr el caso mas comun
        # de un producto recien construido: main.py y test_main.py juntos en una
        # carpeta pelada. En la tarea real de la agenda de contactos el modelo
        # escribio ONCE tests al lado del programa y la revision no ejecuto uno
        # solo. `tests_asociados` es la misma busqueda por convencion que usa el
        # verificador de despues-de-editar, y `correr_tests` lanza pytest con el
        # interprete que corre el agente (no uno del PATH que quiza no lo tenga).
        try:
            from cognia.harness.verificacion import tests_asociados
            hallados = []
            for f in ficheros:
                for t in tests_asociados(f, Path(f).parent):
                    if str(t) not in hallados:
                        hallados.append(str(t))
            if hallados:
                base["tests"] = hallados
                base["comando"] = "pytest (por convencion de nombre, junto al fichero)"
        except Exception as exc:
            base["detalle"] = f"respaldo por convencion no disponible ({type(exc).__name__})"

    if not base["tests"]:
        # Sin test que cubra lo tocado no hay examen que correr. Se DICE cual falta.
        base["detalle"] = (
            "no evaluada: ningun test cubre lo editado"
            + (f" (falta {base['faltan'][0]})" if base["faltan"] else ""))
        return base

    # Desde donde se lanza pytest: la raiz cuando el proyecto la tiene (ahi viven
    # su pytest.ini y su conftest.py), y la carpeta del propio test cuando el
    # producto es una carpeta suelta -- alli `import main` solo resuelve si pytest
    # corre con esa carpeta como base.
    cwd_tests = (str(raiz) if plan.get("comando")
                 else str(Path(base["tests"][0]).parent))
    res = correr_tests(base["tests"], cwd=cwd_tests, timeout=TIMEOUT_TESTS_S)
    base["ok"] = bool(res.get("ok"))
    base["resumen"] = str(res.get("resumen") or "")
    base["salida"] = str(res.get("salida_recortada") or "")
    if res.get("error_harness"):
        # "no se pudo lanzar pytest" NO es un fallo del codigo del modelo: mandarlo a
        # arreglar su fichero por eso seria mandarlo a perseguir un fantasma.
        base["ok"] = None
        base["detalle"] = f"no evaluada (fallo del harness): {base['resumen']}"
        return base
    base["detalle"] = f"{base['resumen']} · {' '.join(base['tests'][:3])}"
    # El ledger de parada_verificada: con esto anotado, la compuerta de POLITICA
    # que corre justo despues ve evidencia FRESCA y no gasta un turno del modelo
    # pidiendo la verificacion que este modulo acaba de hacer. Es una
    # optimizacion, no el veredicto -- pero si se rompe hay que VERLO: la
    # primera version llamaba con `salida=` (el parametro se llama
    # `salida_corta`) y el `except: pass` se comia el TypeError, asi que el
    # ledger no se escribia nunca y nadie se enteraba. El fallo tipico de esta
    # casa es el vacio silencioso.
    try:
        registrar_verificacion(str(raiz), f"pytest {' '.join(base['tests'][:3])}",
                               bool(base["ok"]), salida_corta=base["resumen"])
    except Exception as exc:
        base["detalle"] += f" (no se pudo anotar en el ledger: {type(exc).__name__}: {exc})"
    return base


def fase_producto(art, presupuesto_restante_s: float) -> dict:
    """DE PUNTA A PUNTA: se arranca lo construido y se mira que hace.

    Delega entero en `autoprueba.probar_producto`, que es el motor ya medido de esta casa:
    para Python compila -> importa en subproceso aislado -> ARRANCA con guion de teclado
    derivado de sus propios `input()` y con BRAZO B (el mismo arranque con otros valores,
    para saber si el producto USA lo que se le teclea) -> sin_stubs; para HTML abre la
    pagina en un navegador real, recoge los errores de JS y le pasa el contrato de clics.
    """
    base = {"ok": None, "detalle": "", "entrypoint": "", "lenguaje": "",
            "fases": {}, "fallo_duro": None, "indeterminado": None}
    if art is None:
        base["detalle"] = ("no evaluada: no hay artefacto arrancable entre lo escrito "
                           "(modulos de paquete y tests no se lanzan sueltos)")
        return base
    if not ejecutar_producto_activo():
        base["detalle"] = "no evaluada (apagada: /revision ejecutar off)"
        return base
    if presupuesto_restante_s <= 0:
        base["detalle"] = "no evaluada (presupuesto de pared agotado antes de arrancar)"
        return base
    try:
        from cognia import autoprueba as _ap
    except Exception as exc:
        base["detalle"] = f"no evaluada (autoprueba no importable: {exc})"
        return base

    base["entrypoint"] = art.get("entrypoint") or ""
    base["lenguaje"] = art.get("lenguaje") or ""
    try:
        res = _ap.probar_producto(art)
    except Exception as exc:
        # autoprueba declara que no lanza; si lo hiciera, esto NO puede reprobar al
        # producto (seria condenar por un fallo del instrumento).
        base["detalle"] = f"no evaluada (la prueba revento: {type(exc).__name__}: {exc})"
        return base

    base["fases"] = res.get("fases") or {}
    base["fallo_duro"] = res.get("fallo_duro")
    base["indeterminado"] = res.get("indeterminado")
    arranca = base["fases"].get("arranca") or {}
    if base["fallo_duro"]:
        fallo = base["fases"].get(base["fallo_duro"]) or {}
        base["ok"] = False
        base["detalle"] = f"{base['fallo_duro']}: {fallo.get('detalle') or 'sin detalle'}"
    elif base["indeterminado"]:
        base["ok"] = None
        base["detalle"] = f"indeterminado en {base['indeterminado']}: {arranca.get('detalle', '')}"
    else:
        base["ok"] = True
        base["detalle"] = arranca.get("detalle") or "arranca"
    return base


# -- La revision --------------------------------------------------------------

def revisar(estado) -> dict:
    """Corre la revision profunda y devuelve el informe. NUNCA lanza.

    `estado` (dict, todo opcional salvo ficheros_editados):
        ficheros_editados  rutas escritas en el turno (la prosa se filtra aca)
        workspace          raiz del proyecto (default: cwd)
        pasos              pasos que costo la tarea (senal de complejidad)
        rondas_usadas      rondas de reparacion ya gastadas en ESTE turno
        superficie         "cli"/"tui"/"telegram"... (mensajeria apaga la compuerta)
        on_evento          callable(str) para narrar el avance en el REPL

    Informe: {corrida, ok, motivo, compleja, senales, ficheros, fases, fallos, nudge,
              footer, segundos, rondas_usadas}
    `ok` es True (todo lo evaluable paso), False (algo fallo) o None (no se pudo evaluar
    nada): son tres estados distintos y se mantienen distintos.
    """
    t0 = time.time()
    inf = {"corrida": False, "ok": None, "motivo": "", "compleja": False,
           "senales": {}, "ficheros": [], "fases": {}, "fallos": [],
           "nudge": None, "footer": "", "segundos": 0.0,
           "rondas_usadas": 0, "artefacto": ""}
    try:
        estado = estado if isinstance(estado, dict) else {}
        avisar = estado.get("on_evento")
        if not callable(avisar):
            def avisar(_m):     # noqa: E306  (callback opcional: no-op silencioso)
                return None

        try:
            inf["rondas_usadas"] = int(estado.get("rondas_usadas") or 0)
        except (TypeError, ValueError):
            inf["rondas_usadas"] = 0

        if not activa():
            inf["motivo"] = "apagada"
            return _sellar(inf, t0)

        try:
            from cognia.hermes.parada_verificada import compuerta_activa
            if not compuerta_activa(estado.get("superficie")):
                inf["motivo"] = "superficie_silenciosa"
                return _sellar(inf, t0)
        except Exception:
            pass    # sin el filtro de superficie se revisa igual

        veredicto = es_compleja(estado.get("ficheros_editados"),
                                estado.get("pasos") or 0)
        inf["compleja"] = bool(veredicto.get("compleja"))
        inf["senales"] = veredicto.get("senales") or {}
        inf["ficheros"] = list(veredicto.get("ficheros") or [])
        if not inf["compleja"]:
            inf["motivo"] = veredicto.get("motivo") or "trabajo_simple"
            return _sellar(inf, t0)

        inf["corrida"] = True
        inf["motivo"] = veredicto.get("motivo") or ""
        presupuesto = presupuesto_s()
        raiz = estado.get("workspace") or Path.cwd()

        avisar(f"revision profunda: {len(inf['ficheros'])} fichero(s) — sintaxis")
        inf["fases"]["sintaxis"] = fase_sintaxis(inf["ficheros"])

        restante = presupuesto - (time.time() - t0)
        if restante <= 0:
            inf["fases"]["tests"] = {"ok": None, "detalle": "no evaluada (presupuesto de pared agotado)",
                                     "comando": "", "resumen": "", "salida": "",
                                     "tests": [], "faltan": []}
        else:
            avisar("revision profunda: tests que cubren lo editado")
            inf["fases"]["tests"] = fase_tests(inf["ficheros"], raiz)

        art = artefacto_ejecutable(inf["ficheros"])
        inf["artefacto"] = (art or {}).get("entrypoint", "") or ""
        if art is not None and ejecutar_producto_activo():
            avisar(f"revision profunda: arrancando {Path(inf['artefacto']).name} "
                   f"({art.get('lenguaje')})")
        inf["fases"]["producto"] = fase_producto(art, presupuesto - (time.time() - t0))

        inf["fallos"] = _fallos_de(inf["fases"])
        evaluadas = [f for f in inf["fases"].values() if f.get("ok") is not None]
        inf["ok"] = (None if not evaluadas
                     else not inf["fallos"])
        inf["nudge"] = nudge_de(inf)
        inf["footer"] = footer_de(inf)
        return _sellar(inf, t0)
    except Exception as exc:
        inf["motivo"] = f"error_interno: {type(exc).__name__}: {exc}"
        inf["ok"] = None
        inf["nudge"] = None
        return _sellar(inf, t0)


def _sellar(inf: dict, t0: float) -> dict:
    global _ULTIMO
    inf["segundos"] = round(time.time() - t0, 2)
    if not inf.get("footer"):
        inf["footer"] = footer_de(inf)
    _ULTIMO = inf
    return inf


def ultimo() -> dict:
    """El ultimo informe de la sesion ({} si no hubo ninguno)."""
    return dict(_ULTIMO)


def _fallos_de(fases: dict) -> list:
    """Los fallos DUROS, con su evidencia real. `ok=None` no es fallo: es "no se evaluo"."""
    fallos = []
    sx = fases.get("sintaxis") or {}
    if sx.get("ok") is False:
        fallos.append({"fase": "sintaxis", "detalle": sx.get("detalle") or "",
                       "evidencia": "\n".join(sx.get("errores") or [])})
    tt = fases.get("tests") or {}
    if tt.get("ok") is False:
        fallos.append({"fase": "tests",
                       "detalle": tt.get("resumen") or tt.get("detalle") or "",
                       "evidencia": tt.get("salida") or ""})
    pr = fases.get("producto") or {}
    if pr.get("ok") is False:
        sub = (pr.get("fases") or {}).get(pr.get("fallo_duro") or "") or {}
        ev = "\n".join(x for x in (str(sub.get("stderr") or "").strip(),
                                   str(sub.get("stdout") or "").strip()) if x)
        if not ev:
            ev = "\n".join(sub.get("errores") or [])
        fallos.append({"fase": "producto (de punta a punta)",
                       "detalle": pr.get("detalle") or "", "evidencia": ev})
    return fallos


# -- Lo que lee el modelo, y lo que lee el dueno ------------------------------

def _recortar(texto: str, tope: int = MAX_CHARS_EVIDENCIA) -> str:
    """La COLA de la evidencia: ahi vive el traceback y la linea de resumen."""
    t = (texto or "").strip()
    if len(t) <= tope:
        return t
    return f"[... recortado a {tope} chars, se conserva la cola ...]\n" + t[-tope:]


def _lista_rutas(rutas) -> str:
    out = [f"  - {r}" for r in list(rutas)[:MAX_FICHEROS_NUDGE]]
    resto = len(rutas) - MAX_FICHEROS_NUDGE
    if resto > 0:
        out.append(f"  ... y {resto} mas")
    return "\n".join(out)


def nudge_de(informe: dict) -> "str | None":
    """El turno de usuario que devuelve el fallo REAL al modelo, o None para dejar entregar.

    Es EVIDENCIA, no un sermon: el traceback que salio, el exit code que se leyo, la cola de
    pytest. Y trae la valvula de Hermes: si repararlo es imposible, que lo DIGA concreto en
    vez de declarar la tarea verificada."""
    try:
        if not informe.get("corrida") or not informe.get("fallos"):
            return None
        if int(informe.get("rondas_usadas") or 0) >= max_rondas():
            return None
        bloques = []
        for f in informe["fallos"]:
            ev = _recortar(f.get("evidencia") or "")
            bloques.append(f"[{f['fase']}] {f.get('detalle') or ''}"
                           + (f"\n{ev}" if ev else ""))
        arte = informe.get("artefacto") or ""
        pistas = []
        prod = (informe.get("fases") or {}).get("producto") or {}
        if prod.get("ok") is False and arte:
            pistas.append(f"El producto que se arranco fue `{arte}`. Corrigelo y volve a "
                          f"correrlo vos mismo antes de contestar.")
        tests = (informe.get("fases") or {}).get("tests") or {}
        if tests.get("ok") is False and tests.get("tests"):
            pistas.append("Los tests que fallaron son "
                          f"`{' '.join(tests['tests'][:3])}`: correlos con la tool `tests` "
                          "despues de arreglar.")
        return (
            "[SISTEMA: antes de entregar, el arnes REVISO tu trabajo corriendolo de verdad "
            "(no es una opinion: son procesos que se lanzaron y sus exit codes).\n\n"
            f"Ficheros revisados:\n{_lista_rutas(informe.get('ficheros') or [])}\n\n"
            "FALLA:\n" + "\n\n".join(bloques) + "\n\n"
            + ("\n".join(pistas) + "\n\n" if pistas else "")
            + "Arregla la causa (no el sintoma), volve a correrlo, y recien despues cerra "
            "INCLUYENDO la salida REAL de tu comprobacion.\n"
            "Si arreglarlo es IMPOSIBLE, deci cual es el bloqueo CONCRETO en vez de "
            "entregar esto como si funcionara.]"
        )
    except Exception:
        return None


def _glifo(ok) -> str:
    return "OK" if ok is True else ("FALLA" if ok is False else "sin evaluar")


def footer_de(informe: dict) -> str:
    """Una linea HONESTA para pegar bajo la respuesta final. "" si no hay nada que contar.

    Se pega TAMBIEN cuando pasa: el dueno tiene que poder distinguir "revisado y corre" de
    "nadie lo miro", que es exactamente el par de estados que este repo confunde cuando
    algo se degrada en silencio."""
    try:
        if not informe.get("corrida"):
            return ""
        fases = informe.get("fases") or {}
        partes = []
        sx = fases.get("sintaxis") or {}
        if sx.get("ok") is not None:
            partes.append(f"sintaxis {_glifo(sx.get('ok'))} ({sx.get('revisados', 0)} fich.)")
        tt = fases.get("tests") or {}
        if tt.get("ok") is None:
            if tt.get("faltan"):
                partes.append(f"tests sin evaluar (falta {tt['faltan'][0]})")
        else:
            partes.append(f"tests {_glifo(tt.get('ok'))}: {tt.get('resumen') or ''}".strip())
        pr = fases.get("producto") or {}
        if pr.get("ok") is None:
            partes.append("de punta a punta: " + (pr.get("detalle") or "sin evaluar"))
        else:
            nombre = Path(pr.get("entrypoint") or "producto").name
            partes.append(f"{nombre} {_glifo(pr.get('ok'))}: {pr.get('detalle') or ''}".strip())
        if not partes:
            return ""
        cabecera = ("revision profunda (el arnes lo corrio)"
                    if informe.get("ok") is not False
                    else "revision profunda: QUEDA ROTO tras "
                         f"{informe.get('rondas_usadas', 0)} ronda(s) de reparacion")
        return f"[{cabecera}] " + " · ".join(p for p in partes if p)
    except Exception:
        return ""


def render(informe: dict) -> list:
    """Lineas (con marcado del REPL) para `/revision`. Nunca lanza."""
    try:
        if not informe:
            return ["[info_dim]revision profunda: todavia no corrio en esta sesion[/info_dim]"]
        out = []
        if not informe.get("corrida"):
            out.append(f"[info_dim]no corrio · motivo: {informe.get('motivo') or '-'}"
                       f"[/info_dim]")
            s = informe.get("senales") or {}
            if s:
                out.append(f"[info_dim]  senales: {s.get('ficheros', 0)} fichero(s) · "
                           f"{s.get('lineas', 0)} lineas · {s.get('pasos', 0)} pasos · "
                           f"arrancable: {s.get('arrancable') or 'no'}[/info_dim]")
            return out
        color = ("ok_cl" if informe.get("ok") is True
                 else "err_cl" if informe.get("ok") is False else "warn_cl")
        out.append(f"[{color}]veredicto: {_glifo(informe.get('ok'))}[/{color}]"
                   f" [info_dim]· {informe.get('segundos', 0)} s · disparada por: "
                   f"{informe.get('motivo') or '-'}[/info_dim]")
        for nombre in ("sintaxis", "tests", "producto"):
            f = (informe.get("fases") or {}).get(nombre) or {}
            if not f:
                continue
            c = ("ok_cl" if f.get("ok") is True
                 else "err_cl" if f.get("ok") is False else "warn_cl")
            out.append(f"  [{c}]{nombre}: {_glifo(f.get('ok'))}[/{c}] "
                       f"[info_dim]{(f.get('detalle') or '')[:200]}[/info_dim]")
        for f in (informe.get("fallos") or []):
            ev = (f.get("evidencia") or "").strip().splitlines()
            if ev:
                out.append(f"  [err_cl]  {ev[-1][:200]}[/err_cl]")
        return out
    except Exception as exc:
        return [f"[warn_cl]no se pudo renderizar el informe ({type(exc).__name__})[/warn_cl]"]


__all__ = [
    "VIA", "MAX_RONDAS", "activa", "max_rondas", "ejecutar_producto_activo",
    "presupuesto_s", "umbrales", "mandos", "es_compleja", "artefacto_ejecutable",
    "fase_sintaxis", "fase_tests", "fase_producto", "revisar", "nudge_de",
    "footer_de", "render", "ultimo",
]
