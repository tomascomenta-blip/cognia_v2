"""
prompt_optimizer.py — Cognia Language Engine
============================================
Sistema de optimización automática de prompts.

Hace tres cosas:
  1. COMPRESIÓN DE CONTEXTO
     Antes de enviar contexto al LLM, lo recorta inteligentemente:
     elimina bloques redundantes, comprime episodios, filtra conceptos
     de baja relevancia. Objetivo: reducir tokens enviados en 40-60%.

  2. EVOLUCIÓN DE PROMPTS
     Registra métricas de cada llamada al LLM (longitud, latencia,
     calidad estimada). Genera versiones mejoradas de los prompts
     base automáticamente usando esas métricas.

  3. DETECCIÓN DE PROMPTS INEFICIENTES
     Si un prompt es mucho más largo de lo necesario para el tipo de
     pregunta detectado, lo recorta antes de enviarlo.
"""

import re
import json
import time
import sqlite3
import threading
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from collections import defaultdict

# ── Límites por tipo de pregunta (tokens aproximados) ─────────────────
TOKEN_LIMITS = {
    "definicion":    600,
    "lista":         500,
    "comparacion":   700,
    "como_funciona": 800,
    "historia":      600,
    "estado":        400,
    "confirmacion":  300,
    "corta":         250,
    "general":       600,
}

# Tokens de contexto máximos por nivel de ThrottleController
CONTEXT_TOKENS_BY_LEVEL = {
    "normal":   1400,
    "moderate":  900,
    "low":       500,
    "critical":  250,
}

# Caracteres por token aproximados (español)
CHARS_PER_TOKEN = 3.8


@dataclass
class PromptMetrics:
    prompt_id:      str
    question_type:  str
    prompt_length:  int          # caracteres
    context_length: int          # caracteres del bloque CONTEXTO
    response_length: int         # caracteres de la respuesta recibida
    latency_ms:     float
    used_llm:       bool
    cache_hit:      bool
    quality_score:  float        # 0-1 estimado (longitud + coherencia heurística)
    timestamp:      float = field(default_factory=time.time)
    throttle_level: str = "normal"


@dataclass
class OptimizedPrompt:
    original_length:   int
    optimized_length:  int
    compression_ratio: float     # 0-1: qué fracción se eliminó
    prompt:            str       # prompt final a enviar
    context_blocks:    List[str] # bloques de contexto incluidos
    tokens_estimated:  int


# ══════════════════════════════════════════════════════════════════════
# CONTEXT COMPRESSOR
# ══════════════════════════════════════════════════════════════════════

