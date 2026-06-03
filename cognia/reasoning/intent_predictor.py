"""
cognia/reasoning/intent_predictor.py — Conversational Intent Predictor (CIP)

Predicts likely follow-up queries given a current query Q and its response R.
Pure heuristic, no LLM calls, no external deps. Target: < 5ms execution.

Four prediction strategies:
  1. TOPIC EXPANSION  — extract main entity, generate "how does X work?", "example of X?" etc.
  2. DEPTH DRILL      — conceptual query → predict detail/syntax/comparison requests
  3. CORRECTION FOLLOW-UP — low-confidence markers in response → predict clarification queries
  4. TASK FOLLOW-UP   — "write code / create / build" → predict refinement queries
"""

from __future__ import annotations

import re
from typing import Optional

# Patterns to identify the query intent (Spanish + English)
_WHAT_IS_RE   = re.compile(
    r"^\s*(what\s+is|what'?s|que\s+es|que\+es|qu[ée]\s+es|define|definicion\s+de|definition\s+of)\s+(.+)",
    re.IGNORECASE,
)
_HOW_TO_RE    = re.compile(
    r"^\s*(how\s+to|how\s+do|c[oó]mo\s+(se\s+)?|como\s+usar|how\s+does)\s+(.+)",
    re.IGNORECASE,
)
_EXPLAIN_RE   = re.compile(
    r"^\s*(explain|explica(?:me)?|describe|qu[ée]\s+hace|what\s+does)\s+(.+)",
    re.IGNORECASE,
)
_TASK_RE      = re.compile(
    r"^\s*(write|create|make|build|generate|crea(?:r)?|escribe|genera(?:r)?|implementa(?:r)?|"
    r"hazme|haz\s+un|create\s+a|write\s+a(?:n)?)\s+(.+)",
    re.IGNORECASE,
)
_COMPARE_RE   = re.compile(
    r"\b(vs\.?|versus|compared?\s+to|diferencia(?:s)?\s+(entre|de)|difference\s+between)\b",
    re.IGNORECASE,
)
# Uncertainty markers in assistant response
_UNCERTAIN_RE = re.compile(
    r"\b(no\s+estoy\s+seguro|no\s+tengo\s+certeza|I(?:'m|\s+am)\s+not\s+(sure|certain)|"
    r"I\s+(think|believe|might|may)\s+(be\s+wrong|not\s+be|it\s+could)|"
    r"might\s+be\s+wrong|tal\s+vez|quiz[aá]s|posiblemente|probablemente|"
    r"I(?:'m|\s+am)\s+unsure|no\s+s[eé]\s+(con\s+certeza|exactamente))\b",
    re.IGNORECASE,
)
# Stopwords for entity extraction (Spanish + English)
_STOP = frozenset({
    "el", "la", "los", "las", "un", "una", "de", "del", "en", "a",
    "que", "y", "es", "se", "por", "con", "para", "como", "su", "lo",
    "the", "a", "an", "is", "are", "of", "in", "to", "and", "for",
    "that", "it", "with", "as", "at", "be", "this", "or", "on", "by",
    "can", "do", "does", "did", "has", "have", "had", "will", "would",
    "me", "you", "we", "they", "i", "my", "your", "our", "their",
    "what", "how", "why", "when", "where", "which", "who",
    "please", "just", "very", "really", "some", "any",
})

