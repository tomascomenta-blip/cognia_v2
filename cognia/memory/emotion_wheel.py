"""
cognia/memory/emotion_wheel.py
Plutchik emotion wheel processor for the sleep cycle.

Analyzes the emotional pattern accumulated in episodic memory during the last N hours,
detects imbalances, and modulates episode importance to prevent rumination loops and
reinforce positive-valence learning signals.
"""

import time
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from storage.db_pool import db_connect_pooled as db_connect
from logger_config import get_logger

logger = get_logger(__name__)

# Eight Plutchik primaries: valence, opposite, adjacent pair
_PLUTCHIK: Dict[str, dict] = {
    "joy":          {"valence":  1, "opposite": "sadness",      "adjacent": ("trust", "anticipation")},
    "trust":        {"valence":  1, "opposite": "disgust",      "adjacent": ("joy", "fear")},
    "fear":         {"valence": -1, "opposite": "anger",        "adjacent": ("trust", "surprise")},
    "surprise":     {"valence":  0, "opposite": "anticipation", "adjacent": ("fear", "sadness")},
    "sadness":      {"valence": -1, "opposite": "joy",          "adjacent": ("surprise", "disgust")},
    "disgust":      {"valence": -1, "opposite": "trust",        "adjacent": ("sadness", "anger")},
    "anger":        {"valence": -1, "opposite": "fear",         "adjacent": ("disgust", "anticipation")},
    "anticipation": {"valence":  1, "opposite": "surprise",     "adjacent": ("anger", "joy")},
}

# Normalize DB emotion_label values to Plutchik primaries
_LABEL_MAP: Dict[str, Optional[str]] = {
    "neutral":       None,
    "positive":      "joy",
    "negative":      "sadness",
    "joy":           "joy",
    "happiness":     "joy",
    "felicidad":     "joy",
    "alegria":       "joy",
    "alegría":       "joy",
    "trust":         "trust",
    "confianza":     "trust",
    "fear":          "fear",
    "miedo":         "fear",
    "surprise":      "surprise",
    "sorpresa":      "surprise",
    "sadness":       "sadness",
    "tristeza":      "sadness",
    "disgust":       "disgust",
    "disgusto":      "disgust",
    "asco":          "disgust",
    "anger":         "anger",
    "enojo":         "anger",
    "ira":           "anger",
    "anticipation":  "anticipation",
    "anticipacion":  "anticipation",
    "anticipación":  "anticipation",
}

# Minimum distribution share to declare a dominant emotion
_DOMINANCE_THRESHOLD = 0.15

# Modulation factors for importance adjustment
_BOOST_FACTOR = 1.08   # positive dominant → reinforce
_DAMPEN_FACTOR = 0.92  # negative dominant → anti-rumination


@dataclass
class EmotionReport:
    dominant: Optional[str]          # leading Plutchik primary, or None if diffuse
    intensity: float                 # average |emotion_score| over processed episodes
    distribution: Dict[str, float]  # {primary: normalized_weight}, only non-zero keys
    imbalance: Optional[str]         # e.g. "high_sadness_low_joy", or None
    episodes_processed: int
    importance_modulated: int        # count of episodes whose importance was adjusted
    elapsed_ms: int


