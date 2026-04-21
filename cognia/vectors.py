"""
cognia/vectors.py
=================
Utilidades de vectores, similitud coseno y análisis emocional ligero.
"""

import math
from .config import (
    VECTOR_DIM, _FATIGUE_MONITOR, HAS_FATIGUE,
    POSITIVE_WORDS, NEGATIVE_WORDS,
)
from cognia_embedding import text_to_vector_fast


# ── Operaciones vectoriales ────────────────────────────────────────────

def vec_dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def vec_norm(a):
    return math.sqrt(sum(x * x for x in a))


def cosine_similarity(a, b) -> float:
    if len(a) != len(b):
        return 0.0
    dot = vec_dot(a, b)
    na, nb = vec_norm(a), vec_norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return max(-1.0, min(1.0, dot / (na * nb)))


def text_to_vector(text: str, dim: int = VECTOR_DIM) -> list:
    """Wrapper thread-safe con lazy model, batching y LRU O(1)."""
    return text_to_vector_fast(
        text,
        dim=dim,
        fatigue_monitor=_FATIGUE_MONITOR if HAS_FATIGUE else None,
    )


# ── Análisis emocional ligero ──────────────────────────────────────────

def analyze_emotion(text: str) -> dict:
    words = set(text.lower().split())
    pos = len(words & POSITIVE_WORDS)
    neg = len(words & NEGATIVE_WORDS)
    exclamations = text.count("!")
    score = (pos - neg) / max(1, pos + neg + 1)
    score += exclamations * 0.1
    intensity = (pos + neg + exclamations) / max(1, len(words))
    if score > 0.2:
        label = "positivo"
    elif score < -0.2:
        label = "negativo"
    else:
        label = "neutral"
    return {
        "score": round(score, 3),
        "label": label,
        "intensity": round(min(1.0, intensity), 3)
    }
