"""
anchor_tracker.py
=================
Phase 61 — Conversation Anchor Tracker (CAT).

Tracks the user's original intent for a session. When conversation drifts
far from the anchor topic (detected via keyword overlap), injects a reminder
into the prompt so the AI stays focused. In-memory only — resets on restart.
"""

from __future__ import annotations

import re
import string
from dataclasses import dataclass, field
from typing import Dict


_STOPWORDS = frozenset({
    "this", "that", "with", "from", "have", "will", "what", "where",
    "when", "which", "your", "their", "about", "para", "como", "pero",
    "porque", "cuando", "the", "and", "for", "are", "was", "were",
})

_PUNCT_RE = re.compile(r"[" + re.escape(string.punctuation) + r"]")


def _extract_keywords(text: str) -> frozenset:
    """Extract meaningful keywords from text (lowercase, no punctuation, no stopwords, len > 3)."""
    cleaned = _PUNCT_RE.sub(" ", text.lower())
    words = cleaned.split()
    return frozenset(
        w for w in words
        if len(w) > 3 and w not in _STOPWORDS
    )


@dataclass
class ConversationAnchor:
    original_query: str
    keywords: frozenset
    turn_count: int
    session_id: str


class AnchorTracker:
    """
    Tracks the original user intent for a session.
    Detects topic drift and injects reminders.
    In-memory only — resets on restart (no DB needed).
    """

    DRIFT_THRESHOLD = 0.2    # below this keyword overlap -> drift detected
    REMIND_AFTER_TURNS = 5   # only start checking after N turns
    MAX_HINT_LENGTH = 120

    def __init__(self) -> None:
        self._anchors: Dict[str, ConversationAnchor] = {}

    def set_anchor(self, session_id: str, first_query: str) -> None:
        """Record the first message of a session as the anchor."""
        self._anchors[session_id] = ConversationAnchor(
            original_query=first_query,
            keywords=_extract_keywords(first_query),
            turn_count=0,
            session_id=session_id,
        )

    def check_drift(self, session_id: str, current_query: str) -> float:
        """
        Returns overlap score 0.0-1.0. Low score means drifted from anchor.
        Returns 1.0 if no anchor set or fewer than REMIND_AFTER_TURNS turns.
        """
        anchor = self._anchors.get(session_id)
        if anchor is None:
            return 1.0
        if anchor.turn_count < self.REMIND_AFTER_TURNS:
            return 1.0
        current_keywords = _extract_keywords(current_query)
        overlap = len(anchor.keywords & current_keywords) / max(len(anchor.keywords), 1)
        return overlap

    def record_turn(self, session_id: str) -> None:
        """Increment turn counter for session."""
        anchor = self._anchors.get(session_id)
        if anchor is not None:
            anchor.turn_count += 1

    def get_anchor_hint(self, session_id: str, current_query: str) -> str:
        """
        Returns ASCII hint string if drift detected, empty string otherwise.
        """
        anchor = self._anchors.get(session_id)
        if anchor is None:
            return ""
        score = self.check_drift(session_id, current_query)
        if score >= self.DRIFT_THRESHOLD:
            return ""
        snippet = anchor.original_query[:60]
        hint = f"Note: Original topic was '{snippet}'. Stay focused on that if relevant."
        return hint[:self.MAX_HINT_LENGTH]

    def clear_session(self, session_id: str) -> None:
        """Remove anchor when session ends."""
        self._anchors.pop(session_id, None)
