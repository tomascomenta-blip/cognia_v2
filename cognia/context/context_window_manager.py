"""
context_window_manager.py — Smart Context Window Manager (Phase 56)
====================================================================
Scores and selects context blocks that fit within a token budget.
Replaces naive concatenation with composite scoring:
  composite = relevance * recency_factor * source_weight

recency_factor = 1.0 / (1.0 + age_hours * 0.1)
  0h -> 1.0, 10h -> 0.5, 100h -> 0.09

source_weight: kg=1.0, memory=0.9, notes=0.8, web=0.7, system=0.5
"""

from __future__ import annotations

import time
import threading
from dataclasses import dataclass, field
from typing import List, Dict


_SOURCE_WEIGHTS: Dict[str, float] = {
    "kg":      1.0,
    "memory":  0.9,
    "notes":   0.8,
    "web":     0.7,
    "system":  0.5,
}

_DEFAULT_SOURCE_WEIGHT = 0.5


def _estimate_tokens(text: str) -> int:
    """Approximate token count: word count * 1.3."""
    return int(len(text.split()) * 1.3)


@dataclass
class ContextBlock:
    text: str
    source: str           # "memory", "kg", "notes", "web", "system"
    relevance: float      # 0.0-1.0
    timestamp: float = field(default_factory=time.time)
    tokens: int = 0

    def __post_init__(self) -> None:
        if self.tokens == 0:
            self.tokens = _estimate_tokens(self.text)
        # Clamp relevance
        self.relevance = max(0.0, min(1.0, self.relevance))


class ContextWindowManager:
    """Select and format context blocks within a fixed token budget."""

    MAX_TOKENS = 800  # hard budget for injected context

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._select_calls: int = 0
        self._blocks_selected: int = 0

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _recency_factor(self, timestamp: float) -> float:
        """1.0 for fresh blocks, decays as age_hours grows."""
        age_hours = (time.time() - timestamp) / 3600.0
        return 1.0 / (1.0 + age_hours * 0.1)

    def score_block(self, query: str, block: ContextBlock) -> float:
        """Composite score = relevance * recency_factor * source_weight."""
        recency = self._recency_factor(block.timestamp)
        weight = _SOURCE_WEIGHTS.get(block.source, _DEFAULT_SOURCE_WEIGHT)
        return block.relevance * recency * weight

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    def select(self, query: str, blocks: List[ContextBlock]) -> List[ContextBlock]:
        """Return best subset within MAX_TOKENS budget.

        Algorithm:
        1. Score every block.
        2. Sort descending by composite score.
        3. Deduplicate by first-100-chars fingerprint.
        4. Greedy fill until token budget exhausted.
        """
        if not blocks:
            return []

        scored = sorted(
            [(self.score_block(query, b), b) for b in blocks if b.text.strip()],
            key=lambda x: x[0],
            reverse=True,
        )

        seen_fingerprints: set = set()
        selected: List[ContextBlock] = []
        tokens_used = 0

        for _score, block in scored:
            fp = block.text[:100]
            if fp in seen_fingerprints:
                continue
            if tokens_used + block.tokens > self.MAX_TOKENS:
                # Try a truncated copy to fill remaining budget
                remaining_tokens = self.MAX_TOKENS - tokens_used
                if remaining_tokens > 5:
                    # Convert back from tokens to approximate chars
                    approx_words = int(remaining_tokens / 1.3)
                    words = block.text.split()[:approx_words]
                    if words:
                        truncated_text = " ".join(words)
                        truncated = ContextBlock(
                            text=truncated_text,
                            source=block.source,
                            relevance=block.relevance,
                            timestamp=block.timestamp,
                        )
                        seen_fingerprints.add(fp)
                        selected.append(truncated)
                        tokens_used += truncated.tokens
                break
            seen_fingerprints.add(fp)
            selected.append(block)
            tokens_used += block.tokens

        with self._lock:
            self._select_calls += 1
            self._blocks_selected += len(selected)

        return selected

    # ------------------------------------------------------------------
    # Formatting
    # ------------------------------------------------------------------

    def format_context(self, blocks: List[ContextBlock]) -> str:
        """Format selected blocks grouped by source with [SOURCE] prefix.

        Each block: [SOURCE] text
        Groups separated by newline.
        Hard truncated at MAX_TOKENS * 5 chars.
        """
        if not blocks:
            return ""

        groups: Dict[str, List[str]] = {}
        for block in blocks:
            src = block.source.upper()
            groups.setdefault(src, []).append(block.text.strip())

        parts: List[str] = []
        for src, texts in groups.items():
            for text in texts:
                parts.append(f"[{src}] {text}")

        result = "\n".join(parts)
        char_limit = self.MAX_TOKENS * 5
        if len(result) > char_limit:
            result = result[:char_limit]
        return result

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def get_stats(self) -> Dict[str, object]:
        with self._lock:
            calls = self._select_calls
            avg = self._blocks_selected / calls if calls else 0.0
        return {
            "select_calls": calls,
            "avg_blocks_selected": round(avg, 2),
        }


# Module-level singleton
_cwm: ContextWindowManager | None = None
_cwm_lock = threading.Lock()


def get_context_window_manager() -> ContextWindowManager:
    global _cwm
    if _cwm is None:
        with _cwm_lock:
            if _cwm is None:
                _cwm = ContextWindowManager()
    return _cwm
