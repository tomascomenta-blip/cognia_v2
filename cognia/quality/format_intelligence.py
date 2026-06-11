"""
cognia/quality/format_intelligence.py
======================================
Phase 59 - Response Format Intelligence (RFI)

Detects user question type via pure regex heuristics and returns a formatting
hint to inject into the system prompt so the LLM structures its reply
optimally. No LLM calls, no external dependencies.
"""

from __future__ import annotations

import re


class QuestionType:
    HOW_TO  = "how_to"   # "how do I", "como hago", "how to"
    COMPARE = "compare"  # "compare X vs Y", "difference between", "cual es mejor"
    EXPLAIN = "explain"  # "what is", "explain", "que es", "define"
    LIST    = "list"     # "list", "give me examples", "name some", "what are"
    DEBUG   = "debug"    # "why is X failing", "error", "bug", "not working"
    YES_NO  = "yes_no"   # "is X", "does X", "can X", "do I need"
    CODE    = "code"     # "implement", "write a function", "create a class", "hace una funcion"
    GENERAL = "general"  # fallback


# Compiled patterns (order matters — first match wins)
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        QuestionType.HOW_TO,
        re.compile(
            r'\b(how\s+do\s+i|how\s+to|como\s+hago|como\s+puedo|steps?\s+to)\b',
            re.IGNORECASE,
        ),
    ),
    (
        QuestionType.COMPARE,
        re.compile(
            r'\b(compare|vs\.?|versus|difference\s+between|cual\s+es\s+mejor|which\s+is\s+better)\b',
            re.IGNORECASE,
        ),
    ),
    (
        QuestionType.DEBUG,
        re.compile(
            r'\b(error|exception|bug|not\s+working|fails?|crashes?|traceback|why\s+is.{0,30}not)\b',
            re.IGNORECASE,
        ),
    ),
    (
        QuestionType.LIST,
        re.compile(
            r'\b(list|give\s+me\s+examples?|name\s+some|what\s+are\s+some|ejemplos?|cuales\s+son)\b',
            re.IGNORECASE,
        ),
    ),
    (
        QuestionType.EXPLAIN,
        re.compile(
            r'\b(what\s+is|explain|define|describe|que\s+es|que\s+significa)\b',
            re.IGNORECASE,
        ),
    ),
    (
        QuestionType.YES_NO,
        re.compile(
            r'^(is|does|can|do|will|should|are|have|has|did|was|were|could|would)\s',
            re.IGNORECASE,
        ),
    ),
    (
        QuestionType.CODE,
        re.compile(
            r'\b(implement|write\s+a\s+(function|class|script|program|method)|'
            r'create\s+a\s+(function|class|script|module)|'
            r'code\s+(a|an|the)\s+\w+|'
            r'(hace?|haz)\s+una?\s+(funcion|clase|script|programa)|'
            r'implementa\s+|escribe\s+(una?\s+)?(funcion|clase))\b',
            re.IGNORECASE,
        ),
    ),
]

_HINTS: dict[str, str] = {
    QuestionType.HOW_TO:  "Format your response as numbered steps. Be concise and practical.",
    QuestionType.COMPARE: "Structure your response with clear comparisons. Use bullet points for each option's pros and cons.",
    QuestionType.DEBUG:   "Focus on the root cause first, then provide a concrete fix. Show corrected code if relevant.",
    QuestionType.LIST:    "Respond with a concise bullet-point list. 3-7 items maximum.",
    QuestionType.EXPLAIN: "Start with a one-sentence definition, then elaborate with 2-3 key points.",
    QuestionType.YES_NO:  "Start with a direct yes or no, then briefly explain why.",
    QuestionType.CODE:    "Provide a complete, working implementation. Use clear variable names and handle edge cases.",
    QuestionType.GENERAL: "",
}


class FormatIntelligence:
    """
    Detects question type and returns a formatting hint for the system prompt.
    Pure regex — no LLM calls. Thread-safe (stateless).
    """

    def detect_type(self, message: str) -> str:
        """Classify message into a QuestionType string constant."""
        text = message.strip()
        for qtype, pattern in _PATTERNS:
            if pattern.search(text):
                return qtype
        return QuestionType.GENERAL

    def get_format_hint(self, message: str) -> str:
        """
        Return ASCII format instruction string for the system prompt.
        Returns empty string for GENERAL type.
        """
        qtype = self.detect_type(message)
        return _HINTS.get(qtype, "")
