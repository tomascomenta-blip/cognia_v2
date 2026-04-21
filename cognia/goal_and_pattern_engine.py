"""
goal_and_pattern_engine.py — Cognia PASO 7 + PASO 8
=====================================================
Módulo integrador plug-and-play que implementa:

  PASO 7 — Sistema de objetivos (goal-driven)
    • GoalState          — estructura interna del objetivo activo
    • GoalDetector       — extrae objetivo desde el input del usuario
    • GoalManager        — persiste y actualiza el objetivo entre turnos
    • Integración con memoria episódica y generación de respuesta

  PASO 8 — Aprendizaje por patrones
    • PatternAnalyzer    — analiza historial de interacciones
    • RelationExtractor  — detecta co-ocurrencias y genera relaciones semánticas
    • PatternLearner     — actualiza la memoria semántica en batch
    • BatchScheduler     — controla la ejecución, evita procesar en cada turno

DISEÑO:
  - Cero dependencias nuevas (solo stdlib + lo ya presente en Cognia)
  - Thread-safe con un único lock por componente
  - Optimizado para CPU 2 núcleos / 12 GB RAM
  - Operaciones costosas solo en batch (sleep / cada N interacciones)
  - Nunca rompe la lógica existente: todos los hooks son no-invasivos

INTEGRACIÓN (3 puntos de contacto):
  A. cognia.py  __init__  → importar GoalAndPatternEngine, instanciarlo
  B. cognia.py  observe() → llamar engine.pre_observe() y engine.post_observe()
  C. cognia.py  sleep()   → llamar engine.run_pattern_batch()

  language_engine.py respond() → pasar engine.active_goal_hint() al contexto
  (opcional pero recomendado — mejora alineación de respuestas con el objetivo)

LOGGING:
  Todos los eventos usan el logger_config existente con campos op/context.

EJEMPLO DE USO MÍNIMO (desde cognia.py):

    # __init__
    try:
        from goal_and_pattern_engine import GoalAndPatternEngine
        self._goal_engine = GoalAndPatternEngine(db_path)
        print("✅ GoalAndPatternEngine PASOS 7+8 activo")
    except ImportError:
        self._goal_engine = None

    # observe() — al inicio del método
    if self._goal_engine:
        self._goal_engine.pre_observe(observation, vec)

    # observe() — al final del método, justo antes del return
    if self._goal_engine:
        self._goal_engine.post_observe(observation, result)
        self._goal_engine.tick(self.interaction_count)

    # sleep()
    if self._goal_engine:
        pattern_info = self._goal_engine.run_pattern_batch()
        # incluir pattern_info en el string de retorno si se desea

    # language_engine o respuestas_articuladas — al construir contexto
    if hasattr(ai, '_goal_engine') and ai._goal_engine:
        goal_hint = ai._goal_engine.active_goal_hint()
        if goal_hint:
            context = goal_hint + "\\n\\n" + context
"""

from __future__ import annotations

import json
import math
import sqlite3
import threading
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from logger_config import get_logger, log_db_error

logger = get_logger(__name__)


# ══════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ══════════════════════════════════════════════════════════════════════

# — PASO 7: Objetivos —
GOAL_CHANGE_SIM_THRESHOLD   = 0.30   # similitud < este valor → cambio de objetivo
GOAL_TTL_TURNS              = 15     # turnos máximos que vive un objetivo sin refuerzo
GOAL_MIN_CONFIDENCE         = 0.25   # confianza mínima para activar un objetivo
GOAL_PRIORITY_DECAY         = 0.05   # decaimiento de prioridad por turno sin mención
GOAL_CONTEXT_TURNS          = 3      # turnos previos a considerar para detectar objetivo

# — PASO 8: Patrones —
PATTERN_BATCH_INTERVAL      = 25     # cada N interacciones ejecutar análisis de patrones
PATTERN_MIN_COOCCURRENCE    = 3      # mínimas co-ocurrencias para crear relación
PATTERN_MIN_CONCEPT_SUPPORT = 2      # soporte mínimo del concepto para participar
PATTERN_RELATION_STRENGTH   = 0.25   # fuerza base de las relaciones detectadas
PATTERN_MAX_CONCEPTS_BATCH  = 80     # máximo de conceptos a analizar por batch
PATTERN_MAX_NEW_RELATIONS   = 20     # máximo de relaciones nuevas por batch
PATTERN_HISTORY_WINDOW      = 200    # últimas N interacciones a analizar

