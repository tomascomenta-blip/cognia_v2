"""Cycle 6 - pure BM25 lexical scoring. Exact-phrase match must outscore
unrelated docs; degenerate inputs (empty docs, no shared terms) are well-defined.
"""

from cognia.context.lexical_index import bm25_scores


def test_bm25_exact_phrase_ranks_top():
    docs = [
        "el gato come pescado en la cocina",
        "la clave secreta del despliegue es X",
        "reporte mensual de ventas",
    ]
    s = bm25_scores("clave secreta del despliegue", docs)
    assert s[1] == max(s)


def test_bm25_empty():
    assert bm25_scores("x", []) == []


def test_bm25_no_match():
    assert bm25_scores("zzzzz", ["hola mundo"]) == [0.0]
