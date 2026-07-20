"""
cognia/agents/workers/research_worker.py — Phase 24

Wrapper sobre investigador.py con cache episódico.
Prioridad: cache episódico → Wikipedia → research_llm (LLM, último recurso).

0 LLM calls en ~70% de casos (cache hit o Wikipedia suficiente).
"""

from __future__ import annotations

from typing import Optional

# Similitud mínima para considerar que la memoria episódica ya tiene la respuesta
_EPISODIC_HIT_THRESHOLD = 0.75


def research(
    query: str,
    episodic_memory=None,
    vector_cache=None,
) -> dict:
    """
    Investiga un tema con fallback progresivo.

    Retorna:
        {"source": "episodic"|"wikipedia"|"llm"|"none", "content": str, "found": bool}
    """
    # 1. Cache episódico (0 red, 0 LLM)
    if episodic_memory is not None and vector_cache is not None:
        hit = _search_episodic(query, episodic_memory, vector_cache)
        if hit:
            return {"source": "episodic", "content": hit, "found": True}

    # 2. Wikipedia (red, 0 LLM)
    wiki = _search_wikipedia(query)
    if wiki:
        return {"source": "wikipedia", "content": wiki, "found": True}

    # 3. LLM local (último recurso)
    llm = _research_llm(query)
    if llm:
        return {"source": "llm", "content": llm, "found": True}

    return {"source": "none", "content": "", "found": False}


def _search_episodic(query: str, episodic_memory, vector_cache) -> Optional[str]:
    try:
        from cognia.cognia_embedding import text_to_vector_fast
        emb = text_to_vector_fast(query)
        results = vector_cache.search(emb, top_k=1)
        if not results:
            return None
        r = results[0]
        sim = getattr(r, "similarity", 0.0)
        if sim < _EPISODIC_HIT_THRESHOLD:
            return None
        obs = getattr(r, "observation", None) or str(r)
        return obs[:1000]
    except Exception:
        return None


def _search_wikipedia(query: str) -> Optional[str]:
    try:
        from cognia_v3.core.investigador import buscar_wikipedia
        result = buscar_wikipedia(query)
        if result is None:
            return None
        extract = result.get("extract", "")
        title   = result.get("title", "")
        if not extract:
            return None
        return f"{title}: {extract}"[:1500]
    except Exception:
        return None


def _research_llm(query: str) -> Optional[str]:
    try:
        from cognia.research_engine.researcher import research_question
        proposal = {
            "id": 0,
            "question": query,
            "topic": query,
            "question_type": "uncertainty",
        }
        result = research_question(proposal)
        if result is None or not result.success:
            return None
        return result.answer[:1500]
    except Exception:
        return None
