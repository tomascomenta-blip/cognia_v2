import re

_SIMPLE_QTYPES = {"social", "proyecto_actual", "factual_simple"}

_DECOMPOSE_TRIGGERS = re.compile(
    r'\b(y|además|también|and|also|how|why|what|cómo|por qué|qué)\b',
    re.IGNORECASE
)

_SENTENCE_SPLIT = re.compile(r'[,;]| y | and | además | también | also ')

_NEGATION_PAT = re.compile(
    r'\b(no|nunca|jamas|never|contradice|niega|incorrecto|falso)\b',
    re.IGNORECASE
)

try:
    from cognia.reasoning.contradiction import ContradictionDetector as _CD
    _HAS_CONTRADICTION = True
except Exception:
    _HAS_CONTRADICTION = False


def _detect_contradiction_in_text(text: str) -> bool:
    """Heuristic contradiction scan on plain text without semantic DB access."""
    # Look for opposing claim markers within a short window
    _CONTRA_PAT = re.compile(
        r'\b(pero|however|sin embargo|aunque|yet|nevertheless|on the other hand|'
        r'por otro lado|contrariamente|en cambio|no obstante)\b',
        re.IGNORECASE
    )
    return bool(_CONTRA_PAT.search(text))


class CogniaReasoningEngine:
    def enrich(self, question: str, context: str, q_type: str) -> str:
        """Return enriched context string. Backward-compatible — callers receive a str."""
        return self.enrich_with_meta(question, context, q_type)["context"]

    def enrich_with_meta(self, question: str, context: str, q_type: str) -> dict:
        """
        Returns enriched context plus epistemic metadata.

        Keys:
          context          str   — same as enrich() output
          confidence       float — 0.1-0.95 estimated epistemic confidence
          has_contradiction bool  — True if contradictory markers detected in context
          sub_questions    list  — decomposed sub-questions (may be empty)
        """
        words = question.split()
        if len(words) < 15 or q_type in _SIMPLE_QTYPES:
            return {
                "context": context,
                "confidence": 0.7,
                "has_contradiction": False,
                "sub_questions": [],
            }

        # Decompose into sub-questions (up to 3)
        if _DECOMPOSE_TRIGGERS.search(question):
            parts = [p.strip() for p in _SENTENCE_SPLIT.split(question) if len(p.strip()) > 8]
            sub_qs = parts[:3]
        else:
            sub_qs = [question]

        if len(sub_qs) <= 1:
            enriched_ctx = context
        else:
            bullet_list = "\n".join(f"- {sq}" for sq in sub_qs)
            prefix = f"Analizando:\n{bullet_list}\n\n"
            enriched_ctx = context
            if question in context:
                enriched_ctx = context.replace(question, "").strip()
            enriched_ctx = prefix + enriched_ctx

        # Contradiction detection: heuristic only (no DB/vector access here)
        has_contradiction = _detect_contradiction_in_text(context)

        # Confidence estimation
        confidence = 0.7
        if len(context) < 100:
            confidence -= 0.2
        if has_contradiction:
            confidence -= 0.2
        if _NEGATION_PAT.search(question):
            confidence -= 0.1
        if len(sub_qs) > 3:
            confidence -= 0.1
        confidence = max(0.1, min(0.95, confidence))

        return {
            "context": enriched_ctx,
            "confidence": confidence,
            "has_contradiction": has_contradiction,
            "sub_questions": sub_qs if len(sub_qs) > 1 else [],
        }
