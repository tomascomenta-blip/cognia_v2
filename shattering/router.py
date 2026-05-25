"""
shattering/router.py
====================
GlobalRouter — decides which sub-model to use based on the input query.

Routing blends keyword heuristics with cosine similarity over 384-dim
embeddings (SentenceTransformer all-MiniLM-L6-v2 or n-gram fallback)
shared with the memory subsystem (cognia_embedding).
Falls back to LOGOS for generic or ambiguous queries.

Domain map:
  TECHNE  — code, technical, algorithms, engineering
  RHETOR  — writing, editing, style, language production
  LOGOS   — reasoning, knowledge, analysis, everything else
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np


@dataclass
class RouteDecision:
    sub_model:  str             # "logos" | "techne" | "rhetor"
    confidence: float           # 0.0–1.0
    scores:     Dict[str, int]  # raw keyword hits per domain
    reason:     str


# ── Keyword tables ─────────────────────────────────────────────────────

router_version = "2.0"  # Phase 20.1: embedding-based semantic routing

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

# ── Embedding-based semantic index (Phase 20.1) ────────────────────────

import math as _math
import threading as _threading


def _make_ngram_encoder(dim: int = 384):
    """Standalone n-gram fallback — no external deps."""
    def _encode(text: str) -> list:
        vec = [0.0] * dim
        t = text.lower().strip()
        for i, ch in enumerate(t):
            vec[(ord(ch) * 31 + i) % dim] += 1.0
        for i in range(len(t) - 1):
            vec[(_hash_str(t[i:i+2])) % dim] += 0.7
        for word in t.split():
            vec[(_hash_str(word)) % dim] += 1.5
        norm = _math.sqrt(sum(x * x for x in vec))
        return [x / norm for x in vec] if norm > 0 else vec
    return _encode


def _hash_str(s: str) -> int:
    return hash(s) & 0x7FFFFFFF


class _EmbeddingIndex:
    """
    Semantic similarity using the same 384-dim embedding space as the
    memory subsystem (cognia_embedding: SentenceTransformer or n-gram fallback).

    Build strategy:
      1. Synchronous n-gram build at init — available immediately.
      2. Background ST rebuild once text_to_vector_fast is importable — atomic swap.

    This ensures routing is never blocked, and upgrades to real embeddings
    transparently once the SentenceTransformer model is loaded by the system.
    """

    def __init__(self) -> None:
        self._centroids: Dict[str, np.ndarray] = {}
        self._lock = _threading.Lock()
        from shattering.model_constants import ROUTER_EMBEDDING_DIM
        self._dim = ROUTER_EMBEDDING_DIM
        self._ngram = _make_ngram_encoder(self._dim)

    def _compute_centroids(self, encode, domain_keywords: Dict[str, List[str]]) -> Dict[str, np.ndarray]:
        result: Dict[str, np.ndarray] = {}
        for domain, kws in domain_keywords.items():
            if not kws:
                continue
            vecs = np.array([encode(kw) for kw in kws], dtype=np.float32)
            centroid = vecs.mean(axis=0)
            norm = np.linalg.norm(centroid)
            result[domain] = centroid / norm if norm > 0 else centroid
        return result

    def build(self, domain_keywords: Dict[str, List[str]]) -> None:
        """
        Build n-gram centroids synchronously, then upgrade to ST embeddings in background.
        """
        # Phase 1: instant n-gram centroids (no model loading)
        with self._lock:
            self._centroids = self._compute_centroids(self._ngram, domain_keywords)

        # Phase 2: background upgrade to ST embeddings
        def _rebuild_with_st():
            try:
                from cognia.cognia_embedding import text_to_vector_fast
                upgraded = self._compute_centroids(text_to_vector_fast, domain_keywords)
                with self._lock:
                    self._centroids = upgraded
            except Exception:
                pass  # stay with n-gram

        t = _threading.Thread(target=_rebuild_with_st, daemon=True, name="router-st-upgrade")
        t.start()

    def similarities(self, prompt: str) -> Dict[str, float]:
        """Return cosine similarity of prompt embedding to each domain centroid."""
        with self._lock:
            centroids = dict(self._centroids)

        try:
            from cognia.cognia_embedding import text_to_vector_fast
            pv = np.array(text_to_vector_fast(prompt), dtype=np.float32)
        except Exception:
            pv = np.array(self._ngram(prompt), dtype=np.float32)

        norm = np.linalg.norm(pv)
        if norm > 0:
            pv = pv / norm
        return {domain: float(np.dot(pv, c)) for domain, c in centroids.items()}


class GlobalRouter:
    """
    Routes a text prompt to the most appropriate Shattering sub-model.

    Scoring: each keyword hit adds 1 point to that domain.
    Longer phrases are matched before shorter ones to avoid partial overlaps.
    Ties go to the default sub-model (logos).
    Confidence = winner_score / total_score, clamped to [0.3, 1.0].
    """

    def __init__(self, default_submodel: str = "logos"):
        from shattering.model_constants import ROUTER_SEMANTIC_THRESHOLD, ROUTER_SEMANTIC_BLEND
        self.default              = default_submodel
        self._sem_threshold       = ROUTER_SEMANTIC_THRESHOLD
        self._sem_blend           = ROUTER_SEMANTIC_BLEND
        self._patterns: Dict[str, List[re.Pattern]] = {}
        for domain, kws in _DOMAIN_KEYWORDS.items():
            # longer phrases first to avoid sub-word matches
            sorted_kws = sorted(kws, key=len, reverse=True)
            self._patterns[domain] = [
                re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE)
                for kw in sorted_kws
            ]
        self._semantic = _EmbeddingIndex()
        self._semantic.build(_DOMAIN_KEYWORDS)

    def route(self, prompt: str) -> RouteDecision:
        """
        Analyse prompt and return a RouteDecision.
        Only the first 2000 characters are used for routing; longer inputs are
        truncated to avoid O(L x K) regex cost on large documents.

        Scoring: blends keyword heuristics with lightweight character n-gram
        semantic similarity (no external deps, no model loading).
        """
        prompt_trunc = prompt[:2000]

        if not prompt_trunc.strip():
            return RouteDecision(sub_model=self.default, confidence=0.3,
                                 scores={d: 0 for d in _DOMAIN_KEYWORDS},
                                 reason=f"Empty prompt -- defaulting to '{self.default}'")

        # ── Keyword scores ─────────────────────────────────────────────
        kw_scores: Dict[str, int] = {d: 0 for d in _DOMAIN_KEYWORDS}
        for domain, patterns in self._patterns.items():
            for pat in patterns:
                kw_scores[domain] += len(pat.findall(prompt_trunc))
        kw_total = sum(kw_scores.values())

        # ── Semantic scores ────────────────────────────────────────────
        sem_sims = self._semantic.similarities(prompt_trunc)
        # Normalize semantic sims to [0, 1] range (cosine can be negative)
        sem_min = min(sem_sims.values())
        sem_max = max(sem_sims.values())
        sem_range = max(sem_max - sem_min, 1e-6)
        sem_norm: Dict[str, float] = {
            d: (v - sem_min) / sem_range for d, v in sem_sims.items()
        }
        sem_winner    = max(sem_norm, key=lambda d: sem_norm[d])
        sem_max_score = sem_norm[sem_winner]

        # ── Blend keyword + semantic ────────────────────────────────────
        # Keyword ratio: winner share of total hits
        if kw_total > 0:
            kw_winner     = max(kw_scores, key=lambda d: (kw_scores[d], 1 if d == self.default else 0))
            kw_ratio      = kw_scores[kw_winner] / kw_total
        else:
            kw_winner     = self.default
            kw_ratio      = 0.0

        # Blend: if semantic max is above threshold AND keyword is ambiguous, mix.
        # Skip semantic when keyword winner already dominates (ratio >= 0.60)
        # to avoid confusing clear technical queries with lexical overlap in rhetor.
        kw_dominant = kw_total > 0 and kw_ratio >= 0.60
        if sem_max_score >= self._sem_threshold and not kw_dominant:
            blend = self._sem_blend
            # Combine normalized scores
            combined: Dict[str, float] = {
                d: blend * sem_norm[d] + (1 - blend) * (kw_scores[d] / max(kw_total, 1))
                for d in _DOMAIN_KEYWORDS
            }
            winner      = max(combined, key=lambda d: (combined[d], 1 if d == self.default else 0))
            sem_active  = True
        else:
            winner     = kw_winner
            sem_active = False

        # ── Confidence ────────────────────────────────────────────────
        if kw_total == 0 and not sem_active:
            conf   = 0.3
            reason = f"No keyword matches -- defaulting to '{self.default}'"
        else:
            evidence_scale = min(1.0, kw_total / 6.0)
            kw_conf        = kw_ratio * (0.4 + 0.6 * evidence_scale) if kw_total > 0 else 0.3
            if sem_active:
                conf   = min(1.0, max(0.3, 0.5 * kw_conf + 0.5 * sem_max_score))
                reason = (
                    f"'{winner}' kw={kw_scores.get(winner, 0)}/{kw_total} "
                    f"sem={sem_sims[winner]:.2f} ({conf:.0%})"
                )
            else:
                conf   = min(1.0, max(0.3, kw_conf))
                reason = (
                    f"'{winner}' scored {kw_scores.get(winner, 0)}/{kw_total} hits "
                    f"({conf:.0%} confidence)"
                )

        return RouteDecision(
            sub_model  = winner,
            confidence = round(conf, 3),
            scores     = kw_scores,
            reason     = reason,
        )
