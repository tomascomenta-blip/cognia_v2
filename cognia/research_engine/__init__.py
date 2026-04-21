"""
cognia/research_engine/__init__.py

Módulo de investigación autónoma para Cognia.

Durante el ciclo de sueño, Cognia toma sus preguntas pendientes
(generadas por el CuriosityEngine) y las investiga usando Ollama,
integrando el conocimiento aprendido de vuelta en el KG y la memoria semántica.

Uso desde sleep() en cognia_v3.py:

    from cognia.research_engine import run_research_session, format_sleep_summary

    session = run_research_session(
        cognia_instance=self,
        db_path=self.db,
        max_questions=3,
    )
    research_info = format_sleep_summary(session)
    # Añadir research_info al return de sleep()
"""

from .research_orchestrator import (
    run_research_session,
    format_sleep_summary,
    show_research_history,
    ResearchSessionResult,
)
from .researcher import research_question, ResearchResult
from .knowledge_integrator import (
    integrate_research,
    get_research_log,
    IntegrationResult,
)

__all__ = [
    "run_research_session",
    "format_sleep_summary",
    "show_research_history",
    "ResearchSessionResult",
    "research_question",
    "ResearchResult",
    "integrate_research",
    "get_research_log",
    "IntegrationResult",
]
