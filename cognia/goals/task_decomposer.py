"""
cognia/goals/task_decomposer.py
================================
Decomposes a goal into sub-tasks using deterministic domain templates.
Sub-tasks are created as child goals with parent_id pointing to the parent.
Zero LLM calls — keyword matching only.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from storage.db_pool import get_pool

_GOALS_DB = str(Path(__file__).parent.parent.parent / "cognia_desktop_chat.db")

_DECOMPOSITION_TEMPLATES: dict[str, list[str]] = {
    "aprender": [
        "Buscar recursos sobre {topic}",
        "Practicar {topic} con ejercicios basicos",
        "Construir un proyecto pequeno con {topic}",
        "Revisar lo aprendido y tomar notas",
        "Ensenar {topic} a alguien o escribir un articulo",
    ],
    "learn": [
        "Find resources about {topic}",
        "Practice {topic} with basic exercises",
        "Build a small project using {topic}",
        "Review and take notes",
        "Share knowledge about {topic}",
    ],
    "crear": [
        "Definir los requisitos de {topic}",
        "Disenar la arquitectura de {topic}",
        "Implementar version minima de {topic}",
        "Testear y corregir errores en {topic}",
        "Documentar y publicar {topic}",
    ],
    "build": [
        "Define requirements for {topic}",
        "Design architecture for {topic}",
        "Implement MVP of {topic}",
        "Test and fix {topic}",
        "Document and release {topic}",
    ],
    "leer": [
        "Conseguir el libro/material",
        "Leer primeros capitulos",
        "Tomar notas clave",
        "Completar la lectura",
        "Resumir lo aprendido",
    ],
    "read": [
        "Get the book/material",
        "Read first chapters",
        "Take key notes",
        "Complete reading",
        "Summarize learnings",
    ],
    "mejorar": [
        "Evaluar el estado actual de {topic}",
        "Identificar los 3 principales problemas de {topic}",
        "Implementar mejoras en {topic}",
        "Medir el impacto de las mejoras",
    ],
    "improve": [
        "Assess current state of {topic}",
        "Identify top 3 issues with {topic}",
        "Implement improvements to {topic}",
        "Measure impact of changes",
    ],
}

_DEFAULT_TEMPLATE = [
    "Planificar el enfoque",
    "Dar el primer paso concreto",
    "Revisar el progreso",
    "Completar la tarea",
]


def _row_to_dict(row) -> dict:
    return {
        "id":           row[0],
        "user_id":      row[1],
        "title":        row[2],
        "description":  row[3],
        "status":       row[4],
        "progress_pct": row[5],
        "created_at":   row[6],
        "updated_at":   row[7],
        "completed_at": row[8],
        "parent_id":    row[9] if len(row) > 9 else None,
    }


class TaskDecomposer:
    """
    Decomposes a goal into sub-tasks using domain templates.
    Sub-tasks are stored as child goals with parent_id=goal_id.
    Uses storage/db_pool.py — never calls sqlite3.connect() directly.
    """

    def __init__(self, db_path: str = _GOALS_DB):
        self._db = db_path
        self._ensure_parent_id_column()

    def _ensure_parent_id_column(self) -> None:
        """Add parent_id column to user_goals if it doesn't exist yet."""
        with get_pool(self._db).get() as conn:
            try:
                conn.execute(
                    "ALTER TABLE user_goals ADD COLUMN parent_id INTEGER DEFAULT NULL"
                )
            except Exception:
                # Column already exists — expected after first run
                pass

    def _detect_template(self, title: str) -> tuple[str, str]:
        """
        Returns (template_key, topic_extracted).
        topic_extracted: words from title excluding the matched keyword.
        Falls back to ("_default", title) when no keyword matches.
        """
        title_lower = title.lower().strip()
        for key in _DECOMPOSITION_TEMPLATES:
            if key in title_lower:
                topic = title_lower.replace(key, "").strip()
                return key, topic or "esto"
        return "_default", title

    def decompose(
        self,
        goal_id: int,
        user_id: str,
        max_subtasks: int = 5,
    ) -> list[dict]:
        """
        Load goal by id, detect the right template by keyword in the title,
        and create child goals with parent_id=goal_id.
        Returns the list of created sub-goals.
        Raises ValueError if goal_id not found for user_id.
        """
        # Fetch the parent goal
        with get_pool(self._db).get() as conn:
            row = conn.execute(
                "SELECT id, user_id, title, description, status, progress_pct, "
                "created_at, updated_at, completed_at FROM user_goals "
                "WHERE id = ? AND user_id = ?",
                (goal_id, user_id),
            ).fetchone()

        if row is None:
            raise ValueError(f"Goal {goal_id} not found for user '{user_id}'")

        parent_title = row[2]
        template_key, topic = self._detect_template(parent_title)

        if template_key == "_default":
            steps = _DEFAULT_TEMPLATE[:max_subtasks]
        else:
            raw = _DECOMPOSITION_TEMPLATES[template_key]
            steps = raw[:max_subtasks]

        # Create each sub-task as a child goal
        created = []
        now = int(time.time())
        with get_pool(self._db).get() as conn:
            for step in steps:
                title = step.format(topic=topic) if "{topic}" in step else step
                cur = conn.execute(
                    """
                    INSERT INTO user_goals
                        (user_id, title, description, status, progress_pct,
                         created_at, updated_at, parent_id)
                    VALUES (?, ?, '', 'active', 0, ?, ?, ?)
                    """,
                    (user_id, title, now, now, goal_id),
                )
                sub_id = cur.lastrowid
                created.append({
                    "id":           sub_id,
                    "user_id":      user_id,
                    "title":        title,
                    "description":  "",
                    "status":       "active",
                    "progress_pct": 0,
                    "created_at":   now,
                    "updated_at":   now,
                    "completed_at": None,
                    "parent_id":    goal_id,
                })

        return created

    def get_subtasks(self, parent_id: int) -> list[dict]:
        """Return all child goals for parent_id."""
        with get_pool(self._db).get() as conn:
            rows = conn.execute(
                "SELECT id, user_id, title, description, status, progress_pct, "
                "created_at, updated_at, completed_at, parent_id "
                "FROM user_goals WHERE parent_id = ? ORDER BY id",
                (parent_id,),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]
