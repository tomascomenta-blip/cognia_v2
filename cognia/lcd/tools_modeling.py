"""
cognia/lcd/tools_modeling.py — Herramientas de MODELADO de Blender como tools
AI-nativas (ACCION), sobre los vertices del objeto activo. Recrea Edit Mode +
modificadores confirmados por la investigacion (extrude/bevel/subdivide/inset/
mirror/array/subsurf/ngon) como operaciones invocables por una IA.

Cada tool opera sobre el objeto activo de la escena (escena_crear/agregar
primero). Si el objeto no es un polygon, primero lo convierte a su poligono
base (rect/triangle -> vertices) para poder editar sus vertices.
"""
from __future__ import annotations

from cognia.agent.tools import tool
from cognia.lcd import modeling
from cognia.lcd.tools_lcd import _active

# poligono base por primitiva (coords locales -0.5..0.5) para poder editar
# vertices de un objeto que arranco como rect/triangle/etc.
_BASE = {
    "rect": [[-0.5, -0.5], [0.5, -0.5], [0.5, 0.5], [-0.5, 0.5]],
    "triangle": [[0.0, -0.5], [0.5, 0.5], [-0.5, 0.5]],
    "ellipse": None,   # se aproxima con un ngon
    "circle": None,
}


def _ensure_points(o):
    """Garantiza que el objeto tenga o.points (lo vuelve polygon si hacia falta).
    Devuelve la lista de puntos o None si no se puede."""
    if o.shape == "polygon" and o.points:
        return o.points
    base = _BASE.get(o.shape)
    if base is None:
        base = modeling.ngon(24)          # elipse/circulo -> poligono de 24 lados
    o.shape = "polygon"
    o.points = [list(p) for p in base]
    return o.points


def _apply(ctx, obj_name, fn, *a, **kw):
    scene = _active(ctx)
    if scene is None:
        return None, "no hay escena activa (usa escena_crear primero)"
    o = scene.get(obj_name)
    if o is None:
        return None, f"no existe el objeto '{obj_name}'"
    pts = _ensure_points(o)
    o.points = fn(pts, *a, **kw)
    return o, None


@tool("escena_biselar",
      "escena_biselar <objeto> | <cantidad 0..0.5>  -- Bevel: achaflana las esquinas "
      "(Blender Ctrl+B) para romper el quiebre plano de luz")
def _biselar(args, ctx):
    import re
    parts = re.split(r"\s*\|\s*", args, maxsplit=1)
    name = parts[0].strip()
    try:
        amt = float(parts[1]) if len(parts) > 1 else 0.15
    except ValueError:
        return "RESULTADO escena_biselar ERROR: cantidad debe ser numero"
    o, err = _apply(ctx, name, modeling.bevel, amt)
    if err:
        return f"RESULTADO escena_biselar ERROR: {err}"
    return f"RESULTADO escena_biselar: '{name}' biselado ({len(o.points)} vertices)"


@tool("escena_subdividir",
      "escena_subdividir <objeto> [| <cortes>]  -- Subdivide: mas vertices por arista "
      "(Blender Subdivide) para gradientes finos")
def _subdividir(args, ctx):
    import re
    parts = re.split(r"\s*\|\s*", args, maxsplit=1)
    name = parts[0].strip()
    try:
        cuts = int(parts[1]) if len(parts) > 1 else 1
    except ValueError:
        return "RESULTADO escena_subdividir ERROR: cortes debe ser entero"
    o, err = _apply(ctx, name, modeling.subdivide, cuts)
    if err:
        return f"RESULTADO escena_subdividir ERROR: {err}"
    return f"RESULTADO escena_subdividir: '{name}' -> {len(o.points)} vertices"


@tool("escena_suavizar",
      "escena_suavizar <objeto> [| <iteraciones>]  -- Subsurf: suaviza el contorno "
      "(Blender Subdivision Surface, Chaikin)")
def _suavizar(args, ctx):
    import re
    parts = re.split(r"\s*\|\s*", args, maxsplit=1)
    name = parts[0].strip()
    try:
        it = int(parts[1]) if len(parts) > 1 else 2
    except ValueError:
        return "RESULTADO escena_suavizar ERROR: iteraciones debe ser entero"
    o, err = _apply(ctx, name, modeling.smooth, it)
    if err:
        return f"RESULTADO escena_suavizar ERROR: {err}"
    return f"RESULTADO escena_suavizar: '{name}' suavizado ({len(o.points)} vertices)"


@tool("escena_insertar",
      "escena_insertar <objeto> | <cantidad 0..1>  -- Inset: contorno interior "
      "escalado (Blender I)")
def _insertar(args, ctx):
    import re
    parts = re.split(r"\s*\|\s*", args, maxsplit=1)
    name = parts[0].strip()
    try:
        amt = float(parts[1]) if len(parts) > 1 else 0.2
    except ValueError:
        return "RESULTADO escena_insertar ERROR: cantidad debe ser numero"
    o, err = _apply(ctx, name, modeling.inset, amt)
    if err:
        return f"RESULTADO escena_insertar ERROR: {err}"
    return f"RESULTADO escena_insertar: '{name}' insertado hacia adentro"


