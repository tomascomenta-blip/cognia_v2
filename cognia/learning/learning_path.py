"""
cognia/learning/learning_path.py
=================================
LearningPathGenerator -- template-based structured learning paths with KG enrichment.
No LLM calls. DB: learning_paths table via get_pool().get().
"""
from __future__ import annotations

import json
import time
from typing import Optional

from storage.db_pool import get_pool

_DB_PATH: Optional[str] = None  # injected by cognia_desktop_api.py at startup


def _get_db() -> str:
    if _DB_PATH:
        return _DB_PATH
    return "cognia_learning_paths.db"


_STEP_TEMPLATES: dict[str, list[str]] = {
    "python": [
        "Instalar Python y configurar entorno",
        "Aprender variables y tipos de datos",
        "Practicar control de flujo (if, for, while)",
        "Funciones y modulos",
        "Proyecto practico con los conocimientos adquiridos",
    ],
    "fastapi": [
        "Instalar FastAPI y uvicorn",
        "Crear primer endpoint GET",
        "Parametros de ruta y query",
        "Modelos Pydantic y POST endpoints",
        "Despliegue y documentacion automatica",
    ],
    "machine learning": [
        "Fundamentos de estadistica y algebra lineal",
        "Python scikit-learn basico",
        "Preparacion y limpieza de datos",
        "Modelos supervisados y evaluacion",
        "Proyecto con dataset real",
    ],
    "matematica": [
        "Aritmetica y algebra basica",
        "Ecuaciones y funciones",
        "Geometria y trigonometria",
        "Calculo diferencial",
        "Aplicaciones practicas",
    ],
    "ingles": [
        "Vocabulario basico (100 palabras)",
        "Gramatica basica presente simple",
        "Conversacion cotidiana",
        "Tiempos verbales avanzados",
        "Practica con contenido nativo",
    ],
    "web": [
        "HTML y CSS basico",
        "JavaScript fundamentals",
        "DOM manipulation y eventos",
        "Fetch API y REST",
        "Framework moderno (React/Vue)",
    ],
    "git": [
        "Instalar Git y configuracion inicial",
        "add, commit, push basico",
        "Ramas y merge",
        "Resolucion de conflictos",
        "GitHub workflow",
    ],
    "_default": [
        "Fundamentos teoricos de {topic}",
        "Primeros pasos practicos con {topic}",
        "Profundizar conceptos intermedios de {topic}",
        "Aplicacion avanzada de {topic}",
        "Proyecto integrador sobre {topic}",
    ],
}


def _init_db(db_path: str) -> None:
    with get_pool(db_path).get() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS learning_paths ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  goal TEXT NOT NULL,"
            "  steps_json TEXT NOT NULL,"
            "  current_step INTEGER NOT NULL DEFAULT 0,"
            "  completed INTEGER NOT NULL DEFAULT 0,"
            "  created_at REAL NOT NULL,"
            "  updated_at REAL NOT NULL"
            ")"
        )


def _path_to_dict(row: tuple) -> dict:
    """Convert a DB row (id, goal, steps_json, current_step, completed, created_at, updated_at) to dict."""
    path_id, goal, steps_json, current_step, completed, created_at, updated_at = row
    raw_steps = json.loads(steps_json)
    steps = [
        {"number": i + 1, "title": s, "completed": i < current_step}
        for i, s in enumerate(raw_steps)
    ]
    return {
        "id": path_id,
        "goal": goal,
        "steps": steps,
        "current_step": current_step,
        "completed": bool(completed),
        "created_at": created_at,
        "updated_at": updated_at,
    }


