"""
cognia/quality/contradiction_alert.py
=======================================
Phase 58 — Real-Time Contradiction Alert (RCA)

Detects when a user message contradicts facts stored in the Knowledge Graph.
Complements consistency_checker.py (which checks KG vs KG).
This module checks USER MESSAGES vs KG.

No LLM calls. No external deps. Pure Python + KG lookup.
"""

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cognia.knowledge.graph import KnowledgeGraph

# Patterns: (regex, predicate, negated)
# Each tuple: compiled regex, KG predicate to check, is_negation
_CLAIM_PATTERNS = [
    # "I am / I'm X"
    (re.compile(r"\bI\s+(?:am|'m)\s+(?:a\s+|an\s+)?([A-Za-z][A-Za-z0-9 _-]{1,40})", re.IGNORECASE), "is_a", False),
    # "I use / I work with X"
    (re.compile(r"\bI\s+(?:use|work\s+with|work\s+in)\s+([A-Za-z][A-Za-z0-9 _+-]{1,40})", re.IGNORECASE), "uses", False),
    # "I prefer / I like X"
    (re.compile(r"\bI\s+(?:prefer|like|love|enjoy)\s+([A-Za-z][A-Za-z0-9 _+-]{1,40})", re.IGNORECASE), "prefers", False),
    # "I always use / I always code in X"
    (re.compile(r"\bI\s+always\s+(?:use|code\s+in|work\s+with)\s+([A-Za-z][A-Za-z0-9 _+-]{1,40})", re.IGNORECASE), "prefers", False),
    # Negations: "I don't use / I never use X" / "I don't like X"
    (re.compile(r"\bI\s+(?:don't|do\s+not|never|don't)\s+(?:use|like|prefer|work\s+with|work\s+in)\s+([A-Za-z][A-Za-z0-9 _+-]{1,40})", re.IGNORECASE), "prefers", True),
    # "X is Y" (non-pronoun subject, len > 2)
    (re.compile(r"\b([A-Za-z][A-Za-z0-9 _-]{2,30})\s+is\s+(?:a\s+|an\s+)?([A-Za-z][A-Za-z0-9 _-]{1,40})", re.IGNORECASE), "is_a", False),
]

# Pronouns and generic words that should never be used as subjects/objects
_SKIP_TOKENS = frozenset({
    "i", "he", "she", "it", "we", "they", "you", "me", "him", "her", "us",
    "this", "that", "there", "here", "what", "which", "who", "how", "when",
    "where", "why", "very", "also", "just", "only", "now", "then", "so",
    "and", "but", "or", "the", "a", "an", "is", "are", "was", "were",
    "be", "been", "do", "does", "did", "have", "has", "had", "will",
    "would", "could", "should", "may", "might", "happy", "sad", "good",
    "bad", "great", "fine", "ok", "okay", "yes", "no",
})

# Predicate aliases: claim predicate -> KG predicates to check
_PRED_ALIASES = {
    "is_a":    ("is_a", "instance_of"),
    "uses":    ("used_for", "related_to", "has_property"),
    "prefers": ("related_to", "has_property", "used_for"),
}


def _clean(text: str) -> str:
    """Lowercase, strip trailing punctuation and whitespace."""
    return text.strip().rstrip(".,;:!?").lower().strip()


class ContradictionAlert:
    """
    Detects when user message contradicts KG facts.
    No LLM calls — pure regex + KG lookup.
    """

    CONFIDENCE_THRESHOLD = 0.6  # only alert if KG fact weight >= this
    MAX_ALERTS = 2

    def __init__(self, kg: "KnowledgeGraph"):
        self._kg = kg

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parse_claims(self, message: str) -> list:
        """
        Returns list of (subject, predicate, object, negated) tuples
        extracted from message via regex patterns.
        """
        claims = []
        for pattern, pred, negated in _CLAIM_PATTERNS:
            for m in pattern.finditer(message):
                if pred == "is_a" and m.lastindex == 2:
                    # "X is Y" pattern — two capture groups
                    subject = _clean(m.group(1))
                    obj = _clean(m.group(2))
                    # Skip pronoun subjects
                    if subject in _SKIP_TOKENS or len(subject) <= 2:
                        continue
                elif pred == "is_a" and m.lastindex == 1:
                    # "I am X" pattern
                    subject = "user"
                    obj = _clean(m.group(1))
                else:
                    subject = "user"
                    obj = _clean(m.group(1))

                if obj in _SKIP_TOKENS or len(obj) <= 1:
                    continue
                # Avoid duplicate claims
                entry = (subject, pred, obj, negated)
                if entry not in claims:
                    claims.append(entry)

        return claims

    def _check_claim(self, subject: str, predicate: str, obj: str, negated: bool) -> str:
        """
        Check one claim against KG. Returns contradiction string or "".
        """
        kg_facts = self._kg.get_facts(subject)
        kg_preds = _PRED_ALIASES.get(predicate, (predicate,))

        for fact in kg_facts:
            if fact["weight"] < self.CONFIDENCE_THRESHOLD:
                continue
            # Only check facts where subject is the subject (not object)
            if fact["subject"] != subject:
                continue
            if fact["predicate"] not in kg_preds:
                continue

            kg_obj = fact["object"].strip().lower()

            if negated:
                # User says "I don't use X" — check if KG has (user, pred, X)
                if kg_obj == obj:
                    return (
                        f"Note: Previously recorded that {subject} {fact['predicate']} "
                        f"{kg_obj}, but current message suggests the opposite."
                    )
            else:
                # User claims (subject, pred, obj) — check if KG has (subject, pred, different_obj)
                if kg_obj != obj:
                    return (
                        f"Note: Previously recorded that {subject} {fact['predicate']} "
                        f"{kg_obj}, but current message suggests {obj}."
                    )

        return ""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check(self, user_message: str) -> list:
        """
        Returns list of ASCII contradiction strings (max 2).
        Empty list if no contradictions detected.
        """
        if not user_message or not user_message.strip():
            return []

        claims = self._parse_claims(user_message)
        alerts = []

        for subject, predicate, obj, negated in claims:
            if len(alerts) >= self.MAX_ALERTS:
                break
            alert = self._check_claim(subject, predicate, obj, negated)
            if alert:
                # Truncate to 120 chars, ASCII safe
                alert = alert[:120]
                alert = alert.encode("ascii", errors="replace").decode("ascii")
                if alert not in alerts:
                    alerts.append(alert)

        return alerts

    def get_alert_injection(self, user_message: str) -> str:
        """
        Returns formatted string for system prompt injection.
        Empty string if no contradictions.
        """
        alerts = self.check(user_message)
        if not alerts:
            return ""
        lines = "\n".join(f"- {a}" for a in alerts)
        return f"Contradiction check:\n{lines}"
