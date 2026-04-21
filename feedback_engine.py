"""
feedback_engine.py — Cognia PASO 5: Aprendizaje por Feedback
=============================================================
Cierra el ciclo de aprendizaje:

  feedback del usuario → actualización de memoria → cambio en futuras respuestas

FLUJO:
  1. Cada respuesta generada registra qué episodios y conceptos usó (source_ids).
  2. El feedback (+1 / -1) llega asociado a un response_id.
  3. FeedbackEngine aplica deltas a los pesos/confianzas de esas memorias.
  4. Las búsquedas futuras priorizan memorias con mejor feedback.
  5. El DecisionGate ajusta sus umbrales según historial de calidad simbólica.

INTEGRACIÓN (3 puntos de contacto):
  A. language_engine.py  → llamar FeedbackTracker.register_response() al retornar
  B. cognia.py           → replace apply_feedback() con FeedbackEngine.apply()
  C. episodic.py         → retrieve_similar() multiplica score por feedback_weight
                           (un campo nuevo en episodic_memory, con DEFAULT=1.0)

DISEÑO:
  - Sin dependencias nuevas (solo sqlite3, logging existente)
  - Operaciones O(n_sources) — n_sources ≤ 10 por respuesta
  - Thread-safe con un único lock por DB
  - Decay automático: pesos vuelven lentamente a 1.0 si no hay feedback (no rompe sistema)
  - Límites duros: peso mínimo 0.20, máximo 2.0
"""

from __future__ import annotations

import json
import math
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from logger_config import get_logger, log_db_error

logger = get_logger(__name__)

# ── Constantes calibradas ──────────────────────────────────────────────
WEIGHT_MIN          = 0.20   # peso mínimo de un episodio con muchos -1
WEIGHT_MAX          = 2.00   # peso máximo con muchos +1
WEIGHT_DEFAULT      = 1.00   # todos los episodios comienzan aquí
POSITIVE_DELTA      = 0.15   # cuánto sube un +1
NEGATIVE_DELTA      = 0.20   # cuánto baja un -1 (ligeramente más fuerte)
DECAY_FACTOR        = 0.005  # cuánto decae hacia 1.0 por ciclo de sueño
CONFIDENCE_POS_BUMP = 0.05   # subida de confianza en semantic_memory por +1
CONFIDENCE_NEG_BUMP = 0.03   # bajada de confianza por -1 (moderada, no destruir)
REGISTER_TTL_S      = 3600   # cuánto tiempo conservar un response en el tracker RAM


# ══════════════════════════════════════════════════════════════════════
# ESTRUCTURA DE RESPUESTA RASTREADA
# ══════════════════════════════════════════════════════════════════════

@dataclass
class TrackedResponse:
    response_id:   str
    question:      str
    response_text: str
    stage_used:    str                  # cache / symbolic / hybrid / llm / fallback
    confidence:    float
    episode_ids:   List[int]            # IDs de episodic_memory usados
    concepts:      List[str]            # concepts de semantic_memory usados
    timestamp:     float = field(default_factory=time.time)

    def is_expired(self, ttl: float = REGISTER_TTL_S) -> bool:
        return (time.time() - self.timestamp) > ttl


# ══════════════════════════════════════════════════════════════════════
# TRACKER DE RESPUESTAS (RAM)
# ══════════════════════════════════════════════════════════════════════

