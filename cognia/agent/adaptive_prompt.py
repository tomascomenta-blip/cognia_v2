"""
cognia/agent/adaptive_prompt.py
==============================
Self-tuning system prompt: Cognia learns a few traits about the user across
sessions and folds them into the system prompt, so answers adapt over time.

Deliberately heuristic and concrete (no ML, no embeddings): plain regex + word
counts. Learned traits persist in the user_profile table, so they carry across
restarts -- "afinarse conforme las sesiones".

Two entry points:
  learn_user_traits(ai, user_text)        -- call after each user message
  build_adaptive_system_prompt(ai)        -- call before generating a reply
"""

from __future__ import annotations

import re

from shattering.model_constants import COGNIA_SYSTEM_PROMPT

# Profile keys we manage (namespaced so we never collide with other code).
_K_NAME = "adapt_nombre"
_K_LANG = "adapt_idioma"
_K_VERBOSITY = "adapt_verbosidad"

_ES_HINTS = {"que", "como", "por", "para", "hola", "gracias", "el", "la", "de",
             "y", "pero", "porque", "donde", "cuando", "esto", "eso", "mi", "tu"}
_EN_HINTS = {"the", "what", "how", "you", "is", "and", "but", "because", "where",
             "when", "this", "that", "my", "your", "please", "thanks"}

_NAME_RE = re.compile(
    r"\b(?:me llamo|mi nombre es|soy)\s+([A-Za-zÁÉÍÓÚáéíóúÑñ]{2,20})", re.IGNORECASE
)
_SHORTER = ("se mas breve", "mas corto", "resumido", "se breve", "menos texto",
            "no te extiendas", "respuestas cortas", "be brief", "shorter")
_LONGER = ("explica mas", "mas detalle", "mas detallado", "extiende", "profundiza",
           "respuestas largas", "more detail", "explain more")


def _detect_language(text: str) -> str | None:
    words = re.findall(r"[a-zA-ZáéíóúñÁÉÍÓÚÑ]+", text.lower())
    if len(words) < 3:
        return None
    es = sum(1 for w in words if w in _ES_HINTS)
    en = sum(1 for w in words if w in _EN_HINTS)
    if es == en == 0:
        return None
    return "espanol" if es >= en else "ingles"


def learn_user_traits(ai, user_text: str) -> None:
    """
    Update the persisted user profile from one user message. Best-effort: a DB
    hiccup or a missing profile must never break the chat loop.
    """
    prof = getattr(ai, "user_profile", None)
    if prof is None or not user_text:
        return
    text = user_text.strip()
    low = text.lower()
    try:
        # Name: "me llamo X" / "soy X" / "mi nombre es X"
        m = _NAME_RE.search(text)
        if m:
            name = m.group(1).strip().capitalize()
            # Avoid capturing "soy programador" style false positives loosely:
            if name.lower() not in ("un", "una", "el", "la", "muy", "programador"):
                prof.set(_K_NAME, name)

        # Verbosity preference (explicit user requests only).
        if any(h in low for h in _SHORTER):
            prof.set(_K_VERBOSITY, "breve")
        elif any(h in low for h in _LONGER):
            prof.set(_K_VERBOSITY, "detallada")

        # Preferred language (only overwrite on a confident read).
        lang = _detect_language(text)
        if lang:
            prof.set(_K_LANG, lang)
    except Exception:
        pass


def _frequent_topics(ai, limit: int = 3) -> list:
    try:
        rows = ai.chat_history.get_frequent_topics(top_k=limit)
        return [r["label"] for r in rows if r.get("label")]
    except Exception:
        return []


def build_adaptive_system_prompt(ai) -> str:
    """
    The canonical system prompt plus a short, learned preamble about THIS user.
    Falls back to the plain canonical prompt if nothing has been learned yet.
    """
    prof = getattr(ai, "user_profile", None)
    if prof is None:
        return COGNIA_SYSTEM_PROMPT

    parts = []
    try:
        name = prof.get(_K_NAME)
        if name:
            parts.append(f"El usuario se llama {name}; dirigite a el por su nombre cuando sea natural.")

        lang = prof.get(_K_LANG)
        if lang == "ingles":
            parts.append("El usuario suele escribir en ingles; respondele en ingles.")
        elif lang == "espanol":
            parts.append("El usuario escribe en espanol; respondele en espanol.")

        verbosity = prof.get(_K_VERBOSITY)
        if verbosity == "breve":
            parts.append("Prefiere respuestas breves y directas, sin relleno.")
        elif verbosity == "detallada":
            parts.append("Prefiere respuestas detalladas y con ejemplos.")

        topics = _frequent_topics(ai)
        if topics:
            parts.append("Temas frecuentes del usuario: " + ", ".join(topics) + ".")
    except Exception:
        return COGNIA_SYSTEM_PROMPT

    # Capability evolution: reflect tools Cognia synthesized for itself, so its
    # self-description grows as it gains skills (independent of user traits).
    cap_note = ""
    try:
        from cognia.agent.tool_synthesis import synthesized_capabilities_note
        cap_note = synthesized_capabilities_note()
    except Exception:
        cap_note = ""

    if not parts and not cap_note:
        return COGNIA_SYSTEM_PROMPT

    prompt = COGNIA_SYSTEM_PROMPT
    if parts:
        prompt += "\n\nSobre el usuario (aprendido en sesiones previas):\n- " + "\n- ".join(parts)
    if cap_note:
        prompt += "\n\n" + cap_note
    return prompt
