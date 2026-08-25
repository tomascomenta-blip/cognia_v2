# -*- coding: utf-8 -*-
"""
cognia/harness/offloading.py
============================
OFFLOADING de salidas de herramientas: lo grande va a DISCO, al modelo le
llega un resumen + un HANDLE con el que puede pedir el trozo que necesite.

POR QUE EXISTE (2026-08-12): hoy el resultado de una tool entra ENTERO en el
historial. Un `leer_archivo` de 400 KB o un `ejecutar` con un log largo se
come la ventana de una sola observacion, y a partir de ahi el bucle vive
recortando mensajes (`loop.py:_recortar_mensajes`) — o sea, tirando historia
util para pagar una salida que el modelo miro una vez. La alternativa que ya
existe en el repo (`cognia/compresion_salidas.comprimir`) RECORTA: lo que sale
del recorte se pierde para siempre, y si el dato estaba en la linea 4000 el
agente no tiene forma de recuperarlo — vuelve a llamar a la tool, que devuelve
lo mismo, y se estanca.

Esto es lo contrario: compresion RESTAURABLE. El contenido completo se guarda
en disco y el historial se queda con un resumen navegable + un handle. Es la
mecanica en la que convergen 8 harnesses punteros: Cline (TOOL_RESULT_CHAR_LIMIT
= 2000 chars), deepagents (el resultado va al filesystem virtual), Manus
("compresion restaurable": nunca borrar, siempre poder volver), Anthropic
Research (artifact passing entre subagentes), WebThinker (document_memory) y
`clear_tool_uses` de la Claude API. El umbral por defecto es el de Cline.

Como se usa (el cableado lo hace el integrador; este modulo es autocontenido):

    from cognia.harness import offloading as off

    # en el formateador de observaciones, donde hoy se devuelve el RESULTADO:
    resultado = off.formatear_observacion(salida_cruda, "leer_archivo", args)
    # -> si cabe bajo el umbral, es `salida_cruda` INTACTA (byte a byte)
    # -> si no, es el resumen con el handle, y el original esta en disco

    # y se registra `recuperar` como tool del agente (ver DESC_RECUPERAR /
    # PARAMS_RECUPERAR, listos para el decorador @tool de agent/tools.py).

API publica:

    umbral_bytes() -> int
        UMBRAL_BYTES (2000) o el override COGNIA_TOOL_RESULT_MAX, leido a
        call-time para que los tests y el CLI puedan cambiarlo en caliente.

    guardar(contenido, tool="", args="", sesion=None) -> handle
        Escribe el contenido completo y devuelve el handle corto y legible
        ("res:3f2a1b", 6 hex del sha1). Mismo contenido+tool+args = MISMO
        handle (dedup exacto: releer el mismo fichero no duplica nada).

    resumir_para_modelo(contenido, tool="", handle="", umbral=None,
                        cabeza=15, cola=5) -> str
        El texto que SI ve el modelo. Funcion PURA: no toca disco. Si el
        contenido cabe bajo el umbral lo devuelve INTACTO (no toca lo que ya
        es corto). Si no: primeras ~15 lineas + ultimas ~5, cuantas lineas y
        cuantos bytes se omitieron, y la instruccion EXACTA para leer mas.

    formatear_observacion(contenido, tool="", args="", umbral=None) -> str
        guardar + resumir de una: el punto unico que cablea el integrador.

    recuperar(handle, desde=None, hasta=None, buscar=None, max_bytes=None) -> str
        El trozo pedido: por rango de lineas o por busqueda (con 2 lineas de
        contexto), siempre con tope de bytes. NUNCA lanza: los errores salen
        como texto "ERROR: ..." pensado para que el modelo se auto-corrija.

    listar(sesion=None) -> list[dict]
        Handles vivos con tool, bytes, lineas y edad, la mas nueva primero.

    podar(max_sesiones=20, max_mb=200) -> dict
        Limpieza de sesiones viejas por cantidad y por tamano.

    sesion_actual() / nueva_sesion() / dir_offload()
        Igual que en harness/checkpoints.py.

Almacen (override por COGNIA_OFFLOAD_DIR, leido a call-time):

    ~/.cognia/offload/<sesion>/res-3f2a1b.txt    contenido COMPLETO (utf-8)
    ~/.cognia/offload/<sesion>/res-3f2a1b.json   meta {tool, args, bytes, ...}

Escritura atomica (tmp + os.replace) y `newline=""` en los dos sentidos: lo
que se lee es byte a byte lo que se guardo, sin la traduccion CRLF de Windows
— si no, los bytes y las lineas que reporta el resumen no serian los mismos
que devuelve `recuperar`, que es justo la mentira que rompe la confianza del
modelo en el handle.

LIMITES DECLARADOS (lo que este modulo NO hace):
- El handle en DISCO es "res-3f2a1b.txt", no "res:3f2a1b.txt": en Windows los
  dos puntos abren un Alternate Data Stream de NTFS y el fichero se escribiria
  en un flujo invisible. El handle que ve el modelo lleva ':' igual.
- Solo TEXTO. Un `bytes` entra por `str()`; no se guardan binarios.
- El resumen visible pesa como mucho el umbral + ~1.2 KB de andamiaje
  (cabecera + referencia con handle, ruta del fichero y bytes exactos + las
  recetas de recuperacion): con umbral 2000 son ~3 KB, no 2000 exactos. Se
  prefiere pasarse un KB antes que devolver un handle sin decir como usarlo.
- Las lineas mas largas de _MAX_CHARS_LINEA se muestran cortadas CON marca. Un
  minificado de 400 KB en una sola linea no se puede "resumir por lineas": el
  resumen lo dira (0 lineas omitidas, 400 KB omitidos) y el modelo tendra que
  ir por `buscar`.
- `recuperar` busca primero en la sesion en curso y despues en las demas: un
  handle de una sesion anterior se sigue resolviendo mientras el fichero viva.
- No hay lock entre procesos. Dos Cognias a la vez no se pisan (la sesion
  lleva el PID y el tmp de escritura tambien), pero `podar` de uno puede
  borrar sesiones viejas del otro.
- `podar` NUNCA toca la sesion en curso: si ella sola pasa el presupuesto de
  MB, el resultado sale con `excedido=True` en vez de borrar lo que el agente
  todavia puede estar leyendo.
- No hay TTL por tiempo: la vida de un handle la marca la poda, no un reloj.
- `recuperar` devuelve LINEAS: el salto de linea FINAL del contenido no vuelve
  (el fichero en disco si lo conserva). Recuperar el rango 1-N reconstruye el
  original byte a byte salvo ese '\\n' de cierre. Las lineas se parten SOLO por
  '\\n' (no con `str.splitlines`, que ademas parte por '\\r', '\\f', '\\x85' y
  '\\u2028': con CRLF el round-trip perdia un '\\r' por linea, y un '\\f' dentro
  de un log inflaba el conteo de lineas que se le promete al modelo).
- Un `str` con surrogates sueltos (lo que deja `errors="surrogateescape"`) se
  sanea a utf-8 en la ENTRADA: `encode("utf-8")` lanzaria y se llevaria puesta
  la observacion entera, que es justo lo que este modulo promete no hacer.
- CABLEADO (F3, 2026-08-23): `harness/interceptor.despues` llama a
  `formatear_observacion` cuando `activo()` (env COGNIA_OFFLOAD > config
  'offload' de /offload; el CLI propaga su default 'on' al env al arrancar) y
  `recuperar` esta registrada en tools_harness.py gated por el mismo flag.
  Ojo con el catalogo: el A/B de este repo (2026-07-25, n=4+4) midio que 46
  tools bajan el camino feliz de 4.25/5 a 2.5/5, y por eso existe CORE_TOOLS.
  `recuperar` se gana el sitio porque sin ella el offloading es TRUNCADO: es
  la mitad restaurable de una sola mecanica, no una tool mas.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Umbral de bytes por defecto: el TOOL_RESULT_CHAR_LIMIT de Cline.
UMBRAL_BYTES = 2000

# Lineas de cabeza y cola que se muestran (el principio y el final son lo
# informativo: la cabecera de un fichero y la conclusion de un log/traceback).
CABEZA_DEFECTO = 15
COLA_DEFECTO = 5

# Tope por linea mostrada en el resumen: una sola linea gigante no puede
# reventar el presupuesto de las otras 19. El tope va en CHARS y ademas en
# BYTES: 300 chars de emoji son 1200 bytes y el resumen se pasaba al doble del
# umbral (medido 2966 B con umbral 2000).
_MAX_CHARS_LINEA = 300
_MAX_BYTES_LINEA = 400

# Reparto del presupuesto visible entre cabeza y cola.
_CUOTA_CABEZA = 0.7

# Ventana por defecto de `recuperar` cuando no se pide rango ni busqueda.
_VENTANA_DEFECTO = 60

# Tope de bytes de `recuperar` = 4x el umbral (2000 -> 8000): recuperar un
# trozo tiene que caber en la ventana igual que la observacion original.
_FACTOR_MAX_BYTES = 4

# Tools cuya salida NO se re-offloadea (el interceptor consulta este set).
# `recuperar` ES la via de recuperacion del propio offload y su salida ya
# viene capada por _FACTOR_MAX_BYTES: volver a spillearla anidaba handles
# (spill del spill) y el modelo nunca veia mas de cabeza+cola lineas por
# recuperacion — el contrato "compresion RESTAURABLE" quedaba irrestaurable
# (cazado por la revision adversarial 2026-08-23). Punto de extension: una
# tool futura que se cape sola con criterio propio se anade aqui.
# `delegar_subtarea` se capa sola (4000 chars inline + preview con handle,
# agent/tools.py): re-offloadearla con el umbral generico de 2000 hacia
# preview del preview (lineas doblemente numeradas, la receta apuntando al
# fichero del preview y no al informe) y el tope inline efectivo era 2000,
# no los 4000 que su desc anuncia (revision adversarial 2026-08-24).
# `skill_leer` promete el cuerpo COMPLETO de una skill (material de
# referencia que el modelo pidio por nombre): cabeza+cola le quitaba los
# pasos del medio.
EXENTAS_OFFLOAD = frozenset({"recuperar", "delegar_subtarea", "skill_leer"})

# Marcadores de FALLO en la PRIMERA linea de un resultado de tool: el contrato
# del registry (agent/tools.py) pone "ERROR" en la linea 1, y ejecutar/tests
# reportan "(exit N)" ahi mismo. Es la misma heuristica de fallback del bucle.
_RE_FALLO_LINEA1 = re.compile(r"\bERROR\b|\(exit -?[1-9]\d*\)")
# El marcador de recorte que deja agent/tools._leer_archivo (limit explicito).
_RE_TRUNCADO_TOOL = re.compile(
    r"\[TRUNCADO: mostrando lineas (\d+)-(\d+) de (\d+)")


def es_fallo_primera_linea(texto: str, tool: str = "") -> bool:
    """True si la PRIMERA linea de `texto` trae marcador de fallo DE LA TOOL
    (ERROR o exit != 0). Lo usan el resumen del offload y
    compactacion._linea_tool. Delega en harness/veredicto_tool: para las
    tools de CONTENIDO (leer_archivo, buscar...) el marcador solo cuenta en
    el prefijo 'RESULTADO <tool> <obj>', nunca en el contenido -- antes un
    log con 'ERROR' en su linea 1 spilleaba con ' ERROR' en la cabecera y el
    modelo lo leia como fallo (juez 2026-08-24)."""
    from cognia.harness.veredicto_tool import es_fallo as _es_fallo
    return _es_fallo(texto, tool)

# Lineas de contexto alrededor de cada acierto de `buscar` y tope de aciertos.
_CONTEXTO_BUSCAR = 2
_MAX_ACIERTOS = 40

# Sesiones retenidas y presupuesto de disco (misma politica que checkpoints).
_MAX_SESIONES = 20
_MAX_MB = 200

_SUFIJO_TXT = ".txt"
_SUFIJO_META = ".json"

# "res:" + 6 a 40 hex. Se valida SIEMPRE antes de construir una ruta: el
# handle llega del modelo, o sea de texto no confiable (traversal).
_RE_HANDLE = re.compile(r"^res:[0-9a-f]{6,40}$")
_RE_HEX = re.compile(r"^[0-9a-f]{6,40}$")
# "200-260", "200:260", "200 260" — el modelo escribe el rango de tres formas.
_RE_RANGO = re.compile(r"^(\d+)\s*[-:\s]\s*(\d+)$")

# Id de la sesion en curso: se fija en el primer uso del proceso.
_SESION: str | None = None

# Telemetria minima para la puerta /offload del CLI: el ultimo spill guardado
# y el ultimo fallo del subsistema. Solo memoria de proceso, nada en disco.
_ULTIMO_SPILL: dict = {}
_ULTIMO_ERROR: dict = {}

# Punto de extension: el CLI registra aca su _aviso_degradado para que un
# fallo de disco se VEA en el REPL ademas del logger. None = solo logger.
_AVISADOR = None


def registrar_avisador(fn) -> None:
    """Registra el callable (origen, motivo) -> None que recibe los fallos del
    subsistema (el CLI pasa su `_aviso_degradado`). Un solo avisador: el ultimo
    registrado gana (el REPL se registra una vez al arrancar)."""
    global _AVISADOR
    _AVISADOR = fn


# ── Documentacion para registrar `recuperar` como tool del agente ─────────────
# (listo para el decorador @tool de cognia/agent/tools.py; el integrador solo
# tiene que envolver `herramienta_recuperar` con estos dos valores)

DESC_RECUPERAR = (
    "Lee un trozo de una salida GRANDE que no entro en el historial. Cuando el "
    "resultado de una herramienta era demasiado largo, viste un resumen con un "
    "handle tipo 'res:3f2a1b': el contenido completo esta guardado y esta tool "
    "lo abre. Pedi un rango de lineas ('lineas 200-260') si el resumen ya te "
    "dijo donde mirar, o 'buscar=<texto>' si no sabes en que linea esta lo que "
    "necesitas (devuelve las lineas que casan con 2 de contexto). No re-ejecutes "
    "la herramienta original para volver a ver la salida: usa el handle."
)

PARAMS_RECUPERAR = [
    {"nombre": "handle", "tipo": "string", "requerido": True, "clave": False,
     "descripcion": "El handle que aparecio en el resumen, p.ej. 'res:3f2a1b'."},
    {"nombre": "lineas", "tipo": "string", "requerido": False, "clave": True,
     "descripcion": "Rango de lineas 1-indexado e inclusivo, p.ej. '200-260'. "
                    "Sin esto se devuelven las primeras 60 lineas."},
    {"nombre": "buscar", "tipo": "string", "requerido": False, "clave": True,
     "descripcion": "Texto a buscar (sin distinguir mayusculas). Devuelve las "
                    "lineas que lo contienen con 2 lineas de contexto y su "
                    "numero de linea, para que despues pidas el rango exacto."},
]


# ── Ubicacion y sesiones ──────────────────────────────────────────────────────

def dir_offload() -> Path:
    """Raiz del almacen; COGNIA_OFFLOAD_DIR permite override (tests)."""
    override = os.environ.get("COGNIA_OFFLOAD_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".cognia" / "offload"


def umbral_bytes() -> int:
    """Umbral efectivo en BYTES utf-8. Env COGNIA_TOOL_RESULT_MAX manda.

    Un valor no numerico o <= 0 cae al defecto en vez de "offloadear todo":
    con umbral 0 hasta un "OK" se iria a disco y el modelo tendria que hacer
    un round-trip para leer dos letras.
    """
    bruto = os.environ.get("COGNIA_TOOL_RESULT_MAX", "").strip()
    if not bruto:
        return UMBRAL_BYTES
    try:
        valor = int(float(bruto))
    except (TypeError, ValueError):
        return UMBRAL_BYTES
    return valor if valor > 0 else UMBRAL_BYTES


def activo() -> bool:
    """EL lector del flag de encendido: COGNIA_OFFLOAD en el entorno.

    '1' enciende, '0' apaga, sin poner = apagado. El encendido por defecto
    del PRODUCTO lo pone el CLI: `_aplicar_config_offload()` (cli.py) propaga
    la clave persistida 'offload' (default on) al env en CADA arranque del
    REPL, y /offload on|off actualiza config Y env a la vez — asi este lector,
    tools.py y familias.py (todos leen el env) no pueden divergir de lo que
    dice /offload (la clase de bug del flag TX, cognia/tx/flag.py). Embebido
    sin CLI sigue siendo opt-in por env a proposito: leer aca el
    ~/.cognia_config.json real contaminaria cualquier proceso (tests
    incluidos) con la config del dueno de la maquina.
    """
    return os.environ.get("COGNIA_OFFLOAD", "").strip().lower() in (
        "1", "on", "true", "yes", "si")


def _entero_env(nombre: str, defecto: int, minimo: int = 1) -> int:
    """Un knob entero de entorno; basura o < minimo caen al defecto."""
    bruto = os.environ.get(nombre, "").strip()
    if not bruto:
        return defecto
    try:
        valor = int(float(bruto))
    except (TypeError, ValueError):
        return defecto
    return valor if valor >= minimo else defecto


def cabeza_defecto() -> int:
    """Lineas de cabeza del preview; COGNIA_OFFLOAD_CABEZA la mueve (el CLI
    la propaga desde la clave persistida 'offload_cabeza')."""
    return _entero_env("COGNIA_OFFLOAD_CABEZA", CABEZA_DEFECTO)


def cola_defecto() -> int:
    """Lineas de cola del preview; COGNIA_OFFLOAD_COLA la mueve (0 = solo
    cabeza, permitido). La cola existe porque el truncado clasico solo
    conserva cabeza y la conclusion de un log/traceback vive al FINAL."""
    return _entero_env("COGNIA_OFFLOAD_COLA", COLA_DEFECTO, minimo=0)


def _umbral_efectivo(umbral) -> int:
    """El umbral que pide el llamador, o el de entorno. Un valor basura cae al
    de entorno en vez de lanzar: esto corre en el formateador de observaciones,
    donde una excepcion cuesta el turno entero."""
    valor = _entero(umbral)
    return valor if valor and valor > 0 else umbral_bytes()


def _nuevo_id() -> str:
    """'YYYYmmdd-HHMMSS-ffffff-<pid>': ordenable por nombre = ordenable en el
    tiempo, y el pid separa dos Cognias abiertos a la vez."""
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f") + f"-{os.getpid()}"


def sesion_actual() -> str:
    """Id de la sesion en curso, creandolo en el primer uso del proceso."""
    global _SESION
    if _SESION is None:
        _SESION = _nuevo_id()
    return _SESION


def nueva_sesion() -> str:
    """Abre una sesion nueva y devuelve su id. Los handles anteriores siguen
    resolviendo (recuperar mira todas las sesiones), pero no se mezclan."""
    global _SESION
    nuevo = _nuevo_id()
    while nuevo == _SESION:          # dos llamadas en el mismo microsegundo
        nuevo = _nuevo_id()
    _SESION = nuevo
    return _SESION


def sesiones() -> list:
    """Ids de las sesiones con almacen en disco, la mas nueva primero."""
    try:
        return sorted((d.name for d in dir_offload().iterdir() if d.is_dir()),
                      reverse=True)
    except OSError:
        return []


def _dir_sesion(sesion: str) -> Path:
    return dir_offload() / sesion


# ── Handles y disco ───────────────────────────────────────────────────────────

def normalizar_handle(bruto) -> str:
    """Handle canonico ('res:3f2a1b') o "" si no es un handle valido.

    Tolerante con lo que escribe el modelo (comillas, backticks, punto final,
    mayusculas, el prefijo 'res:' olvidado) y ESTRICTA con lo que no lo es: la
    ruta se construye a partir de esto, asi que cualquier cosa fuera de
    [0-9a-f] se rechaza — un '../..' jamas llega a tocar el filesystem.
    """
    if not bruto:
        return ""
    txt = str(bruto).strip().strip("'\"`,.;()[]").strip().lower()
    if txt.startswith("res:"):
        txt = "res:" + txt[4:].strip()
    elif _RE_HEX.match(txt):
        txt = "res:" + txt          # el modelo se comio el prefijo
    return txt if _RE_HANDLE.match(txt) else ""


def _un_segmento(nombre: str) -> str:
    """El nombre de fichero saneado a UN solo segmento de path.

    Los handles validos ya son hex (los filtra `normalizar_handle`), pero esta
    es la ULTIMA linea antes de construir una ruta: cualquier '/', '\\' o char
    raro se vuelve '_' para que un nombre jamas pueda salirse del directorio
    de su sesion. ':' aparte: en NTFS abre un Alternate Data Stream (el
    contenido se escribiria en un flujo invisible y `listar` no lo veria).
    """
    limpio = re.sub(r"[^0-9A-Za-z._-]", "_", nombre.replace(":", "-"))
    return limpio.lstrip(".") or "_"


def _ruta_txt(sesion: str, handle: str) -> Path:
    return _dir_sesion(sesion) / (_un_segmento(handle) + _SUFIJO_TXT)


def _ruta_meta(sesion: str, handle: str) -> Path:
    return _dir_sesion(sesion) / (_un_segmento(handle) + _SUFIJO_META)


def _handle_de_fichero(p: Path) -> str:
    return p.stem.replace("-", ":", 1)


def _escribir_atomico(destino: Path, texto: str) -> None:
    """tmp + os.replace: un corte a mitad deja el fichero anterior intacto y
    nunca un contenido truncado. El tmp lleva el PID para que dos procesos no
    se pisen el temporal."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_name(destino.name + f".tmp{os.getpid()}")
    # newline="": se guarda EXACTAMENTE lo que se paso (sin traducir \n a \r\n),
    # o sea los bytes que reporta el resumen son los que devuelve `recuperar`.
    tmp.write_text(texto, encoding="utf-8", newline="")
    os.replace(tmp, destino)


