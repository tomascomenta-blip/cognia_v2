"""
app/routes/chat.py
==================
Endpoint POST /api/chat
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

# Instancia global (se inicializa una sola vez al arrancar)
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


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    if not req.input.strip():
        return ChatResponse(response="", error="Mensaje vacío.")
    try:
        ai = get_cognia()
        from respuestas_articuladas import responder_articulado
        resultado = responder_articulado(ai, req.input.strip())
        if "error" in resultado:
            return ChatResponse(response="", error=str(resultado["error"]))
        return ChatResponse(
            response=resultado.get("response", ""),
            stage=resultado.get("stage", ""),
        )
    except Exception as e:
        return ChatResponse(response="", error=str(e))
