"""
response_gate.py -- Deterministic quality gate for AI responses.
Scores responses before delivery and triggers a retry if quality is too low.
No LLM calls -- pure heuristics.
"""

import re
from typing import Tuple

# Words ignored when extracting keywords for relevance scoring
_STOPWORDS = frozenset({
    "the", "a", "an", "is", "it", "in", "on", "at", "to", "for", "of",
    "and", "or", "but", "with", "this", "that", "are", "was", "were",
    "be", "been", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "can", "not", "no",
    "from", "by", "as", "if", "so", "up", "out", "about", "what",
    "how", "when", "where", "who", "which", "they", "we", "you", "he",
    "she", "his", "her", "their", "our", "my", "your", "its", "all",
    # Spanish common stopwords
    "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del",
    "al", "en", "con", "por", "para", "que", "como", "mas", "pero",
    "muy", "ya", "si", "hay", "ser", "esta", "ese", "esa", "eso",
    "me", "te", "se", "le", "les", "nos", "sus", "sin",
})

# Patterns that indicate a refusal or error response
_REFUSAL_STARTS = (
    "i cannot",
    "i can't",
    "i don't know",
    "no puedo",
    "no se",
    "no sé",
    "lo siento, no",
    "sorry, i",
    "i'm sorry, i",
    "i am unable",
    "i am not able",
)

_ERROR_MARKERS = ("error:", "exception:", "traceback (")


class ResponseGate:
    """
    Deterministic quality gate. Scores responses before delivery.
    No LLM calls -- pure heuristics.

    Score is 0.0-1.0 composed of three weighted sub-scores:
      - length check     (weight 0.3)
      - relevance check  (weight 0.4)
      - refusal/error    (weight 0.3)
    """

    # Retry threshold: responses scoring below this trigger a retry
    RETRY_THRESHOLD = 0.35

    # ---- sub-scorers ----------------------------------------------------

    def _score_length(self, response: str) -> float:
        """Return 0.0-1.0 based on character length."""
        n = len(response)
        if n < 20:
            return 0.0
        if n < 50:
            return 0.3
        if n <= 200:
            return 0.7
        return 1.0

    def _extract_keywords(self, text: str) -> list:
        """Extract meaningful words (>3 chars, not stopwords) from text."""
        words = re.findall(r"[a-zA-Z\u00e0-\u00ff]{4,}", text.lower())
        return [w for w in words if w not in _STOPWORDS]

    def _score_relevance(self, question: str, response: str) -> float:
        """Return 0.0-1.0 based on keyword overlap between question and response."""
        keywords = self._extract_keywords(question)
        if not keywords:
            return 0.5
        response_lower = response.lower()
        matches = sum(1 for kw in keywords if kw in response_lower)
        return min(matches / len(keywords), 1.0)

    def _score_refusal(self, question: str, response: str) -> float:
        """Return 0.0-1.0 penalizing refusals, errors, and question echoes."""
        resp_lower = response.lower().strip()

        # Hard penalty: short refusal
        if len(response) < 150:
            for prefix in _REFUSAL_STARTS:
                if resp_lower.startswith(prefix):
                    return 0.0

        # Hard penalty: response is only the question repeated
        q_stripped = question.strip().lower()
        if resp_lower == q_stripped:
            return 0.0
        # Near-echo: response contains almost nothing but the question text
        if q_stripped and len(response) < len(question) * 1.2:
            norm_resp = re.sub(r"[?.!]+", "", resp_lower).strip()
            norm_q    = re.sub(r"[?.!]+", "", q_stripped).strip()
            if norm_resp == norm_q:
                return 0.0

        # Partial penalty: error/exception markers
        for marker in _ERROR_MARKERS:
            if marker in resp_lower:
                return 0.2

        return 1.0

    # ---- public API -----------------------------------------------------

    def score(self, question: str, response: str) -> float:
        """
        Return a 0.0-1.0 quality score for the response.
        Combined as weighted sum: length (0.3) + relevance (0.4) + refusal (0.3)
        """
        if not response or not response.strip():
            return 0.0

        length_s    = self._score_length(response)
        relevance_s = self._score_relevance(question, response)
        refusal_s   = self._score_refusal(question, response)

        # When refusal/echo is detected (0.0), relevance credit is forfeited --
        # matching keywords because the response IS the question is not informative.
        if refusal_s == 0.0:
            relevance_s = 0.0

        combined = (length_s * 0.3) + (relevance_s * 0.4) + (refusal_s * 0.3)
        return round(max(0.0, min(1.0, combined)), 4)

    def should_retry(self, question: str, response: str) -> Tuple[bool, str]:
        """
        Decide whether the response warrants a retry.
        Returns (retry: bool, reason: str).
        reason is ASCII-safe and is included in the retry prompt.
        """
        q_score = self.score(question, response)
        if q_score >= self.RETRY_THRESHOLD:
            return (False, "")

        length_s    = self._score_length(response)
        relevance_s = self._score_relevance(question, response)
        refusal_s   = self._score_refusal(question, response)

        if length_s == 0.0 or not response.strip():
            reason = "response too short"
        elif refusal_s == 0.0:
            reason = "incomplete response"
        elif relevance_s < 0.15:
            reason = "off-topic response"
        else:
            reason = "incomplete response"

        return (True, reason)

    def build_retry_prompt(
        self, original_question: str, bad_response: str, reason: str
    ) -> str:
        """
        Build an enhanced prompt that explains what went wrong.
        bad_response is accepted for API symmetry but not echoed back,
        to keep the retry prompt short.
        """
        return (
            f"The previous answer was {reason}. "
            f"Please answer more completely: {original_question}"
        )

    def pick_better(self, question: str, original: str, candidate: str) -> str:
        """Devuelve la respuesta de MAYOR calidad (score), no la mas larga. Desempata a
        favor de 'original' (no reemplazar sin mejora real). Usado por el auto-gate para
        quedarse con la regeneracion solo si puntua mejor (FASE 4a)."""
        if not candidate or not candidate.strip():
            return original
        if self.score(question, candidate) > self.score(question, original):
            return candidate
        return original