# — Palabras de parada para detección de objetivos —
_STOP_WORDS = {
    "el", "la", "los", "las", "un", "una", "unos", "unas",
    "de", "del", "al", "en", "y", "o", "que", "qué", "cómo",
    "cuál", "cuáles", "es", "son", "para", "por", "con", "sin",
    "me", "te", "se", "le", "lo", "quiero", "puedo", "puede",
    "hay", "haz", "dame", "dime", "cuánto", "cuántos", "cuántas",
    "the", "a", "an", "of", "is", "are", "how", "what", "which",
    "can", "do", "does", "give", "tell", "me", "you", "it",
}

# — Verbos de objetivo (indican intención del usuario) —
_GOAL_VERBS = [
    "aprender", "entender", "comprender", "saber", "conocer",
    "crear", "hacer", "construir", "desarrollar", "implementar",
    "resolver", "arreglar", "encontrar", "buscar", "investigar",
    "mejorar", "optimizar", "analizar", "comparar", "explicar",
    "learn", "understand", "know", "create", "build", "make",
    "solve", "find", "search", "improve", "analyze", "explain",
]


# ══════════════════════════════════════════════════════════════════════
# PASO 7 — ESTRUCTURAS DE OBJETIVO
# ══════════════════════════════════════════════════════════════════════

@dataclass
class GoalState:
    """Representación del objetivo activo del usuario."""
    goal_text:      str             # texto del objetivo
    keywords:       List[str]       # palabras clave extraídas
    vector:         List[float]     # embedding del objetivo
    priority:       float           # 0.0-1.0
    confidence:     float           # qué tan seguro estamos del objetivo
    context:        str             # contexto asociado
    created_at:     float = field(default_factory=time.time)
    last_confirmed: float = field(default_factory=time.time)
    turn_count:     int   = 0       # turnos desde que fue detectado
    reinforcements: int   = 0       # veces que el usuario reforzó este objetivo

    def age_turns(self) -> int:
        return self.turn_count

    def is_expired(self) -> bool:
        return self.turn_count > GOAL_TTL_TURNS and self.priority < 0.30

    def decay(self):
        """Decaimiento de prioridad por turno sin mención explícita."""
        self.turn_count += 1
        self.priority = max(0.10, self.priority - GOAL_PRIORITY_DECAY)

    def reinforce(self, sim: float):
        """Refuerzo cuando el nuevo input es coherente con el objetivo."""
        self.reinforcements += 1
        self.last_confirmed = time.time()
        self.priority = min(1.0, self.priority + sim * 0.15)
        self.turn_count = 0   # resetear contador de inactividad

    def to_dict(self) -> dict:
        return {
            "goal_text":      self.goal_text,
            "keywords":       self.keywords,
            "priority":       round(self.priority, 3),
            "confidence":     round(self.confidence, 3),
            "context":        self.context,
            "turn_count":     self.turn_count,
            "reinforcements": self.reinforcements,
        }


# ══════════════════════════════════════════════════════════════════════
# PASO 7 — DETECTOR DE OBJETIVO
# ══════════════════════════════════════════════════════════════════════

