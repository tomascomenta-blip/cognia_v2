"""
cognia/reasoning/idea_eval.py
=============================
Autoevaluacion de novedad (pieza 8 de la mision creativa). Toma una idea y la
puntua en tres ejes 0.0-1.0 (novedad x factibilidad x impacto) con UNA llamada
LLM de baja temperatura, parseo robusto y reintento si el parseo da vacio (la 1a
llamada en server frio a veces vuelve sin los ejes). Reusa la leccion de
hypothesis.generate_many: si tras el reintento no se pudo parsear, se devuelve
None (honesto) en vez de inventar puntajes.

El backend vivo se toca SOLO via creative_generate (creative_llm.py).
"""

import re
from typing import Optional

from .creative_llm import creative_generate


# Mapea variantes (con/sin acento) al nombre canonico del eje.
_AXIS_ALIASES = {
    "novedad":      "novedad",
    "factibilidad": "factibilidad",
    "impacto":      "impacto",
}

# Una linea "<eje> <sep> <valor>": separador ':' '=' o '-', valor 0.0-1.0
# admitiendo "0.7", ".7", "1", "0,7" (coma decimal). El nombre del eje se captura
# crudo (con o sin acento) y se normaliza despues contra _AXIS_ALIASES.
_AXIS_RE = re.compile(
    r"([A-Za-zÁÉÍÓÚáéíóúÑñ]+)\s*[:=\-]\s*([01](?:[.,]\d+)?|[.,]\d+)",
    re.UNICODE,
)


def _strip_accents(s: str) -> str:
    """Quita acentos basicos para casar 'novedad'/'novédad' sin depender de unicodedata."""
    table = str.maketrans("áéíóúÁÉÍÓÚ", "aeiouAEIOU")
    return s.translate(table)


def _parse_axes(text: str) -> dict:
    """Parsea hasta tres ejes de una respuesta tipo:

        novedad: 0.7
        factibilidad: 0.5
        impacto: 0.8

    Robusto a mayus/minus, acentos ausentes, separador ':' '=' o '-', y valor
    "0.7"/".7"/"1"/"0,7" (coma). Devuelve {"novedad","factibilidad","impacto"}
    SOLO con los ejes que parseo (clamp [0,1]); los faltantes no aparecen.
    """
    out = {}
    if not text:
        return out
    for raw_name, raw_val in _AXIS_RE.findall(text):
        key = _strip_accents(raw_name).lower()
        axis = _AXIS_ALIASES.get(key)
        if axis is None or axis in out:
            continue
        try:
            val = float(raw_val.replace(",", "."))
        except ValueError:
            continue
        out[axis] = max(0.0, min(1.0, val))
    return out


def _eval_prompt(idea: str, context: str) -> str:
    """Arma el prompt de evaluacion en el formato exacto de 3 ejes."""
    ctx = ""
    if context and context.strip():
        ctx = f"Contexto: {context.strip()}\n"
    return (
        f"{ctx}Idea: {idea.strip()}\n\n"
        "Evalua esta idea en TRES ejes, cada uno entre 0.0 y 1.0:\n"
        "- novedad: que tan original y no obvia es.\n"
        "- factibilidad: que tan realista es de implementar.\n"
        "- impacto: que efecto potencial tendria si funciona.\n"
        "Responde SOLO en este formato exacto, una linea por eje:\n"
        "novedad: 0.6\nfactibilidad: 0.7\nimpacto: 0.5\n"
    )


def evaluate_idea(orchestrator, idea: str, context: str = "") -> Optional[dict]:
    """Evalua una idea en novedad x factibilidad x impacto via el LLM vivo.

    Una llamada de baja temperatura (0.25, max_tokens 120) que pide los tres
    ejes. Si el parseo no devuelve los 3, REINTENTA una vez (rescata el edge de
    server frio). Si tras el reintento no se parseo NINGUN eje, devuelve None
    (honesto: no se pudo evaluar). Si se parseo al menos uno pero falta alguno,
    el faltante toma default 0.5. value = round(nov*fac*imp, 3).
    Devuelve {"novedad","factibilidad","impacto","value"} (todos a 3 decimales).
    """
    if orchestrator is None or not idea or not idea.strip():
        return None

    prompt = _eval_prompt(idea, context)
    raw = creative_generate(orchestrator, prompt, temperature=0.25, max_tokens=120)
    axes = _parse_axes(raw or "")
    # Reintento si faltan ejes: la 1a llamada en server frio a veces vuelve
    # vacia/incompleta (mismo edge documentado en hypothesis.generate_many).
    if len(axes) < 3:
        raw = creative_generate(orchestrator, prompt, temperature=0.25, max_tokens=120)
        retry = _parse_axes(raw or "")
        # Conserva lo que ya teniamos y completa con lo nuevo (no piso ejes buenos).
        for k, v in retry.items():
            axes.setdefault(k, v)

    if not axes:
        # Fallo total tras el reintento: no inventamos numeros.
        return None

    nov = axes.get("novedad", 0.5)
    fac = axes.get("factibilidad", 0.5)
    imp = axes.get("impacto", 0.5)
    value = round(nov * fac * imp, 3)
    return {
        "novedad":      round(nov, 3),
        "factibilidad": round(fac, 3),
        "impacto":      round(imp, 3),
        "value":        value,
    }


def rank_ideas(orchestrator, ideas: list) -> list:
    """Evalua cada idea (una llamada por idea) y devuelve los items ordenados
    por value desc. Las que evaluan None van al final con value=None y marcadas
    (no se inventan). Acota a las primeras 8 ideas: si llegan mas, evalua solo
    esas 8 y registra el truncado en cada item devuelto (no se silencia).
    """
    items = []
    if not ideas:
        return items

    truncated = len(ideas) > 8
    to_eval = ideas[:8] if truncated else ideas

    for idea in to_eval:
        ev = evaluate_idea(orchestrator, idea)
        if ev is None:
            item = {"idea": idea, "novedad": None, "factibilidad": None,
                    "impacto": None, "value": None}
        else:
            item = {"idea": idea, **ev}
        if truncated:
            item["truncated"] = True
        items.append(item)

    # value None al final; entre los puntuados, value desc. Clave estable.
    items.sort(key=lambda d: (d["value"] is None, -(d["value"] or 0.0)))
    return items
