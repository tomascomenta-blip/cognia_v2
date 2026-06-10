"""
model_collapse_guard.py — Cognia Paso 3
========================================
Detecta y previene el colapso de modelo: situación en la que Cognia
empieza a dar respuestas homogéneas porque un label dominante se repite
demasiado en el aprendizaje.

Dos tipos de colapso que detecta:

  1. COLAPSO POR LABEL (repetición)
     El mismo correct_label aparece en > LABEL_DOMINANCE_PCT % de las
     últimas N correcciones. Indica que se está sobre-entrenando un
     concepto a expensas de los demás.

  2. COLAPSO POR DIVERSIDAD SEMÁNTICA (homogeneización)
     La similitud coseno media entre los vectores de los últimos K
     episodios supera SIMILARITY_COLLAPSE_THRESHOLD. Indica que
     las observaciones recientes son demasiado parecidas entre sí
     y Cognia está convergiendo hacia un único atractor.

Acción al detectar colapso:
  - Retorna verdict="warn"  → TeacherInterface muestra advertencia pero acepta
  - Retorna verdict="reject" → TeacherInterface rechaza la corrección
  - El SelfArchitect (Paso 4) lee los reportes para proponer intervenciones

Diseño:
  - Sin dependencias externas pesadas: usa solo sqlite3 + math.
  - Si numpy está disponible, usa np.mean para el cálculo vectorial.
  - Persistencia en DB: tabla collapse_events para auditoría.
"""

import math
import time
import sqlite3
import threading
from typing import List, Dict, Optional

# ── Umbrales ──────────────────────────────────────────────────────────
LABEL_DOMINANCE_PCT        = 0.60   # >60% de correcciones con el mismo label → alerta
LABEL_DOMINANCE_REJECT_PCT = 0.80   # >80% → rechazo
WINDOW_CORRECTIONS         = 30     # ventana de correcciones para calcular dominancia
SIMILARITY_COLLAPSE_THRESHOLD = 0.92  # similitud media entre episodios → colapso semántico
SIMILARITY_WINDOW_EPISODES    = 20    # episodios a comparar para similitud
MIN_CORRECTIONS_TO_EVALUATE   = 5     # no evaluar hasta tener al menos N correcciones