def _preparar(contenido) -> tuple:
    """(texto codificable en utf-8, sus bytes). Punto UNICO de entrada.

    Un `str` con surrogates sueltos —lo que deja `errors="surrogateescape"` al
    decodificar salida de subprocess o nombres de fichero— hace lanzar a
    `.encode("utf-8")`, y esa excepcion se llevaria puesta la observacion
    entera: el offloading es una MEJORA del formateador, no puede ser el que
    mata el turno. Se sanea una sola vez aca y lo que se guarda es lo que se
    mide (el round-trip sigue siendo exacto sobre el texto ya saneado).
    """
    txt = contenido if isinstance(contenido, str) else str(contenido)
    try:
        return txt, txt.encode("utf-8")
    except UnicodeEncodeError:
        crudo = txt.encode("utf-8", "replace")
        return crudo.decode("utf-8"), crudo


def _lineas(texto: str) -> list:
    """Parte SOLO por '\\n'. No es `str.splitlines()`: ese parte ademas por
    '\\r', '\\v', '\\f', '\\x1c-\\x1e', '\\x85', '\\u2028' y '\\u2029', y como
    aca se re-une con '\\n' el round-trip dejaba de ser byte a byte (una salida
    CRLF perdia un '\\r' por linea) y el conteo de lineas que se le promete al
    modelo no era el del fichero (un '\\f' en un log sumaba una linea que
    `recuperar` despues no encontraba en ese numero).
    """
    if not texto:
        return []
    partes = texto.split("\n")
    if partes and partes[-1] == "":
        partes.pop()             # el '\n' de cierre no abre una linea nueva
    return partes


