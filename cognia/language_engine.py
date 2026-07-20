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
    from cognia_v3.interfaces.language_engine import get_language_engine
    engine = get_language_engine(ai)
    resultado = engine.respond(ai, pregunta)
"""

import re
import time
import threading
import uuid
import json
import os
import urllib.request
from dataclasses import dataclass, field
from typing import Optional, Dict, Any

try:
    from cognia.symbolic_responder import SymbolicResponder, UMBRAL_CONFIANZA, UMBRAL_FALLBACK, UMBRAL_MINIMO
except ImportError:
    from cognia_v3.interfaces.symbolic_responder import SymbolicResponder, UMBRAL_CONFIANZA, UMBRAL_FALLBACK, UMBRAL_MINIMO

from security.ollama_url import validate_ollama_url

# ── Thought-Chain Persistence (TCP) ──────────────────────────────────────────
_thought_cache = None   # type: ignore[assignment]  # ThoughtCache | None


def enable_thought_cache(db_path: str = "cognia_thought_cache.db") -> None:
    """Enable TCP — import is deferred so the module stays importable without numpy."""
    global _thought_cache
    from cognia.reasoning.thought_cache import ThoughtCache
    _thought_cache = ThoughtCache(db_path)


def disable_thought_cache() -> None:
    global _thought_cache
    _thought_cache = None

# KnowledgeCache fast-path (optional — gracefully absent)
try:
    from cognia.knowledge.knowledge_cache import KnowledgeCache as _KnowledgeCache
    _HAS_KNOWLEDGE_CACHE = True
except ImportError:
    _HAS_KNOWLEDGE_CACHE = False

# Pattern: informational questions that benefit from cached facts
_KNOWLEDGE_QUESTION_PAT = re.compile(
    r'^\s*(?:qu[eé]\s+es|qu[eé]\s+son|c[oó]mo\s+funciona|qui[eé]n\s+es|cu[aá]ndo\s+(?:fue|se|naci)|d[oó]nde\s+(?:est[aá]|fue)|'
    r'what\s+is|what\s+are|how\s+does|how\s+do|who\s+is|when\s+was|where\s+is)\b',
    re.IGNORECASE,
)

_KNOWLEDGE_STOPWORDS = frozenset({
    "que", "qué", "es", "son", "un", "una", "el", "la", "los", "las",
    "de", "del", "en", "y", "o", "a", "al", "lo", "como", "cómo",
    "funciona", "funcionan", "quien", "quién", "cuando", "cuándo",
    "donde", "dónde", "fue", "se", "está", "nació",
    "what", "is", "are", "how", "does", "do", "who", "when", "was", "where",
})


def _extract_topic(question: str) -> str:
    """Strip interrogative stopwords and return the 3-4 substantive words as topic."""
    tokens = re.sub(r"[^\w\s]", "", question.lower()).split()
    filtered = [t for t in tokens if t not in _KNOWLEDGE_STOPWORDS and len(t) > 2]
    return " ".join(filtered[:4]) if filtered else question[:40].lower()


# PASO 4: Decision Gate de tres zonas
try:
    from cognia.decision_gate import DecisionGate, GateAction, get_decision_gate
except ImportError:
    from cognia_v3.interfaces.decision_gate import DecisionGate, GateAction, get_decision_gate

# PASO 5: Tracker de fuentes de respuesta para feedback
try:
    from cognia.feedback_engine import get_feedback_tracker
    HAS_FEEDBACK_TRACKER = True
except ImportError:
    try:
        from cognia_v3.core.feedback_engine import get_feedback_tracker
        HAS_FEEDBACK_TRACKER = True
    except ImportError:
        HAS_FEEDBACK_TRACKER = False

from .logger_config import get_logger as _get_le_logger
_le_logger = _get_le_logger(__name__)

try:
    from cognia.memory_response_engine import MemoryContextBuilder
    HAS_MEM_BUILDER = True
except ImportError:
    try:
        from memory_response_engine import MemoryContextBuilder
        HAS_MEM_BUILDER = True
    except ImportError:
        HAS_MEM_BUILDER = False

# Si coverage de memoria supera este umbral, Ollama articula SOLO el contexto dado.
_MEMORY_PRIMARY_THRESHOLD = 0.45

_MEMORY_PRIMARY_SYSTEM_PROMPT = (
    "Eres Cognia, un sistema de IA cuya fuente de conocimiento real es su memoria episodica. "
    "El contexto provisto ES tu conocimiento real sobre este tema — no inventes ni agregues nada externo. "
    "Articula una respuesta coherente y natural usando UNICAMENTE la informacion del contexto dado. "
    "Si el contexto no cubre completamente la pregunta, dilo con honestidad. "
    "Maximo 3 parrafos claros. Responde en el idioma de la pregunta."
)

try:
    from cognia.response_cache import ResponseCache
except ImportError:
    from cognia_v3.interfaces.response_cache import ResponseCache

try:
    from cognia.prompt_optimizer import PromptOptimizer, ContextCompressor
except ImportError:
    from cognia_v3.interfaces.prompt_optimizer import PromptOptimizer, ContextCompressor

# ── Dynamic system prompt ─────────────────────────────────────────────
def _build_dynamic_system_prompt(ai) -> str:
    """Build a personalized system prompt using crystallized knowledge and user profile."""
    base = (
        "Eres Cognia, un sistema de inteligencia artificial cognitiva "
        "con memoria episodica, grafo de conocimiento y capacidad de aprendizaje. "
        "Fuiste creado por Tomas Montes. Tu creador es Tomas Montes."
    )
    additions = []
    try:
        cryst = ai.semantic.get_crystallized(min_support=5, min_confidence=0.8)
        if cryst:
            topics = ", ".join(c["concept"] for c in cryst[:5])
            additions.append(f"Temas que dominas: {topics}.")
    except Exception:
        pass
    try:
        profile = ai.user_profile.get_active()
        if profile and profile.get("name"):
            additions.append(f"El usuario se llama {profile['name']}.")
    except Exception:
        pass
    try:
        count = getattr(ai, 'interaction_count', 0)
        if count > 50:
            additions.append(f"Llevan {count} interacciones juntos.")
    except Exception:
        pass
    if additions:
        return base + " " + " ".join(additions)
    return base


# ── Project context reader ────────────────────────────────────────────
def _build_project_context(cwd: str = None, max_chars_per_file: int = 2000) -> str:
    """
    Lee archivos de descripcion del proyecto en el CWD.
    Prioridad: AGENTS.md / CLAUDE.md > README.md > pyproject.toml > ...
    Retorna string con el contenido relevante, o "" si no encuentra nada util.

    AGENTS.md va arriba, no al final: es el fichero cuyo proposito es decirle a
    un agente como comportarse en ESE proyecto, asi que si algo se recorta no
    puede ser lo primero en caerse. Convencion que salio de la investigacion
    del 2026-07-20 (`FerroxLabs/agents-md`, que la usa para forzar bucles de
    verificacion). Antes estaba detras incluso de setup.cfg.
    """
    import pathlib
    base = pathlib.Path(cwd or os.getcwd())
    candidates = [
        "AGENTS.md", "agents.md",
        "CLAUDE.md", "claude.md",
        "README.md", "README.rst", "readme.md",
        "pyproject.toml", "package.json", "setup.py", "setup.cfg",
    ]
    parts = []
    # En Windows el sistema de ficheros no distingue mayusculas, asi que
    # "AGENTS.md" y "agents.md" son el MISMO fichero y se leia dos veces: el
    # contexto del proyecto salia duplicado entero, y con n_ctx=8192 eso es
    # espacio que se le quita al trabajo. Se deduplica por ruta real.
    vistos = set()
    for name in candidates:
        p = base / name
        if not p.exists():
            continue
        try:
            clave = p.resolve()
        except OSError:
            clave = p
        if clave in vistos:
            continue
        vistos.add(clave)
        try:
            text = p.read_text(encoding="utf-8", errors="replace")[:max_chars_per_file]
            parts.append(f"--- {name} ---\n{text.strip()}")
        except Exception:
            continue
    return "\n\n".join(parts)


# ── ITCS: pipeline budget (fast | normal | deep) ─────────────────────
# Set per-request by cognia_desktop_api.py before calling engine.respond().
# Resets to "normal" after each request — callers must set it each time.
_pipeline_budget: str = "normal"


def set_pipeline_budget(budget: str) -> None:
    """Set the active pipeline budget for the next respond() call.

    budget: "fast" | "normal" | "deep"
    Called by cognia_desktop_api.py after ITCS complexity scoring.
    """
    global _pipeline_budget
    if budget in ("fast", "normal", "deep"):
        _pipeline_budget = budget


# ── CuriosityEngine + CuriosityWorker singletons ─────────────────────
_curiosity_engine = None
_curiosity_worker = None

try:
    from cognia.reasoning.curiosity_engine import CuriosityEngine as _CuriosityEngine
    from cognia.reasoning.curiosity_worker import CuriosityWorker as _CuriosityWorker
    _curiosity_engine = _CuriosityEngine()
    _curiosity_worker = _CuriosityWorker(_curiosity_engine)
    _curiosity_worker.start()
except Exception:
    pass  # non-fatal — curiosity disabled if DB or imports fail


# ── Singleton global (un engine por proceso) ──────────────────────────
_ENGINE_INSTANCE: Optional["LanguageEngine"] = None

def get_language_engine(cognia_instance=None, orchestrator=None) -> "LanguageEngine":
    global _ENGINE_INSTANCE
    if _ENGINE_INSTANCE is None:
        db = getattr(cognia_instance, "db", "cognia_memory.db") if cognia_instance else "cognia_memory.db"
        orch = orchestrator or getattr(cognia_instance, "_orchestrator", None)
        _ENGINE_INSTANCE = LanguageEngine(db_path=db, orchestrator=orch)
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
    # PASO 5: IDs de episodios usados para poder rastrear el feedback
    episode_ids:       list = field(default_factory=list)
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

    Si se pasa `orchestrator`, se usa como backend de inferencia primario
    cuando los shards Qwen estan disponibles; Ollama queda como fallback.
    """

    def __init__(self, db_path: str = "cognia_memory.db",
                 ollama_url: str = None, modelo: str = None,
                 orchestrator=None):
        self.db_path    = db_path
        self.ollama_url = validate_ollama_url(
            ollama_url or os.environ.get("OLLAMA_URL", "http://localhost:11434")
        )
        self.modelo     = modelo     or os.environ.get("COGNIA_MODEL", "llama3.2")
        # Optional ShatteringOrchestrator — used instead of Ollama when shards are ready
        self._orchestrator = orchestrator

        self.symbolic   = SymbolicResponder()
        self.cache      = ResponseCache(db_path)
        self.optimizer  = PromptOptimizer(db_path)
        self.compressor = ContextCompressor()

        # Estadísticas de sesión
        self._stats = {
            "total": 0, "cache_hits": 0, "symbolic_only": 0,
            "hybrid": 0, "full_llm": 0, "fallbacks": 0,
            "memory_primary": 0,   # llamadas al LLM en modo articulador restringido
        }
        # PASO 4: gate de decision de tres zonas
        self.gate = get_decision_gate()
        # Motor de contexto de memoria (Stage 0)
        self._mem_builder = MemoryContextBuilder() if HAS_MEM_BUILDER else None
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
        # Snapshot ITCS budget; reset module-level for next request (avoids leaking)
        import cognia.language_engine as _le_mod
        _active_budget = _le_mod._pipeline_budget
        _le_mod._pipeline_budget = "normal"

        # User facts: infer from user text in background (fire-and-forget)
        try:
            import threading as _uf_threading
            from cognia.social.user_facts import UserFactsMemory as _UFM_infer
            _uf_q = question
            def _bg_infer_user_facts():
                try:
                    _UFM_infer().infer_and_store(_uf_q)
                except Exception:
                    pass
            _uf_threading.Thread(target=_bg_infer_user_facts, daemon=True).start()
        except Exception:
            pass

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
        # STAGE 0.5: BYPASS SOCIAL — saludos y preguntas de identidad
        # van directo al LLM, el simbólico no puede responderlas bien
        # ══════════════════════════════════════════════════════════════
        _CREATOR_PAT = re.compile(
            r'\b(cre[oó]|hizo|dise[nñ][oó]|fabric[oó]|desarroll[oó]|program[oó]|quien.*hiz|autor|fundador|creador)\b',
            re.IGNORECASE
        )
        if _CREATOR_PAT.search(question):
            latency = (time.perf_counter() - t0) * 1000
            return EngineResult(
                response        = "Fui creado por Tomas Montes.",
                stage_used      = "identity_static",
                latency_ms      = latency,
                tokens_sent     = 0,
                confidence      = 1.0,
                cache_hit       = False,
                used_llm        = False,
                question_type   = "social",
                tipo_pregunta   = "social",
                tiene_contexto  = True,
                info_suficiente = True,
            )
        # ── Deterministic recall bypass ───────────────────────────────
        # Small LLMs hallucinate "no tengo memoria" for context-recall
        # questions; answer directly from ConversationContext buffer.
        _RECALL_PAT = re.compile(
            r'\b(que.*te.*dij[ei]|que.*te.*ped[íi]|[uú]ltimo.*mensaje|last.*message'
            r'|recuerdas.*que|lo.?[uú]ltimo|what.*last|lo.*que.*ped[íi]|lo.*que.*dij[ei]'
            r'|cual.*fue.*[uú]ltimo|cual.*fue.*lo.*[uú]ltimo|de.*que.*habl[aá]bamos'
            r'|qu[eé].*te.*pregunt[eé]|mi.*[uú]ltima.*pregunta|[uú]ltima.*cosa.*que'
            r'|what.*did.*i.*say|what.*was.*my.*last|do.*you.*remember.*what|remind.*me.*what)\b',
            re.IGNORECASE,
        )
        _NAME_PAT = re.compile(
            r'\b(c[oó]mo.*me.*llamo|cu[aá]l.*es.*mi.*nombre|sabes.*mi.*nombre'
            r'|recuerdas.*mi.*nombre|cu[aá]l.*era.*mi.*nombre)\b',
            re.IGNORECASE,
        )
        if _NAME_PAT.search(question) or _RECALL_PAT.search(question):
            try:
                from cognia_v3.memory.conversation_memory import get_conversation_context
                import re as _re
                _ctx = get_conversation_context(ai)
                _turns = _ctx._buffer.get_all() if hasattr(_ctx, '_buffer') else []
                _prev = [t for t in _turns if t.user_text.strip() != question.strip()]
                # Name-recall: only for name-specific questions
                if _NAME_PAT.search(question):
                    _NAME_DECL = _re.compile(
                        r'(?:mi nombre es|me llamo|soy)\s+([A-Za-zÁáÉéÍíÓóÚúÑñ]{2,30})',
                        _re.IGNORECASE,
                    )
                    for _t in reversed(_prev):
                        _m = _NAME_DECL.search(_t.user_text)
                        if _m:
                            _name = _m.group(1).capitalize()
                            latency = (time.perf_counter() - t0) * 1000
                            return EngineResult(
                                response        = f"Tu nombre es {_name}.",
                                stage_used      = "recall_static",
                                latency_ms      = latency,
                                tokens_sent     = 0,
                                confidence      = 1.0,
                                cache_hit       = False,
                                used_llm        = False,
                                question_type   = "recall",
                                tipo_pregunta   = "recall",
                                tiene_contexto  = True,
                                info_suficiente = True,
                            )
                # Last-message recall
                if _prev:
                    _last = _prev[-1]
                    _recall_resp = f"Tu ultimo mensaje fue: \"{_last.short_user(120)}\""
                    latency = (time.perf_counter() - t0) * 1000
                    return EngineResult(
                        response        = _recall_resp,
                        stage_used      = "recall_static",
                        latency_ms      = latency,
                        tokens_sent     = 0,
                        confidence      = 1.0,
                        cache_hit       = False,
                        used_llm        = False,
                        question_type   = "recall",
                        tipo_pregunta   = "recall",
                        tiene_contexto  = True,
                        info_suficiente = True,
                    )
            except Exception:
                pass

        # ══════════════════════════════════════════════════════════════
        # STAGE 0.3: KNOWLEDGE CACHE FAST-PATH
        # Only for informational questions (qué es, cómo funciona, etc.)
        # Bypasses LLM entirely when a cached fact is available.
        # ══════════════════════════════════════════════════════════════
        if _KNOWLEDGE_QUESTION_PAT.search(question):
            _kc = getattr(ai, "_knowledge_cache", None)
            if _kc is not None:
                try:
                    _topic = _extract_topic(question)
                    _cached_fact = _kc.get(_topic) if _topic else None
                    if _cached_fact:
                        latency = (time.perf_counter() - t0) * 1000
                        _le_logger.info(
                            "stage=knowledge_cache topic=%s",
                            _topic,
                            extra={"op": "language_engine.stage0_3", "context": "cache_hit"},
                        )
                        return EngineResult(
                            response        = _cached_fact,
                            stage_used      = "knowledge_cache",
                            latency_ms      = latency,
                            tokens_sent     = 0,
                            confidence      = 0.75,
                            cache_hit       = True,
                            used_llm        = False,
                            question_type   = "informativa",
                            tipo_pregunta   = "informativa",
                            tiene_contexto  = True,
                            info_suficiente = True,
                        )
                except Exception:
                    pass  # never block on cache error

        # ─────────────────────────────────────────────────────────────
        _q_type_pre, _ = self.symbolic.classifier.classify(question)
        if _q_type_pre == "social":
            _le_logger.info(
                "stage=social_bypass decision=llm reason=social_question",
                extra={"op": "language_engine.stage0_5", "context": f"q={question[:60]}"},
            )
            throttle_level = self._get_throttle_level(ai)
            investigated = False
            # Para preguntas sociales: NO usar contexto episódico
            # Solo el identity prompt — evita que memorias irrelevantes contaminen la respuesta
            _identity_context = _build_dynamic_system_prompt(ai)
            optimized  = self.optimizer.optimize(question, _identity_context, "social", throttle_level)
            llm_result = self._call_ollama(optimized.prompt, "social", question)
            latency    = (time.perf_counter() - t0) * 1000
            self._stats["full_llm"] += 1
            response = (
                llm_result["text"]
                if llm_result.get("ok") and llm_result.get("text")
                else "Hola, soy Cognia, un sistema de IA cognitiva. ¿En qué puedo ayudarte?"
            )
            if vec and len(response) > 20:
                self.cache.store(
                    question=question, response=response,
                    vector=vec, concept=None, confidence=0.90, used_llm=True,
                )
            return EngineResult(
                response        = response,
                stage_used      = "llm_social",
                latency_ms      = latency,
                tokens_sent     = optimized.tokens_estimated,
                confidence      = 0.90,
                cache_hit       = False,
                used_llm        = True,
                question_type   = "social",
                tipo_pregunta   = "social",
                tiene_contexto  = bool(pre_built_context),
                info_suficiente = True,
                investigated    = investigated,
            )

        # ══════════════════════════════════════════════════════════════
        # STAGE 0.45: PROJECT CONTEXT — preguntas sobre el proyecto actual
        # Lee archivos del CWD para responder sin contaminar con memoria
        # episódica de conversaciones anteriores.
        # ══════════════════════════════════════════════════════════════
        if _q_type_pre == "proyecto_actual":
            _proj_ctx = _build_project_context()
            _cwd_display = os.path.basename(os.getcwd()) or os.getcwd()
            if _proj_ctx:
                _proj_sys = (
                    "Eres Cognia, un asistente de IA. El usuario te pregunta sobre el "
                    "proyecto en el directorio de trabajo actual. A continuacion se "
                    "muestran los archivos de descripcion del proyecto. "
                    "Responde en el idioma de la pregunta de forma directa y concisa. "
                    "No inventes informacion fuera del contexto dado."
                )
                _proj_prompt = (
                    f"{_proj_sys}\n\n"
                    f"=== CONTEXTO DEL PROYECTO ===\n{_proj_ctx}\n"
                    f"=== FIN DEL CONTEXTO ===\n\n"
                    f"Pregunta: {question}"
                )
                _le_logger.info(
                    "stage=project_context cwd=%s",
                    _cwd_display,
                    extra={"op": "language_engine.stage0_45", "context": "cwd_scan"},
                )
                llm_result = self._call_ollama(_proj_prompt, "proyecto_actual", question)
                latency    = (time.perf_counter() - t0) * 1000
                self._stats["full_llm"] += 1
                response = (
                    llm_result["text"]
                    if llm_result.get("ok") and llm_result.get("text")
                    else "No encontre archivos de descripcion en el directorio actual."
                )
                return EngineResult(
                    response        = response,
                    stage_used      = "project_context",
                    latency_ms      = latency,
                    tokens_sent     = len(_proj_prompt) // 4,
                    confidence      = 0.92,
                    cache_hit       = False,
                    used_llm        = True,
                    question_type   = "proyecto_actual",
                    tipo_pregunta   = "proyecto_actual",
                    tiene_contexto  = True,
                    info_suficiente = True,
                )
            else:
                # Sin archivos de descripcion — retornar directo, sin tocar memoria episodica
                latency = (time.perf_counter() - t0) * 1000
                _le_logger.info(
                    "stage=project_context_empty cwd=%s",
                    _cwd_display,
                    extra={"op": "language_engine.stage0_45", "context": "no_files"},
                )
                return EngineResult(
                    response        = (
                        f"No encontre archivos de descripcion del proyecto en '{_cwd_display}'. "
                        f"Agrega un README.md o CLAUDE.md al directorio para que pueda responder."
                    ),
                    stage_used      = "project_context_empty",
                    latency_ms      = latency,
                    tokens_sent     = 0,
                    confidence      = 1.0,
                    cache_hit       = False,
                    used_llm        = False,
                    question_type   = "proyecto_actual",
                    tipo_pregunta   = "proyecto_actual",
                    tiene_contexto  = False,
                    info_suficiente = False,
                )

        # ══════════════════════════════════════════════════════════════
        # STAGE 0: MEMORY CONTEXT BUILD
        # Construye contexto desde memoria episódica/KG antes de llegar
        # al simbólico o al LLM. Si coverage es alto, Ollama solo articula
        # lo que la memoria provee, no genera desde su entrenamiento.
        # ══════════════════════════════════════════════════════════════
        _mem_ctx   = None
        _mem_sys   = None    # system prompt override para _call_ollama()
        if self._mem_builder is not None and vec:
            try:
                _mem_ctx = self._mem_builder.build(ai, question, vec)
                if _mem_ctx.coverage >= _MEMORY_PRIMARY_THRESHOLD:
                    _mem_sys = _MEMORY_PRIMARY_SYSTEM_PROMPT
                    self._stats["memory_primary"] += 1
                    _le_logger.info(
                        "stage=memory_primary coverage=%.3f episodes=%d facts=%d",
                        _mem_ctx.coverage, _mem_ctx.episode_count, _mem_ctx.fact_count,
                        extra={"op": "language_engine.stage0",
                               "context": f"label={_mem_ctx.top_label}"},
                    )
                # Si el caller no pasó contexto, usar el de memoria como base
                if not pre_built_context and _mem_ctx.text:
                    pre_built_context = _mem_ctx.text
            except Exception as _me:
                _le_logger.warning(
                    "Stage 0 memory build error: %s", _me,
                    extra={"op": "language_engine.stage0", "context": ""},
                )

        # Use ReasoningPlanner depth to gate complex processing downstream
        _plan_depth = 3
        try:
            if hasattr(ai, 'planner') and ai.planner:
                _rp = ai.planner.plan_reasoning_depth(question)
                _plan_depth = _rp.get("recommended_depth", 3)
        except Exception:
            pass

        # ══════════════════════════════════════════════════════════════
        # STAGE 2: SYMBOLIC RESPONSE + DECISION GATE (PASO 4)
        # ══════════════════════════════════════════════════════════════
        sym_response   = self.symbolic.respond(ai, question)
        throttle_level = self._get_throttle_level(ai)

        # PASO 5: extraer episode_ids del último retrieve_similar para rastrear feedback.
        # Se recogen del estado interno de ai.episodic — sin coste extra
        # porque retrieve_similar() ya fue llamado dentro de symbolic.respond().
        def _collect_ep_ids(ai_inst) -> list:
            try:
                # La función retrieve_similar() actualiza access_count en DB
                # pero no expone los IDs usados. Los recuperamos del contexto
                # de la última llamada vía los similares del assessment.
                try:
                    from cognia.vectors import text_to_vector as _tv
                except ImportError:
                    from vectors import text_to_vector as _tv
                _v = _tv(question)
                _sims = ai_inst.episodic.retrieve_similar(_v, top_k=5)
                return [s["id"] for s in _sims if s.get("id") and s["similarity"] > 0.20]
            except Exception:
                return []

        # Forzar simbólico si el sistema está bajo carga crítica
        if throttle_level == "critical":
            self._stats["symbolic_only"] += 1
            latency = (time.perf_counter() - t0) * 1000
            text = sym_response.text
            if sym_response.confidence < 0.30:
                text = (sym_response.text + "\n\n(Nota: el sistema está bajo alta "
                        "carga; esta respuesta viene de mi conocimiento estructurado.)")
            _le_logger.info(
                "stage=decision confidence={:.3f} decision=symbolic_forced "
                "reason=critical_throttle".format(sym_response.confidence),
                extra={"op": "language_engine.stage2", "context": "throttle=critical"},
            )
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
                tiene_contexto = sym_response.confidence > 0.10,
            )

        # PASO 4: Decision Gate de tres zonas
        # vec ya fue calculado en Stage 1 (cache check) - reutilizar
        gate_decision = self.gate.evaluate(
            sym_response    = sym_response,
            question        = question,
            question_vec    = vec,
            cognia_instance = ai,
        )

        if gate_decision.action == GateAction.SYMBOLIC:
            # Zona alta + relevancia OK - simbólico directo
            self._stats["symbolic_only"] += 1
            latency = (time.perf_counter() - t0) * 1000
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

            # PASO 5: recoger IDs y registrar en tracker
            _ep_ids    = _collect_ep_ids(ai)
            _concepts  = [self._get_top_concept(ai, question)] if self._get_top_concept(ai, question) else []
            _result_sym = EngineResult(
                response         = sym_response.text,
                stage_used       = "symbolic",
                latency_ms       = latency,
                tokens_sent      = 0,
                confidence       = sym_response.confidence,
                cache_hit        = False,
                used_llm         = False,
                symbolic_sources = sym_response.sources,
                episode_ids      = _ep_ids,
                question_type    = sym_response.question_type,
                tipo_pregunta    = sym_response.question_type,
                tiene_contexto   = True,
                info_suficiente  = True,
            )
            if HAS_FEEDBACK_TRACKER:
                get_feedback_tracker().register_response(
                    response_id   = _result_sym.response_id,
                    question      = question,
                    response_text = sym_response.text,
                    stage_used    = "symbolic",
                    confidence    = sym_response.confidence,
                    episode_ids   = _ep_ids,
                    concepts      = _concepts,
                )
            return _result_sym

        # Zona media o baja - LLM necesario
        # ══════════════════════════════════════════════════════════════
        # STAGE 2B: SEGUNDA OPORTUNIDAD SIMBÓLICA (PASO 4)
        # ══════════════════════════════════════════════════════════════
        # Si el gate rechazó por low_relevance (no por low_confidence),
        # intentar la síntesis multi-fuente que ancla al vector de la pregunta.
        if gate_decision.reason in ("low_relevance", "medium_confidence_low_relevance"):
            try:
                from cognia.symbolic_synthesizer import get_synthesizer as _get_synth
            except ImportError:
                try:
                    from cognia_v3.interfaces.symbolic_synthesizer import get_synthesizer as _get_synth
                except ImportError:
                    _get_synth = None

            if _get_synth is not None:
                try:
                    _synth2  = _get_synth()
                    _sr2     = _synth2.synthesize(ai, question, vec)

                    if not _sr2.fallback and _sr2.confidence >= 0.12:
                        # Re-evaluar con el gate usando la respuesta sintetizada
                        try:
                            from cognia.symbolic_responder import SymbolicResponse as _SR
                        except ImportError:
                            from cognia_v3.interfaces.symbolic_responder import SymbolicResponse as _SR
                        _sym2 = _SR(
                            text          = _sr2.text,
                            confidence    = _sr2.confidence,
                            used_llm      = False,
                            sources       = _sr2.sources_used,
                            question_type = sym_response.question_type,
                        )
                        _gate2 = self.gate.evaluate(
                            sym_response    = _sym2,
                            question        = question,
                            question_vec    = vec,
                            cognia_instance = ai,
                        )
                        _le_logger.info(
                            f"stage=synthesis_retry "
                            f"confidence={_sr2.confidence:.3f} "
                            f"decision={_gate2.action.value} "
                            f"reason={_gate2.reason} "
                            f"relevance={_gate2.relevance_score:.3f} "
                            f"episodes={_sr2.episodes_used} facts={_sr2.facts_used}",
                            extra={
                                "op":      "language_engine.stage2b",
                                "context": f"original_reason={gate_decision.reason}",
                            },
                        )

                        if _gate2.action == GateAction.SYMBOLIC:
                            self._stats["symbolic_only"] += 1
                            latency = (time.perf_counter() - t0) * 1000
                            if vec:
                                self.cache.store(
                                    question   = question,
                                    response   = _sr2.text,
                                    vector     = vec,
                                    concept    = self._get_top_concept(ai, question),
                                    confidence = _sr2.confidence,
                                    used_llm   = False,
                                )
                            self._record_metrics("symbolic", question,
                                                 sym_response.question_type,
                                                 0, latency, False)
                            return EngineResult(
                                response         = _sr2.text,
                                stage_used       = "symbolic_synthesized",
                                latency_ms       = latency,
                                tokens_sent      = 0,
                                confidence       = _sr2.confidence,
                                cache_hit        = False,
                                used_llm         = False,
                                symbolic_sources = _sr2.sources_used,
                                question_type    = sym_response.question_type,
                                tipo_pregunta    = sym_response.question_type,
                                tiene_contexto   = True,
                                info_suficiente  = True,
                            )

                        if _gate2.action == GateAction.HYBRID:
                            sym_response  = _sym2
                            gate_decision = _gate2
                except Exception as _se:
                    _le_logger.warning(
                        "Stage 2B synthesis_retry falló",
                        extra={"op": "language_engine.stage2b", "context": str(_se)},
                    )

        # ══════════════════════════════════════════════════════════════
        # STAGES 3 & 4: LLM (HÍBRIDO O COMPLETO)
        # ══════════════════════════════════════════════════════════════

        # Confidence gate: if symbolic confidence is very low AND no memory context, refuse rather than hallucinate
        if (gate_decision.action == GateAction.LLM
                and sym_response.confidence < 0.15
                and not pre_built_context
                and (_mem_ctx is None or _mem_ctx.coverage < 0.1)):
            _low_conf_response = (
                "No tengo suficiente informacion en mi memoria para responder esto con certeza. "
                "Puedes ensenharme mas sobre este tema usando el comando /aprender, "
                "o reformula la pregunta con mas contexto."
            )
            latency = (time.perf_counter() - t0) * 1000
            return EngineResult(
                response        = _low_conf_response,
                stage_used      = "low_confidence_refusal",
                latency_ms      = latency,
                tokens_sent     = 0,
                confidence      = sym_response.confidence,
                cache_hit       = False,
                used_llm        = False,
                question_type   = sym_response.question_type,
                tipo_pregunta   = sym_response.question_type,
                tiene_contexto  = False,
                info_suficiente = False,
            )

        # Stage 0 (lazy): construir o enriquecer contexto solo cuando el LLM
        # va a ser necesario. Si pre_built_context ya existe y es suficiente,
        # se reutiliza. Si no, se intenta investigación autónoma primero.
        # PASO 3: construir_contexto() ya incluye el bloque conversacional.
        context = pre_built_context or self._build_context(ai, question)
        context, investigated = self._maybe_investigate(ai, question, context)

        # PASO 3: detectar cambio de tema + SIEMPRE prepend conversation block.
        # Cuando pre_built_context proviene del Stage 0 de memoria, _build_context()
        # no se ejecuta y el historial de conversación se pierde. Este bloque lo
        # restaura de forma barata (in-memory, sin DB queries extra).
        try:
            from cognia_v3.memory.conversation_memory import get_conversation_context
            _conv_ctx = get_conversation_context(ai)
            self._topic_changed_hint = _conv_ctx.topic_changed_last()
            if vec:
                _conv_block = _conv_ctx.build_context_block(question, vec)
                if _conv_block and _conv_block not in context:
                    context = _conv_block + ("\n\n" + context if context else "")
        except Exception:
            self._topic_changed_hint = False

        # Usar gate para determinar híbrido vs LLM completo
        is_hybrid = (gate_decision.action == GateAction.HYBRID)

        # Optimizar prompt
        q_type    = sym_response.question_type
        optimized = self.optimizer.optimize(question, context, q_type, throttle_level)

        # Reasoning enrichment for complex questions — only when planner says depth >= 2
        _reasoning_confidence = None
        _has_contradiction = False
        # TCP: check thought cache before calling enrich_with_meta
        _tc_hit = None
        if _thought_cache is not None:
            _tc_hit = _thought_cache.lookup(question)
        if _plan_depth >= 2 and _active_budget != "fast":
            if _tc_hit is not None:
                # Replay cached reasoning chain — skip enrich_with_meta() call
                _enriched_ctx       = _tc_hit.get("reasoning_context", context) or context
                _reasoning_confidence = _tc_hit.get("confidence", 0.5)
                _has_contradiction    = _tc_hit.get("has_contradiction", False)
                if _enriched_ctx != context:
                    context = _enriched_ctx
                    optimized = self.optimizer.optimize(question, _enriched_ctx, q_type, throttle_level)
            else:
                try:
                    from cognia.reasoning.cognia_reasoning_engine import CogniaReasoningEngine as _CRE
                    _meta = _CRE().enrich_with_meta(question, context, q_type)
                    _enriched_ctx = _meta["context"]
                    _reasoning_confidence = _meta["confidence"]
                    _has_contradiction = _meta["has_contradiction"]
                except Exception:
                    _enriched_ctx = context
                if _enriched_ctx != context:
                    context = _enriched_ctx
                    optimized = self.optimizer.optimize(question, _enriched_ctx, q_type, throttle_level)

        # Low-confidence gate: uncertain reasoning promotes LLM-only to hybrid
        # so the symbolic base anchors the response on uncertain queries
        if (not is_hybrid
                and _reasoning_confidence is not None
                and _reasoning_confidence < 0.4
                and gate_decision.action.value == "llm"):
            is_hybrid = True
            _le_logger.info(
                "reasoning_confidence=%.2f has_contradiction=%s -> promoted to hybrid",
                _reasoning_confidence, _has_contradiction,
                extra={"op": "language_engine.reasoning_gate", "context": ""},
            )

        if _plan_depth >= 3 and _active_budget not in ("fast",) and q_type in ('comparacion', 'general', 'como_funciona', 'definicion'):
            try:
                from cognia.reasoning.hypothesis import HypothesisModule as _HM
                _hmod = _HM()
                _words = [w for w in question.split() if len(w) > 4 and w.isalpha()][:4]
                if len(_words) >= 2 and _hmod.semantic is not None:
                    _hyp = _hmod.generate(_words[0], _words[1])
                    if (_hyp and isinstance(_hyp, dict)
                            and _hyp.get('confidence', 0) > 0.4
                            and 'hypothesis' in _hyp):
                        context = f"[Hipotesis interna: {_hyp['hypothesis']}]\n{context}"
                        optimized = self.optimizer.optimize(question, context, q_type, throttle_level)
            except Exception:
                pass

        # Epistemic gate: internal self-questioning pass for medium-low confidence + complex questions
        # Runs silently — never shown to user; prepended as context the LLM uses to self-anchor.
        # Same pattern as [Hipotesis interna: ...] above — prefixed context, not instruction.
        if (
            _reasoning_confidence is not None
            and 0.15 < _reasoning_confidence < 0.45
            and _plan_depth >= 2
            and _active_budget != "fast"
            and q_type not in ('social', 'confirmacion', 'corta')
        ):
            try:
                _SELF_QUESTIONS = [
                    "Que estoy asumiendo en esta pregunta?",
                    "Que evidencia tengo en mi memoria?",
                    "Que alternativas existen?",
                    "Hay alguna contradiccion en lo que se pregunta?",
                ]
                _sq_lines = []
                for _sq in _SELF_QUESTIONS:
                    _sq_keywords = _sq.lower().split()[:3]
                    if not any(kw in context.lower() for kw in _sq_keywords):
                        _sq_lines.append(f"- {_sq}")
                if _sq_lines:
                    _sq_block = "[Analisis interno]\n" + "\n".join(_sq_lines) + "\n"
                    context = _sq_block + context
                    optimized = self.optimizer.optimize(question, context, q_type, throttle_level)
                    _le_logger.debug(
                        "epistemic_gate: confidence=%.2f, self_questions_prepended=True",
                        _reasoning_confidence,
                    )
            except Exception:
                pass

        # Planning context: prepend symbolic plan when task is complex and non-generic
        # so the LLM can follow the decomposition implicitly without extra instructions.
        if _plan_depth >= 3 and _active_budget != "fast":
            try:
                from cognia.agents.planner import classify_task as _ct, plan_task as _pt
                _task_type = _ct(question)
                if _task_type is not None:
                    _plan = _pt(question)
                    if _plan and len(_plan) > 1:
                        _plan_lines = [
                            f"  {i+1}. {getattr(st, 'description', str(st))}"
                            for i, st in enumerate(_plan[:4])
                        ]
                        _plan_ctx = "[Plan de razonamiento]\n" + "\n".join(_plan_lines) + "\n"
                        context = _plan_ctx + context
                        optimized = self.optimizer.optimize(question, context, q_type, throttle_level)
            except Exception:
                pass

        # TCP: store thought chain after all reasoning blocks have run
        if _thought_cache is not None and _tc_hit is None and _reasoning_confidence is not None:
            _thought_cache.store(question, {
                "reasoning_context": context,
                "confidence":        _reasoning_confidence,
                "has_contradiction": _has_contradiction,
                "sub_questions":     [],
                "hypothesis":        locals().get("_hyp", {}).get("hypothesis") if "_hyp" in dir() else None,
                "task_type":         locals().get("_task_type") if "_task_type" in dir() else None,
                "plan_steps":        [],
            })

        # En modo híbrido: añadir la base simbólica al prompt
        if is_hybrid and sym_response.text:
            hybrid_prefix = (
                f"Tengo esta información base: {sym_response.text[:300]}\n\n"
                "Amplía y mejora esta respuesta usando el contexto adicional."
            )
            final_prompt = hybrid_prefix + "\n\n" + optimized.prompt
        else:
            final_prompt = optimized.prompt

        # Inyectar contexto de metas y curiosity — fire-and-forget safe
        if _context_injector is not None:
            _ctx_block = _context_injector.get_context_block(
                getattr(self, "_user_id", "local")
            )
            if _ctx_block:
                final_prompt = _ctx_block + "\n\n" + final_prompt

        # Inyectar temas recurrentes consolidados desde memoria a largo plazo
        try:
            from cognia.memory.long_term_consolidator import LongTermConsolidator as _LTC
            _ltc_summary = _LTC().get_summary("default")
            if _ltc_summary:
                final_prompt = f"[Memoria a largo plazo]: {_ltc_summary}\n\n" + final_prompt
        except ImportError:
            pass
        except Exception:
            pass

        # Adaptive length instruction — appended based on question complexity
        _LENGTH_BY_TYPE = {
            "social":         " Responde en 1-2 oraciones, natural y directo.",
            "factual_simple": " Responde en 1-3 oraciones concretas.",
            "math":           " Muestra el resultado y los pasos clave, sin relleno.",
            "codigo":         " Solo el codigo relevante con comentario minimo si es necesario.",
        }
        _len_hint = _LENGTH_BY_TYPE.get(q_type, "")
        if _len_hint and not is_hybrid:
            final_prompt = final_prompt + _len_hint

        # Anti-echo: if question contains assertion bias, add counter-perspective signal
        _anti_echo_sys = _mem_sys
        _ASSERT_PAT = re.compile(
            r'\b(no es cierto|verdad que|isn.t it|obviously|clearly|definitely|'
            r'siempre es mejor|nunca funciona|todos saben|evidentemente|por supuesto que)\b',
            re.IGNORECASE
        )
        if _ASSERT_PAT.search(question):
            _anti_echo_note = (
                "\n\nIMPORTANT: The user's question contains a strong assertion. "
                "Before agreeing, consider at least one alternative perspective or counterexample. "
                "Be honest if the assertion is not universally true."
            )
            _anti_echo_sys = (_mem_sys or "") + _anti_echo_note

        # Llamar al LLM
        llm_result = self._call_ollama(final_prompt, q_type, question,
                                       system_override=_anti_echo_sys)

        latency = (time.perf_counter() - t0) * 1000
        stage   = "hybrid" if is_hybrid else "llm"
        self._stats["hybrid" if is_hybrid else "full_llm"] += 1

        if llm_result["ok"]:
            response  = llm_result["text"]
            tokens_out = llm_result.get("tokens", 0)

            # Self-correction: check if response contradicts a high-confidence stored fact
            try:
                if hasattr(ai, 'contradiction') and len(response) > 50:
                    _corr_check = ai.contradiction.check(response, q_type, vec, ai.semantic)
                    if _corr_check:
                        response = response + (
                            "\n\n[Nota: esto puede entrar en conflicto con algo que aprendi antes. "
                            "Verifica si es correcto.]"
                        )
            except Exception:
                pass

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

            # PASO 5: recoger IDs y registrar en tracker
            _ep_ids_llm   = _collect_ep_ids(ai)
            _top_c_llm    = self._get_top_concept(ai, question)
            _concepts_llm = [_top_c_llm] if _top_c_llm else []
            _result_llm   = EngineResult(
                response          = response,
                stage_used        = stage,
                latency_ms        = latency,
                tokens_sent       = optimized.tokens_estimated,
                confidence        = max(sym_response.confidence, 0.45),
                cache_hit         = False,
                used_llm          = True,
                symbolic_sources  = sym_response.sources,
                episode_ids       = _ep_ids_llm,
                question_type     = q_type,
                compression_ratio = optimized.compression_ratio,
                modelo            = self.modelo,
                tipo_pregunta     = q_type,
                tiene_contexto    = bool(context),
                episodios_usados  = context.count("- '") if context else 0,
                investigated      = investigated,
            )
            if HAS_FEEDBACK_TRACKER:
                get_feedback_tracker().register_response(
                    response_id   = _result_llm.response_id,
                    question      = question,
                    response_text = response,
                    stage_used    = stage,
                    confidence    = max(sym_response.confidence, 0.45),
                    episode_ids   = _ep_ids_llm,
                    concepts      = _concepts_llm,
                )

            # Auto-populate KG from user question + AI response (silent, best-effort)
            try:
                if hasattr(ai, 'kg'):
                    ai.kg.extract_and_store(question + " " + response, source="conversation")
            except Exception:
                pass

            # Quality scoring — fire-and-forget so it never delays the response
            if _plan_depth >= 1:
                def _score_and_persist(_q=question, _r=response, _db=self.db_path):
                    try:
                        from cognia.quality.response_scorer import ResponseScorer
                        _sc = ResponseScorer(_db)
                        _sc.persist(_q, _r, _sc.score(_q, _r))
                    except Exception:
                        pass
                _t = threading.Thread(target=_score_and_persist, daemon=True)
                _t.start()

            # CuriosityEngine — fire-and-forget when confidence is low
            _conf_for_curiosity = (
                _reasoning_confidence
                if _reasoning_confidence is not None
                else _result_llm.confidence
            )
            if _curiosity_engine is not None and _conf_for_curiosity < 0.4:
                threading.Thread(
                    target=_curiosity_engine.enqueue,
                    args=(
                        _curiosity_engine.generate_questions(
                            question, response, _conf_for_curiosity
                        ),
                        question,
                    ),
                    daemon=True,
                ).start()

            return _result_llm

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
                     original_question: str, system_override: str = None) -> Dict:
        """
        Llama al backend de inferencia con el prompt optimizado.

        Prioridad:
          1. ShatteringOrchestrator (shards Qwen reales) — si disponible y listo
          2. Ollama — como fallback
        """
        # Delegate to shard pipeline when real weights are present
        if (self._orchestrator is not None
                and hasattr(self._orchestrator, "shards_ready")
                and self._orchestrator.shards_ready()):
            try:
                result = self._orchestrator.infer(prompt)
                return {"ok": True, "text": result.text, "tokens": 0, "truncated": False}
            except Exception as _shard_exc:
                _le_logger.warning(
                    "Shard inference failed, falling back to Ollama: %s", _shard_exc,
                    extra={"op": "language_engine._call_ollama", "context": "shard_fallback"},
                )

        try:
            from cognia.prompt_optimizer import TOKEN_LIMITS
        except ImportError:
            from cognia_v3.interfaces.prompt_optimizer import TOKEN_LIMITS
        num_predict = TOKEN_LIMITS.get(question_type, 500)
        # Límites conservadores para CPU sin GPU
        num_predict = min(num_predict, 900)

        # Prioridad: caller override > frontend override > default por tipo de pregunta
        system = (
            system_override or
            getattr(self, "_system_override", None) or
            self._get_system_prompt(question_type)
        )
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
                from cognia_v3.interfaces.language_corrector import LanguageCorrector
                _lc = LanguageCorrector()
                text, is_truncated = _lc.clean_response(text)
            except ImportError:
                pass
            return {"ok": True, "text": text, "tokens": len(tokens),
                    "truncated": is_truncated}
        except Exception as e:
            try:
                from cognia_v3.interfaces.model_router import _llamar_shard_network
                shard_text = _llamar_shard_network(prompt, question_type)
                if shard_text:
                    return {"ok": True, "text": shard_text, "tokens": 0, "truncated": False}
            except Exception:
                pass
            return {"ok": False, "error": str(e), "text": ""}

    def _get_system_prompt(self, question_type: str, query_hint: str = "") -> str:
        base = (
            "Eres Cognia, una IA con memoria episódica y grafo de conocimiento, "
            "creada por Tomas Montes. "
            "Usa el contexto de memoria dado. "
            "Si hay una sección CONVERSACIÓN RECIENTE en el contexto, "
            "úsala para mantener la coherencia y continuidad de la charla: "
            "evita repetir lo que ya explicaste y conecta tu respuesta con "
            "lo dicho antes cuando sea relevante. "
            "Responde en el mismo idioma de la pregunta."
        )
        extras = {
            "lista":         " Lista máx 5 ítems, 1 oración cada uno.",
            "como_funciona": " Pasos numerados, máx 5 pasos.",
            "comparacion":   " 2-3 diferencias clave, máx 2 párrafos.",
            "definicion":    " 1-2 párrafos directos.",
        }
        topic_hint = ""
        if getattr(self, "_topic_changed_hint", False):
            topic_hint = (
                " IMPORTANTE: el usuario ha cambiado de tema. "
                "Responde únicamente sobre la nueva pregunta, "
                "sin mezclar información del tema anterior."
            )
        system_prompt = base + extras.get(question_type, " Máx 2 párrafos breves.") + topic_hint
        # persona instruction — prepended if configured for this user
        if _persona_manager is not None:
            _persona_instr = _persona_manager.get_persona_instruction(
                getattr(self, "_user_id", "local")
            )
            if _persona_instr:
                system_prompt = _persona_instr + "\n\n" + system_prompt

        # ── Collect injection blocks then prioritize ──────────────────
        _injection_blocks = []

        try:
            from cognia.adaptive.feedback_learner import FeedbackLearner as _FL
            _hint = _FL().get_adjustment_hint(question_type)
            if _hint:
                _injection_blocks.append({"type": "feedback", "content": "[Ajuste adaptativo]: " + _hint})
        except Exception:
            pass
        try:
            from cognia.reasoning.self_critic import SelfCritic as _SC
            _recent = _SC().get_recent_critiques(1)
            if _recent and _recent[0].get("overall_score", 1.0) < 0.8:
                _injection_blocks.append({"type": "autocritica", "content": "[Autocritica previa]: " + _recent[0]["critique"]})
        except Exception:
            pass
        try:
            from cognia.knowledge.crystallizer import KnowledgeCrystallizer as _KC
            _cryst_ctx = _KC().get_injection_context(5)
            if _cryst_ctx:
                _injection_blocks.append({"type": "crystallized_kg", "content": "[Conocimiento cristalizado]: " + _cryst_ctx})
        except Exception:
            pass
        try:
            from cognia.social.user_facts import UserFactsMemory as _UFM
            _uf_ctx = _UFM().get_context(5)
            if _uf_ctx:
                _injection_blocks.append({"type": "user_facts", "content": _uf_ctx})
        except Exception:
            pass

        if _injection_blocks:
            try:
                from cognia.context.injection_prioritizer import InjectionPrioritizer as _IP
                _selected = _IP().prioritize(_injection_blocks, query=query_hint, max_blocks=4)
                _injected = _IP().build_context_string(_selected)
            except Exception:
                # Fallback: concatenate all blocks (original behavior)
                _injected = "\n".join(b["content"] for b in _injection_blocks)
            if _injected:
                system_prompt = system_prompt + "\n" + _injected

        return system_prompt

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
                from cognia_v3.interfaces.respuestas_articuladas import construir_contexto
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
            # El concepto mas fuerte de la memoria no es necesariamente EL DE
            # LA PREGUNTA: la recuperacion siempre devuelve el vecino mas
            # cercano, por lejos que este. Sin este chequeo, saber mucho de un
            # tema ajeno se contaba como saber del que se pregunta. Caso real
            # (2026-07-19): pregunta sobre los modelos MiniCPM de OpenBMB ->
            # top_concept 'conocimiento_python' -> "conocimiento suficiente" ->
            # no se investigaba y el modelo inventaba nombres de modelos.
            if not self._contexto_pertinente(question,
                                             str(top_concept).replace("_", " ")):
                return False
            try:
                from cognia_v3.interfaces.respuestas_articuladas import tiene_suficiente_info
            except ImportError:
                from cognia.respuestas_articuladas import tiene_suficiente_info
            result = tiene_suficiente_info(ai, top_concept)
            return result.get("suficiente", False)
        except Exception:
            return False

    def _contexto_pertinente(self, question: str, context: str,
                             minimo: int = 1) -> bool:
        """El contexto recuperado habla de lo que se pregunto?

        Compara terminos de contenido (sin acentos, sin palabras vacias, 4+
        letras) reutilizando investigador._terminos para no duplicar la logica.
        Ante cualquier fallo devuelve True, que es el comportamiento previo: si
        no se puede evaluar la pertinencia, no se fuerza una investigacion.
        """
        try:
            from investigador import _terminos
        except ImportError:
            return True
        try:
            terminos_pregunta = _terminos(question)
            if not terminos_pregunta:
                return True
            return len(terminos_pregunta & _terminos(context)) >= minimo
        except Exception:
            return True

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
        # Si el contexto ya es rico Y HABLA DEL TEMA, no investigar.
        #
        # La heuristica era solo de longitud, y contar caracteres no distingue
        # "sé mucho de esto" de "sé mucho de otra cosa". Caso real
        # (2026-07-19): ante una pregunta sobre los modelos MiniCPM de OpenBMB,
        # la memoria devolvio 15 episodios del concepto 'conocimiento_python';
        # el contexto superaba los 300 caracteres, esta compuerta cortaba aca y
        # la investigacion no llegaba a ejecutarse nunca. El modelo respondia de
        # memoria parametrica —recomendando DINOv2 para leer capturas, y en otra
        # corrida inventando que BLIP significa "Bootstrap-Large-Language-Model-
        # Instruct"— mientras la busqueda web ya recuperaba 12 de 12 fuentes
        # correctas que se descartaban sin usarse.
        CONTEXT_RICH_THRESHOLD = 300   # caracteres -- heuristica barata
        if len(context) >= CONTEXT_RICH_THRESHOLD and \
                self._contexto_pertinente(question, context):
            return context, False

        # Si Cognia ya tiene suficiente conocimiento interno, no investigar
        if self._knowledge_sufficient(ai, question):
            return context, False

        # Intentar investigacion autonoma
        try:
            from cognia_v3.core.investigador import investigar_si_necesario
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
            "total_requests":      s["total"],
            "cache_hit_rate":      round(s["cache_hits"]      / total, 3),
            "symbolic_rate":       round(s["symbolic_only"]   / total, 3),
            "hybrid_rate":         round(s["hybrid"]          / total, 3),
            "full_llm_rate":       round(s["full_llm"]        / total, 3),
            "fallback_rate":       round(s["fallbacks"]       / total, 3),
            "memory_primary_rate": round(s["memory_primary"]  / total, 3),
            "llm_avoided_pct":     round(
                (s["cache_hits"] + s["symbolic_only"]) / total * 100, 1
            ),
            "cache":               self.cache.stats(),
            "prompt_stats":        self.optimizer.get_stats(),
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


# ── ContextInjector singleton (goals + curiosity insights) ───────────────────
try:
    from cognia.context_injector import _context_injector
except Exception:
    _context_injector = None  # type: ignore[assignment]

# ── Auto-enable TCP on module load ────────────────────────────────────────────
try:
    enable_thought_cache()
except Exception:
    pass  # non-fatal — numpy or sqlite missing; TCP stays disabled

# ── PersonaManager singleton ──────────────────────────────────────────────────
_persona_manager = None
try:
    from cognia.persona.persona_manager import PersonaManager as _PersonaManager
    _persona_manager = _PersonaManager()
except Exception:
    pass  # non-fatal — persona disabled if DB not ready
