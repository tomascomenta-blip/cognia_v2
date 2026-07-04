"""
cognia_x/lcd/selfplay.py — AUTO-PRUEBAS de la herramienta AI-nativa de escena.

Lo que el dueño pidio: "puedes hacer pruebas incluso TU misma intentando hacer
cosas y evaluar que tanto se parecen". Este modulo da (1) una METRICA de
similitud entre dos escenas (cuanto se parecen, cero-LLM y determinista) y (2)
un motor de AUTO-PRUEBA donde un AGENTE (una funcion que emite ACCIONes, sea el
3B, una politica scripted, o yo misma) intenta REPRODUCIR una escena objetivo a
partir de su descripcion, y se mide el parecido del resultado con el objetivo.

Es el analogo, para escenas, del "juez por tests ejecutados" del codigo: la
escena objetivo ES el oraculo; la similitud es el score. Sirve para medir el
techo de las tools (que tan bien una IA puede armar/editar una escena) y para
detectar regresiones de forma cuantitativa.

similarity(a, b) in [0,1] combina:
  - match de objetos por tipo (¿estan los mismos objetos?)      peso 0.40
  - IoU medio de las cajas de los objetos emparejados            peso 0.35
  - acierto de color de los emparejados                          peso 0.10
  - relaciones espaciales pareadas (izq/der/encima/debajo)       peso 0.15
Determinista, O(n^2) en objetos (escenas chicas). Sin red neuronal.
"""
from __future__ import annotations

from cognia_x.lcd.scene import Scene


def _iou(a, b) -> float:
    """Intersection-over-Union de dos cajas (x0,y0,x1,y1)."""
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    iw, ih = max(0.0, ix1 - ix0), max(0.0, iy1 - iy0)
    inter = iw * ih
    area_a = max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0)
    area_b = max(0.0, bx1 - bx0) * max(0.0, by1 - by0)
    union = area_a + area_b - inter
    return inter / union if union > _EPS else 0.0


_EPS = 1e-9


def _color_close(c1, c2, tol: int = 40) -> bool:
    return all(abs(int(a) - int(b)) <= tol for a, b in zip(c1, c2))


def _match_objects(a: Scene, b: Scene):
    """Empareja objetos de a y b por TIPO (name) y cercania de posicion.
    Devuelve (pares, no_emparejados_a, no_emparejados_b). Greedy: para cada
    objeto de a busca el objeto libre de b del MISMO tipo mas cercano."""
    libres_b = list(b.objects)
    pares, sin_a = [], []
    for oa in a.objects:
        cands = [ob for ob in libres_b if ob.name == oa.name]
        if not cands:
            sin_a.append(oa)
            continue
        best = min(cands, key=lambda ob: (oa.x - ob.x) ** 2 + (oa.y - ob.y) ** 2)
        pares.append((oa, best))
        libres_b.remove(best)
    return pares, sin_a, libres_b


def _relations(scene: Scene):
    """Relaciones espaciales IMPLICITAS entre cada par de objetos (por sus
    posiciones): {(tipo_a, tipo_b): set(relaciones)}. Cero-LLM, del layout."""
    rels = {}
    objs = scene.objects
    for i, a in enumerate(objs):
        for b in objs:
            if a is b:
                continue
            s = set()
            if a.x < b.x - 0.03:
                s.add("left_of")
            if a.x > b.x + 0.03:
                s.add("right_of")
            if a.y < b.y - 0.03:
                s.add("above")
            if a.y > b.y + 0.03:
                s.add("below")
            if s:
                rels[(a.name, b.name)] = s
    return rels


