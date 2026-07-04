"""
cognia_x/lcd/tools_lcd.py — Herramientas AI-NATIVAS de LCD (plan 12, Fase 0/1).

Convierte el pipeline LCD (scene.py/planner.py/renderer.py) en TOOLS invocables
por el agente MoM via el protocolo ACCION, para que una IA construya/edite/
consulte una escena ESTRUCTURADA (no pixeles) y la verifique con un oraculo
CERO-LLM. Es la primera familia de la biblioteca de herramientas AI-nativas.

Propiedades AI-nativas (ver 12_HERRAMIENTAS_IA_LCD_MOM.md §0):
  - E/S estructurada: la escena es un dict/JSON inspeccionable, no un canvas.
  - Verificable por oraculo: escena_crear devuelve el control composicional
    (objetos presentes + relacion satisfecha) medido cero-LLM.
  - Componible: cada tool devuelve un RESULTADO que el modelo encadena; la
    escena viva persiste en ctx['working_memory'] entre pasos de una tarea.
  - Auto-mejorable: registradas en el mismo registry que HERMES puede extender.

Concreto: funciones planas + el @tool decorator del registry. La escena activa
vive en working_memory['_lcd_scene'] (una por tarea; simple y suficiente).
"""
from __future__ import annotations

from cognia.agent.tools import tool
from cognia_x.lcd.planner import _find_objects, _find_relation, _tokens, plan
from cognia_x.lcd.scene import COLORS, Scene


# ── oraculo cero-LLM: control composicional de una escena vs su descripcion ──

def _relation_ok(scene: Scene, subj: str, rel: str, ref: str) -> bool:
    """Las POSICIONES de la escena satisfacen la relacion pedida (mismo criterio
    que lcd/eval.py — el oraculo del paper §8.1)."""
    a, b = scene.get(subj), scene.get(ref)
    if a is None or b is None:
        return False
    if rel == "on":
        return a.y < b.y and abs(a.x - b.x) < 0.25
    if rel == "above":
        return a.y < b.y - 0.05
    if rel == "below":
        return a.y > b.y
    if rel == "left_of":
        return a.x < b.x
    if rel == "right_of":
        return a.x > b.x
    return True


def control_check(scene: Scene, descripcion: str) -> dict:
    """Oraculo CERO-LLM: dada la escena y la descripcion que la origino, cuanta
    de la spec se cumple. Extrae objetos+relacion esperados con el MISMO parser
    del planner de reglas (autolabel por oraculo) y verifica presencia, conteo y
    relacion. Devuelve {present, count_ok, relation_ok, score, total}."""
    toks = _tokens(descripcion)
    found = _find_objects(toks)              # [(color, obj_key)]
    expected = [k for _, k in found]
    rel = _find_relation(descripcion)
    names = [o.name for o in scene.objects]
    present = all(e in names for e in expected)
    count_ok = len(names) >= len(expected) and len(expected) > 0
    relation_ok = True
    if len(expected) >= 2 and rel:
        relation_ok = _relation_ok(scene, expected[0], rel, expected[1])
    checks = [present, count_ok, relation_ok]
    return {"present": present, "count_ok": count_ok, "relation_ok": relation_ok,
            "score": sum(checks), "total": len(checks),
            "expected": expected, "relation": rel}


# ── estado: la escena viva de la tarea (persistente entre ACCIONes) ──────────

def _scenes(ctx) -> dict:
    return ctx.setdefault("working_memory", {}).setdefault("_lcd_scene", {})


def _active(ctx):
    return _scenes(ctx).get("escena")


def _describe(scene: Scene, max_objs: int = 8) -> str:
    parts = []
    for o in scene.objects[:max_objs]:
        rel = f" {o.relation} {o.ref}" if o.relation else ""
        parts.append(f"{o.name}@({o.x:.2f},{o.y:.2f}){rel}")
    return "; ".join(parts)


# ── tools AI-nativas ─────────────────────────────────────────────────────────

@tool("escena_crear",
      "escena_crear <descripcion>            -- construye una escena ESTRUCTURADA "
      "(objetos+relaciones) desde una descripcion y la verifica (control cero-LLM)")
