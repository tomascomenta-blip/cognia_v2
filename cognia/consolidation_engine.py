"""
consolidation_engine.py — Cognia PASO 6: Consolidación y Limpieza de Memoria
=============================================================================
Implementa el ciclo de "sueño profundo" cognitivo:

  1. ELIMINACIÓN    — borra episodios de baja calidad (peso bajo + poco uso)
  2. DEBILITAMIENTO — reduce confianza de episodios negativos sin borrarlos
  3. CONSOLIDACIÓN  — fusiona episodios similares en uno más fuerte
  4. REFUERZO       — sube importancia de memorias valiosas frecuentes
  5. DECAY          — decaimiento gradual de memorias no usadas
  6. DEDUPLICACIÓN  — elimina semánticos redundantes de baja calidad

PRINCIPIOS DE DISEÑO:
  - Cero dependencias nuevas (sqlite3 + logging existente)
  - Operaciones por batches — no recorre toda la DB en un solo scan
  - Thread-safe: un único lock por instancia
  - NO rompe el sistema si la DB tiene columnas extra o schema ligeramente diferente
  - Todas las operaciones son reversibles (soft-delete via forgotten=1 antes de purge)
  - Se activa desde cognia.sleep() — no corre en background constante

INTEGRACIÓN (2 puntos de contacto):
  A. cognia.py  → importar y llamar en sleep()
  B. cognia.py  → llamar tick() desde observe() para conteo de ciclos

COLUMNAS REQUERIDAS en episodic_memory (todas ya existen):
  id, observation, label, vector, confidence, importance, feedback_weight,
  access_count, forgotten, last_access, review_count, timestamp

COLUMNAS REQUERIDAS en semantic_memory:
  concept, confidence, support, emotion_avg
"""

from __future__ import annotations

import json
import math
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from logger_config import get_logger, log_db_error

logger = get_logger(__name__)

# ══════════════════════════════════════════════════════════════════════
# UMBRALES Y CONSTANTES
# ══════════════════════════════════════════════════════════════════════

# — Eliminación dura (purge) —
PURGE_WEIGHT_MAX        = 0.30   # episodios con feedback_weight <= este valor Y...
PURGE_ACCESS_MAX        = 2      # ...accedidos <= N veces son candidatos a borrar
PURGE_AGE_DAYS_MIN      = 7      # ...y tienen al menos N días de antigüedad
PURGE_CONFIDENCE_MAX    = 0.40   # ...y confianza <= umbral

# — Debilitamiento suave (no borrar, solo bajar importancia) —
WEAKEN_WEIGHT_MAX       = 0.45   # episodios con feedback_weight entre 0.30-0.45
WEAKEN_IMPORTANCE_DELTA = 0.15   # cuánto se reduce su importancia
WEAKEN_IMPORTANCE_MIN   = 0.3    # nunca dejar importance < este valor

# — Consolidación (fusión de episodios similares) —
CONSOLIDATE_SIM_THRESHOLD  = 0.92   # similitud coseno mínima para considerar fusión
CONSOLIDATE_BATCH_SIZE     = 200    # cuántos episodios revisar por ciclo
CONSOLIDATE_MIN_CONFIDENCE = 0.35   # no fusionar episodios muy poco confiables

# — Refuerzo de memorias valiosas —
REINFORCE_WEIGHT_MIN    = 1.40   # episodios con feedback_weight >= este valor...
REINFORCE_ACCESS_MIN    = 5      # ...y accedidos >= N veces reciben refuerzo
REINFORCE_CONF_DELTA    = 0.05   # cuánto sube su confianza
REINFORCE_CONF_MAX      = 0.95   # techo de confianza

# — Decay de importancia (memorias no usadas) —
DECAY_IMPORTANCE_FACTOR = 0.008  # reducción por ciclo: new_imp = imp - FACTOR*(imp-1.0)
DECAY_IMPORTANCE_MIN    = 0.8    # no decaer por debajo de este valor
DECAY_LAST_ACCESS_DAYS  = 14     # solo decaer si no se accedió en N días

# — Deduplicación semántica —
DEDUP_SIM_THRESHOLD     = 0.93   # similitud para considerar semánticos duplicados
DEDUP_MIN_SUPPORT       = 3      # el ganador debe tener al menos N de support

