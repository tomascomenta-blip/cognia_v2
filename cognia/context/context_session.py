"""
context_session.py
===================
Context Map Cycle 5: build the context memory as a conversation advances.

A chat message is recorded as a 'msg' pointer into chat_history (by id), never
duplicating its text. The pointer is embedded so it ranks in ContextMap.query,
and a short summary is kept for the human-readable index (cognia_context.md).
"""

from cognia.context.context_map import ContextMap  # noqa: F401  (import contract)


def record_message(cm, ai, msg_id, content, project=None):
    """Registra un mensaje de la conversacion como puntero 'msg' (apunta a
    chat_history.id, no duplica el texto). Embebe el contenido para que sea
    rankeable. Devuelve el id del puntero, o None si falla (best-effort)."""
    try:
        vec = ai.perception.extract_features(content)["vector"]
        summary = content[:120].replace("\n", " ").strip()
        proj = project if project is not None else cm.project
        return cm.add_pointer("msg", str(msg_id), vector=vec, label=proj, summary=summary)
    except Exception:
        return None