@tool("escena_extruir",
      "escena_extruir <objeto> | <arista_i> <dx> <dy>  -- Extrude: desplaza una "
      "arista creando cara nueva (Blender E)")
def _extruir(args, ctx):
    import re
    parts = re.split(r"\s*\|\s*", args, maxsplit=1)
    name = parts[0].strip()
    nums = (parts[1] if len(parts) > 1 else "").split()
    if len(nums) != 3:
        return "RESULTADO escena_extruir ERROR: formato (objeto | arista_i dx dy)"
    try:
        i, dx, dy = int(nums[0]), float(nums[1]), float(nums[2])
    except ValueError:
        return "RESULTADO escena_extruir ERROR: arista_i entero, dx/dy numeros"
    o, err = _apply(ctx, name, modeling.extrude_edge, i, dx, dy)
    if err:
        return f"RESULTADO escena_extruir ERROR: {err}"
    return f"RESULTADO escena_extruir: '{name}' arista {i} extruida ({len(o.points)} vertices)"


@tool("escena_espejar",
      "escena_espejar <objeto> [| x|y]  -- Mirror: refleja los vertices (Blender "
      "Mirror modifier)")
def _espejar(args, ctx):
    import re
    parts = re.split(r"\s*\|\s*", args, maxsplit=1)
    name = parts[0].strip()
    axis = (parts[1].strip().lower() if len(parts) > 1 else "x")
    if axis not in ("x", "y"):
        return "RESULTADO escena_espejar ERROR: eje = x | y"
    o, err = _apply(ctx, name, modeling.mirror, axis)
    if err:
        return f"RESULTADO escena_espejar ERROR: {err}"
    return f"RESULTADO escena_espejar: '{name}' reflejado en {axis}"


@tool("escena_array",
      "escena_array <objeto> | <n> <dx> <dy>  -- Array: N copias con offset "
      "(Blender Array modifier) — p.ej. bandas repetidas")
def _array(args, ctx):
    import re
    parts = re.split(r"\s*\|\s*", args, maxsplit=1)
    name = parts[0].strip()
    nums = (parts[1] if len(parts) > 1 else "").split()
    if len(nums) != 3:
        return "RESULTADO escena_array ERROR: formato (objeto | n dx dy)"
    try:
        n, dx, dy = int(nums[0]), float(nums[1]), float(nums[2])
    except ValueError:
        return "RESULTADO escena_array ERROR: n entero, dx/dy numeros"
    scene = _active(ctx)
    if scene is None:
        return "RESULTADO escena_array ERROR: no hay escena activa"
    o = scene.get(name)
    if o is None:
        return f"RESULTADO escena_array ERROR: no existe el objeto '{name}'"
    copias = modeling.array(o, n, dx, dy)
    scene.remove(name)                       # reemplazar el original por las N copias
    for c in copias:
        scene.add(c)
    return f"RESULTADO escena_array: '{name}' x{n} copias con offset ({dx},{dy})"


@tool("escena_poligono",
      "escena_poligono <objeto> | <n_lados>  -- convierte un objeto en un poligono "
      "regular de n lados (Blender add circle/ngon) — hexagono, tuerca, etc.")
def _poligono(args, ctx):
    import re
    parts = re.split(r"\s*\|\s*", args, maxsplit=1)
    name = parts[0].strip()
    try:
        n = int(parts[1]) if len(parts) > 1 else 6
    except ValueError:
        return "RESULTADO escena_poligono ERROR: n_lados debe ser entero"
    scene = _active(ctx)
    if scene is None:
        return "RESULTADO escena_poligono ERROR: no hay escena activa"
    o = scene.get(name)
    if o is None:
        return f"RESULTADO escena_poligono ERROR: no existe el objeto '{name}'"
    o.shape = "polygon"
    o.points = modeling.ngon(n)
    return f"RESULTADO escena_poligono: '{name}' ahora es un poligono de {n} lados"


@tool("escena_animar_caida",
      "escena_animar_caida [archivo.gif]  -- genera un GIF del lapiz cayendo del "
      "cielo y rebotando (dinamica real: gravedad + rebote + rotacion)")
def _animar_caida(args, ctx):
    from cognia.lcd.animation import render_fall_gif
    dest = args.strip() or "lapiz_rebote.gif"
    try:
        path = render_fall_gif(dest, frames=90)
    except Exception as e:
        return f"RESULTADO escena_animar_caida ERROR: {e}"
    return (f"RESULTADO escena_animar_caida: GIF del lapiz cayendo y rebotando "
            f"escrito en {path} (dinamica: gravedad+rebote+rotacion, determinista)")


def load_modeling_tools() -> int:
    """Cuenta las tools de modelado registradas (idempotente)."""
    from cognia.agent.tools import TOOLS
    return sum(1 for n in ("escena_biselar", "escena_subdividir", "escena_suavizar",
                           "escena_insertar", "escena_extruir", "escena_espejar",
                           "escena_array", "escena_poligono", "escena_animar_caida")
               if n in TOOLS)
