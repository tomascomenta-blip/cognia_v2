"""
cognia/goals/goal_suggester.py
==============================
Sugiere metas proactivamente al usuario basandose en su perfil de intereses
y patrones de consulta. Sin LLM calls — matching de plantillas determinista.
"""

from __future__ import annotations

from typing import Optional

# Plantillas de sugerencias por dominio detectado
_SUGGESTIONS_BY_TOPIC: dict[str, list[str]] = {
    "python": [
        "Completar un proyecto Python de principio a fin",
        "Aprender testing con pytest",
        "Publicar un paquete en PyPI",
    ],
    "javascript": [
        "Construir una SPA con vanilla JS",
        "Aprender Node.js backend",
        "Publicar un paquete npm",
    ],
    "machine": [
        "Entrenar un modelo en un dataset propio",
        "Leer 3 papers de ML este mes",
        "Implementar un clasificador desde cero",
    ],
    "learning": [
        "Crear un sistema de notas estructurado",
        "Revisar apuntes cada semana",
        "Ensenar lo aprendido a alguien",
    ],
    "fastapi": [
        "Desplegar una API en produccion",
        "Agregar autenticacion a tu API",
        "Escribir tests para todos los endpoints",
    ],
    "datos": [
        "Analizar un dataset real",
        "Crear visualizaciones de datos",
        "Aprender SQL avanzado",
    ],
    "data": [
        "Analyze a real dataset",
        "Build a data pipeline",
        "Learn advanced SQL",
    ],
    "code": [
        "Refactor a project to improve readability",
        "Add tests to an existing project",
        "Contribute to an open source project",
    ],
    "design": [
        "Create a design system",
        "Learn Figma advanced features",
        "Build a portfolio",
    ],
    "writing": [
        "Write one article per week",
        "Start a technical blog",
        "Document a project completely",
    ],
    "typescript": [
        "Migrar un proyecto JS a TypeScript",
        "Aprender tipos avanzados de TypeScript",
        "Configurar un proyecto con strict mode",
    ],
    "react": [
        "Construir una app completa con React",
        "Aprender React hooks avanzados",
        "Publicar un componente en npm",
    ],
}

_PATTERN_SUGGESTIONS: dict[str, list[str]] = {
    "asks_how": [
        "Documentar 3 cosas que aprendiste esta semana",
        "Crear un wiki personal de conocimiento",
    ],
    "asks_code": [
        "Completar un proyecto de codigo de principio a fin",
        "Mejorar la cobertura de tests de un proyecto",
    ],
    "asks_why": [
        "Leer un libro tecnico completo",
        "Investigar a fondo un tema que te genera dudas",
    ],
    "asks_list": [
        "Organizar tus tareas pendientes en categorias",
        "Crear un roadmap personal de aprendizaje",
    ],
}

_GENERIC_SUGGESTIONS: list[str] = [
    "Definir una meta de aprendizaje para este mes",
    "Revisar tus avances semanalmente",
    "Compartir algo que hayas aprendido con otro",
]


class GoalSuggester:
    """
    Sugiere metas basandose en el perfil del usuario y sus metas activas.
    Sin LLM calls — basado en plantillas + matching de topicos.
    """

    def suggest(self, user_id: str, max_suggestions: int = 5) -> list[dict]:
        """
        Retorna lista de sugerencias:
        [{"title": str, "reason": str, "source": "topic"|"pattern"|"generic"}]

        Logica:
        1. Cargar perfil del usuario (UserProfileBuilder)
        2. Para cada top_topic: buscar en _SUGGESTIONS_BY_TOPIC
        3. Para cada query_pattern: buscar en _PATTERN_SUGGESTIONS
        4. Filtrar sugerencias que ya son metas activas (para no duplicar)
        5. Deduplicar y retornar top max_suggestions
        """
        profile = self._load_user_profile(user_id)
        active_titles = self._get_active_goal_titles(user_id)

        seen: set[str] = set()
        suggestions: list[dict] = []

        # --- topic-based suggestions ---
        if profile:
            for topic_entry in profile.get("top_topics", []):
                term = topic_entry.get("term", "") if isinstance(topic_entry, dict) else str(topic_entry)
                term_lower = term.lower()
                for key, titles in _SUGGESTIONS_BY_TOPIC.items():
                    if key in term_lower or term_lower in key:
                        for title in titles:
                            title_lower = title.lower()
                            if title_lower not in seen and title_lower not in active_titles:
                                seen.add(title_lower)
                                suggestions.append({
                                    "title": title,
                                    "reason": f"Basado en tu interes en {term}",
                                    "source": "topic",
                                })
                        break  # one key match per term is enough

        # --- pattern-based suggestions ---
        if profile:
            for pattern in profile.get("query_patterns", []):
                for title in _PATTERN_SUGGESTIONS.get(pattern, []):
                    title_lower = title.lower()
                    if title_lower not in seen and title_lower not in active_titles:
                        seen.add(title_lower)
                        suggestions.append({
                            "title": title,
                            "reason": f"Segun tu patron de consultas: {pattern}",
                            "source": "pattern",
                        })

        # --- generic fallback if we still have room ---
        if len(suggestions) < max_suggestions:
            for title in _GENERIC_SUGGESTIONS:
                title_lower = title.lower()
                if title_lower not in seen and title_lower not in active_titles:
                    seen.add(title_lower)
                    suggestions.append({
                        "title": title,
                        "reason": "Sugerencia general de productividad",
                        "source": "generic",
                    })
                if len(suggestions) >= max_suggestions:
                    break

        return suggestions[:max_suggestions]

    def _get_active_goal_titles(self, user_id: str) -> set[str]:
        """Carga metas activas y retorna set de titles lowercase."""
        try:
            from cognia.goals.goal_tracker import GoalTracker
            tracker = GoalTracker()
            goals = tracker.get_goals(user_id, status="active")
            return {g["title"].lower() for g in goals}
        except Exception:
            return set()

    def _load_user_profile(self, user_id: str) -> Optional[dict]:
        """
        Importa UserProfileBuilder y carga perfil.
        Retorna None si no hay perfil.
        """
        try:
            from cognia.profile.user_profile_builder import UserProfileBuilder
            builder = UserProfileBuilder()
            return builder.get_profile(user_id)
        except Exception:
            return None

    def get_suggestions_context(self, user_id: str) -> str:
        """
        Retorna string corto para inyectar en context:
        "Sugerencias de metas: [Aprender testing con pytest, Publicar paquete npm]"
        "" si no hay sugerencias.
        """
        suggestions = self.suggest(user_id, max_suggestions=3)
        if not suggestions:
            return ""
        titles = [s["title"] for s in suggestions]
        return "Sugerencias de metas: [" + ", ".join(titles) + "]"
