"""
context_engine.py
=================
Context Map Cycle 7: public high-level facade over the context engine, for the
CLI. Wraps ContextMap + record_message + on-disk gap-filling so callers do not
have to wire embeddings, projects and retries by hand.

retrieve() does the organic gap-fill the owner asked for: if the best score is
weak, it indexes the NEW tail of every known source on disk (files that grew or
were never fully indexed) and retries once. See cognia/context/CONTEXT_MAP_DESIGN.md.
"""

from cognia.context.context_map import ContextMap
from cognia.context.context_session import record_message
from cognia.context.gap_filler import fill_gaps_ondisk


def _embed_fn(ai):
    return lambda t: ai.perception.extract_features(t)["vector"]


def record_turn(ai, role, content, msg_id, project="default"):
    """Registra un mensaje de la conversacion como puntero. No-op si content vacio.
    Devuelve el id del puntero o None."""
    if not content or not content.strip():
        return None
    cm = ContextMap(db_path=getattr(ai, "db", None), project=project)
    return record_message(cm, ai, msg_id, content, project=project)


def retrieve(ai, query, project="default", budget_tokens=4000, top_k=50,
             min_score=0.25, gap_fill=True):
    """Recupera spans relevantes (hibrido BM25+vector). Si el mejor score < min_score
    y gap_fill, indexa huecos on-disk de las fuentes conocidas y reintenta UNA vez.
    Devuelve la lista de query_hybrid ({id,score,text,...})."""
    cm = ContextMap(db_path=getattr(ai, "db", None), project=project)
    embed = _embed_fn(ai)
    res = cm.query_text_hybrid(query, embed, budget_tokens=budget_tokens, top_k=top_k)
    top = res[0]["score"] if res else -1.0
    if gap_fill and top < min_score:
        fill_gaps_ondisk(cm, ai, project)
        res = cm.query_text_hybrid(query, embed, budget_tokens=budget_tokens, top_k=top_k)
    return res


def refresh_map(ai, project="default", out_path=None):
    """Regenera el archivo de contexto legible (cognia_context.md). Devuelve la ruta."""
    cm = ContextMap(db_path=getattr(ai, "db", None), project=project)
    if out_path is None:
        import os
        out_path = os.path.join(os.getcwd(), "cognia_context.md")
    return cm.write_markdown(out_path, project=project)


def stats(ai, project="default"):
    return ContextMap(db_path=getattr(ai, "db", None), project=project).stats()