def _leer(ruta: Path) -> str:
    # `Path.read_text(newline=...)` recien existe en 3.13 y el repo corre en
    # 3.12: se abre a mano para desactivar la traduccion de saltos de linea
    # (sin newline="" Windows leeria "\r\n" como "\n" y el round-trip mentiria).
    with open(ruta, "r", encoding="utf-8", newline="") as fh:
        return fh.read()


def guardar(contenido, tool: str = "", args: str = "",
            sesion: str | None = None) -> str:
    """Guarda el contenido COMPLETO y devuelve su handle ('res:3f2a1b').

    El handle son los 6 primeros hex del sha1 de (tool, args, contenido): el
    mismo resultado guardado dos veces devuelve el mismo handle y un solo
    fichero (releer el mismo fichero en el mismo turno es lo normal, y
    duplicarlo llenaria el disco sin aportar nada). Si esos 6 hex ya existen
    con OTRO contenido, el handle se alarga hasta que no colisione.
    """
    texto, crudo = _preparar(contenido)
    ses = sesion or sesion_actual()
    digest = hashlib.sha1(
        "\x00".join((str(tool), str(args), texto)).encode("utf-8", "replace")
    ).hexdigest()

    handle = ""
    for n in (6, 8, 12, 40):
        cand = "res:" + digest[:n]
        ruta = _ruta_txt(ses, cand)
        if not ruta.exists():
            handle = cand
            break
        try:
            if _leer(ruta) == texto:
                return cand          # dedup exacto: ya esta guardado
        except OSError:
            pass
        # Colision (o fichero ilegible): se alarga el handle y se reintenta.
    if not handle:
        handle = "res:" + digest

    _escribir_atomico(_ruta_txt(ses, handle), texto)
    meta = {
        "handle": handle,
        "tool": str(tool),
        "args": str(args)[:500],
        "bytes": len(crudo),
        "lineas": len(_lineas(texto)),
        "ts": datetime.now().isoformat(timespec="seconds"),
    }
    try:
        _escribir_atomico(_ruta_meta(ses, handle),
                          json.dumps(meta, ensure_ascii=False))
    except OSError as exc:
        # La meta es decoracion para `listar`: su perdida no invalida el handle.
        _degradar("guardar_meta", exc)
    # Telemetria para /offload: el ultimo spill con sus bytes reales.
    _ULTIMO_SPILL.clear()
    _ULTIMO_SPILL.update(meta, ruta=str(_ruta_txt(ses, handle)))
    return handle


