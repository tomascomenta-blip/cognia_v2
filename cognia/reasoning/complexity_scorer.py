"""
cognia/reasoning/complexity_scorer.py
======================================
Inference-Time Compute Scaling (ITCS) — scores query complexity 1-5 and
recommends a pipeline budget (fast/normal/deep).

No LLM calls — pure heuristics for zero-latency overhead.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class ComplexityResult:
    score: int          # 1-5
    budget: str         # "fast" | "normal" | "deep"
    reasons: list[str]  # why this score was assigned (for logging)


class ComplexityScorer:
    """
    Scores query complexity 1-5 using additive heuristics, no LLM calls.

    Score  Budget   Pipeline
    1      fast     No RST, no hypothesis, no self-questioning, 1 memory pass
    2      fast     No RST, no hypothesis, 1 memory pass
    3      normal   Standard pipeline (current behavior)
    4      deep     RST + hypothesis + self-questioning + 2 memory passes
    5      deep     RST + hypothesis + self-questioning + 2 memory passes + plan

    Scoring factors (additive, clipped to [1,5]):
    +0 (base)  : always
    +1         : query length > 80 chars
    +1         : contains "?" or interrogative word
    +1         : technical vocabulary >= 2 words from TECH_VOCAB
    +1         : multi-clause query (>= 3 clause connectors)
    +1         : comparative/analytical terms present

    Score 1 overrides (greetings, single-word, simple confirmations).
    """

    TECH_VOCAB: frozenset[str] = frozenset({
        'algorithm', 'api', 'architecture', 'async', 'binary', 'cache', 'compiler',
        'concurrent', 'cryptography', 'database', 'debug', 'deployment', 'distributed',
        'encryption', 'framework', 'gradient', 'hash', 'inference', 'kernel', 'latency',
        'memory', 'middleware', 'model', 'neural', 'optimization', 'parameter', 'pipeline',
        'protocol', 'queue', 'recursive', 'regex', 'runtime', 'schema', 'serialization',
        'shard', 'socket', 'thread', 'tensor', 'token', 'vector', 'algoritmo', 'arquitectura',
        'cifrado', 'compilador', 'concurrente', 'distribuido', 'encriptacion', 'inferencia',
        'parametro', 'recursivo',
    })

    GREETINGS: frozenset[str] = frozenset({
        'hola', 'hi', 'hello', 'hey', 'buenos', 'buenas', 'thanks', 'gracias', 'ok',
        'okay', 'si', 'no', 'yes', 'bye', 'adios', 'chao', 'ciao',
    })

    # Interrogative words / patterns that signal a real question
    _INTERROGATIVES = re.compile(
        r'\b(what|how|why|when|where|who|which|explain|describe|'
        r'qu[eé]|c[oó]mo|por\s+qu[eé]|cu[aá]l|cu[aá]ndo|d[oó]nde|qui[eé]n|explica|describe)\b',
        re.IGNORECASE,
    )

    _CLAUSE_CONNECTORS = re.compile(
        r'\b(and|or|but|however|while|whereas|although|'
        r'aunque|mientras|pero|sin\s+embargo)\b|[,;]',
        re.IGNORECASE,
    )

    _COMPARATIVE = re.compile(
        r'\b(compare|contrast|tradeoff|trade-off|versus|vs\.?|difference|'
        r'mejor|peor|pros|cons|ventaja|desventaja|'
        r'compared\s+to|diferencia\s+entre)\b',
        re.IGNORECASE,
    )

    def score(self, query: str) -> ComplexityResult:
        """Score the query and return a ComplexityResult."""
        tokens = re.sub(r"[^\w\s]", "", query.lower()).split()
        reasons: list[str] = []

        # ── Override: greeting / single-word / simple confirmation ──────
        if self._is_greeting(tokens):
            return ComplexityResult(score=1, budget="fast",
                                    reasons=["greeting or single-word query"])

        if len(tokens) <= 5 and not self._INTERROGATIVES.search(query):
            return ComplexityResult(score=1, budget="fast",
                                    reasons=["short affirmation, no interrogative"])

        # ── Additive scoring ─────────────────────────────────────────────
        score = 1  # base

        if len(query) > 80:
            score += 1
            reasons.append("length > 80 chars")

        if "?" in query or self._INTERROGATIVES.search(query):
            score += 1
            reasons.append("interrogative word or '?'")

        tech_count = self._count_tech_vocab(tokens)
        if tech_count >= 2:
            score += 1
            reasons.append(f"tech vocab ({tech_count} terms)")

        clause_hits = len(self._CLAUSE_CONNECTORS.findall(query))
        if clause_hits >= 3:
            score += 1
            reasons.append(f"multi-clause ({clause_hits} connectors)")

        if self._COMPARATIVE.search(query):
            score += 1
            reasons.append("comparative/analytical terms")

        score = max(1, min(5, score))

        if not reasons:
            reasons.append("base score")

        budget = self._budget(score)
        return ComplexityResult(score=score, budget=budget, reasons=reasons)

    def _is_greeting(self, tokens: list[str]) -> bool:
        """True for single-word queries, greetings, or greeting-prefixed short queries."""
        if not tokens:
            return True
        # Single word (after punctuation strip)
        if len(tokens) == 1:
            return True
        # First token is a greeting word
        if tokens[0] in self.GREETINGS:
            return True
        # Short phrase starting with greeting prefix
        if len(tokens) <= 3 and tokens[0] in self.GREETINGS:
            return True
        return False

    def _count_tech_vocab(self, tokens: list[str]) -> int:
        """Count how many tokens are in the technical vocabulary set."""
        return sum(1 for t in tokens if t in self.TECH_VOCAB)

    @staticmethod
    def _budget(score: int) -> str:
        if score <= 2:
            return "fast"
        if score == 3:
            return "normal"
        return "deep"
