"""
language_engine.py — Cognia Language Engine
============================================
Orquestador principal del motor de lenguaje híbrido.

Reemplaza la llamada directa a Ollama en respuestas_articuladas.py
con un pipeline de 5 etapas:

  STAGE 1: CACHE CHECK
    ¿Ya respondí algo similar? → reutilizar sin LLM ni embedding nuevo

  STAGE 2: SYMBOLIC ATTEMPT
    ¿Cognia tiene suficiente conocimiento estructurado?
    → responder con SymbolicResponder (0 tokens LLM)

  STAGE 3: HYBRID (simbólico + LLM enriquecido)
    ¿Confianza media? → construir base simbólica + LLM la enriquece
    con contexto MUY comprimido (reduce tokens 50-60%)

  STAGE 4: FULL LLM (con contexto optimizado)
    ¿Conocimiento insuficiente o creativo? → LLM completo pero con
    prompt comprimido por PromptOptimizer

  STAGE 5: FALLBACK
    Si LLM no responde → respuesta simbólica con advertencia

Integración:
  Sustituir en respuestas_articuladas.py:
    respuesta = llamar_ollama(prompt, ...)
  por:
    from language_engine import get_language_engine
    engine = get_language_engine(ai)
    resultado = engine.respond(ai, pregunta)
"""

import time
import uuid
import json
import os
import urllib.request
from dataclasses import dataclass, field
from typing import Optional, Dict, Any

try:
    from cognia.symbolic_responder import SymbolicResponder, UMBRAL_CONFIANZA, UMBRAL_FALLBACK, UMBRAL_MINIMO
except ImportError:
    from symbolic_responder import SymbolicResponder, UMBRAL_CONFIANZA, UMBRAL_FALLBACK, UMBRAL_MINIMO

try:
    from cognia.response_cache import ResponseCache
except ImportError:
    from response_cache import ResponseCache

try:
    from cognia.prompt_optimizer import PromptOptimizer, ContextCompressor
except ImportError:
    from prompt_optimizer import PromptOptimizer, ContextCompressor

# ── Singleton global (un engine por proceso) ──────────────────────────
_ENGINE_INSTANCE: Optional["LanguageEngine"] = None

def get_language_engine(cognia_instance=None) -> "LanguageEngine":
    global _ENGINE_INSTANCE
    if _ENGINE_INSTANCE is None:
        db = getattr(cognia_instance, "db", "cognia_memory.db") if cognia_instance else "cognia_memory.db"
        _ENGINE_INSTANCE = LanguageEngine(db_path=db)
    return _ENGINE_INSTANCE


# ══════════════════════════════════════════════════════════════════════
# RESULTADO DEL ENGINE
# ══════════════════════════════════════════════════════════════════════

@dataclass
class EngineResult:
    response:          str
    stage_used:        str           # "cache" | "symbolic" | "hybrid" | "llm" | "fallback"
    latency_ms:        float
    tokens_sent:       int           # tokens estimados enviados al LLM
    confidence:        float
    cache_hit:         bool
    used_llm:          bool
    symbolic_sources:  list = field(default_factory=list)
    question_type:     str  = "general"
    compression_ratio: float = 0.0
    response_id:       str  = field(default_factory=lambda: uuid.uuid4().hex[:12])
    # Metadatos extra para compatibilidad con respuestas_articuladas.py
    modelo:            str  = ""
    tipo_pregunta:     str  = ""
    tiene_contexto:    bool = False
    episodios_usados:  int  = 0
    info_suficiente:   bool = False
    investigated:      bool = False   # True si Stage 0 hizo investigación en Wikipedia

    def to_dict(self) -> Dict[str, Any]:
        return {
            "response":         self.response,
            "stage":            self.stage_used,
            "latency_ms":       round(self.latency_ms, 1),
            "tokens_sent":      self.tokens_sent,
            "confidence":       round(self.confidence, 3),
            "cache_hit":        self.cache_hit,
            "used_llm":         self.used_llm,
            "question_type":    self.question_type,
            "compression_ratio":round(self.compression_ratio, 3),
            "response_id":      self.response_id,
            "modelo":           self.modelo,
            "tipo_pregunta":    self.tipo_pregunta,
            "tiene_contexto":   self.tiene_contexto,
            "episodios_usados": self.episodios_usados,
            "info_suficiente":  self.info_suficiente,
            "investigated":     self.investigated,
        }