class FeedbackTracker:
    """
    Mantiene en RAM un mapa response_id → TrackedResponse.

    register_response() se llama desde language_engine.py al final de respond().
    get_sources()       se llama desde FeedbackEngine.apply() para saber qué tocar.

    Capacidad limitada a MAX_TRACKED para no consumir memoria indefinidamente.
    """

    MAX_TRACKED = 500

    def __init__(self):
        self._store: Dict[str, TrackedResponse] = {}
        self._lock  = threading.Lock()

    def register_response(
        self,
        response_id:   str,
        question:      str,
        response_text: str,
        stage_used:    str,
        confidence:    float,
        episode_ids:   List[int],
        concepts:      List[str],
    ) -> None:
        """
        Registra los metadatos de la respuesta para poder aplicar feedback después.
        Llamar desde language_engine.respond() antes de retornar EngineResult.
        """
        with self._lock:
            # Limpieza de expirados antes de insertar
            if len(self._store) >= self.MAX_TRACKED:
                expired = [k for k, v in self._store.items() if v.is_expired()]
                for k in expired:
                    del self._store[k]
                # Si aún hay demasiados, eliminar los más viejos
                if len(self._store) >= self.MAX_TRACKED:
                    oldest = sorted(self._store.items(), key=lambda x: x[1].timestamp)
                    for k, _ in oldest[:50]:
                        del self._store[k]

            self._store[response_id] = TrackedResponse(
                response_id   = response_id,
                question      = question[:400],
                response_text = response_text[:500],
                stage_used    = stage_used,
                confidence    = confidence,
                episode_ids   = episode_ids[:20],   # cap
                concepts      = concepts[:10],
            )

        logger.debug(
            "Respuesta rastreada para feedback",
            extra={
                "op":      "feedback_tracker.register",
                "context": (
                    f"response_id={response_id} stage={stage_used} "
                    f"ep_ids={episode_ids[:5]} concepts={concepts[:3]}"
                ),
            },
        )

    def get_sources(self, response_id: str) -> Optional[TrackedResponse]:
        with self._lock:
            tr = self._store.get(response_id)
            if tr and tr.is_expired():
                del self._store[response_id]
                return None
            return tr

    def size(self) -> int:
        with self._lock:
            return len(self._store)


# ── Singleton del tracker ─────────────────────────────────────────────
_TRACKER: Optional[FeedbackTracker] = None
_TRACKER_LOCK = threading.Lock()


def get_feedback_tracker() -> FeedbackTracker:
    global _TRACKER
    if _TRACKER is None:
        with _TRACKER_LOCK:
            if _TRACKER is None:
                _TRACKER = FeedbackTracker()
    return _TRACKER


# ══════════════════════════════════════════════════════════════════════
# ESQUEMA DB (migración aditiva, no rompe tablas existentes)
# ══════════════════════════════════════════════════════════════════════

