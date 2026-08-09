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

Regla de recorte (2026-08-09, obra "nivel SOTA", A5): el catalogo por defecto
es una ALLOWLIST — el set CORE de ~12 tools ortogonales de
cognia.agent.tools.CORE_TOOLS (leer/escribir/editar/borrar/listar/buscar/
ejecutar/tests/generar_codigo/delegar/recordar/calcular) — y no una denylist:
con denylist, cada tool nueva registrada engordaba el catalogo default en
silencio, que es exactamente como se llego a las 46-79 tools que el A/B del
2026-07-25 midio como degradacion (camino feliz 4.25/5 -> 2.5/5). Las familias
opt-in (pantalla_/escena_/imagen_/web_/repo_a_prompt) entran SOLO con su flag
activo: el opt-in explicito del dueno gana al recorte de UX. El modo AVANZADO
sigue mostrando todo, y las tools fuera del catalogo siguen siendo invocables
(run_tool no filtra por esto): solo dejan de anunciarse en el prompt.
"""
from __future__ import annotations

from typing import Optional

K_UI_MODE = "COGNIA_UI_MODE"   # "sencillo" (default) | "avanzado"


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
    """Set de tools visibles para el modelo segun el modo. En avanzado: todas.
    En sencillo: el catalogo CORE (~12, allowlist) mas las familias opt-in
    cuyo flag esta activo ('responder' se maneja aparte en el loop, no esta en
    el registry, asi que no hace falta preservarlo aca).

    El import de tools es perezoso y con fallback a un set literal: este
    modulo es UX puro y no puede caerse (ni arrastrar el import pesado de
    tools) por culpa del catalogo."""
    names = set(all_names)
    if not is_simple(override):
        return names
    try:
        from cognia.agent.tools import CORE_TOOLS, flag_de_optin, _flag_activo
    except Exception:
        # fallback degradable: el mismo CORE, congelado (si tools no importa,
        # el agente tampoco va a correr; esto solo protege al REPL/UI)
        CORE_TOOLS = {
            "leer_archivo", "escribir_archivo", "editar_archivo",
            "apendar_archivo", "borrar_archivo", "listar", "buscar",
            "ejecutar", "tests", "generar_codigo", "delegar_subtarea",
            "recordar", "calcular"}
        flag_de_optin = lambda n: ""          # noqa: E731
        _flag_activo = lambda f: False        # noqa: E731
    out = set()
    for n in names:
        flag = flag_de_optin(n)
        if flag:
            if _flag_activo(flag):
                out.add(n)
        elif n in CORE_TOOLS:
            out.add(n)
    return out
