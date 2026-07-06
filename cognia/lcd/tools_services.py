"""
cognia/lcd/tools_services.py — Herramientas AI-NATIVAS de SERVICIO para LCD.

Tres servicios sobre la escena estructurada (scene.py) que tools_lcd.py no
cubre: export/import a archivo (exporters.py), undo/redo (history.py) y
plantillas listas para arrancar una escena compuesta (templates.py). Mismo
patron que tools_lcd.py: funciones planas + @tool, la escena activa vive en
ctx['working_memory']['_lcd_scene']['escena'] (se reusa _active/_scenes de
tools_lcd.py, no se duplica el acceso). El historial de undo/redo vive junto,
en ctx['working_memory']['_lcd_history'] (una SceneHistory por sesion/tarea).
"""
from __future__ import annotations

import re as _re

from cognia.agent.tools import tool
from cognia.lcd.exporters import export_scene, import_scene_json
from cognia.lcd.history import SceneHistory
from cognia.lcd.templates import get_template, list_templates
from cognia.lcd.tools_lcd import _active, _scenes


def _history(ctx) -> SceneHistory:
    """El SceneHistory de la tarea (uno por ctx['working_memory'], igual que
    _lcd_scene lo es por tarea). Se crea perezosamente la primera vez."""
    wm = ctx.setdefault("working_memory", {})
    hist = wm.get("_lcd_history")
    if hist is None:
        hist = wm["_lcd_history"] = SceneHistory()
    return hist


# ── tools AI-nativas ─────────────────────────────────────────────────────────

@tool("escena_exportar",
      "escena_exportar <svg|json> [| archivo]  -- exporta la escena activa a "
      "SVG o JSON (a archivo si se da; si no, un extracto del contenido)")
def _escena_exportar(args, ctx):
    scene = _active(ctx)
    if scene is None:
        return ("RESULTADO escena_exportar ERROR: no hay escena activa "
                "(usa escena_crear o escena_plantilla primero)")
    parts = _re.split(r"\s*\|\s*", args.strip(), maxsplit=1)
    fmt = parts[0].strip().lower()
    path = parts[1].strip() if len(parts) == 2 and parts[1].strip() else None
    if fmt not in ("svg", "json"):
        return f"RESULTADO escena_exportar ERROR: formato '{fmt}' invalido (svg|json)"
    try:
        out = export_scene(scene, fmt, path)
    except Exception as e:
        return f"RESULTADO escena_exportar ERROR: {e}"
    if path:
        return f"RESULTADO escena_exportar: {fmt} escrito en {out} ({len(scene.objects)} objetos)"
    extracto = out[:200].replace("\n", " ")
    return f"RESULTADO escena_exportar ({fmt}, {len(out)} chars): {extracto}"


@tool("escena_importar",
      "escena_importar <archivo.json>          -- carga una escena desde JSON "
      "a la escena activa")
def _escena_importar(args, ctx):
    path = args.strip()
    if not path:
        return "RESULTADO escena_importar ERROR: falta la ruta del archivo"
    try:
        scene = import_scene_json(path)
    except Exception as e:
        return f"RESULTADO escena_importar ERROR: no se pudo leer '{path}': {e}"
    _history(ctx).push(scene)
    _scenes(ctx)["escena"] = scene
    return f"RESULTADO escena_importar: {len(scene.objects)} objetos cargados desde {path}"


@tool("escena_deshacer",
      "escena_deshacer                         -- deshace el ultimo cambio "
      "de la escena activa (undo)")
def _escena_deshacer(args, ctx):
    prev = _history(ctx).undo()
    if prev is None:
        return "RESULTADO escena_deshacer ERROR: no hay estados previos para deshacer"
    _scenes(ctx)["escena"] = prev
    return f"RESULTADO escena_deshacer: escena restaurada ({len(prev.objects)} objetos)"


@tool("escena_rehacer",
      "escena_rehacer                          -- rehace el ultimo deshacer "
      "sobre la escena activa (redo)")
def _escena_rehacer(args, ctx):
    nxt = _history(ctx).redo()
    if nxt is None:
        return "RESULTADO escena_rehacer ERROR: no hay estados para rehacer"
    _scenes(ctx)["escena"] = nxt
    return f"RESULTADO escena_rehacer: escena restaurada ({len(nxt.objects)} objetos)"


@tool("escena_plantilla",
      "escena_plantilla <nombre>               -- carga una plantilla lista "
      "(mesa_servida, cielo, sala, ...) como escena activa")
def _escena_plantilla(args, ctx):
    nombre = args.strip().lower()
    if not nombre:
        return (f"RESULTADO escena_plantilla ERROR: falta el nombre. "
                f"Validas: {', '.join(list_templates())}")
    scene = get_template(nombre)
    if scene is None:
        return (f"RESULTADO escena_plantilla ERROR: '{nombre}' no existe. "
                f"Validas: {', '.join(list_templates())}")
    _history(ctx).push(scene)          # checkpoint ANTES de quedar activa (undo)
    _scenes(ctx)["escena"] = scene
    return f"RESULTADO escena_plantilla: '{nombre}' cargada ({len(scene.objects)} objetos)"


# Import de este modulo = registro de las tools en el registry global (via el
# @tool decorator). load_service_tools() existe para llamarlo explicito y
# contar, mismo patron que load_lcd_tools() en tools_lcd.py.
def load_service_tools() -> int:
    """Devuelve cuantas tools de servicio LCD estan registradas."""
    from cognia.agent.tools import TOOLS
    return sum(1 for n in ("escena_exportar", "escena_importar", "escena_deshacer",
                           "escena_rehacer", "escena_plantilla")
               if n in TOOLS)
