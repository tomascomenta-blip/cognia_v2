"""
cognia/simple_mode.py
=====================
Modo SENCILLO (por defecto ON) para la version comercializable: cognia "solo
funciona" -- sin logs de detalle y con una paleta de herramientas recortada a
lo que le sirve a un usuario comun. El modo AVANZADO reactiva todo (logs de
proceso + todas las tools) para quien quiera ver que hace por dentro.

Es UX puro y deterministico: una preferencia persistida (~/.cognia/config.env,
mismo mecanismo que user_prefs) + dos predicados. Sin dependencias del modelo.
Testeable sin disco pasando el valor por override.

Regla de recorte: se ocultan las tools de INTROSPECCION/DESARROLLO que a un
usuario comun le parecen ruido (git, knowledge-graph, validadores de sintaxis,
notas de trabajo, http, arbol/contar-lineas, delegar/crear-herramienta). NO se
oculta nada que una tarea cotidiana necesite (leer/escribir/buscar archivos,
ejecutar, tests, generar_codigo, calcular, fecha, memoria de usuario, resumir).
El agente sigue teniendo el pipeline de calidad (generar_codigo valida por
tests), asi que recortar los validadores sueltos no le baja la capacidad.
"""
from __future__ import annotations

from typing import Optional

K_UI_MODE = "COGNIA_UI_MODE"   # "sencillo" (default) | "avanzado"

# Tools ocultas en modo sencillo (aparecen solo en avanzado). Ver docstring.
HIDDEN_IN_SIMPLE = frozenset({
    "git_estado", "git_diff", "git_log",
    "kg_buscar", "kg_agregar",
    "py_validar", "json_validar",
    "arbol", "contar_lineas",
    "http_get",
    "notas", "anotar",
    "delegar_subtarea", "crear_herramienta",
    # diagnostico del pipeline de escena (util para una IA/dev, ruido para el
    # usuario comun, que solo quiere crear/editar la escena):
    "atribuir_fallo", "reejecutar_etapa",
})


def get_ui_mode(override: Optional[str] = None) -> str:
    """Modo de UI actual. override para tests; si no, la preferencia persistida;
    default 'sencillo' (la version comercializable arranca simple)."""
    if override is not None:
        return override
    try:
        from cognia.user_prefs import load_prefs
        val = load_prefs().get(K_UI_MODE)
    except Exception:
        val = None
    # tolerar tambien os.environ directo (config.env se carga ahi al arrancar)
    if not val:
        import os
        val = os.environ.get(K_UI_MODE)
    return (val or "sencillo").strip().lower()


def is_simple(override: Optional[str] = None) -> bool:
    return get_ui_mode(override) != "avanzado"


def set_ui_mode(mode: str) -> str:
    """Persiste el modo ('sencillo'|'avanzado'); devuelve el valor normalizado."""
    mode = "avanzado" if str(mode).strip().lower().startswith("avan") else "sencillo"
    try:
        from cognia.user_prefs import save_pref
        save_pref(K_UI_MODE, mode)
    except Exception:
        import os
        os.environ[K_UI_MODE] = mode
    return mode


def should_show_detail(markup_line: str, override: Optional[str] = None) -> bool:
    """True si esta linea DEBE imprimirse. En modo sencillo se suprimen SOLO las
    lineas de detalle/proceso ('[detail]'): los resultados, avisos y errores
    ([ok_cl]/[warn_cl]/[err_cl]/paneles) SIEMPRE se muestran -- 'solo funciona'
    no es 'oculta los errores'."""
    if not is_simple(override):
        return True
    s = markup_line if isinstance(markup_line, str) else str(markup_line)
    return "[detail]" not in s


def visible_tools(all_names, override: Optional[str] = None):
    """Set de tools visibles para el usuario segun el modo. En avanzado: todas.
    En sencillo: todas menos HIDDEN_IN_SIMPLE ('responder' se maneja aparte en
    el loop, no esta en el registry, asi que no hace falta preservarlo aca)."""
    names = set(all_names)
    if not is_simple(override):
        return names
    return {n for n in names if n not in HIDDEN_IN_SIMPLE}