class GoalDetector:
    """
    Extrae el objetivo del usuario a partir del texto de entrada.

    Estrategia (sin modelos extra, solo heurísticas lingüísticas):
      1. Buscar verbos de objetivo en el texto
      2. Extraer las N palabras más relevantes (filtrar stop-words)
      3. Calcular confianza basada en señales textuales
      4. Comparar con objetivo activo para detectar continuidad o cambio
    """

    def detect(self, text: str,
               conversation_history: List[str],
               active_goal: Optional[GoalState]) -> Tuple[Optional[str], float, List[str]]:
        """
        Detecta el objetivo en el texto.

        Returns:
            (goal_text, confidence, keywords)
            goal_text = None si no se detecta objetivo claro
        """
        text_lower = text.lower().strip()
        words = [w.strip(".,;:?!¿¡()\"'") for w in text_lower.split()]
        words = [w for w in words if len(w) > 2 and w not in _STOP_WORDS]

        # Calcular señales
        has_goal_verb = any(v in text_lower for v in _GOAL_VERBS)
        has_question  = "?" in text or text_lower.startswith(("qué", "cómo", "cuál",
                                                               "por qué", "what", "how"))
        is_command    = any(text_lower.startswith(v) for v in _GOAL_VERBS[:10])
        has_context   = len(conversation_history) > 0

        # Confianza inicial
        confidence = 0.0
        if has_goal_verb:  confidence += 0.40
        if has_question:   confidence += 0.20
        if is_command:     confidence += 0.30
        if has_context:    confidence += 0.10

        # Si la confianza es muy baja y hay un objetivo activo, heredar
        if confidence < GOAL_MIN_CONFIDENCE and active_goal:
            logger.debug(
                "Objetivo débil — heredando objetivo activo",
                extra={"op": "goal_detector.detect",
                       "context": f"conf={confidence:.2f} active={active_goal.goal_text[:40]}"},
            )
            return None, confidence, words

        # Extraer keywords (las palabras más largas/informativas)
        keywords = sorted(words, key=len, reverse=True)[:6]

        # Construir texto del objetivo (máx 80 chars)
        goal_text = text[:80].strip()

        logger.debug(
            "Objetivo detectado",
            extra={"op": "goal_detector.detect",
                   "context": f"conf={confidence:.2f} keywords={keywords[:3]} "
                              f"verb={has_goal_verb} question={has_question}"},
        )
        return goal_text, min(1.0, confidence), keywords


# ══════════════════════════════════════════════════════════════════════
# PASO 7 — GESTOR DE OBJETIVO
# ══════════════════════════════════════════════════════════════════════

