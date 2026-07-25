"""
cognia/memory/episodic_fast.py
==============================
Parche de velocidad para EpisodicMemory.retrieve_similar

PROBLEMA ORIGINAL:
  - Carga 7000+ vectores desde SQLite en cada consulta
  - json.loads() por cada fila
  - cosine_similarity() en Python puro (loop)
  Resultado: 2000-3000ms por búsqueda

SOLUCIÓN:
  - VectorCache: carga todos los vectores en numpy una sola vez
  - Búsqueda matricial: dot product batch en ~2ms
  - Invalidación automática cuando se agregan episodios nuevos
  - Zero dependencias nuevas (solo numpy, ya instalado)

USO:
  Reemplaza retrieve_similar en EpisodicMemory automáticamente.
  Solo importar este módulo activa el parche.
"""

import json
import threading
import time
import numpy as np
from datetime import datetime
from typing import Optional

from storage.db_pool import db_connect_pooled as db_connect
from ..config import DB_PATH
from ..logger_config import get_logger, log_db_error, log_slow

logger = get_logger(__name__)

DEBOUNCE_S = 3.0   # minimum seconds between cache rebuilds triggered by mark_dirty()


class VectorCache:
    """
    Cache de vectores en memoria como matriz numpy.
    
    Se reconstruye automáticamente cuando la DB crece.
    Búsqueda: ~2ms para 10k vectores vs ~2500ms en Python puro.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._matrix: Optional[np.ndarray] = None  # (N, 384)
        self._meta: list = []        # [{id, observation, label, ...}]
        self._db_count: int = 0      # episodios cuando se construyó el cache
        self._db_hash: int = 0       # hash XOR de últimos 50 ids+importance+confidence
        self._built_at: float = 0.0
        self._dirty: bool = False    # True after mark_dirty(); cleared after rebuild
        self._dirty_since: float = 0.0
        self._faiss_index = None     # IndexFlatIP built by _build_locked() if faiss-cpu installed
        self._lock = threading.RLock()

    def _needs_rebuild(self, current_hash: int) -> bool:
        """Reconstruir si el hash cambió o el cache está vacío."""
        return self._matrix is None or current_hash != self._db_hash

    def _get_db_hash(self) -> int:
        """
        Hash liviano para detectar cambios en importance/confidence.

        Estrategia: XOR de (id ^ timestamp_int) de los últimos 50 episodios
        activos, ordenados por id DESC.  Coste: ~1 query, sin cargar vectores.
        Throttle: máximo 1 vez cada 2 segundos (igual que el COUNT anterior).
        """
        now = time.time()
        if hasattr(self, '_hash_cache_ts') and (now - self._hash_cache_ts) < 2.0:
            return getattr(self, '_hash_cache_val', 0)
        conn = None
        try:
            conn = db_connect(self.db_path)
            rows = conn.execute("""
                SELECT id, COALESCE(importance, 1.0), COALESCE(confidence, 0.5)
                FROM episodic_memory
                WHERE forgotten = 0
                ORDER BY id DESC
                LIMIT 50
            """).fetchall()

            h = 0
            for ep_id, imp, conf in rows:
                # Codificar importance y confidence como enteros escalados
                imp_i  = int(float(imp)  * 1000)
                conf_i = int(float(conf) * 1000)
                h ^= (int(ep_id) * 2654435761) ^ (imp_i * 40503) ^ (conf_i * 6971)
            h ^= len(rows) * 0x9E3779B9  # incorporate count so XOR can't cancel to 0
            h &= 0xFFFFFFFF

            self._hash_cache_ts  = now
            self._hash_cache_val = h
            return h
        except Exception:
            return 0
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    def mark_dirty(self):
        """
        Signal that the DB has new data.  Rebuild is deferred until DEBOUNCE_S
        seconds have elapsed since the first dirty mark — so 200 consecutive
        store() calls during a sleep cycle produce at most 1 rebuild.
        """
        with self._lock:
            if not self._dirty:
                self._dirty_since = time.monotonic()
            self._dirty = True

    def build(self, include_forgotten: bool = False):
        """Carga todos los vectores en memoria como matriz numpy."""
        with self._lock:
            self._build_locked(include_forgotten)

    def _build_locked(self, include_forgotten: bool = False):
        """Must be called with self._lock held."""
        t0 = time.perf_counter()
        cond = "" if include_forgotten else "WHERE forgotten = 0"
        conn = None
        try:
            conn = db_connect(self.db_path)
            rows = conn.execute(f"""
                SELECT id, observation, label, vector, confidence, importance,
                       emotion_score, emotion_label, surprise,
                       COALESCE(feedback_weight, 1.0)
                FROM episodic_memory {cond}
            """).fetchall()
        except Exception as exc:
            if "no such table" in str(exc):
                logger.debug("vector_cache.build: tabla aun no inicializada, cache vacio")
            else:
                log_db_error(logger, "vector_cache.build", exc)
            return
        finally:
            if conn is not None:
                conn.close()

        if not rows:
            self._matrix = np.zeros((0, 384), dtype=np.float32)
            self._meta = []
            self._db_count = 0
            self._max_id_visto = None      # sin base: el proximo va completo
            self._n_hasta_max = 0
            self._built_include_forgotten = include_forgotten
            return

        # Paso 1: detectar la dimension dominante
        from collections import Counter
        dim_counts = Counter()
        parsed_rows = []
        for row in rows:
            try:
                vec = json.loads(row[3])
                dim_counts[len(vec)] += 1
                parsed_rows.append((row, vec))
            except Exception:
                parsed_rows.append((row, None))

        if not dim_counts:
            logger.warning("VectorCache: no hay vectores validos",
                           extra={"op": "vector_cache.build", "context": "empty"})
            return

        dominant_dim = dim_counts.most_common(1)[0][0]
        logger.info(
            f"VectorCache: dimension dominante={dominant_dim} distribucion={dict(dim_counts.most_common(5))}",
            extra={"op": "vector_cache.build", "context": f"dim={dominant_dim}"}
        )

        # Paso 2: construir matriz solo con vectores de dimension dominante
        vectors = []
        meta = []
        skipped = 0
        for row, vec in parsed_rows:
            if vec is None or len(vec) != dominant_dim:
                skipped += 1
                continue
            ep_id, obs, label, vec_str, conf, imp, emo_score, emo_label, surprise, fb_weight = row
            vectors.append(vec)
            meta.append({
                "id": ep_id,
                "observation": obs,
                "label": label,
                "confidence": float(conf or 0.5),
                "importance": float(imp or 1.0),
                "emotion_score": float(emo_score or 0.0),
                "emotion_label": emo_label or "neutral",
                "surprise": float(surprise or 0.0),
                "feedback_weight": float(fb_weight or 1.0),
            })

        if skipped > 0:
            logger.warning(
                f"VectorCache: {skipped} vectores ignorados (dimension != {dominant_dim})",
                extra={"op": "vector_cache.build", "context": f"skipped={skipped}"}
            )

        # Matriz numpy normalizada (para cosine similarity como dot product)
        mat = np.array(vectors, dtype=np.float32)
        norms = np.linalg.norm(mat, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        self._matrix = mat / norms  # vectores unitarios

        # Optional FAISS index for faster ANN search at scale
        self._faiss_index = None
        try:
            import faiss as _faiss
            _fi = _faiss.IndexFlatIP(dominant_dim)
            _fi.add(self._matrix)
            self._faiss_index = _fi
        except Exception:
            pass

        self._meta = meta
        self._db_count = len(rows)
        # Base para los refrescos incrementales: hasta que id llegue este build
        # y cuantas filas activas hay hasta ahi (si ese conteo baja, hubo
        # olvidos/borrados y el incremental se descarta solo).
        try:
            self._max_id_visto = max(int(r[0]) for r in rows)
            self._n_hasta_max = len(rows)
            self._built_include_forgotten = include_forgotten
        except Exception:
            self._max_id_visto = None
        self._db_hash = getattr(self, '_hash_cache_val', 0)
        self._built_at = time.perf_counter()
        # Invalidate throttle so next _get_db_hash() re-queries the DB.
        # Without this, a dirty-triggered build stores a pre-dirty hash,
        # causing an extra rebuild on the next search() call.
        self._hash_cache_ts = 0.0

        elapsed = (time.perf_counter() - t0) * 1000
        logger.info(
            f"VectorCache construido: {len(rows)} vectores en {elapsed:.1f}ms",
            extra={"op": "vector_cache.build", "context": f"n={len(rows)}"}
        )

    # Cuantos episodios recientes refrescan sus escalares (confidence,
    # importance, feedback_weight) en un refresco incremental. Cubre de sobra
    # los 50 que vigila _get_db_hash().
    _RECIENTES_A_REFRESCAR = 200

    def _refresh_locked(self, include_forgotten: bool = False):
        """Pone el cache al dia SIN releer los 65k vectores si solo hubo altas.

        POR QUE: cada mensaje del usuario guarda un episodio -> el hash cambia
        -> se reconstruia la matriz ENTERA. Medido en una sesion real del dueno
        (2026-07-25): "VectorCache construido: 65290 vectores en 5737.8ms" y un
        "Operacion lenta: 5978ms retrieve_similar" en CADA turno. O(n) por
        mensaje, y creciendo.

        Solo se hace incremental cuando es DEMOSTRABLEMENTE seguro: misma
        vista (include_forgotten), matriz ya construida, y el numero de
        episodios activos con id <= max_id_visto sin cambios (si bajo, hubo
        olvidos/borrados y la matriz vieja ya no vale -> build completo).
        Ante cualquier duda o error: build completo."""
        if (self._matrix is None or not self._meta
                or getattr(self, "_max_id_visto", None) is None
                or getattr(self, "_built_include_forgotten", None) != include_forgotten):
            return self._build_locked(include_forgotten)

        max_id = self._max_id_visto
        cond = "" if include_forgotten else "AND forgotten = 0"
        conn = None
        try:
            conn = db_connect(self.db_path)
            (n_viejos,) = conn.execute(
                f"SELECT COUNT(*) FROM episodic_memory WHERE id <= ? {cond}",
                (max_id,)).fetchone()
            if n_viejos != getattr(self, "_n_hasta_max", -1):
                return self._build_locked(include_forgotten)   # cambio lo viejo

            nuevas = conn.execute(f"""
                SELECT id, observation, label, vector, confidence, importance,
                       emotion_score, emotion_label, surprise,
                       COALESCE(feedback_weight, 1.0)
                FROM episodic_memory WHERE id > ? {cond}
            """, (max_id,)).fetchall()

            # escalares recientes: pueden haber cambiado sin alta ninguna
            recientes = conn.execute(f"""
                SELECT id, confidence, importance, COALESCE(feedback_weight, 1.0)
                FROM episodic_memory
                WHERE id > ? {cond}
            """, (max_id - self._RECIENTES_A_REFRESCAR,)).fetchall()
        except Exception as exc:
            log_db_error(logger, "vector_cache.refresh", exc)
            return self._build_locked(include_forgotten)
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

        t0 = time.perf_counter()
        dim = int(self._matrix.shape[1])
        vectores, meta_nueva = [], []
        for row in nuevas:
            try:
                vec = json.loads(row[3])
            except Exception:
                continue
            if len(vec) != dim:          # otra dimension: no entra en la matriz
                continue
            (ep_id, obs, label, _vs, conf, imp,
             emo_score, emo_label, surprise, fb_weight) = row
            vectores.append(vec)
            meta_nueva.append({
                "id": ep_id, "observation": obs, "label": label,
                "confidence": float(conf or 0.5),
                "importance": float(imp or 1.0),
                "emotion_score": float(emo_score or 0.0),
                "emotion_label": emo_label or "neutral",
                "surprise": float(surprise or 0.0),
                "feedback_weight": float(fb_weight or 1.0),
            })

        if vectores:
            mat = np.array(vectores, dtype=np.float32)
            norms = np.linalg.norm(mat, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            mat = mat / norms
            self._matrix = np.vstack([self._matrix, mat])
            self._meta.extend(meta_nueva)
            if self._faiss_index is not None:
                try:
                    self._faiss_index.add(mat)      # FAISS anade incremental
                except Exception:
                    self._faiss_index = None        # se recreara en el proximo build

        if recientes:
            pos = {m["id"]: i for i, m in enumerate(self._meta)}
            for ep_id, conf, imp, fb in recientes:
                i = pos.get(ep_id)
                if i is not None:
                    self._meta[i]["confidence"] = float(conf or 0.5)
                    self._meta[i]["importance"] = float(imp or 1.0)
                    self._meta[i]["feedback_weight"] = float(fb or 1.0)

        if nuevas:
            self._max_id_visto = max(int(r[0]) for r in nuevas)
            self._n_hasta_max = n_viejos + len(nuevas)
        self._db_count = len(self._meta)
        self._db_hash = self._get_db_hash()
        self._hash_cache_ts = 0.0
        logger.info(
            f"VectorCache incremental: +{len(vectores)} vectores "
            f"(total {len(self._meta)}) en {(time.perf_counter()-t0)*1000:.1f}ms",
            extra={"op": "vector_cache.refresh", "context": f"n={len(self._meta)}"}
        )

    def search(self, query_vector: list, top_k: int = 5,
               include_forgotten: bool = False) -> list:
        """
        Búsqueda vectorial matricial.
        ~2ms para 7000 vectores vs ~2500ms en Python puro.
        """
        with self._lock:
            # Dirty flag takes priority; debounce delays rebuild during burst stores
            now = time.monotonic()
            if self._dirty:
                if (now - self._dirty_since) >= DEBOUNCE_S or self._matrix is None:
                    self._refresh_locked(include_forgotten)
                    self._dirty = False
                # else: debounce window — search stale matrix
            else:
                current_hash = self._get_db_hash()
                if self._needs_rebuild(current_hash):
                    self._refresh_locked(include_forgotten)

            if self._matrix is None or len(self._meta) == 0:
                return []

            # Query vector normalizado
            if query_vector is None:
                return []
            try:
                qv = np.array(query_vector, dtype=np.float32)
            except (TypeError, ValueError):
                return []
            if qv.ndim != 1 or qv.shape[0] == 0:
                return []
            import math as _math
            qnorm = float(np.linalg.norm(qv))
            if qnorm == 0 or not _math.isfinite(qnorm):
                return []
            qv = qv / qnorm

            # FAISS ANN if installed; fallback to numpy dot product
            fi = self._faiss_index
            if fi is not None:
                n_cands = min(max(top_k * 5, 50), len(self._meta))
                _s, _xi = fi.search(qv.reshape(1, -1), n_cands)
                candidate_pairs = [
                    (int(_xi[0][j]), float(_s[0][j]))
                    for j in range(n_cands) if _xi[0][j] >= 0
                ]
            else:
                _raw = self._matrix @ qv
                candidate_pairs = list(enumerate(_raw.tolist()))

            results = []
            for i, sim in candidate_pairs:
                m = self._meta[i]
                emo_boost = abs(m["emotion_score"]) * 0.1
                fw = m["feedback_weight"]
                fw_factor = 0.70 + 0.30 * fw
                score = (
                    0.55 * float(sim) +
                    0.20 * m["confidence"] +
                    0.15 * min(m["importance"], 2.0) / 2.0 +
                    emo_boost
                ) * fw_factor
                results.append({
                    "id": m["id"],
                    "observation": m["observation"],
                    "label": m["label"],
                    "similarity": float(sim),
                    "confidence": m["confidence"],
                    "score": score,
                    "emotion": {
                        "score": m["emotion_score"],
                        "label": m["emotion_label"]
                    },
                    "surprise": m["surprise"],
                    "feedback_weight": round(fw, 3),
                })

            results.sort(key=lambda x: x["score"], reverse=True)
            return results[:top_k]


# ── Singleton por db_path ──────────────────────────────────────────────
_caches: dict = {}

def get_vector_cache(db_path: str = DB_PATH) -> VectorCache:
    if db_path not in _caches:
        _caches[db_path] = VectorCache(db_path)
    return _caches[db_path]


def invalidate_cache(db_path: str = DB_PATH):
    """Llamar después de store() para forzar rebuild en próxima búsqueda."""
    if db_path in _caches:
        cache = _caches[db_path]
        with cache._lock:
            cache._db_hash = -1
            cache._hash_cache_ts = 0.0  # forzar re-query del hash
