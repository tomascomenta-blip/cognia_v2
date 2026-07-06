"""
cognia/lcd/planner.py — Módulo de PLANIFICACIÓN (LCD, paper §4.1 mod 1).

Prompt textual -> escena estructurada (objetos + posiciones + relaciones). Es
la primera etapa del pipeline LCD: decidir QUÉ hay y DÓNDE antes de tocar
píxeles (§3.2 "geometría antes que píxeles"). Análogo a los enfoques
LayoutGPT/LLM-as-planner (§2.1), pero aquí basado en REGLAS (determinista,
100% fiable) — el paper propone un LLM; se deja el hook plan_with_llm para
usar el 3B, pero el default es la gramática para que el control composicional
sea exacto por construcción y medible sin ruido de modelo.

Gramática soportada (suficiente para el eval de control §8.1):
  [det] [color?] OBJ [relacion [det] [color?] OBJ]?
p.ej. "a red cup on a blue table", "una taza roja sobre una mesa azul",
"a green ball to the left of a yellow box".
"""
from __future__ import annotations

import re

from cognia.lcd.scene import COLORS, SHAPES, Obj, Scene

_REL = {
    "on": "on", "sobre": "on", "encima": "on",
    "above": "above", "arriba": "above",
    "below": "below", "under": "below", "debajo": "below", "abajo": "below",
    "left of": "left_of", "left": "left_of", "izquierda": "left_of",
    "right of": "right_of", "right": "right_of", "derecha": "right_of",
    "next to": "next_to", "junto": "next_to", "al lado": "next_to",
    "in": "in", "en": "in", "inside": "in", "dentro": "in",
}
_STOP = {"a", "an", "the", "un", "una", "el", "la", "los", "las", "of", "de",
         "to", "with", "and", "y", "una", "some"}


def _tokens(text):
    return re.findall(r"[a-záéíóúñ]+", (text or "").lower())


def _find_objects(tokens):
    """Devuelve [(color|None, obj_key)] en orden de aparición."""
    out, pending_color = [], None
    for w in tokens:
        if w in COLORS:
            pending_color = w
        elif w in SHAPES:
            out.append((pending_color, w))
            pending_color = None
    return out


def _find_relation(text):
    """Primera relación mencionada (frase o palabra), o None."""
    t = text.lower()
    # frases de 2 palabras primero (left of, next to, al lado)
    for phrase in ("left of", "right of", "next to", "al lado"):
        if phrase in t:
            return _REL[phrase]
    for w in _tokens(text):
        if w in _REL:
            return _REL[w]
    return None


def plan(prompt: str, width: int = 512, height: int = 512) -> Scene:
    """Prompt -> Scene estructurada (determinista). Resuelve relaciones en
    posiciones concretas. Objetos sin relación se distribuyen en el suelo."""
    toks = _tokens(prompt)
    found = _find_objects(toks)
    rel = _find_relation(prompt)
    scene = Scene(width=width, height=height)

    def make(color_name, key, x, y, z):
        shape, w, h = SHAPES[key]
        color = COLORS.get(color_name or "", (150, 150, 150))
        return Obj(name=key, shape=shape, x=x, y=y, w=w, h=h, color=color, z=z)

    if not found:
        return scene

    if len(found) >= 2 and rel:
        # OBJ_A rel OBJ_B: B es la referencia (base), A el sujeto.
        (ca, ka), (cb, kb) = found[0], found[1]
        base = make(cb, kb, 0.5, 0.68, 0)
        sw, sh = SHAPES[ka][1], SHAPES[ka][2]
        if rel == "on":            # A encima de B (apoyado en su borde superior)
            ax, ay = base.x, base.y - base.h / 2 - sh / 2
        elif rel == "above":
            ax, ay = base.x, base.y - base.h / 2 - sh / 2 - 0.08
        elif rel == "below":
            ax, ay = base.x, base.y + base.h / 2 + sh / 2 + 0.02
        elif rel == "left_of":
            ax, ay = base.x - base.w / 2 - sw / 2 - 0.04, base.y
        elif rel == "right_of":
            ax, ay = base.x + base.w / 2 + sw / 2 + 0.04, base.y
        elif rel == "next_to":
            ax, ay = base.x + base.w / 2 + sw / 2 + 0.04, base.y
        elif rel == "in":
            ax, ay = base.x, base.y
        else:
            ax, ay = base.x, base.y - 0.2
        subj = make(ca, ka, ax, ay, 1)
        subj.relation, subj.ref = rel, kb
        scene.objects = [base, subj]
    else:
        # sin relación clara: distribuir en el suelo, tamaños respetados
        n = len(found)
        for i, (c, k) in enumerate(found):
            x = (i + 1) / (n + 1)
            _, _, h = SHAPES[k]
            scene.objects.append(make(c, k, x, 0.68 - h / 2 + 0.06, i))
    return scene


# ── Hook LLM (paper §4.1 mod 1 = LLM planner). Opcional: usa el 3B para
# producir la escena JSON. El default (plan) es reglas, para control exacto. ──

_LLM_PROMPT = """Convierte la descripcion en una escena JSON con objetos.
Formato EXACTO (responde SOLO el JSON):
{{"objects":[{{"name":"table","shape":"rect","x":0.5,"y":0.7,"w":0.5,"h":0.12,"color":[60,110,220]}}]}}
x,y = centro en [0,1] (y: 0=arriba,1=abajo). shape: rect|ellipse|circle|triangle.

Descripcion: {prompt}"""


def plan_with_llm(prompt: str, orch, width=512, height=512):
    """Planner con el LLM (opcional). Devuelve (Scene|None, raw). Cae a None si
    el modelo no produce JSON valido — el caller decide usar plan() de reglas."""
    import json
    try:
        raw = orch.infer(_LLM_PROMPT.format(prompt=prompt), max_tokens=400,
                         temperature=0.0).text
    except Exception as e:
        return None, f"infer error: {e}"
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return None, raw[:200]
    try:
        d = json.loads(m.group(0))
        objs = []
        for od in d.get("objects", []):
            objs.append(Obj(name=str(od.get("name", "obj")),
                            shape=od.get("shape", "rect"),
                            x=float(od["x"]), y=float(od["y"]),
                            w=float(od.get("w", 0.15)), h=float(od.get("h", 0.15)),
                            color=tuple(od.get("color", (150, 150, 150))),
                            z=int(od.get("z", 0))))
        return Scene(objects=objs, width=width, height=height), raw[:200]
    except Exception as e:
        return None, f"json/parse error: {e}"
