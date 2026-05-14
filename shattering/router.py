"""
shattering/router.py
====================
GlobalRouter — decides which sub-model to use based on the input query.

Routing is done via keyword heuristics + domain scoring.
Falls back to LOGOS for generic or ambiguous queries.

Domain map:
  TECHNE  — code, technical, algorithms, engineering
  RHETOR  — writing, editing, style, language production
  LOGOS   — reasoning, knowledge, analysis, everything else
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class RouteDecision:
    sub_model:  str             # "logos" | "techne" | "rhetor"
    confidence: float           # 0.0–1.0
    scores:     Dict[str, int]  # raw keyword hits per domain
    reason:     str


# ── Keyword tables ─────────────────────────────────────────────────────

router_version = "1.1"

_TECHNE: List[str] = [
    "code", "function", "bug", "debug", "error", "exception", "syntax",
    "implement", "algorithm", "class", "method", "variable", "compile",
    "script", "program", "python", "javascript", "typescript", "java",
    "rust", "golang", "kotlin", "swift", "bash", "shell", "terminal",
    "sql", "query", "database", "api", "endpoint", "library", "framework",
    "docker", "git", "regex", "unit test", "refactor", "import", "module",
    "package", "repository", "devops", "pipeline", "deploy", "lambda",
    "recursion", "loop", "array", "dict", "hash", "pointer", "thread",
    "async", "await", "coroutine", "stack", "heap", "binary", "bitwise",
    "makefile", "cmake", "linter", "formatter", "debugger", "profiler",
    # v1.1 additions
    "model", "training", "neural", "tensor", "gpu", "machine learning",
    "deep learning", "django", "fastapi", "react", "vue", "kubernetes",
    "serverless", "pandas", "numpy", "spark", "postgresql", "mongodb",
    "llm", "fine-tune", "embedding",
]

_RHETOR: List[str] = [
    "write", "essay", "draft", "paragraph", "sentence", "grammar",
    "summarize", "summary", "translate", "translation", "style", "tone",
    "formal", "informal", "persuasive", "narrative", "creative", "story",
    "poem", "poetry", "letter", "email", "report", "thesis", "academic",
    "citation", "quote", "paraphrase", "introduction", "conclusion",
    "edit", "proofread", "rephrase", "reword", "rewrite", "improve text",
    "articulate", "eloquent", "concise", "verbose", "metaphor", "analogy",
    "blog", "article", "review", "describe", "depict", "illustrate",
    "redact", "redactar", "ensayo", "resumen",
    # v1.1 additions
    "marketing", "campaign", "brand", "pitch", "copywriting", "proposal",
    "memo", "screenplay", "dialogue", "documentation", "manual", "guide",
    "tutorial", "specification", "propuesta", "borrador", "introduccion",
]

_LOGOS: List[str] = [
    "explain", "why", "how does", "what is", "analyze", "compare", "contrast",
    "logic", "reason", "reasoning", "philosophy", "science", "math",
    "history", "fact", "knowledge", "understand", "concept", "theory",
    "hypothesis", "evidence", "argument", "debate", "pros", "cons",
    "evaluate", "assess", "implication", "consequence", "cause", "effect",
    "define", "definition", "meaning", "significance", "relationship",
    "think", "thought", "idea", "insight", "paradox", "dilemma",
    # v1.1 additions
    "algebra", "calculus", "geometry", "proof", "physics", "chemistry",
    "biology", "quantum", "ethics", "sociology", "economics", "estadistica",
    "demostrar", "analizar", "explicar",
]

_DOMAIN_KEYWORDS: Dict[str, List[str]] = {
    "techne": _TECHNE,
    "rhetor": _RHETOR,
    "logos":  _LOGOS,
}


class GlobalRouter:
    """
    Routes a text prompt to the most appropriate Shattering sub-model.

    Scoring: each keyword hit adds 1 point to that domain.
    Longer phrases are matched before shorter ones to avoid partial overlaps.
    Ties go to the default sub-model (logos).
    Confidence = winner_score / total_score, clamped to [0.3, 1.0].
    """

    def __init__(self, default_submodel: str = "logos"):
        self.default = default_submodel
        self._patterns: Dict[str, List[re.Pattern]] = {}
        for domain, kws in _DOMAIN_KEYWORDS.items():
            # longer phrases first to avoid sub-word matches
            sorted_kws = sorted(kws, key=len, reverse=True)
            self._patterns[domain] = [
                re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE)
                for kw in sorted_kws
            ]

    def route(self, prompt: str) -> RouteDecision:
        """
        Analyse prompt and return a RouteDecision.
        Only the first 2000 characters are used for routing; longer inputs are
        truncated to avoid O(L x K) regex cost on large documents.
        """
        prompt = prompt[:2000]
        scores: Dict[str, int] = {d: 0 for d in _DOMAIN_KEYWORDS}
        for domain, patterns in self._patterns.items():
            for pat in patterns:
                scores[domain] += len(pat.findall(prompt))

        total = sum(scores.values())

        # Pick winner; ties broken by default sub-model priority
        winner = max(
            scores,
            key=lambda d: (scores[d], 1 if d == self.default else 0),
        )

        if total == 0:
            conf   = 0.3
            reason = f"No keyword matches — defaulting to '{self.default}'"
        else:
            conf   = min(1.0, max(0.3, scores[winner] / total))
            reason = (
                f"'{winner}' scored {scores[winner]}/{total} hits "
                f"({conf:.0%} confidence)"
            )

        return RouteDecision(
            sub_model=winner,
            confidence=round(conf, 3),
            scores=scores,
            reason=reason,
        )
