"""
cognia/reasoning/factual_validator.py
======================================
Real-Time Factual Validation (RFV) -- extracts claims from generated responses
and cross-checks against the local Knowledge Graph.

Pipeline:
1. Extract (subject, predicate, object) claims from response text
   using independent regex patterns (not coupled to graph.py).
2. For each claim, query KG for facts about the subject with same predicate.
3. Check if any stored fact contradicts the claim.
   Contradiction = same subject + same predicate + DIFFERENT object
   with edit distance / max_len > 0.4 (not a typo variation).
4. Return ValidationResult with list of contradictions.

This module never modifies the response -- it returns findings only.
The caller decides whether to append a correction note.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, List, Tuple

if TYPE_CHECKING:
    from cognia.knowledge.graph import KnowledgeGraph

# ---------------------------------------------------------------------------
# Extraction patterns: (regex, predicate_label)
# Each regex must have group 1 = subject, group 2 = object.
# Patterns are independent of graph.py to avoid coupling.
# ---------------------------------------------------------------------------
_RFV_PATTERNS: List[Tuple[re.Pattern, str]] = [
    # "X is a Y" / "X es un/una Y"
    (re.compile(
        r'\b(.{3,40}?)\s+(?:is\s+an?|es\s+un[ao]?)\s+(.{3,50}?)(?:[.,;!?\n]|$)',
        re.IGNORECASE,
    ), "is_a"),
    # "X is Y" (property/descriptor, English)
    (re.compile(
        r'\b(.{3,40}?)\s+is\s+([a-z][a-z ]{2,40}?)(?:[.,;!?\n]|$)',
        re.IGNORECASE,
    ), "has_property"),
    # "X es Y" (property/descriptor, Spanish)
    (re.compile(
        r'\b(.{3,40}?)\s+es\s+([a-z\xe1\xe9\xed\xf3\xfa\xf1][a-z\xe1\xe9\xed\xf3\xfa\xf1 ]{2,40}?)(?:[.,;!?\n]|$)',
        re.IGNORECASE,
    ), "has_property"),
    # "X was created by Y" / "X fue creado por Y"
    (re.compile(
        r'\b(.{3,40}?)\s+(?:was\s+created\s+by|fue\s+creado\s+por)\s+(.{3,50}?)(?:[.,;!?\n]|$)',
        re.IGNORECASE,
    ), "related_to"),
    # "X belongs to Y" / "X pertenece a Y"
    (re.compile(
        r'\b(.{3,40}?)\s+(?:belongs\s+to|pertenece\s+a)\s+(.{3,50}?)(?:[.,;!?\n]|$)',
        re.IGNORECASE,
    ), "part_of"),
]

# Map RFV predicate labels to KG canonical predicates
_RFV_PRED_MAP = {
    "is_a":         "is_a",
    "has_property": "has_property",
    "related_to":   "related_to",
    "part_of":      "part_of",
}

# Articles/stopwords to strip when normalizing
_STRIP_ARTICLES = re.compile(
    r'^\s*(?:el|la|los|las|un|una|unos|unas|the|a|an)\s+',
    re.IGNORECASE,
)

_STOPWORDS = frozenset({
    "que", "qué", "es", "son", "un", "una", "el", "la", "los", "las",
    "de", "del", "en", "y", "o", "a", "al", "lo", "se", "su", "sus",
    "con", "por", "para", "pero", "como", "más", "muy", "también",
    "the", "is", "are", "was", "were", "has", "have", "and", "or",
    "but", "in", "on", "at", "to", "of", "for", "with", "by", "not",
})


@dataclass
class ValidationResult:
    has_contradictions: bool
    contradictions: list  # each: {claim: (s,p,o), stored_fact: (s,p,o,w), conflict_type: str}
    claims_checked: int


class FactualValidator:
    """Cross-check generated response text against the Knowledge Graph."""

    def __init__(self, kg: "KnowledgeGraph") -> None:
        self.kg = kg

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate(self, response_text: str) -> ValidationResult:
        """
        Extract claims from response_text and check each against the KG.
        Returns ValidationResult. Never raises -- catches all exceptions.
        """
        try:
            return self._validate_inner(response_text)
        except Exception:
            # Never break the response pipeline
            return ValidationResult(
                has_contradictions=False,
                contradictions=[],
                claims_checked=0,
            )

    def format_correction_note(self, result: ValidationResult) -> str:
        """
        Format a brief correction note (ASCII only, max 2 items).
        Returns empty string if no contradictions or none meet the weight threshold.
        Example: "[Nota: segun mi base de conocimiento, X p Y, no Z]"
        """
        if not result.has_contradictions:
            return ""
        notes = []
        for c in result.contradictions:
            if len(notes) >= 2:
                break
            s, p, o = c["claim"]
            _, _, stored_o, w = c["stored_fact"]
            if w >= 0.7:
                note = (
                    f"[Nota: segun mi base de conocimiento, "
                    f"{s} {p} {stored_o}, no {o}]"
                )
                # Ensure ASCII only -- replace any non-ASCII with closest safe char
                note = note.encode("ascii", errors="replace").decode("ascii")
                notes.append(note)
        return " ".join(notes)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _validate_inner(self, response_text: str) -> ValidationResult:
        claims = self._extract_claims(response_text)
        contradictions = []

        for subj, pred, obj in claims:
            stored_facts = self._get_stored_facts(subj, pred)
            for fact in stored_facts:
                if self._contradicts(obj, fact["object"]):
                    contradictions.append({
                        "claim": (subj, pred, obj),
                        "stored_fact": (
                            fact["subject"],
                            fact["predicate"],
                            fact["object"],
                            fact["weight"],
                        ),
                        "conflict_type": "value_mismatch",
                    })

        return ValidationResult(
            has_contradictions=len(contradictions) > 0,
            contradictions=contradictions,
            claims_checked=len(claims),
        )

    def _extract_claims(self, text: str) -> List[Tuple[str, str, str]]:
        """Extract (subject, predicate, object) claims from text."""
        if len(text) < 30:
            return []

        claims: List[Tuple[str, str, str]] = []
        # Split into sentences to reduce greedy cross-clause matches
        sentences = re.split(r"[.!?\n]+", text)
        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) < 10:
                continue
            for pattern, raw_pred in _RFV_PATTERNS:
                for m in pattern.finditer(sentence):
                    subj = self._normalize(m.group(1))
                    obj  = self._normalize(m.group(2))
                    if len(subj) < 3 or len(obj) < 3:
                        continue
                    if subj in _STOPWORDS or obj in _STOPWORDS:
                        continue
                    if len(subj) > 60 or len(obj) > 60:
                        continue
                    kg_pred = _RFV_PRED_MAP.get(raw_pred, "related_to")
                    claims.append((subj, kg_pred, obj))

        # Deduplicate while preserving order
        seen = set()
        unique: List[Tuple[str, str, str]] = []
        for c in claims:
            if c not in seen:
                seen.add(c)
                unique.append(c)
        return unique

    def _get_stored_facts(self, subject: str, predicate: str) -> list:
        """
        Query KG for rows with matching subject AND predicate.
        Uses the KG's db_connect pattern (same as graph.py).
        """
        try:
            from storage.db_pool import db_connect_pooled as db_connect
            from cognia.config import DB_PATH
            db_path = getattr(self.kg, "db", DB_PATH)
            conn = db_connect(db_path)
            c = conn.cursor()
            c.execute(
                "SELECT subject, predicate, object, weight "
                "FROM knowledge_graph "
                "WHERE subject=? AND predicate=? "
                "ORDER BY weight DESC LIMIT 10",
                (subject, predicate),
            )
            rows = c.fetchall()
            conn.close()
            return [
                {"subject": r[0], "predicate": r[1], "object": r[2], "weight": r[3]}
                for r in rows
            ]
        except Exception:
            return []

    def _contradicts(self, claim_obj: str, stored_obj: str) -> bool:
        """
        Return True if claim_obj and stored_obj are meaningfully different.
        Not a contradiction if one contains the other, or if they are similar
        (edit_distance / max_len <= 0.4 -- typo tolerance).
        """
        a = self._normalize(claim_obj)
        b = self._normalize(stored_obj)
        if a == b:
            return False
        # Containment: "scripting language" vs "language" -- not a contradiction
        if a in b or b in a:
            return False
        # Edit-distance check to avoid flagging typo variants
        dist = _edit_distance(a, b)
        max_len = max(len(a), len(b), 1)
        similarity_ratio = 1.0 - (dist / max_len)
        # If objects are too similar (ratio > 0.6), treat as same thing
        if similarity_ratio > 0.6:
            return False
        return True

    def _normalize(self, text: str) -> str:
        """Lowercase, strip leading articles and punctuation, collapse whitespace."""
        text = text.strip().lower()
        text = _STRIP_ARTICLES.sub("", text).strip()
        text = re.sub(r"[^\w\s]", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text


# ---------------------------------------------------------------------------
# Levenshtein edit distance (pure Python, no external deps)
# ---------------------------------------------------------------------------

def _edit_distance(a: str, b: str) -> int:
    """Character-level Levenshtein distance."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    # Limit to first 80 chars to keep O(n*m) bounded
    a = a[:80]
    b = b[:80]
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1] + [0] * len(b)
        for j, cb in enumerate(b):
            curr[j + 1] = min(
                prev[j + 1] + 1,   # deletion
                curr[j] + 1,       # insertion
                prev[j] + (0 if ca == cb else 1),  # substitution
            )
        prev = curr
    return prev[-1]