def _buscar_fichero(handle: str) -> tuple:
    """(ruta_txt, sesion) del handle, o (None, ""). Primero la sesion en curso
    y despues el resto: un handle de una sesion anterior sigue resolviendo."""
    actual = sesion_actual()
    for ses in [actual] + [s for s in sesiones() if s != actual]:
        ruta = _ruta_txt(ses, handle)
        if ruta.exists():
            return ruta, ses
    return None, ""


def ruta_de(handle) -> str:
    """Ruta ABSOLUTA del fichero de un handle, o "" si no resuelve.

    Existe porque el handle solo sirve si la tool `recuperar` esta registrada,
    y `recuperar` es opt-in (COGNIA_OFFLOAD=1). Con la ruta, cualquier consumidor
    —el agente con `leer_archivo`, el usuario con un editor, otro proceso—
    llega al contenido completo sin depender de ese flag. `listar()` ya la
    publicaba por handle; esto es la misma verdad, consultable de a uno.

    Valida el handle con `normalizar_handle` antes de tocar el filesystem: la
    misma regla de traversal que el resto del modulo, sin excepciones nuevas.
    """
    h = normalizar_handle(handle)
    if not h:
        return ""
    ruta, _ = _buscar_fichero(h)
    try:
        return str(ruta.resolve()) if ruta else ""
    except OSError:
        return str(ruta) if ruta else ""


