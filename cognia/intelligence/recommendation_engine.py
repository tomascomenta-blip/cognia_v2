"""
cognia/intelligence/recommendation_engine.py
=============================================
Personalized Recommendation Engine — generates up to 5 next-best-action
recommendations based on the user's current state across all subsystems.

No LLM calls. Uses get_pool() from storage/db_pool.py — never sqlite3.connect().
No PyTorch. ASCII-only in user-facing strings.
"""

from __future__ import annotations

import time
from typing import Optional

from storage.db_pool import get_pool


# ── DB path resolution ──────────────────────────────────────────────────────
# Module-level variable set by cognia_desktop_api.py at startup.
_DB_PATH: Optional[str] = None


def _get_db() -> str:
    if _DB_PATH:
        return _DB_PATH
    from pathlib import Path
    return str(Path(__file__).parent.parent.parent / "cognia_desktop_chat.db")


class RecommendationEngine:
    """
    Generates personalized next-best-action recommendations from live DB state.
    Each rule is individually guarded so a missing table never raises.
    """

    # ── Rule helpers ────────────────────────────────────────────────────────

    def _rule_sr_cards(self) -> Optional[dict]:
        """SR cards due for review."""
        try:
            db = _get_db()
            now = time.time()
            with get_pool(db).get() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) FROM sr_cards WHERE next_review <= ?",
                    (now,),
                ).fetchone()
            count = int(row[0]) if row and row[0] else 0
            if count > 0:
                return {
                    "type": "learning",
                    "priority": 1,
                    "title": f"Tienes {count} tarjeta(s) para revisar",
                    "reason": "El repaso espaciado es mas efectivo cuando se hace a tiempo",
                    "action": "/revisar",
                }
        except Exception:
            pass
        return None

    def _rule_pending_goals(self) -> Optional[dict]:
        """Oldest pending goal."""
        try:
            db = _get_db()
            with get_pool(db).get() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) FROM user_goals WHERE status='pending'",
                ).fetchone()
                count = int(row[0]) if row and row[0] else 0
                if count > 0:
                    first = conn.execute(
                        "SELECT id, title FROM user_goals WHERE status='pending' ORDER BY id ASC LIMIT 1",
                    ).fetchone()
                    goal_id = first[0] if first else ""
                    goal_title = first[1] if first else "objetivo"
                    return {
                        "type": "goals",
                        "priority": 2,
                        "title": f"Objetivo pendiente: {goal_title}",
                        "reason": "Mantener objetivos activos mejora el enfoque",
                        "action": f"/meta-prog {goal_id} <progreso>",
                    }
        except Exception:
            pass
        return None

    def _rule_action_notes(self) -> Optional[dict]:
        """Smart notes of type 'action'."""
        try:
            db = _get_db()
            with get_pool(db).get() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) FROM smart_notes WHERE note_type='action'",
                ).fetchone()
            count = int(row[0]) if row and row[0] else 0
            if count > 0:
                return {
                    "type": "notes",
                    "priority": 3,
                    "title": f"Tienes {count} nota(s) de tipo accion sin completar",
                    "reason": "Las acciones pendientes requieren seguimiento",
                    "action": "/notas acciones",
                }
        except Exception:
            pass
        return None

    def _rule_curiosity(self) -> Optional[dict]:
        """Unanswered curiosity queue entries."""
        try:
            db = _get_db()
            with get_pool(db).get() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) FROM curiosity_queue WHERE answered=0",
                ).fetchone()
            count = int(row[0]) if row and row[0] else 0
            if count > 0:
                return {
                    "type": "curiosity",
                    "priority": 4,
                    "title": f"Hay {count} pregunta(s) de curiosidad pendiente(s)",
                    "reason": "Explorar preguntas pendientes expande el conocimiento",
                    "action": "/buscar-web <pregunta>",
                }
        except Exception:
            pass
        return None

    def _rule_streak(self) -> Optional[dict]:
        """Streak maintenance — check if user has used Cognia today."""
        try:
            db = _get_db()
            import datetime
            today = datetime.date.today().isoformat()
            with get_pool(db).get() as conn:
                row = conn.execute(
                    "SELECT count FROM feature_usage WHERE date=?",
                    (today,),
                ).fetchone()
            today_count = int(row[0]) if row and row[0] else 0
            if today_count == 0:
                return {
                    "type": "engagement",
                    "priority": 5,
                    "title": "No has usado Cognia hoy",
                    "reason": "Mantener la racha diaria mejora el aprendizaje",
                    "action": "/estado",
                }
        except Exception:
            pass
        return None

    # ── Public API ──────────────────────────────────────────────────────────

    def generate(self, user_id: str = "default") -> list[dict]:
        """
        Generate up to 5 personalized recommendations sorted by priority asc.
        Each recommendation: {type, priority, title, reason, action}.
        """
        candidates = [
            self._rule_sr_cards(),
            self._rule_pending_goals(),
            self._rule_action_notes(),
            self._rule_curiosity(),
            self._rule_streak(),
        ]
        recs = [r for r in candidates if r is not None]
        recs.sort(key=lambda r: r["priority"])
        return recs[:5]

    def get_top(self, user_id: str = "default") -> Optional[dict]:
        """Return the highest priority recommendation or None."""
        recs = self.generate(user_id)
        return recs[0] if recs else None

    def get_summary(self, user_id: str = "default") -> str:
        """Return formatted ASCII summary of current recommendations."""
        recs = self.generate(user_id)
        if not recs:
            return "No hay recomendaciones pendientes."
        lines = ["Proximos pasos recomendados:"]
        for i, rec in enumerate(recs, 1):
            lines.append(f"  {i}. [{rec['type']}] {rec['title']} -> {rec['action']}")
        return "\n".join(lines)
