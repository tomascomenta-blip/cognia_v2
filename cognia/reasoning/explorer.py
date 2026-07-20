"""
cognia/reasoning/explorer.py
============================
Modo explorador 70/30 (pieza 4 de la mision creativa). Reserva parte del
presupuesto computacional para EXPLORAR ideas poco convencionales en vez de
gastarlo todo refinando lo prometedor: 70% explotacion (profundizar ideas
buenas), 30% exploracion (enfoques fundamentalmente nuevos).

Regla del GOAL: la exploracion NUNCA se elimina por completo. allocate lo
garantiza con el invariante explore_n>=1 SIEMPRE (incluso con total chico).

El backend vivo se toca SOLO via creative_generate (creative_llm.py) en _deepen,
y via repetition_detector.force_alternatives en _explore_new (que ya pide
enfoques distintos a alta temperatura). Las llamadas LLM estan acotadas a
<= total+1 (el i3 es lento, techo ~8 tok/s).
"""

from typing import Optional

from .creative_llm import creative_generate
from . import repetition_detector as _rd


def allocate(total: int, exploit_ratio: float = 0.7) -> tuple:
    """Reparte `total` unidades de presupuesto en (exploit_n, explore_n).

    explore_n = max(1, round(total*(1-exploit_ratio))) -> SIEMPRE >=1: la
    exploracion nunca se elimina (regla del GOAL). exploit_n = max(0, total-explore_n).

    Deterministico. round() usa el redondeo bancario de Python (round(1.5)=2),
    asi que con ratio 0.7 y total=5: round(5*0.3)=round(1.5)=2 -> (3, 2). Para
    total<=1 devolvemos (0, 1): al menos exploramos una idea nueva.

    Invariante: explore_n >= 1 para CUALQUIER total y ratio; y para total>=1,
    exploit_n + explore_n == total.
    """
    if total <= 1:
        return (0, 1)
    explore_n = max(1, round(total * (1.0 - exploit_ratio)))
    # Cap: si el ratio es muy bajo, explore_n podria pasarse de total y dejar
    # exploit_n negativo; lo acotamos para conservar la suma == total.
    explore_n = min(explore_n, total)
    exploit_n = max(0, total - explore_n)
    return (exploit_n, explore_n)


def _deepen(orchestrator, problem: str, idea: str) -> Optional[str]:
    """EXPLOTACION de una idea prometedora: pide al LLM que la profundice/refine
    para el problema concreto (mas detalle, como implementarla). Temperatura
    media (0.5): explotar es refinar, no divergir. None si falla o sale corto.
    """
    if orchestrator is None or not idea or not idea.strip():
        return None
    prompt = (
        f"Problema: {problem.strip()}\n\n"
        f"Idea prometedora a profundizar:\n{idea.strip()}\n\n"
        "Profundiza y refina ESTA idea concreta (no propongas otra): agrega "
        "detalle, di COMO implementarla, que pasos seguir y que la hace funcionar. "
        "Se concreto y directo, sin introduccion."
    )
    return creative_generate(orchestrator, prompt, temperature=0.5, max_tokens=280)


def _explore_new(orchestrator, problem: str, known: list, n: int) -> list:
    """EXPLORACION: reusa repetition_detector.force_alternatives, que ya pide
    enfoques FUNDAMENTALMENTE DISTINTOS de los `known` a alta temperatura y
    filtra los genuinamente nuevos. Devuelve la lista (vacia si nada nuevo).
    """
    if n <= 0:
        return []
    return _rd.force_alternatives(orchestrator, problem, known, n=n)


def explore_exploit(orchestrator, problem: str, known: list, total: int = 5,
                    exploit_ratio: float = 0.7) -> dict:
    """Corre un ciclo explotacion/exploracion 70/30 sobre un problema.

    `known` se asume PRE-RANKEADO por valor (mejores primero): explotamos las
    primeras exploit_n profundizandolas, y exploramos explore_n enfoques nuevos
    que eviten todo lo conocido. El total de llamadas LLM queda acotado a
    <= total+1 (exploit_n _deepen + 1 force_alternatives), por el i3 lento.

    Sin backend o problema vacio -> dict con reason y listas vacias.
    """
    if orchestrator is None or not problem or not problem.strip():
        return {"exploit_n": 0, "explore_n": 0, "exploited": [], "explored": [],
                "reason": "sin backend o problema vacio"}

    known = [k for k in (known or []) if k and k.strip()]
    exploit_n, explore_n = allocate(total, exploit_ratio)
    # Si no hay ideas conocidas no se puede explotar nada: exploit efectivo 0
    # (pero igual se explora, explore_n>=1 por el invariante de allocate).
    exploit_efectivo = min(exploit_n, len(known))

    exploited = []
    for idea in known[:exploit_efectivo]:
        profundizada = _deepen(orchestrator, problem, idea)
        if profundizada:
            exploited.append({"base": idea, "profundizada": profundizada})

    explored = _explore_new(orchestrator, problem, known, explore_n)

    return {
        "exploit_ratio": exploit_ratio,
        "exploit_n": exploit_n,
        "explore_n": explore_n,
        "exploited": exploited,
        "explored": explored,
    }
