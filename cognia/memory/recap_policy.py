"""
cognia/memory/recap_policy.py — FASE 6 (O2 + O3)
================================================
O3 — Recapitulacion automatica: decide CUANDO recapitular el contexto, segun los
disparadores del objetivo (cantidad de turnos, tamano de contexto, demasiadas tareas
activas, multiples objetivos simultaneos). Pura, sin LLM, testeable.

O2 — Taxonomia canonica de memoria multinivel: mapea los 5 niveles del objetivo a las
piezas REALES del repo (fuente unica para no crear estructuras duplicadas).
"""

from __future__ import annotations

# Disparadores por defecto (O3)
RECAP_TURN_INTERVAL     = 10     # cada N turnos de usuario
RECAP_MAX_CONTEXT_CHARS = 8000   # ~2000 tokens de historial acumulado
RECAP_MAX_ACTIVE_TASKS  = 5
RECAP_MAX_GOALS         = 3

# Taxonomia canonica O2: nivel del objetivo -> pieza real existente (NO duplicar).
MEMORY_LEVELS = {
    "inmediata": "context/band_router.py banda LOCAL (fast-path de la respuesta actual)",
    "sesion":    "cli.py _history + memory/conversation_memory.py (buffer de turnos)",
    "trabajo":   "goals/goal_tracker.py (objetivos/tareas activos)",
    "proyectos": "memory/project_memory.py project_flows (estado persistente de flujos /flujo, "
                 "retomable entre sesiones) + agents/task_queue.py agent_tasks (tareas)",
    "historica": "memory/episodic.py + memory/semantic.py + knowledge_graph (KG)",
}


def should_recap(
    n_user_turns: int,
    context_chars: int = 0,
    n_active_tasks: int = 0,
    n_goals: int = 0,
    turn_interval: int = RECAP_TURN_INTERVAL,
    max_context_chars: int = RECAP_MAX_CONTEXT_CHARS,
) -> tuple[bool, str]:
    """Decide si conviene recapitular ahora. Devuelve (bool, motivo). Sin LLM.

    Dispara cuando: se cumplen N turnos, el contexto supera el umbral de chars, hay
    demasiadas tareas activas, o hay multiples objetivos simultaneos (objetivo O3).
    """
    if turn_interval > 0 and n_user_turns > 0 and n_user_turns % turn_interval == 0:
        return (True, f"turnos={n_user_turns} (cada {turn_interval})")
    if max_context_chars > 0 and context_chars >= max_context_chars:
        return (True, f"contexto={context_chars}>={max_context_chars} chars")
    if n_active_tasks >= RECAP_MAX_ACTIVE_TASKS:
        return (True, f"tareas activas={n_active_tasks}")
    if n_goals >= RECAP_MAX_GOALS:
        return (True, f"objetivos simultaneos={n_goals}")
    return (False, "")