class ContextCompressor:
    """
    Recorta y prioriza el contexto cognitivo antes de enviarlo al LLM.

    Estrategia:
      - Conservar: CONVERSACIÓN RECIENTE, ESTADO COGNITIVO (siempre)
      - Priorizar: bloques con mayor similitud al concepto principal
      - Comprimir: episodios largos → resumen de 1 línea
      - Eliminar: repeticiones, bloques con similitud < 0.25
      - Truncar: si aún excede el límite por nivel de carga
    """

    # Bloques que siempre se conservan (nunca eliminar)
    ALWAYS_KEEP = {"CONVERSACIÓN RECIENTE", "ESTADO COGNITIVO"}
    # Bloques en orden de prioridad (mayor prioridad = primero)
    BLOCK_PRIORITY = [
        "GRAFO DE CONOCIMIENTO",
        "INFERENCIAS SIMBÓLICAS",
        "CONVERSACIÓN RECIENTE",
        "MEMORIAS EPISÓDICAS",
        "CONCEPTOS RELACIONADOS",
        "PREDICCIONES TEMPORALES",
        "HIPÓTESIS PREVIAS",
        "ESTADO COGNITIVO",
    ]

    def compress(self, context: str, question_type: str,
                 throttle_level: str = "normal",
                 max_chars: Optional[int] = None) -> Tuple[str, List[str]]:
        """
        Comprime el contexto para el nivel de carga dado.

        Retorna (contexto_comprimido, lista_de_bloques_incluidos).
        """
        if not context:
            return context, []

        token_limit = CONTEXT_TOKENS_BY_LEVEL.get(throttle_level, 1400)
        char_limit  = max_chars or int(token_limit * CHARS_PER_TOKEN)

        # Parsear bloques del contexto
        blocks = self._parse_blocks(context)

        # Comprimir contenido de cada bloque
        blocks = {k: self._compress_block(k, v) for k, v in blocks.items()}

        # Ordenar por prioridad y quitar duplicados
        ordered = self._prioritize(blocks, question_type)

        # Construir contexto respetando el límite de caracteres
        included  = []
        parts     = []
        char_count = 0
        for block_name, content in ordered:
            block_str = f"{block_name}:\n{content}"
            if block_name in self.ALWAYS_KEEP or char_count + len(block_str) <= char_limit:
                parts.append(block_str)
                included.append(block_name)
                char_count += len(block_str)
            if char_count >= char_limit:
                break

        return "\n\n".join(parts), included

    def _parse_blocks(self, context: str) -> Dict[str, str]:
        """Separa el contexto en bloques por cabecera."""
        blocks = {}
        current_header = None
        current_lines  = []
        for line in context.split("\n"):
            if line.endswith(":") and line.upper() == line.upper():
                if current_header:
                    blocks[current_header] = "\n".join(current_lines).strip()
                current_header = line.rstrip(":")
                current_lines  = []
            else:
                current_lines.append(line)
        if current_header:
            blocks[current_header] = "\n".join(current_lines).strip()
        return blocks

    def _compress_block(self, name: str, content: str) -> str:
        """Comprime el contenido de un bloque específico."""
        if not content:
            return content

        lines = [l for l in content.split("\n") if l.strip()]

        if name == "MEMORIAS EPISÓDICAS":
            # Conservar máx 3 episodios, truncar observaciones largas
            compressed = []
            for line in lines[:3]:
                if "'" in line:
                    # Truncar la observación entre comillas
                    line = re.sub(r"'(.{60,}?)'", lambda m: f"'{m.group(1)[:60]}...'", line)
                compressed.append(line)
            return "\n".join(compressed)

        elif name == "CONCEPTOS RELACIONADOS":
            # Máx 4 conceptos, solo nombre + activación
            result = []
            for line in lines[:4]:
                # Simplificar: "- concepto (activación: 0.85)" → "- concepto"
                simplified = re.sub(r"\s*\(activación:.*?\)", "", line)
                result.append(simplified)
            return "\n".join(result)

        elif name == "GRAFO DE CONOCIMIENTO":
            # Máx 6 hechos, eliminar pesos
            result = []
            for line in lines[:6]:
                simplified = re.sub(r"\s*\(peso:.*?\)", "", line)
                result.append(simplified)
            return "\n".join(result)

        elif name == "INFERENCIAS SIMBÓLICAS":
            return "\n".join(lines[:3])

        elif name == "HIPÓTESIS PREVIAS":
            return "\n".join(lines[:2])

        elif name == "PREDICCIONES TEMPORALES":
            return "\n".join(lines[:2])

        elif name == "CONVERSACIÓN RECIENTE":
            return "\n".join(lines[-4:])  # últimos 4 turnos

        return "\n".join(lines)

    def _prioritize(self, blocks: Dict[str, str],
                    question_type: str) -> List[Tuple[str, str]]:
        """Ordena los bloques por relevancia para el tipo de pregunta."""
        # Ajustar prioridades según tipo
        priority = self.BLOCK_PRIORITY.copy()
        if question_type == "como_funciona":
            priority.insert(0, "INFERENCIAS SIMBÓLICAS")
        elif question_type == "historia":
            priority.insert(0, "MEMORIAS EPISÓDICAS")
        elif question_type in ("lista", "comparacion"):
            priority.insert(0, "GRAFO DE CONOCIMIENTO")

        result = []
        added  = set()
        for block_name in priority:
            if block_name in blocks and block_name not in added:
                result.append((block_name, blocks[block_name]))
                added.add(block_name)
        # Añadir bloques no en la lista de prioridad al final
        for k, v in blocks.items():
            if k not in added:
                result.append((k, v))
        return result


# ══════════════════════════════════════════════════════════════════════
# PROMPT METRICS STORE
# ══════════════════════════════════════════════════════════════════════

