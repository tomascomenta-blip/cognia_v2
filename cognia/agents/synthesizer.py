"""
cognia/agents/synthesizer.py — Phase 24

El único componente del agent runtime que usa LLM.
Toma los resultados acumulados de los workers y genera la respuesta final
vía ShatteringOrchestrator (TECHNE/LOGOS/RHETOR según contenido).

Presupuesto: 1 LLM call por tarea, contexto máximo ~300 tokens.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from cognia.agents.planner import SubTask

# Tokens máximos del contexto que se envía al LLM
_MAX_CONTEXT_TOKENS = 300
# Chars aproximados por token (estimación conservadora)
_CHARS_PER_TOKEN    = 4
_MAX_CONTEXT_CHARS  = _MAX_CONTEXT_TOKENS * _CHARS_PER_TOKEN


def synthesize(
    task_description: str,
    subtasks: List[SubTask],
    results: Dict[str, Any],
    orchestrator=None,
    lpc_session_id: Optional[str] = None,
) -> str:
    """
    Genera la respuesta final para el usuario.

    Si hay un orchestrator disponible: usa LLM (1 call).
    Si no: retorna resumen estructurado determinista (fallback).
    """
    context = _build_context(task_description, subtasks, results)

    if orchestrator is not None:
        try:
            result = orchestrator.infer(context, lpc_session_id=lpc_session_id)
            return result.text
        except Exception as e:
            # LLM falló — caer al resumen determinista
            pass

    return _deterministic_summary(task_description, subtasks, results)


def _build_context(
    task_description: str,
    subtasks: List[SubTask],
    results: Dict[str, Any],
) -> str:
    """
    Construye el prompt para el LLM respetando el presupuesto de tokens.
    Formato compacto: tarea + resultados de workers en texto plano.
    """
    lines = [
        f"Task: {task_description}",
        "",
        "Gathered information:",
    ]

    budget = _MAX_CONTEXT_CHARS - len("\n".join(lines))

    for st in subtasks:
        if st.tool_required == "synthesize":
            continue
        r = results.get(st.id)
        if r is None:
            continue

        # Extraer texto del resultado (puede ser dict o str)
        if isinstance(r, dict):
            text = r.get("content") or r.get("extract") or r.get("output") or str(r)
        else:
            text = str(r)

        text = text.strip()
        if not text:
            continue

        entry = f"- [{st.tool_required}] {text}"
        if len(entry) > budget:
            entry = entry[:budget] + "..."
            lines.append(entry)
            break
        lines.append(entry)
        budget -= len(entry)
        if budget <= 0:
            break

    lines.append("")
    lines.append("Provide a clear, concise answer based on the information above.")
    return "\n".join(lines)


def _deterministic_summary(
    task_description: str,
    subtasks: List[SubTask],
    results: Dict[str, Any],
) -> str:
    """Resumen estructurado cuando el LLM no está disponible."""
    parts = [f"Results for: {task_description}", ""]
    for st in subtasks:
        if st.tool_required == "synthesize":
            continue
        r = results.get(st.id)
        if r is None:
            continue
        if isinstance(r, dict):
            text = r.get("content") or r.get("output") or str(r)
        else:
            text = str(r)
        if text.strip():
            parts.append(f"[{st.tool_required}] {text.strip()[:400]}")
    return "\n".join(parts) if len(parts) > 2 else f"No results for: {task_description}"