class GoalManager:
    """
    Mantiene el objetivo activo entre turnos.

    Ciclo de vida:
      detect_and_update(input, vec) → actualiza estado interno
      get_active() → retorna GoalState o None
      active_goal_hint() → string listo para inyectar en el prompt
    """

    def __init__(self):
        self._active: Optional[GoalState] = None
        self._history: List[GoalState]    = []   # historial de objetivos completados
        self._detector = GoalDetector()
        self._lock = threading.Lock()
        self._conversation_hints: List[str] = []  # últimos N inputs para contexto

    def detect_and_update(self, text: str, vec: List[float]) -> Optional[GoalState]:
        """
        Analiza el input y actualiza el objetivo activo.
        Retorna el GoalState activo (puede ser el mismo o uno nuevo).
        """
        with self._lock:
            # Actualizar historial de conversación
            self._conversation_hints.append(text[:120])
            if len(self._conversation_hints) > GOAL_CONTEXT_TURNS:
                self._conversation_hints.pop(0)

            # Detectar objetivo en el texto actual
            goal_text, confidence, keywords = self._detector.detect(
                text, self._conversation_hints[:-1], self._active
            )

            # Sin objetivo detectado y hay uno activo: decaer y mantener
            if goal_text is None:
                if self._active:
                    self._active.decay()
                    if self._active.is_expired():
                        logger.info(
                            "Objetivo expirado por inactividad",
                            extra={"op": "goal_manager.expire",
                                   "context": f"goal={self._active.goal_text[:40]} "
                                              f"turns={self._active.turn_count}"},
                        )
                        self._history.append(self._active)
                        self._active = None
                return self._active

            # Calcular similitud con objetivo activo
            if self._active and vec:
                sim = _cosine(vec, self._active.vector) if self._active.vector else 0.0

                if sim >= GOAL_CHANGE_SIM_THRESHOLD:
                    # Reforzar objetivo existente
                    self._active.reinforce(sim)
                    logger.debug(
                        "Objetivo reforzado",
                        extra={"op": "goal_manager.reinforce",
                               "context": f"sim={sim:.3f} priority={self._active.priority:.2f} "
                                          f"goal={self._active.goal_text[:40]}"},
                    )
                    return self._active
                else:
                    # Cambio de objetivo
                    logger.info(
                        "Cambio de objetivo detectado",
                        extra={"op": "goal_manager.change",
                               "context": f"sim={sim:.3f} "
                                          f"old={self._active.goal_text[:40]} "
                                          f"new={goal_text[:40]}"},
                    )
                    self._history.append(self._active)

            # Crear nuevo objetivo
            new_goal = GoalState(
                goal_text  = goal_text,
                keywords   = keywords,
                vector     = vec[:] if vec else [],
                priority   = 0.60 + confidence * 0.40,
                confidence = confidence,
                context    = " | ".join(self._conversation_hints[-2:]),
            )
            self._active = new_goal
            logger.info(
                "Nuevo objetivo activo",
                extra={"op": "goal_manager.new_goal",
                       "context": f"goal={goal_text[:60]} "
                                  f"priority={new_goal.priority:.2f} "
                                  f"keywords={keywords[:3]}"},
            )
            return self._active

    def get_active(self) -> Optional[GoalState]:
        with self._lock:
            return self._active

    def active_goal_hint(self) -> str:
        """
        Genera el bloque de texto para inyectar en el prompt/contexto.
        Retorna "" si no hay objetivo activo o es muy débil.
        """
        with self._lock:
            if not self._active or self._active.priority < 0.25:
                return ""
            g = self._active
            kw = ", ".join(g.keywords[:4]) if g.keywords else ""
            hint = (
                f"OBJETIVO DEL USUARIO (prioridad={g.priority:.0%}): "
                f"{g.goal_text}"
            )
            if kw:
                hint += f" | temas clave: {kw}"
            return hint

    def goal_aware_memory_boost(self, memories: List[dict]) -> List[dict]:
        """
        PASO 7: Re-puntúa memorias recuperadas para priorizar las relacionadas
        con el objetivo activo.

        Recibe lista de memorias con campo 'score' (float) y 'observation' (str).
        Retorna la misma lista con scores ajustados (ordenada por score desc).
        """
        with self._lock:
            goal = self._active

        if not goal or not goal.vector or not memories:
            return memories

        boosted = []
        for mem in memories:
            try:
                obs_vec = mem.get("_vec")   # vector pre-calculado si existe
                if obs_vec is None:
                    # No tenemos vector de la memoria — boost superficial por keywords
                    obs_text = mem.get("observation", "").lower()
                    kw_hits  = sum(1 for kw in goal.keywords if kw in obs_text)
                    boost    = kw_hits * 0.05
                else:
                    sim   = _cosine(goal.vector, obs_vec)
                    boost = sim * 0.20 * goal.priority

                new_score = mem.get("score", 0.0) + boost
                boosted.append({**mem, "score": new_score, "_goal_boost": round(boost, 4)})
            except Exception as exc:
                logger.warning(
                    "Error aplicando goal boost a memoria",
                    extra={"op": "goal_manager.boost",
                           "context": f"err={exc}"},
                )
                boosted.append(mem)

        boosted.sort(key=lambda x: x["score"], reverse=True)
        return boosted

    def stats(self) -> dict:
        with self._lock:
            return {
                "active_goal":        self._active.to_dict() if self._active else None,
                "history_count":      len(self._history),
                "conversation_turns": len(self._conversation_hints),
            }


# ══════════════════════════════════════════════════════════════════════
# PASO 8 — ANALIZADOR DE PATRONES
# ══════════════════════════════════════════════════════════════════════

