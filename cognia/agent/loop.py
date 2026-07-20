"""
cognia/agent/loop.py
====================
Dynamic step-budgeting for the agent loop.

The old loop ran a fixed 12 steps for every task -- wasteful for "que hora es"
and too short for "refactoriza este modulo". This lets the agent decide HOW MANY
steps a task deserves, with a hard ceiling so it can never run away.

Concrete, not abstract: two plain functions and a couple of constants.
"""

from __future__ import annotations

import re

# Absolute safety ceiling -- the loop can never exceed this regardless of the
# model's estimate or extension requests. Prevents a stuck agent from looping
# forever while still being "effectively unlimited" for real tasks.
AGENT_HARD_CAP = 40

# Complexity rating (1-5) -> initial step budget.
_RATING_TO_BUDGET = {1: 2, 2: 4, 3: 8, 4: 16, 5: 28}

# Cheap keyword prior used when the model is unavailable or vague.
_SIMPLE_HINTS = (
    "hola", "gracias", "que es", "que hora", "fecha", "define", "calcula",
    "calcular", "suma", "resta", "cuanto es",
)


def estimate_step_budget(task: str, orch, hard_cap: int = AGENT_HARD_CAP) -> int:
    """
    Decide how many steps to grant this task.

    First a cheap heuristic prior, then one quick LLM complexity rating (1-5).
    The rating wins when available; otherwise the heuristic stands. Always
    clamped to [1, hard_cap].
    """
    tl = task.lower()
    if len(task) < 60 and any(h in tl for h in _SIMPLE_HINTS):
        heuristic = 2
    elif len(task) > 200:
        heuristic = 8
    else:
        heuristic = 4

    try:
        prompt = (
            "Clasifica la COMPLEJIDAD de esta tarea para un agente con "
            "herramientas, del 1 (trivial, 1-2 pasos) al 5 (muy compleja, muchos "
            "pasos). Responde SOLO el numero.\n\nTarea: " + task[:400]
        )
        rating_text = orch.infer(prompt).text
        m = re.search(r"[1-5]", rating_text)
        if m:
            return max(1, min(_RATING_TO_BUDGET[int(m.group())], hard_cap))
    except Exception:
        pass
    return max(1, min(heuristic, hard_cap))


def wants_more_steps(task: str, last_results: str, orch, inferir=None) -> int:
    """
    When the budget runs out without a final answer, ask the model whether the
    task is actually done and, if not, how many MORE steps it needs. Returns the
    number of extra steps to grant (0 = done / no extension). Bounded small so an
    extension can't itself run away; the caller still enforces AGENT_HARD_CAP.

    `inferir(orch, prompt) -> str` permite pasar el mismo camino de inferencia
    que usa el bucle, con su caida a llm_local. Sin eso, esta funcion sacaba un
    digito a la brava del texto que devolviera el orquestador — incluido su
    aviso de "no hay backend", que NO es una excepcion sino una respuesta
    normal. Medido el 2026-07-20: eso concedia pasos extra una y otra vez sobre
    un fallo que no se iba a arreglar solo, y el agente encadeno 40 rondas.
    """
    try:
        prompt = (
            "Un agente trabajo en esta tarea pero se quedo sin pasos. Mira el "
            "ultimo progreso. Si la tarea YA esta resuelta responde 0. Si falta, "
            "responde SOLO cuantos pasos mas necesita (1-8).\n\n"
            f"Tarea: {task[:300]}\n\nUltimo progreso:\n{last_results[:600]}"
        )
        texto = (inferir(orch, prompt) if inferir
                 else (orch.infer(prompt).text or ""))
        if not texto:
            return 0
        m = re.search(r"\b([0-8])\b", texto)
        if m:
            return int(m.group(1))
    except Exception:
        pass
    return 0