class ModelCollapseGuard:
    """
    Guard de colapso de modelo para Cognia.

    Instanciado por TeacherInterface. Puede también ser consultado
    directamente por el SelfArchitect en el Paso 4.

    Uso:
        guard   = ModelCollapseGuard(db_path="cognia_memory.db")
        verdict = guard.check_correction(
            label="color_azul",
            observation="el cielo es azul",
            recent_corrections=[...],   # lista de dicts del TeacherInterface
        )
        # verdict["verdict"] → "ok" | "warn" | "reject"
    """

    def __init__(self, db_path: str = "cognia_memory.db"):
        self._db_path = db_path
        self._lock    = threading.RLock()
        self._init_db()

        # Cache de conteos para no consultar DB en cada corrección
        self._label_counts:  Dict[str, int] = {}
        self._last_refresh   = 0.0
        self._refresh_every  = 60.0   # segundos

    # ── API pública ────────────────────────────────────────────────────

    def check_correction(self, label: str, observation: str,
                         recent_corrections: List[Dict]) -> Dict:
        """
        Evalúa si la corrección propuesta es segura o indicaría colapso.

        Retorna dict con:
          verdict:  "ok" | "warn" | "reject"
          reason:   str explicando el veredicto
          metrics:  dict con los valores calculados
        """
        metrics = {}

        # ── Check 1: dominancia por label ─────────────────────────────
        if len(recent_corrections) >= MIN_CORRECTIONS_TO_EVALUATE:
            dominance = self._label_dominance(label, recent_corrections)
            metrics["label_dominance"] = round(dominance, 3)

            if dominance >= LABEL_DOMINANCE_REJECT_PCT:
                self._log_event("label_collapse_reject", label, dominance)
                return {
                    "verdict": "reject",
                    "reason":  (f"Colapso por label: '{label}' representa "
                                f"{dominance:.0%} de las últimas correcciones "
                                f"(umbral rechazo: {LABEL_DOMINANCE_REJECT_PCT:.0%}). "
                                f"Diversifica las correcciones antes de continuar."),
                    "metrics": metrics,
                }
            if dominance >= LABEL_DOMINANCE_PCT:
                self._log_event("label_collapse_warn", label, dominance)
                return {
                    "verdict": "warn",
                    "reason":  (f"Advertencia: '{label}' representa {dominance:.0%} "
                                f"de las últimas correcciones. Considera diversificar."),
                    "metrics": metrics,
                }

        # ── Check 2: diversidad semántica de episodios recientes ──────
        semantic_score = self._semantic_diversity()
        metrics["semantic_similarity"] = round(semantic_score, 3)

        if semantic_score >= SIMILARITY_COLLAPSE_THRESHOLD:
            self._log_event("semantic_collapse_warn", label, semantic_score)
            return {
                "verdict": "warn",
                "reason":  (f"Diversidad semántica baja: similitud media entre "
                            f"episodios recientes = {semantic_score:.3f} "
                            f"(umbral: {SIMILARITY_COLLAPSE_THRESHOLD}). "
                            f"El modelo está convergiendo hacia respuestas homogéneas."),
                "metrics": metrics,
            }

        return {"verdict": "ok", "reason": "", "metrics": metrics}

    def get_collapse_report(self) -> Dict:
        """
        Reporte completo del estado de colapso para el SelfArchitect.

        Retorna:
          risk_level:     "low" | "medium" | "high"
          dominant_labels: los labels más repetidos con su porcentaje
          semantic_score: similitud media actual
          events_24h:     eventos de colapso en las últimas 24 horas
        """
        dominant = self._top_labels(limit=5)
        sem_score = self._semantic_diversity()
        events = self._recent_events(hours=24)

        # Nivel de riesgo
        risk = "low"
        if dominant and dominant[0]["pct"] >= LABEL_DOMINANCE_PCT:
            risk = "medium"
        if dominant and dominant[0]["pct"] >= LABEL_DOMINANCE_REJECT_PCT:
            risk = "high"
        if sem_score >= SIMILARITY_COLLAPSE_THRESHOLD:
            risk = "high" if risk == "medium" else "medium"

        return {
            "risk_level":      risk,
            "dominant_labels": dominant,
            "semantic_score":  round(sem_score, 3),
            "events_24h":      events,
            "thresholds": {
                "label_warn":   LABEL_DOMINANCE_PCT,
                "label_reject": LABEL_DOMINANCE_REJECT_PCT,
                "semantic":     SIMILARITY_COLLAPSE_THRESHOLD,
            },
        }

    # ── Internos ───────────────────────────────────────────────────────

    def _label_dominance(self, candidate_label: str,
                          recent_corrections: List[Dict]) -> float:
        """
        Fracción de correcciones en la ventana que tienen candidate_label.
        Incluye la corrección propuesta como si ya se hubiera aplicado.
        """
        window = recent_corrections[-WINDOW_CORRECTIONS:]
        labels = [c["correct_label"] for c in window] + [candidate_label]
        if not labels:
            return 0.0
        count = labels.count(candidate_label)
        return count / len(labels)

    def _semantic_diversity(self) -> float:
        """
        Similitud coseno media entre los últimos SIMILARITY_WINDOW_EPISODES
        episodios activos. Valor alto = baja diversidad = riesgo de colapso.

        Si numpy no está disponible usa implementación pura en Python.
        """
        try:
            conn = sqlite3.connect(self._db_path)
            rows = conn.execute("""
                SELECT vector FROM episodic_memory
                WHERE forgotten = 0 AND vector IS NOT NULL
                ORDER BY timestamp DESC LIMIT ?
            """, (SIMILARITY_WINDOW_EPISODES,)).fetchall()
            conn.close()
        except Exception:
            return 0.0

        if len(rows) < 3:
            return 0.0

        import json
        vecs = []
        for (v_json,) in rows:
            try:
                v = json.loads(v_json)
                if isinstance(v, list) and v:
                    vecs.append(v)
            except Exception:
                continue

        if len(vecs) < 3:
            return 0.0

        # Calcular similitud media entre pares consecutivos (O(n), no O(n²))
        sims = []
        for i in range(len(vecs) - 1):
            sims.append(_cosine(vecs[i], vecs[i + 1]))

        return sum(sims) / len(sims) if sims else 0.0

    def _top_labels(self, limit: int = 5) -> List[Dict]:
        try:
            conn = sqlite3.connect(self._db_path)
            rows = conn.execute("""
                SELECT correct_label, COUNT(*) as cnt
                FROM teacher_corrections
                WHERE accepted = 1
                  AND timestamp > ?
                GROUP BY correct_label
                ORDER BY cnt DESC LIMIT ?
            """, (time.time() - 86400 * 7, limit)).fetchall()   # última semana
            conn.close()
        except Exception:
            return []

        total = sum(r[1] for r in rows)
        if total == 0:
            return []
        return [
            {"label": r[0], "count": r[1], "pct": round(r[1] / total, 3)}
            for r in rows
        ]

    def _recent_events(self, hours: int = 24) -> List[Dict]:
        cutoff = time.time() - hours * 3600
        try:
            conn = sqlite3.connect(self._db_path)
            rows = conn.execute("""
                SELECT event_type, label, score, timestamp
                FROM collapse_events
                WHERE timestamp > ?
                ORDER BY timestamp DESC LIMIT 20
            """, (cutoff,)).fetchall()
            conn.close()
            return [{"type": r[0], "label": r[1],
                     "score": r[2], "ts": r[3]} for r in rows]
        except Exception:
            return []

    def _log_event(self, event_type: str, label: str, score: float):
        try:
            conn = sqlite3.connect(self._db_path)
            conn.execute("""
                INSERT INTO collapse_events (event_type, label, score, timestamp)
                VALUES (?,?,?,?)
            """, (event_type, label, round(score, 4), time.time()))
            conn.commit()
            conn.close()
        except Exception:
            pass

    def _init_db(self):
        try:
            conn = sqlite3.connect(self._db_path)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS collapse_events (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    label      TEXT,
                    score      REAL,
                    timestamp  REAL NOT NULL
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ce_ts "
                "ON collapse_events(timestamp)"
            )
            conn.commit()
            conn.close()
        except Exception:
            pass


# ── Utilidad coseno pura Python ───────────────────────────────────────

def _cosine(a: List[float], b: List[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot  = sum(x * y for x, y in zip(a, b))
    na   = math.sqrt(sum(x * x for x in a))
    nb   = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return max(-1.0, min(1.0, dot / (na * nb)))
