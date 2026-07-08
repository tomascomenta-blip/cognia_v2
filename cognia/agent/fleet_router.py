# -*- coding: utf-8 -*-
"""Router del fleet de expertos LoRA (FLEET_DESIGN, 2026-07-08).

Reglas LEXICAS deterministas — NO matching semantico difuso: la leccion medida
de skills (umbral 0.35 matcheaba cualquier cosa en espanol; re-calibrado 0.48
y aun con residuo) aplica 1:1 aca. Default = None (base pura): la base ya pasa
G1/G5 por construccion, el fleet nunca rinde menos que la base.

Expertos hoy (adapters.json junto al GGUF):
  accion  — tool-calling formato ACCION + identidad Cognia (cognia3b_v1:
            G2A 95.2% y G3 20/20 medidos en el deploy real; G1 regresiona
            -8pp, por eso NUNCA se activa para chat general).

Quien lo usa:
  - _run_agent_task (cli.py): experto "accion" para toda la tarea de agente.
  - fast-path de chat (cli.py): expert_for_chat_turn() por turno.
  - /largo (_resolve_largo_backend): siempre base (None).
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional


def _fold(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", t.lower())
                   if not unicodedata.combining(c))


# Identidad: preguntas sobre quien/que es el asistente, su nombre, su origen.
# El experto accion (cognia3b_v1) contesta como Cognia (G3 20/20); la base
# contesta como Qwen (G3 0/20). Patrones sobre texto folded (sin tildes).
_IDENTITY_RES = [
    re.compile(r"\bquien\s+(sos|eres|te\s+(creo|hizo|entreno|programo|desarrollo))\b"),
    re.compile(r"\bque\s+(sos|eres)\b"),
    re.compile(r"\bcomo\s+te\s+llam"),
    re.compile(r"\b(cual\s+es\s+)?tu\s+nombre\b"),
    re.compile(r"\bquien\s+es\s+cognia\b"),
    re.compile(r"\b(sos|eres)\s+(cognia|chatgpt|gpt|qwen|una?\s+ia|un\s+robot|humano)\b"),
    re.compile(r"\bhablame\s+(de|sobre)\s+(ti|vos)\b"),
    re.compile(r"\bpresenta(te|te\s+vos)\b"),
    re.compile(r"\bwho\s+(are|made|created|trained)\s+you\b"),
    re.compile(r"\bwhat('?s|\s+is)\s+your\s+name\b"),
    re.compile(r"\bwhat\s+are\s+you\b"),
]


def is_identity_turn(text: str) -> bool:
    """True si el turno pregunta por la identidad del asistente."""
    folded = _fold(text or "")
    return any(rx.search(folded) for rx in _IDENTITY_RES)


def expert_for_chat_turn(text: str) -> Optional[str]:
    """Experto del fleet para un turno de CHAT (no agente), o None = base.

    Solo identidad va al experto: el chat general queda en la base porque el
    adapter regresiona G1 (medido -8pp). Las tareas de agente no pasan por
    aca (el loop activa "accion" directo).
    """
    return "accion" if is_identity_turn(text) else None