class PatternAnalyzer:
    """
    Analiza el historial de interacciones y detecta:
      - Temas frecuentes (conceptos que aparecen juntos)
      - Co-ocurrencias → relaciones semánticas potenciales
    """

    def analyze_history(self, db_path: str,
                        window: int = PATTERN_HISTORY_WINDOW
                        ) -> Tuple[List[str], Dict[Tuple[str, str], int]]:
        """
        Lee los últimos `window` episodios y extrae:
          - frequent_labels:  etiquetas más comunes
          - cooccurrences:    (label_a, label_b) → count

        Returns:
            (frequent_labels, cooccurrences)
        """
        try:
            conn = sqlite3.connect(db_path)
            conn.text_factory = str
            c = conn.cursor()
            c.execute("""
                SELECT label, observation
                FROM episodic_memory
                WHERE forgotten = 0 AND label IS NOT NULL AND label != ''
                ORDER BY id DESC
                LIMIT ?
            """, (window,))
            rows = c.fetchall()
            conn.close()
        except Exception as exc:
            log_db_error(logger, "pattern_analyzer.analyze_history", exc,
                         extra_ctx=f"window={window}")
            return [], {}

        if not rows:
            return [], {}

        # Conteo de etiquetas
        label_counter: Counter = Counter()
        # Grupos de etiquetas por "sesión" (ventana deslizante de 5)
        labels_sequence = [r[0] for r in rows if r[0]]
        for label in labels_sequence:
            label_counter[label] += 1

        # Co-ocurrencias en ventana deslizante de 5
        cooccurrences: Dict[Tuple[str, str], int] = defaultdict(int)
        window_size = 5
        for i in range(len(labels_sequence)):
            window_labels = labels_sequence[i:i + window_size]
            unique_in_window = list(set(window_labels))
            for j in range(len(unique_in_window)):
                for k in range(j + 1, len(unique_in_window)):
                    la, lb = sorted([unique_in_window[j], unique_in_window[k]])
                    cooccurrences[(la, lb)] += 1

        # Frecuentes: mínimo 2 ocurrencias
        frequent_labels = [
            label for label, count in label_counter.most_common(PATTERN_MAX_CONCEPTS_BATCH)
            if count >= 2
        ]

        logger.info(
            "Análisis de historial completado",
            extra={"op": "pattern_analyzer.analyze",
                   "context": f"episodes={len(rows)} frequent={len(frequent_labels)} "
                              f"cooccurrences={len(cooccurrences)}"},
        )
        return frequent_labels, dict(cooccurrences)


# ══════════════════════════════════════════════════════════════════════
# PASO 8 — EXTRACTOR DE RELACIONES
# ══════════════════════════════════════════════════════════════════════

class RelationExtractor:
    """
    Convierte co-ocurrencias estadísticas en relaciones semánticas
    con un tipo inferido heurísticamente.
    """

    # Mapa de etiqueta → predicado heurístico
    _PREDICATE_HINTS = {
        ("inteligencia_artificial", "machine_learning"):  "incluye",
        ("machine_learning", "deep_learning"):             "incluye",
        ("python", "machine_learning"):                    "se_usa_en",
        ("neuroplasticidad", "aprendizaje"):               "relacionado_con",
    }

    def extract(self, cooccurrences: Dict[Tuple[str, str], int],
                min_count: int = PATTERN_MIN_COOCCURRENCE,
                max_relations: int = PATTERN_MAX_NEW_RELATIONS
                ) -> List[Dict]:
        """
        Extrae relaciones desde co-ocurrencias.

        Returns:
            Lista de dicts: {concept_a, concept_b, predicate, strength, count}
        """
        relations = []
        # Ordenar por frecuencia descendente
        sorted_pairs = sorted(cooccurrences.items(), key=lambda x: x[1], reverse=True)

        for (la, lb), count in sorted_pairs:
            if count < min_count:
                continue
            if len(relations) >= max_relations:
                break

            # Calcular fuerza basada en frecuencia (normalizada log)
            strength = min(1.0, PATTERN_RELATION_STRENGTH + math.log(count + 1) * 0.08)

            # Intentar inferir predicado
            predicate = self._infer_predicate(la, lb)

            relations.append({
                "concept_a": la,
                "concept_b": lb,
                "predicate": predicate,
                "strength":  round(strength, 3),
                "count":     count,
            })

        logger.info(
            "Relaciones extraídas de co-ocurrencias",
            extra={"op": "relation_extractor.extract",
                   "context": f"pairs_analyzed={len(sorted_pairs)} "
                              f"relations_created={len(relations)}"},
        )
        return relations

    def _infer_predicate(self, la: str, lb: str) -> str:
        """Heurística simple para asignar predicado a una relación."""
        key = (la, lb)
        if key in self._PREDICATE_HINTS:
            return self._PREDICATE_HINTS[key]
        key_rev = (lb, la)
        if key_rev in self._PREDICATE_HINTS:
            return self._PREDICATE_HINTS[key_rev]

        # Por longitud de nombre: el más específico (más largo) es "parte de" el general
        if len(lb) > len(la) + 5:
            return "es_parte_de"
        if len(la) > len(lb) + 5:
            return "incluye"
        return "relacionado_con"


