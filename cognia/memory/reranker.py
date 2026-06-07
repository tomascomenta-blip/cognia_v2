"""
cognia/memory/reranker.py
=========================
Retrieval re-ranker for the HYDRA GLOBAL band (whitepaper section 5.3 +
section 12: "retrieval/consolidation quality is what fails first at scale").

The GLOBAL band fuses two heterogeneous memory sources -- EPISODIC (concrete
past experiences) and SEMANTIC (abstracted concepts). Previously the band just
concatenated episodic top-3 + semantic top-3 with no fusion: a low-similarity
episodic hit could outrank a high-similarity semantic hit purely by ordering,
duplicates from the two stores were emitted twice, and neither recency nor
importance influenced the final ranking.

This module implements a real, deterministic, offline re-ranker that:
  - maps both sources onto a single RankedItem schema using their REAL fields,
  - scores each candidate by a weighted fusion of similarity + recency +
    importance (Chimera 5.3 ranking terms),
  - deduplicates by normalized label text (keeping the higher score),
  - returns the global top-k sorted by fused score.

It never raises: missing keys fall back to documented neutral defaults so an
empty or partially-populated store degrades gracefully instead of crashing the
GLOBAL band.

REAL fields this re-ranker adapts to (read from the live code, NOT assumed):
  episodic (EpisodicMemory.retrieve_similar / VectorCache.search items):
      "label", "observation", "similarity", "confidence", "score",
      "importance" (present only in the slow path / cache meta; absent in the
      returned dict, so we read it defensively and default it), NO timestamp
      field is exposed in the returned item -> recency defaults to neutral.
  semantic (SemanticMemory.find_related items):
      "concept", "similarity", "confidence", "emotion_avg". NO importance and
      NO timestamp -> importance falls back to confidence, recency to neutral.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional


# -- Fusion weights -------------------------------------------------------
# WHY these values: similarity is the primary relevance signal, so it carries
# the majority of the weight. Recency and importance are secondary re-ranking
# corrections (Chimera 5.3): a slightly-less-similar but very recent or very
# important memory can be promoted, but cannot dominate a clearly-more-similar
# one. Weights sum to 1.0 so the fused score stays in [0, 1] when each term is
# in [0, 1].
W_SIM = 0.6
W_RECENCY = 0.2
W_IMPORTANCE = 0.2

# WHY: episodic "importance" is stored on a 0..3 scale (EpisodicMemory.store
# caps final_importance at 3.0). To normalize into 0..1 we divide by this cap.
_IMPORTANCE_MAX = 3.0

# WHY: with no timestamp available we cannot compute true decay, so we emit a
# neutral midpoint -- neither boosting nor penalizing -- per the spec.
_NEUTRAL_RECENCY = 0.5

# WHY: recency decays linearly to 0 over this horizon. ~30 days matches the
# longest spaced-repetition review interval used by episodic memory, so a
# memory older than a review cycle contributes no recency boost.
_RECENCY_HORIZON_HOURS = 30.0 * 24.0


@dataclass
class RankedItem:
    source: str          # "episodic" or "semantic"
    label: str
    similarity: float
    recency: float       # 0..1
    importance: float    # 0..1
    score: float


def _clamp01(value: float) -> float:
    """Clamp to [0, 1]. WHY: semantic cosine similarity can be negative; the
    fused score must stay in a comparable, well-defined range."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    if v < 0.0:
        return 0.0
    if v > 1.0:
        return 1.0
    return v


def _recency_score(timestamp_iso_or_none: Optional[str]) -> float:
    """
    Map an ISO timestamp to a recency score in [0, 1]: 1.0 for "just now",
    decaying linearly toward 0.0 at _RECENCY_HORIZON_HOURS old.

    WHY: recent memories are more relevant to the current turn (Chimera 5.3
    recency term). Parsing is fully defensive -- any malformed or missing
    timestamp yields the neutral midpoint and never raises.
    """
    if not timestamp_iso_or_none:
        return _NEUTRAL_RECENCY
    try:
        ts = datetime.fromisoformat(str(timestamp_iso_or_none))
    except (ValueError, TypeError):
        return _NEUTRAL_RECENCY
    try:
        age_seconds = (datetime.now() - ts).total_seconds()
    except (ValueError, TypeError, OverflowError):
        return _NEUTRAL_RECENCY
    # Future timestamps clamp to "most recent".
    if age_seconds <= 0:
        return 1.0
    age_hours = age_seconds / 3600.0
    if age_hours >= _RECENCY_HORIZON_HOURS:
        return 0.0
    return 1.0 - (age_hours / _RECENCY_HORIZON_HOURS)


def _first_present(item: dict, keys, default):
    """Return item[k] for the first key present with a non-None value, else
    default. WHY: the two stores expose different field names for the same
    concept (e.g. timestamp vs last_access); tolerate all real variants."""
    for k in keys:
        if k in item and item[k] is not None:
            return item[k]
    return default


