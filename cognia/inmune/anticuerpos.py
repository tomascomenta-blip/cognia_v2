# -*- coding: utf-8 -*-
"""ANTICUERPOS: convierte un fallo confirmado en un CHEQUEO que corre y VETA.

QUE RESUELVE
------------
Hoy todo el aprendizaje de agentes termina en PROSA: las skills auto-capturadas
de este repo, las rules de Cursor, las memorias. Prosa que se inyecta en el
prompt y que el modelo puede ignorar --- y que ademas ENVENENA cuando la traza
de la que salio era mala. Un anticuerpo es lo contrario: un predicado
DETERMINISTA sobre (tool, args, ctx) que corre en cada tool call y devuelve
veto o nada. No hay LLM en ninguna parte de este modulo.

POR QUE EXISTE
--------------
Regla escrita por el dueno de este repo tras varios incidentes
(memoria: "Una leccion en prosa no impide nada"): *convertirla en un chequeo
que corre al arrancar, o se repite*. Y el contraejemplo que fija el diseno
(memoria: "Las skills auto-capturadas ENVENENAN tareas ajenas"): una traza de
atasco ascendida a "procedimiento verificado" sin ninguna compuerta. De ahi que
aqui NADA se active por haber sido sintetizado: `sintetizar` deja el anticuerpo
en CUARENTENA y solo `examinar` --- que exige vetar los casos del fallo Y dejar
pasar una bateria de casos SANOS held-out, con CERO falsos positivos --- lo
pasa a 'activo'.

EVIDENCIA / HUECO DEL CAMPO (2026-08-18)
----------------------------------------
Los harnesses clasifican las acciones por TIPO DE HERRAMIENTA ("permito Bash?")
cuando la pregunta que decide es otra. Un anticuerpo clasifica por
REPRODUCCION DE UN FALLO YA VISTO, que es informacion que el harness ya tiene
tirada en las trayectorias y nadie usa. La entrada natural es el informe de
atribucion causal (replay contrafactual: "el paso i causo el fallo"); este
modulo es el consumidor de ese informe --- y su contrato con el es DUCK-TYPED
a proposito (ver `sintetizar`), para no acoplarse a una estructura que todavia
se esta moviendo.

MEDICION (esta maquina, Windows 11 Pro, venv312, 2026-08-19)
------------------------------------------------------------
Coste de `evaluar` con 50 anticuerpos activos sobre 1000 llamadas, medido con
`scripts/medir_inmune.py` (pegado del guion que corre de verdad, no declarado):

    python 3.12.10 / 50 anticuerpos activos / 1000 llamadas por escenario
    PASA  (recorre los 50 sin cortar) ........  20.24 us/llamada
    VETO  (dispara el ultimo del indice) .....   3.56 us/llamada
    tool SIN anticuerpos (corte rapido) ......   0.25 us/llamada

Presupuesto fijado: ~1000 us (1 ms) por llamada. Peor caso medido: 20.24 us =
0.020 ms, un factor 49 por debajo. SI puede vivir en el camino caliente. El caso
caro es el que NO veta, porque ahi se recorren los 50 candidatos sin cortar; el
caso comun de verdad (una tool a la que no apunta ningun anticuerpo) sale por un
`dict.get` fallido y cuesta 0.25 us.

Primera version medida: 28.22 / 9.32 / 5.95 us. Los 5.95 us del caso trivial
eran construir el `Path` del almacen y parsear el TTL en CADA llamada; el camino
rapido de `_indice()` compara la env var como cadena y no toca `pathlib`. Se deja
escrito porque el numero antes/despues es la unica prueba de que la optimizacion
hacia falta.

API
---
    from cognia.inmune import anticuerpos as ac

    ab = ac.sintetizar(informe_causal, trayectoria)   # dict | None
    ac.registrar(ab)                                  # nace en 'cuarentena'
    ac.examinar(ab, casos_positivos, casos_negativos) # LA COMPUERTA -> activo/no
    veto = ac.evaluar("ejecutar", "git push --force", ctx)   # None | {veto, mensaje}
    ac.registrar_resultado(ab["id"], fue_util=False)  # retiro automatico tras N FP
    ac.activos(); ac.listar(); ac.retirar(id, motivo); ac.recargar()

LIMITES DECLARADOS
------------------
  - `evaluar` FALLA ABIERTO: cualquier excepcion interna devuelve None y la
    llamada pasa. Un sistema inmune que bloquea el agente cuando se rompe es
    peor que no tenerlo (mismo criterio que `cognia/harness/interceptor.py`).
  - `evaluar` NO relee el disco en cada llamada: comprueba el `stat` del almacen
    como mucho una vez cada `COGNIA_INMUNE_TTL` segundos (1.0 por defecto). Un
    proceso AJENO que edite el JSON tarda hasta ese TTL en verse. Los cambios
    hechos por esta misma API se ven al instante.
  - Los cuatro tipos de chequeo son los unicos que hay. Si el fallo no cabe en
    ninguno, `sintetizar` devuelve None: NO se fabrica un anticuerpo de prosa.
  - 'leido_antes' depende de que el integrador rellene `ctx['leidos']`. Si el
    ctx no trae esa clave, el chequeo NO veta (no puede distinguir "no lo leyo"
    de "no me lo contaron"): fallar abierto es la unica lectura honesta.
  - `evaluar` NO persiste el contador de aciertos (seria una escritura a disco
    en el camino caliente). Lo incrementa en memoria; quien quiera contabilidad
    duradera llama a `registrar_resultado(id, fue_util=True)` tras el veto.
  - No hay bloqueo de fichero entre procesos. Dos Cognias escribiendo el almacen
    a la vez pueden perder un anticuerpo (el ultimo `replace` gana). Es un
    almacen de aprendizaje, no un libro mayor.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

# ── Constantes del contrato ───────────────────────────────────────────────────

ESTADOS = ("cuarentena", "activo", "retirado")

TIPOS_CHEQUEO = (
    "precondicion_fichero",
    "patron_args",
    "comando_prohibido",
    "orden_de_pasos",
)

# Cuantos falsos positivos en PRODUCCION retiran un anticuerpo solo. Tres y no
# uno: en produccion el "fue_util=False" lo manda un humano o una heuristica que
# tambien se equivoca, al contrario que en `examinar`, donde los casos sanos son
# held-out elegidos a mano y por eso ahi UNO basta.
MAX_FALSOS_POSITIVOS = 3

# Herramientas cuyo PRIMER campo del protocolo de texto es una ruta. El registry
# (cognia/agent/tools.py) es la fuente de verdad de que existe; esta tabla solo
# dice DONDE esta la ruta, y se mantiene local a proposito para que `evaluar` no
# arrastre el import del registry en el camino caliente.
_RUTA_PRIMERA = {
    "leer_archivo", "escribir_archivo", "editar_archivo", "apendar_archivo",
    "borrar_archivo", "copiar_archivo", "mover_archivo", "crear_directorio",
    "contar_lineas", "py_validar", "json_validar", "deshacer_edicion",
}

# Herramientas que CREAN el fichero: para ellas "la ruta no existe" es lo normal
# y jamas se sintetiza una precondicion 'existe' (seria un veto sobre lo sano).
_CREAN = {"escribir_archivo", "crear_directorio", "copiar_archivo", "mover_archivo"}

# Herramientas que editan un fichero PREEXISTENTE por bloques: son las unicas
# donde "no lo habias leido" es una causa de fallo real (el bloque SEARCH sale
# de la imaginacion del modelo).
_EDITAN = {"editar_archivo", "apendar_archivo"}

# Comandos cuya sola presencia en unos args ya explica un desastre. La lista es
# corta y literal a proposito: cada entrada tiene que poder defenderse sola.
_DESTRUCTIVOS = (
    "git push --force", "git push -f", "git reset --hard", "git clean -fd",
    "rm -rf", "rmdir /s", "del /f", "remove-item -recurse -force",
    "drop table", "drop database", "truncate table",
    "mkfs", "shutdown", "diskpart",
)

# Huellas de error que identifican, sin LLM, "el fichero no estaba".
_ERR_NO_EXISTE = (
    "no such file", "not found", "no existe", "cannot find", "no se encuentra",
    "filenotfounderror", "enoent", "errno 2",
)

# Huellas de error que identifican "editaste a ciegas": el bloque no casaba.
_ERR_NO_CASA = (
    "no se encontro", "no se encontr\u00f3", "search", "no coincide", "no match",
    "no aparece", "bloque",
)


# ── Ubicacion del almacen ─────────────────────────────────────────────────────

def dir_inmune() -> Path:
    """Raiz del almacen; COGNIA_INMUNE_DIR permite override (tests).

    Se lee a CALL-TIME y no al importar: los tests cambian la env var despues de
    que el modulo ya este cargado, y un `Path` congelado en el import los
    mandaria al ~/.cognia del dueno (incidente conocido de este repo con las
    rutas fijadas al importar el modulo).
    """
    override = os.environ.get("COGNIA_INMUNE_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".cognia" / "inmune"


def ruta_almacen() -> Path:
    """El JSON unico donde viven todos los anticuerpos."""
    return dir_inmune() / "anticuerpos.json"


def _ttl() -> float:
    """Segundos entre dos `stat` del almacen vistos desde el camino caliente."""
    try:
        return max(0.0, float(os.environ.get("COGNIA_INMUNE_TTL", "1.0")))
    except Exception:
        return 1.0


def _max_fp() -> int:
    try:
        return max(1, int(os.environ.get("COGNIA_INMUNE_MAX_FP",
                                         str(MAX_FALSOS_POSITIVOS))))
    except Exception:
        return MAX_FALSOS_POSITIVOS


# ── Estado en memoria ─────────────────────────────────────────────────────────
#
# `datos` es la lista completa; `indice` es {tool -> [anticuerpos activos]} con
# '*' para los que aplican a cualquier herramienta. `firma` es (mtime_ns, size)
# del JSON: si no cambia, no hay nada que releer.

_ESTADO = {
    "ruta": None,     # str de la ruta con la que se cargo
    "env": None,      # valor CRUDO de COGNIA_INMUNE_DIR con el que se cargo
    "firma": None,    # (mtime_ns, size) o None si el fichero no existe
    "datos": None,    # list[dict] o None si nunca se cargo
    "indice": None,   # dict[str, list[dict]]
    "visto": 0.0,     # time.monotonic() del ultimo stat
    "ttl": 1.0,       # copia del TTL resuelto, para no reparsear en caliente
}

# Regex compiladas, cacheadas por patron. Compilar es lo caro; casar no lo es.
_RE_CACHE: dict = {}


def _firma_disco(ruta: Path):
    try:
        st = ruta.stat()
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def recargar() -> list:
    """Fuerza una relectura del almacen desde disco. Devuelve los anticuerpos.

    Es lo que llama un test (o un proceso que sabe que otro escribio) para no
    esperar al TTL. Tambien es lo que hace que "otra instancia" del sistema vea
    lo que persistio la anterior sin reiniciar el proceso.
    """
    _ESTADO["ruta"] = None
    _ESTADO["env"] = None
    _ESTADO["firma"] = None
    _ESTADO["datos"] = None
    _ESTADO["indice"] = None
    _ESTADO["visto"] = 0.0
    return _cargar()


def _cargar() -> list:
    """La lista de anticuerpos, releyendo el JSON solo si el `stat` cambio.

    Nunca lanza: un JSON corrupto degrada a lista vacia (y el agente sigue).
    """
    env = os.environ.get("COGNIA_INMUNE_DIR", "")
    ahora = time.monotonic()
    if (_ESTADO["datos"] is not None
            and _ESTADO["env"] == env
            and (ahora - _ESTADO["visto"]) < _ESTADO["ttl"]):
        return _ESTADO["datos"]

    ruta = ruta_almacen()
    sruta = str(ruta)
    firma = _firma_disco(ruta)
    _ESTADO["visto"] = ahora
    _ESTADO["ttl"] = _ttl()
    if (_ESTADO["datos"] is not None and _ESTADO["ruta"] == sruta
            and firma == _ESTADO["firma"]):
        _ESTADO["env"] = env
        return _ESTADO["datos"]

    datos = []
    try:
        cargado = json.loads(ruta.read_text(encoding="utf-8"))
        if isinstance(cargado, dict):
            cargado = cargado.get("anticuerpos") or []
        if isinstance(cargado, list):
            datos = [a for a in cargado if isinstance(a, dict) and a.get("id")]
    except Exception:
        datos = []

    _ESTADO["ruta"] = sruta
    _ESTADO["env"] = env
    _ESTADO["firma"] = firma
    _ESTADO["datos"] = datos
    _ESTADO["indice"] = _construir_indice(datos)
    return datos


def _construir_indice(datos: list) -> dict:
    """{tool -> [activos]}. Indexar por tool es lo que hace que `evaluar` no
    recorra el almacen entero: la inmensa mayoria de tool calls no tiene ni un
    anticuerpo apuntandole y sale por un `dict.get` que falla."""
    idx: dict = {}
    for ab in datos:
        if ab.get("estado") != "activo":
            continue
        try:
            tool = (ab.get("disparador") or {}).get("tool") or "*"
        except Exception:
            tool = "*"
        idx.setdefault(str(tool), []).append(ab)
    return idx


def _indice() -> dict:
    """El indice de activos. Camino RAPIDO primero: mientras el TTL no venza y
    la env var no cambie, no se construye ni un `Path` ni se parsea un float
    (medido: construir el Path del almacen costaba ~4 us de los ~6 us que valia
    una llamada que no vetaba nada)."""
    if (_ESTADO["datos"] is not None
            and _ESTADO["env"] == os.environ.get("COGNIA_INMUNE_DIR", "")
            and (time.monotonic() - _ESTADO["visto"]) < _ESTADO["ttl"]):
        return _ESTADO["indice"] or {}
    _cargar()
    return _ESTADO["indice"] or {}


def _guardar(datos: list) -> None:
    """Escribe el almacen entero (tmp + replace) y refresca la cache en memoria."""
    ruta = ruta_almacen()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_name(ruta.name + ".tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(str(tmp), str(ruta))
    _ESTADO["ruta"] = str(ruta)
    _ESTADO["env"] = os.environ.get("COGNIA_INMUNE_DIR", "")
    _ESTADO["firma"] = _firma_disco(ruta)
    _ESTADO["datos"] = datos
    _ESTADO["indice"] = _construir_indice(datos)
    _ESTADO["visto"] = time.monotonic()
    _ESTADO["ttl"] = _ttl()


# ── Utilidades deterministas ──────────────────────────────────────────────────

def _ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _rx(patron: str):
    """Regex compilada e insensible a mayusculas, cacheada. None si no compila."""
    r = _RE_CACHE.get(patron)
    if r is None:
        try:
            r = re.compile(patron, re.IGNORECASE)
        except Exception:
            r = False
        _RE_CACHE[patron] = r
    return r or None


def ruta_de_args(nombre_tool: str, args: str) -> str:
    """La ruta que estos args nombran, o '' si esta tool no lleva ruta delante.

    Mismo protocolo que `cognia/harness/interceptor.py:ruta_destino`: la ruta va
    primera y '|' separa el resto. Se replica aqui (y no se importa) para que el
    camino caliente no arrastre el import del arnes entero.
    """
    if nombre_tool not in _RUTA_PRIMERA or not args:
        return ""
    return args.split("|", 1)[0].strip().strip('"').strip("'")


def _norm_ruta(p: str) -> str:
    """Clave comparable de una ruta en Windows: separadores y caja unificados.

    Sin `normcase` un anticuerpo sintetizado sobre 'C:/x/A.py' no reconoceria
    'c:\\x\\a.py', que en NTFS es EL MISMO FICHERO.
    """
    try:
        return os.path.normcase(os.path.normpath(str(p).strip().strip('"').strip("'")))
    except Exception:
        return str(p)


def _leidos(ctx: dict) -> set:
    crudo = ctx.get("leidos") or ctx.get("ficheros_leidos") or ()
    try:
        return {_norm_ruta(x) for x in crudo}
    except Exception:
        return set()


def _historial(ctx: dict) -> list:
    """Los nombres de tool ya usados, en orden. Acepta lista de str o de dicts."""
    crudo = ctx.get("historial") or ctx.get("pasos") or ()
    out = []
    try:
        for p in crudo:
            if isinstance(p, dict):
                n = _tool_de(p)
                if n:
                    out.append(str(n))
            elif p:
                out.append(str(p))
    except Exception:
        return []
    return out


def _tokens_en_orden(aguja: str, pajar: str) -> bool:
    """True si todos los tokens de `aguja` aparecen en `pajar` en ese orden.

    Asi `git push --force` casa tanto `git push --force origin main` como
    `git push origin main --force`, que es el MISMO desastre escrito distinto;
    una comparacion de subcadena solo cazaria el primero.
    """
    pos = 0
    for t in aguja.split():
        i = pajar.find(t, pos)
        if i < 0:
            return False
        pos = i + len(t)
    return True


# ── LOS CUATRO CHEQUEOS ───────────────────────────────────────────────────────

def _chequea(chequeo: dict, nombre_tool: str, args: str, ctx: dict) -> bool:
    """True = VETAR. Determinista, sin red y sin LLM; solo toca disco cuando el
    chequeo es una precondicion de existencia (un `os.path.exists`)."""
    tipo = chequeo.get("tipo")

    if tipo == "patron_args":
        rx = _rx(str(chequeo.get("patron") or ""))
        return bool(rx and rx.search(args))

    if tipo == "comando_prohibido":
        bajos = args.lower()
        cmds = chequeo.get("comandos") or [chequeo.get("comando") or ""]
        for c in cmds:
            c = str(c or "").strip().lower()
            if c and _tokens_en_orden(c, bajos):
                return True
        return False

    if tipo == "precondicion_fichero":
        ruta = chequeo.get("ruta") or ruta_de_args(nombre_tool, args)
        if not ruta:
            return False                       # sin ruta no se puede decidir
        exige = chequeo.get("exige") or "existe"
        if exige == "leido_antes":
            if "leidos" not in ctx and "ficheros_leidos" not in ctx:
                return False                   # el ctx no lo cuenta: fallar abierto
            return _norm_ruta(ruta) not in _leidos(ctx)
        try:
            hay = os.path.exists(ruta)
        except Exception:
            return False
        if exige == "existe":
            return not hay
        if exige == "no_existe":
            return hay
        return False

    if tipo == "orden_de_pasos":
        tras = str(chequeo.get("tras") or "")
        requiere = str(chequeo.get("requiere") or "")
        if not tras or not requiere:
            return False
        hist = _historial(ctx)
        if tras not in hist:
            return False
        i = len(hist) - 1 - hist[::-1].index(tras)   # ultima aparicion de `tras`
        return requiere not in hist[i + 1:]

    return False


def _dispara(ab: dict, nombre_tool: str, args: str, ctx: dict) -> bool:
    """Pre-filtro barato del disparador: tool, patron opcional y contexto.

    Separar disparador de chequeo no es cosmetico: el disparador es lo que se
    puede resolver con comparaciones de igualdad (y por eso se indexa), y el
    chequeo es lo que puede costar un `exists` o un recorrido del historial.
    """
    disp = ab.get("disparador") or {}
    tool = disp.get("tool")
    if tool and tool != "*" and tool != nombre_tool:
        return False
    pat = disp.get("patron_args")
    if pat:
        rx = _rx(str(pat))
        if not rx or not rx.search(args):
            return False
    for k, v in (disp.get("contexto") or {}).items():
        if ctx.get(k) != v:
            return False
    return True


def aplica(ab: dict, nombre_tool: str, args: str, ctx: dict | None = None) -> bool:
    """True si ESTE anticuerpo vetaria esta llamada, IGNORANDO su estado.

    Se expone porque es justo lo que necesita `examinar` (evaluar un anticuerpo
    en cuarentena, que por definicion no esta en el indice de activos) y lo que
    necesita quien quiera depurar un veto sin activarlo antes.
    """
    try:
        ctx = ctx if isinstance(ctx, dict) else {}
        args = args or ""
        if not _dispara(ab, nombre_tool, args, ctx):
            return False
        return _chequea(ab.get("chequeo") or {}, nombre_tool, args, ctx)
    except Exception:
        return False


# ── EL PUNTO CALIENTE ─────────────────────────────────────────────────────────

def evaluar(nombre_tool: str, args: str, ctx: dict | None = None) -> dict | None:
    """None para dejar pasar, o {veto: True, mensaje, id, nombre} para vetar.

    `mensaje` esta escrito PARA EL MODELO (no es un log): dice que se bloqueo,
    de que fallo viene y que hacer en su lugar. El interceptor del repo lo
    devuelve tal cual como resultado de la herramienta.

    Contrato duro: NUNCA lanza. Cualquier error interno = None (dejar pasar).
    Es el unico codigo que corre en CADA tool call: ver la MEDICION de la
    cabecera para el coste real por llamada.
    """
    try:
        idx = _indice()
        if not idx:
            return None
        cands = idx.get(nombre_tool)
        gen = idx.get("*")
        if not cands and not gen:
            return None
        ctx = ctx if isinstance(ctx, dict) else {}
        args = args or ""
        for lote in (cands, gen):
            if not lote:
                continue
            for ab in lote:
                if not _dispara(ab, nombre_tool, args, ctx):
                    continue
                if not _chequea(ab.get("chequeo") or {}, nombre_tool, args, ctx):
                    continue
                # Contabilidad en MEMORIA: escribir el JSON aqui metería un
                # fsync en el camino caliente. Lo duradero es registrar_resultado.
                ab["aciertos"] = int(ab.get("aciertos") or 0) + 1
                ab["ultima_vez"] = _ahora()
                return {
                    "veto": True,
                    "id": ab.get("id"),
                    "nombre": ab.get("nombre"),
                    "mensaje": mensaje_de_veto(ab),
                }
        return None
    except Exception:
        return None


def mensaje_de_veto(ab: dict) -> str:
    """El texto que lee el MODELO cuando se le veta una accion.

    Lleva el remedio y una orden explicita de NO reintentar: un modelo chico al
    que solo se le dice "bloqueado" repite la misma llamada hasta agotar pasos
    (mismo hallazgo que en `cognia/harness/limites.py`).
    """
    origen = ab.get("origen") or {}
    trayecto = origen.get("trayectoria") or "?"
    paso = origen.get("paso")
    donde = (f"trayectoria {trayecto}, paso {paso}" if paso is not None
             else f"trayectoria {trayecto}")
    remedio = (ab.get("remedio") or "").strip() or "Replantea la accion antes de reintentarla."
    return (
        f"VETADO por el sistema inmune ({ab.get('nombre') or ab.get('id')}).\n"
        f"Esta accion reproduce un fallo YA CONFIRMADO en {donde}.\n"
        f"QUE HACER: {remedio}\n"
        f"Si crees que este veto es un falso positivo, dilo explicitamente y sigue "
        f"por otra via: NO reintentes la misma llamada."
    )


# ── SINTESIS desde un informe causal ──────────────────────────────────────────

def _pasos_de(trayectoria) -> list:
    if isinstance(trayectoria, dict):
        pasos = trayectoria.get("pasos") or trayectoria.get("trayectoria") or []
    else:
        pasos = trayectoria
    return pasos if isinstance(pasos, list) else []


def _paso_culpable(informe: dict, trayectoria) -> dict:
    """El paso al que el informe atribuye el fallo, como dict, o {}.

    Contrato DUCK-TYPED con el modulo de atribucion causal (a proposito: esa
    estructura todavia se esta moviendo). Se acepta `paso_culpable` como indice
    entero, como el dict del paso entero, o `paso` a secas; y `trayectoria` como
    lista de pasos o como dict con 'pasos'.
    """
    p = informe.get("paso_culpable")
    if p is None:
        p = informe.get("paso")
    if isinstance(p, dict):
        return p
    pasos = _pasos_de(trayectoria)
    if isinstance(p, int) and 0 <= p < len(pasos):
        cand = pasos[p]
        return cand if isinstance(cand, dict) else {}
    return {}


def _texto_error(paso: dict, informe: dict) -> str:
    partes = [paso.get("error"), paso.get("salida"), paso.get("out"),
              informe.get("error"), informe.get("modo_fallo"), informe.get("evidencia")]
    return " ".join(str(x) for x in partes if x).lower()


def _token_citado(args: str, error: str, minimo: int = 6) -> str:
    """El token mas largo de `args` que el texto del error CITA literalmente.

    Es el unico anclaje honesto para fabricar un `patron_args`: si el error
    menciona la cadena, esa cadena es parte de la causa; si no la menciona, no
    hay evidencia de que lo sea y no se inventa el patron.
    """
    mejor = ""
    for t in re.split(r"[\s,;:()\[\]{}'\"]+", args or ""):
        t = t.strip()
        if len(t) >= minimo and t.lower() in error and len(t) > len(mejor):
            mejor = t
    return mejor


def _valida_chequeo(ch) -> dict | None:
    """Un chequeo dictado por el informe causal solo se acepta si es EJECUTABLE.

    Un 'tipo' desconocido o un regex que no compila producirian un anticuerpo
    que nunca veta nada y que aun asi ocuparia sitio y confianza.
    """
    if not isinstance(ch, dict) or ch.get("tipo") not in TIPOS_CHEQUEO:
        return None
    tipo = ch["tipo"]
    if tipo == "patron_args" and not _rx(str(ch.get("patron") or "")):
        return None
    if tipo == "comando_prohibido" and not (ch.get("comando") or ch.get("comandos")):
        return None
    if tipo == "orden_de_pasos" and not (ch.get("tras") and ch.get("requiere")):
        return None
    if tipo == "precondicion_fichero" and ch.get("exige") not in (
            "existe", "no_existe", "leido_antes"):
        return None
    return dict(ch)


# NOMBRE DE LA TOOL EN UN PASO: el repo tiene DOS formatos vivos y hay que
# aceptar los dos o el modulo se queda mudo justo en produccion. El `trace` del
# bucle (cognia/agent/loop.py) usa "action"; el grabador de flujos
# (cognia/flujos/grabador.py) usa "tool". Cazado en el e2e del 2026-08-19: con
# la traza REAL del bucle, sintetizar() devolvia None SIEMPRE porque leia una
# clave que ese formato no tiene -- un fallo silencioso de los que este repo
# persigue: el sistema inmune "funcionaba" y no podia nacer un solo anticuerpo.
def _tool_de(paso) -> str:
    if not isinstance(paso, dict):
        return ""
    return str(paso.get("tool") or paso.get("action")
               or paso.get("nombre") or "").strip()


def _ruta_leida_antes(ruta: str, informe: dict, trayectoria) -> bool:
    """True si la trayectoria muestra una lectura previa de esa ruta."""
    if not ruta:
        return False
    pasos = _pasos_de(trayectoria)
    if not pasos:
        return False
    objetivo = _norm_ruta(ruta)
    tope = informe.get("paso_culpable")
    if not isinstance(tope, int):
        tope = len(pasos)
    for p in pasos[:tope]:
        if not isinstance(p, dict):
            continue
        if _tool_de(p) in ("leer_archivo", "leer_lote"):
            if _norm_ruta(str(p.get("args") or "").split("|", 1)[0]) == objetivo:
                return True
    return False


def sintetizar(informe_causal: dict, trayectoria=None) -> dict | None:
    """Convierte un fallo ATRIBUIDO en un anticuerpo en cuarentena, o None.

    Devuelve None --- y esto es la mitad del valor del modulo --- cuando el fallo
    no cabe en ningun chequeo determinista: un error de razonamiento, una
    respuesta pobre, un "el modelo no entendio la tarea". Esos NO se convierten
    en prosa inyectada; simplemente no producen anticuerpo.

    Orden de reglas (la primera que casa gana), todas ancladas en EVIDENCIA del
    informe, nunca en una corazonada:
      0. El informe trae un `chequeo` explicito y valido -> se usa tal cual.
      1. Los args del paso culpable contienen un comando destructivo conocido
         -> comando_prohibido.
      2. La tool EDITA por bloques y el error dice "no casaba", o la ruta no se
         habia leido antes en la trayectoria -> precondicion_fichero
         'leido_antes'.
      3. El error dice "no existe" y la tool NO crea ficheros
         -> precondicion_fichero 'existe'.
      4. El error CITA literalmente un token de los args -> patron_args.
      5. El informe trae `orden` {tras, requiere} -> orden_de_pasos.
      6. Nada de lo anterior -> None.

    Devuelve None ademas si `informe_causal['confianza']` viene y es < 0.5: un
    fallo mal atribuido produce un anticuerpo que veta lo sano, y ese es
    exactamente el modo de muerte de las skills auto-capturadas de este repo.

    NUNCA activa nada: el anticuerpo sale en 'cuarentena' y solo `examinar` lo
    puede mover.
    """
    try:
        if not isinstance(informe_causal, dict):
            return None
        conf = informe_causal.get("confianza")
        if isinstance(conf, (int, float)) and not isinstance(conf, bool) and conf < 0.5:
            return None

        paso = _paso_culpable(informe_causal, trayectoria)
        tool = _tool_de(paso) or str(informe_causal.get("tool") or "").strip()
        if not tool:
            return None
        args = str(paso.get("args") or informe_causal.get("args") or "")
        error = _texto_error(paso, informe_causal)

        chequeo = _valida_chequeo(informe_causal.get("chequeo"))
        remedio = str(informe_causal.get("remedio") or "").strip()

        if chequeo is None:
            bajos = args.lower()
            for c in _DESTRUCTIVOS:
                if _tokens_en_orden(c, bajos):
                    chequeo = {"tipo": "comando_prohibido", "comando": c}
                    remedio = remedio or (
                        f"'{c}' destruyo trabajo en esta misma trayectoria. Usa la "
                        f"variante no destructiva o pide confirmacion al usuario.")
                    break

        if chequeo is None and tool in _EDITAN:
            ruta = ruta_de_args(tool, args)
            if ruta and (any(h in error for h in _ERR_NO_CASA)
                         or not _ruta_leida_antes(ruta, informe_causal, trayectoria)):
                chequeo = {"tipo": "precondicion_fichero", "exige": "leido_antes"}
                remedio = remedio or (
                    "Editaste un fichero que no habias leido en este turno y el bloque "
                    "no casaba. Lee el fichero con leer_archivo antes de editarlo.")

        if (chequeo is None and tool not in _CREAN
                and any(h in error for h in _ERR_NO_EXISTE)):
            if ruta_de_args(tool, args):
                chequeo = {"tipo": "precondicion_fichero", "exige": "existe"}
                remedio = remedio or (
                    "La ruta no existia y la llamada fallo. Comprueba con listar/arbol "
                    "que la ruta existe antes de usarla.")

        if chequeo is None:
            tok = _token_citado(args, error)
            if tok:
                chequeo = {"tipo": "patron_args", "patron": re.escape(tok)}
                remedio = remedio or (
                    f"Los args que contienen '{tok}' ya fallaron aqui. Cambia ese "
                    f"argumento en vez de repetir la llamada.")

        if chequeo is None:
            orden = informe_causal.get("orden")
            if isinstance(orden, dict) and orden.get("tras") and orden.get("requiere"):
                chequeo = {"tipo": "orden_de_pasos",
                           "tras": str(orden["tras"]), "requiere": str(orden["requiere"])}
                remedio = remedio or (
                    f"Llamaste a '{tool}' tras '{orden['tras']}' sin pasar por "
                    f"'{orden['requiere']}', y eso fallo. Haz '{orden['requiere']}' antes.")

        if chequeo is None:
            return None   # NO se inventa un anticuerpo de prosa

        disparador = {"tool": tool, "patron_args": None, "contexto": {}}
        disp_inf = informe_causal.get("disparador")
        if isinstance(disp_inf, dict):
            disparador.update({k: v for k, v in disp_inf.items()
                               if k in ("tool", "patron_args", "contexto")})

        trayecto_id = informe_causal.get("trayectoria")
        if trayecto_id is None and isinstance(trayectoria, dict):
            trayecto_id = trayectoria.get("id")
        idx_paso = informe_causal.get("paso_culpable")

        return {
            "id": _nuevo_id(tool, chequeo),
            "nombre": _nombre(tool, chequeo),
            "origen": {
                "trayectoria": trayecto_id,
                "paso": idx_paso if isinstance(idx_paso, int) else None,
                "fallo": str(informe_causal.get("modo_fallo")
                             or informe_causal.get("error") or "")[:400],
            },
            "disparador": disparador,
            "chequeo": chequeo,
            "remedio": remedio,
            "estado": "cuarentena",
            "creado": _ahora(),
            "aciertos": 0,
            "falsos_positivos": 0,
            "ultima_vez": None,
        }
    except Exception:
        return None


def _firma_chequeo(tool: str, chequeo: dict) -> str:
    crudo = json.dumps([tool, chequeo], sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(crudo.encode("utf-8")).hexdigest()[:12]


def _nuevo_id(tool: str, chequeo: dict) -> str:
    """Id ORDENABLE en el tiempo + firma del chequeo: dos sintesis del mismo
    chequeo dan la misma firma y `registrar` deduplica sin heuristicas."""
    return f"ab-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{_firma_chequeo(tool, chequeo)}"


def _nombre(tool: str, chequeo: dict) -> str:
    tipo = chequeo.get("tipo")
    if tipo == "comando_prohibido":
        return f"{tool}: prohibido '{chequeo.get('comando') or 'comando'}'"
    if tipo == "precondicion_fichero":
        return f"{tool}: la ruta debe cumplir '{chequeo.get('exige')}'"
    if tipo == "patron_args":
        return f"{tool}: args que casan /{chequeo.get('patron')}/"
    if tipo == "orden_de_pasos":
        return f"{tool}: tras '{chequeo.get('tras')}' exige '{chequeo.get('requiere')}'"
    return f"{tool}: anticuerpo"


# ── Almacen: alta, listado, retiro ────────────────────────────────────────────

def registrar(anticuerpo: dict) -> dict | None:
    """Da de alta un anticuerpo (siempre en 'cuarentena') y lo persiste.

    Deduplica por firma (tool + chequeo): si ya existe uno con el mismo chequeo
    devuelve el existente SIN tocar su estado. Asi diez trayectorias que tropiezan
    con el mismo fallo no llenan el almacen de clones y --- mas importante --- no
    resucitan en cuarentena un anticuerpo ya RETIRADO por falsos positivos.
    """
    if not isinstance(anticuerpo, dict) or not anticuerpo.get("chequeo"):
        return None
    datos = list(_cargar())
    tool = str((anticuerpo.get("disparador") or {}).get("tool") or "*")
    firma = _firma_chequeo(tool, anticuerpo["chequeo"])
    for ab in datos:
        t = str((ab.get("disparador") or {}).get("tool") or "*")
        if _firma_chequeo(t, ab.get("chequeo") or {}) == firma:
            return ab
    nuevo = dict(anticuerpo)
    nuevo["estado"] = "cuarentena"      # nace SIEMPRE en cuarentena, sin excepcion
    nuevo.setdefault("id", _nuevo_id(tool, nuevo["chequeo"]))
    nuevo.setdefault("creado", _ahora())
    nuevo.setdefault("aciertos", 0)
    nuevo.setdefault("falsos_positivos", 0)
    nuevo.setdefault("ultima_vez", None)
    datos.append(nuevo)
    _guardar(datos)
    return nuevo


def listar() -> list:
    """Todos los anticuerpos del almacen, en el orden en que se dieron de alta."""
    return list(_cargar())


def activos() -> list:
    """Solo los que de verdad vetan. Es lo que indexa `evaluar`."""
    return [a for a in _cargar() if a.get("estado") == "activo"]


def obtener(id_ab: str) -> dict | None:
    for a in _cargar():
        if a.get("id") == id_ab:
            return a
    return None


def retirar(id_ab: str, motivo: str = "") -> dict | None:
    """Saca un anticuerpo de circulacion. No se borra: se marca 'retirado' con
    el motivo, porque el historial de por que algo dejo de valer es la unica
    defensa contra volver a activarlo por las mismas razones."""
    datos = list(_cargar())
    for ab in datos:
        if ab.get("id") == id_ab:
            ab["estado"] = "retirado"
            ab["motivo_retiro"] = str(motivo or "")
            ab["ultima_vez"] = _ahora()
            _guardar(datos)
            return ab
    return None


# ── LA COMPUERTA ──────────────────────────────────────────────────────────────

def _caso(c) -> tuple:
    """Normaliza un caso de examen a (tool, args, ctx). Acepta dict o tupla."""
    if isinstance(c, dict):
        return (_tool_de(c),
                str(c.get("args") or ""),
                c.get("ctx") if isinstance(c.get("ctx"), dict) else {})
    if isinstance(c, (list, tuple)):
        tool = str(c[0]) if len(c) > 0 else ""
        args = str(c[1]) if len(c) > 1 else ""
        ctx = c[2] if len(c) > 2 and isinstance(c[2], dict) else {}
        return (tool, args, ctx)
    return ("", "", {})


def examinar(anticuerpo: dict, casos_positivos, casos_negativos) -> dict:
    """LA COMPUERTA. Activa el anticuerpo SOLO si veta todo lo malo y NADA sano.

    - `casos_positivos`: llamadas que reproducen el fallo. Tienen que ser vetadas
      TODAS: si una escapa, el chequeo no captura el fallo que dice capturar.
    - `casos_negativos`: bateria HELD-OUT de llamadas sanas. UN solo falso
      positivo y NO se activa. Uno, no tres: aqui los sanos los elige el
      integrador a mano, y un veto sobre lo sano rompe tareas ajenas --- que es
      exactamente como murieron las skills auto-capturadas de este repo.
    - Sin casos positivos NO se activa: un anticuerpo del que nadie demostro que
      dispara sobre su propio fallo es una supersticion, no un chequeo.

    Devuelve {activado, estado, positivos_vetados, positivos_total,
    falsos_positivos: [...], motivo} y persiste el resultado si el anticuerpo ya
    estaba dado de alta (examinar un dict suelto no crea nada en el almacen).
    """
    res = {"activado": False, "estado": "cuarentena", "positivos_vetados": 0,
           "positivos_total": 0, "falsos_positivos": [], "motivo": ""}
    if not isinstance(anticuerpo, dict) or not anticuerpo.get("chequeo"):
        res["motivo"] = "anticuerpo invalido: no lleva chequeo"
        return res

    pos = list(casos_positivos or [])
    neg = list(casos_negativos or [])
    res["positivos_total"] = len(pos)

    escapados = []
    for c in pos:
        tool, args, ctx = _caso(c)
        if aplica(anticuerpo, tool, args, ctx):
            res["positivos_vetados"] += 1
        else:
            escapados.append({"tool": tool, "args": args})

    for c in neg:
        tool, args, ctx = _caso(c)
        if aplica(anticuerpo, tool, args, ctx):
            res["falsos_positivos"].append({"tool": tool, "args": args})

    if not pos:
        res["motivo"] = "sin casos positivos: no se demostro que capture el fallo"
    elif escapados:
        res["motivo"] = f"{len(escapados)} caso(s) del fallo NO vetados: {escapados[:3]}"
    elif res["falsos_positivos"]:
        res["motivo"] = (f"{len(res['falsos_positivos'])} falso(s) positivo(s) sobre "
                         f"casos sanos: {res['falsos_positivos'][:3]}")
    else:
        res["activado"] = True
        res["estado"] = "activo"
        res["motivo"] = (f"{len(pos)} positivos vetados, 0 falsos positivos "
                         f"en {len(neg)} sanos")

    if res["activado"]:
        anticuerpo["estado"] = "activo"
    res["estado"] = anticuerpo.get("estado", "cuarentena")
    anticuerpo["examen"] = {"positivos": len(pos), "negativos": len(neg),
                            "activado": res["activado"], "motivo": res["motivo"],
                            "cuando": _ahora()}

    datos = list(_cargar())
    for ab in datos:
        if ab.get("id") == anticuerpo.get("id"):
            ab["estado"] = anticuerpo["estado"]
            ab["examen"] = anticuerpo["examen"]
            _guardar(datos)
            break
    return res


def registrar_resultado(id_ab: str, fue_util: bool) -> dict | None:
    """Contabiliza un veto en PRODUCCION y retira solo tras N falsos positivos.

    `fue_util=False` significa "este veto bloqueo algo que estaba bien". Al
    llegar a `COGNIA_INMUNE_MAX_FP` (3 por defecto) el anticuerpo pasa a
    'retirado' sin que nadie tenga que acordarse de mirarlo: un chequeo que se
    equivoca tres veces cuesta mas de lo que ahorra.
    """
    datos = list(_cargar())
    for ab in datos:
        if ab.get("id") != id_ab:
            continue
        if fue_util:
            ab["aciertos"] = int(ab.get("aciertos") or 0) + 1
        else:
            ab["falsos_positivos"] = int(ab.get("falsos_positivos") or 0) + 1
            if ab["falsos_positivos"] >= _max_fp():
                ab["estado"] = "retirado"
                ab["motivo_retiro"] = (f"retiro automatico: {ab['falsos_positivos']} "
                                       f"falsos positivos en produccion")
        ab["ultima_vez"] = _ahora()
        _guardar(datos)
        return ab
    return None
