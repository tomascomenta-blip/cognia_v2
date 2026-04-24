"""
app/routes/chat.py
==================
Endpoint POST /api/chat con fallback simbolico cuando Ollama no esta disponible.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

_cognia = None

def get_cognia():
    global _cognia
    if _cognia is None:
        from cognia.cognia import Cognia
        _cognia = Cognia()
    return _cognia


class ChatRequest(BaseModel):
    input: str

class ChatResponse(BaseModel):
    response: str
    stage: str = ""
    error: str = ""


def _respuesta_sin_ollama(ai, pregunta: str) -> dict:
    """
    Respuesta usando solo memoria interna de Cognia, sin LLM.
    Fuerza al LanguageEngine a usar Stage 2 (simbolico) o Stage 5 (fallback)
    apuntando Ollama a un puerto cerrado para que falle rapido.
    """
    try:
        from language_engine import get_language_engine
        engine = get_language_engine(ai)
        original_url = engine.ollama_url
        engine.ollama_url = "http://127.0.0.1:1"
        try:
            result = engine.respond(cognia_instance=ai, question=pregunta)
            return {"response": result.response, "stage": result.stage_used}
        finally:
            engine.ollama_url = original_url
    except Exception:
        try:
            resp = ai.process(pregunta)
            return {"response": resp or "Mensaje recibido.", "stage": "process"}
        except Exception:
            return {
                "response": (
                    "Cognia recibio tu mensaje. "
                    "El modelo de lenguaje (Ollama) no esta disponible en este servidor. "
                    "Puedes usar comandos como 'yo', 'conceptos', 'dormir' para interactuar "
                    "con la memoria interna de Cognia."
                ),
                "stage": "no_llm",
            }


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    if not req.input.strip():
        return ChatResponse(response="", error="Mensaje vacio.")
    try:
        ai = get_cognia()
        try:
            from respuestas_articuladas import responder_articulado
            resultado = responder_articulado(ai, req.input.strip())
        except Exception as e:
            resultado = {"error": str(e)}

        if "error" in resultado:
            err = str(resultado["error"])
            ollama_error = any(x in err.lower() for x in [
                "ollama", "connection refused", "urlerror", "urlopen", "errno 111"
            ])
            if ollama_error:
                fallback = _respuesta_sin_ollama(ai, req.input.strip())
                return ChatResponse(
                    response=fallback["response"],
                    stage=fallback.get("stage", "fallback"),
                )
            return ChatResponse(response="", error=err)

        stage = (
            resultado.get("stage")
            or resultado.get("language_engine", {}).get("stage", "")
        )
        return ChatResponse(
            response=resultado.get("response", ""),
            stage=stage,
        )
    except Exception as e:
        return ChatResponse(response="", error=str(e))
