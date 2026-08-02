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
from cognia.context.gap_filler import query_with_gap_fill


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
    Devuelve la lista de query_hybrid ({id,score,text,...}).

    El patron consultar->rellenar->reintentar vive en gap_filler.query_with_gap_fill
    (hybrid+ondisk); aqui solo se arma el ContextMap y el embedder."""
    cm = ContextMap(db_path=getattr(ai, "db", None), project=project)
    embed = _embed_fn(ai)
    if gap_fill:
        return query_with_gap_fill(cm, ai, query, embed, budget_tokens=budget_tokens,
                                   top_k=top_k, min_score=min_score,
                                   hybrid=True, ondisk=True)
    return cm.query_text_hybrid(query, embed, budget_tokens=budget_tokens, top_k=top_k)


def list_projects(ai):
    """Lista los projects distintos presentes en el context map."""
    cm = ContextMap(db_path=getattr(ai, "db", None))
    return cm.list_projects()


def retrieve_all(ai, query, budget_tokens=4000, top_k=50):
    """Recupera spans relevantes ACROSS todos los projects del context map
    (hibrido por project, merge por score). Devuelve lista
    [{id,score,text,source_ref,project}]."""
    results = []
    for p in list_projects(ai):
        cm = ContextMap(db_path=getattr(ai, "db", None), project=p)
        for r in cm.query_text_hybrid(query, _embed_fn(ai), budget_tokens=budget_tokens, top_k=top_k):
            r = dict(r)
            r["project"] = p
            results.append(r)
    results.sort(key=lambda r: r["score"], reverse=True)
    # empaquetar hasta budget (~4 chars/token) sobre el merge global
    out, used = [], 0
    for r in results:
        est = max(1, len(r.get("text") or "") // 4)
        if used + est > budget_tokens:
            break
        out.append(r)
        used += est
    return out


def refresh_map(ai, project="default", out_path=None):
    """Regenera el archivo de contexto legible (cognia_context.md). Devuelve la ruta."""
    cm = ContextMap(db_path=getattr(ai, "db", None), project=project)
    if out_path is None:
        import os
        out_path = os.path.join(os.getcwd(), "cognia_context.md")
    return cm.write_markdown(out_path, project=project)


def stats(ai, project="default"):
    return ContextMap(db_path=getattr(ai, "db", None), project=project).stats()


def record_conversation(ai, user_text, assistant_text, project="conversacion",
                        user_msg_id=None, assistant_msg_id=None):
    """Guarda el turno (user + assistant) como punteros rankeables.
    Si el caller pasa el id de chat_history del mensaje (user_msg_id /
    assistant_msg_id), delega en record_message: puntero 'msg' que apunta a la
    fila existente SIN duplicar el texto (lossless). Sin id, guarda un puntero
    'text' inline (comportamiento historico).
    Best-effort: try/except -> 0; nunca levanta. Devuelve cuantos punteros agrego."""
    n = 0
    try:
        cm = ContextMap(db_path=getattr(ai, "db", None), project=project)
        embed = _embed_fn(ai)
        for role, txt, mid in (("user", user_text, user_msg_id),
                               ("assistant", assistant_text, assistant_msg_id)):
            if not txt or not txt.strip():
                continue
            if mid is not None:
                if record_message(cm, ai, mid, txt, project=project) is not None:
                    n += 1
                continue
            vec = embed(txt)
            cm.add_pointer("text", "", inline_text=txt, vector=vec,
                           label=project, summary=(role + ": " + txt[:100]).replace("\n", " "))
            n += 1
    except Exception:
        pass
    return n
