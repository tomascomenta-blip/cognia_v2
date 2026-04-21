"""
teacher_interface.py — Cognia Paso 3
======================================
Punto de entrada único para correcciones y enseñanza externa.

PASO 1: Logging estructurado — eliminados todos los except: pass
"""

import time
import sqlite3
import threading
from dataclasses import dataclass, field
from typing import Optional, List, Dict

from logger_config import get_logger, log_db_error, safe_execute

logger = get_logger(__name__)

# ── Constantes ────────────────────────────────────────────────────────
CORRECTION_CONFIDENCE  = 0.85
CORRECTION_IMPORTANCE  = 1.8
BULK_BATCH_SIZE        = 32
MIN_OBSERVATION_LEN    = 3


@dataclass
class CorrectionRecord:
    observation:    str
    wrong_label:    Optional[str]
    correct_label:  str
    source:         str
    timestamp:      float = field(default_factory=time.time)
    accepted:       bool  = True
    rejection_reason: str = ""


class TeacherInterface:
    """
    Interfaz de enseñanza para Cognia.
    """

    def __init__(self, cognia_instance, db_path: str = "cognia_memory.db"):
        self._ai       = cognia_instance
        self._db_path  = db_path
        self._lock     = threading.RLock()
        self._session_corrections = 0
        self._session_rejections  = 0
        self._init_db()

        self._guard = None
        try:
            from model_collapse_guard import ModelCollapseGuard
            self._guard = ModelCollapseGuard(db_path=db_path)
            logger.info("ModelCollapseGuard cargado",
                        extra={"op": "teacher.init", "context": f"db={db_path}"})
        except ImportError:
            logger.info("ModelCollapseGuard no disponible (opcional)",
                        extra={"op": "teacher.init", "context": "module_missing"})

        self._corrector = None
        try:
            from language_corrector import LanguageCorrector
            self._corrector = LanguageCorrector()
            logger.info("LanguageCorrector cargado",
                        extra={"op": "teacher.init", "context": "ok"})
        except ImportError:
            logger.info("LanguageCorrector no disponible (opcional)",
                        extra={"op": "teacher.init", "context": "module_missing"})

    # ── API pública ────────────────────────────────────────────────────

    def correct(self, observation: str, correct_label: str,
                source: str = "human") -> Dict:
        t0 = time.perf_counter()

        observation   = observation.strip()
        correct_label = correct_label.strip().lower()
        if len(observation) < MIN_OBSERVATION_LEN or not correct_label:
            logger.warning(
                "Corrección rechazada: input demasiado corto",
                extra={"op": "teacher.correct",
                       "context": f"obs_len={len(observation)} label='{correct_label}'"},
            )
            return {"accepted": False, "rejection_reason": "input_too_short",
                    "label": correct_label}

        if self._corrector:
            try:
                observation   = self._corrector.clean(observation)
                correct_label = self._corrector.normalize_label(correct_label)
            except Exception as exc:
                logger.warning(
                    "LanguageCorrector falló, usando texto original",
                    extra={"op": "teacher.correct",
                           "context": f"label={correct_label} err={exc}"},
                )

        wrong_label = self._get_current_prediction(observation)

        guard_verdict = "ok"
        if self._guard:
            try:
                verdict = self._guard.check_correction(
                    label=correct_label,
                    observation=observation,
                    recent_corrections=self._recent_corrections(limit=20),
                )
                guard_verdict = verdict["verdict"]
                if verdict["verdict"] == "reject":
                    self._session_rejections += 1
                    logger.info(
                        f"Corrección rechazada por guard: {verdict['reason']}",
                        extra={"op": "teacher.correct",
                               "context": f"label={correct_label} reason={verdict['reason']}"},
                    )
                    record = CorrectionRecord(
                        observation=observation, wrong_label=wrong_label,
                        correct_label=correct_label, source=source,
                        accepted=False, rejection_reason=verdict["reason"],
                    )
                    self._persist(record)
                    return {
                        "accepted":         False,
                        "rejection_reason": verdict["reason"],
                        "label":            correct_label,
                        "guard_verdict":    guard_verdict,
                        "latency_ms":       round((time.perf_counter() - t0) * 1000, 1),
                    }
            except Exception as exc:
                logger.error(
                    "ModelCollapseGuard lanzó excepción inesperada, continuando sin guard",
                    extra={"op": "teacher.correct",
                           "context": f"label={correct_label} err={exc}"},
                )

        try:
            with self._lock:
                result = self._ai.observe(
                    observation,
                    provided_label=correct_label,
                )
                self._boost_last_episode(correct_label)
                self._session_corrections += 1
        except Exception as exc:
            logger.error(
                "cognia.observe() falló durante corrección",
                extra={"op": "teacher.correct",
                       "context": f"label={correct_label} err={exc}"},
            )
            return {
                "accepted":         False,
                "rejection_reason": f"observe_error: {exc}",
                "label":            correct_label,
                "guard_verdict":    guard_verdict,
                "latency_ms":       round((time.perf_counter() - t0) * 1000, 1),
            }

        self._invalidate_engine_cache(correct_label)

        record = CorrectionRecord(
            observation=observation, wrong_label=wrong_label,
            correct_label=correct_label, source=source,
            accepted=True,
        )
        self._persist(record)

        latency = round((time.perf_counter() - t0) * 1000, 1)
        logger.info(
            "Corrección aplicada",
            extra={"op": "teacher.correct",
                   "context": f"label={correct_label} was_error={result.get('was_error', False)} latency_ms={latency}"},
        )
        return {
            "accepted":      True,
            "label":         correct_label,
            "was_error":     result.get("was_error", False),
            "guard_verdict": guard_verdict,
            "latency_ms":    latency,
        }

    def teach_batch(self, pairs: List[tuple], source: str = "batch") -> Dict:
        pairs   = pairs[:BULK_BATCH_SIZE]
        results = {"accepted": 0, "rejected": 0, "errors": 0, "details": []}

        logger.info(
            f"Iniciando teach_batch con {len(pairs)} pares",
            extra={"op": "teacher.teach_batch", "context": f"source={source}"},
        )

        for obs, label in pairs:
            try:
                r = self.correct(obs, label, source=source)
                if r["accepted"]:
                    results["accepted"] += 1
                else:
                    results["rejected"] += 1
                results["details"].append(r)
            except Exception as exc:
                results["errors"] += 1
                results["details"].append({"error": str(exc), "obs": obs[:40]})
                logger.error(
                    "Error inesperado en teach_batch para un par",
                    extra={"op": "teacher.teach_batch",
                           "context": f"label={label} obs_preview={obs[:40]} err={exc}"},
                )

        logger.info(
            f"teach_batch completado: {results['accepted']} aceptadas, "
            f"{results['rejected']} rechazadas, {results['errors']} errores",
            extra={"op": "teacher.teach_batch", "context": f"source={source}"},
        )
        return results

    def stats(self) -> Dict:
        db_total    = self._db_count("accepted=1")
        db_rejected = self._db_count("accepted=0")
        return {
            "session_corrections": self._session_corrections,
            "session_rejections":  self._session_rejections,
            "db_total_accepted":   db_total,
            "db_total_rejected":   db_rejected,
            "guard_active":        self._guard is not None,
            "corrector_active":    self._corrector is not None,
        }

    def recent_corrections(self, limit: int = 10) -> List[Dict]:
        return self._recent_corrections(limit=limit)

    # ── Internos ───────────────────────────────────────────────────────

    def _get_current_prediction(self, observation: str) -> Optional[str]:
        try:
            from cognia.vectors import text_to_vector
            vec = text_to_vector(observation)
            similar = self._ai.episodic.retrieve_similar(vec, top_k=3)
            assessment = self._ai.metacog.assess_confidence(similar)
            return assessment.get("top_label")
        except ImportError as exc:
            logger.warning(
                "No se pudo importar text_to_vector para predicción previa",
                extra={"op": "teacher._get_current_prediction",
                       "context": f"err={exc}"},
            )
            return None
        except Exception as exc:
            logger.warning(
                "Error obteniendo predicción previa (no crítico)",
                extra={"op": "teacher._get_current_prediction",
                       "context": f"obs_len={len(observation)} err={exc}"},
            )
            return None

    def _boost_last_episode(self, label: str):
        try:
            conn = sqlite3.connect(self._db_path)
            conn.execute("""
                UPDATE episodic_memory
                SET confidence = MIN(1.0, confidence + 0.25),
                    importance  = MIN(2.5, importance  + 0.8)
                WHERE label = ? AND forgotten = 0
                ORDER BY timestamp DESC LIMIT 1
            """, (label,))
            conn.commit()
            conn.close()
        except Exception as exc:
            log_db_error(logger, "teacher._boost_last_episode", exc,
                         extra_ctx=f"label={label}")

    def _invalidate_engine_cache(self, concept: str):
        try:
            from language_engine import get_language_engine
            get_language_engine(self._ai).invalidate_concept(concept)
        except ImportError:
            logger.debug(
                "language_engine no disponible para invalidar caché",
                extra={"op": "teacher._invalidate_engine_cache",
                       "context": f"concept={concept}"},
            )
        except Exception as exc:
            logger.warning(
                "No se pudo invalidar caché del engine",
                extra={"op": "teacher._invalidate_engine_cache",
                       "context": f"concept={concept} err={exc}"},
            )

    def _recent_corrections(self, limit: int = 20) -> List[Dict]:
        try:
            conn = sqlite3.connect(self._db_path)
            rows = conn.execute("""
                SELECT observation, wrong_label, correct_label, source,
                       timestamp, accepted, rejection_reason
                FROM teacher_corrections
                ORDER BY timestamp DESC LIMIT ?
            """, (limit,)).fetchall()
            conn.close()
            return [
                {
                    "observation":    r[0], "wrong_label":   r[1],
                    "correct_label":  r[2], "source":        r[3],
                    "timestamp":      r[4], "accepted":      bool(r[5]),
                    "rejection_reason": r[6],
                }
                for r in rows
            ]
        except Exception as exc:
            log_db_error(logger, "teacher._recent_corrections", exc,
                         extra_ctx=f"limit={limit}")
            return []

    def _persist(self, record: CorrectionRecord):
        try:
            conn = sqlite3.connect(self._db_path)
            conn.execute("""
                INSERT INTO teacher_corrections
                (observation, wrong_label, correct_label, source,
                 timestamp, accepted, rejection_reason)
                VALUES (?,?,?,?,?,?,?)
            """, (
                record.observation[:400], record.wrong_label,
                record.correct_label, record.source,
                record.timestamp, int(record.accepted),
                record.rejection_reason,
            ))
            conn.commit()
            conn.close()
        except Exception as exc:
            log_db_error(logger, "teacher._persist", exc,
                         extra_ctx=f"label={record.correct_label} accepted={record.accepted}")

    def _db_count(self, where: str) -> int:
        try:
            conn = sqlite3.connect(self._db_path)
            n = conn.execute(
                f"SELECT COUNT(*) FROM teacher_corrections WHERE {where}"
            ).fetchone()[0]
            conn.close()
            return n
        except Exception as exc:
            log_db_error(logger, "teacher._db_count", exc,
                         extra_ctx=f"where={where}")
            return 0

    def _init_db(self):
        try:
            conn = sqlite3.connect(self._db_path)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS teacher_corrections (
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    observation      TEXT NOT NULL,
                    wrong_label      TEXT,
                    correct_label    TEXT NOT NULL,
                    source           TEXT DEFAULT 'human',
                    timestamp        REAL NOT NULL,
                    accepted         INTEGER DEFAULT 1,
                    rejection_reason TEXT DEFAULT ''
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_tc_label "
                "ON teacher_corrections(correct_label)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_tc_ts "
                "ON teacher_corrections(timestamp)"
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            log_db_error(logger, "teacher._init_db", exc,
                         extra_ctx=f"db_path={self._db_path}")


# ── Singleton por proceso ─────────────────────────────────────────────
_TEACHER_INSTANCE = None
_TEACHER_LOCK     = threading.Lock()


def get_teacher(cognia_instance, db_path: str = "cognia_memory.db") -> TeacherInterface:
    global _TEACHER_INSTANCE
    if _TEACHER_INSTANCE is None:
        with _TEACHER_LOCK:
            if _TEACHER_INSTANCE is None:
                _TEACHER_INSTANCE = TeacherInterface(cognia_instance, db_path)
    return _TEACHER_INSTANCE
