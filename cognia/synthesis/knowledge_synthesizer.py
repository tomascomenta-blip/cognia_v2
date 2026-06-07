"""
cognia/synthesis/knowledge_synthesizer.py
==========================================
KnowledgeSynthesizer — aggregates notes, KG facts, and conversation excerpts
about a topic into a structured synthesis. Pure heuristic, no LLM calls.
"""
from __future__ import annotations

from typing import Optional

from storage.db_pool import get_pool

# DB paths injected at startup by cognia_desktop_api.py
_CHAT_DB: Optional[str] = None  # smart_notes + chat_history
_KG_DB: Optional[str] = None    # knowledge_graph (cognia_memory.db)


def _default_chat_db() -> str:
    return _CHAT_DB or "cognia_desktop_chat.db"


def _default_kg_db() -> str:
    if _KG_DB:
        return _KG_DB
    import os
    from pathlib import Path
    db_dir = Path(os.environ.get("COGNIA_DB_PATH", Path.home() / ".cognia"))
    return str(db_dir / "cognia_memory.db")


def _shares_more_than_n_words(a: str, b: str, n: int = 3) -> bool:
    """Return True if strings a and b share more than n words (case-insensitive)."""
    words_a = set(a.lower().split())
    words_b = set(b.lower().split())
    return len(words_a & words_b) > n


class KnowledgeSynthesizer:
    """
    Aggregates notes, KG facts, and conversation excerpts about a topic
    into a structured synthesis dict. No LLM calls.
    """

    def _extract_relevant_notes(self, topic: str, limit: int = 5) -> list[str]:
        """Query smart_notes for content matching topic. Returns content strings."""
        try:
            with get_pool(_default_chat_db()).get() as conn:
                rows = conn.execute(
                    "SELECT content FROM smart_notes WHERE content LIKE ? LIMIT ?",
                    (f"%{topic}%", limit),
                ).fetchall()
            return [row[0] for row in rows]
        except Exception:
            return []

    def _extract_kg_facts(self, topic: str, limit: int = 5) -> list[str]:
        """Query knowledge_graph for subject or object matching topic.
        Returns formatted 'subject predicate object' strings."""
        try:
            with get_pool(_default_kg_db()).get() as conn:
                rows = conn.execute(
                    "SELECT subject, predicate, object FROM knowledge_graph "
                    "WHERE subject LIKE ? OR object LIKE ? LIMIT ?",
                    (f"%{topic}%", f"%{topic}%", limit),
                ).fetchall()
            return [f"{row[0]} {row[1]} {row[2]}" for row in rows]
        except Exception:
            return []

    def _extract_chat_context(self, topic: str, limit: int = 5) -> list[str]:
        """Query chat_history for assistant messages matching topic.
        Returns first 200 chars of each."""
        try:
            with get_pool(_default_chat_db()).get() as conn:
                rows = conn.execute(
                    "SELECT content FROM chat_history "
                    "WHERE content LIKE ? AND role = 'assistant' LIMIT ?",
                    (f"%{topic}%", limit),
                ).fetchall()
            return [row[0][:200] for row in rows]
        except Exception:
            return []

    def synthesize(self, topic: str) -> dict:
        """
        Aggregate notes, KG facts, and chat context for topic.
        Deduplicates by skipping entries that share >3 words with an existing entry.
        Returns a structured dict with synthesis string and source metadata.
        """
        raw_notes = self._extract_relevant_notes(topic)
        raw_kg = self._extract_kg_facts(topic)
        raw_chat = self._extract_chat_context(topic)

        # Deduplicate across all sources combined
        seen: list[str] = []

        def _dedup(items: list[str]) -> list[str]:
            result = []
            for item in items:
                if not any(_shares_more_than_n_words(item, s) for s in seen):
                    seen.append(item)
                    result.append(item)
            return result

        notes = _dedup(raw_notes)
        kg_facts = _dedup(raw_kg)
        chat_refs = _dedup(raw_chat)

        sources = []
        if kg_facts:
            sources.append("kg")
        if notes:
            sources.append("notes")
        if chat_refs:
            sources.append("chat")

        # Build synthesis string
        parts = [f"Sintesis sobre '{topic}':"]

        if kg_facts:
            parts.append(f"\nHechos conocidos ({len(kg_facts)}):")
            for f in kg_facts:
                parts.append(f"  - {f}")

        if notes:
            parts.append(f"\nNotas relevantes ({len(notes)}):")
            for n in notes:
                parts.append(f"  - {n[:100]}")

        if chat_refs:
            parts.append(f"\nReferencias en conversaciones ({len(chat_refs)}):")
            for c in chat_refs:
                parts.append(f"  - {c[:100]}")

        synthesis = "\n".join(parts)

        return {
            "topic": topic,
            "notes_count": len(notes),
            "kg_facts_count": len(kg_facts),
            "chat_refs_count": len(chat_refs),
            "synthesis": synthesis,
            "sources": sources,
        }