# Levenshtein-ish similarity: normalized token overlap
def _token_sim(a: str, b: str) -> float:
    ta = set(a.lower().split())
    tb = set(b.lower().split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(len(ta), len(tb))


class IntentPredictor:
    """
    Returns up to n likely follow-up queries for a given (query, response) pair.
    All methods are stateless and thread-safe.
    """

    def predict_followups(self, query: str, response: str, n: int = 3) -> list[str]:
        """
        Returns up to n likely follow-up queries.
        Pure heuristic, no LLM calls, < 5ms execution.
        """
        if not query or not query.strip():
            return []

        candidates: list[str] = []
        candidates.extend(self._topic_expansion(query))
        candidates.extend(self._depth_drill(query, response))
        candidates.extend(self._correction_followup(response))
        candidates.extend(self._task_followup(query))
        return self._deduplicate(candidates)[:n]

    # ── private helpers ────────────────────────────────────────────────

    def _extract_main_entity(self, text: str) -> str:
        """Extract the main noun phrase (best-effort) from text."""
        # Strip leading question words and common prefixes
        cleaned = re.sub(
            r"^\s*(what\s+is|what'?s|que\s+es|qu[ée]\s+es|how\s+does|c[oó]mo|explain|"
            r"explica(?:me)?|define|write\s+a(?:n)?|create\s+a(?:n)?|make\s+a(?:n)?|"
            r"build\s+a(?:n)?|haz\s+un|crea(?:r)?|escribe|genera(?:r)?|the|un|una)\s+",
            "",
            text,
            flags=re.IGNORECASE,
        ).strip()
        # Remove trailing punctuation
        cleaned = cleaned.rstrip("?.!,;:")
        # Take first 3-5 content words, skip stop words
        words = [w for w in cleaned.split() if w.lower() not in _STOP]
        if not words:
            # fallback: take first 3 words of cleaned
            words = cleaned.split()[:3]
        entity = " ".join(words[:4])
        return entity.strip() if entity.strip() else text.strip()[:40]

    def _topic_expansion(self, query: str) -> list[str]:
        """
        Given a "what is X?" or "X es un Y" type query, generate:
          - "how does X work?"
          - "give me an example of X"
          - "what are the uses of X?" / "what is X used for?"
        """
        results: list[str] = []

        # Match "what is X?" / "que es X?"
        m = _WHAT_IS_RE.match(query)
        if m:
            entity = m.group(2).rstrip("?.!").strip()
            if entity:
                results.append(f"how does {entity} work?")
                results.append(f"give me an example of {entity}")
                results.append(f"what are the uses of {entity}?")
            return results

        # Match "explain X" / "describe X"
        m = _EXPLAIN_RE.match(query)
        if m:
            entity = m.group(2).rstrip("?.!").strip()
            if entity:
                results.append(f"explain {entity} in more detail")
                results.append(f"give me an example of {entity}")
                results.append(f"what is {entity} used for?")
            return results

        # Generic: extract entity and produce generic follow-ups
        entity = self._extract_main_entity(query)
        if entity and len(entity) > 2:
            results.append(f"how does {entity} work?")
            results.append(f"give me an example of {entity}")

        return results

    def _depth_drill(self, query: str, response: str) -> list[str]:
        """
        If the query is conceptual or the response is long, predict detail/syntax requests.
        """
        results: list[str] = []
        q_lower = query.lower()

        # Already a "how to" — no depth drill needed (already concrete)
        if _HOW_TO_RE.match(query):
            return results

        entity = self._extract_main_entity(query)

        # If response is long (>300 chars), user likely wants a summary or clarification
        if len(response) > 300:
            results.append(f"can you summarize that?")

        # Conceptual indicator: "what is", "explain", "describe"
        is_conceptual = bool(
            _WHAT_IS_RE.match(query) or
            _EXPLAIN_RE.match(query) or
            re.search(r"\b(concept|definition|overview|overview|basics|fundamentos|concepto)\b", q_lower)
        )
        if is_conceptual and entity and len(entity) > 2:
            results.append(f"what is the syntax of {entity}?")
            results.append(f"what are common mistakes with {entity}?")

        # Comparison trigger
        if _COMPARE_RE.search(query):
            results.append("what are the key differences?")
            results.append("which one should I use?")

        return results

    def _correction_followup(self, response: str) -> list[str]:
        """
        If the response contains uncertainty markers, predict clarification follow-ups.
        """
        if not response:
            return []
        if _UNCERTAIN_RE.search(response):
            return [
                "can you be more specific?",
                "are you sure about that?",
            ]
        return []

    def _task_followup(self, query: str) -> list[str]:
        """
        If the query is a task request ("write code for X", "create Y"),
        predict refinement or explanation requests.
        """
        results: list[str] = []
        m = _TASK_RE.match(query)
        if not m:
            return results

        verb = m.group(1).lower()
        # Distinguish code-generating tasks from generic creation
        is_code = any(kw in query.lower() for kw in (
            "code", "function", "class", "script", "program", "algorithm",
            "implementation", "implement", "codigo", "funcion", "programa",
        ))
        if is_code:
            results.append("make it more efficient")
            results.append("add error handling")
            results.append("explain this code")
        else:
            results.append("can you improve it?")
            results.append("make it more detailed")

        return results

    def _deduplicate(self, candidates: list[str]) -> list[str]:
        """
        Remove exact duplicates and near-identical strings (token overlap >= 0.75).
        Preserves insertion order (earlier = higher priority).
        """
        seen: list[str] = []
        for cand in candidates:
            if not cand or not cand.strip():
                continue
            cand = cand.strip()
            is_dup = False
            for s in seen:
                if _token_sim(cand, s) >= 0.75:
                    is_dup = True
                    break
            if not is_dup:
                seen.append(cand)
        return seen
