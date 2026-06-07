"""
injection_prioritizer.py — Context Injection Prioritizer
=========================================================
Ranks context blocks by relevance to the current query and returns the
top-N blocks within a character budget.  No DB, pure in-memory computation.

Phase 56 upgrade: build_blocks() converts the legacy dict format into
ContextBlock objects for ContextWindowManager, and prioritize() uses CWM
when available (backwards-compatible fallback to legacy path if CWM absent).
"""

from __future__ import annotations

import threading
import time
from typing import List, Dict, Any

try:
    from cognia.context.context_window_manager import (
        ContextBlock,
        ContextWindowManager,
        get_context_window_manager,
    )
    _HAS_CWM = True
except ImportError:
    _HAS_CWM = False

# Maps InjectionPrioritizer block types to CWM source strings
_TYPE_TO_SOURCE: Dict[str, str] = {
    "user_facts":       "memory",
    "crystallized_kg":  "kg",
    "goals":            "memory",
    "autocritica":      "system",
    "feedback":         "system",
    "long_term_memory": "memory",
    "curiosity":        "notes",
    "adaptive":         "system",
}

# Base priority weights per block type (0-1 scale).
_PRIORITY_WEIGHTS: Dict[str, float] = {
    "user_facts":        0.9,   # personal facts: always high relevance
    "crystallized_kg":   0.8,   # high-confidence facts
    "goals":             0.7,   # user objectives
    "autocritica":       0.6,   # self-improvement signal
    "feedback":          0.6,   # adaptive hint
    "long_term_memory":  0.5,   # recurring topics
    "curiosity":         0.4,   # speculative insights
    "adaptive":          0.3,   # background adjustment
}


class InjectionPrioritizer:
    """Rank and filter context injection blocks before building the system prompt."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._call_count: int = 0
        self._total_blocks_selected: int = 0
        self._total_chars_selected: int = 0

    # ------------------------------------------------------------------
    # Core scoring
    # ------------------------------------------------------------------

    def score_block(self, block_type: str, content: str, query: str) -> float:
        """Return a relevance score in [0.0, 1.0] for a single block.

        Score = base_weight * relevance_boost, clamped to [0.0, 1.0].
        relevance_boost is 1.5 when any word from query (>3 chars) appears
        in content.lower(), otherwise 1.0.
        """
        base = _PRIORITY_WEIGHTS.get(block_type, 0.3)
        content_lower = content.lower()
        boost = 1.0
        for word in query.split():
            if len(word) > 3 and word.lower() in content_lower:
                boost = 1.5
                break
        return min(base * boost, 1.0)

    # ------------------------------------------------------------------
    # Prioritization
    # ------------------------------------------------------------------

    def prioritize(
        self,
        blocks: List[Dict[str, Any]],
        query: str,
        max_blocks: int = 4,
        max_total_chars: int = 800,
    ) -> List[Dict[str, Any]]:
        """Score, sort, and greedily select blocks within budget.

        Parameters
        ----------
        blocks:
            List of {"type": str, "content": str} dicts.
        query:
            Current user message used for relevance boost.
        max_blocks:
            Maximum number of blocks to return.
        max_total_chars:
            Total character budget across all selected blocks.

        Returns
        -------
        Selected blocks in descending score order.
        """
        # Phase 56 fast path: use CWM for richer scoring when available
        if _HAS_CWM:
            context_dict = {
                b.get("type", "unknown"): b.get("content", "")
                for b in blocks
                if b.get("content", "").strip()
            }
            cwm_blocks = self.build_blocks(query, context_dict)
            cwm = get_context_window_manager()
            # Respect max_blocks by temporarily noting it is advisory
            chosen = cwm.select(query, cwm_blocks)[:max_blocks]
            # Convert back to legacy dict format
            selected = [
                {"type": cb.source, "content": cb.text}
                for cb in chosen
            ]
            chars_used = sum(len(b["content"]) for b in selected)
            with self._lock:
                self._call_count += 1
                self._total_blocks_selected += len(selected)
                self._total_chars_selected += chars_used
            return selected

        scored = [
            (self.score_block(b.get("type", ""), b.get("content", ""), query), b)
            for b in blocks
            if b.get("content", "").strip()
        ]
        scored.sort(key=lambda x: x[0], reverse=True)

        selected: List[Dict[str, Any]] = []
        chars_used = 0
        for score, block in scored:
            if len(selected) >= max_blocks:
                break
            content = block.get("content", "")
            if chars_used + len(content) > max_total_chars:
                # Try a truncated version to fill remaining budget
                remaining = max_total_chars - chars_used
                if remaining > 20:
                    truncated = dict(block)
                    truncated["content"] = content[:remaining]
                    selected.append(truncated)
                    chars_used += remaining
                break
            selected.append(block)
            chars_used += len(content)

        with self._lock:
            self._call_count += 1
            self._total_blocks_selected += len(selected)
            self._total_chars_selected += chars_used

        return selected

    # ------------------------------------------------------------------
    # String builder
    # ------------------------------------------------------------------

    def build_context_string(self, selected: List[Dict[str, Any]]) -> str:
        """Join selected blocks' content with newlines."""
        return "\n".join(b.get("content", "") for b in selected if b.get("content", "").strip())

    # ------------------------------------------------------------------
    # Phase 56 — CWM bridge
    # ------------------------------------------------------------------

    def build_blocks(self, query: str, context_dict: Dict[str, str]) -> "List[ContextBlock]":
        """Convert legacy {type: content} dict into ContextBlock list for CWM.

        Parameters
        ----------
        query:
            Current user message (used to compute relevance boost).
        context_dict:
            Mapping of block_type -> content string (same format as
            the dicts passed to prioritize()).

        Returns
        -------
        List of ContextBlock objects ready for ContextWindowManager.select().
        """
        if not _HAS_CWM:
            return []
        blocks: List[ContextBlock] = []
        for block_type, content in context_dict.items():
            if not content or not content.strip():
                continue
            base_relevance = _PRIORITY_WEIGHTS.get(block_type, 0.3)
            # Apply same relevance boost as score_block()
            for word in query.split():
                if len(word) > 3 and word.lower() in content.lower():
                    base_relevance = min(base_relevance * 1.5, 1.0)
                    break
            source = _TYPE_TO_SOURCE.get(block_type, "system")
            blocks.append(
                ContextBlock(
                    text=content,
                    source=source,
                    relevance=base_relevance,
                    timestamp=time.time(),
                )
            )
        return blocks

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        """Return thread-safe call statistics."""
        with self._lock:
            count = self._call_count
            avg_blocks = (
                self._total_blocks_selected / count if count else 0.0
            )
            avg_chars = (
                self._total_chars_selected / count if count else 0.0
            )
        return {
            "call_count":       count,
            "avg_blocks_selected": round(avg_blocks, 2),
            "avg_total_chars":  round(avg_chars, 1),
        }