def _meta_de(sesion: str, handle: str) -> dict:
    try:
        return json.loads(_leer(_ruta_meta(sesion, handle)))
    except (OSError, ValueError):
        return {}


# ── Resumen: lo unico que entra al historial ──────────────────────────────────

def _fmt_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def _cortar_linea(linea: str) -> str:
    """Una linea larguisima se muestra cortada CON marca: la marca es la
    diferencia entre 'esto es todo' y 'aca hay mas' (silencio = mentira)."""
    cabe = linea[:_MAX_CHARS_LINEA]
    if len(cabe.encode("utf-8")) > _MAX_BYTES_LINEA:
        # Corte en frontera de codepoint: el tope real es en BYTES, si no una
        # linea de emoji (4 B por char) valia 4x lo presupuestado.
        cabe = cabe.encode("utf-8")[:_MAX_BYTES_LINEA].decode("utf-8", "ignore")
    if len(cabe) == len(linea):
        return linea
    return cabe + f" ... [+{len(linea) - len(cabe)} chars en esta linea]"


def _tomar(lineas: list, cuota: int, desde_el_final: bool = False,
           sobrecoste: int = 0) -> list:
    """Toma lineas (ya cortadas) mientras quepan en `cuota` bytes. Se corta por
    LINEA ENTERA para que el conteo de omitidas siga siendo verdad.
    `sobrecoste`: bytes fijos que cada linea suma al salir (el prefijo de
    numero de _numerar), para que el presupuesto siga siendo el real."""
    elegidas = []
    gasto = 0
    orden = reversed(lineas) if desde_el_final else iter(lineas)
    for linea in orden:
        coste = len(linea.encode("utf-8")) + 1 + sobrecoste
        if elegidas and gasto + coste > cuota:
            break
        elegidas.append(linea)
        gasto += coste
    return list(reversed(elegidas)) if desde_el_final else elegidas


def _ancho_numero(total_lineas: int) -> int:
    """Bytes del prefijo 'NNNN| ' con el que _numerar antepone cada linea."""
    return len(str(max(1, total_lineas))) + 2


def _numerar(lineas: list, desde: int, total_lineas: int) -> list:
    """Cada linea del preview con su numero REAL en la salida completa:
    '   12| texto'. Sin el numero, la cola era un tramo anonimo y el modelo
    tenia que adivinar el rango para `recuperar`; con el numero, el rango
    que pide es el que ve (deepagents 0.7.8, _message_eviction.py numera
    cabeza y cola y marca '... [N lines truncated] ...' entre ambas)."""
    ancho = len(str(max(1, total_lineas)))
    return [f"{desde + i:>{ancho}}| {linea}" for i, linea in enumerate(lineas)]


