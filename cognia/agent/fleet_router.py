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
    re.compile(r"\bque\s+asistente\b"),
    re.compile(r"\bpresentar(te|me\s+a)\b"),
    re.compile(r"\bfuiste\s+(desarrollad|cread|entrenad|program|hech)"),
    re.compile(r"\b(con\s+)?que\s+(ia|modelo|inteligencia)\b.{0,40}\b(hablando|hablo|sos|eres|estoy)\b"),
    re.compile(r"\bwho\s+(are|made|created|trained)\s+you\b"),
    re.compile(r"\bwhat('?s|\s+is)\s+your\s+name\b"),
    re.compile(r"\byour\s+name\b"),
    re.compile(r"\bwhat\s+are\s+you\b"),
    re.compile(r"\bwhat\s+you\s+are\b"),
    re.compile(r"\b(what|which)\s+ai\b"),
    re.compile(r"\bintroduce\s+yourself\b"),
    re.compile(r"\bare\s+you\s+(chatgpt|gemini|gpt|claude|qwen|cognia|an?\s+ai|a\s+robot|human)\b"),
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


def member_for_chat_turn(text: str, razonador_ok: bool = True) -> Optional[str]:
    """Miembro del FLEET-30 (fleet_registry) para el turno, o None = 3B.

    Ruteo por eje MEDIDO (AUDIT_COLONIA 2026-07-12, suites congeladas):
    turnos de RAZONAMIENTO (mismo detector regex que dispara stepwise) van
    al qwen3_4b CRUDO — G2R 92.5% vs 82 del 3B+stepwise y 27.5 del 3B
    crudo. El 4B va SIN stepwise (medido crudo; sobre-instruir degrada).
    Kill-switch: COGNIA_RAZONA_4B=0. Si el miembro no arranca, el caller
    cae al 3B+stepwise (fallback total, nunca peor que hoy).
    razonador_ok: permiso del perfil hibrido (False a /esfuerzo bajo =
    no despertar el 4B; el turno queda en el 3B+stepwise)."""
    import os
    if not razonador_ok:
        return None
    if os.environ.get("COGNIA_RAZONA_4B", "").strip().lower() in (
            "0", "off", "false", "no"):
        return None
    from cognia.agent.stepwise import needs_stepwise
    return "qwen3_4b" if needs_stepwise(text) else None
