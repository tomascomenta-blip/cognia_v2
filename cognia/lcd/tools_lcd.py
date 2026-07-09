"""
cognia/lcd/tools_lcd.py — Herramientas AI-NATIVAS de LCD (plan 12, Fase 0/1).

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

import re as _re

from cognia.agent.tools import tool
from cognia.lcd.planner import _find_objects, _find_relation, _tokens, plan
from cognia.lcd.scene import COLORS, MATERIALS, Obj, Scene, SHAPES


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


def _parse_kv(text: str) -> dict:
    """Parsea pares clave=valor separados por espacios (p.ej. 'x=0.3 y=0.5
    color=red') en un dict {clave: valor_str}. Usado por las tools de edicion
    TOTAL que aceptan varios argumentos con nombre tras el '|'."""
    return dict(_re.findall(r"(\w+)\s*=\s*(\S+)", text or ""))


def _strip_pipe(text: str) -> str:
    """Saca un '|' inicial (tools sin objeto antes del pipe: camara/luz/fondo)."""
    t = (text or "").strip()
    return t[1:].strip() if t.startswith("|") else t


def _fold_ascii(s: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", (s or "").lower().strip())
                   if not unicodedata.combining(c))


def _resolver_nombre(scene: Scene, name: str):
    """Resuelve una referencia de objeto a un nombre EXISTENTE de la escena:
    exacto primero; si no, por nombre canonico (sinonimos es/en de scene.py +
    acentos foldeados): 'cup' encuentra 'taza', 'árbol' encuentra 'arbol'.
    None si nada matchea. Gap cazado por eval_lcd_gap 2026-07-09: el modelo
    traduce el nombre del objeto al idioma del turno y el lookup exacto
    fallaba con 'no existe el objeto'."""
    from cognia.lcd.scene import canonical_name
    if any(o.name == name for o in scene.objects):
        return name
    objetivo = canonical_name(_fold_ascii(name))
    for o in scene.objects:
        if canonical_name(_fold_ascii(o.name)) == objetivo:
            return o.name
    return None


# ── tools AI-nativas ─────────────────────────────────────────────────────────

@tool("escena_crear",
      "escena_crear <descripcion>            -- construye una escena ESTRUCTURADA "
      "(objetos+relaciones) desde una descripcion y la verifica (control cero-LLM)")
def _escena_crear(args, ctx):
    desc = args.strip()
    if not desc:
        return "RESULTADO escena_crear ERROR: falta la descripcion de la escena"
    # 1) planner de REGLAS primero (control exacto por construccion, cero costo).
    scene = plan(desc)
    via = "reglas"
    # 2) si las reglas no reconocen objetos (vocabulario fuera de la gramatica) Y
    #    hay orquestador en ctx, intentar el planner-LLM (el 3B, 7/8 medido) como
    #    ruta de lenguaje natural. El checker cero-LLM sigue siendo el oraculo.
    if not scene.objects:
        orch = _orch_from_ctx(ctx)
        if orch is not None:
            from cognia.lcd.planner import plan_with_llm
            llm_scene, _raw = plan_with_llm(desc, orch)
            if llm_scene is not None and llm_scene.objects:
                scene, via = llm_scene, "planner-LLM"
    if not scene.objects:
        return ("RESULTADO escena_crear ERROR: no reconoci objetos en la "
                "descripcion (vocabulario de reglas acotado; el planner-LLM "
                "tampoco produjo escena valida o no hay modelo disponible)")
    _scenes(ctx)["escena"] = scene
    _scenes(ctx)["_desc"] = desc          # la descripcion origen (arbitro/reejecutar)
    chk = control_check(scene, desc)
    return (f"RESULTADO escena_crear ({via}): {len(scene.objects)} objetos "
            f"[{_describe(scene)}] | control {chk['score']}/{chk['total']} "
            f"(presentes={chk['present']}, conteo={chk['count_ok']}, "
            f"relacion={chk['relation_ok']})")


def _orch_from_ctx(ctx):
    """Orquestador YA vivo en el ctx del loop (ai._orchestrator), o None. NO crea
    uno (una tool de escena no debe levantar el modelo como efecto secundario)."""
    ai = ctx.get("ai") if isinstance(ctx, dict) else None
    return getattr(ai, "_orchestrator", None) if ai is not None else None


@tool("escena_editar",
      "escena_editar <objeto> | <attr>=<valor>  -- edita UN objeto (color/x/y) sin "
      "tocar el resto (O(1), selectivo)")
def _escena_editar(args, ctx):
    scene = _active(ctx)
    if scene is None:
        return "RESULTADO escena_editar ERROR: no hay escena activa (usa escena_crear primero)"
    parts = _re.split(r"\s*\|\s*", args, maxsplit=1)
    if len(parts) != 2:
        return "RESULTADO escena_editar ERROR: formato (objeto | attr=valor)"
    obj = _resolver_nombre(scene, parts[0].strip()) or parts[0].strip()
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
        obj = _resolver_nombre(scene, obj) or obj
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
    from cognia.lcd.renderer import render_to
    dest = args.strip() or "escena_lcd.png"
    try:
        path = render_to(scene, dest)
    except Exception as e:
        return f"RESULTADO render_aprox ERROR: {e}"
    return f"RESULTADO render_aprox: PNG escrito en {path} ({len(scene.objects)} objetos)"


@tool("atribuir_fallo",
      "atribuir_fallo                        -- si la escena no cumple lo pedido, "
      "señala la ETAPA culpable (plan/geometria/render) con oraculo cero-LLM")
def _atribuir_fallo(args, ctx):
    scene = _active(ctx)
    if scene is None:
        return "RESULTADO atribuir_fallo ERROR: no hay escena activa (usa escena_crear primero)"
    desc = _scenes(ctx).get("_desc", "")
    from cognia.lcd.arbiter import attribute_scene_failure
    v = attribute_scene_failure(desc, scene)
    if v["stage"] is None:
        return "RESULTADO atribuir_fallo: todos los contratos pasan (la escena cumple la spec)"
    return (f"RESULTADO atribuir_fallo: etapa culpable = {v['stage']} "
            f"({v['contract']}): {v['reason']}. Usa reejecutar_etapa {v['stage']}.")


@tool("reejecutar_etapa",
      "reejecutar_etapa <plan|geometria|render>  -- re-corre SOLO esa etapa sobre la "
      "escena activa (no regenera el resto)")
def _reejecutar_etapa(args, ctx):
    scene = _active(ctx)
    if scene is None:
        return "RESULTADO reejecutar_etapa ERROR: no hay escena activa (usa escena_crear primero)"
    stage = args.strip().lower()
    if stage not in ("plan", "geometria", "render"):
        return "RESULTADO reejecutar_etapa ERROR: etapa = plan | geometria | render"
    desc = _scenes(ctx).get("_desc", "")
    if stage in ("plan", "geometria"):
        # re-planifica desde la descripcion (repara objetos faltantes y posiciones
        # mal puestas de una) sin que el usuario reescriba nada.
        if not desc:
            return "RESULTADO reejecutar_etapa ERROR: no hay descripcion origen para re-planificar"
        nueva = plan(desc)
        _scenes(ctx)["escena"] = nueva
        chk = control_check(nueva, desc)
        return (f"RESULTADO reejecutar_etapa {stage}: escena re-planificada "
                f"({len(nueva.objects)} objetos), control {chk['score']}/{chk['total']}")
    # render: re-render de la escena actual (sin tocar la geometria)
    from cognia.lcd.renderer import render_to
    try:
        path = render_to(scene, "escena_lcd.png")
    except Exception as e:
        return f"RESULTADO reejecutar_etapa render ERROR: {e}"
    return f"RESULTADO reejecutar_etapa render: PNG re-generado en {path}"


# ── tools AI-nativas de EDICION TOTAL (agregar/quitar/mover/layout/fisica) ──
# Mismo contrato que arriba: cada una opera sobre _active(ctx); sin escena
# activa -> error claro. Formato ACCION con argumentos separados por '|'.

@tool("escena_agregar",
      "escena_agregar <objeto> [| x=.. y=.. color=.. w=.. h=..]  -- agrega un "
      "objeto NUEVO del vocabulario (SHAPES) a la escena activa")
def _escena_agregar(args, ctx):
    scene = _active(ctx)
    if scene is None:
        return "RESULTADO escena_agregar ERROR: no hay escena activa (usa escena_crear primero)"
    parts = _re.split(r"\s*\|\s*", args.strip(), maxsplit=1)
    name = parts[0].strip()
    if not name:
        return "RESULTADO escena_agregar ERROR: falta el nombre del objeto"
    if name not in SHAPES:
        return f"RESULTADO escena_agregar ERROR: '{name}' no esta en el vocabulario (SHAPES)"
    shape, w_def, h_def = SHAPES[name]
    kv = _parse_kv(parts[1]) if len(parts) == 2 else {}
    try:
        x = float(kv.get("x", 0.5))
        y = float(kv.get("y", 0.5))
        w = float(kv.get("w", w_def))
        h = float(kv.get("h", h_def))
    except ValueError:
        return "RESULTADO escena_agregar ERROR: x/y/w/h deben ser numeros"
    color_raw = kv.get("color")
    color = COLORS.get(color_raw.lower(), (150, 150, 150)) if color_raw else (150, 150, 150)
    z = max((o.z for o in scene.objects), default=-1) + 1   # el nuevo va al frente
    obj = scene.add(Obj(name=name, shape=shape, x=x, y=y, w=w, h=h, color=color, z=z))
    return (f"RESULTADO escena_agregar: '{obj.key()}' agregado en ({x:.2f},{y:.2f}) "
            f"({len(scene.objects)} objetos totales)")


@tool("escena_quitar",
      "escena_quitar <objeto>                -- quita un objeto de la escena activa")
def _escena_quitar(args, ctx):
    scene = _active(ctx)
    if scene is None:
        return "RESULTADO escena_quitar ERROR: no hay escena activa (usa escena_crear primero)"
    name = args.strip()
    if not name:
        return "RESULTADO escena_quitar ERROR: falta el objeto"
    if not scene.remove(name):
        return f"RESULTADO escena_quitar ERROR: no existe el objeto '{name}'"
    return f"RESULTADO escena_quitar: '{name}' quitado ({len(scene.objects)} objetos restantes)"


@tool("escena_duplicar",
      "escena_duplicar <objeto> [| dx=.. dy=..]  -- duplica un objeto desplazado "
      "(desambigua el id automaticamente)")
def _escena_duplicar(args, ctx):
    scene = _active(ctx)
    if scene is None:
        return "RESULTADO escena_duplicar ERROR: no hay escena activa (usa escena_crear primero)"
    parts = _re.split(r"\s*\|\s*", args.strip(), maxsplit=1)
    name = parts[0].strip()
    kv = _parse_kv(parts[1]) if len(parts) == 2 else {}
    try:
        dx = float(kv.get("dx", 0.08))
        dy = float(kv.get("dy", 0.0))
    except ValueError:
        return "RESULTADO escena_duplicar ERROR: dx/dy deben ser numeros"
    c = scene.duplicate(name, dx=dx, dy=dy)
    if c is None:
        return f"RESULTADO escena_duplicar ERROR: no existe el objeto '{name}'"
    return f"RESULTADO escena_duplicar: '{name}' -> '{c.key()}' en ({c.x:.2f},{c.y:.2f})"


@tool("escena_mover",
      "escena_mover <objeto> | x=.. y=..     -- mueve un objeto (uno o ambos ejes)")
def _escena_mover(args, ctx):
    scene = _active(ctx)
    if scene is None:
        return "RESULTADO escena_mover ERROR: no hay escena activa (usa escena_crear primero)"
    parts = _re.split(r"\s*\|\s*", args.strip(), maxsplit=1)
    if len(parts) != 2:
        return "RESULTADO escena_mover ERROR: formato (objeto | x=.. y=..)"
    name = parts[0].strip()
    kv = _parse_kv(parts[1])
    if "x" not in kv and "y" not in kv:
        return "RESULTADO escena_mover ERROR: falta x= y/o y="
    if scene.get(name) is None:
        return f"RESULTADO escena_mover ERROR: no existe el objeto '{name}'"
    try:
        changes = {}
        if "x" in kv:
            changes["x"] = float(kv["x"])
        if "y" in kv:
            changes["y"] = float(kv["y"])
    except ValueError:
        return "RESULTADO escena_mover ERROR: x/y deben ser numeros"
    scene.edit(name, **changes)
    o = scene.get(name)
    return f"RESULTADO escena_mover: '{name}' -> ({o.x:.2f},{o.y:.2f})"


@tool("escena_rotar",
      "escena_rotar <objeto> | <grados>      -- edita la rotacion (grados) de un objeto")
def _escena_rotar(args, ctx):
    scene = _active(ctx)
    if scene is None:
        return "RESULTADO escena_rotar ERROR: no hay escena activa (usa escena_crear primero)"
    parts = _re.split(r"\s*\|\s*", args.strip(), maxsplit=1)
    if len(parts) != 2:
        return "RESULTADO escena_rotar ERROR: formato (objeto | grados)"
    name = parts[0].strip()
    try:
        deg = float(parts[1].strip())
    except ValueError:
        return "RESULTADO escena_rotar ERROR: los grados deben ser numero"
    if not scene.edit(name, rotation=deg):
        return f"RESULTADO escena_rotar ERROR: no existe el objeto '{name}'"
    return f"RESULTADO escena_rotar: '{name}' rotation={deg}"


@tool("escena_escalar",
      "escena_escalar <objeto> | <factor>    -- multiplica w y h por factor (>0)")
def _escena_escalar(args, ctx):
    scene = _active(ctx)
    if scene is None:
        return "RESULTADO escena_escalar ERROR: no hay escena activa (usa escena_crear primero)"
    parts = _re.split(r"\s*\|\s*", args.strip(), maxsplit=1)
    if len(parts) != 2:
        return "RESULTADO escena_escalar ERROR: formato (objeto | factor)"
    name = parts[0].strip()
    try:
        factor = float(parts[1].strip())
    except ValueError:
        return "RESULTADO escena_escalar ERROR: el factor debe ser numero"
    if factor <= 0:
        return "RESULTADO escena_escalar ERROR: el factor debe ser > 0"
    o = scene.get(name)
    if o is None:
        return f"RESULTADO escena_escalar ERROR: no existe el objeto '{name}'"
    scene.edit(name, w=o.w * factor, h=o.h * factor)
    return f"RESULTADO escena_escalar: '{name}' -> ({o.w:.2f}x{o.h:.2f})"


@tool("escena_material",
      "escena_material <objeto> | <material>  -- edita el material (valida contra "
      "MATERIALS pero acepta cualquiera con aviso)")
def _escena_material(args, ctx):
    scene = _active(ctx)
    if scene is None:
        return "RESULTADO escena_material ERROR: no hay escena activa (usa escena_crear primero)"
    parts = _re.split(r"\s*\|\s*", args.strip(), maxsplit=1)
    if len(parts) != 2:
        return "RESULTADO escena_material ERROR: formato (objeto | material)"
    name = parts[0].strip()
    mat = parts[1].strip().lower()
    if not mat:
        return "RESULTADO escena_material ERROR: falta el material"
    if not scene.edit(name, material=mat):
        return f"RESULTADO escena_material ERROR: no existe el objeto '{name}'"
    aviso = "" if mat in MATERIALS else " (aviso: material no listado en MATERIALS, se acepta igual)"
    return f"RESULTADO escena_material: '{name}' material={mat}{aviso}"


@tool("escena_capa",
      "escena_capa <objeto> | <frente|fondo|z=N>  -- cambia el orden de dibujo (z)")
def _escena_capa(args, ctx):
    scene = _active(ctx)
    if scene is None:
        return "RESULTADO escena_capa ERROR: no hay escena activa (usa escena_crear primero)"
    parts = _re.split(r"\s*\|\s*", args.strip(), maxsplit=1)
    if len(parts) != 2:
        return "RESULTADO escena_capa ERROR: formato (objeto | frente|fondo|z=N)"
    name = parts[0].strip()
    spec = parts[1].strip().lower()
    if scene.get(name) is None:
        return f"RESULTADO escena_capa ERROR: no existe el objeto '{name}'"
    if spec == "frente":
        z = max((o.z for o in scene.objects), default=0) + 1
    elif spec == "fondo":
        z = min((o.z for o in scene.objects), default=0) - 1
    else:
        m = _re.match(r"z\s*=\s*(-?\d+)", spec)
        if not m:
            return "RESULTADO escena_capa ERROR: formato (frente|fondo|z=N)"
        z = int(m.group(1))
    scene.edit(name, z=z)
    return f"RESULTADO escena_capa: '{name}' z={z}"


@tool("escena_camara",
      "escena_camara | width=.. height=..    -- edita el tamano del canvas (la 'camara')")
def _escena_camara(args, ctx):
    scene = _active(ctx)
    if scene is None:
        return "RESULTADO escena_camara ERROR: no hay escena activa (usa escena_crear primero)"
    kv = _parse_kv(_strip_pipe(args))
    if not kv:
        return "RESULTADO escena_camara ERROR: formato (width=.. height=..)"
    try:
        if "width" in kv:
            scene.width = int(float(kv["width"]))
        if "height" in kv:
            scene.height = int(float(kv["height"]))
    except ValueError:
        return "RESULTADO escena_camara ERROR: width/height deben ser numeros"
    return f"RESULTADO escena_camara: {scene.width}x{scene.height}"


@tool("escena_luz",
      "escena_luz | <x>,<y>                  -- edita la direccion de luz (light_dir)")
def _escena_luz(args, ctx):
    scene = _active(ctx)
    if scene is None:
        return "RESULTADO escena_luz ERROR: no hay escena activa (usa escena_crear primero)"
    text = _strip_pipe(args)
    m = _re.match(r"(-?[\d.]+)\s*,\s*(-?[\d.]+)", text)
    if not m:
        return "RESULTADO escena_luz ERROR: formato (x,y) por ejemplo -0.5,-0.8"
    scene.light_dir = (float(m.group(1)), float(m.group(2)))
    return f"RESULTADO escena_luz: light_dir={scene.light_dir}"


@tool("escena_fondo",
      "escena_fondo | <color>                -- edita el color de fondo (nombre de "
      "COLORS o r,g,b)")
def _escena_fondo(args, ctx):
    scene = _active(ctx)
    if scene is None:
        return "RESULTADO escena_fondo ERROR: no hay escena activa (usa escena_crear primero)"
    text = _strip_pipe(args)
    if not text:
        return "RESULTADO escena_fondo ERROR: falta el color"
    if text.lower() in COLORS:
        scene.background = COLORS[text.lower()]
    else:
        m = _re.match(r"(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", text)
        if not m:
            return f"RESULTADO escena_fondo ERROR: color desconocido '{text}' (usa nombre o r,g,b)"
        scene.background = tuple(int(g) for g in m.groups())
    return f"RESULTADO escena_fondo: background={scene.background}"


@tool("escena_alinear",
      "escena_alinear <o1,o2,...> | <left|right|top|bottom|centerx|centery>  -- "
      "alinea varios objetos a un borde/eje comun")
def _escena_alinear(args, ctx):
    scene = _active(ctx)
    if scene is None:
        return "RESULTADO escena_alinear ERROR: no hay escena activa (usa escena_crear primero)"
    parts = _re.split(r"\s*\|\s*", args.strip(), maxsplit=1)
    if len(parts) != 2:
        return "RESULTADO escena_alinear ERROR: formato (o1,o2,... | left|right|top|bottom|centerx|centery)"
    names = [n.strip() for n in parts[0].split(",") if n.strip()]
    modo = parts[1].strip().lower()
    if len(names) < 2:
        return "RESULTADO escena_alinear ERROR: se necesitan al menos 2 objetos"
    objs = []
    for n in names:
        o = scene.get(n)
        if o is None:
            return f"RESULTADO escena_alinear ERROR: no existe el objeto '{n}'"
        objs.append(o)
    if modo == "left":
        borde = min(o.x - o.w / 2 for o in objs)
        for o in objs:
            o.x = borde + o.w / 2
    elif modo == "right":
        borde = max(o.x + o.w / 2 for o in objs)
        for o in objs:
            o.x = borde - o.w / 2
    elif modo == "top":
        borde = min(o.y - o.h / 2 for o in objs)
        for o in objs:
            o.y = borde + o.h / 2
    elif modo == "bottom":
        borde = max(o.y + o.h / 2 for o in objs)
        for o in objs:
            o.y = borde - o.h / 2
    elif modo == "centerx":
        c = sum(o.x for o in objs) / len(objs)
        for o in objs:
            o.x = c
    elif modo == "centery":
        c = sum(o.y for o in objs) / len(objs)
        for o in objs:
            o.y = c
    else:
        return "RESULTADO escena_alinear ERROR: modo invalido (left|right|top|bottom|centerx|centery)"
    return f"RESULTADO escena_alinear: [{', '.join(names)}] alineados a {modo}"


@tool("escena_distribuir",
      "escena_distribuir <o1,o2,...> | <horizontal|vertical>  -- distribuye los "
      "objetos equiespaciados entre los extremos actuales")
def _escena_distribuir(args, ctx):
    scene = _active(ctx)
    if scene is None:
        return "RESULTADO escena_distribuir ERROR: no hay escena activa (usa escena_crear primero)"
    parts = _re.split(r"\s*\|\s*", args.strip(), maxsplit=1)
    if len(parts) != 2:
        return "RESULTADO escena_distribuir ERROR: formato (o1,o2,... | horizontal|vertical)"
    names = [n.strip() for n in parts[0].split(",") if n.strip()]
    modo = parts[1].strip().lower()
    if modo not in ("horizontal", "vertical"):
        return "RESULTADO escena_distribuir ERROR: modo invalido (horizontal|vertical)"
    if len(names) < 2:
        return "RESULTADO escena_distribuir ERROR: se necesitan al menos 2 objetos"
    objs = []
    for n in names:
        o = scene.get(n)
        if o is None:
            return f"RESULTADO escena_distribuir ERROR: no existe el objeto '{n}'"
        objs.append(o)
    attr = "x" if modo == "horizontal" else "y"
    objs.sort(key=lambda o: getattr(o, attr))
    lo, hi = getattr(objs[0], attr), getattr(objs[-1], attr)
    n = len(objs)
    step = (hi - lo) / (n - 1) if n > 1 else 0.0
    for i, o in enumerate(objs):
        setattr(o, attr, lo + step * i)
    return (f"RESULTADO escena_distribuir: [{', '.join(o.key() for o in objs)}] "
            f"equiespaciados en {modo}")


@tool("escena_relacionar",
      "escena_relacionar <A> | <on|left_of|right_of|above|below> | <B>  -- "
      "reposiciona A respecto de B segun la relacion pedida")
def _escena_relacionar(args, ctx):
    scene = _active(ctx)
    if scene is None:
        return "RESULTADO escena_relacionar ERROR: no hay escena activa (usa escena_crear primero)"
    parts = _re.split(r"\s*\|\s*", args.strip())
    if len(parts) != 3:
        return "RESULTADO escena_relacionar ERROR: formato (A | relacion | B)"
    name_a, rel, name_b = parts[0].strip(), parts[1].strip().lower(), parts[2].strip()
    if rel not in ("on", "left_of", "right_of", "above", "below"):
        return "RESULTADO escena_relacionar ERROR: relacion invalida (on|left_of|right_of|above|below)"
    a, b = scene.get(name_a), scene.get(name_b)
    if a is None or b is None:
        faltante = name_a if a is None else name_b
        return f"RESULTADO escena_relacionar ERROR: no existe el objeto '{faltante}'"
    # misma logica de posicionamiento que planner.plan (§4.1): B es la base, A
    # se recoloca pegado a su borde segun la relacion.
    if rel == "on":
        a.x, a.y = b.x, b.y - b.h / 2 - a.h / 2
    elif rel == "above":
        a.x, a.y = b.x, b.y - b.h / 2 - a.h / 2 - 0.08
    elif rel == "below":
        a.x, a.y = b.x, b.y + b.h / 2 + a.h / 2 + 0.02
    elif rel == "left_of":
        a.x, a.y = b.x - b.w / 2 - a.w / 2 - 0.04, b.y
    elif rel == "right_of":
        a.x, a.y = b.x + b.w / 2 + a.w / 2 + 0.04, b.y
    a.relation, a.ref = rel, b.key()
    ok = _relation_ok(scene, a.key(), rel, b.key())
    return (f"RESULTADO escena_relacionar: '{a.key()}' {rel} '{b.key()}' -> "
            f"({a.x:.2f},{a.y:.2f}); relacion_ok={ok}")


@tool("escena_fisica",
      "escena_fisica                         -- asienta la escena activa con "
      "gravedad/colision (physics.settle) y reporta plausibilidad")
def _escena_fisica(args, ctx):
    scene = _active(ctx)
    if scene is None:
        return "RESULTADO escena_fisica ERROR: no hay escena activa (usa escena_crear primero)"
    from cognia.lcd.physics import physics_report, settle
    rep = settle(scene)
    chk = physics_report(scene)
    return (f"RESULTADO escena_fisica: asentada (iters={rep['iters']}, "
            f"movidos={rep['moved']}); plausible={chk['plausible']} "
            f"flotando={chk['flotando']} solapando={chk['solapando']} "
            f"inestables={chk['inestables']}")


@tool("escena_forma",
      "escena_forma <objeto> | <rect|ellipse|circle|triangle|polygon>  -- cambia la "
      "figura de un objeto (edicion de figuras)")
def _escena_forma(args, ctx):
    scene = _active(ctx)
    if scene is None:
        return "RESULTADO escena_forma ERROR: no hay escena activa (usa escena_crear primero)"
    parts = _re.split(r"\s*\|\s*", args, maxsplit=1)
    if len(parts) != 2:
        return "RESULTADO escena_forma ERROR: formato (objeto | forma)"
    name, forma = parts[0].strip(), parts[1].strip().lower()
    if forma not in ("rect", "ellipse", "circle", "triangle", "polygon"):
        return ("RESULTADO escena_forma ERROR: forma invalida "
                "(rect|ellipse|circle|triangle|polygon)")
    if not scene.edit(name, shape=forma):
        return f"RESULTADO escena_forma ERROR: no existe el objeto '{name}'"
    return f"RESULTADO escena_forma: '{name}' ahora es {forma}"


@tool("escena_vertices",
      "escena_vertices <objeto> | x1,y1 x2,y2 x3,y3 ...  -- define los VERTICES de un "
      "objeto (coords locales -0.5..0.5, 0=centro); lo vuelve un polygon")
def _escena_vertices(args, ctx):
    scene = _active(ctx)
    if scene is None:
        return "RESULTADO escena_vertices ERROR: no hay escena activa (usa escena_crear primero)"
    parts = _re.split(r"\s*\|\s*", args, maxsplit=1)
    if len(parts) != 2:
        return "RESULTADO escena_vertices ERROR: formato (objeto | x1,y1 x2,y2 ...)"
    name = parts[0].strip()
    pts = []
    for tok in parts[1].split():
        m = _re.match(r"(-?[\d.]+),(-?[\d.]+)$", tok.strip())
        if not m:
            return f"RESULTADO escena_vertices ERROR: vertice mal formado '{tok}' (usa x,y)"
        pts.append([float(m.group(1)), float(m.group(2))])
    if len(pts) < 3:
        return "RESULTADO escena_vertices ERROR: hacen falta al menos 3 vertices"
    o = scene.get(name)
    if o is None:
        return f"RESULTADO escena_vertices ERROR: no existe el objeto '{name}'"
    o.shape = "polygon"
    o.points = pts
    return f"RESULTADO escena_vertices: '{name}' con {len(pts)} vertices (ahora polygon)"


# Import de este modulo = registro de las tools en el registry global (via el
# @tool decorator). load_lcd_tools() existe para llamarlo explicito y contar.
def load_lcd_tools() -> int:
    """Devuelve cuantas tools LCD estan registradas (idempotente: el @tool ya
    corrio al importar). Sirve de hook explicito para el loop del agente."""
    from cognia.agent.tools import TOOLS
    return sum(1 for n in ("escena_crear", "escena_editar", "escena_consultar",
                           "render_aprox", "atribuir_fallo", "reejecutar_etapa",
                           "escena_agregar", "escena_quitar", "escena_duplicar",
                           "escena_mover", "escena_rotar", "escena_escalar",
                           "escena_material", "escena_capa", "escena_camara",
                           "escena_luz", "escena_fondo", "escena_alinear",
                           "escena_distribuir", "escena_relacionar", "escena_fisica",
                           "escena_forma", "escena_vertices")
               if n in TOOLS)