def resumir_para_modelo(contenido, tool: str = "", handle: str = "",
                        umbral: int | None = None,
                        cabeza: int | None = None,
                        cola: int | None = None,
                        ruta: str = "") -> str:
    """El texto que SI ve el modelo. PURA: no toca disco.

    Si el contenido cabe bajo el umbral se devuelve INTACTO — esta funcion no
    toca lo que ya es corto (ni una cabecera, ni un recorte, nada: el 90% de
    las observaciones son 'OK' y deben seguir siendo 'OK'). Por encima del
    umbral: primeras `cabeza` lineas + ultimas `cola` (None = los knobs de
    entorno/config, ver cabeza_defecto/cola_defecto), cuantas lineas y bytes
    quedaron fuera, y la REFERENCIA: handle + ruta del fichero + bytes exactos
    + la instruccion concreta para pedir el resto (contrato deepseek-harness).
    """
    texto, crudo = _preparar(contenido)
    umb = _umbral_efectivo(umbral)
    total_bytes = len(crudo)
    if total_bytes <= umb:
        return texto

    lineas = _lineas(texto)
    total_lineas = len(lineas)
    n_cabeza = max(1, int(cabeza) if cabeza is not None else cabeza_defecto())
    n_cola = max(0, int(cola) if cola is not None else cola_defecto())
    # Sin solape: con pocas lineas la cola cede a favor de la cabeza.
    if n_cabeza + n_cola > total_lineas:
        n_cola = max(0, total_lineas - n_cabeza)

    crudas_cabeza = lineas[:n_cabeza]
    crudas_cola = lineas[total_lineas - n_cola:] if n_cola else []

    cuota_cabeza = int(umb * _CUOTA_CABEZA)
    ancho = _ancho_numero(total_lineas)
    bloque_cabeza = _tomar([_cortar_linea(l) for l in crudas_cabeza], cuota_cabeza,
                           sobrecoste=ancho)
    cuota_cola = umb - sum(len(l.encode("utf-8")) + 1 + ancho for l in bloque_cabeza)
    bloque_cola = _tomar([_cortar_linea(l) for l in crudas_cola],
                         max(0, cuota_cola), desde_el_final=True, sobrecoste=ancho)

    # Cuentas HONESTAS: sobre las lineas que de verdad quedaron.
    vistas = len(bloque_cabeza) + len(bloque_cola)
    omitidas = max(0, total_lineas - vistas)
    bytes_vistos = sum(len(l.encode("utf-8")) + 1
                       for l in crudas_cabeza[:len(bloque_cabeza)])
    if bloque_cola:
        bytes_vistos += sum(len(l.encode("utf-8")) + 1
                            for l in crudas_cola[-len(bloque_cola):])
    bytes_omitidos = max(0, total_bytes - bytes_vistos)

    que = f" de {tool}" if tool else ""
    # Si la tool YA habia recortado (leer_archivo con limit explicito deja su
    # marcador '... [TRUNCADO: mostrando lineas A-B de T'), la cabecera lo
    # dice: lo guardado es SOLO ese tramo. 'NO se perdio nada' sobre un
    # fichero recortado antes del offload era mentira (juez 2026-08-24).
    m_tr = _RE_TRUNCADO_TOOL.search(texto)
    if m_tr:
        a, b, t = m_tr.group(1), m_tr.group(2), m_tr.group(3)
        guardado = (f"Guardado SOLO el tramo {a}-{b}: el fichero tiene {t} "
                    f"lineas (leer_archivo <ruta> offset={int(b) + 1} para "
                    f"seguir, o limit mayor).")
    elif handle:
        guardado = "NO se perdio nada: esta guardada."
    else:
        # Sin handle (offload apagado, o el disco fallo) lo omitido NO esta
        # en ningun lado: decir 'esta guardada' en la cabecera y 'no se
        # guardo handle' en el pie era una contradiccion en la misma
        # observacion (revision adversarial 2026-08-24).
        guardado = "Lo omitido NO se guardo: no hay handle ni fichero."
    # El marcador de FALLO viaja EN LA CABECERA: los clasificadores de rio
    # abajo (cli legacy `result[:120]`, la especulacion de loop.py, _linea_tool
    # de compactacion) leen \bERROR\b en la primera linea, y sin esto un
    # traceback spilleado se clasificaba como exito — el ERROR del contenido
    # quedaba enterrado bajo esta cabecera (revision adversarial 2026-08-23).
    marca = " ERROR" if es_fallo_primera_linea(texto, tool) else ""
    partes = [
        f"[SALIDA GRANDE{que}{marca}: {total_lineas} lineas, {_fmt_bytes(total_bytes)}. "
        f"NO esta entera aca: faltan {omitidas} lineas "
        f"({_fmt_bytes(bytes_omitidos)}). {guardado}]"
    ]
    # Cabeza y cola NUMERADAS con su numero real (ver _numerar) y el hueco
    # marcado entre ambas: 'primeras 15' + 'ultimas 5' sin numeros dejaba al
    # modelo pidiendo `recuperar` a ciegas en el medio.
    if bloque_cabeza:
        partes.append(f"--- primeras {len(bloque_cabeza)} lineas "
                      f"(1-{len(bloque_cabeza)} de {total_lineas}) ---")
        partes.extend(_numerar(bloque_cabeza, 1, total_lineas))
    if bloque_cola:
        ini = total_lineas - len(bloque_cola) + 1
        if omitidas:
            partes.append(f"... [{omitidas} lineas omitidas] ...")
        partes.append(f"--- ultimas {len(bloque_cola)} lineas "
                      f"({ini}-{total_lineas}, el FINAL) ---")
        partes.extend(_numerar(bloque_cola, ini, total_lineas))

    if handle:
        # REFERENCIA (contrato dsh): handle + ruta real + bytes EXACTOS + la
        # instruccion concreta. El rango de ejemplo existe de verdad: un
        # ejemplo fuera de rango entrena al modelo a pedir lineas que no hay.
        # La ruta va porque `recuperar` es solo una de las vias: con la ruta,
        # `leer_archivo` y `buscar` (las tools que el modelo SIEMPRE tiene)
        # tambien llegan al contenido completo.
        ini_ej = min(len(bloque_cabeza) + 1, total_lineas)
        fin_ej = min(ini_ej + _VENTANA_DEFECTO - 1, total_lineas)
        donde = f" -> fichero: {ruta}" if ruta else ""
        partes.append(
            f"[COMPLETO en {handle} ({total_lineas} lineas, {total_bytes} "
            f"bytes exactos){donde}. Para ver mas usa la herramienta "
            f"recuperar, NO repitas la llamada original:]\n"
            f"  recuperar {handle} lineas {ini_ej}-{fin_ej}   (rango de lineas, "
            f"1-{total_lineas})\n"
            f"  recuperar {handle} buscar=<texto>   (lineas que casan, con "
            f"{_CONTEXTO_BUSCAR} de contexto)")
        if ruta:
            partes.append(
                f"  leer_archivo {ruta} offset={ini_ej}   (el fichero completo "
                f"en disco)\n"
                f"  buscar <texto> | {ruta}   (grep sobre el fichero completo)")
    else:
        partes.append("[el resto NO esta disponible: no se guardo handle]")
    return "\n".join(partes)


def formatear_observacion(contenido, tool: str = "", args: str = "",
                          umbral: int | None = None) -> str:
    """El punto UNICO que cablea el integrador: umbral de bytes en el
    formateador de observaciones.

    Bajo el umbral devuelve el contenido intacto (sin tocar disco). Por encima,
    lo guarda y devuelve el resumen con el handle + la ruta real del fichero.
    RESILIENCIA (regla dsh): si el disco falla, se conserva el resultado
    INLINE (cabeza+cola, truncado al umbral) sin handle y se avisa degradado —
    un fallo de almacenamiento NUNCA convierte una llamada exitosa en error.
    """
    texto, crudo = _preparar(contenido)
    umb = _umbral_efectivo(umbral)
    if len(crudo) <= umb:
        return texto
    ruta = ""
    try:
        handle = guardar(texto, tool, args)
        ruta = ruta_de(handle)
    except (OSError, ValueError) as exc:
        _degradar("formatear_observacion", exc)
        handle = ""
    return resumir_para_modelo(texto, tool=tool, handle=handle, umbral=umb,
                               ruta=ruta)


# ── Recuperacion (pensada para exponerse como TOOL del agente) ────────────────

def _entero(valor):
    """int o None. Los argumentos llegan del modelo: '200', 200, '200.0', ''."""
    if valor is None or valor == "":
        return None
    try:
        return int(str(valor).strip())
    except (TypeError, ValueError):
        try:
            return int(float(str(valor).strip()))
        except (TypeError, ValueError):
            return None


def _recortar_bytes(texto: str, max_bytes: int) -> tuple:
    """(texto recortado a max_bytes, se_recorto). Corta en frontera de
    codepoint (errors='ignore'), nunca a mitad de un caracter utf-8, y ademas
    en frontera de LINEA: una ultima linea partida a la mitad ('  2') se lee
    como un dato y no como un corte."""
    crudo = texto.encode("utf-8")
    if len(crudo) <= max_bytes:
        return texto, False
    salida = crudo[:max_bytes].decode("utf-8", "ignore")
    corte = salida.rfind("\n")
    # rfind<=0 = no hay linea entera que salvar (p.ej. un minificado de 400 KB
    # en una sola linea): ahi se devuelve el corte por bytes, que es lo unico
    # que hay.
    return (salida[:corte] if corte > 0 else salida), True


