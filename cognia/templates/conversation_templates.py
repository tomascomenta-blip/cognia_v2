"""
conversation_templates.py
=========================
Predefined conversation templates for structured work sessions.
Builtin templates live in code (stable); custom templates are stored in the
chat DB via storage/db_pool.py.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone

BUILTIN_TEMPLATES: dict[str, dict] = {
    "code_review": {
        "id": "code_review",
        "name": "Code Review",
        "description": "Revision sistematica de codigo",
        "initial_prompt": "Vamos a hacer una revision de codigo. Por favor proporciona el codigo que quieres revisar.",
        "guide_questions": [
            "El codigo sigue las convenciones del proyecto?",
            "Hay posibles bugs o casos edge no manejados?",
            "El codigo es legible y esta bien documentado?",
            "Hay oportunidades de optimizacion?",
            "Las pruebas cubren los casos importantes?",
        ],
        "tags": ["codigo", "revision", "calidad"],
        "estimated_turns": 5,
        "builtin": True,
    },
    "brainstorming": {
        "id": "brainstorming",
        "name": "Brainstorming",
        "description": "Generacion libre de ideas sobre un tema",
        "initial_prompt": "Vamos a hacer un brainstorming. Cual es el tema o problema sobre el que quieres generar ideas?",
        "guide_questions": [
            "Cuales son las soluciones mas obvias?",
            "Que pasaria si hicieramos lo contrario?",
            "Como lo resolveria alguien de otro campo?",
            "Cuales son las restricciones reales vs asumidas?",
            "Cual es la idea mas loca que se nos ocurre?",
        ],
        "tags": ["ideas", "creatividad", "problema"],
        "estimated_turns": 8,
        "builtin": True,
    },
    "study_session": {
        "id": "study_session",
        "name": "Sesion de Estudio",
        "description": "Sesion estructurada para aprender un concepto",
        "initial_prompt": "Vamos a estudiar juntos. Que concepto o tema quieres aprender hoy?",
        "guide_questions": [
            "Que sabes ya sobre este tema?",
            "Cual es la parte que encuentras mas dificil?",
            "Puedes darme un ejemplo de uso real?",
            "Como se relaciona con lo que ya sabes?",
            "Puedes explicarlo con tus propias palabras?",
        ],
        "tags": ["estudio", "aprendizaje", "concepto"],
        "estimated_turns": 10,
        "builtin": True,
    },
    "debugging": {
        "id": "debugging",
        "name": "Debugging Session",
        "description": "Proceso sistematico para encontrar y corregir bugs",
        "initial_prompt": "Vamos a hacer debugging. Describe el problema que estas experimentando y el comportamiento esperado.",
        "guide_questions": [
            "Cuando ocurrio por primera vez el error?",
            "Es reproducible consistentemente?",
            "Que cambios recientes podrian haberlo causado?",
            "Que dice el stack trace o mensaje de error?",
            "Ya probaste alguna solucion?",
        ],
        "tags": ["debugging", "error", "bug"],
        "estimated_turns": 6,
        "builtin": True,
    },
    "planning": {
        "id": "planning",
        "name": "Sesion de Planificacion",
        "description": "Planificar un proyecto o tarea compleja",
        "initial_prompt": "Vamos a planificar. Que proyecto o tarea quieres planificar?",
        "guide_questions": [
            "Cual es el objetivo final medible?",
            "Cuales son los pasos principales?",
            "Que recursos necesitas?",
            "Cuales son los riesgos principales?",
            "Cual es la fecha limite?",
        ],
        "tags": ["planificacion", "proyecto", "organizacion"],
        "estimated_turns": 7,
        "builtin": True,
    },
}

_REQUIRED_FIELDS = {"name", "description", "initial_prompt", "guide_questions"}


def _slugify(text: str) -> str:
    """Convert text to a URL-safe slug."""
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_-]+", "_", slug)
    slug = slug.strip("_")
    return slug or uuid.uuid4().hex[:8]


def _init_custom_table(db_path: str) -> None:
    from storage.db_pool import get_pool
    with get_pool(db_path).get() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS custom_templates ("
            "  id TEXT PRIMARY KEY,"
            "  name TEXT NOT NULL,"
            "  description TEXT NOT NULL,"
            "  initial_prompt TEXT NOT NULL,"
            "  guide_questions TEXT NOT NULL,"  # JSON array
            "  tags TEXT NOT NULL DEFAULT '[]',"  # JSON array
            "  estimated_turns INTEGER NOT NULL DEFAULT 5,"
            "  created_at TEXT NOT NULL"
            ")"
        )


class ConversationTemplateManager:
    """
    Manages conversation templates: builtin (in-code) + custom (stored in DB).

    Table: custom_templates — see _init_custom_table for schema.
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path
        if db_path:
            _init_custom_table(db_path)

    # ── helpers ──────────────────────────────────────────────────────────

    def _fetch_custom(self) -> list[dict]:
        if not self._db_path:
            return []
        from storage.db_pool import get_pool
        with get_pool(self._db_path).get() as conn:
            rows = conn.execute(
                "SELECT id, name, description, initial_prompt, guide_questions,"
                "       tags, estimated_turns, created_at"
                " FROM custom_templates ORDER BY created_at"
            ).fetchall()
        result = []
        for row in rows:
            tid, name, desc, ip, gq_json, tags_json, est, created = row
            result.append({
                "id": tid,
                "name": name,
                "description": desc,
                "initial_prompt": ip,
                "guide_questions": json.loads(gq_json),
                "tags": json.loads(tags_json),
                "estimated_turns": est,
                "created_at": created,
                "builtin": False,
            })
        return result

    # ── public API ────────────────────────────────────────────────────────

    def list_templates(self, tag: str | None = None) -> list[dict]:
        """Return all templates (builtin + custom). Optionally filter by tag."""
        all_templates = list(BUILTIN_TEMPLATES.values()) + self._fetch_custom()
        if tag:
            all_templates = [t for t in all_templates if tag in t.get("tags", [])]
        return all_templates

    def get_template(self, template_id: str) -> dict | None:
        """Return a template by id, or None if not found."""
        if template_id in BUILTIN_TEMPLATES:
            return BUILTIN_TEMPLATES[template_id]
        if not self._db_path:
            return None
        from storage.db_pool import get_pool
        with get_pool(self._db_path).get() as conn:
            row = conn.execute(
                "SELECT id, name, description, initial_prompt, guide_questions,"
                "       tags, estimated_turns, created_at"
                " FROM custom_templates WHERE id = ?",
                (template_id,),
            ).fetchone()
        if row is None:
            return None
        tid, name, desc, ip, gq_json, tags_json, est, created = row
        return {
            "id": tid,
            "name": name,
            "description": desc,
            "initial_prompt": ip,
            "guide_questions": json.loads(gq_json),
            "tags": json.loads(tags_json),
            "estimated_turns": est,
            "created_at": created,
            "builtin": False,
        }

    def create_custom(self, template_data: dict) -> dict:
        """
        Create and persist a custom template.
        Raises ValueError if required fields are missing or DB is not configured.
        """
        missing = _REQUIRED_FIELDS - set(template_data.keys())
        if missing:
            raise ValueError(f"Missing required fields: {sorted(missing)}")
        if not isinstance(template_data.get("guide_questions"), list):
            raise ValueError("guide_questions must be a list")
        if not self._db_path:
            raise RuntimeError("db_path not configured — cannot persist custom templates")

        base_slug = _slugify(template_data["name"])
        template_id = base_slug
        # Ensure uniqueness: append short uuid suffix if slug already exists
        if self.get_template(template_id) is not None:
            template_id = f"{base_slug}_{uuid.uuid4().hex[:6]}"

        tags = template_data.get("tags", [])
        est = int(template_data.get("estimated_turns", 5))
        created_at = datetime.now(timezone.utc).isoformat()

        from storage.db_pool import get_pool
        with get_pool(self._db_path).get() as conn:
            conn.execute(
                "INSERT INTO custom_templates"
                " (id, name, description, initial_prompt, guide_questions, tags, estimated_turns, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    template_id,
                    template_data["name"],
                    template_data["description"],
                    template_data["initial_prompt"],
                    json.dumps(template_data["guide_questions"]),
                    json.dumps(tags),
                    est,
                    created_at,
                ),
            )

        return {
            "id": template_id,
            "name": template_data["name"],
            "description": template_data["description"],
            "initial_prompt": template_data["initial_prompt"],
            "guide_questions": template_data["guide_questions"],
            "tags": tags,
            "estimated_turns": est,
            "created_at": created_at,
            "builtin": False,
        }

    def delete_custom(self, template_id: str) -> bool:
        """
        Delete a custom template by id.
        Returns False if the template is builtin or does not exist.
        """
        if template_id in BUILTIN_TEMPLATES:
            return False
        if not self._db_path:
            return False
        from storage.db_pool import get_pool
        with get_pool(self._db_path).get() as conn:
            cursor = conn.execute(
                "DELETE FROM custom_templates WHERE id = ?", (template_id,)
            )
            return cursor.rowcount > 0

    def start_session(self, template_id: str, session_id: str | None = None) -> dict:
        """
        Return the initial prompt and guide questions for a template session.
        Generates a session_id if not provided.
        Raises KeyError if template not found.
        """
        tpl = self.get_template(template_id)
        if tpl is None:
            raise KeyError(f"Template '{template_id}' not found")
        if not session_id:
            session_id = f"tpl_{template_id}_{uuid.uuid4().hex[:8]}"
        return {
            "template_id": template_id,
            "session_id": session_id,
            "initial_prompt": tpl["initial_prompt"],
            "guide_questions": tpl["guide_questions"],
            "estimated_turns": tpl["estimated_turns"],
        }
