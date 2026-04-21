"""
cognia/memory/working.py
========================
Módulo de percepción y memoria de trabajo (buffer de corto plazo).
"""

from datetime import datetime
from typing import List
from ..vectors import text_to_vector, cosine_similarity, analyze_emotion
from ..config import VECTOR_DIM


class PerceptionModule:
    def __init__(self):
        self.dim = VECTOR_DIM

    def encode(self, text: str) -> list:
        return text_to_vector(text)

    def extract_features(self, text: str) -> dict:
        words = text.lower().split()
        emotion = analyze_emotion(text)
        return {
            "length": len(text),
            "word_count": len(words),
            "has_question": "?" in text,
            "has_negation": any(w in words for w in ["no","not","nunca","jamás","sin","never"]),
            "is_correction": any(w in words for w in ["corrección","error","incorrecto","mal","wrong","fix"]),
            "emotion": emotion,
            "words": words,
            "vector": self.encode(text)
        }


class WorkingMemory:
    CAPACITY = 20

    def __init__(self):
        self._buffer: List[dict] = []

    def add(self, observation: str, label: str, vector: list, emotion: dict, confidence: float):
        entry = {
            "observation": observation,
            "label": label,
            "vector": vector,
            "emotion": emotion,
            "confidence": confidence,
            "timestamp": datetime.now().isoformat()
        }
        self._buffer.append(entry)
        if len(self._buffer) > self.CAPACITY:
            self._buffer.pop(0)

    def get_recent(self, n: int = 5) -> list:
        return self._buffer[-n:]

    def get_context_labels(self) -> list:
        return [e["label"] for e in self._buffer if e.get("label")]

    def find_similar_in_buffer(self, vector: list, threshold: float = 0.75) -> list:
        results = []
        for entry in self._buffer:
            sim = cosine_similarity(vector, entry["vector"])
            if sim >= threshold:
                results.append({**entry, "similarity": sim})
        return sorted(results, key=lambda x: x["similarity"], reverse=True)

    def clear(self):
        self._buffer = []