def similarity(a: Scene, b: Scene) -> dict:
    """Cuanto se parece la escena a a la b, in [0,1] (1 = identicas). Devuelve
    el score y el desglose por componente para inspeccionabilidad."""
    if not a.objects and not b.objects:
        return {"score": 1.0, "obj_match": 1.0, "iou": 1.0, "color": 1.0, "rel": 1.0}
    pares, sin_a, sin_b = _match_objects(a, b)
    n_union = len(a.objects) + len(sin_b)          # objetos de a + los de b sin par
    obj_match = len(pares) / n_union if n_union else 1.0

    iou = (sum(_iou(oa.bbox(), ob.bbox()) for oa, ob in pares) / len(pares)
           if pares else 0.0)
    color = (sum(_color_close(oa.color, ob.color) for oa, ob in pares) / len(pares)
             if pares else 0.0)

    # relaciones: fraccion de las relaciones de b reproducidas en a
    ra, rb = _relations(a), _relations(b)
    if rb:
        hit = sum(1 for k, v in rb.items() if ra.get(k, set()) & v)
        rel = hit / len(rb)
    else:
        rel = 1.0

    score = 0.40 * obj_match + 0.35 * iou + 0.10 * color + 0.15 * rel
    return {"score": round(score, 4), "obj_match": round(obj_match, 3),
            "iou": round(iou, 3), "color": round(color, 3), "rel": round(rel, 3),
            "pares": len(pares), "faltan": len(sin_a), "sobran": len(sin_b)}


# ── Motor de auto-prueba: un agente intenta reproducir una escena objetivo ──

def attempt_reproduce(target: Scene, description: str, agent_fn, run_tool_fn,
                      max_steps: int = 12) -> dict:
    """El agente (agent_fn) intenta reconstruir `target` a partir de su
    `description`, emitiendo ACCIONes que se ejecutan con run_tool_fn sobre una
    escena de trabajo fresca. Mide la similitud final con el objetivo.

    agent_fn(description, history, target_summary) -> str (una linea 'accion args'
    o 'FIN'). run_tool_fn(name, args, ctx) -> str (el RESULTADO). Devuelve
    {similarity, steps, trace}."""
    import re
    # sembrar una escena de trabajo VACIA para que escena_agregar tenga sobre
    # que operar (el agente construye desde cero, sin el planner de reglas).
    ctx = {"working_memory": {"_lcd_scene": {"escena": Scene(), "_desc": description}},
           "agent_state": {}}
    history = []
    for step in range(max_steps):
        line = (agent_fn(description, history, _summary(target)) or "").strip()
        if not line or line.upper().startswith("FIN"):
            break
        m = re.match(r"(\w+)\s*(.*)", line)
        if not m:
            history.append(f"(ignorada: {line[:40]})")
            continue
        name, args = m.group(1), m.group(2).strip()
        try:
            res = run_tool_fn(name, args, ctx)
        except Exception as e:
            res = f"RESULTADO {name} ERROR: {e}"
        history.append(f"{name} {args} -> {res[:80]}")
    got = ctx.get("working_memory", {}).get("_lcd_scene", {}).get("escena")
    sim = similarity(got, target) if got is not None else {"score": 0.0}
    return {"similarity": sim, "steps": len(history), "trace": history,
            "built": got is not None}


def _summary(scene: Scene) -> str:
    """Descripcion estructurada compacta de una escena (para darle al agente el
    objetivo sin pasarle el objeto). Cero-LLM."""
    return "; ".join(f"{o.name}@({o.x:.2f},{o.y:.2f})" for o in scene.objects)


def scripted_from_scene(target: Scene):
    """Un agente 'perfecto' SCRIPTED: emite las ACCIONes que reconstruyen el
    target exactamente (escena_crear vacio + escena_agregar por objeto con su
    pos/color). Sirve de test de techo: reproduce -> similitud ~1.0. Es la
    'prueba que yo misma hago' automatizada (una politica que arma la escena)."""
    from cognia_x.lcd.scene import COLORS
    # nombre de color inverso (RGB -> nombre) para emitir args legibles
    rgb_to_name = {}
    for n, rgb in COLORS.items():
        rgb_to_name.setdefault(rgb, n)
    acciones = []
    # arrancar una escena vacia con un objeto ancla (el primero), luego agregar
    if not target.objects:
        acciones = ["FIN"]
    else:
        for i, o in enumerate(target.objects):
            cname = rgb_to_name.get(tuple(o.color), "")
            extra = f" color={cname}" if cname else ""
            acciones.append(f"escena_agregar {o.name} | x={o.x:.3f} y={o.y:.3f} "
                            f"w={o.w:.3f} h={o.h:.3f}{extra}")
        acciones.append("FIN")
    it = iter(acciones)

    def agent_fn(description, history, target_summary):
        return next(it, "FIN")
    return agent_fn
