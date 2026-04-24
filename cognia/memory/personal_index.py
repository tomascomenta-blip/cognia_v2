"""
cognia/memory/personal_index.py
================================
PersonalIndex -- Fase 6: indice privado de conceptos de alta importancia personal.

Separado del KnowledgeGraph global:
  - NO se comparte en la red mesh ni en la capa publica
  - Persistido en user_profile bajo 'personal_index:{user_id}'
  - Busqueda por resonancia emocional ademas de similitud semantica
"""
from __future__ import annotations
import re, json, time, math
from dataclasses import dataclass, field
from typing import Optional
from logger_config import get_logger
logger = get_logger(__name__)

@dataclass
class PersonalEntry:
    concept:      str
    importance:   float = 0.5
    emotion_tags: list  = field(default_factory=list)
    access_count: int   = 0
    last_access:  float = field(default_factory=time.time)
    note:         str   = ""

    def reinforce(self, delta: float = 0.05, emotions: list = None) -> None:
        self.importance   = min(1.0, self.importance + delta)
        self.access_count += 1
        self.last_access  = time.time()
        if emotions:
            for e in emotions:
                if e and e not in self.emotion_tags:
                    self.emotion_tags.append(e)

    def decay(self, factor: float = 0.98) -> None:
        self.importance = max(0.0, self.importance * factor)

    def to_dict(self) -> dict:
        return {"concept": self.concept, "importance": self.importance,
                "emotion_tags": self.emotion_tags, "access_count": self.access_count,
                "last_access": self.last_access, "note": self.note}

    @classmethod
    def from_dict(cls, d: dict) -> "PersonalEntry":
        return cls(concept=d.get("concept",""), importance=float(d.get("importance",0.5)),
                   emotion_tags=list(d.get("emotion_tags",[])), access_count=int(d.get("access_count",0)),
                   last_access=float(d.get("last_access",time.time())), note=d.get("note",""))


class PersonalIndex:
    MAX_ENTRIES = 500

    def __init__(self, user_id: str = "default"):
        self.user_id   = user_id
        self._entries: dict[str, PersonalEntry] = {}

    def add(self, concept: str, importance: float = 0.5,
            emotions: list = None, note: str = "") -> PersonalEntry:
        concept = concept.strip().lower()
        if not concept:
            raise ValueError("concept no puede ser vacio")
        if concept in self._entries:
            self._entries[concept].reinforce(0.05, emotions or [])
        else:
            if len(self._entries) >= self.MAX_ENTRIES:
                self._evict_weakest()
            self._entries[concept] = PersonalEntry(concept=concept, importance=importance,
                                                    emotion_tags=list(emotions or []), note=note)
        return self._entries[concept]

    def get(self, concept: str) -> Optional[PersonalEntry]:
        concept = concept.strip().lower()
        entry = self._entries.get(concept)
        if entry:
            entry.access_count += 1
            entry.last_access = time.time()
        return entry

    def remove(self, concept: str) -> bool:
        concept = concept.strip().lower()
        if concept in self._entries:
            del self._entries[concept]
            return True
        return False

    def search(self, query: str, top_k: int = 5, emotion_filter: list = None,
               embeddings_fn=None) -> list:
        query_lower = query.strip().lower()
        results = []
        q_vec = None
        if embeddings_fn:
            try: q_vec = embeddings_fn(query_lower)
            except Exception: q_vec = None
        for entry in self._entries.values():
            if emotion_filter and not any(e in entry.emotion_tags for e in emotion_filter):
                continue
            sem = self._semantic_score(query_lower, entry, q_vec, embeddings_fn)
            emo = self._emotion_score(query_lower, entry)
            score = 0.6 * sem + 0.3 * emo + 0.1 * entry.importance
            if score > 0.05:
                results.append((entry, round(score, 4)))
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]

    def _semantic_score(self, query, entry, q_vec, embeddings_fn) -> float:
        if q_vec is not None and embeddings_fn is not None:
            try:
                import numpy as np
                e_vec = embeddings_fn(entry.concept)
                dot = float(np.dot(q_vec, e_vec))
                norm = float(np.linalg.norm(q_vec) * np.linalg.norm(e_vec))
                return dot / norm if norm > 0 else 0.0
            except Exception: pass
        if query in entry.concept or entry.concept in query:
            return 0.8
        q_words = set(query.split())
        c_words = set(entry.concept.split())
        overlap = len(q_words & c_words)
        return overlap / max(len(q_words), len(c_words)) if overlap else 0.0

    def _emotion_score(self, query, entry) -> float:
        if not entry.emotion_tags: return 0.0
        matched = sum(1 for e in entry.emotion_tags if e in query)
        return min(1.0, matched / len(entry.emotion_tags))

    def decay_all(self, factor: float = 0.98) -> None:
        for entry in self._entries.values():
            entry.decay(factor)

    def _evict_weakest(self) -> None:
        now = time.time()
        worst = min(self._entries, key=lambda k: self._entries[k].importance *
                    math.exp(-(now - self._entries[k].last_access) / 86400))
        del self._entries[worst]

    def to_dict(self) -> dict:
        return {"user_id": self.user_id,
                "entries": {k: v.to_dict() for k, v in self._entries.items()}}

    @classmethod
    def from_dict(cls, data: dict) -> "PersonalIndex":
        idx = cls(user_id=data.get("user_id","default"))
        for k, v in data.get("entries", {}).items():
            idx._entries[k] = PersonalEntry.from_dict(v)
        return idx

    def save(self, db_path: str) -> bool:
        import datetime
        key = f"personal_index:{self.user_id}"
        value = json.dumps(self.to_dict())
        now = datetime.datetime.now().isoformat()
        try:
            from storage.db_pool import db_connect_pooled
            conn = db_connect_pooled(db_path)
            conn.execute("""INSERT INTO user_profile (key, value, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
            """, (key, value, now))
            conn.close()
            return True
        except Exception as exc:
            logger.warning("PersonalIndex.save error: %s", exc)
            return False

    @classmethod
    def load(cls, user_id: str, db_path: str) -> "PersonalIndex":
        key = f"personal_index:{user_id}"
        try:
            from storage.db_pool import db_connect_pooled
            conn = db_connect_pooled(db_path)
            row = conn.execute("SELECT value FROM user_profile WHERE key=?", (key,)).fetchone()
            conn.close()
            if row and row[0]:
                return cls.from_dict(json.loads(row[0]))
        except Exception as exc:
            logger.warning("PersonalIndex.load error: %s", exc)
        return cls(user_id=user_id)

    def summary(self) -> dict:
        if not self._entries: return {"total": 0, "top": []}
        top = sorted(self._entries.values(), key=lambda e: e.importance, reverse=True)[:5]
        return {"total": len(self._entries),
                "top": [{"concept": e.concept, "importance": round(e.importance, 3),
                         "emotions": e.emotion_tags} for e in top]}
