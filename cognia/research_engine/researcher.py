"""
researcher.py — Motor de investigación autónoma de Cognia.

Toma preguntas pendientes del CuriosityEngine y las intenta responder
usando el LLM local. Produce respuestas estructuradas listas
para ser integradas al conocimiento de Cognia.

Backend (2026-07-16): el camino primario es el backend REAL — el `llm`
inyectado por el caller (run_research_session lo arma sobre el orquestador
del REPL) o, sin él, un ShatteringOrchestrator lazy propio (mismo patrón
que cognia_v3/interfaces/model_router._LOCAL_ORCH). Ollama quedó como
fallback opcional y respeta OLLAMA_URL (antes era el ÚNICO camino, con URL
hardcodeada: sin Ollama toda investigación fallaba en silencio).

PRINCIPIO:
    Lee preguntas de curiosity_proposals (solo lectura del estado).
    Escribe respuestas de vuelta SOLO a través del knowledge_integrator,
    que controla exactamente qué y cuánto se modifica.
"""

import json
import os
import urllib.request as _req
from dataclasses import dataclass
from typing import Callable, Optional

# ── Configuración ──────────────────────────────────────────────────────────────

OLLAMA_URL    = (os.environ.get("OLLAMA_URL", "http://localhost:11434")
                 .rstrip("/") + "/api/generate")
OLLAMA_MODEL  = os.environ.get("COGNIA_OLLAMA_MODEL", "llama3.2")
TIMEOUT_SEC   = 5   # short timeout — circuit breaker handles retries

# Firma del backend inyectable: (prompt, system, max_tokens, temperature) -> texto|None
LlmFn = Callable[[str, str, int, float], Optional[str]]

_LOCAL_ORCH = None  # lazy: solo si nadie inyecta un llm (tool research_llm suelta)


def _llm_local():
    """Orquestador lazy propio (backend real) para callers sin instancia.

    Higiene del instrumento (mismo patron que hybrid_router._config_effort):
    bajo pytest NO se construye el orquestador — cargaria el modelo REAL
    (cazado 2026-07-16: la suite quedo colgada cargando el 7B porque un test
    ejercitaba research_question sin mock; antes 'funcionaba' solo porque el
    unico backend era un Ollama muerto que fallaba rapido). Un test que
    quiera el camino real inyecta llm= o mockea este hook."""
    global _LOCAL_ORCH
    if os.environ.get("PYTEST_CURRENT_TEST") and _LOCAL_ORCH is None:
        return None
    try:
        if _LOCAL_ORCH is None:
            from shattering.orchestrator import ShatteringOrchestrator
            _LOCAL_ORCH = ShatteringOrchestrator(mode="local")
        return _LOCAL_ORCH
    except Exception:
        return None


_SYSTEM_RESEARCH = (
    "You are a concise research assistant embedded in a cognitive AI system. "
    "Your answers fill knowledge gaps. Be precise, factual, and structured. "
    "Always follow the requested output format exactly. "
    "Respond in the same language as the question."
)


def _call_llm(prompt: str, llm: Optional[LlmFn] = None) -> Optional[str]:
    """Backend real (inyectado u orquestador lazy) primero; Ollama al final."""
    if llm is not None:
        try:
            raw = llm(prompt, _SYSTEM_RESEARCH, 600, 0.55)
            if raw:
                return raw
        except Exception as exc:
            print(f"[researcher] backend inyectado fallo: {exc}")
    orch = _llm_local()
    if orch is not None:
        try:
            r = orch.infer(f"{_SYSTEM_RESEARCH}\n\n{prompt}",
                           max_tokens=600, temperature=0.55)
            if r is not None and getattr(r, "mode", "") != "simulation":
                text = (r.text or "").strip()
                if text:
                    return text
        except Exception as exc:
            print(f"[researcher] backend local fallo: {exc}")
    return _call_ollama(prompt)

# Confianza base que se asigna a conocimiento aprendido via investigación
# (menor que el conocimiento aprendido por observación directa)
BASE_RESEARCH_CONFIDENCE = 0.45

# Longitud mínima de respuesta para considerarla válida
MIN_ANSWER_LENGTH = 60


# ── Dataclass de resultado ─────────────────────────────────────────────────────

@dataclass
class ResearchResult:
    """Resultado de investigar una pregunta pendiente."""
    proposal_id:    int
    question:       str
    topic:          str
    question_type:  str          # isolation | bridge | contradiction | uncertainty
    answer:         str          # respuesta en lenguaje natural
    key_concepts:   list         # conceptos clave extraídos de la respuesta
    relations:      list         # lista de (sujeto, predicado, objeto) para el KG
    confidence:     float        # confianza asignada al conocimiento generado
    success:        bool


# ── Prompts por tipo de pregunta ───────────────────────────────────────────────

