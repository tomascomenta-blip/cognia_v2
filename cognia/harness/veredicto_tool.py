"""
cognia/harness/veredicto_tool.py -- exito/fallo de un RESULTADO de tool (2026-08-24)
==================================================================================
POR QUE EXISTE: cinco sitios distintos (agent/tools.run_tool, agent/loop,
harness/offloading, harness/compactacion, harness/render_tools y el bucle
legacy de cli.py) decidian si una tool FALLO mirando `\\bERROR\\b` en la
cabeza del texto. Esa regla no distingue el marcador del registry
('RESULTADO x ERROR: ...') del CONTENIDO que la tool trae: leer un log cuya
primera linea dice '2026-08-24T10:00:00 ERROR [cache] ...' salia como fallo,
con vineta ROJA, y el offload le clavaba ' ERROR' en la cabecera; el modelo
leia "fallo" y la tarea moria en bucle (cazado por el juez tecleando en el
REPL real, 2026-08-24, fixture grande.log).

LA REGLA: para las tools cuyo resultado es CONTENIDO AJENO (lecturas,
listados, busquedas: TOOLS_CONTENIDO) el marcador de fallo solo cuenta si
aparece ANTES del primer ': ' de la primera linea -- o sea en el prefijo
'RESULTADO <tool> <objeto>' que escribe el registry, nunca en lo que sigue al
':' (que ya es el contenido). Ademas se ignora lo entrecomillado: el patron
de una busqueda ('RESULTADO buscar \\'ERROR\\': a | b') es un dato, no un
veredicto. Para el resto (ejecucion, escritura, validadores) se conserva la
regla laxa de siempre sobre la primera linea: 'py_validar x.py: ERROR ...' es
un fallo real que vive despues del ':'.

Y para la EJECUCION (ejecutar/tests) el veredicto es el exit code que va en
el prefijo '(exit N)': la salida de un `grep ERROR` es contenido, no un fallo
(cazado re-tecleando la misma tarea: 'grep -oE "ERROR [..]" | uniq -c' con
exit 0 salia en rojo y disparaba el 'No se pudo completar' del cierre E8).
Sin '(exit N)' en el prefijo (comando BLOQUEADO, tool reventada) rige la
regla laxa, y en tools.run_tool el exit REAL medido manda por encima.

Todos los formatos del registry (agent/tools.py) caben en la regla:
    RESULTADO leer_archivo x.log ERROR: offset=...      -> fallo
    RESULTADO leer_archivo x.log: ERROR de arranque     -> contenido, OK
    RESULTADO buscar ERROR: uso: buscar <patron>        -> fallo
    RESULTADO buscar 'ERROR': a.py:3 | b.py:9           -> contenido, OK
    RESULTADO ejecutar (exit 1): Traceback ...          -> fallo (exit)
    RESULTADO ejecutar (exit 0): 56 ERROR [db]          -> contenido, OK
    RESULTADO ejecutar ERROR: comando vacio             -> fallo (laxa)
    RESULTADO py_validar x.py: ERROR linea 3: ...       -> fallo (laxa)
    [SALIDA GRANDE de ejecutar ERROR: 300 lineas ...]   -> fallo (offload)

CONTRATO: funciones puras, sin dependencias, nunca lanzan. El exit code REAL
de un proceso sigue mandando por encima de esto (tools.run_tool lo aplica
DESPUES): esta regla solo decide cuando no hay exit medido.
"""
from __future__ import annotations

import re

# Tools cuyo resultado es contenido ajeno: lo que hay despues del ':' es un
# fichero, un listado o unos aciertos, nunca un veredicto de la tool.
TOOLS_CONTENIDO = frozenset({
    "leer_archivo", "recuperar", "contar_lineas",
    "listar", "arbol", "git_estado", "git_log", "git_diff",
    "buscar", "buscar_en_repo", "buscar_ficheros", "web_buscar", "web_abrir",
    "kg_buscar", "recordar", "bitacora_buscar", "notas", "cuaderno",
    "repo_map", "code_grafo", "docs_repo", "docs_libreria", "preguntar_repo",
    "repo_a_prompt", "http_get", "ver_salida", "ctx_grep", "ctx_leer",
})

_RE_FALLO = re.compile(r"\bERROR\b|\(exit -?[1-9]\d*\)")
_RE_EXIT = re.compile(r"\(exit (-?\d+)\)")
_RE_PREFIJO = re.compile(r"^\s*(?:\[SALIDA GRANDE de\s+)?(?:RESULTADO\s+)?([A-Za-z_][\w-]*)")
_RE_ENTRECOMILLADO = re.compile(r"'[^']*'|\"[^\"]*\"")
_RE_OFFLOAD = re.compile(r"^\s*\[SALIDA GRANDE de\s+([A-Za-z_][\w-]*)")


def primera_linea(texto: str) -> str:
    return (texto or "").split("\n", 1)[0][:200]


def tool_de(texto: str) -> str:
    """El nombre de la tool que escribio el RESULTADO, leido de su prefijo
    ('RESULTADO <tool> ...' o la cabecera del offload '[SALIDA GRANDE de
    <tool> ...'). '' si la cabeza no trae prefijo."""
    primera = primera_linea(texto)
    m = _RE_OFFLOAD.match(primera)
    if m:
        return m.group(1)
    m = re.match(r"^\s*RESULTADO\s+([A-Za-z_][\w-]*)", primera)
    return m.group(1) if m else ""


def cabeza_de_veredicto(primera: str) -> str:
    """La parte de la primera linea donde PUEDE vivir el marcador de fallo de
    una tool de contenido: hasta el primer ': ' (o el final), y sin lo
    entrecomillado."""
    corte = primera.find(": ")
    cabeza = primera if corte < 0 else primera[:corte]
    return _RE_ENTRECOMILLADO.sub("", cabeza)


def es_fallo(texto: str, tool: str = "") -> bool:
    """True si el RESULTADO de `tool` es un fallo de la TOOL (no de su
    contenido). Sin `tool` se intenta leer del prefijo; si tampoco hay, rige
    la regla laxa (compatibilidad con el resto del repo)."""
    primera = primera_linea(texto)
    if not primera.strip():
        return False
    nombre = (tool or "").strip() or tool_de(primera)
    cabeza = cabeza_de_veredicto(primera)
    if nombre in TOOLS_CONTENIDO:
        return bool(_RE_FALLO.search(cabeza))
    # Ejecucion con exit en el prefijo: el exit ES el veredicto (ERROR en el
    # prefijo tambien cuenta: 'RESULTADO ejecutar ERROR (exit 1): ...').
    if _RE_EXIT.search(cabeza):
        return bool(_RE_FALLO.search(cabeza))
    return bool(_RE_FALLO.search(primera[:120]))


def es_exito(texto: str, tool: str = "") -> bool:
    return not es_fallo(texto, tool)
