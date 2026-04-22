"""
cognia/memory/narrative.py
==========================
Hilos narrativos: agrupa episodios en secuencias coherentes.

Fase 2 — NarrativeThread
"""

import json
import time
from typing import List, Optional

from storage.db_pool import db_connect_pooled as db_connect
from ..config import DB_PATH
from ..vectors import cosine_similarity
from logger_config import get_logger, log_db_error

logger = get_logger(__name__)

# Umbral mínimo de similitud semántica para incluir un episodio en el hilo
NARRATIVE_SIM_THRESHOLD = 0.6
# Ventana temporal por defecto (horas)
NARRATIVE_WINDOW_HOURS  = 2.0


class NarrativeThread:
    """
    Construye hilos narrativos coherentes a partir de un episodio semilla.

    Un hilo narrativo es una secuencia ordenada cronológicamente de episodios
    que comparten una ventana temporal (±window_hours) Y similitud semántica
    >= sim_threshold con el episodio semilla.

    Usa EpisodicMemory.get_in_window() para la ventana temporal y
    cosine_similarity() para el filtro semántico.
    No duplica lógica de embeddings ni de almacenamiento.

    Uso típico
    ----------
        thread = NarrativeThread(db_path)
        episodios = thread.build_thread(seed_id=42)
    """

    def __init__(
        self,
        db_path: str = DB_PATH,
        sim_threshold: float = NARRATIVE_SIM_THRESHOLD,
        window_hours: float = NARRATIVE_WINDOW_HOURS,
    ):
        self.db_path       = db_path
        self.sim_threshold = sim_threshold
        self.window_hours  = window_hours

    # ──────────────────────────────────────────────────────────────────
    # API pública
    # ──────────────────────────────────────────────────────────────────

    def build_thread(self, seed_id: int) -> List[dict]:
        """
        Construye y retorna el hilo narrativo del episodio *seed_id*.

        Pasos
        -----
        1. Cargar el episodio semilla (timestamp + vector).
        2. Obtener candidatos con EpisodicMemory.get_in_window().
        3. Filtrar por similitud coseno >= sim_threshold.
        4. Retornar lista ordenada cronológicamente (incluye la semilla).

        Retorna
        -------
        Lista de dicts con claves:
            id, observation, label, timestamp, confidence,
            importance, emotion_score, emotion_label, surprise, similarity
        Lista vacía si el seed no existe o hay error.
        """
        t0 = time.perf_counter()

        seed = self._load_seed(seed_id)
        if seed is None:
            return []

        # Importar aquí para evitar importación circular
        from .episodic import EpisodicMemory
        episodic = EpisodicMemory(self.db_path)

        candidates = episodic.get_in_window(
            timestamp=seed["timestamp"],
            window_hours=self.window_hours,
        )

        if not candidates:
            # Retornar al menos la semilla
            seed["similarity"] = 1.0
            return [seed]

        seed_vec = seed.get("vector")
        thread = []

        for ep in candidates:
            if ep["id"] == seed_id:
                ep["similarity"] = 1.0
                thread.append(ep)
                continue

            if seed_vec is None:
                # Sin vector en semilla, incluir todos los candidatos de la ventana
                ep["similarity"] = 0.0
                thread.append(ep)
                continue

            ep_vec = self._load_vector(ep["id"])
            if ep_vec is None:
                continue

            sim = cosine_similarity(seed_vec, ep_vec)
            if sim >= self.sim_threshold:
                ep["similarity"] = round(float(sim), 4)
                thread.append(ep)

        # Ordenar cronológicamente
        thread.sort(key=lambda x: x.get("timestamp", ""))

        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.debug(
            f"NarrativeThread: {len(thread)} episodios en hilo (seed={seed_id})",
            extra={
                "op":      "narrative.build_thread",
                "context": f"seed={seed_id} candidates={len(candidates)} "
                           f"thread={len(thread)} ms={elapsed_ms:.1f}",
            },
        )
        return thread

    # ──────────────────────────────────────────────────────────────────
    # Helpers internos
    # ──────────────────────────────────────────────────────────────────

    def _load_seed(self, seed_id: int) -> Optional[dict]:
        """Carga el episodio semilla con su vector desde SQLite."""
        try:
            conn = db_connect(self.db_path)
            c = conn.cursor()
            c.execute("""
                SELECT id, observation, label, timestamp,
                       confidence, importance,
                       emotion_score, emotion_label, surprise, vector
                FROM episodic_memory
                WHERE id = ? AND forgotten = 0
            """, (seed_id,))
            row = c.fetchone()
            conn.close()
        except Exception as exc:
            log_db_error(logger, "narrative._load_seed", exc,
                         extra_ctx=f"seed_id={seed_id}")
            return None

        if not row:
            logger.warning(
                "NarrativeThread: episodio semilla no encontrado",
                extra={"op": "narrative._load_seed",
                       "context": f"seed_id={seed_id}"},
            )
            return None

        ep_id, obs, label, ts, conf, imp, emo_s, emo_l, surprise, vec_str = row
        vec = None
        try:
            if vec_str:
                vec = json.loads(vec_str)
        except (json.JSONDecodeError, TypeError):
            pass

        return {
            "id":            ep_id,
            "observation":   obs,
            "label":         label,
            "timestamp":     ts,
            "confidence":    float(conf   or 0.5),
            "importance":    float(imp    or 1.0),
            "emotion_score": float(emo_s  or 0.0),
            "emotion_label": emo_l        or "neutral",
            "surprise":      float(surprise or 0.0),
            "vector":        vec,
        }

    def _load_vector(self, ep_id: int) -> Optional[list]:
        """Carga solo el vector de un episodio (columna pesada, on-demand)."""
        try:
            conn = db_connect(self.db_path)
            row = conn.execute(
                "SELECT vector FROM episodic_memory WHERE id = ?", (ep_id,)
            ).fetchone()
            conn.close()
            if row and row[0]:
                return json.loads(row[0])
        except Exception as exc:
            log_db_error(logger, "narrative._load_vector", exc,
                         extra_ctx=f"ep_id={ep_id}")
        return None
