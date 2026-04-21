"""
decision_gate.py — Cognia PASO 4: Gating de decisión de tres zonas
===================================================================
Reemplaza la lógica binaria `if confidence >= UMBRAL_CONFIANZA` por un
sistema de tres zonas con validación semántica de relevancia.

ZONAS:
  HIGH   (>= 0.72)  → simbólico directo, pero solo si pasa is_response_relevant()
  MEDIUM (0.38-0.72) → híbrido o LLM, según relevancia
  LOW    (< 0.38)   → LLM siempre

FLUJO:
  DecisionGate.evaluate(sym_response, question, vec, ai)
  → GateDecision(action, reason, adjusted_confidence)

USO desde language_engine.py (Stage 2):
  from decision_gate import DecisionGate, GateAction
  gate   = DecisionGate()
  result = gate.evaluate(sym_response, question, vec, ai)
  if result.action == GateAction.SYMBOLIC:
      # usar sym_response directamente
  elif result.action == GateAction.HYBRID:
      # sym_response como base + LLM enriquece
  else:
      # LLM completo
"""

import math
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional, List

from logger_config import get_logger, log_slow

logger = get_logger(__name__)

# ── Umbrales calibrados (PASO 4) ──────────────────────────────────────
# Anteriores: UMBRAL_CONFIANZA=0.55, UMBRAL_FALLBACK=0.42, UMBRAL_MINIMO=0.30
# Nuevos: más exigentes para reducir falsos positivos del simbólico
HIGH_THRESHOLD    = 0.72   # antes 0.55 — requiere conocimiento sólido
MEDIUM_THRESHOLD  = 0.38   # antes 0.42 — zona híbrida más amplia
# Por debajo de MEDIUM_THRESHOLD → LLM directo

# Umbral de similitud para is_response_relevant()
RELEVANCE_MIN_SIM = 0.30   # similitud coseno mínima pregunta↔respuesta simbólica

# Longitud mínima para que una respuesta simbólica sea considerada sustancial
MIN_SYMBOLIC_LEN  = 60     # caracteres


class GateAction(str, Enum):
    SYMBOLIC  = "symbolic"
    HYBRID    = "hybrid"
    LLM       = "llm"


@dataclass
class GateDecision:
    action:               GateAction
    reason:               str
    original_confidence:  float
    adjusted_confidence:  float
    relevance_score:      float   # -1.0 si no se calculó
    elapsed_ms:           float   = 0.0


# ══════════════════════════════════════════════════════════════════════
# UTILIDADES: similitud coseno inline (sin dependencias extra)
# ══════════════════════════════════════════════════════════════════════

