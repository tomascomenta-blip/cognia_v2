"""
cognia/context_injector.py
==========================
Singleton que agrega contexto de metas activas y curiosity insights
al prompt del LLM — inyeccion fire-and-forget, falla silenciosamente.
"""

from __future__ import annotations


class ContextInjector:
    """
    Agrega contexto de metas y curiosity insights al prompt del LLM.
    Singleton — se inicializa una vez al import.
    """

    def __init__(self) -> None:
        self._goal_tracker = None
        self._curiosity_engine = None
        self._available = False
        try:
            from cognia.goals.goal_tracker import GoalTracker
            from cognia.reasoning.curiosity_engine import CuriosityEngine
            self._goal_tracker = GoalTracker()
            self._curiosity_engine = CuriosityEngine()
            self._available = True
        except Exception:
            pass

    def get_context_block(self, user_id: str = "local") -> str:
        """
        Retorna bloque de contexto para inyectar antes del prompt del LLM.
        Si no hay nada relevante retorna "".

        Formato:
          [Contexto del usuario]
          Metas activas: [Aprender Python (45%), ...]
          Conocimiento reciente: [tema1, tema2]
        """
        if not self._available:
            return ""

        parts: list[str] = []

        # Goals summary
        try:
            summary = self._goal_tracker.get_active_goals_summary(user_id)
            if summary:
                parts.append(summary)
        except Exception:
            pass

        # Curiosity insights — ultimas 3, solo questions (max 60 chars cada una)
        try:
            insights = self._curiosity_engine.get_insights(limit=3)
            if insights:
                questions = [
                    i.get("question", "")[:60]
                    for i in insights
                    if i.get("question")
                ]
                if questions:
                    parts.append("Conocimiento reciente: " + ", ".join(questions[:3]))
        except Exception:
            pass

        if not parts:
            return ""

        block = "[Contexto del usuario]\n" + "\n".join(parts)
        # Guardia de longitud: nunca contaminar el prompt con un bloque gigante
        return block[:500]


# Singleton de modulo — una sola instancia por proceso
_context_injector = ContextInjector()
