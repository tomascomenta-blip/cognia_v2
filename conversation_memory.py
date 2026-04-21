"""
conversation_memory.py — Cognia PASO 3: Memoria Conversacional Multi-Turno
===========================================================================
Implementa contexto coherente entre turnos de conversación.

COMPONENTES:
  ConversationBuffer   — buffer circular de turnos (usuario + Cognia)
  TopicTracker         — detecta tema actual y cambios de tema
  ContextSelector      — selecciona turnos relevantes por similitud semántica
  ConversationContext  — fachada que orquesta los tres componentes

INTEGRACIÓN:
  1. En respuestas_articuladas.py → construir_contexto():
       from conversation_memory import get_conversation_context
       ctx = get_conversation_context(ai)
       bloque_conv = ctx.build_context_block(pregunta, vec_pregunta)

  2. En language_engine.py → LanguageEngine.__init__():
       from conversation_memory import get_conversation_context
       # (acceso via ai en respond())

  3. En respuestas_articuladas.py → _postprocess_response():
       ctx = get_conversation_context(ai)
       ctx.add_turn(pregunta, respuesta, vec_pregunta)

DISEÑO PARA CPU (2 núcleos, 12 GB RAM):
  - Buffer circular de tamaño fijo → sin crecimiento indefinido
  - Similitud coseno en RAM → sin DB, O(N) con N ≤ MAX_TURNS
  - Embeddings reutilizados del pipeline principal → 0 cómputo extra
  - Lock mínimo por operación → no bloquea el hilo principal
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict

from logger_config import get_logger

logger = get_logger(__name__)

# ── Configuración ──────────────────────────────────────────────────────
MAX_TURNS           = 12    # máximo de turnos almacenados en el buffer
CONTEXT_TURNS       = 4     # turnos a incluir en el bloque de contexto
SIM_THRESHOLD       = 0.35  # similitud mínima para considerar un turno relevante
TOPIC_CHANGE_THRESH = 0.28  # similitud < este valor → cambio de tema detectado
TOPIC_WINDOW        = 3     # últimos N turnos para calcular vector de tema
MAX_CONTEXT_CHARS   = 800   # límite de caracteres del bloque de contexto al LLM


# ══════════════════════════════════════════════════════════════════════
# 1. TURNO DE CONVERSACIÓN
# ══════════════════════════════════════════════════════════════════════

@dataclass
class ConversationTurn:
    """Un par usuario/Cognia con su vector semántico."""
    user_text:    str
    cognia_text:  str
    vector:       List[float]          # vector del user_text (reutilizado del pipeline)
    timestamp:    float = field(default_factory=time.time)
    topic_label:  Optional[str] = None # etiqueta de tema asignada por TopicTracker

    def age_seconds(self) -> float:
        return time.time() - self.timestamp

    def short_user(self, max_chars: int = 150) -> str:
        return self.user_text[:max_chars]

    def short_cognia(self, max_chars: int = 180) -> str:
        return self.cognia_text[:max_chars]


# ══════════════════════════════════════════════════════════════════════
# 2. BUFFER CIRCULAR
# ══════════════════════════════════════════════════════════════════════

class ConversationBuffer:
    """
    Buffer circular de MAX_TURNS turnos conversacionales.
    Thread-safe. Acceso O(1) al último turno, O(N) a todos.
    """

    def __init__(self, max_turns: int = MAX_TURNS):
        self._turns: deque[ConversationTurn] = deque(maxlen=max_turns)
        self._lock  = threading.Lock()
        self._count = 0   # total histórico (no limitado por maxlen)

    def add(self, turn: ConversationTurn) -> None:
        with self._lock:
            self._turns.append(turn)
            self._count += 1
        logger.debug(
            "Turno añadido al buffer conversacional",
            extra={
                "op":      "conv_buffer.add",
                "context": f"total_turns={self._count} buffer_size={len(self._turns)} "
                           f"topic={turn.topic_label}",
            },
        )

    def get_all(self) -> List[ConversationTurn]:
        with self._lock:
            return list(self._turns)

    def get_last(self, n: int) -> List[ConversationTurn]:
        with self._lock:
            turns = list(self._turns)
        return turns[-n:] if n < len(turns) else turns

    def last_vector(self) -> Optional[List[float]]:
        with self._lock:
            if self._turns:
                return self._turns[-1].vector
        return None

    def is_empty(self) -> bool:
        with self._lock:
            return len(self._turns) == 0

    @property
    def total_count(self) -> int:
        return self._count

    def __len__(self) -> int:
        with self._lock:
            return len(self._turns)


# ══════════════════════════════════════════════════════════════════════
# 3. DETECTOR DE TEMA
# ══════════════════════════════════════════════════════════════════════

class TopicTracker:
    """
    Detecta el tema actual y los cambios de tema.

    Estrategia:
      - El "vector de tema" es la media de los vectores de los últimos
        TOPIC_WINDOW turnos. Estable, barato, sin modelos extra.
      - Un nuevo turno se compara contra ese vector de tema.
      - Si similitud < TOPIC_CHANGE_THRESH → cambio de tema.

    Logging:
      - INFO cuando se detecta un cambio de tema.
      - DEBUG en cada actualización.
    """

    def __init__(self, window: int = TOPIC_WINDOW,
                 change_threshold: float = TOPIC_CHANGE_THRESH):
        self._window     = window
        self._threshold  = change_threshold
        self._topic_vec: Optional[List[float]] = None
        self._topic_label: str = "inicio"
        self._change_count: int = 0

    def update(self, new_vec: List[float],
               buffer: ConversationBuffer) -> Tuple[bool, str]:
        """
        Actualiza el estado del topic tracker.

        Retorna:
          (topic_changed: bool, topic_label: str)
        """
        # Calcular vector de tema actual a partir de los últimos N turnos
        recent = buffer.get_last(self._window)
        if recent:
            self._topic_vec = _mean_vector(
                [t.vector for t in recent] + [new_vec]
            )
        else:
            self._topic_vec = new_vec[:]

        # Primera interacción: no hay cambio
        if len(recent) == 0:
            self._topic_label = "tema_inicial"
            logger.debug(
                "TopicTracker: primera interacción",
                extra={"op": "topic_tracker.update", "context": "first_turn"},
            )
            return False, self._topic_label

        # Similitud entre la nueva pregunta y el vector de tema previo
        prev_topic = buffer.last_vector()
        if prev_topic is None:
            return False, self._topic_label

        sim = _cosine(new_vec, prev_topic)

        topic_changed = sim < self._threshold
        if topic_changed:
            self._change_count += 1
            self._topic_label = f"tema_{self._change_count}"
            logger.info(
                "Cambio de tema detectado",
                extra={
                    "op":      "topic_tracker.change",
                    "context": f"sim={sim:.3f} threshold={self._threshold} "
                               f"nuevo_tema={self._topic_label}",
                },
            )
        else:
            logger.debug(
                "Tema continúa",
                extra={
                    "op":      "topic_tracker.update",
                    "context": f"sim={sim:.3f} tema={self._topic_label}",
                },
            )

        return topic_changed, self._topic_label

    @property
    def current_label(self) -> str:
        return self._topic_label

    @property
    def changes(self) -> int:
        return self._change_count


# ══════════════════════════════════════════════════════════════════════
# 4. SELECTOR DE CONTEXTO RELEVANTE
# ══════════════════════════════════════════════════════════════════════

class ContextSelector:
    """
    Selecciona los turnos más relevantes para una nueva pregunta.

    Combina dos criterios:
      1. Recencia  — los últimos CONTEXT_TURNS turnos siempre se consideran.
      2. Similitud — dentro del buffer completo, se añaden turnos cuya
                     similitud con la nueva pregunta supere SIM_THRESHOLD.

    Con topic_changed=True, solo se usan los turnos del tema nuevo
    (los más recientes), descartando historia irrelevante.

    El resultado se limita a MAX_CONTEXT_CHARS caracteres para no
    inflar el prompt al LLM.
    """

    def __init__(self,
                 context_turns: int   = CONTEXT_TURNS,
                 sim_threshold: float = SIM_THRESHOLD,
                 max_chars: int       = MAX_CONTEXT_CHARS):
        self._n_turns   = context_turns
        self._threshold = sim_threshold
        self._max_chars = max_chars

    def select(self,
               query_vec: List[float],
               buffer: ConversationBuffer,
               topic_changed: bool = False) -> List[ConversationTurn]:
        """
        Retorna los turnos seleccionados, ordenados cronológicamente.
        """
        all_turns = buffer.get_all()
        if not all_turns:
            return []

        # Si cambia el tema, solo usar los últimos turnos (nuevo contexto limpio)
        if topic_changed:
            selected = all_turns[-self._n_turns:]
            logger.debug(
                "Selección de contexto post-cambio de tema",
                extra={
                    "op":      "ctx_selector.select",
                    "context": f"topic_changed=True turns_selected={len(selected)}",
                },
            )
            return selected

        # Sin cambio de tema: recencia + similitud semántica
        recent_set  = set(id(t) for t in all_turns[-self._n_turns:])
        selected_ids: Dict[int, ConversationTurn] = {}

        # Incluir siempre los más recientes
        for t in all_turns[-self._n_turns:]:
            selected_ids[id(t)] = t

        # Añadir por similitud semántica desde el buffer completo
        for t in all_turns:
            if id(t) in selected_ids:
                continue
            sim = _cosine(query_vec, t.vector)
            if sim >= self._threshold:
                selected_ids[id(t)] = t

        # Ordenar cronológicamente (preservar orden del deque)
        ordered = [t for t in all_turns if id(t) in selected_ids]

        logger.debug(
            "Selección de contexto conversacional",
            extra={
                "op":      "ctx_selector.select",
                "context": f"total_buffer={len(all_turns)} selected={len(ordered)} "
                           f"recent={len(recent_set)} sem_extra={len(ordered)-len(recent_set)}",
            },
        )
        return ordered

    def build_block(self, turns: List[ConversationTurn],
                    topic_changed: bool = False) -> str:
        """
        Convierte los turnos seleccionados en el bloque de texto
        que se inyecta en el prompt del LLM.

        Formato:
          CONVERSACIÓN RECIENTE:
          [Usuario]: ...
          [Cognia]: ...
          [Usuario]: ...
          ...
        """
        if not turns:
            return ""

        prefix = ""
        if topic_changed:
            prefix = "(tema nuevo) "

        lines = [f"CONVERSACIÓN RECIENTE {prefix}(".rstrip("(") + "):"]
        chars = len(lines[0])

        for turn in turns:
            u_line = f"[Usuario]: {turn.short_user()}"
            c_line = f"[Cognia]:  {turn.short_cognia()}"

            # Respetar límite de caracteres
            if chars + len(u_line) + len(c_line) + 2 > self._max_chars:
                break

            lines.append(u_line)
            lines.append(c_line)
            chars += len(u_line) + len(c_line) + 2

        if len(lines) == 1:
            return ""  # solo el encabezado, sin contenido útil

        return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════
# 5. FACHADA PRINCIPAL
# ══════════════════════════════════════════════════════════════════════

class ConversationContext:
    """
    Orquesta Buffer + TopicTracker + ContextSelector.

    Uso en respuestas_articuladas.py:

        from conversation_memory import get_conversation_context

        # En construir_contexto():
        ctx = get_conversation_context(ai)
        bloque = ctx.build_context_block(pregunta, vec)

        # En _postprocess_response() o al final de responder_articulado():
        ctx.add_turn(pregunta, respuesta, vec)
    """

    def __init__(self,
                 max_turns: int       = MAX_TURNS,
                 context_turns: int   = CONTEXT_TURNS,
                 sim_threshold: float = SIM_THRESHOLD,
                 topic_threshold: float = TOPIC_CHANGE_THRESH):
        self._buffer   = ConversationBuffer(max_turns)
        self._tracker  = TopicTracker(change_threshold=topic_threshold)
        self._selector = ContextSelector(context_turns, sim_threshold)
        self._lock     = threading.Lock()

        # Estado de la última llamada (para add_turn posterior)
        self._last_topic_changed: bool = False
        self._last_topic_label: str    = "inicio"

    def build_context_block(self,
                            question: str,
                            question_vec: List[float]) -> str:
        """
        Construye el bloque de contexto conversacional para el prompt.
        Llama ANTES de generar la respuesta.

        Retorna string listo para insertar en el contexto del LLM,
        o "" si no hay historial relevante.
        """
        if self._buffer.is_empty():
            logger.debug(
                "Buffer vacío — sin contexto conversacional",
                extra={"op": "conv_ctx.build", "context": "empty_buffer"},
            )
            return ""

        with self._lock:
            topic_changed, topic_label = self._tracker.update(
                question_vec, self._buffer
            )
            self._last_topic_changed = topic_changed
            self._last_topic_label   = topic_label

        selected = self._selector.select(
            question_vec, self._buffer, topic_changed
        )
        block = self._selector.build_block(selected, topic_changed)

        logger.debug(
            "Bloque de contexto construido",
            extra={
                "op":      "conv_ctx.build",
                "context": f"topic={topic_label} changed={topic_changed} "
                           f"turns_selected={len(selected)} block_chars={len(block)}",
            },
        )
        return block

    def add_turn(self,
                 user_text: str,
                 cognia_text: str,
                 vector: List[float]) -> None:
        """
        Registra un turno completado (usuario + respuesta de Cognia).
        Llama DESPUÉS de generar la respuesta.

        El vector debe ser el vector del user_text para búsqueda semántica.
        """
        if not vector:
            logger.warning(
                "add_turn llamado sin vector — turno ignorado",
                extra={"op": "conv_ctx.add_turn", "context": f"user_len={len(user_text)}"},
            )
            return

        turn = ConversationTurn(
            user_text   = user_text[:400],
            cognia_text = cognia_text[:500],
            vector      = vector,
            topic_label = self._last_topic_label,
        )
        self._buffer.add(turn)

    def topic_changed_last(self) -> bool:
        """True si en la última build_context_block se detectó cambio de tema."""
        return self._last_topic_changed

    def current_topic(self) -> str:
        return self._last_topic_label

    def stats(self) -> Dict:
        return {
            "buffer_size":    len(self._buffer),
            "total_turns":    self._buffer.total_count,
            "topic_changes":  self._tracker.changes,
            "current_topic":  self._last_topic_label,
        }


# ══════════════════════════════════════════════════════════════════════
# 6. SINGLETON POR INSTANCIA DE COGNIA
# ══════════════════════════════════════════════════════════════════════
#
# Usamos un dict keyed por id(cognia_instance) para soportar múltiples
# instancias (tests, multi-tenant). En producción solo hay una.

_CONTEXTS: Dict[int, ConversationContext] = {}
_CONTEXTS_LOCK = threading.Lock()


def get_conversation_context(
    cognia_instance=None,
    max_turns: int       = MAX_TURNS,
    context_turns: int   = CONTEXT_TURNS,
    sim_threshold: float = SIM_THRESHOLD,
) -> ConversationContext:
    """
    Retorna (o crea) el ConversationContext asociado a esta instancia de Cognia.

    Si cognia_instance es None, retorna un contexto global (modo standalone).
    """
    key = id(cognia_instance) if cognia_instance is not None else 0

    with _CONTEXTS_LOCK:
        if key not in _CONTEXTS:
            _CONTEXTS[key] = ConversationContext(
                max_turns     = max_turns,
                context_turns = context_turns,
                sim_threshold = sim_threshold,
            )
            logger.info(
                "ConversationContext creado",
                extra={
                    "op":      "conv_ctx.init",
                    "context": f"key={key} max_turns={max_turns} "
                               f"context_turns={context_turns} sim_th={sim_threshold}",
                },
            )
    return _CONTEXTS[key]


# ══════════════════════════════════════════════════════════════════════
# 7. UTILIDADES VECTORIALES (sin dependencias externas)
# ══════════════════════════════════════════════════════════════════════

def _cosine(a: List[float], b: List[float]) -> float:
    """Similitud coseno. Retorna 0.0 si alguno de los vectores es nulo."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na  = math.sqrt(sum(x * x for x in a))
    nb  = math.sqrt(sum(x * x for x in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return max(-1.0, min(1.0, dot / (na * nb)))


def _mean_vector(vectors: List[List[float]]) -> List[float]:
    """Media componente a componente. Asume vectores de igual dimensión."""
    if not vectors:
        return []
    dim = len(vectors[0])
    result = [0.0] * dim
    for v in vectors:
        for i, x in enumerate(v):
            result[i] += x
    n = len(vectors)
    return [x / n for x in result]