def _cosine(a: List[float], b: List[float]) -> float:
    """Similitud coseno entre dos vectores. Retorna 0.0 si hay error."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na  = math.sqrt(sum(x * x for x in a))
    nb  = math.sqrt(sum(x * x for x in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return max(-1.0, min(1.0, dot / (na * nb)))


def _text_to_vec(text: str) -> Optional[List[float]]:
    """Wrapper tolerante para text_to_vector. Retorna None si falla."""
    try:
        from cognia.vectors import text_to_vector
        return text_to_vector(text[:300])
    except ImportError:
        try:
            from vectors import text_to_vector
            return text_to_vector(text[:300])
        except Exception:
            return None
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════════
# VALIDADOR DE RELEVANCIA SEMÁNTICA
# ══════════════════════════════════════════════════════════════════════

def is_response_relevant(
    question: str,
    response: str,
    question_vec: Optional[List[float]] = None,
    min_sim: float = RELEVANCE_MIN_SIM,
) -> tuple:
    """
    Evalúa si una respuesta simbólica es semánticamente relevante
    para la pregunta del usuario.

    Usa el embedding ya calculado de la pregunta (question_vec) si está
    disponible para evitar recalcular. Si no, lo calcula internamente.

    Args:
        question:     pregunta del usuario
        response:     texto de la respuesta simbólica
        question_vec: vector pre-calculado de la pregunta (reutilizar si existe)
        min_sim:      umbral mínimo de similitud para considerar relevante

    Returns:
        (is_relevant: bool, similarity: float)
        similarity = -1.0 si los embeddings no están disponibles
    """
    # Respuesta vacía o muy corta → no relevante
    if not response or len(response.strip()) < MIN_SYMBOLIC_LEN:
        return False, 0.0

    # Respuesta de "ignorancia" → no relevante para activar simbólico
    _ignorance_markers = [
        "no tengo información",
        "mi conocimiento sobre",
        "no he aprendido suficiente",
        "no tengo una lista específica",
        "no tengo suficiente información",
    ]
    resp_lower = response.lower()
    if any(m in resp_lower for m in _ignorance_markers):
        logger.debug(
            "Respuesta simbólica contiene marcador de ignorancia",
            extra={"op": "gate.is_response_relevant", "context": f"q_len={len(question)}"},
        )
        return False, 0.0

    # Calcular similitud semántica
    q_vec = question_vec or _text_to_vec(question)
    if q_vec is None:
        # Sin embeddings: aceptar si la confianza ya era alta (decisión aguas arriba)
        logger.debug(
            "Embeddings no disponibles — relevancia no verificable",
            extra={"op": "gate.is_response_relevant", "context": "vec=None"},
        )
        return True, -1.0

    r_vec = _text_to_vec(response[:300])
    if r_vec is None:
        return True, -1.0

    sim = _cosine(q_vec, r_vec)
    is_rel = sim >= min_sim

    logger.debug(
        f"Relevancia semántica: sim={sim:.3f} umbral={min_sim} → {'OK' if is_rel else 'FALLO'}",
        extra={
            "op":      "gate.is_response_relevant",
            "context": f"sim={sim:.3f} min_sim={min_sim}",
        },
    )
    return is_rel, sim


# ══════════════════════════════════════════════════════════════════════
# DECISION GATE PRINCIPAL
# ══════════════════════════════════════════════════════════════════════

class DecisionGate:
    """
    Árbitro de tres zonas para decidir entre simbólico, híbrido y LLM.

    Instanciar una vez y reutilizar (sin estado mutable entre llamadas).
    """

    def __init__(
        self,
        high_threshold:   float = HIGH_THRESHOLD,
        medium_threshold: float = MEDIUM_THRESHOLD,
        relevance_min:    float = RELEVANCE_MIN_SIM,
    ):
        self.high_threshold   = high_threshold
        self.medium_threshold = medium_threshold
        self.relevance_min    = relevance_min

    def evaluate(
        self,
        sym_response,                        # SymbolicResponse de symbolic_responder.py
        question:     str,
        question_vec: Optional[List[float]], # pasar el vec ya calculado para reutilizar
        cognia_instance = None,              # para logging extra si se necesita
    ) -> GateDecision:
        """
        Evalúa sym_response y devuelve la decisión de routing.

        El vec de la pregunta se pasa desde language_engine.respond()
        donde ya fue calculado en Stage 1 (cache check). Así se evita
        recalcular el embedding.

        Args:
            sym_response:    resultado de SymbolicResponder.respond()
            question:        pregunta original del usuario
            question_vec:    vector pre-calculado de la pregunta
            cognia_instance: instancia Cognia (no se usa directamente,
                             reservado para extensiones futuras)

        Returns:
            GateDecision con action, reason, confidence ajustada
        """
        t0   = time.perf_counter()
        conf = sym_response.confidence

        # ── ZONA BAJA: LLM directo sin más evaluaciones ───────────────
        if conf < self.medium_threshold:
            decision = GateDecision(
                action               = GateAction.LLM,
                reason               = "low_confidence",
                original_confidence  = conf,
                adjusted_confidence  = conf,
                relevance_score      = -1.0,
                elapsed_ms           = (time.perf_counter() - t0) * 1000,
            )
            self._log(decision, question)
            return decision

        # ── ZONA ALTA: simbólico candidato, pero validar relevancia ──
        if conf >= self.high_threshold:
            is_rel, sim = is_response_relevant(
                question    = question,
                response    = sym_response.text,
                question_vec= question_vec,
                min_sim     = self.relevance_min,
            )
            if is_rel:
                decision = GateDecision(
                    action               = GateAction.SYMBOLIC,
                    reason               = "high_confidence_relevant",
                    original_confidence  = conf,
                    adjusted_confidence  = conf,
                    relevance_score      = sim,
                    elapsed_ms           = (time.perf_counter() - t0) * 1000,
                )
                self._log(decision, question)
                return decision
            else:
                # Alta confianza pero respuesta irrelevante → forzar LLM
                decision = GateDecision(
                    action               = GateAction.LLM,
                    reason               = "low_relevance",
                    original_confidence  = conf,
                    adjusted_confidence  = conf * 0.5,  # penalizar
                    relevance_score      = sim,
                    elapsed_ms           = (time.perf_counter() - t0) * 1000,
                )
                self._log(decision, question)
                return decision

        # ── ZONA MEDIA: híbrido — evaluar relevancia para decidir grado
        is_rel, sim = is_response_relevant(
            question    = question,
            response    = sym_response.text,
            question_vec= question_vec,
            min_sim     = self.relevance_min,
        )

        if is_rel:
            # Relevante en zona media → híbrido (simbólico como base + LLM enriquece)
            decision = GateDecision(
                action               = GateAction.HYBRID,
                reason               = "medium_confidence_relevant",
                original_confidence  = conf,
                adjusted_confidence  = conf,
                relevance_score      = sim,
                elapsed_ms           = (time.perf_counter() - t0) * 1000,
            )
        else:
            # Zona media pero irrelevante → LLM completo
            decision = GateDecision(
                action               = GateAction.LLM,
                reason               = "medium_confidence_low_relevance",
                original_confidence  = conf,
                adjusted_confidence  = conf * 0.6,
                relevance_score      = sim,
                elapsed_ms           = (time.perf_counter() - t0) * 1000,
            )

        self._log(decision, question)
        return decision

    # ── Logging estructurado ─────────────────────────────────────────

    def _log(self, decision: GateDecision, question: str):
        """
        Emite un log estructurado con todos los datos de la decisión.
        Formato grep-amigable con campos clave=valor.
        """
        logger.info(
            f"stage=decision "
            f"confidence={decision.original_confidence:.3f} "
            f"adjusted={decision.adjusted_confidence:.3f} "
            f"decision={decision.action.value} "
            f"reason={decision.reason} "
            f"relevance={decision.relevance_score:.3f} "
            f"gate_ms={decision.elapsed_ms:.1f}",
            extra={
                "op":      "decision_gate.evaluate",
                "context": (
                    f"q_len={len(question)} "
                    f"high_t={self.high_threshold} "
                    f"med_t={self.medium_threshold}"
                ),
            },
        )


# ── Singleton del gate (un objeto por proceso, sin estado) ────────────
_GATE_INSTANCE: Optional[DecisionGate] = None


def get_decision_gate() -> DecisionGate:
    """Retorna el singleton del DecisionGate."""
    global _GATE_INSTANCE
    if _GATE_INSTANCE is None:
        _GATE_INSTANCE = DecisionGate()
    return _GATE_INSTANCE
