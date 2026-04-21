"""
researcher.py — Motor de investigación autónoma de Cognia.

Toma preguntas pendientes del CuriosityEngine y las intenta responder
usando el LLM local (Ollama). Produce respuestas estructuradas listas
para ser integradas al conocimiento de Cognia.

PRINCIPIO:
    Lee preguntas de curiosity_proposals (solo lectura del estado).
    Escribe respuestas de vuelta SOLO a través del knowledge_integrator,
    que controla exactamente qué y cuánto se modifica.
"""

import json
import urllib.request as _req
from dataclasses import dataclass
from typing import Optional

# ── Configuración ──────────────────────────────────────────────────────────────

OLLAMA_URL    = "http://localhost:11434/api/generate"
OLLAMA_MODEL  = "llama3.2"
TIMEOUT_SEC   = 120

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
            "system": (
                "You are a concise research assistant embedded in a cognitive AI system. "
                "Your answers fill knowledge gaps. Be precise, factual, and structured. "
                "Always follow the requested output format exactly. "
                "Respond in the same language as the question."
            ),
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

def research_question(proposal: dict) -> Optional[ResearchResult]:
    """
    Investiga una pregunta pendiente del CuriosityEngine usando Ollama.

    Args:
        proposal: dict con keys: id, question, topic, type, score, rationale

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
    raw    = _call_ollama(prompt)

    if raw is None:
        return None

    result = _parse_response(raw, proposal)

    if result:
        print(f"[researcher] ✅ Respuesta obtenida ({len(result.relations)} relaciones, "
              f"{len(result.key_concepts)} conceptos clave)")
    else:
        print(f"[researcher] ⚠️  Respuesta no parseable")

    return result
