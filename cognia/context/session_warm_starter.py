"""
cognia/context/session_warm_starter.py
=======================================
Phase 62 -- Session Warm Starter (SWS)

Compiles a user briefing from KG facts, knowledge gaps, and long-term memory
and prepends it to the system prompt on the first turn of each session.
Eliminates cold-start: AI starts every session knowing who the user is.

No LLM calls. No external deps. Max output 400 chars.
"""

from __future__ import annotations

from typing import Optional, Set


class SessionWarmStarter:
    """
    Compiles user context briefing from KG + gaps + memory summary.
    Called once per session on first turn. No LLM calls.
    """

    MAX_OUTPUT_CHARS = 400

    def __init__(self, kg, db_path: str, consolidator=None):
        """
        kg          -- KnowledgeGraph instance (must have get_facts(concept)->list)
        db_path     -- path to the chat/knowledge DB for querying knowledge_gaps
        consolidator-- optional LongTermConsolidator instance (has get_summary(user_id)->str)
        """
        self._kg = kg
        self._db_path = db_path
        self._consolidator = consolidator
        self._briefed_sessions: Set[str] = set()

    # ── Session tracking ──────────────────────────────────────────────

    def is_first_turn(self, session_id: str) -> bool:
        """True if this session has not yet received a briefing."""
        return session_id not in self._briefed_sessions

    def mark_briefed(self, session_id: str) -> None:
        """Record that session received its briefing."""
        self._briefed_sessions.add(session_id)

    # ── Briefing construction ─────────────────────────────────────────

    def _get_user_facts_section(self) -> tuple:
        """
        Returns (section_str, fact_count).
        section_str is empty string if < 3 facts meet the weight threshold.
        """
        try:
            raw = self._kg.get_facts("user")
        except Exception:
            return "", 0

        # Filter by weight >= 0.5, sort descending, take top 3
        filtered = [r for r in raw if r.get("weight", 0) >= 0.5]
        filtered.sort(key=lambda r: r.get("weight", 0), reverse=True)
        top = filtered[:3]

        if not top:
            return "", 0

        parts = []
        for row in top:
            pred = row.get("predicate", "")
            obj = row.get("object", "")
            if not obj:
                continue
            # Map common predicates to readable phrases
            if pred in ("is_a", "instance_of"):
                parts.append(f"User: is a {obj}")
            elif pred in ("located_in", "part_of"):
                parts.append(f"User: works at {obj}")
            elif pred in ("has_property", "capable_of", "used_for"):
                parts.append(f"User: prefers {obj}")
            else:
                parts.append(f"User: {pred} {obj}")

        if not parts:
            return "", 0

        return "; ".join(parts), len(top)

    def _get_gaps_section(self) -> str:
        """Returns gap section string, or empty string if no gaps or table missing."""
        try:
            from storage.db_pool import get_pool
            with get_pool(self._db_path).get() as conn:
                rows = conn.execute(
                    "SELECT topic FROM knowledge_gaps "
                    "WHERE resolved = 0 "
                    "ORDER BY timestamp DESC "
                    "LIMIT 2"
                ).fetchall()
            if not rows:
                return ""
            topics = [r[0] for r in rows if r[0]]
            if not topics:
                return ""
            return "Recent unknowns: " + ", ".join(topics)
        except Exception:
            # Table may not exist — skip silently
            return ""

    def _get_memory_section(self) -> str:
        """Returns memory summary section, or empty string on any failure."""
        if self._consolidator is None:
            return ""
        try:
            summary = self._consolidator.get_summary("default")
            if not summary:
                return ""
            first_80 = summary[:80]
            return "Memory: " + first_80
        except Exception:
            return ""

    def build_briefing(self, session_id: str) -> str:
        """
        Returns ASCII briefing string for the system prompt.
        Returns empty string if fewer than 3 user facts with weight >= 0.5.
        Hard-truncated to MAX_OUTPUT_CHARS.
        """
        facts_section, fact_count = self._get_user_facts_section()

        # Require at least 3 qualifying facts to be useful
        if fact_count < 3:
            return ""

        sections = [facts_section]

        gaps_section = self._get_gaps_section()
        if gaps_section:
            sections.append(gaps_section)

        memory_section = self._get_memory_section()
        if memory_section:
            sections.append(memory_section)

        body = " | ".join(sections)
        result = "Context: " + body

        # Hard truncate
        if len(result) > self.MAX_OUTPUT_CHARS:
            result = result[:self.MAX_OUTPUT_CHARS]

        # Ensure ASCII only — replace any non-ASCII char with '?'
        result = result.encode("ascii", errors="replace").decode("ascii")

        return result
