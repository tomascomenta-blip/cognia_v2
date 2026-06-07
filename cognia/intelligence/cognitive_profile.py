"""
cognia/intelligence/cognitive_profile.py
=========================================
Unified Cognitive Profile — aggregates data from 8 subsystems into a single
snapshot for a given user_id. Each subsystem is wrapped in try/except so a
missing or broken subsystem returns a safe fallback rather than raising.

No PyTorch. Uses get_pool() from storage/db_pool.py — never sqlite3.connect().
No new abstractions beyond what is described.
"""

from __future__ import annotations

from typing import Optional

from storage.db_pool import get_pool


# ── DB path resolution ──────────────────────────────────────────────────────
# Mirrors the pattern used by other singletons in cognia_desktop_api.py:
# a module-level _DB_PATH variable that the desktop API sets at startup.
_DB_PATH: Optional[str] = None


def _get_db() -> str:
    if _DB_PATH:
        return _DB_PATH
    # Fallback for tests and direct usage
    from pathlib import Path
    return str(Path(__file__).parent.parent.parent / "cognia_desktop_chat.db")


def _get_kg_db() -> str:
    """KnowledgeGraph uses cognia/config.py DB_PATH (cognia_memory.db)."""
    try:
        from cognia.config import DB_PATH
        return DB_PATH
    except Exception:
        from pathlib import Path
        return str(Path(__file__).parent.parent.parent / "cognia_memory.db")