# — Límites por ciclo (CPU control) —
MAX_PURGE_PER_CYCLE     = 100
MAX_CONSOLIDATE_CYCLES  = 3      # máximo de pasadas de consolidación por sleep
MAX_REINFORCE_PER_CYCLE = 50
MAX_DECAY_PER_CYCLE     = 200
MAX_DEDUP_SEMANTIC      = 30

# — Trigger de activación desde observe() —
DEFAULT_CONSOLIDATION_INTERVAL = 20   # cada N interacciones, activar ciclo ligero


# ══════════════════════════════════════════════════════════════════════
# RESULTADO DEL CICLO
# ══════════════════════════════════════════════════════════════════════

@dataclass
class ConsolidationResult:
    purged:          int = 0     # episodios eliminados permanentemente
    weakened:        int = 0     # episodios debilitados
    consolidated:    int = 0     # pares fusionados (episodios absorbidos)
    reinforced:      int = 0     # episodios reforzados
    decayed:         int = 0     # episodios con decay aplicado
    sem_deduped:     int = 0     # conceptos semánticos eliminados como duplicados
    elapsed_ms:      float = 0.0
    cycle_type:      str = "full"   # "full" | "light"

    def to_dict(self) -> dict:
        return {
            "purged":       self.purged,
            "weakened":     self.weakened,
            "consolidated": self.consolidated,
            "reinforced":   self.reinforced,
            "decayed":      self.decayed,
            "sem_deduped":  self.sem_deduped,
            "elapsed_ms":   round(self.elapsed_ms, 1),
            "cycle_type":   self.cycle_type,
        }

    def summary_line(self) -> str:
        return (
            f"PASO6 [{self.cycle_type}] "
            f"purged={self.purged} weakened={self.weakened} "
            f"consolidated={self.consolidated} reinforced={self.reinforced} "
            f"decayed={self.decayed} sem_dedup={self.sem_deduped} "
            f"({self.elapsed_ms:.0f}ms)"
        )


# ══════════════════════════════════════════════════════════════════════
# HELPERS INTERNOS
# ══════════════════════════════════════════════════════════════════════

def _cosine(a: List[float], b: List[float]) -> float:
    """Similitud coseno sin dependencias externas."""
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na  = math.sqrt(sum(x * x for x in a))
    nb  = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return max(-1.0, min(1.0, dot / (na * nb)))


def _avg_vec(vecs: List[List[float]]) -> List[float]:
    """Promedio de vectores (consolidación)."""
    if not vecs:
        return []
    n = len(vecs)
    return [sum(v[i] for v in vecs) / n for i in range(len(vecs[0]))]


def _db_connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=10)
    conn.text_factory = str
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _days_ago(days: int) -> str:
    """Retorna timestamp ISO de N días atrás."""
    dt = datetime.now() - timedelta(days=days)
    return dt.isoformat()


# ══════════════════════════════════════════════════════════════════════
# MOTOR DE CONSOLIDACIÓN
# ══════════════════════════════════════════════════════════════════════

