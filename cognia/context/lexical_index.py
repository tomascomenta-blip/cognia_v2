"""
lexical_index.py
================
Context Map Cycle 6: pure-Python BM25 lexical scoring, no external deps and no
persistent state. Used to re-rank vector candidates by exact lexical match so a
literal phrase ("la clave secreta del despliegue es X") is not diluted away by a
large chunk's averaged embedding. See cognia/context/context_map.query_hybrid.
"""

import re
import math
from collections import Counter

_TOKEN = re.compile(r"[a-z0-9_]+")


def _tokenize(text):
    return _TOKEN.findall((text or "").lower())


def bm25_scores(query, docs, k1=1.5, b=0.75):
    """Score each doc in `docs` (list of strings) by standard BM25 over the terms
    of `query`. idf with smoothing, tf saturated by k1, length-normalized by b.
    Returns a list of floats in the same order as docs; empty docs -> []."""
    N = len(docs)
    if N == 0:
        return []
    doc_tokens = [_tokenize(d) for d in docs]
    doc_lens = [len(t) for t in doc_tokens]
    avgdl = sum(doc_lens) / N
    if avgdl < 1.0:
        avgdl = 1.0
    query_terms = set(_tokenize(query))
    df = {}
    for t in query_terms:
        df[t] = sum(1 for toks in doc_tokens if t in toks)
    idf = {}
    for t in query_terms:
        idf[t] = math.log(1 + (N - df[t] + 0.5) / (df[t] + 0.5))
    scores = []
    for i in range(N):
        counts = Counter(doc_tokens[i])
        dl = doc_lens[i]
        score = 0.0
        for t in query_terms:
            f = counts.get(t, 0)
            if f == 0:
                continue
            denom = f + k1 * (1 - b + b * dl / avgdl)
            score += idf[t] * (f * (k1 + 1)) / denom
        scores.append(score)
    return scores
