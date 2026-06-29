"""
gap_filler.py
=============
Context Map Cycle 4 (gap-filling): when a query finds no good coverage in the
index, index the part of the corpus that is NOT indexed yet and retry once.
Lazy indexing on demand.

Coordinator only: imports ingest and context_map; neither imports this module,
so there is no import cycle. See cognia/context/CONTEXT_MAP_DESIGN.md.
"""

from pathlib import Path

from cognia.ingest import _chunk_text_with_offsets


def index_source_range(cm, ai, source_ref, project, start=0):
    """Index the [start:] range of a text file: write 'file' pointers (absolute
    offsets over the file, LOSSLESS) and update coverage to the full length.
    Returns the number of pointers added. Best-effort: if the file cannot be
    read, returns 0 without raising."""
    try:
        full = Path(source_ref).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    tail = full[start:]
    spans = _chunk_text_with_offsets(tail)
    n = 0
    for (chunk_text, s, e) in spans:
        vec = ai.perception.extract_features(chunk_text)["vector"]
        summary = chunk_text[:120].replace("\n", " ").strip()
        cm.add_pointer("file", source_ref, char_start=start + s, char_end=start + e,
                       vector=vec, label=project, summary=summary)
        n += 1
    try:
        mtime = Path(source_ref).stat().st_mtime
    except OSError:
        mtime = 0.0
    cm.mark_coverage(source_ref, indexed_through=len(full), total_chars=len(full),
                     mtime=mtime)
    return n


def fill_gaps(cm, ai, project=None, max_sources=10):
    """Index the gaps (uncovered tails) of the project's known sources.
    Returns the total number of pointers added."""
    proj = project if project is not None else cm.project
    gaps = cm.uncovered_sources(proj)[:max_sources]
    total = 0
    for (source_ref, indexed_through, total_chars) in gaps:
        total += index_source_range(cm, ai, source_ref, proj, start=indexed_through or 0)
    return total


def fill_gaps_ondisk(cm, ai, project=None, max_sources=50):
    """Detecta huecos por el TAMANO ACTUAL del archivo en disco (no por coverage
    almacenado): para cada fuente conocida, si el archivo on-disk es mas largo que
    indexed_through, indexa la cola [indexed_through:]. Devuelve total de punteros
    agregados. Solo aplica a fuentes que son archivos legibles (las 'text'/inline se saltan)."""
    proj = project if project is not None else cm.project
    total = 0
    for (source_ref, indexed_through, total_chars) in cm.all_coverage(proj)[:max_sources]:
        try:
            cur_len = len(Path(source_ref).read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue  # no es archivo legible (p.ej. fuente 'msg' o borrada)
        if cur_len > (indexed_through or 0):
            total += index_source_range(cm, ai, source_ref, proj, start=indexed_through or 0)
    return total


def query_with_gap_fill(cm, ai, query_text, embed_fn, budget_tokens=4000,
                        top_k=50, min_score=0.5):
    """Query the index; if the best score < min_score (nothing good found),
    fill the known gaps and retry ONCE. Returns the query() result list."""
    res = cm.query_text(query_text, embed_fn, budget_tokens=budget_tokens, top_k=top_k)
    top = res[0]["score"] if res else -1.0
    if top >= min_score:
        return res
    fill_gaps(cm, ai, cm.project)
    return cm.query_text(query_text, embed_fn, budget_tokens=budget_tokens, top_k=top_k)