def _escena_crear(args, ctx):
    desc = args.strip()
    if not desc:
        return "RESULTADO escena_crear ERROR: falta la descripcion de la escena"
    scene = plan(desc)
    if not scene.objects:
        return ("RESULTADO escena_crear ERROR: no reconoci objetos en la "
                "descripcion (vocabulario acotado: taza/mesa/pelota/caja/... )")
    _scenes(ctx)["escena"] = scene
    chk = control_check(scene, desc)
    return (f"RESULTADO escena_crear: {len(scene.objects)} objetos [{_describe(scene)}] "
            f"| control {chk['score']}/{chk['total']} "
            f"(presentes={chk['present']}, conteo={chk['count_ok']}, "
            f"relacion={chk['relation_ok']})")


@tool("escena_editar",
      "escena_editar <objeto> | <attr>=<valor>  -- edita UN objeto (color/x/y) sin "
      "tocar el resto (O(1), selectivo)")
def _escena_editar(args, ctx):
    scene = _active(ctx)
    if scene is None:
        return "RESULTADO escena_editar ERROR: no hay escena activa (usa escena_crear primero)"
    import re as _re
    parts = _re.split(r"\s*\|\s*", args, maxsplit=1)
    if len(parts) != 2:
        return "RESULTADO escena_editar ERROR: formato (objeto | attr=valor)"
    obj = parts[0].strip()
    m = _re.match(r"(\w+)\s*=\s*(.+)", parts[1].strip())
    if not m:
        return "RESULTADO escena_editar ERROR: formato del cambio (attr=valor)"
    attr, val = m.group(1), m.group(2).strip()
    # snapshot del resto para probar 'no toca lo demas' (diferenciador §8.2)
    otros_antes = {o.name: (o.x, o.y, o.color) for o in scene.objects if o.name != obj}
    kw = {}
    if attr in ("x", "y", "w", "h"):
        try:
            kw[attr] = float(val)
        except ValueError:
            return f"RESULTADO escena_editar ERROR: {attr} debe ser numero"
    elif attr == "color":
        kw["color"] = val if val.lower() in COLORS else val
    else:
        return f"RESULTADO escena_editar ERROR: atributo '{attr}' no editable (color/x/y/w/h)"
    if not scene.edit(obj, **kw):
        return f"RESULTADO escena_editar ERROR: no existe el objeto '{obj}'"
    otros_despues = {o.name: (o.x, o.y, o.color) for o in scene.objects if o.name != obj}
    intactos = otros_antes == otros_despues
    return (f"RESULTADO escena_editar: '{obj}' {attr}={val} aplicado; "
            f"resto intacto={intactos} ({len(otros_antes)} otros objetos)")


@tool("escena_consultar",
      "escena_consultar [objeto]             -- inspecciona la escena estructurada "
      "(o un objeto): que hay, donde, relaciones")
def _escena_consultar(args, ctx):
    scene = _active(ctx)
    if scene is None:
        return "RESULTADO escena_consultar ERROR: no hay escena activa (usa escena_crear primero)"
    obj = args.strip()
    if obj:
        o = scene.get(obj)
        if o is None:
            return f"RESULTADO escena_consultar ERROR: no existe el objeto '{obj}'"
        rel = f", {o.relation} de {o.ref}" if o.relation else ""
        return (f"RESULTADO escena_consultar {obj}: forma={o.shape}, "
                f"pos=({o.x:.2f},{o.y:.2f}), tam=({o.w:.2f}x{o.h:.2f}), color={o.color}{rel}")
    return (f"RESULTADO escena_consultar: {len(scene.objects)} objetos, "
            f"{scene.width}x{scene.height} -> [{_describe(scene)}]")


@tool("render_aprox",
      "render_aprox [archivo.png]            -- renderiza la escena activa a PNG "
      "(aproximado, sin refinador neuronal)")
def _render_aprox(args, ctx):
    scene = _active(ctx)
    if scene is None:
        return "RESULTADO render_aprox ERROR: no hay escena activa (usa escena_crear primero)"
    from cognia_x.lcd.renderer import render_to
    dest = args.strip() or "escena_lcd.png"
    try:
        path = render_to(scene, dest)
    except Exception as e:
        return f"RESULTADO render_aprox ERROR: {e}"
    return f"RESULTADO render_aprox: PNG escrito en {path} ({len(scene.objects)} objetos)"


# Import de este modulo = registro de las 4 tools en el registry global (via el
# @tool decorator). load_lcd_tools() existe para llamarlo explicito y contar.
def load_lcd_tools() -> int:
    """Devuelve cuantas tools LCD estan registradas (idempotente: el @tool ya
    corrio al importar). Sirve de hook explicito para el loop del agente."""
    from cognia.agent.tools import TOOLS
    return sum(1 for n in ("escena_crear", "escena_editar", "escena_consultar",
                           "render_aprox") if n in TOOLS)