def recuperar(handle, desde=None, hasta=None, buscar=None,
              max_bytes: int | None = None) -> str:
    """Devuelve un trozo de una salida offloadeada. NUNCA lanza.

    Para registrarla como herramienta del agente (cognia/agent/tools.py):

        desc   = DESC_RECUPERAR   (ver arriba en este modulo)
        params = PARAMS_RECUPERAR:
            handle  (string, requerido)  el 'res:3f2a1b' del resumen
            lineas  (string, opcional)   rango 1-indexado inclusivo, '200-260'
            buscar  (string, opcional)   texto a buscar, sin case; +-2 lineas

    Modos (excluyentes, gana `buscar`):
      - buscar='foo'      -> las lineas que contienen 'foo' con 2 de contexto
                             y su NUMERO de linea (para pedir el rango exacto).
      - desde/hasta       -> ese rango, 1-indexado e inclusivo.
      - nada              -> las primeras 60 lineas.
    `desde` acepta ademas el rango entero ('200-260'), que es como lo escribe
    el modelo la mitad de las veces.

    Todo sale acotado a `max_bytes` (por defecto 4x el umbral): recuperar un
    trozo tiene que caber en la ventana igual que la observacion original. Los
    errores se devuelven como texto "ERROR: ..." con la lista de handles vivos:
    el error ES el siguiente prompt, y lanzar una excepcion aca mataria el
    turno por una equivocacion del modelo que el modelo puede corregir solo.
    """
    tope = _entero(max_bytes) or (umbral_bytes() * _FACTOR_MAX_BYTES)
    tope = max(200, tope)

    h = normalizar_handle(handle)
    if not h:
        return (f"ERROR: '{str(handle)[:40]}' no es un handle valido. Un handle "
                f"es 'res:' + 6 hex, tal como aparecio en el resumen "
                f"(ej: res:3f2a1b).{_pista_handles()}")

    ruta, ses = _buscar_fichero(h)
    if ruta is None:
        return (f"ERROR: el handle {h} no existe (ya se podo o nunca se guardo). "
                f"No lo inventes: usa uno de los que salieron en un resumen."
                f"{_pista_handles()}")
    try:
        contenido = _leer(ruta)
    except OSError as exc:
        _degradar("recuperar", exc)
        return f"ERROR: no se pudo leer {h} en disco ({exc.__class__.__name__})."

    lineas = _lineas(contenido)
    total = len(lineas)
    meta = _meta_de(ses, h)
    tool = meta.get("tool", "")
    marca = f"{h}" + (f" - {tool}" if tool else "")
    if total == 0:
        # Sin esto la respuesta era "pedi un rango dentro de 1-0", que es una
        # instruccion imposible: el modelo reintentaba en vez de seguir.
        return f"[{marca} - la salida guardada esta VACIA (0 lineas)]"

    if buscar is not None and str(buscar).strip():
        return _buscar_en(lineas, str(buscar).strip(), marca, total, tope)

    # `desde` puede venir como rango entero ('200-260'): se desarma aca.
    if hasta is None and isinstance(desde, str):
        m = _RE_RANGO.match(desde.strip())
        if m:
            desde, hasta = m.group(1), m.group(2)
    ini = _entero(desde)
    fin = _entero(hasta)
    if ini is None and fin is None:
        ini, fin = 1, min(_VENTANA_DEFECTO, total)
    elif ini is None:
        ini = max(1, fin - _VENTANA_DEFECTO + 1)
    elif fin is None:
        fin = min(total, ini + _VENTANA_DEFECTO - 1)

    if ini < 1:
        ini = 1
    if ini > total:
        return (f"ERROR: {h} tiene {total} lineas y pediste desde la {ini}. "
                f"Pedi un rango dentro de 1-{total}.")
    if fin < ini:
        return (f"ERROR: rango invertido ({ini}-{fin}). El formato es "
                f"'lineas <desde>-<hasta>' con desde <= hasta.")
    fin = min(fin, total)

    trozo = "\n".join(lineas[ini - 1:fin])
    trozo, recortado = _recortar_bytes(trozo, tope)
    cab = f"[{marca} - lineas {ini}-{fin} de {total}]"
    if recortado:
        cab += (f"\n[recortado a {tope} bytes: pedi un rango mas chico para "
                f"ver el resto]")
    return cab + "\n" + trozo


def _buscar_en(lineas: list, aguja: str, marca: str, total: int,
               tope: int) -> str:
    """Lineas que contienen `aguja` (sin case) con _CONTEXTO_BUSCAR de contexto,
    numeradas y con los bloques solapados fundidos en uno."""
    baja = aguja.lower()
    aciertos = [i for i, l in enumerate(lineas) if baja in l.lower()]
    es_acierto = set(aciertos)      # `in` sobre la lista era O(n) por linea
    if not aciertos:
        return (f"[{marca} - 0 lineas casan con {aguja!r} (de {total})]\n"
                f"No esta. Proba con otra palabra, o pedi un rango de lineas "
                f"(1-{total}).")

    mostrados = aciertos[:_MAX_ACIERTOS]
    quiero = set()
    for i in mostrados:
        for j in range(max(0, i - _CONTEXTO_BUSCAR),
                       min(total, i + _CONTEXTO_BUSCAR + 1)):
            quiero.add(j)

    partes = []
    previo = None
    for j in sorted(quiero):
        if previo is not None and j > previo + 1:
            partes.append("   ...")
        # El '>' marca el acierto; el numero de linea es lo que deja al modelo
        # pedir despues el rango exacto con `lineas`.
        partes.append(f"{'>' if j in es_acierto else ' '} {j + 1}: {lineas[j]}")
        previo = j

    cuerpo, recortado = _recortar_bytes("\n".join(partes), tope)
    cab = (f"[{marca} - {len(aciertos)} lineas casan con {aguja!r} (de {total}), "
           f"+-{_CONTEXTO_BUSCAR} de contexto]")
    if len(aciertos) > len(mostrados):
        cab += f"\n[se muestran los primeros {len(mostrados)} aciertos]"
    if recortado:
        cab += f"\n[recortado a {tope} bytes: afina la busqueda]"
    return cab + "\n" + cuerpo


def herramienta_recuperar(args: str, ctx: dict | None = None) -> str:
    """Adaptador al protocolo texto del loop: fn(args, ctx) -> str.

    Acepta lo que el modelo escribe de verdad:
        res:3f2a1b
        res:3f2a1b | 200-260
        res:3f2a1b lineas=200-260
        res:3f2a1b buscar=timeout
    """
    texto = (args or "").strip()
    if not texto:
        return ("ERROR: falta el handle. Uso: recuperar res:3f2a1b lineas 200-260"
                + _pista_handles())
    # `buscar=` se lleva TODO lo que viene detras (puede tener espacios y '|').
    aguja = None
    m = re.search(r"\bbuscar\s*=\s*(.+)$", texto, re.IGNORECASE | re.DOTALL)
    if m:
        aguja = m.group(1).strip().strip("'\"")
        texto = texto[:m.start()]
    resto = [t for t in re.split(r"[|\s]+", texto.strip()) if t]
    if not resto:
        return recuperar("", buscar=aguja)
    # El handle es el PRIMER token que lo parezca, no el primero a secas: el
    # modelo repite a veces el nombre de la tool ("recuperar res:3f2a1b 1-5") y
    # eso devolvia "'recuperar' no es un handle valido" con el handle ahi al lado.
    pos = next((i for i, t in enumerate(resto) if normalizar_handle(t)), 0)
    handle = resto[pos]
    rango, sueltos = None, []
    for token in resto[:pos] + resto[pos + 1:]:
        token = token.strip().lower()
        if token.startswith("lineas="):
            token = token.split("=", 1)[1]
        if token in ("lineas", "linea", "lines", "recuperar"):
            continue
        if _RE_RANGO.match(token):
            rango = token if rango is None else rango
        elif token.isdigit():
            sueltos.append(token)
    if rango is None and sueltos:
        # "res:x 200 260": el split por espacios parte el rango en dos y antes
        # se perdia el final (se servia 200-259, no lo que el modelo pidio).
        rango = sueltos[0] if len(sueltos) == 1 else f"{sueltos[0]}-{sueltos[1]}"
    return recuperar(handle, desde=rango, buscar=aguja)