_INIT_SQL = [
    # Columna feedback_weight en episodic_memory (DEFAULT 1.0)
    # sqlite3 ignora la ALTER si ya existe → seguro ejecutar cada arranque
    """
    ALTER TABLE episodic_memory
    ADD COLUMN feedback_weight REAL DEFAULT 1.0
    """,
    # Tabla de historial de feedback para auditoría y decay
    """
    CREATE TABLE IF NOT EXISTS feedback_log (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        response_id  TEXT    NOT NULL,
        feedback     INTEGER NOT NULL,    -- +1 o -1
        stage_used   TEXT,
        confidence   REAL,
        ep_ids       TEXT,                -- JSON array de IDs afectados
        concepts     TEXT,                -- JSON array de conceptos afectados
        timestamp    REAL    NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_fl_response ON feedback_log(response_id)",
    "CREATE INDEX IF NOT EXISTS idx_fl_ts       ON feedback_log(timestamp)",
]


def _init_schema(db_path: str) -> None:
    """Aplica migraciones aditivas. Se puede llamar múltiples veces sin riesgo."""
    try:
        conn = sqlite3.connect(db_path)
        for sql in _INIT_SQL:
            try:
                conn.execute(sql)
            except sqlite3.OperationalError as e:
                # "duplicate column name" → ya existe, ignorar
                if "duplicate column" not in str(e).lower():
                    raise
        conn.commit()
        conn.close()
        logger.debug(
            "Schema PASO 5 inicializado",
            extra={"op": "feedback_engine._init_schema", "context": f"db={db_path}"},
        )
    except Exception as exc:
        log_db_error(logger, "feedback_engine._init_schema", exc,
                     extra_ctx=f"db_path={db_path}")


# ══════════════════════════════════════════════════════════════════════
# ENGINE PRINCIPAL DE FEEDBACK
# ══════════════════════════════════════════════════════════════════════

class FeedbackEngine:
    """
    Aplica feedback de usuario a la memoria de Cognia.

    Uso desde cognia.py:
        from feedback_engine import FeedbackEngine
        self._feedback_engine = FeedbackEngine(db_path)

    Luego en apply_feedback():
        self._feedback_engine.apply(
            response_id    = response_id,
            feedback       = 1 if correct else -1,
            correction_text = correction_text,
            cognia_instance = self,
        )
    """

    def __init__(self, db_path: str = "cognia_memory.db"):
        self.db_path = db_path
        self._lock   = threading.Lock()
        _init_schema(db_path)
        self.tracker = get_feedback_tracker()
        logger.info(
            "FeedbackEngine PASO 5 inicializado",
            extra={"op": "feedback_engine.__init__", "context": f"db={db_path}"},
        )

    # ── API principal ──────────────────────────────────────────────────

    def apply(
        self,
        response_id:     str,
        feedback:        int,          # +1 (positivo) o -1 (negativo)
        correction_text: Optional[str] = None,
        cognia_instance  = None,       # instancia Cognia completa (opcional)
    ) -> Dict:
        """
        Aplica feedback a las memorias usadas para generar response_id.

        Si el response_id no está en el tracker (respuesta muy vieja o
        caché de sesiones anteriores), aplica un feedback "ciego" solo
        al metacog y chat_history — sin modificar episodios específicos.

        Returns:
            dict con resumen de cambios aplicados
        """
        t0 = time.perf_counter()
        feedback = max(-1, min(1, int(feedback)))   # asegurar -1 o +1

        sources = self.tracker.get_sources(response_id)

        ep_ids   = sources.episode_ids if sources else []
        concepts = sources.concepts    if sources else []
        stage    = sources.stage_used  if sources else "unknown"
        conf     = sources.confidence  if sources else 0.5

        # ── 1. Actualizar feedback_weight en episodic_memory ──────────
        ep_changes = self._update_episode_weights(ep_ids, feedback)

        # ── 2. Actualizar confianza en semantic_memory ────────────────
        sem_changes = self._update_semantic_confidence(concepts, feedback)

        # ── 3. Registrar en feedback_log para auditoría y decay ───────
        self._log_feedback(response_id, feedback, stage, conf, ep_ids, concepts)

        # ── 4. Si feedback negativo + texto corrector: aprender ───────
        learn_result = {}
        if feedback == -1 and correction_text and cognia_instance:
            learn_result = self._learn_from_correction(correction_text, cognia_instance)

        # ── 5. Ajustar gate si hay historial suficiente ───────────────
        gate_adjusted = self._maybe_adjust_gate(stage, feedback)

        elapsed_ms = (time.perf_counter() - t0) * 1000

        summary = {
            "response_id":    response_id,
            "feedback":       feedback,
            "stage_used":     stage,
            "ep_ids_affected":  ep_changes["affected"],
            "ep_weight_deltas": ep_changes["deltas"],
            "sem_affected":   sem_changes["affected"],
            "gate_adjusted":  gate_adjusted,
            "learned":        bool(learn_result),
            "elapsed_ms":     round(elapsed_ms, 1),
        }

        logger.info(
            f"feedback={feedback:+d} "
            f"stage={stage} "
            f"affected_ep={ep_changes['affected']} "
            f"affected_sem={sem_changes['affected']} "
            f"new_weights={ep_changes['new_weights'][:5]} "
            f"gate_adjusted={gate_adjusted} "
            f"elapsed_ms={elapsed_ms:.1f}",
            extra={
                "op":      "feedback_engine.apply",
                "context": f"response_id={response_id} conf={conf:.2f}",
            },
        )

        return summary

    # ── Actualización de pesos episódicos ─────────────────────────────

    def _update_episode_weights(
        self, ep_ids: List[int], feedback: int
    ) -> Dict:
        """
        Modifica feedback_weight en episodic_memory.

        Fórmula:
          nuevo_peso = clamp(
              peso_actual + delta * feedback_direction,
              WEIGHT_MIN, WEIGHT_MAX
          )
        donde delta = POSITIVE_DELTA para +1, NEGATIVE_DELTA para -1.
        """
        if not ep_ids:
            return {"affected": 0, "deltas": [], "new_weights": []}

        delta     = POSITIVE_DELTA if feedback == 1 else -NEGATIVE_DELTA
        affected  = 0
        deltas    = []
        new_ws    = []

        try:
            conn = sqlite3.connect(self.db_path)
            conn.text_factory = str

            for ep_id in ep_ids:
                try:
                    row = conn.execute(
                        "SELECT feedback_weight, confidence FROM episodic_memory WHERE id=?",
                        (ep_id,)
                    ).fetchone()
                    if row is None:
                        continue

                    old_w    = row[0] if row[0] is not None else WEIGHT_DEFAULT
                    old_conf = row[1] if row[1] is not None else 0.5
                    new_w    = max(WEIGHT_MIN, min(WEIGHT_MAX, old_w + delta))

                    # Para feedback positivo subir confianza ligeramente
                    conf_delta = CONFIDENCE_POS_BUMP if feedback == 1 else -CONFIDENCE_NEG_BUMP
                    new_conf = max(0.10, min(1.0, old_conf + conf_delta))

                    conn.execute(
                        "UPDATE episodic_memory SET feedback_weight=?, confidence=? WHERE id=?",
                        (new_w, new_conf, ep_id),
                    )
                    affected += 1
                    deltas.append(round(new_w - old_w, 3))
                    new_ws.append(round(new_w, 3))

                except Exception as exc:
                    log_db_error(logger, "feedback_engine._update_episode_weights.row",
                                 exc, extra_ctx=f"ep_id={ep_id}")

            conn.commit()
            conn.close()

        except Exception as exc:
            log_db_error(logger, "feedback_engine._update_episode_weights",
                         exc, extra_ctx=f"ep_ids={ep_ids[:5]}")

        return {"affected": affected, "deltas": deltas, "new_weights": new_ws}

    # ── Actualización de confianza semántica ──────────────────────────

    def _update_semantic_confidence(
        self, concepts: List[str], feedback: int
    ) -> Dict:
        """
        Ajusta confidence en semantic_memory para los conceptos usados.
        Más conservador que los episodios: solo pequeños ajustes.
        """
        if not concepts:
            return {"affected": 0}

        conf_delta = CONFIDENCE_POS_BUMP if feedback == 1 else -CONFIDENCE_NEG_BUMP
        affected   = 0

        try:
            conn = sqlite3.connect(self.db_path)
            conn.text_factory = str

            for concept in concepts:
                try:
                    row = conn.execute(
                        "SELECT confidence FROM semantic_memory WHERE concept=?",
                        (concept,)
                    ).fetchone()
                    if row is None:
                        continue

                    old_conf = row[0] if row[0] is not None else 0.5
                    new_conf = max(0.10, min(1.0, old_conf + conf_delta))

                    conn.execute(
                        "UPDATE semantic_memory SET confidence=? WHERE concept=?",
                        (new_conf, concept),
                    )
                    affected += 1

                except Exception as exc:
                    log_db_error(logger, "feedback_engine._update_semantic.row",
                                 exc, extra_ctx=f"concept={concept}")

            conn.commit()
            conn.close()

        except Exception as exc:
            log_db_error(logger, "feedback_engine._update_semantic_confidence",
                         exc, extra_ctx=f"concepts={concepts[:5]}")

        return {"affected": affected}

    # ── Registro de feedback en DB ────────────────────────────────────

    def _log_feedback(
        self,
        response_id: str,
        feedback:    int,
        stage:       str,
        confidence:  float,
        ep_ids:      List[int],
        concepts:    List[str],
    ) -> None:
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                """INSERT INTO feedback_log
                   (response_id, feedback, stage_used, confidence,
                    ep_ids, concepts, timestamp)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    response_id, feedback, stage, confidence,
                    json.dumps(ep_ids[:20]),
                    json.dumps(concepts[:10]),
                    time.time(),
                ),
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            log_db_error(logger, "feedback_engine._log_feedback",
                         exc, extra_ctx=f"response_id={response_id}")

    # ── Aprendizaje desde texto corrector ─────────────────────────────

    def _learn_from_correction(
        self, correction_text: str, cognia_instance
    ) -> Dict:
        """
        Cuando el usuario da -1 y escribe una corrección, la guardamos
        como episodio de alta importancia para que compita en futuras búsquedas.
        """
        try:
            try:
                from cognia.vectors import text_to_vector, analyze_emotion
            except ImportError:
                from vectors import text_to_vector, analyze_emotion

            vec     = text_to_vector(correction_text[:300])
            emotion = {"score": -0.3, "label": "negativo", "intensity": 0.5}

            ep_id = cognia_instance.episodic.store(
                observation  = correction_text,
                label        = None,
                vector       = vec,
                confidence   = 0.85,
                importance   = 2.5,        # alta importancia: corrección explícita
                emotion      = emotion,
                surprise     = 0.6,
                context_tags = ["feedback", "correction"],
            )

            # Establecer peso alto desde el inicio para que aparezca primero
            try:
                conn = sqlite3.connect(self.db_path)
                conn.execute(
                    "UPDATE episodic_memory SET feedback_weight=? WHERE id=?",
                    (1.5, ep_id),
                )
                conn.commit()
                conn.close()
            except Exception:
                pass

            logger.info(
                "Episodio de corrección almacenado",
                extra={
                    "op":      "feedback_engine._learn_from_correction",
                    "context": f"ep_id={ep_id} len={len(correction_text)}",
                },
            )
            return {"ep_id": ep_id}

        except Exception as exc:
            log_db_error(logger, "feedback_engine._learn_from_correction",
                         exc, extra_ctx=f"text_len={len(correction_text)}")
            return {}

    # ── Ajuste dinámico del gate de decisión ─────────────────────────

    def _maybe_adjust_gate(self, stage: str, feedback: int) -> bool:
        """
        Si el stage simbólico recibe muchos -1 consecutivos, sube el umbral
        HIGH_THRESHOLD temporalmente para forzar más uso del LLM.

        Evalúa las últimas N entradas del feedback_log.
        Solo ajusta el singleton del gate — no persiste en DB (reset al reiniciar).
        """
        # Solo ajustar si la respuesta vino del simbólico
        if stage not in ("symbolic", "symbolic_synthesized", "symbolic_forced"):
            return False

        try:
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute(
                """SELECT feedback FROM feedback_log
                   WHERE stage_used IN ('symbolic','symbolic_synthesized','symbolic_forced')
                   ORDER BY timestamp DESC LIMIT 10""",
            ).fetchall()
            conn.close()

            if len(rows) < 5:
                return False

            recent_feedbacks = [r[0] for r in rows]
            negative_rate    = recent_feedbacks.count(-1) / len(recent_feedbacks)

            try:
                from decision_gate import get_decision_gate
            except ImportError:
                from cognia.decision_gate import get_decision_gate

            gate = get_decision_gate()

            if negative_rate >= 0.60:
                # Demasiados -1 en simbólico → ser más conservador
                new_high = min(0.88, gate.high_threshold + 0.04)
                if new_high != gate.high_threshold:
                    gate.high_threshold = new_high
                    logger.warning(
                        f"Gate HIGH_THRESHOLD subido a {new_high:.2f} "
                        f"(tasa negativa simbólica: {negative_rate:.0%})",
                        extra={
                            "op":      "feedback_engine._maybe_adjust_gate",
                            "context": f"negative_rate={negative_rate:.2f} stage={stage}",
                        },
                    )
                    return True

            elif negative_rate <= 0.20:
                # Simbólico funcionando bien → relajar umbral (volver a default)
                new_high = max(0.72, gate.high_threshold - 0.02)
                if new_high != gate.high_threshold:
                    gate.high_threshold = new_high
                    logger.info(
                        f"Gate HIGH_THRESHOLD bajado a {new_high:.2f} "
                        f"(tasa negativa simbólica: {negative_rate:.0%})",
                        extra={
                            "op":      "feedback_engine._maybe_adjust_gate",
                            "context": f"negative_rate={negative_rate:.2f}",
                        },
                    )
                    return True

        except Exception as exc:
            log_db_error(logger, "feedback_engine._maybe_adjust_gate",
                         exc, extra_ctx=f"stage={stage}")

        return False

    # ── Decay periódico (llamar desde cognia.sleep()) ─────────────────

    def decay_weights(self) -> Dict:
        """
        Aplica un decay suave: feedback_weight vuelve gradualmente a 1.0.

        Fórmula: new_w = w + DECAY_FACTOR * (1.0 - w)
        Esto asegura convergencia a 1.0 sin cruzar límites.

        Llamar desde cognia.sleep() para normalización periódica.
        """
        t0 = time.perf_counter()
        updated = 0
        try:
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute(
                """SELECT id, feedback_weight FROM episodic_memory
                   WHERE feedback_weight != 1.0 AND forgotten = 0"""
            ).fetchall()

            for ep_id, w in rows:
                if w is None:
                    continue
                w = float(w)
                new_w = w + DECAY_FACTOR * (1.0 - w)
                new_w = round(max(WEIGHT_MIN, min(WEIGHT_MAX, new_w)), 4)
                if abs(new_w - w) > 0.0001:
                    conn.execute(
                        "UPDATE episodic_memory SET feedback_weight=? WHERE id=?",
                        (new_w, ep_id),
                    )
                    updated += 1

            conn.commit()
            conn.close()

        except Exception as exc:
            log_db_error(logger, "feedback_engine.decay_weights", exc)

        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.info(
            f"Decay de feedback_weight: {updated} episodios ajustados",
            extra={
                "op":      "feedback_engine.decay_weights",
                "context": f"updated={updated} elapsed_ms={elapsed_ms:.1f}",
            },
        )
        return {"updated": updated, "elapsed_ms": round(elapsed_ms, 1)}

    # ── Estadísticas ──────────────────────────────────────────────────

    def stats(self) -> Dict:
        """Resumen del estado de feedback para diagnóstico."""
        try:
            conn = sqlite3.connect(self.db_path)
            total_fb = conn.execute("SELECT COUNT(*) FROM feedback_log").fetchone()[0]
            pos_fb   = conn.execute(
                "SELECT COUNT(*) FROM feedback_log WHERE feedback=1"
            ).fetchone()[0]
            neg_fb   = conn.execute(
                "SELECT COUNT(*) FROM feedback_log WHERE feedback=-1"
            ).fetchone()[0]

            low_w    = conn.execute(
                "SELECT COUNT(*) FROM episodic_memory WHERE feedback_weight < 0.5"
            ).fetchone()[0]
            high_w   = conn.execute(
                "SELECT COUNT(*) FROM episodic_memory WHERE feedback_weight > 1.5"
            ).fetchone()[0]
            avg_w_row = conn.execute(
                "SELECT AVG(feedback_weight) FROM episodic_memory WHERE forgotten=0"
            ).fetchone()
            avg_w    = round(avg_w_row[0] or 1.0, 3)
            conn.close()

            return {
                "total_feedback":    total_fb,
                "positive":          pos_fb,
                "negative":          neg_fb,
                "positive_rate":     round(pos_fb / max(1, total_fb), 3),
                "tracker_size":      self.tracker.size(),
                "episodes_low_weight":  low_w,
                "episodes_high_weight": high_w,
                "avg_feedback_weight":  avg_w,
            }
        except Exception as exc:
            log_db_error(logger, "feedback_engine.stats", exc)
            return {}


# ── Singleton del engine ──────────────────────────────────────────────
_ENGINE: Optional[FeedbackEngine] = None
_ENGINE_LOCK = threading.Lock()


def get_feedback_engine(db_path: str = "cognia_memory.db") -> FeedbackEngine:
    global _ENGINE
    if _ENGINE is None:
        with _ENGINE_LOCK:
            if _ENGINE is None:
                _ENGINE = FeedbackEngine(db_path)
    return _ENGINE
