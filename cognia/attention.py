"""
cognia/attention.py
====================
Sistema de atención ponderada para priorizar memorias relevantes.

Fórmula:
  attention_score =
    w_sem  * similitud_semántica   (0.40)
    w_emo  * emoción               (0.25)
    w_rec  * recencia              (0.20)
    w_freq * frecuencia            (0.15)
"""

import math
from datetime import datetime


class AttentionSystem:

    def __init__(self,
                 w_semantic: float = 0.40,
                 w_emotion: float = 0.25,
                 w_recency: float = 0.20,
                 w_frequency: float = 0.15,
                 threshold: float = 0.25):
        self.threshold = threshold
        total = w_semantic + w_emotion + w_recency + w_frequency
        self.w_semantic  = w_semantic  / total
        self.w_emotion   = w_emotion   / total
        self.w_recency   = w_recency   / total
        self.w_frequency = w_frequency / total

    def score(self, episode: dict, query_vector: list,
              current_time: float = None) -> float:
        if current_time is None:
            current_time = __import__("time").time()

        sem_score = max(0.0, episode.get("similarity", 0.0))

        emo_data = episode.get("emotion", {})
        emo_score = (abs(emo_data.get("score", 0.0)) if isinstance(emo_data, dict)
                     else abs(episode.get("emotion_score", 0.0)))

        try:
            last_access_str = episode.get("last_access", datetime.now().isoformat())
            last_dt = datetime.fromisoformat(last_access_str)
            hours_ago = (datetime.now() - last_dt).total_seconds() / 3600
            recency_score = math.exp(-0.1 * hours_ago)
        except Exception:
            recency_score = 0.5

        access_count = episode.get("access_count", 1)
        freq_score = math.log(1 + access_count) / math.log(1 + 100)

        attention = (
            self.w_semantic  * sem_score +
            self.w_emotion   * emo_score +
            self.w_recency   * recency_score +
            self.w_frequency * freq_score
        )

        importance = episode.get("importance", 1.0)
        attention *= min(1.5, importance)

        return round(min(1.0, attention), 4)

    def filter_memories(self, episodes: list, query_vector: list) -> list:
        # FIX: calcular current_time UNA vez para todos los episodios
        # Antes: time.time() se llamaba N veces dentro de score()
        import time as _t
        _now = _t.time()
        scored = [{**ep, "attention_score": self.score(ep, query_vector, current_time=_now)}
                  for ep in episodes]
        filtered = [ep for ep in scored if ep["attention_score"] >= self.threshold]
        filtered.sort(key=lambda x: x["attention_score"], reverse=True)
        return filtered

    def explain_attention(self, episode: dict, query_vector: list) -> str:
        sem = max(0.0, episode.get("similarity", 0.0))
        emo_data = episode.get("emotion", {})
        emo = abs(emo_data.get("score", 0.0)) if isinstance(emo_data, dict) else 0.0

        try:
            last_dt = datetime.fromisoformat(episode.get("last_access", datetime.now().isoformat()))
            hours = (datetime.now() - last_dt).total_seconds() / 3600
            rec = math.exp(-0.1 * hours)
        except Exception:
            rec = 0.5

        freq = math.log(1 + episode.get("access_count", 1)) / math.log(101)
        total = self.score(episode, query_vector)

        return (f"Atención {total:.2f}: "
                f"semántica={sem:.2f}×{self.w_semantic:.2f} + "
                f"emoción={emo:.2f}×{self.w_emotion:.2f} + "
                f"recencia={rec:.2f}×{self.w_recency:.2f} + "
                f"frecuencia={freq:.2f}×{self.w_frequency:.2f}")