def _episodic_to_ranked(item: dict) -> Optional[RankedItem]:
    label = _first_present(item, ("label", "observation"), "")
    label = str(label).strip()
    if not label:
        return None

    similarity = _first_present(item, ("similarity", "score"), 0.0)
    sim_norm = _clamp01(similarity)

    # WHY: importance is stored 0..3; normalize by the cap. It is absent from
    # the returned dict on the fast path, so default to a neutral 1.0 (the
    # store() default) before normalizing -> 1.0/3.0.
    raw_importance = _first_present(item, ("importance",), 1.0)
    try:
        importance = _clamp01(float(raw_importance) / _IMPORTANCE_MAX)
    except (TypeError, ValueError):
        importance = _clamp01(1.0 / _IMPORTANCE_MAX)

    # WHY: episodic items returned by retrieve_similar expose no timestamp, but
    # other episodic paths (get_in_window) carry "timestamp"/"last_access".
    # Read whichever is present, else neutral.
    ts = _first_present(item, ("timestamp", "last_access", "last_accessed"), None)
    recency = _recency_score(ts)

    score = W_SIM * sim_norm + W_RECENCY * recency + W_IMPORTANCE * importance
    return RankedItem(
        source="episodic",
        label=label,
        similarity=float(similarity) if _is_number(similarity) else 0.0,
        recency=recency,
        importance=importance,
        score=score,
    )


def _semantic_to_ranked(item: dict) -> Optional[RankedItem]:
    label = _first_present(item, ("concept", "label"), "")
    label = str(label).strip()
    if not label:
        return None

    similarity = _first_present(item, ("similarity", "score"), 0.0)
    sim_norm = _clamp01(similarity)

    # WHY: semantic items have no importance field. Use confidence (or support)
    # as a proxy for how well-established the concept is; default neutral 0.5.
    raw_importance = _first_present(item, ("confidence", "support"), 0.5)
    importance = _clamp01(raw_importance)

    # WHY: semantic items expose no per-result timestamp (last_updated lives in
    # the store, not the find_related result) -> neutral recency.
    ts = _first_present(item, ("last_updated", "timestamp"), None)
    recency = _recency_score(ts)

    score = W_SIM * sim_norm + W_RECENCY * recency + W_IMPORTANCE * importance
    return RankedItem(
        source="semantic",
        label=label,
        similarity=float(similarity) if _is_number(similarity) else 0.0,
        recency=recency,
        importance=importance,
        score=score,
    )


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _norm_label(label: str) -> str:
    """Normalize label text for dedup: lowercased, whitespace-collapsed, ASCII.
    WHY: the same memory can surface from both stores or with cosmetic
    differences; dedup must compare on stable, case-insensitive text."""
    text = " ".join(str(label).split()).strip().lower()
    return text.encode("ascii", "replace").decode("ascii")


def rerank(episodic_items: List[dict],
           semantic_items: List[dict],
           top_k: int = 5) -> List[RankedItem]:
    """
    Fuse episodic + semantic candidates into a single re-ranked top-k.

    Never raises: bad/missing items are skipped, missing keys use documented
    neutral defaults.
    """
    ranked: List[RankedItem] = []

    for raw in (episodic_items or []):
        if not isinstance(raw, dict):
            continue
        try:
            item = _episodic_to_ranked(raw)
        except Exception:
            item = None
        if item is not None:
            ranked.append(item)

    for raw in (semantic_items or []):
        if not isinstance(raw, dict):
            continue
        try:
            item = _semantic_to_ranked(raw)
        except Exception:
            item = None
        if item is not None:
            ranked.append(item)

    # Deduplicate by normalized label, keeping the higher-scoring item.
    best_by_label: dict = {}
    for item in ranked:
        key = _norm_label(item.label)
        if not key:
            continue
        prev = best_by_label.get(key)
        if prev is None or item.score > prev.score:
            best_by_label[key] = item

    deduped = list(best_by_label.values())
    # Sort by fused score desc; tie-break on similarity then label for
    # determinism (stable, reproducible output for the same store state).
    deduped.sort(key=lambda r: (r.score, r.similarity, r.label), reverse=True)

    try:
        k = int(top_k)
    except (TypeError, ValueError):
        k = 5
    if k < 0:
        k = 0
    return deduped[:k]


def format_ranked(items: List[RankedItem]) -> List[str]:
    """
    Render RankedItems as ASCII strings for the GLOBAL band, e.g.:
        "episodic[score=0.72 sim=0.40 rec=0.90 imp=0.50]: <label>"
    """
    out: List[str] = []
    for it in (items or []):
        try:
            label = " ".join(str(it.label).split()).strip()
            line = "%s[score=%.2f sim=%.2f rec=%.2f imp=%.2f]: %s" % (
                it.source, it.score, it.similarity, it.recency,
                it.importance, label,
            )
            out.append(line.encode("ascii", "replace").decode("ascii"))
        except Exception:
            continue
    return out