# ══════════════════════════════════════════════════════════════════════
# LANGUAGE ENGINE
# ══════════════════════════════════════════════════════════════════════

class LanguageEngine:
    """
    Motor de lenguaje híbrido para Cognia.

    Instanciar una vez y reutilizar:
        engine = LanguageEngine(db_path="cognia_memory.db")
        result = engine.respond(cognia_instance, pregunta)
    """

    def __init__(self, db_path: str = "cognia_memory.db",
                 ollama_url: str = None, modelo: str = None):
        self.db_path    = db_path
        self.ollama_url = ollama_url or os.environ.get("OLLAMA_URL", "http://localhost:11434")
        self.modelo     = modelo     or os.environ.get("COGNIA_MODEL", "llama3.2")

        self.symbolic   = SymbolicResponder()
        self.cache      = ResponseCache(db_path)
        self.optimizer  = PromptOptimizer(db_path)
        self.compressor = ContextCompressor()

        # Estadísticas de sesión
        self._stats = {
            "total": 0, "cache_hits": 0, "symbolic_only": 0,
            "hybrid": 0, "full_llm": 0, "fallbacks": 0,
        }
        print("[LanguageEngine] Motor híbrido inicializado.")

    # ── API principal ──────────────────────────────────────────────────

    def respond(self, cognia_instance, question: str,
                pre_built_context: str = "") -> EngineResult:
        """
        Genera una respuesta usando el pipeline de 5 etapas.

        Args:
            cognia_instance:   instancia de Cognia
            question:          pregunta del usuario
            pre_built_context: contexto ya construido por construir_contexto()
                               (si existe, evita reconstruirlo)
        """
        t0 = time.perf_counter()
        self._stats["total"] += 1
        ai = cognia_instance

        # ── Obtener vector de la pregunta ──────────────────────────────
        vec = self._get_vector(question)

        # ══════════════════════════════════════════════════════════════
        # STAGE 1: CACHE
        # ══════════════════════════════════════════════════════════════
        if vec:
            cached = self.cache.get(question, vec)
            if cached:
                self._stats["cache_hits"] += 1
                latency = (time.perf_counter() - t0) * 1000
                self._record_metrics("cache", question, cached.question_type,
                                     0, latency, True)
                return EngineResult(
                    response       = cached.response,
                    stage_used     = "cache",
                    latency_ms     = latency,
                    tokens_sent    = 0,
                    confidence     = cached.confidence,
                    cache_hit      = True,
                    used_llm       = False,
                    question_type  = cached.question_type,
                    tipo_pregunta  = cached.question_type,
                    tiene_contexto = True,
                    info_suficiente= True,
                )

        # ══════════════════════════════════════════════════════════════
        # STAGE 2: SYMBOLIC RESPONSE
        # ══════════════════════════════════════════════════════════════
        sym_response = self.symbolic.respond(ai, question)
        throttle_level = self._get_throttle_level(ai)

        if sym_response.confidence >= UMBRAL_CONFIANZA:
            self._stats["symbolic_only"] += 1
            latency = (time.perf_counter() - t0) * 1000
            # Guardar en caché para próximas veces
            if vec:
                self.cache.store(
                    question   = question,
                    response   = sym_response.text,
                    vector     = vec,
                    concept    = self._get_top_concept(ai, question),
                    confidence = sym_response.confidence,
                    used_llm   = False,
                )
            self._record_metrics("symbolic", question, sym_response.question_type,
                                 0, latency, False)
            return EngineResult(
                response         = sym_response.text,
                stage_used       = "symbolic",
                latency_ms       = latency,
                tokens_sent      = 0,
                confidence       = sym_response.confidence,
                cache_hit        = False,
                used_llm         = False,
                symbolic_sources = sym_response.sources,
                question_type    = sym_response.question_type,
                tipo_pregunta    = sym_response.question_type,
                tiene_contexto   = True,
                info_suficiente  = True,
            )

        # Si el nivel de carga es crítico → forzar respuesta simbólica
        if throttle_level == "critical":
            self._stats["symbolic_only"] += 1
            latency = (time.perf_counter() - t0) * 1000
            text = sym_response.text
            if sym_response.confidence < UMBRAL_MINIMO:
                text = (sym_response.text + "\n\n(Nota: el sistema está bajo alta "
                        "carga; esta respuesta viene de mi conocimiento estructurado.)")
            return EngineResult(
                response       = text,
                stage_used     = "symbolic_forced",
                latency_ms     = latency,
                tokens_sent    = 0,
                confidence     = sym_response.confidence,
                cache_hit      = False,
                used_llm       = False,
                question_type  = sym_response.question_type,
                tipo_pregunta  = sym_response.question_type,
                tiene_contexto = sym_response.confidence > 0.1,
            )

        # ══════════════════════════════════════════════════════════════
        # STAGES 3 & 4: LLM (HÍBRIDO O COMPLETO)
        # ══════════════════════════════════════════════════════════════

        # Stage 0 (lazy): construir o enriquecer contexto solo cuando el LLM
        # va a ser necesario. Si pre_built_context ya existe y es suficiente,
        # se reutiliza. Si no, se intenta investigación autónoma primero.
        context = pre_built_context or self._build_context(ai, question)
        context, investigated = self._maybe_investigate(ai, question, context)

        # Decidir entre híbrido y LLM completo
        is_hybrid = (UMBRAL_FALLBACK <= sym_response.confidence < UMBRAL_CONFIANZA)

        # Optimizar prompt
        q_type    = sym_response.question_type
        optimized = self.optimizer.optimize(question, context, q_type, throttle_level)

        # En modo híbrido: añadir la base simbólica al prompt
        if is_hybrid and sym_response.text:
            hybrid_prefix = (
                f"Tengo esta información base: {sym_response.text[:300]}\n\n"
                "Amplía y mejora esta respuesta usando el contexto adicional."
            )
            final_prompt = hybrid_prefix + "\n\n" + optimized.prompt
        else:
            final_prompt = optimized.prompt

        # Llamar al LLM
        llm_result = self._call_ollama(final_prompt, q_type, question)

        latency = (time.perf_counter() - t0) * 1000
        stage   = "hybrid" if is_hybrid else "llm"
        self._stats["hybrid" if is_hybrid else "full_llm"] += 1

        if llm_result["ok"]:
            response  = llm_result["text"]
            tokens_out = llm_result.get("tokens", 0)

            # Guardar en caché
            if vec and len(response) > 30:
                self.cache.store(
                    question   = question,
                    response   = response,
                    vector     = vec,
                    concept    = self._get_top_concept(ai, question),
                    confidence = max(sym_response.confidence, 0.45),
                    used_llm   = True,
                )

            self._record_metrics(stage, question, q_type,
                                 optimized.tokens_estimated, latency, True)
            return EngineResult(
                response          = response,
                stage_used        = stage,
                latency_ms        = latency,
                tokens_sent       = optimized.tokens_estimated,
                confidence        = max(sym_response.confidence, 0.45),
                cache_hit         = False,
                used_llm          = True,
                symbolic_sources  = sym_response.sources,
                question_type     = q_type,
                compression_ratio = optimized.compression_ratio,
                modelo            = self.modelo,
                tipo_pregunta     = q_type,
                tiene_contexto    = bool(context),
                episodios_usados  = context.count("- '") if context else 0,
                investigated      = investigated,
            )

        # ══════════════════════════════════════════════════════════════
        # STAGE 5: FALLBACK
        # ══════════════════════════════════════════════════════════════
        self._stats["fallbacks"] += 1
        latency  = (time.perf_counter() - t0) * 1000
        fallback = sym_response.text or (
            f"No pude procesar tu pregunta ahora mismo. "
            f"({llm_result.get('error', 'LLM no disponible')})"
        )
        return EngineResult(
            response       = fallback,
            stage_used     = "fallback",
            latency_ms     = latency,
            tokens_sent    = 0,
            confidence     = sym_response.confidence,
            cache_hit      = False,
            used_llm       = False,
            question_type  = q_type,
            tipo_pregunta  = q_type,
        )

    # ── Llamada a Ollama ───────────────────────────────────────────────

    def _call_ollama(self, prompt: str, question_type: str,
                     original_question: str) -> Dict:
        """Llama a Ollama con el prompt optimizado."""
        try:
            from cognia.prompt_optimizer import TOKEN_LIMITS
        except ImportError:
            from prompt_optimizer import TOKEN_LIMITS
        num_predict = TOKEN_LIMITS.get(question_type, 500)
        # Límites conservadores para CPU sin GPU
        num_predict = min(num_predict, 420)

        system = self._get_system_prompt(question_type)
        payload = json.dumps({
            "model":   self.modelo,
            "prompt":  prompt,
            "system":  system,
            "stream":  True,
            "options": {"temperature": 0.7, "num_predict": num_predict}
        }).encode("utf-8")

        try:
            req = urllib.request.Request(
                f"{self.ollama_url}/api/generate",
                data    = payload,
                headers = {"Content-Type": "application/json"},
            )
            tokens = []
            with urllib.request.urlopen(req, timeout=180) as r:
                for line in r:
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line.decode("utf-8"))
                    except Exception:
                        continue
                    tok = chunk.get("response", "")
                    if tok:
                        tokens.append(tok)
                    if chunk.get("done"):
                        break
            text = "".join(tokens).strip()
            # ── Paso 3: limpiar respuesta con LanguageCorrector ───────
            is_truncated = False
            try:
                from language_corrector import LanguageCorrector
                _lc = LanguageCorrector()
                text, is_truncated = _lc.clean_response(text)
            except ImportError:
                pass
            return {"ok": True, "text": text, "tokens": len(tokens),
                    "truncated": is_truncated}
        except Exception as e:
            return {"ok": False, "error": str(e), "text": ""}

    def _get_system_prompt(self, question_type: str) -> str:
        base = (
            "Eres Cognia, una IA con memoria episódica y grafo de conocimiento. "
            "Usa el contexto de memoria dado. Responde en el mismo idioma de la pregunta."
        )
        extras = {
            "lista":         " Lista máx 5 ítems, 1 oración cada uno.",
            "como_funciona": " Pasos numerados, máx 5 pasos.",
            "comparacion":   " 2-3 diferencias clave, máx 2 párrafos.",
            "definicion":    " 1-2 párrafos directos.",
        }
        return base + extras.get(question_type, " Máx 2 párrafos breves.")

    # ── Helpers ────────────────────────────────────────────────────────

    def _get_vector(self, text: str) -> Optional[list]:
        try:
            from cognia.vectors import text_to_vector
            return text_to_vector(text)
        except ImportError:
            try:
                from vectors import text_to_vector
                return text_to_vector(text)
            except Exception:
                return None
        except Exception:
            return None

    def _get_throttle_level(self, ai) -> str:
        try:
            if hasattr(ai, "throttle"):
                return ai.throttle.level
            if hasattr(ai, "fatigue") and ai.fatigue:
                adaps = ai.fatigue.get_adaptations()
                mode  = adaps.get("mode", "normal")
                return {"critical": "critical", "high": "low",
                        "moderate": "moderate"}.get(mode, "normal")
        except Exception:
            pass
        return "normal"

    def _get_top_concept(self, ai, question: str) -> Optional[str]:
        try:
            try:
                from cognia.vectors import text_to_vector
            except ImportError:
                from vectors import text_to_vector
            vec = text_to_vector(question)
            similares = ai.episodic.retrieve_similar(vec, top_k=3)
            assessment = ai.metacog.assess_confidence(similares)
            return assessment.get("top_label")
        except Exception:
            return None

    def _build_context(self, ai, question: str) -> str:
        """
        Construye contexto cognitivo completo.
        Intenta importar construir_contexto desde respuestas_articuladas
        con paths absoluto y relativo para robustez.
        """
        try:
            try:
                from respuestas_articuladas import construir_contexto
            except ImportError:
                from cognia.respuestas_articuladas import construir_contexto
            return construir_contexto(ai, question)
        except Exception:
            return ""

    def _knowledge_sufficient(self, ai, question: str) -> bool:
        """
        Consulta rapida a la DB: tiene Cognia suficiente informacion sobre
        el concepto principal de esta pregunta para no necesitar Wikipedia?

        Reutiliza tiene_suficiente_info de respuestas_articuladas sin duplicar
        la logica. Retorna True si el conocimiento es suficiente.
        """
        try:
            top_concept = self._get_top_concept(ai, question)
            if not top_concept:
                return False
            try:
                from respuestas_articuladas import tiene_suficiente_info
            except ImportError:
                from cognia.respuestas_articuladas import tiene_suficiente_info
            result = tiene_suficiente_info(ai, top_concept)
            return result.get("suficiente", False)
        except Exception:
            return False

    def _maybe_investigate(self, ai, question: str,
                           context: str) -> tuple:
        """
        Stage 0 (lazy): investiga en Wikipedia solo si el contexto es pobre
        y el conocimiento interno no es suficiente.

        Se llama DESPUES de que Stages 1 y 2 no dispararon, es decir, cuando
        el engine ha determinado que necesita el LLM. En ese punto vale la pena
        enriquecer el contexto antes de construir el prompt.

        Retorna (context_final: str, investigated: bool).
        El contexto devuelto puede ser el mismo de entrada (sin cambios)
        si la investigacion no fue necesaria o fallo.
        """
        # Si el contexto ya es rico, no investigar
        CONTEXT_RICH_THRESHOLD = 300   # caracteres -- heuristica barata
        if len(context) >= CONTEXT_RICH_THRESHOLD:
            return context, False

        # Si Cognia ya tiene suficiente conocimiento interno, no investigar
        if self._knowledge_sufficient(ai, question):
            return context, False

        # Intentar investigacion autonoma
        try:
            from investigador import investigar_si_necesario
            new_context, investigated, _info = investigar_si_necesario(
                ai, question, context
            )
            return new_context, investigated
        except ImportError:
            pass
        except Exception:
            pass

        return context, False

    def _record_metrics(self, stage: str, question: str, q_type: str,
                        tokens: int, latency_ms: float, used_llm: bool):
        try:
            self.optimizer.record_call(
                prompt_id     = uuid.uuid4().hex[:8],
                question_type = q_type,
                prompt_len    = len(question),
                context_len   = 0,
                response_len  = 0,
                latency_ms    = latency_ms,
                used_llm      = used_llm,
                cache_hit     = (stage == "cache"),
            )
        except Exception:
            pass

    # ── Stats y diagnóstico ────────────────────────────────────────────

    def stats(self) -> Dict:
        s = self._stats
        total = max(1, s["total"])
        return {
            "total_requests":   s["total"],
            "cache_hit_rate":   round(s["cache_hits"]    / total, 3),
            "symbolic_rate":    round(s["symbolic_only"] / total, 3),
            "hybrid_rate":      round(s["hybrid"]        / total, 3),
            "full_llm_rate":    round(s["full_llm"]      / total, 3),
            "fallback_rate":    round(s["fallbacks"]     / total, 3),
            "llm_avoided_pct":  round(
                (s["cache_hits"] + s["symbolic_only"]) / total * 100, 1
            ),
            "cache":            self.cache.stats(),
            "prompt_stats":     self.optimizer.get_stats(),
        }

    def run_prompt_evolution(self) -> Dict[str, str]:
        """
        Disparar evolución de prompts manualmente o desde el ciclo sleep().
        Retorna dict de prompts evolucionados.
        """
        evolved = self.optimizer.evolve_prompts()
        print(f"[LanguageEngine] Evolución completada: {len(evolved)} prompts actualizados")
        return evolved

    def invalidate_concept(self, concept: str) -> int:
        """Llamar cuando Cognia aprende algo nuevo sobre un concepto."""
        return self.cache.invalidate_concept(concept)

    def report_weak_zones(self) -> dict:
        """
        Paso 4: reporta zonas debiles del engine al SelfArchitect.

        Retorna un dict con metricas que el ArchitectureEvaluator puede
        inyectar en collect_metrics() para diagnosticar problemas del engine:

          engine_fallback_rate   — fraccion de requests que llegaron al Stage 5
          engine_cache_hit_rate  — eficiencia del cache semantico
          engine_llm_avoided_pct — % de respuestas sin llamar al LLM
          engine_symbolic_rate   — % respondidas solo con conocimiento simbolico
          engine_hybrid_rate     — % respondidas en modo hibrido
          engine_total_requests  — total de requests procesados esta sesion

        Si el fallback_rate > 0.2 o cache_hit_rate < 0.3, el architect
        deberia proponer ajustes en UMBRAL_CONFIANZA o cache TTLs.
        """
        s = self.stats()
        cache_stats = s.get("cache", {})
        return {
            "engine_fallback_rate":   s.get("fallback_rate",   0.0),
            "engine_cache_hit_rate":  s.get("cache_hit_rate",  0.0),
            "engine_llm_avoided_pct": s.get("llm_avoided_pct", 0.0),
            "engine_symbolic_rate":   s.get("symbolic_rate",   0.0),
            "engine_hybrid_rate":     s.get("hybrid_rate",     0.0),
            "engine_full_llm_rate":   s.get("full_llm_rate",   0.0),
            "engine_total_requests":  s.get("total_requests",  0),
            "engine_cache_ram_entries": cache_stats.get("ram_entries", 0),
            "engine_cache_hits":      cache_stats.get("hits",    0),
            "engine_cache_misses":    cache_stats.get("misses",  0),
        }