def _pista_handles() -> str:
    """Los handles vivos, para que el error se pueda arreglar sin adivinar."""
    vivos = listar()[:5]
    if not vivos:
        return ""
    return " Handles vivos: " + ", ".join(
        f"{e['handle']} ({e['tool'] or 'tool'}, {e['lineas']} lineas)"
        for e in vivos)


# ── Inventario y poda ─────────────────────────────────────────────────────────

def listar(sesion: str | None = None) -> list:
    """Handles vivos de la sesion, la mas nueva primero.

    Cada entrada: {handle, tool, args, bytes, lineas, edad_s, sesion, ruta}.
    Los datos se leen de la meta y se COMPLETAN con el stat real del .txt: si
    la meta se perdio, el inventario sigue diciendo la verdad sobre el tamano.
    """
    ses = sesion or sesion_actual()
    try:
        ficheros = [p for p in _dir_sesion(ses).iterdir()
                    if p.suffix == _SUFIJO_TXT and p.is_file()]
    except OSError:
        return []
    ahora = datetime.now().timestamp()
    salida = []
    for p in sorted(ficheros, key=lambda f: _mtime(f), reverse=True):
        handle = _handle_de_fichero(p)
        meta = _meta_de(ses, handle)
        try:
            tam = p.stat().st_size
        except OSError:
            tam = int(meta.get("bytes", 0))
        salida.append({
            "handle": handle,
            "tool": meta.get("tool", ""),
            "args": meta.get("args", ""),
            "bytes": tam,
            "lineas": int(meta.get("lineas", 0)),
            "edad_s": max(0, int(ahora - _mtime(p))),
            "sesion": ses,
            "ruta": str(p),
        })
    return salida


def resumen_listado(sesion: str | None = None) -> str:
    """Una linea por handle vivo, lista para pintar en el CLI o darsela al
    modelo cuando pregunta que tiene guardado."""
    vivos = listar(sesion)
    if not vivos:
        return "sin salidas guardadas"
    return "\n".join(
        f"{e['handle']}  {e['tool'] or '-':<16} {e['lineas']:>6} lineas  "
        f"{_fmt_bytes(e['bytes']):>9}  hace {e['edad_s']}s"
        for e in vivos)


def podar(max_sesiones: int = _MAX_SESIONES, max_mb: int = _MAX_MB) -> dict:
    """Limpieza: retiene las `max_sesiones` mas recientes y despues, si el
    almacen sigue pasando `max_mb`, borra las sesiones mas viejas hasta entrar.

    NUNCA toca la sesion en curso ni lanza. Si con todo lo demas borrado la
    sesion actual sola pasa el presupuesto, sale `excedido=True`: borrarle al
    agente lo que puede estar leyendo es peor que pasarse de MB.
    """
    actual = sesion_actual()
    borradas, liberados = [], 0
    n_ses = _entero(max_sesiones)
    n_mb = _entero(max_mb)
    n_ses = _MAX_SESIONES if n_ses is None else n_ses
    n_mb = _MAX_MB if n_mb is None else n_mb

    for ses in sesiones()[max(0, n_ses):]:
        if ses == actual:
            continue
        liberados += _borrar_sesion(ses, borradas)

    presupuesto = max(0, n_mb) * 1024 * 1024
    total = _bytes_totales()
    if total > presupuesto:
        # De la mas vieja a la mas nueva, siempre saltando la sesion en curso.
        for ses in reversed(sesiones()):
            if total <= presupuesto:
                break
            if ses == actual:
                continue
            libre = _borrar_sesion(ses, borradas)
            liberados += libre
            total -= libre

    # Un solo recuento final: con dos, `bytes_restantes` y `excedido` podian
    # salir de walks distintos y contradecirse.
    restantes = _bytes_totales()
    return {
        "sesiones_borradas": borradas,
        "bytes_liberados": liberados,
        "bytes_restantes": restantes,
        "excedido": restantes > presupuesto,
    }


def _borrar_sesion(sesion: str, acumulador: list) -> int:
    """Borra una sesion entera; devuelve los bytes liberados (0 si fallo)."""
    ruta = _dir_sesion(sesion)
    peso = _peso_dir(ruta)
    try:
        shutil.rmtree(ruta)
    except OSError as exc:
        _degradar("podar", exc)
        return 0
    acumulador.append(sesion)
    return peso


def _peso_dir(ruta: Path) -> int:
    total = 0
    try:
        for p in ruta.rglob("*"):
            try:
                if p.is_file():
                    total += p.stat().st_size
            except OSError:
                continue
    except OSError:
        return total
    return total


def _bytes_totales() -> int:
    return _peso_dir(dir_offload())


def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def _degradar(donde: str, exc: Exception) -> None:
    """El offloading es una MEJORA del formateador: si el disco falla, se avisa
    (logger + el avisador del CLI si esta registrado) y el turno sigue. Nunca
    se mata la observacion por esto."""
    motivo = f"{donde}: {exc.__class__.__name__}: {exc}"
    logger.warning("harness.offloading degradado: %s", motivo)
    _ULTIMO_ERROR.clear()
    _ULTIMO_ERROR.update(motivo=motivo,
                         ts=datetime.now().isoformat(timespec="seconds"))
    if _AVISADOR is not None:
        try:
            _AVISADOR("offloading", motivo)
        except Exception as exc2:
            # El aviso jamas puede romper el camino que esta avisando.
            logger.warning("harness.offloading avisador roto: %s", exc2)


def estado() -> dict:
    """Foto del subsistema para la puerta /offload del CLI: encendido, almacen,
    knobs efectivos, handles vivos y la telemetria del ultimo spill/error."""
    vivos = listar()
    return {
        "activo": activo(),
        "dir": str(dir_offload()),
        "sesion": sesion_actual(),
        "umbral": umbral_bytes(),
        "cabeza": cabeza_defecto(),
        "cola": cola_defecto(),
        "handles": len(vivos),
        "bytes_sesion": sum(e["bytes"] for e in vivos),
        "ultimo_spill": dict(_ULTIMO_SPILL),
        "ultimo_error": dict(_ULTIMO_ERROR),
    }
