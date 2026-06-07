"""
cognia/persona/persona_manager.py
===================================
Gestiona el estilo de comunicacion por usuario.
Persiste en user_personas (cognia_desktop_chat.db por defecto).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

PERSONAS: dict[str, str] = {
    "formal":    "Responde de forma formal y profesional.",
    "tecnico":   "Usa terminologia tecnica precisa. Incluye detalles de implementacion cuando sea relevante.",
    "casual":    "Responde de forma conversacional y amigable.",
    "conciso":   "Se breve y directo. Maximo 3 oraciones por punto.",
    "detallado": "Proporciona respuestas exhaustivas con ejemplos y contexto completo.",
    "default":   "",
}

_DEFAULT_DB = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "cognia_desktop_chat.db",
)


class PersonaManager:
    """
    Gestiona el estilo de comunicacion por usuario.
    Table: user_personas (user_id TEXT PRIMARY KEY, persona TEXT, custom_instruction TEXT, updated_at TEXT)
    """

    def __init__(self, db_path: str = None):
        self._db = db_path or os.environ.get("COGNIA_CHAT_DB", _DEFAULT_DB)
        self._init_table()

    def _init_table(self) -> None:
        from storage.db_pool import get_pool
        with get_pool(self._db).get() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS user_personas ("
                "  user_id TEXT PRIMARY KEY,"
                "  persona TEXT NOT NULL DEFAULT 'default',"
                "  custom_instruction TEXT NOT NULL DEFAULT '',"
                "  updated_at TEXT NOT NULL"
                ")"
            )

    def set_persona(self, user_id: str, persona: str, custom_instruction: str = "") -> bool:
        """Upsert persona for user. Returns True if OK, False if invalid."""
        persona = (persona or "").strip()
        custom_instruction = (custom_instruction or "").strip()

        # Validate: persona must be in PERSONAS keys OR custom_instruction must be non-empty
        if persona not in PERSONAS and not custom_instruction:
            return False

        # If persona not in PERSONAS but custom_instruction provided, use "default" as base
        if persona not in PERSONAS:
            persona = "default"

        from storage.db_pool import get_pool
        now = datetime.now(timezone.utc).isoformat()
        with get_pool(self._db).get() as conn:
            conn.execute(
                "INSERT INTO user_personas (user_id, persona, custom_instruction, updated_at) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET "
                "  persona=excluded.persona, "
                "  custom_instruction=excluded.custom_instruction, "
                "  updated_at=excluded.updated_at",
                (user_id, persona, custom_instruction, now),
            )
        return True

    def get_persona_instruction(self, user_id: str) -> str:
        """Return the persona instruction string for the user, or '' if none configured."""
        row = self._fetch_row(user_id)
        if row is None:
            return ""
        persona, custom_instruction = row
        if custom_instruction:
            return custom_instruction
        if persona and persona in PERSONAS:
            return PERSONAS[persona]
        return ""

    def get_persona(self, user_id: str) -> dict:
        """Return {"persona": str, "custom_instruction": str}."""
        row = self._fetch_row(user_id)
        if row is None:
            return {"persona": "default", "custom_instruction": ""}
        persona, custom_instruction = row
        return {"persona": persona, "custom_instruction": custom_instruction}

    def list_personas(self) -> list[str]:
        """Return persona names excluding 'default'."""
        return [k for k in PERSONAS if k != "default"]

    def reset_persona(self, user_id: str) -> bool:
        """Reset user to default persona (no instruction)."""
        return self.set_persona(user_id, "default", "")

    # ── Internal ──────────────────────────────────────────────────────

    def _fetch_row(self, user_id: str):
        """Return (persona, custom_instruction) or None if not found."""
        from storage.db_pool import get_pool
        with get_pool(self._db).get() as conn:
            row = conn.execute(
                "SELECT persona, custom_instruction FROM user_personas WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return row