class CognitiveProfile:
    """
    Aggregates data from multiple subsystems into a unified per-user profile.
    All section builds are individually guarded — subsystem errors never propagate.
    """

    # ── Section builders ────────────────────────────────────────────────────

    def _build_identity(self, user_id: str) -> dict:
        try:
            from cognia.profile.user_profile_builder import UserProfileBuilder
            upb = UserProfileBuilder(db_path=_get_db())
            profile = upb.get_profile(user_id) or upb.build_profile()
            top_terms = [t["term"] for t in profile.get("top_topics", [])[:10]]
            return {
                "dominant_language": profile.get("dominant_language", "unknown"),
                "query_patterns": profile.get("query_patterns", []),
                "top_terms": top_terms,
            }
        except Exception:
            return {"dominant_language": "unknown", "query_patterns": [], "top_terms": []}

    def _build_learning(self) -> dict:
        try:
            from cognia.learning.spaced_repetition import SpacedRepetitionEngine
            sr = SpacedRepetitionEngine(db_path=_get_db())
            stats = sr.get_stats()
            return {
                "total": stats.get("total", 0),
                "due_today": stats.get("due_today", 0),
                "mastered": stats.get("mastered", 0),
            }
        except Exception:
            return {"total": 0, "due_today": 0, "mastered": 0}

    def _build_goals(self, user_id: str) -> dict:
        try:
            db = _get_db()
            with get_pool(db).get() as conn:
                total = conn.execute(
                    "SELECT COUNT(*) FROM user_goals WHERE user_id = ?", (user_id,)
                ).fetchone()[0]
                pending = conn.execute(
                    "SELECT COUNT(*) FROM user_goals WHERE user_id = ? AND status IN ('active', 'pending', 'in_progress')",
                    (user_id,),
                ).fetchone()[0]
                completed = conn.execute(
                    "SELECT COUNT(*) FROM user_goals WHERE user_id = ? AND status = 'completed'",
                    (user_id,),
                ).fetchone()[0]
            return {"total": total, "pending": pending, "completed": completed}
        except Exception:
            return {"total": 0, "pending": 0, "completed": 0}

    def _build_feedback(self) -> dict:
        try:
            from cognia.adaptive.feedback_learner import FeedbackLearner
            fl = FeedbackLearner()
            stats = fl.get_stats()
            return {
                "total": stats.get("total", 0),
                "positive": stats.get("positive", 0),
                "negative": stats.get("negative", 0),
            }
        except Exception:
            return {"total": 0, "positive": 0, "negative": 0}

    def _build_achievements(self, user_id: str) -> dict:
        try:
            from cognia.gamification.achievement_system import AchievementSystem
            ach = AchievementSystem(db_path=_get_db())
            stats = ach.get_stats(user_id)
            return {
                "unlocked": stats.get("unlocked", 0),
                "total": stats.get("total", 0),
                "points": stats.get("points", 0),
            }
        except Exception:
            return {"unlocked": 0, "total": 0, "points": 0}

    def _build_analytics(self, user_id: str) -> dict:
        try:
            from cognia.analytics.usage_analytics import UsageAnalytics
            ua = UsageAnalytics(db_path=_get_db())
            stats = ua.get_stats(user_id)
            return {
                "streak": stats.get("streak", 0),
                "active_days": stats.get("active_days", 0),
                "today_count": stats.get("today_count", 0),
            }
        except Exception:
            return {"streak": 0, "active_days": 0, "today_count": 0}

    def _build_notes(self, user_id: str) -> dict:
        try:
            db = _get_db()
            with get_pool(db).get() as conn:
                total = conn.execute("SELECT COUNT(*) FROM smart_notes").fetchone()[0]
                rows = conn.execute(
                    "SELECT note_type, COUNT(*) FROM smart_notes GROUP BY note_type"
                ).fetchall()
            by_type = {r[0]: r[1] for r in rows}
            return {"total": total, "by_type": by_type}
        except Exception:
            return {"total": 0, "by_type": {}}

    def _build_synthesis_ready(self) -> tuple[bool, int]:
        """Returns (synthesis_ready, kg_facts_count)."""
        try:
            db = _get_kg_db()
            with get_pool(db).get() as conn:
                kg_count = conn.execute(
                    "SELECT COUNT(*) FROM knowledge_graph"
                ).fetchone()[0]
            return kg_count
        except Exception:
            return 0

    # ── Public API ──────────────────────────────────────────────────────────

    def build(self, user_id: str = "default") -> dict:
        """
        Aggregate all subsystems into a single profile dict.
        Each section is independently guarded; unavailable subsystems
        return a safe fallback instead of propagating exceptions.
        """
        identity = self._build_identity(user_id)
        learning = self._build_learning()
        goals = self._build_goals(user_id)
        feedback = self._build_feedback()
        achievements = self._build_achievements(user_id)
        analytics = self._build_analytics(user_id)
        notes = self._build_notes(user_id)
        kg_facts = self._build_synthesis_ready()

        synthesis_ready = (notes.get("total", 0) > 0) or (kg_facts > 0)

        # overall_score = weighted sum, clamped 0-1000
        score = (
            achievements.get("points", 0) * 0.3
            + goals.get("completed", 0) * 10
            + learning.get("mastered", 0) * 5
            + feedback.get("positive", 0) * 2
            + analytics.get("streak", 0) * 3
        )
        overall_score = max(0, min(1000, score))

        return {
            "user_id": user_id,
            "identity": identity,
            "learning": learning,
            "goals": goals,
            "feedback": feedback,
            "achievements": achievements,
            "analytics": analytics,
            "notes": notes,
            "kg_facts": kg_facts,
            "synthesis_ready": synthesis_ready,
            "overall_score": overall_score,
        }

    def get_summary(self, user_id: str = "default") -> str:
        """Build and return a human-readable ASCII summary of the cognitive profile."""
        p = self.build(user_id)

        identity = p["identity"]
        learning = p["learning"]
        goals = p["goals"]
        feedback = p["feedback"]
        achievements = p["achievements"]
        analytics = p["analytics"]
        notes = p["notes"]

        lines = [
            f"=== Cognitive Profile: {user_id} ===",
            f"Score: {p['overall_score']:.0f}/1000",
            "",
            f"Identity",
            f"  Language  : {identity.get('dominant_language', 'unknown')}",
            f"  Patterns  : {', '.join(identity.get('query_patterns', [])) or 'none'}",
            f"  Top terms : {', '.join(identity.get('top_terms', [])[:5]) or 'none'}",
            "",
            f"Learning",
            f"  Cards     : {learning.get('total', 0)} total, "
            f"{learning.get('mastered', 0)} mastered, "
            f"{learning.get('due_today', 0)} due today",
            "",
            f"Goals",
            f"  Total     : {goals.get('total', 0)}, "
            f"Pending: {goals.get('pending', 0)}, "
            f"Completed: {goals.get('completed', 0)}",
            "",
            f"Feedback",
            f"  Total     : {feedback.get('total', 0)}, "
            f"+{feedback.get('positive', 0)} / -{feedback.get('negative', 0)}",
            "",
            f"Achievements",
            f"  Unlocked  : {achievements.get('unlocked', 0)}/{achievements.get('total', 0)} "
            f"({achievements.get('points', 0)} pts)",
            "",
            f"Activity",
            f"  Streak    : {analytics.get('streak', 0)} days",
            f"  Active days: {analytics.get('active_days', 0)}, "
            f"Today: {analytics.get('today_count', 0)} events",
            "",
            f"Notes",
            f"  Total     : {notes.get('total', 0)}",
        ]

        by_type = notes.get("by_type", {})
        if by_type:
            for nt, cnt in sorted(by_type.items()):
                lines.append(f"    {nt}: {cnt}")

        lines += [
            "",
            f"KG facts  : {p['kg_facts']}",
            f"Synthesis : {'ready' if p['synthesis_ready'] else 'not enough data'}",
        ]

        return "\n".join(lines)
