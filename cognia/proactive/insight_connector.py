"""
cognia/proactive/insight_connector.py
======================================
Phase 57 — Proactive Insight Connector (PIC).
Finds non-obvious connections between the current query and facts stored
in the Knowledge Graph. Pure heuristic graph traversal, no LLM calls.
"""

from __future__ import annotations

_STOPWORDS = frozenset({
    "this", "that", "with", "from", "have", "will", "what", "where",
    "when", "which", "your", "their", "about", "para", "como", "pero",
    "porque", "cuando", "also", "just", "been", "than", "then", "they",
    "them", "were", "there", "here", "more", "some", "into", "over",
    "after", "before",
})


def _ascii_safe(text: str) -> str:
    """Replace non-ASCII characters with closest ASCII equivalent or drop them."""
    return text.encode("ascii", errors="ignore").decode("ascii")


class InsightConnector:
    """
    Finds connections between current query and KG knowledge.
    No LLM calls. Pure heuristic graph traversal.
    """

    MAX_INSIGHTS = 2
    MIN_CONNECTION_SCORE = 0.3

    def __init__(self, kg) -> None:
        # kg: KnowledgeGraph instance — typed loosely to avoid circular imports
        self._kg = kg

    # ── public API ────────────────────────────────────────────────────────────

    def find_insights(self, query: str) -> list:
        """
        Returns list of ASCII insight strings (max MAX_INSIGHTS).
        Empty list if no interesting connections found.
        """
        keywords = self._extract_keywords(query)
        if not keywords:
            return []

        scored: list = []  # list of (score, insight_text)
        seen_texts: set = set()

        # Always also probe the "user" subject to surface user-specific facts
        probe_terms = list(keywords) + ["user"]

        for term in probe_terms:
            try:
                facts = self._kg.get_facts(term)
            except Exception:
                facts = []

            for fact in facts:
                subj = str(fact.get("subject", "")).strip()
                pred = str(fact.get("predicate", "")).strip()
                obj  = str(fact.get("object", "")).strip()
                weight = float(fact.get("weight", 0.0))

                # Score connection
                any_kw_in_triple = any(
                    kw in subj or kw in obj for kw in keywords
                )
                relevance = 1.0 if any_kw_in_triple else 0.5
                connection_score = weight * relevance

                if connection_score < self.MIN_CONNECTION_SCORE:
                    continue

                # Format insight text
                if subj == "user":
                    text = f"Based on your background in {obj}, note that {obj} is related to {pred}."
                else:
                    text = f"Related: {subj} {pred} {obj}"

                # Truncate and make ASCII-safe
                text = _ascii_safe(text)[:120]

                if text in seen_texts:
                    continue
                seen_texts.add(text)

                scored.append((connection_score, text))

        # Sort descending by score, return top MAX_INSIGHTS
        scored.sort(key=lambda x: x[0], reverse=True)
        return [text for _score, text in scored[: self.MAX_INSIGHTS]]

    def get_prompt_injection(self, query: str) -> str:
        """
        Returns formatted string for system prompt injection.
        Empty string if no insights found.
        """
        insights = self.find_insights(query)
        if not insights:
            return ""
        lines = "\n".join(f"- {i}" for i in insights)
        return f"Relevant context:\n{lines}"

    # ── private helpers ───────────────────────────────────────────────────────

    def _extract_keywords(self, query: str) -> list:
        """Return words > 3 chars, not stopwords, lowercased."""
        words = query.lower().split()
        return [
            w.strip(".,;:!?\"'()[]{}") for w in words
            if len(w.strip(".,;:!?\"'()[]{}")) > 3
            and w.strip(".,;:!?\"'()[]{}") not in _STOPWORDS
        ]