class LearningPathGenerator:
    """Generate and manage structured learning paths without LLM calls."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = db_path or _get_db()
        _init_db(self._db_path)

    # ── Internal ─────────────────────────────────────────────────────────

    def _pick_template(self, goal: str) -> list[str]:
        goal_lower = goal.lower()
        for keyword, steps in _STEP_TEMPLATES.items():
            if keyword == "_default":
                continue
            if keyword in goal_lower:
                return steps
        # fallback: generic template with {topic} replaced
        return [s.replace("{topic}", goal) for s in _STEP_TEMPLATES["_default"]]

    # ── Public API ────────────────────────────────────────────────────────

    def generate(self, goal: str) -> dict:
        """Find best template match, create steps, insert into DB, return path dict."""
        if not goal or not goal.strip():
            raise ValueError("goal cannot be empty")
        goal = goal.strip()
        steps = self._pick_template(goal)
        now = time.time()
        steps_json = json.dumps(steps, ensure_ascii=False)
        with get_pool(self._db_path).get() as conn:
            cur = conn.execute(
                "INSERT INTO learning_paths (goal, steps_json, current_step, completed, created_at, updated_at)"
                " VALUES (?, ?, 0, 0, ?, ?)",
                (goal, steps_json, now, now),
            )
            path_id = cur.lastrowid
            row = conn.execute(
                "SELECT id, goal, steps_json, current_step, completed, created_at, updated_at"
                " FROM learning_paths WHERE id = ?",
                (path_id,),
            ).fetchone()
        return _path_to_dict(row)

    def get_path(self, path_id: int) -> dict:
        """Fetch path by id. Raises ValueError if not found."""
        with get_pool(self._db_path).get() as conn:
            row = conn.execute(
                "SELECT id, goal, steps_json, current_step, completed, created_at, updated_at"
                " FROM learning_paths WHERE id = ?",
                (path_id,),
            ).fetchone()
        if row is None:
            raise ValueError(f"learning path {path_id} not found")
        return _path_to_dict(row)

    def advance_step(self, path_id: int) -> dict:
        """Increment current_step. Marks completed=1 if all steps done."""
        with get_pool(self._db_path).get() as conn:
            row = conn.execute(
                "SELECT id, goal, steps_json, current_step, completed, created_at, updated_at"
                " FROM learning_paths WHERE id = ?",
                (path_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"learning path {path_id} not found")
            _, goal, steps_json, current_step, completed, created_at, _ = row
            total_steps = len(json.loads(steps_json))
            if current_step >= total_steps:
                # already at end; return as-is
                return _path_to_dict(row)
            new_step = current_step + 1
            new_completed = 1 if new_step >= total_steps else 0
            now = time.time()
            conn.execute(
                "UPDATE learning_paths SET current_step = ?, completed = ?, updated_at = ? WHERE id = ?",
                (new_step, new_completed, now, path_id),
            )
            updated_row = conn.execute(
                "SELECT id, goal, steps_json, current_step, completed, created_at, updated_at"
                " FROM learning_paths WHERE id = ?",
                (path_id,),
            ).fetchone()
        return _path_to_dict(updated_row)

    def get_active_paths(self) -> list[dict]:
        """Return all paths where completed=0."""
        with get_pool(self._db_path).get() as conn:
            rows = conn.execute(
                "SELECT id, goal, steps_json, current_step, completed, created_at, updated_at"
                " FROM learning_paths WHERE completed = 0 ORDER BY created_at DESC"
            ).fetchall()
        return [_path_to_dict(r) for r in rows]

    def get_stats(self) -> dict:
        """Return total_paths, active, completed, avg_completion_pct."""
        with get_pool(self._db_path).get() as conn:
            total = conn.execute("SELECT COUNT(*) FROM learning_paths").fetchone()[0]
            active = conn.execute(
                "SELECT COUNT(*) FROM learning_paths WHERE completed = 0"
            ).fetchone()[0]
            done = conn.execute(
                "SELECT COUNT(*) FROM learning_paths WHERE completed = 1"
            ).fetchone()[0]
            rows = conn.execute(
                "SELECT steps_json, current_step FROM learning_paths"
            ).fetchall()
        if rows:
            pcts = []
            for steps_json, current_step in rows:
                n = len(json.loads(steps_json))
                pcts.append((current_step / n * 100) if n > 0 else 0.0)
            avg_pct = round(sum(pcts) / len(pcts), 1)
        else:
            avg_pct = 0.0
        return {
            "total_paths": total,
            "active": active,
            "completed": done,
            "avg_completion_pct": avg_pct,
        }