class ConsolidationEngine:
    """
    Motor de consolidación y limpieza de memoria para Cognia.

    Uso desde cognia.py:
        from consolidation_engine import get_consolidation_engine
        self._consolidation_engine = get_consolidation_engine(db_path)

    En sleep():
        result = self._consolidation_engine.run_full_cycle()

    En observe() (ciclo ligero):
        self._consolidation_engine.tick(self.interaction_count)
    """

    def __init__(self, db_path: str = "cognia_memory.db",
                 consolidation_interval: int = DEFAULT_CONSOLIDATION_INTERVAL):
        self.db_path  = db_path
        self._interval = consolidation_interval
        self._lock    = threading.RLock()
        self._light_cycle_count = 0   # cuántos ciclos ligeros se han ejecutado
        self._init_schema()

    # ─────────────────────────────────────────────────────────────────
    # API PÚBLICA
    # ─────────────────────────────────────────────────────────────────

    def tick(self, interaction_count: int) -> Optional[ConsolidationResult]:
        """
        Llamar desde observe() en cada interacción.
        Activa un ciclo LIGERO cada `_interval` interacciones.
        No bloquea ni es costoso.
        """
        if interaction_count > 0 and interaction_count % self._interval == 0:
            return self.run_light_cycle()
        return None

    def run_full_cycle(self) -> ConsolidationResult:
        """
        Ciclo COMPLETO — llamar desde cognia.sleep().
        Incluye todas las fases: purge + weaken + consolidate + reinforce + decay + dedup.
        """
        t0 = time.perf_counter()
        result = ConsolidationResult(cycle_type="full")

        with self._lock:
            result.purged       = self._phase_purge()
        time.sleep(0.05)   # FIX: yield entre fases para no bloquear hilo principal
        with self._lock:
            result.weakened     = self._phase_weaken()
        time.sleep(0.05)
        with self._lock:
            result.consolidated = self._phase_consolidate()
        time.sleep(0.05)
        with self._lock:
            result.reinforced   = self._phase_reinforce()
            result.decayed      = self._phase_decay()
            result.sem_deduped  = self._phase_semantic_dedup()
            self._record_cycle(result)

        result.elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.info(
            result.summary_line(),
            extra={"op": "consolidation.run_full_cycle",
                   "context": f"db={self.db_path}"},
        )
        return result

    def run_light_cycle(self) -> ConsolidationResult:
        """
        Ciclo LIGERO — llamar desde tick() / observe().
        Solo decay + weaken suave. Muy rápido (< 30ms en hardware objetivo).
        """
        t0 = time.perf_counter()
        result = ConsolidationResult(cycle_type="light")
        self._light_cycle_count += 1

        with self._lock:
            result.weakened = self._phase_weaken(limit=30)
            result.decayed  = self._phase_decay(limit=50)

        result.elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.debug(
            result.summary_line(),
            extra={"op": "consolidation.run_light_cycle",
                   "context": f"light_cycles={self._light_cycle_count}"},
        )
        return result

    def stats(self) -> Dict:
        """Diagnóstico rápido del estado de memoria."""
        try:
            conn = _db_connect(self.db_path)
            ep_total = conn.execute(
                "SELECT COUNT(*) FROM episodic_memory WHERE forgotten=0"
            ).fetchone()[0]
            ep_low_w = conn.execute(
                "SELECT COUNT(*) FROM episodic_memory WHERE forgotten=0 AND feedback_weight <= ?",
                (PURGE_WEIGHT_MAX,)
            ).fetchone()[0]
            ep_high_w = conn.execute(
                "SELECT COUNT(*) FROM episodic_memory WHERE forgotten=0 AND feedback_weight >= ?",
                (REINFORCE_WEIGHT_MIN,)
            ).fetchone()[0]
            sem_total = conn.execute(
                "SELECT COUNT(*) FROM semantic_memory"
            ).fetchone()[0]
            cycles_run = conn.execute(
                "SELECT COUNT(*) FROM consolidation_log"
            ).fetchone()[0]
            conn.close()
            return {
                "ep_total":       ep_total,
                "ep_low_weight":  ep_low_w,
                "ep_high_weight": ep_high_w,
                "sem_total":      sem_total,
                "cycles_run":     cycles_run,
                "light_cycles":   self._light_cycle_count,
            }
        except Exception as exc:
            log_db_error(logger, "consolidation.stats", exc)
            return {}

    # ─────────────────────────────────────────────────────────────────
    # FASE 1: PURGE — eliminación dura de episodios de baja calidad
    # ─────────────────────────────────────────────────────────────────

    def _phase_purge(self, limit: int = MAX_PURGE_PER_CYCLE) -> int:
        """
        Marca como forgotten=1 (soft-delete) episodios que cumplen TODOS los criterios:
          - feedback_weight <= PURGE_WEIGHT_MAX   (muy penalizados por usuario)
          - access_count    <= PURGE_ACCESS_MAX   (casi nunca usados)
          - confidence      <= PURGE_CONFIDENCE_MAX
          - timestamp       < N días atrás        (no recientes)
          - NOT forgotten ya
          - NOT label protegido (aprendizaje explícito, correcciones)

        Usa soft-delete para preservar integridad referencial.
        """
        cutoff = _days_ago(PURGE_AGE_DAYS_MIN)
        try:
            conn = _db_connect(self.db_path)
            rows = conn.execute("""
                SELECT id, label, confidence, feedback_weight, access_count
                FROM episodic_memory
                WHERE forgotten = 0
                  AND COALESCE(feedback_weight, 1.0) <= ?
                  AND COALESCE(access_count, 0)     <= ?
                  AND confidence                    <= ?
                  AND timestamp                     <  ?
                  AND COALESCE(label, '') NOT IN (
                    'feedback', 'correction', 'correccion',
                    'aprendizaje', 'ensenanza', 'conocimiento_critico'
                  )
                ORDER BY feedback_weight ASC, confidence ASC
                LIMIT ?
            """, (PURGE_WEIGHT_MAX, PURGE_ACCESS_MAX,
                  PURGE_CONFIDENCE_MAX, cutoff, limit)).fetchall()

            if not rows:
                conn.close()
                return 0

            ids = [r[0] for r in rows]
            now = datetime.now().isoformat()

            # Soft-delete: forgotten=1 (recover posible si hay error)
            conn.executemany(
                "UPDATE episodic_memory SET forgotten=1, last_access=? WHERE id=?",
                [(now, ep_id) for ep_id in ids]
            )
            conn.commit()
            conn.close()

            logger.info(
                f"cleanup: removed_ids={ids[:10]} total={len(ids)}",
                extra={"op": "consolidation._phase_purge",
                       "context": f"ids_sample={ids[:5]} cutoff={cutoff}"},
            )
            return len(ids)

        except Exception as exc:
            log_db_error(logger, "consolidation._phase_purge", exc)
            return 0

    # ─────────────────────────────────────────────────────────────────
    # FASE 2: WEAKEN — debilitamiento suave de episodios negativos
    # ─────────────────────────────────────────────────────────────────

    def _phase_weaken(self, limit: int = 100) -> int:
        """
        Para episodios con feedback negativo moderado (no suficiente para purge):
        reduce su importancia para que aparezcan menos en búsquedas,
        pero los conserva (pueden rehabilitarse con feedback positivo futuro).
        """
        try:
            conn = _db_connect(self.db_path)
            rows = conn.execute("""
                SELECT id, importance
                FROM episodic_memory
                WHERE forgotten = 0
                  AND COALESCE(feedback_weight, 1.0) > ?
                  AND COALESCE(feedback_weight, 1.0) <= ?
                  AND importance                     > ?
                ORDER BY feedback_weight ASC
                LIMIT ?
            """, (PURGE_WEIGHT_MAX, WEAKEN_WEIGHT_MAX,
                  WEAKEN_IMPORTANCE_MIN, limit)).fetchall()

            if not rows:
                conn.close()
                return 0

            updates = []
            for ep_id, imp in rows:
                new_imp = max(WEAKEN_IMPORTANCE_MIN, float(imp) - WEAKEN_IMPORTANCE_DELTA)
                updates.append((round(new_imp, 4), ep_id))

            conn.executemany(
                "UPDATE episodic_memory SET importance=? WHERE id=?", updates
            )
            conn.commit()
            conn.close()

            logger.debug(
                f"Weaken: {len(updates)} episodios debilitados",
                extra={"op": "consolidation._phase_weaken",
                       "context": f"delta={WEAKEN_IMPORTANCE_DELTA}"},
            )
            return len(updates)

        except Exception as exc:
            log_db_error(logger, "consolidation._phase_weaken", exc)
            return 0

    # ─────────────────────────────────────────────────────────────────
    # FASE 3: CONSOLIDATE — fusión de episodios similares
    # ─────────────────────────────────────────────────────────────────

    def _phase_consolidate(self) -> int:
        """
        Detecta pares de episodios con similitud coseno >= CONSOLIDATE_SIM_THRESHOLD.
        Fusiona: el episodio de mayor confianza absorbe al otro.
        - Vector resultante: promedio ponderado por confianza
        - Confianza resultante: max(conf_a, conf_b) + 0.03
        - Importancia: max(imp_a, imp_b)
        - feedback_weight: promedio
        - El episodio absorbido: forgotten=1

        Procesa en batches para no saturar la CPU.
        """
        total_merged = 0

        for _ in range(MAX_CONSOLIDATE_CYCLES):
            merged = self._consolidate_batch()
            total_merged += merged
            if merged == 0:
                break   # no hay más pares — salir

        if total_merged > 0:
            logger.info(
                f"Consolidate: {total_merged} episodios fusionados",
                extra={"op": "consolidation._phase_consolidate",
                       "context": f"threshold={CONSOLIDATE_SIM_THRESHOLD}"},
            )
        return total_merged

    def _consolidate_batch(self) -> int:
        """Procesa un batch de episodios buscando duplicados."""
        try:
            conn = _db_connect(self.db_path)
            rows = conn.execute("""
                SELECT id, vector, confidence, importance,
                       COALESCE(feedback_weight, 1.0), label
                FROM episodic_memory
                WHERE forgotten = 0
                  AND confidence >= ?
                ORDER BY confidence DESC, importance DESC
                LIMIT ?
            """, (CONSOLIDATE_MIN_CONFIDENCE, CONSOLIDATE_BATCH_SIZE)).fetchall()
            conn.close()
        except Exception as exc:
            log_db_error(logger, "consolidation._consolidate_batch", exc)
            return 0

        if len(rows) < 2:
            return 0

        # Parsear vectores
        parsed = []
        for row in rows:
            ep_id, vec_str, conf, imp, fw, label = row
            try:
                vec = json.loads(vec_str)
                parsed.append((ep_id, vec, float(conf), float(imp), float(fw), label))
            except (json.JSONDecodeError, TypeError):
                continue

        merged_ids = set()  # IDs ya procesados en este batch
        to_merge: List[Tuple] = []   # (survivor_id, absorbed_id, new_vec, new_conf, new_imp, new_fw)

        for i in range(len(parsed)):
            if parsed[i][0] in merged_ids:
                continue
            id_a, vec_a, conf_a, imp_a, fw_a, label_a = parsed[i]

            for j in range(i + 1, len(parsed)):
                if parsed[j][0] in merged_ids:
                    continue
                id_b, vec_b, conf_b, imp_b, fw_b, label_b = parsed[j]

                sim = _cosine(vec_a, vec_b)
                if sim >= CONSOLIDATE_SIM_THRESHOLD:
                    # El de mayor confianza sobrevive
                    if conf_a >= conf_b:
                        survivor, absorbed = id_a, id_b
                        s_vec, s_conf, s_imp, s_fw = vec_a, conf_a, imp_a, fw_a
                        a_vec, a_conf, a_imp, a_fw = vec_b, conf_b, imp_b, fw_b
                    else:
                        survivor, absorbed = id_b, id_a
                        s_vec, s_conf, s_imp, s_fw = vec_b, conf_b, imp_b, fw_b
                        a_vec, a_conf, a_imp, a_fw = vec_a, conf_a, imp_a, fw_a

                    # Fusión: promedio ponderado por confianza
                    total_conf = s_conf + a_conf
                    w_s = s_conf / total_conf if total_conf > 0 else 0.5
                    w_a = 1.0 - w_s
                    new_vec  = [w_s * sv + w_a * av for sv, av in zip(s_vec, a_vec)]
                    new_conf = min(REINFORCE_CONF_MAX, max(s_conf, a_conf) + 0.03)
                    new_imp  = max(s_imp, a_imp)
                    new_fw   = (s_fw + a_fw) / 2.0

                    to_merge.append((survivor, absorbed, new_vec, new_conf, new_imp, new_fw))
                    merged_ids.add(absorbed)
                    merged_ids.add(survivor)   # survivor no puede absorber más en este batch

                    logger.debug(
                        f"consolidation: merged_ids=[{absorbed}] into survivor={survivor} sim={sim:.3f} new_weight={new_fw:.3f}",
                        extra={"op": "consolidation._consolidate_batch",
                               "context": f"sim={sim:.3f} survivor={survivor} absorbed={absorbed}"},
                    )
                    break  # un merge por episodio por batch

        if not to_merge:
            return 0

        try:
            conn = _db_connect(self.db_path)
            now = datetime.now().isoformat()
            for survivor, absorbed, new_vec, new_conf, new_imp, new_fw in to_merge:
                # Actualizar el survivor con el vector fusionado
                conn.execute("""
                    UPDATE episodic_memory
                    SET vector=?, confidence=?, importance=?, feedback_weight=?, last_access=?
                    WHERE id=?
                """, (json.dumps(new_vec), round(new_conf, 4),
                      round(new_imp, 4), round(new_fw, 4), now, survivor))
                # Soft-delete el absorbido
                conn.execute(
                    "UPDATE episodic_memory SET forgotten=1, last_access=? WHERE id=?",
                    (now, absorbed)
                )
            conn.commit()
            conn.close()
        except Exception as exc:
            log_db_error(logger, "consolidation._consolidate_batch.write", exc)
            return 0

        return len(to_merge)

    # ─────────────────────────────────────────────────────────────────
    # FASE 4: REINFORCE — refuerzo de memorias valiosas
    # ─────────────────────────────────────────────────────────────────

    def _phase_reinforce(self, limit: int = MAX_REINFORCE_PER_CYCLE) -> int:
        """
        Episodios con feedback muy positivo Y alta frecuencia de uso
        reciben un pequeño boost de confianza.
        Esto asegura que el conocimiento útil llegue al techo de confianza
        de forma orgánica, no solo por aprendizaje explícito.
        """
        try:
            conn = _db_connect(self.db_path)
            rows = conn.execute("""
                SELECT id, confidence
                FROM episodic_memory
                WHERE forgotten = 0
                  AND COALESCE(feedback_weight, 1.0) >= ?
                  AND COALESCE(access_count, 0)     >= ?
                  AND confidence                    <  ?
                ORDER BY feedback_weight DESC, access_count DESC
                LIMIT ?
            """, (REINFORCE_WEIGHT_MIN, REINFORCE_ACCESS_MIN,
                  REINFORCE_CONF_MAX, limit)).fetchall()

            if not rows:
                conn.close()
                return 0

            updates = []
            for ep_id, conf in rows:
                new_conf = min(REINFORCE_CONF_MAX, float(conf) + REINFORCE_CONF_DELTA)
                updates.append((round(new_conf, 4), ep_id))

            conn.executemany(
                "UPDATE episodic_memory SET confidence=? WHERE id=?", updates
            )
            conn.commit()
            conn.close()

            logger.debug(
                f"Reinforce: {len(updates)} episodios reforzados",
                extra={"op": "consolidation._phase_reinforce",
                       "context": f"delta={REINFORCE_CONF_DELTA} weight_min={REINFORCE_WEIGHT_MIN}"},
            )
            return len(updates)

        except Exception as exc:
            log_db_error(logger, "consolidation._phase_reinforce", exc)
            return 0

    # ─────────────────────────────────────────────────────────────────
    # FASE 5: DECAY — decaimiento de memorias no usadas
    # ─────────────────────────────────────────────────────────────────

    def _phase_decay(self, limit: int = MAX_DECAY_PER_CYCLE) -> int:
        """
        Reduce gradualmente la importancia de episodios no accedidos.

        Decay dinámico (Fase 2):
          - Base: DECAY_IMPORTANCE_FACTOR
          - Alta emoción (|emotion_score| > 0.5) → decae más lento:
                factor_real = factor * (1 - abs(emotion_score) * 0.5)
          - Sin accesos (access_count == 0) → decae más rápido:
                factor_real = factor * 1.5
          - Ambas condiciones se evalúan independientemente y se combinan.

        Fórmula: new_imp = imp - factor_real * (imp - DECAY_IMPORTANCE_MIN)
        Converge a DECAY_IMPORTANCE_MIN sin cruzarlo nunca.

        NO toca feedback_weight — responsabilidad del FeedbackEngine.
        """
        cutoff = _days_ago(DECAY_LAST_ACCESS_DAYS)
        try:
            conn = _db_connect(self.db_path)
            rows = conn.execute("""
                SELECT id, importance,
                       COALESCE(emotion_score, 0.0),
                       COALESCE(access_count, 0)
                FROM episodic_memory
                WHERE forgotten = 0
                  AND importance > ?
                  AND COALESCE(last_access, timestamp) < ?
                ORDER BY importance DESC
                LIMIT ?
            """, (DECAY_IMPORTANCE_MIN + 0.01, cutoff, limit)).fetchall()

            if not rows:
                conn.close()
                return 0

            updates = []
            for ep_id, imp, emotion_score, access_count in rows:
                imp   = float(imp)
                emo   = float(emotion_score)
                acc   = int(access_count)

                factor = DECAY_IMPORTANCE_FACTOR

                # Alta emoción → memoria más persistente (decae más lento)
                if abs(emo) > 0.5:
                    factor = factor * (1.0 - abs(emo) * 0.5)

                # Sin ningún acceso → decae más rápido
                if acc == 0:
                    factor = factor * 1.5

                new_imp = imp - factor * (imp - DECAY_IMPORTANCE_MIN)
                new_imp = max(DECAY_IMPORTANCE_MIN, round(new_imp, 4))
                if abs(new_imp - imp) > 0.0001:
                    updates.append((new_imp, ep_id))

            if updates:
                conn.executemany(
                    "UPDATE episodic_memory SET importance=? WHERE id=?", updates
                )
                conn.commit()

            conn.close()

            logger.debug(
                f"Decay dinámico: {len(updates)} episodios con importancia reducida",
                extra={"op": "consolidation._phase_decay",
                       "context": f"cutoff_days={DECAY_LAST_ACCESS_DAYS} "
                                  f"base_factor={DECAY_IMPORTANCE_FACTOR}"},
            )
            return len(updates)

        except Exception as exc:
            log_db_error(logger, "consolidation._phase_decay", exc)
            return 0

    # ─────────────────────────────────────────────────────────────────
    # FASE 6: DEDUP SEMÁNTICO — eliminar conceptos redundantes
    # ─────────────────────────────────────────────────────────────────

    def _phase_semantic_dedup(self, limit: int = MAX_DEDUP_SEMANTIC) -> int:
        """
        Detecta conceptos semánticos muy similares (mismo espacio vectorial)
        y elimina el de menor soporte, transfiriendo sus asociaciones al ganador.

        Solo opera sobre conceptos con soporte bajo (< DEDUP_MIN_SUPPORT),
        para no tocar conocimiento bien consolidado.
        """
        try:
            conn = _db_connect(self.db_path)
            rows = conn.execute("""
                SELECT concept, vector, confidence, support, associations
                FROM semantic_memory
                ORDER BY support DESC, confidence DESC
                LIMIT ?
            """, (min(limit * 5, 300),)).fetchall()
            conn.close()
        except Exception as exc:
            log_db_error(logger, "consolidation._phase_semantic_dedup", exc)
            return 0

        if len(rows) < 2:
            return 0

        # Parsear vectores
        parsed = []
        for row in rows:
            concept, vec_str, conf, support, assoc_str = row
            try:
                vec = json.loads(vec_str)
                parsed.append((concept, vec, float(conf), int(support or 1), assoc_str))
            except (json.JSONDecodeError, TypeError):
                continue

        to_delete = []
        processed = set()

        for i in range(len(parsed)):
            if parsed[i][0] in processed:
                continue
            c_a, v_a, conf_a, sup_a, assoc_a = parsed[i]

            for j in range(i + 1, len(parsed)):
                if parsed[j][0] in processed:
                    continue
                c_b, v_b, conf_b, sup_b, assoc_b = parsed[j]

                sim = _cosine(v_a, v_b)
                if sim >= DEDUP_SIM_THRESHOLD:
                    # El de mayor soporte sobrevive
                    if sup_a >= sup_b:
                        winner, loser = c_a, c_b
                    else:
                        winner, loser = c_b, c_a

                    # Solo eliminar el loser si tiene poco soporte
                    loser_sup = sup_b if winner == c_a else sup_a
                    if loser_sup < DEDUP_MIN_SUPPORT:
                        to_delete.append((winner, loser))
                        processed.add(loser)
                        logger.debug(
                            f"consolidation: sem_dedup winner='{winner}' loser='{loser}' sim={sim:.3f}",
                            extra={"op": "consolidation._phase_semantic_dedup",
                                   "context": f"sim={sim:.3f} loser_support={loser_sup}"},
                        )
                    break

            if len(to_delete) >= limit:
                break

        if not to_delete:
            return 0

        try:
            conn = _db_connect(self.db_path)
            for winner, loser in to_delete:
                # Transferir asociaciones del loser al winner antes de borrar
                self._transfer_associations(conn, winner, loser)
                conn.execute(
                    "DELETE FROM semantic_memory WHERE concept=?", (loser,)
                )
            conn.commit()
            conn.close()
        except Exception as exc:
            log_db_error(logger, "consolidation._phase_semantic_dedup.delete", exc)
            return 0

        logger.info(
            f"Semantic dedup: {len(to_delete)} conceptos eliminados",
            extra={"op": "consolidation._phase_semantic_dedup",
                   "context": f"deleted={[lo for _, lo in to_delete[:5]]}"},
        )
        return len(to_delete)

    def _transfer_associations(self, conn: sqlite3.Connection,
                               winner: str, loser: str) -> None:
        """
        Transfiere las asociaciones del loser al winner antes de eliminar el loser.
        Las asociaciones existentes en el winner toman precedencia (no se sobrescriben).
        """
        try:
            row_w = conn.execute(
                "SELECT associations FROM semantic_memory WHERE concept=?", (winner,)
            ).fetchone()
            row_l = conn.execute(
                "SELECT associations FROM semantic_memory WHERE concept=?", (loser,)
            ).fetchone()
            if not row_w or not row_l:
                return

            assoc_w = json.loads(row_w[0] or "{}")
            assoc_l = json.loads(row_l[0] or "{}")

            # Mezcla: winner conserva sus valores, solo agrega los del loser que no tiene
            for concept, strength in assoc_l.items():
                if concept != winner and concept not in assoc_w:
                    assoc_w[concept] = strength * 0.7   # reducir peso transferido

            conn.execute(
                "UPDATE semantic_memory SET associations=? WHERE concept=?",
                (json.dumps(assoc_w), winner)
            )
        except (json.JSONDecodeError, TypeError, Exception):
            pass  # No crítico — solo una optimización

    # ─────────────────────────────────────────────────────────────────
    # SCHEMA y REGISTRO
    # ─────────────────────────────────────────────────────────────────

    def _init_schema(self) -> None:
        """
        Crea la tabla de auditoría consolidation_log.
        Migración aditiva — seguro ejecutar múltiples veces.
        """
        try:
            conn = _db_connect(self.db_path)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS consolidation_log (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp    TEXT    NOT NULL,
                    cycle_type   TEXT    NOT NULL,
                    purged       INTEGER DEFAULT 0,
                    weakened     INTEGER DEFAULT 0,
                    consolidated INTEGER DEFAULT 0,
                    reinforced   INTEGER DEFAULT 0,
                    decayed      INTEGER DEFAULT 0,
                    sem_deduped  INTEGER DEFAULT 0,
                    elapsed_ms   REAL    DEFAULT 0
                )
            """)
            conn.commit()
            conn.close()
            logger.debug(
                "Schema PASO 6 inicializado",
                extra={"op": "consolidation._init_schema",
                       "context": f"db={self.db_path}"},
            )
        except Exception as exc:
            log_db_error(logger, "consolidation._init_schema", exc,
                         extra_ctx=f"db_path={self.db_path}")

    def _record_cycle(self, result: ConsolidationResult) -> None:
        """Guarda un registro en consolidation_log para auditoría."""
        try:
            conn = _db_connect(self.db_path)
            conn.execute("""
                INSERT INTO consolidation_log
                (timestamp, cycle_type, purged, weakened, consolidated,
                 reinforced, decayed, sem_deduped, elapsed_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (datetime.now().isoformat(), result.cycle_type,
                  result.purged, result.weakened, result.consolidated,
                  result.reinforced, result.decayed, result.sem_deduped,
                  result.elapsed_ms))
            conn.commit()
            conn.close()
        except Exception as exc:
            log_db_error(logger, "consolidation._record_cycle", exc)


# ══════════════════════════════════════════════════════════════════════
# SINGLETON
# ══════════════════════════════════════════════════════════════════════

_ENGINE: Optional[ConsolidationEngine] = None
_ENGINE_LOCK = threading.Lock()


def get_consolidation_engine(
    db_path: str = "cognia_memory.db",
    consolidation_interval: int = DEFAULT_CONSOLIDATION_INTERVAL,
) -> ConsolidationEngine:
    """
    Retorna la instancia singleton del motor de consolidación.
    Thread-safe — seguro llamar desde múltiples hilos.
    """
    global _ENGINE
    if _ENGINE is None:
        with _ENGINE_LOCK:
            if _ENGINE is None:
                _ENGINE = ConsolidationEngine(db_path, consolidation_interval)
    return _ENGINE