class EmotionWheelProcessor:
    """
    Runs once per sleep cycle. Reads recent episodes, computes the Plutchik
    distribution, detects imbalances, and modulates episode importance.

    Bounded by: hours param (default 24h) and LIMIT 500 on the DB query.
    No LLM calls — pure arithmetic.
    """

    def __init__(self, db_path: str):
        self._db = db_path

    def process(self, hours: float = 24.0) -> EmotionReport:
        t0 = time.perf_counter()
        since = (datetime.now() - timedelta(hours=hours)).isoformat()

        rows = self._fetch(since)
        if not rows:
            return EmotionReport(
                dominant=None, intensity=0.0, distribution={}, imbalance=None,
                episodes_processed=0, importance_modulated=0,
                elapsed_ms=int((time.perf_counter() - t0) * 1000),
            )

        acc: Dict[str, float] = {k: 0.0 for k in _PLUTCHIK}
        total_weight = 0.0
        total_intensity = 0.0

        for _ep_id, emo_score, emo_label, importance in rows:
            primary = _LABEL_MAP.get((emo_label or "neutral").lower())
            if primary is None:
                continue
            weight = abs(float(emo_score)) * max(0.1, float(importance))
            acc[primary] += weight
            total_weight += weight
            total_intensity += abs(float(emo_score))

        if total_weight > 0:
            for k in acc:
                acc[k] /= total_weight

        intensity = min(1.0, total_intensity / max(1, len(rows)))
        dominant = _dominant(acc)
        imbalance = _detect_imbalance(acc, dominant)
        modulated = self._modulate(rows, acc, dominant)

        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        return EmotionReport(
            dominant=dominant,
            intensity=round(intensity, 3),
            distribution={k: round(v, 3) for k, v in acc.items() if v > 0.001},
            imbalance=imbalance,
            episodes_processed=len(rows),
            importance_modulated=modulated,
            elapsed_ms=elapsed_ms,
        )

    def _fetch(self, since: str) -> list:
        try:
            conn = db_connect(self._db)
            c = conn.cursor()
            c.execute("""
                SELECT id, emotion_score, emotion_label, importance
                FROM episodic_memory
                WHERE forgotten = 0 AND timestamp >= ?
                ORDER BY importance DESC
                LIMIT 500
            """, (since,))
            rows = c.fetchall()
            conn.close()
            return rows
        except Exception as exc:
            logger.warning("emotion_wheel: fetch failed: %s", exc)
            return []

    def _modulate(
        self,
        rows: list,
        dist: Dict[str, float],
        dominant: Optional[str],
    ) -> int:
        if dominant is None or dist.get(dominant, 0) < _DOMINANCE_THRESHOLD:
            return 0
        valence = _PLUTCHIK[dominant]["valence"]
        if valence == 0:
            return 0

        factor = _BOOST_FACTOR if valence > 0 else _DAMPEN_FACTOR
        targets = [
            (ep_id, float(imp))
            for ep_id, _score, label, imp in rows
            if _LABEL_MAP.get((label or "neutral").lower()) == dominant
        ]
        if not targets:
            return 0

        updated = 0
        try:
            conn = db_connect(self._db)
            c = conn.cursor()
            for ep_id, imp in targets:
                new_imp = max(0.1, min(3.0, imp * factor))
                if abs(new_imp - imp) > 0.001:
                    c.execute(
                        "UPDATE episodic_memory SET importance = ? WHERE id = ?",
                        (new_imp, ep_id),
                    )
                    updated += 1
            conn.commit()
            conn.close()
        except Exception as exc:
            logger.warning("emotion_wheel: modulate failed: %s", exc)
        return updated


# ── Pure functions ────────────────────────────────────────────────────────────

def _dominant(dist: Dict[str, float]) -> Optional[str]:
    if not dist:
        return None
    top = max(dist, key=dist.get)
    return top if dist[top] >= _DOMINANCE_THRESHOLD else None


def _detect_imbalance(
    dist: Dict[str, float],
    dominant: Optional[str],
) -> Optional[str]:
    if dominant is None:
        return None
    data = _PLUTCHIK[dominant]
    valence = data["valence"]
    opposite = data["opposite"]

    # Strongly negative dominant with weak positive opposite
    if valence < 0 and dist.get(dominant, 0) > 0.35:
        if dist.get(opposite, 0) < 0.10:
            return f"high_{dominant}_low_{opposite}"

    # Combined joy+trust > 70% of weight (positive echo chamber)
    if dist.get("joy", 0) + dist.get("trust", 0) > 0.70:
        return "excess_positive_bias"

    return None