# ══════════════════════════════════════════════════════════════════════
# PASO 8 — APRENDEDOR DE PATRONES (batch)
# ══════════════════════════════════════════════════════════════════════

class PatternLearner:
    """
    Integra los patrones detectados en la memoria semántica de Cognia.

    No modifica episodic_memory. Solo actualiza/crea relaciones en
    semantic_memory usando los métodos existentes de SemanticMemory.
    """

    def run_batch(self, db_path: str,
                  semantic_memory,    # instancia de cognia.memory.SemanticMemory
                  ) -> dict:
        """
        Ejecuta el ciclo completo de aprendizaje por patrones.

        Args:
            db_path:         ruta a la DB SQLite
            semantic_memory: instancia de SemanticMemory (ya instanciada en Cognia)

        Returns:
            dict con estadísticas del ciclo
        """
        t0 = time.perf_counter()

        analyzer  = PatternAnalyzer()
        extractor = RelationExtractor()

        # 1. Analizar historial
        frequent_labels, cooccurrences = analyzer.analyze_history(db_path)

        if not frequent_labels:
            logger.info(
                "Sin datos suficientes para aprendizaje por patrones",
                extra={"op": "pattern_learner.run_batch", "context": "no_data"},
            )
            return {"relations_created": 0, "concepts_reinforced": 0,
                    "elapsed_ms": 0.0, "skipped": True}

        # 2. Extraer relaciones
        relations = extractor.extract(cooccurrences)

        # 3. Actualizar memoria semántica
        relations_created  = 0
        concepts_reinforced = 0

        for rel in relations:
            ca = rel["concept_a"]
            cb = rel["concept_b"]
            strength = rel["strength"]

            # Verificar que ambos conceptos existen en semantic_memory
            # antes de crear la relación (evitar ruido)
            try:
                ca_exists = semantic_memory.get_concept(ca) is not None
                cb_exists = semantic_memory.get_concept(cb) is not None
            except Exception:
                continue

            if ca_exists and cb_exists:
                try:
                    semantic_memory.add_association(ca, cb, strength=strength)
                    semantic_memory.add_association(cb, ca, strength=strength * 0.7)
                    relations_created += 1
                    logger.debug(
                        "Relación semántica creada por patrón",
                        extra={"op": "pattern_learner.add_relation",
                               "context": f"{ca} <-> {cb} "
                                          f"pred={rel['predicate']} "
                                          f"strength={strength:.3f} "
                                          f"count={rel['count']}"},
                    )
                except Exception as exc:
                    logger.warning(
                        "Error creando relación semántica",
                        extra={"op": "pattern_learner.add_relation",
                               "context": f"err={exc} pair={ca}/{cb}"},
                    )

        # 4. Reforzar conceptos frecuentes en semantic_memory
        # (incrementar confidence_delta levemente para concepts bien observados)
        for label in frequent_labels[:20]:
            try:
                concept = semantic_memory.get_concept(label)
                if concept and concept.get("support", 0) >= PATTERN_MIN_CONCEPT_SUPPORT:
                    semantic_memory.update_concept(
                        label,
                        concept["vector"],
                        description=concept.get("description", ""),
                        confidence_delta=0.02,
                        emotion_score=concept.get("emotion_avg", 0.0),
                    )
                    concepts_reinforced += 1
            except Exception as exc:
                logger.warning(
                    "Error reforzando concepto",
                    extra={"op": "pattern_learner.reinforce",
                           "context": f"label={label} err={exc}"},
                )

        elapsed_ms = (time.perf_counter() - t0) * 1000

        logger.info(
            "Ciclo de aprendizaje por patrones completado",
            extra={"op": "pattern_learner.run_batch",
                   "context": f"relations={relations_created} "
                              f"reinforced={concepts_reinforced} "
                              f"elapsed_ms={elapsed_ms:.1f}"},
        )
        return {
            "relations_created":  relations_created,
            "concepts_reinforced": concepts_reinforced,
            "frequent_labels":    frequent_labels[:10],
            "elapsed_ms":         round(elapsed_ms, 1),
            "skipped":            False,
        }