def _build_prompt(question: str, topic: str, question_type: str) -> str:
    """
    Construye un prompt específico según el tipo de pregunta de curiosidad.
    Cada tipo tiene un enfoque diferente en la respuesta esperada.
    """
    base_instruction = (
        f"You are the internal research module of Cognia, an AI cognitive architecture.\n"
        f"You are trying to fill a gap in your knowledge base.\n\n"
        f"Topic: {topic or question}\n"
        f"Question: {question}\n\n"
    )

    if question_type == "isolation":
        # Concepto con pocas conexiones en el KG — necesita más relaciones
        instruction = (
            "This concept exists in the knowledge base but has very few connections.\n"
            "Your goal: explain what this concept IS and how it RELATES to other concepts.\n"
            "Focus on connections, relationships, and context.\n"
        )
    elif question_type == "bridge":
        # Dos conceptos sin conexión — buscar el puente entre ellos
        instruction = (
            "These two concepts exist separately in the knowledge base with no clear connection.\n"
            "Your goal: find the relationship or bridge between them.\n"
            "Be specific about HOW they connect.\n"
        )
    elif question_type == "contradiction":
        # Contradicción entre dos episodios — intentar resolver
        instruction = (
            "There is a contradiction in the knowledge base about this topic.\n"
            "Your goal: explain why both views might coexist, or which is more accurate.\n"
            "Provide a resolution or nuanced explanation.\n"
        )
    else:  # uncertainty
        # Concepto de baja confianza — necesita más claridad
        instruction = (
            "This concept has low confidence in the knowledge base — it's poorly understood.\n"
            "Your goal: provide a clear, accurate explanation.\n"
            "Be concrete and informative.\n"
        )

    format_instruction = (
        "\nRespond in this EXACT format (no extra text):\n\n"
        "ANSWER: <2-4 sentence explanation>\n"
        "KEY_CONCEPTS: <comma-separated list of 3-6 important concepts from your answer>\n"
        "RELATIONS: <one relation per line in format: subject | predicate | object>\n"
        "CONFIDENCE: <number between 0.3 and 0.9 indicating how certain you are>\n"
    )

    return base_instruction + instruction + format_instruction


def _call_ollama(prompt: str) -> Optional[str]:
    """Llama a Ollama y retorna el texto generado, o None si falla."""
    try:
        payload = json.dumps({
            "model":   OLLAMA_MODEL,
            "prompt":  prompt,
            "system":  _SYSTEM_RESEARCH,
            "stream":  False,
            "options": {
                "temperature":  0.55,   # Más bajo que el generador — queremos hechos, no creatividad
                "num_predict":  600,
                "top_p":        0.85,
            }
        }).encode("utf-8")

        req = _req.Request(
            OLLAMA_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with _req.urlopen(req, timeout=TIMEOUT_SEC) as resp:
            data = json.loads(resp.read())
            return data.get("response", "").strip()

    except Exception as exc:
        print(f"[researcher] Ollama error: {exc}")
        return None


def _parse_response(raw: str, proposal: dict) -> Optional[ResearchResult]:
    """
    Parsea la respuesta estructurada del LLM.
    Extrae: ANSWER, KEY_CONCEPTS, RELATIONS, CONFIDENCE.
    """
    if not raw or len(raw) < MIN_ANSWER_LENGTH:
        return None

    answer       = ""
    key_concepts = []
    relations    = []
    confidence   = BASE_RESEARCH_CONFIDENCE

    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("ANSWER:"):
            answer = line[7:].strip()
        elif line.startswith("KEY_CONCEPTS:"):
            raw_concepts = line[13:].strip()
            key_concepts = [c.strip() for c in raw_concepts.split(",") if c.strip()]
        elif line.startswith("RELATIONS:"):
            pass  # La siguiente línea comienza las relaciones
        elif "|" in line and not line.startswith("CONFIDENCE"):
            # Parsear relación: sujeto | predicado | objeto
            parts = [p.strip() for p in line.split("|")]
            if len(parts) == 3 and all(parts):
                relations.append(tuple(parts))
        elif line.startswith("CONFIDENCE:"):
            try:
                val = float(line[11:].strip())
                confidence = max(0.3, min(0.9, val))
            except ValueError:
                confidence = BASE_RESEARCH_CONFIDENCE

    if not answer or len(answer) < 20:
        return None

    return ResearchResult(
        proposal_id=   proposal["id"],
        question=      proposal["question"],
        topic=         proposal.get("topic", ""),
        question_type= proposal.get("type", "uncertainty"),
        answer=        answer,
        key_concepts=  key_concepts[:6],
        relations=     relations[:8],   # Máximo 8 relaciones por investigación
        confidence=    confidence,
        success=       True,
    )


# ── API pública ────────────────────────────────────────────────────────────────

def research_question(proposal: dict,
                      llm: Optional[LlmFn] = None) -> Optional[ResearchResult]:
    """
    Investiga una pregunta pendiente del CuriosityEngine con el LLM local.

    Args:
        proposal: dict con keys: id, question, topic, type, score, rationale
        llm:      backend real inyectado por el caller (opcional); sin él se
                  usa el orquestador lazy local y Ollama como último fallback.

    Returns:
        ResearchResult con la respuesta y conocimiento estructurado,
        o None si la investigación falló.
    """
    question      = proposal.get("question", "")
    topic         = proposal.get("topic", "")
    question_type = proposal.get("type", "uncertainty")

    if not question:
        return None

    print(f"[researcher] 🔍 Investigando: '{question[:60]}...'")

    prompt = _build_prompt(question, topic, question_type)
    raw    = _call_llm(prompt, llm=llm)

    if raw is None:
        print("[researcher] ⚠️  Sin backend LLM vivo (orquestador/Ollama). "
              "Instala el modelo con 'cognia install-model'.")
        return None

    result = _parse_response(raw, proposal)

    if result:
        print(f"[researcher] ✅ Respuesta obtenida ({len(result.relations)} relaciones, "
              f"{len(result.key_concepts)} conceptos clave)")
    else:
        print(f"[researcher] ⚠️  Respuesta no parseable")

    return result
