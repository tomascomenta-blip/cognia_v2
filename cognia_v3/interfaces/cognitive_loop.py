"""
CognitiveLoop — Central orchestrator for Cognia v3.
Routes each query through the correct processing pipeline.

Modes:
  FAST        → LLM directly (simple/conversational queries)
  RECALL      → KG + EpisodicMemory → inject context → LLM
  DELIBERATE  → KG + InferenceEngine (multi-hop) → LLM
  ACT         → Task decomposition → LLM synthesis

Adaptado a las APIs reales de cognia_v3.core.cognia_v3:
  KnowledgeGraph.get_facts(concept) -> [{"subject","predicate","object","weight"}]
  EpisodicMemory.retrieve_similar(query_vector, top_k) -> [{"observation",...}]
  InferenceEngine.infer(concept) -> [dict]
  LanguageEngine.respond(cognia_instance, question) -> EngineResult(.response)

Usage:
    loop = CognitiveLoop(kg, llm, episodic_memory=mem, inference_engine=inf, cognia=ai)
    response = loop.process("Why does rain cause floods?")
    print(response.answer)
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal, Any, Callable, Optional
import logging
import re

logger = logging.getLogger(__name__)

QueryMode = Literal["FAST", "RECALL", "DELIBERATE", "ACT"]

# Palabras función que no sirven como concepto de KG
_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "what", "who", "how", "why", "do",
    "does", "did", "of", "in", "on", "to", "and", "or", "que", "qué", "como",
    "cómo", "por", "para", "los", "las", "una", "uno", "del", "con", "sobre",
    "es", "son", "el", "la", "de", "un", "se", "me", "te", "mi", "tu", "y", "o",
}


@dataclass
class CogniaResponse:
    mode_used: QueryMode
    answer: str
    context_used: list[str] = field(default_factory=list)
    reasoning_steps: list[str] = field(default_factory=list)
    confidence: float = 0.7


class CognitiveLoop:
    """
    Central orchestrator. Reemplaza el ruteo binario de decision_gate.py
    por cuatro pipelines explícitos.
    """

    # Señales de ruteo por keyword (extender con términos del dominio)
    _RECALL = ["remember", "recall", "what did", "last time", "previously",
               "recuerda", "recordas", "último", "antes", "mencioné", "dijiste",
               "what do i know", "qué sé", "que se yo"]
    _DELIBERATE = ["why", "how does", "explain", "analyze", "compare", "reason",
                   "step by step", "por qué", "porqué", "cómo funciona", "explica",
                   "razona", "analiza", "diferencia", "paso a paso"]
    _ACT = ["write", "create", "build", "implement", "generate", "run", "execute",
            "escribe", "escribí", "crea", "creá", "implementa", "genera",
            "construye", "haz", "hacé", "programa"]

    def __init__(self, kg: Any, language_engine: Any,
                 episodic_memory: Any = None, inference_engine: Any = None,
                 cognia: Any = None, vectorize: Optional[Callable[[str], list]] = None):
        self.kg = kg
        self.lang = language_engine
        self.memory = episodic_memory
        self.inference = inference_engine
        self.cognia = cognia          # instancia Cognia (LanguageEngine.respond la pide)
        self._vectorize = vectorize   # texto -> vector, para retrieve_similar
        self._kg_concepts_cache: Optional[list[str]] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process(self, query: str) -> CogniaResponse:
        """Main entry point. Classify and route the query."""
        mode = self._classify(query)
        logger.info("CognitiveLoop [%s] -> %s", mode, query[:60])

        dispatch = {
            "FAST": self._fast,
            "RECALL": self._recall,
            "DELIBERATE": self._deliberate,
            "ACT": self._act,
        }
        return dispatch[mode](query)

    def classify(self, query: str) -> QueryMode:
        """Clasificación pública — útil para tests y logging."""
        return self._classify(query)

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    def _classify(self, query: str) -> QueryMode:
        q = query.lower()
        if any(s in q for s in self._ACT):
            return "ACT"
        if any(s in q for s in self._DELIBERATE):
            return "DELIBERATE"
        if any(s in q for s in self._RECALL):
            return "RECALL"
        if self._query_concepts(q):
            return "RECALL"
        return "FAST"

    def _kg_concepts(self) -> list[str]:
        """Conceptos conocidos del KG (cacheados). Usa el grafo networkx interno."""
        if self._kg_concepts_cache is None:
            try:
                g = self.kg._get_graph() if hasattr(self.kg, "_get_graph") else None
                self._kg_concepts_cache = [str(n) for n in g.nodes][:500] if g is not None else []
            except Exception:
                self._kg_concepts_cache = []
        return self._kg_concepts_cache

    def _query_concepts(self, query_lower: str) -> list[str]:
        """Conceptos del KG mencionados en la query (palabras > 2 chars, sin stopwords)."""
        words = {w for w in re.findall(r"[\wáéíóúñü]+", query_lower)
                 if len(w) > 2 and w not in _STOPWORDS}
        return [c for c in self._kg_concepts()
                if c.lower() in words or any(w in c.lower() for w in words if len(w) > 3)][:5]

    # ------------------------------------------------------------------
    # LLM bridge
    # ------------------------------------------------------------------

    def _call_llm(self, prompt: str) -> str:
        """
        Adapter sobre el motor de lenguaje disponible:
          - callable plano: fn(prompt) -> str
          - LanguageEngine del repo: .respond(cognia, prompt) -> EngineResult(.response)
          - genéricos: .generate / .query / .chat / .ask
        """
        if callable(self.lang) and not hasattr(self.lang, "respond"):
            return str(self.lang(prompt))
        if hasattr(self.lang, "respond"):
            result = self.lang.respond(self.cognia, prompt)
            return getattr(result, "response", str(result))
        for method in ("generate", "query", "chat", "ask"):
            if hasattr(self.lang, method):
                return str(getattr(self.lang, method)(prompt))
        raise AttributeError("language_engine no expone respond/generate/query/chat/ask ni es callable")

    # ------------------------------------------------------------------
    # Pipelines
    # ------------------------------------------------------------------

    def _fast(self, query: str) -> CogniaResponse:
        answer = self._call_llm(query)
        return CogniaResponse(mode_used="FAST", answer=answer, confidence=0.7)

    def _gather_context(self, query: str) -> list[str]:
        context_parts: list[str] = []

        # 1. KG: hechos de los conceptos mencionados
        try:
            for concept in self._query_concepts(query.lower()):
                for f in (self.kg.get_facts(concept) or [])[:4]:
                    s, p, o = f.get("subject", ""), f.get("predicate", ""), f.get("object", "")
                    if s and o:
                        context_parts.append(f"{s} {p} {o}")
        except Exception as e:
            logger.warning("KG lookup failed: %s", e)

        # 2. Memoria episódica por similitud vectorial
        if self.memory is not None and self._vectorize is not None:
            try:
                vec = self._vectorize(query)
                for ep in (self.memory.retrieve_similar(vec, top_k=3) or []):
                    text = str(ep.get("observation", "")).strip()
                    if text:
                        context_parts.append(text[:150])
            except Exception as e:
                logger.warning("Memory retrieve failed: %s", e)

        # dedup preservando orden
        seen = set()
        return [c for c in context_parts if not (c in seen or seen.add(c))]

    def _recall(self, query: str) -> CogniaResponse:
        context_parts = self._gather_context(query)
        if context_parts:
            joined = "\n".join(f"- {c}" for c in context_parts)
            augmented = f"Context (use this to answer):\n{joined}\n\nQuestion: {query}"
        else:
            augmented = query
        answer = self._call_llm(augmented)
        return CogniaResponse(mode_used="RECALL", answer=answer,
                              context_used=context_parts, confidence=0.8)

    def _deliberate(self, query: str) -> CogniaResponse:
        context = self._gather_context(query)
        inferences: list[str] = []

        if self.inference is not None:
            try:
                for concept in self._query_concepts(query.lower())[:2]:
                    for inf in (self.inference.infer(concept) or [])[:2]:
                        inferences.append(str(inf))
            except Exception as e:
                logger.warning("Inference failed: %s", e)

        full_context = context + inferences
        if full_context:
            joined = "\n".join(f"- {c}" for c in full_context)
            augmented = (f"Facts and inferences:\n{joined}\n\n"
                         f"Analyze and explain step by step: {query}")
        else:
            augmented = f"Think step by step and explain: {query}"

        answer = self._call_llm(augmented)
        return CogniaResponse(mode_used="DELIBERATE", answer=answer,
                              context_used=full_context,
                              reasoning_steps=inferences, confidence=0.85)

    def _act(self, query: str) -> CogniaResponse:
        steps_raw = self._call_llm(f"Break into 3 numbered steps: {query}")
        final = self._call_llm(f"Execute step by step:\n{steps_raw}\n\nTask: {query}")
        return CogniaResponse(mode_used="ACT", answer=final,
                              reasoning_steps=[steps_raw], confidence=0.65)