# ══════════════════════════════════════════════════════════════════════
# SCHEDULER (controla ejecución del batch)
# ══════════════════════════════════════════════════════════════════════

class BatchScheduler:
    """
    Controla cuándo ejecutar el batch de patrones.
    Evita procesar en cada interacción (demasiado costoso).
    """

    def __init__(self, interval: int = PATTERN_BATCH_INTERVAL):
        self._interval       = interval
        self._last_run_count = 0
        self._run_count      = 0

    def should_run(self, interaction_count: int) -> bool:
        if interaction_count - self._last_run_count >= self._interval:
            return True
        return False

    def mark_ran(self, interaction_count: int):
        self._last_run_count = interaction_count
        self._run_count += 1

    @property
    def total_runs(self) -> int:
        return self._run_count


# ══════════════════════════════════════════════════════════════════════
# FACHADA PRINCIPAL — GoalAndPatternEngine
# ══════════════════════════════════════════════════════════════════════

class GoalAndPatternEngine:
    """
    Fachada plug-and-play para PASOS 7 y 8.

    Un único objeto a instanciar en cognia.py __init__:

        self._goal_engine = GoalAndPatternEngine(db_path)

    Expone 4 métodos de integración:

        pre_observe(observation, vec)         — antes del ciclo observe
        post_observe(observation, result)     — después del ciclo observe
        tick(interaction_count)               — llamar al final de observe
        run_pattern_batch()                   — llamar desde sleep()
        active_goal_hint()                    — string para el prompt LLM
        goal_aware_boost(memories)            — re-rankear memorias
        stats()                               — diagnóstico
    """

    def __init__(self, db_path: str = "cognia_memory.db"):
        self.db_path        = db_path
        self.goal_manager   = GoalManager()
        self.pattern_learner = PatternLearner()
        self.scheduler      = BatchScheduler()
        self._lock          = threading.Lock()
        self._last_vec: Optional[List[float]] = None

        logger.info(
            "GoalAndPatternEngine inicializado",
            extra={"op": "goal_pattern_engine.init",
                   "context": f"db={db_path} "
                              f"batch_interval={PATTERN_BATCH_INTERVAL} "
                              f"goal_ttl_turns={GOAL_TTL_TURNS}"},
        )

    # ── HOOK 1: antes del ciclo observe ───────────────────────────────

    def pre_observe(self, observation: str, vec: Optional[List[float]]) -> Optional[GoalState]:
        """
        Llamar AL INICIO de cognia.observe() después de calcular el vector.

        Detecta/actualiza el objetivo activo con el input actual.
        No modifica ningún estado de Cognia — solo lee el input.

        Args:
            observation: texto del usuario
            vec:         vector de embedding ya calculado (reutilizar)

        Returns:
            GoalState activo (puede ser None si no hay objetivo claro)
        """
        if not observation:
            return None

        try:
            goal = self.goal_manager.detect_and_update(observation, vec or [])
            self._last_vec = vec
            return goal
        except Exception as exc:
            logger.warning(
                "pre_observe falló",
                extra={"op": "goal_pattern_engine.pre_observe", "context": str(exc)},
            )
            return None

    # ── HOOK 2: después del ciclo observe ─────────────────────────────

    def post_observe(self, observation: str, result: dict):
        """
        Llamar AL FINAL de cognia.observe() justo antes del return.

        Puede enriquecer el result con información del objetivo activo.
        No lanza excepciones — todo dentro de try/except.

        Args:
            observation: texto procesado
            result:      dict de resultado de observe() (se modifica in-place)
        """
        try:
            goal = self.goal_manager.get_active()
            if goal:
                result["active_goal"] = goal.to_dict()
        except Exception as exc:
            logger.warning(
                "post_observe falló",
                extra={"op": "goal_pattern_engine.post_observe", "context": str(exc)},
            )

    # ── HOOK 3: tick (llamar al final de observe) ──────────────────────

    def tick(self, interaction_count: int):
        """
        Control de ciclos. No ejecuta operaciones costosas aquí.
        Solo actualiza contadores. El batch real corre desde sleep().
        """
        pass   # El scheduler decide en run_pattern_batch()

    # ── HOOK 4: batch de patrones (desde sleep) ───────────────────────

    def run_pattern_batch(self,
                          semantic_memory=None,
                          interaction_count: int = 0) -> str:
        """
        Ejecuta el ciclo completo de aprendizaje por patrones.
        Llamar desde cognia.sleep() o cuando interaction_count alcance el umbral.

        Args:
            semantic_memory:    instancia de ai.semantic (SemanticMemory)
            interaction_count:  número de interacciones (para el scheduler)

        Returns:
            string con resumen para incluir en el log de sleep()
        """
        # El scheduler solo aplica si se pasa interaction_count
        if interaction_count > 0:
            if not self.scheduler.should_run(interaction_count):
                return ""
            self.scheduler.mark_ran(interaction_count)

        if semantic_memory is None:
            logger.warning(
                "run_pattern_batch llamado sin semantic_memory",
                extra={"op": "goal_pattern_engine.batch", "context": "no_semantic"},
            )
            return ""

        try:
            result = self.pattern_learner.run_batch(self.db_path, semantic_memory)
            if result.get("skipped"):
                return ""
            return (
                f"\n   Patrones PASO 8:  "
                f"+{result['relations_created']} relaciones, "
                f"{result['concepts_reinforced']} conceptos reforzados "
                f"({result['elapsed_ms']:.0f}ms)"
            )
        except Exception as exc:
            logger.warning(
                "run_pattern_batch falló",
                extra={"op": "goal_pattern_engine.batch", "context": str(exc)},
            )
            return ""

    # ── API de integración con generación de respuesta ────────────────

    def active_goal_hint(self) -> str:
        """
        PASO 7: retorna bloque de texto para inyectar en el contexto del LLM.
        Llamar desde construir_contexto() o language_engine.respond().

        Returns:
            str listo para anteponer al contexto, o "" si no hay objetivo.
        """
        return self.goal_manager.active_goal_hint()

    def goal_aware_boost(self, memories: List[dict]) -> List[dict]:
        """
        PASO 7: re-rankea memorias priorizando las relacionadas con el objetivo.

        Args:
            memories: lista de memorias con campo 'score' y 'observation'

        Returns:
            misma lista con scores ajustados, ordenada por score desc
        """
        return self.goal_manager.goal_aware_memory_boost(memories)

    # ── Diagnóstico ────────────────────────────────────────────────────

    def stats(self) -> dict:
        return {
            "goal":    self.goal_manager.stats(),
            "pattern": {"batch_runs": self.scheduler.total_runs,
                        "next_run_in": max(0, PATTERN_BATCH_INTERVAL
                                          - (self.scheduler._last_run_count or 0))},
        }


# ══════════════════════════════════════════════════════════════════════
# SINGLETON
# ══════════════════════════════════════════════════════════════════════

_ENGINE: Optional[GoalAndPatternEngine] = None


def get_goal_engine(db_path: str = "cognia_memory.db") -> GoalAndPatternEngine:
    """Retorna el singleton del GoalAndPatternEngine."""
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = GoalAndPatternEngine(db_path)
    return _ENGINE


# ══════════════════════════════════════════════════════════════════════
# UTILIDADES VECTORIALES (sin dependencias externas)
# ══════════════════════════════════════════════════════════════════════

def _cosine(a: List[float], b: List[float]) -> float:
    """Similitud coseno. Retorna 0.0 si algún vector es vacío/nulo."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na  = math.sqrt(sum(x * x for x in a))
    nb  = math.sqrt(sum(x * x for x in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return max(-1.0, min(1.0, dot / (na * nb)))
