"""
teacher_interface.py — Cognia Paso 3
======================================
Punto de entrada único para correcciones y enseñanza externa.

Responsabilidades:
  - Recibir correcciones humanas (observación + label correcto) y
    traducirlas en llamadas a cognia.observe() con el peso adecuado.
  - Registrar el historial de correcciones en SQLite para que el
    ModelCollapseGuard pueda detectar patrones de sobre-corrección.
  - Exponer métricas de aprendizaje al SelfArchitect (Paso 4).
  - Invocar al LanguageEngine para invalidar el caché del concepto
    afectado justo después de cada corrección.

Diseño:
  - No toca la DB de episodic_memory directamente — todo pasa por
    cognia.observe() para respetar el pipeline cognitivo completo.
  - Thread-safe: puede llamarse desde web_app.py y desde scripts
    de entrenamiento batch en paralelo.
  - Importación opcional: si no existe, cognia.py sigue funcionando.
"""

import time
import sqlite3
import threading
from dataclasses import dataclass, field
from typing import Optional, List, Dict

# ── Constantes ────────────────────────────────────────────────────────
CORRECTION_CONFIDENCE  = 0.85   # confianza asignada a correcciones humanas
CORRECTION_IMPORTANCE  = 1.8    # importancia episódica (mayor que aprendizaje normal)
BULK_BATCH_SIZE        = 32     # máximo de correcciones por lote en teach_batch()
MIN_OBSERVATION_LEN    = 3      # ignorar observaciones vacías o triviales


@dataclass
class CorrectionRecord:
    observation:    str
    wrong_label:    Optional[str]    # None si era primera vez (no había predicción)
    correct_label:  str
    source:         str              # "human", "batch", "api"
    timestamp:      float = field(default_factory=time.time)
    accepted:       bool  = True     # False si el guard rechazó la corrección
    rejection_reason: str = ""


class TeacherInterface:
    """
    Interfaz de enseñanza para Cognia.

    Uso típico desde web_app.py:
        teacher = TeacherInterface(cognia_instance=ai, db_path=ai.db)
        result  = teacher.correct("el cielo es azul", "color_azul")

    Uso desde script de entrenamiento:
        teacher.teach_batch([
            ("el cielo es azul",   "color_azul"),
            ("la hierba es verde", "color_verde"),
        ])
    """

    def __init__(self, cognia_instance, db_path: str = "cognia_memory.db"):
        self._ai       = cognia_instance
        self._db_path  = db_path
        self._lock     = threading.RLock()
        self._session_corrections = 0
        self._session_rejections  = 0
        self._init_db()

        # Importar guard si existe — opcional
        self._guard = None
        try:
            from model_collapse_guard import ModelCollapseGuard
            self._guard = ModelCollapseGuard(db_path=db_path)
        except ImportError:
            pass

        # Importar corrector de lenguaje — opcional
        self._corrector = None
        try:
            from language_corrector import LanguageCorrector
            self._corrector = LanguageCorrector()
        except ImportError:
            pass

    # ── API pública ────────────────────────────────────────────────────

    def correct(self, observation: str, correct_label: str,
                source: str = "human") -> Dict:
        """
        Aplica una corrección individual.

        Flujo:
          1. Validar entrada
          2. Limpiar texto (LanguageCorrector si disponible)
          3. Pedir permiso al ModelCollapseGuard
          4. Llamar a cognia.observe(observation, provided_label=correct_label)
             con confidence y importance elevados
          5. Invalidar caché del engine para el concepto
          6. Persistir registro en DB

        Retorna dict con: accepted, label, was_error, guard_verdict, latency_ms
        """
        t0 = time.perf_counter()

        # Validación
        observation   = observation.strip()
        correct_label = correct_label.strip().lower()
        if len(observation) < MIN_OBSERVATION_LEN or not correct_label:
            return {"accepted": False, "rejection_reason": "input_too_short",
                    "label": correct_label}

        # Limpieza de texto
        if self._corrector:
            observation   = self._corrector.clean(observation)
            correct_label = self._corrector.normalize_label(correct_label)

        # ¿Cuál era la predicción previa? (para el registro)
        wrong_label = self._get_current_prediction(observation)

        # Consultar al guard
        guard_verdict = "ok"
        if self._guard:
            verdict = self._guard.check_correction(
                label=correct_label,
                observation=observation,
                recent_corrections=self._recent_corrections(limit=20),
            )
            guard_verdict = verdict["verdict"]
            if verdict["verdict"] == "reject":
                self._session_rejections += 1
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

        # Aplicar corrección a través de observe()
        with self._lock:
            result = self._ai.observe(
                observation,
                provided_label=correct_label,
            )
            # Elevar confianza e importancia del episodio recién almacenado
            self._boost_last_episode(correct_label)
            self._session_corrections += 1

        # Invalidar caché del engine
        self._invalidate_engine_cache(correct_label)

        # Persistir
        record = CorrectionRecord(
            observation=observation, wrong_label=wrong_label,
            correct_label=correct_label, source=source,
            accepted=True,
        )
        self._persist(record)

        latency = round((time.perf_counter() - t0) * 1000, 1)
        return {
            "accepted":      True,
            "label":         correct_label,
            "was_error":     result.get("was_error", False),
            "guard_verdict": guard_verdict,
            "latency_ms":    latency,
        }

    def teach_batch(self, pairs: List[tuple], source: str = "batch") -> Dict:
        """
        Aplica una lista de (observación, label) en lote.

        Limita a BULK_BATCH_SIZE por llamada para no saturar la memoria.
        Retorna resumen: accepted, rejected, errors.
        """
        pairs   = pairs[:BULK_BATCH_SIZE]
        results = {"accepted": 0, "rejected": 0, "errors": 0, "details": []}

        for obs, label in pairs:
            try:
                r = self.correct(obs, label, source=source)
                if r["accepted"]:
                    results["accepted"] += 1
                else:
                    results["rejected"] += 1
                results["details"].append(r)
            except Exception as e:
                results["errors"] += 1
                results["details"].append({"error": str(e), "obs": obs[:40]})

        return results

    def stats(self) -> Dict:
        """Métricas de la sesión actual y acumuladas en DB."""
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
        """Últimas correcciones para el SelfArchitect (Paso 4)."""
        return self._recent_corrections(limit=limit)

    # ── Internos ───────────────────────────────────────────────────────

    def _get_current_prediction(self, observation: str) -> Optional[str]:
        try:
            from cognia.vectors import text_to_vector
            vec = text_to_vector(observation)
            similar = self._ai.episodic.retrieve_similar(vec, top_k=3)
            assessment = self._ai.metacog.assess_confidence(similar)
            return assessment.get("top_label")
        except Exception:
            return None

    def _boost_last_episode(self, label: str):
        """
        Eleva confidence e importance del episodio más reciente con este label.
        Operación directa en DB — no pasa por observe() para no crear duplicados.
        """
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
        except Exception:
            pass

    def _invalidate_engine_cache(self, concept: str):
        try:
            from language_engine import get_language_engine
            get_language_engine(self._ai).invalidate_concept(concept)
        except Exception:
            pass

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
        except Exception:
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
        except Exception:
            pass

    def _db_count(self, where: str) -> int:
        try:
            conn = sqlite3.connect(self._db_path)
            n = conn.execute(
                f"SELECT COUNT(*) FROM teacher_corrections WHERE {where}"
            ).fetchone()[0]
            conn.close()
            return n
        except Exception:
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
        except Exception:
            pass


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
