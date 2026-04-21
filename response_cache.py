"""
response_cache.py — Cognia Language Engine
==========================================
Cache semántico de respuestas previas.

PASO 1: Logging estructurado — eliminados todos los except: pass
"""

import time
import json
import math
import sqlite3
import threading
from dataclasses import dataclass, field
from collections import OrderedDict
from typing import Optional, List, Dict

from logger_config import get_logger, log_db_error, log_slow, safe_execute

logger = get_logger(__name__)

# ── Configuración ─────────────────────────────────────────────────────
CACHE_MAX_RAM      = 200
CACHE_SIMILARITY   = 0.88
CACHE_TTL_DEFAULT  = 3600 * 6
CACHE_TTL_FACTUAL  = 3600 * 48
CACHE_TTL_CREATIVE = 1800


@dataclass
class CacheEntry:
    question:   str
    response:   str
    vector:     List[float]
    concept:    Optional[str]
    confidence: float
    used_llm:   bool
    timestamp:  float = field(default_factory=time.time)
    hits:       int   = 0
    ttl:        float = CACHE_TTL_DEFAULT

    def is_expired(self) -> bool:
        return (time.time() - self.timestamp) > self.ttl

    def to_dict(self) -> dict:
        return {
            "question":   self.question,
            "response":   self.response,
            "vector":     self.vector,
            "concept":    self.concept,
            "confidence": self.confidence,
            "used_llm":   self.used_llm,
            "timestamp":  self.timestamp,
            "hits":       self.hits,
            "ttl":        self.ttl,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CacheEntry":
        return cls(**d)


def _cosine(a: List[float], b: List[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na  = math.sqrt(sum(x * x for x in a))
    nb  = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return max(-1.0, min(1.0, dot / (na * nb)))


class ResponseCache:
    """Caché semántico de dos capas: RAM (rápido) + SQLite (persistente)."""

    def __init__(self, db_path: str = "cognia_memory.db"):
        self._db_path  = db_path
        self._ram: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock     = threading.RLock()
        self._hits     = 0
        self._misses   = 0
        self._init_db()

    # ── API pública ────────────────────────────────────────────────────

    def get(self, question: str, vector: List[float]) -> Optional[CacheEntry]:
        hit = self._search_ram(vector)
        if hit:
            with self._lock:
                hit.hits += 1
            self._hits += 1
            logger.debug(
                "Cache RAM hit",
                extra={"op": "cache.get", "context": f"question_len={len(question)} hits={hit.hits}"},
            )
            return hit

        hit = self._search_db(vector)
        if hit:
            self._promote_to_ram(hit)
            self._hits += 1
            logger.debug(
                "Cache DB hit (promovido a RAM)",
                extra={"op": "cache.get", "context": f"question_len={len(question)}"},
            )
            return hit

        self._misses += 1
        return None

    def store(self, question: str, response: str, vector: List[float],
              concept: Optional[str] = None, confidence: float = 0.5,
              used_llm: bool = True) -> CacheEntry:
        ttl = CACHE_TTL_CREATIVE if used_llm else (
              CACHE_TTL_FACTUAL  if confidence >= 0.75 else CACHE_TTL_DEFAULT)

        entry = CacheEntry(
            question   = question[:500],
            response   = response[:2000],
            vector     = vector,
            concept    = concept,
            confidence = confidence,
            used_llm   = used_llm,
            ttl        = ttl,
        )
        self._add_to_ram(entry)
        self._persist_to_db(entry)
        logger.debug(
            "Entrada guardada en caché",
            extra={"op": "cache.store", "context": f"concept={concept} confidence={confidence:.2f} used_llm={used_llm}"},
        )
        return entry

    def invalidate_concept(self, concept: str) -> int:
        n = 0
        with self._lock:
            keys_to_del = [k for k, v in self._ram.items()
                           if v.concept == concept]
            for k in keys_to_del:
                del self._ram[k]
                n += 1
        n += self._db_delete_concept(concept)
        logger.info(
            f"Caché invalidado para concepto '{concept}'",
            extra={"op": "cache.invalidate_concept",
                   "context": f"entries_removed={n}"},
        )
        return n

    def clear_expired(self) -> int:
        n = 0
        with self._lock:
            keys = [k for k, v in self._ram.items() if v.is_expired()]
            for k in keys:
                del self._ram[k]
                n += 1
        n += self._db_clear_expired()
        logger.info(
            f"Entradas expiradas eliminadas: {n}",
            extra={"op": "cache.clear_expired", "context": f"count={n}"},
        )
        return n

    @property
    def hit_rate(self) -> float:
        total = self._hits + self._misses
        return self._hits / total if total > 0 else 0.0

    def stats(self) -> Dict:
        with self._lock:
            ram_size = len(self._ram)
        return {
            "ram_entries": ram_size,
            "hits":        self._hits,
            "misses":      self._misses,
            "hit_rate":    round(self.hit_rate, 3),
        }

    # ── Internos: RAM ──────────────────────────────────────────────────

    def _search_ram(self, vector: List[float]) -> Optional[CacheEntry]:
        with self._lock:
            best_sim   = 0.0
            best_entry = None
            for entry in self._ram.values():
                if entry.is_expired():
                    continue
                try:
                    sim = _cosine(vector, entry.vector)
                except Exception as exc:
                    logger.warning(
                        "Error calculando similitud coseno en RAM",
                        extra={"op": "cache._search_ram",
                               "context": f"vec_len={len(vector)} err={exc}"},
                    )
                    continue
                if sim > best_sim and sim >= CACHE_SIMILARITY:
                    best_sim   = sim
                    best_entry = entry
            if best_entry:
                self._ram.move_to_end(id(best_entry).__str__())
            return best_entry

    def _add_to_ram(self, entry: CacheEntry):
        with self._lock:
            key = f"{entry.timestamp}_{id(entry)}"
            self._ram[key] = entry
            while len(self._ram) > CACHE_MAX_RAM:
                self._ram.popitem(last=False)

    def _promote_to_ram(self, entry: CacheEntry):
        self._add_to_ram(entry)

    # ── Internos: SQLite ───────────────────────────────────────────────

    def _init_db(self):
        try:
            conn = sqlite3.connect(self._db_path)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS response_cache (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    question   TEXT NOT NULL,
                    response   TEXT NOT NULL,
                    vector     TEXT NOT NULL,
                    concept    TEXT,
                    confidence REAL DEFAULT 0.5,
                    used_llm   INTEGER DEFAULT 1,
                    timestamp  REAL NOT NULL,
                    hits       INTEGER DEFAULT 0,
                    ttl        REAL DEFAULT 21600
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_rc_concept ON response_cache(concept)"
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            # Aquí sí es error porque sin DB el caché persistente no funciona
            log_db_error(logger, "cache._init_db", exc,
                         extra_ctx=f"db_path={self._db_path}")

    def _search_db(self, vector: List[float]) -> Optional[CacheEntry]:
        t0 = time.perf_counter()
        try:
            conn = sqlite3.connect(self._db_path)
            conn.text_factory = str
            now  = time.time()
            rows = conn.execute("""
                SELECT question, response, vector, concept, confidence,
                       used_llm, timestamp, hits, ttl
                FROM response_cache
                WHERE (? - timestamp) < ttl
                ORDER BY timestamp DESC LIMIT 100
            """, (now,)).fetchall()
            conn.close()
        except Exception as exc:
            log_db_error(logger, "cache._search_db", exc)
            return None

        best_sim   = 0.0
        best_entry = None
        for row in rows:
            try:
                row_vec = json.loads(row[2])
                sim = _cosine(vector, row_vec)
                if sim > best_sim and sim >= CACHE_SIMILARITY:
                    best_sim = sim
                    best_entry = CacheEntry(
                        question   = row[0],
                        response   = row[1],
                        vector     = row_vec,
                        concept    = row[3],
                        confidence = row[4],
                        used_llm   = bool(row[5]),
                        timestamp  = row[6],
                        hits       = row[7],
                        ttl        = row[8],
                    )
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                logger.warning(
                    "Fila de caché DB corrupta, ignorando",
                    extra={"op": "cache._search_db",
                           "context": f"row_preview={str(row[0])[:40]} err={exc}"},
                )
                continue

        log_slow(logger, "cache._search_db", t0, threshold_ms=100)
        return best_entry

    def _persist_to_db(self, entry: CacheEntry):
        try:
            conn = sqlite3.connect(self._db_path)
            conn.execute("""
                INSERT INTO response_cache
                (question, response, vector, concept, confidence,
                 used_llm, timestamp, hits, ttl)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (
                entry.question, entry.response,
                json.dumps(entry.vector[:64]),
                entry.concept, entry.confidence,
                int(entry.used_llm), entry.timestamp,
                entry.hits, entry.ttl,
            ))
            conn.commit()
            conn.close()
        except Exception as exc:
            log_db_error(logger, "cache._persist_to_db", exc,
                         extra_ctx=f"concept={entry.concept} confidence={entry.confidence:.2f}")

    def _db_delete_concept(self, concept: str) -> int:
        try:
            conn = sqlite3.connect(self._db_path)
            conn.execute("DELETE FROM response_cache WHERE concept=?", (concept,))
            n = conn.total_changes
            conn.commit()
            conn.close()
            return n
        except Exception as exc:
            log_db_error(logger, "cache._db_delete_concept", exc,
                         extra_ctx=f"concept={concept}")
            return 0

    def _db_clear_expired(self) -> int:
        try:
            conn = sqlite3.connect(self._db_path)
            conn.execute(
                "DELETE FROM response_cache WHERE (? - timestamp) >= ttl",
                (time.time(),)
            )
            n = conn.total_changes
            conn.commit()
            conn.close()
            return n
        except Exception as exc:
            log_db_error(logger, "cache._db_clear_expired", exc)
            return 0
