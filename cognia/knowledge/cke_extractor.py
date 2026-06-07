"""
cognia/knowledge/cke_extractor.py
===================================
Conversational Knowledge Extraction (CKE) — Phase 53.

Extracts structured facts from user messages using pure regex and stores them
in the KnowledgeGraph. Designed to run fire-and-forget on every /infer call.
"""

import re
from typing import List, Tuple

from cognia.knowledge.graph import KnowledgeGraph

# Entities too generic to be useful graph nodes
_STOP_ENTITIES = frozenset({
    "it", "this", "that", "he", "she", "they", "we", "i", "you",
    "one", "thing", "something", "anything", "everything", "nothing",
    "someone", "anyone", "everyone",
})

# Leading articles to strip before storing an entity
_ARTICLE_RE = re.compile(
    r"^\s*(?:el|la|los|las|un|una|unos|unas|the|a|an)\s+",
    re.IGNORECASE,
)

# Punctuation to strip from right edge of captured groups
_TRAIL_PUNCT_RE = re.compile(r"[.,;:!?'\"]+$")


def _clean(text: str) -> str:
    text = text.strip().lower()
    text = _ARTICLE_RE.sub("", text).strip()
    text = _TRAIL_PUNCT_RE.sub("", text).strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _valid(entity: str) -> bool:
    return len(entity) >= 2 and entity not in _STOP_ENTITIES


# Each pattern: (compiled_re, predicate, weight, subject_group, object_group)
# subject_group / object_group: 1-indexed re match groups, or the literal "user"
_PATTERNS: List[Tuple] = [
    # Correction: "no, X is Y" / "actually X is Y" / "wrong, X is Y"
    (
        re.compile(
            r"(?:no[,.]?\s+|actually[,.]?\s+|wrong[,.]?\s+)"
            r"(.{2,40}?)\s+is\s+(?:not\s+)?([a-z][a-z ]{1,40}?)(?:[.,;!?]|$)",
            re.IGNORECASE,
        ),
        "is_a", 0.9, 1, 2,
    ),
    # IS-A English: "X is a Y" / "X is an Y"
    (
        re.compile(
            r"\b(.{2,40}?)\s+is\s+an?\s+([a-z][a-z ]{1,40}?)(?:[.,;!?]|$)",
            re.IGNORECASE,
        ),
        "is_a", 0.8, 1, 2,
    ),
    # IS-A Spanish: "X es un Y" / "X es una Y"
    (
        re.compile(
            r"\b(.{2,40}?)\s+es\s+un[ao]?\s+([a-zA-ZáéíóúñÁÉÍÓÚÑ][a-zA-ZáéíóúñÁÉÍÓÚÑ ]{1,40}?)(?:[.,;!?]|$)",
            re.IGNORECASE,
        ),
        "is_a", 0.8, 1, 2,
    ),
    # PROPERTY English: "X has Y"
    (
        re.compile(
            r"\b(.{2,40}?)\s+has\s+([a-z][a-z ]{1,40}?)(?:[.,;!?]|$)",
            re.IGNORECASE,
        ),
        "has_property", 0.7, 1, 2,
    ),
    # PROPERTY Spanish: "X tiene Y"
    (
        re.compile(
            r"\b(.{2,40}?)\s+tiene\s+([a-zA-ZáéíóúñÁÉÍÓÚÑ][a-zA-ZáéíóúñÁÉÍÓÚÑ ]{1,40}?)(?:[.,;!?]|$)",
            re.IGNORECASE,
        ),
        "has_property", 0.7, 1, 2,
    ),
    # RELATED-TO: "X uses Y" / "X works with Y" / "X does Y"
    (
        re.compile(
            r"\b(.{2,40}?)\s+(?:uses|works with|does)\s+([a-z][a-z ]{1,40}?)(?:[.,;!?]|$)",
            re.IGNORECASE,
        ),
        "related_to", 0.6, 1, 2,
    ),
    # USER IS: "I am X"
    (
        re.compile(
            r"\bI\s+am\s+(?:an?\s+)?([a-z][a-z ]{1,40}?)(?:[.,;!?]|$)",
            re.IGNORECASE,
        ),
        "is_a", 0.85, None, 1,
    ),
    # USER WORKS: "I work at Y" / "I work for Y"
    (
        re.compile(
            r"\bI\s+work\s+(?:at|for)\s+([a-zA-Z][a-zA-Z0-9 ]{1,40}?)(?:[.,;!?]|$)",
            re.IGNORECASE,
        ),
        "located_in", 0.85, None, 1,
    ),
    # USER PREFERS: "I prefer X" / "I like X" / "I love X" / "I use X"
    (
        re.compile(
            r"\bI\s+(?:prefer|like|love|use)\s+([a-z][a-z ]{1,40}?)(?:[.,;!?]|$)",
            re.IGNORECASE,
        ),
        "related_to", 0.85, None, 1,
    ),
]

# Map CKE predicates to the KG VALID_RELATIONS set
_PRED_MAP = {
    "is_a":         "is_a",
    "has_property": "has_property",
    "related_to":   "related_to",
    "located_in":   "located_in",
}

_MAX_FACTS = 5


class CKEExtractor:
    def __init__(self, kg: KnowledgeGraph):
        self._kg = kg

    def extract_and_store(
        self,
        user_message: str,
        assistant_response: str = "",
    ) -> List[Tuple[str, str, str, float]]:
        """
        Extract facts from user_message and store them in the KG.
        Returns list of (subject, predicate, object, weight) for each stored triple.
        assistant_response is accepted for API symmetry but not processed — user
        utterances carry higher-signal self-disclosure than generated text.
        """
        stored: List[Tuple[str, str, str, float]] = []
        text = user_message.strip()
        if not text:
            return stored

        # Process sentence-by-sentence to avoid greedy cross-clause captures
        sentences = re.split(r"[.!?\n]+", text)

        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) < 4:
                continue
            if len(stored) >= _MAX_FACTS:
                break

            for pat, predicate, weight, s_group, o_group in _PATTERNS:
                if len(stored) >= _MAX_FACTS:
                    break
                for m in pat.finditer(sentence):
                    if len(stored) >= _MAX_FACTS:
                        break

                    subject = "user" if s_group is None else _clean(m.group(s_group))
                    obj = _clean(m.group(o_group))  # o_group is always an int here

                    if not _valid(subject) or not _valid(obj):
                        continue
                    if len(subject) > 60 or len(obj) > 60:
                        continue

                    kg_pred = _PRED_MAP.get(predicate, "related_to")
                    self._kg.add_triple(subject, kg_pred, obj, weight=weight, source="cke")
                    stored.append((subject, kg_pred, obj, weight))

        return stored