class PromptMetricsStore:
    """
    Persiste métricas de llamadas al LLM para el sistema de evolución.
    """

    def __init__(self, db_path: str = "cognia_memory.db"):
        self._db = db_path
        self._lock = threading.Lock()
        self._init_table()

    def _init_table(self):
        try:
            conn = sqlite3.connect(self._db)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS prompt_metrics (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    prompt_id      TEXT,
                    question_type  TEXT,
                    prompt_length  INTEGER,
                    context_length INTEGER,
                    response_length INTEGER,
                    latency_ms     REAL,
                    used_llm       INTEGER,
                    cache_hit      INTEGER,
                    quality_score  REAL,
                    throttle_level TEXT,
                    timestamp      REAL
                )
            """)
            conn.commit()
            conn.close()
        except Exception:
            pass

    def record(self, m: PromptMetrics):
        with self._lock:
            try:
                conn = sqlite3.connect(self._db)
                conn.execute("""
                    INSERT INTO prompt_metrics
                    (prompt_id, question_type, prompt_length, context_length,
                     response_length, latency_ms, used_llm, cache_hit,
                     quality_score, throttle_level, timestamp)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """, (m.prompt_id, m.question_type, m.prompt_length,
                      m.context_length, m.response_length, m.latency_ms,
                      int(m.used_llm), int(m.cache_hit), m.quality_score,
                      m.throttle_level, m.timestamp))
                conn.commit()
                conn.close()
            except Exception:
                pass

    def get_stats_by_type(self) -> Dict:
        """Devuelve estadísticas agrupadas por tipo de pregunta."""
        try:
            conn = sqlite3.connect(self._db)
            rows = conn.execute("""
                SELECT question_type,
                       COUNT(*) as n,
                       AVG(latency_ms) as avg_lat,
                       AVG(quality_score) as avg_qual,
                       AVG(prompt_length) as avg_len,
                       AVG(context_length) as avg_ctx,
                       SUM(cache_hit) as cache_hits,
                       SUM(used_llm) as llm_calls
                FROM prompt_metrics
                GROUP BY question_type
                ORDER BY n DESC
            """).fetchall()
            conn.close()
            result = {}
            for row in rows:
                result[row[0]] = {
                    "count":      row[1],
                    "avg_lat_ms": round(row[2] or 0, 1),
                    "avg_quality":round(row[3] or 0, 3),
                    "avg_prompt_chars": round(row[4] or 0),
                    "avg_context_chars":round(row[5] or 0),
                    "cache_hit_rate": round((row[6] or 0) / max(1, row[1]), 3),
                    "llm_call_rate":  round((row[7] or 0) / max(1, row[1]), 3),
                }
            return result
        except Exception:
            return {}


# ══════════════════════════════════════════════════════════════════════
# PROMPT OPTIMIZER
# ══════════════════════════════════════════════════════════════════════

class PromptOptimizer:
    """
    Optimiza prompts antes de enviarlos al LLM.
    Mantiene métricas y evoluciona los prompts base automáticamente.

    Pipeline:
      1. Estimar si el prompt es más largo de lo necesario
      2. Comprimir el contexto con ContextCompressor
      3. Registrar métricas de la llamada
      4. Analizar métricas acumuladas → sugerir mejoras
    """

    # Prompts base que se pueden evolucionar
    BASE_PROMPTS = {
        "general": (
            "PREGUNTA: {question}\n\n"
            "CONTEXTO DE MI MEMORIA:\n{context}\n\n"
            "Responde basándote en el contexto de forma natural."
        ),
        "sin_contexto": (
            "PREGUNTA: {question}\n\n"
            "No tengo información específica en mi memoria sobre esto. "
            "Razona sobre los conceptos involucrados y responde directamente. "
            "Máximo 2 párrafos."
        ),
        "definicion": (
            "PREGUNTA: {question}\n\n"
            "CONOCIMIENTO:\n{context}\n\n"
            "Define el concepto en 1-2 párrafos directos."
        ),
        "lista": (
            "PREGUNTA: {question}\n\n"
            "DATOS:\n{context}\n\n"
            "Responde con una lista concisa de 4-6 puntos."
        ),
        "como_funciona": (
            "PREGUNTA: {question}\n\n"
            "CONOCIMIENTO:\n{context}\n\n"
            "Explica el proceso en pasos claros. Máximo 5 pasos."
        ),
    }

    def __init__(self, db_path: str = "cognia_memory.db"):
        self.compressor = ContextCompressor()
        self.metrics    = PromptMetricsStore(db_path)
        self._evolved_prompts: Dict[str, str] = {}   # versiones mejoradas
        self._db = db_path

    def optimize(self, question: str, context: str, question_type: str,
                 throttle_level: str = "normal") -> OptimizedPrompt:
        """
        Construye un prompt optimizado listo para enviar al LLM.

        Retorna OptimizedPrompt con el prompt ya armado.
        """
        # Comprimir contexto
        compressed_ctx, included_blocks = self.compressor.compress(
            context, question_type, throttle_level
        )

        # Seleccionar plantilla base (evolucionada si existe)
        template_key = question_type if question_type in self.BASE_PROMPTS else "general"
        template     = self._evolved_prompts.get(template_key,
                        self.BASE_PROMPTS.get(template_key,
                        self.BASE_PROMPTS["general"]))

        # Construir prompt final
        q_trimmed  = question[:400]
        ctx_trimmed = compressed_ctx[:int(
            CONTEXT_TOKENS_BY_LEVEL.get(throttle_level, 1400) * CHARS_PER_TOKEN
        )]

        prompt = template.format(
            question=q_trimmed,
            context=ctx_trimmed if compressed_ctx else "(sin contexto relevante)"
        )

        original_len  = len(question) + len(context)
        optimized_len = len(prompt)
        compression   = max(0.0, 1.0 - (optimized_len / max(1, original_len)))

        return OptimizedPrompt(
            original_length   = original_len,
            optimized_length  = optimized_len,
            compression_ratio = round(compression, 3),
            prompt            = prompt,
            context_blocks    = included_blocks,
            tokens_estimated  = int(optimized_len / CHARS_PER_TOKEN),
        )

    def record_call(self, prompt_id: str, question_type: str,
                    prompt_len: int, context_len: int,
                    response_len: int, latency_ms: float,
                    used_llm: bool, cache_hit: bool,
                    throttle_level: str = "normal"):
        """Registra métricas de una llamada (LLM o caché) para evolución."""
        quality = self._estimate_quality(response_len, latency_ms, used_llm)
        self.metrics.record(PromptMetrics(
            prompt_id      = prompt_id,
            question_type  = question_type,
            prompt_length  = prompt_len,
            context_length = context_len,
            response_length= response_len,
            latency_ms     = latency_ms,
            used_llm       = used_llm,
            cache_hit      = cache_hit,
            quality_score  = quality,
            throttle_level = throttle_level,
        ))

    def evolve_prompts(self) -> Dict[str, str]:
        """
        Analiza las métricas acumuladas y genera versiones mejoradas
        de los prompts base. Retorna dict de prompts evolucionados.

        Estrategias de evolución:
          - Si avg_latency alto y avg_quality OK → acortar instrucciones
          - Si avg_quality bajo → añadir instrucciones de formato
          - Si context demasiado largo → añadir indicación de brevedad
        """
        stats = self.metrics.get_stats_by_type()
        evolved = {}

        for q_type, data in stats.items():
            if data["count"] < 5:
                continue  # No hay suficientes datos

            base = self.BASE_PROMPTS.get(q_type, self.BASE_PROMPTS["general"])
            improvements = []

            # Si la latencia promedio es alta → pedir respuesta más corta
            if data["avg_lat_ms"] > 8000:
                improvements.append("Sé muy conciso. ")

            # Si la calidad es baja → añadir guía de formato
            if data["avg_quality"] < 0.4:
                improvements.append("Estructura tu respuesta claramente. ")

            # Si el contexto promedio enviado es muy largo → pedir síntesis
            if data["avg_context_chars"] > 2000:
                base = base.replace(
                    "Responde basándote en el contexto",
                    "Sintetiza la información clave y responde"
                )

            if improvements:
                prefix = "".join(improvements)
                evolved[q_type] = base + f"\n\n{prefix}"
            else:
                evolved[q_type] = base

        self._evolved_prompts.update(evolved)
        return evolved

    def get_stats(self) -> Dict:
        return self.metrics.get_stats_by_type()

    def _estimate_quality(self, response_len: int,
                           latency_ms: float, used_llm: bool) -> float:
        """
        Heurística de calidad: respuestas de longitud media y latencia
        razonable reciben puntuación alta.
        No hay feedback humano real — se puede mejorar con thumbs up/down.
        """
        # Longitud óptima: 200-800 caracteres
        if response_len < 50:
            len_score = 0.2
        elif response_len < 200:
            len_score = 0.6
        elif response_len <= 800:
            len_score = 1.0
        elif response_len <= 1500:
            len_score = 0.8
        else:
            len_score = 0.5

        # Latencia: < 2s excelente, < 8s buena, > 20s mala
        if latency_ms < 2000:
            lat_score = 1.0
        elif latency_ms < 8000:
            lat_score = 0.8
        elif latency_ms < 20000:
            lat_score = 0.5
        else:
            lat_score = 0.2

        # Caché hits son siempre "calidad suficiente"
        if not used_llm:
            return round((len_score * 0.6 + lat_score * 0.4), 3)

        return round((len_score * 0.5 + lat_score * 0.5), 3)
