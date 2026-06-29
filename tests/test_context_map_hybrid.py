"""Cycle 6 - hybrid retrieval (BM25 lexical + vector fusion).

Reproduces the e2e finding: a vector alone ranks a deceptively-close but
unrelated chunk above the chunk that literally contains the answer phrase.
The lexical re-rank (BM25) recovers the right chunk. Vectors are deterministic.
"""

import pytest

from cognia.context.context_map import ContextMap
from storage.db_pool import close_pool


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "ctxmap_hybrid_test.db")
    yield path
    close_pool(path)


def _setup(db_path):
    cm = ContextMap(db_path=db_path, project="p")
    # A: vector deceptively close to the query but NOT the answer.
    a = cm.add_pointer(
        "text", "",
        inline_text=("El componente de notificaciones envia alertas cuando hay "
                     "eventos criticos en produccion"),
        vector=[0.0, 1.0],
    )
    # B: holds the literal answer phrase, vector worse AND genuinely different
    # (not near-identical) so min-max fusion produces the exact 0.5 tie the e2e
    # exposed; only margin-preserving max-norm lifts B above A.
    b = cm.add_pointer(
        "text", "",
        inline_text="La clave secreta del despliegue es ZephyrPangolin-7741",
        vector=[0.3, 0.95],
    )
    return cm, a, b


def test_vector_alone_misses(db_path):
    cm, a, b = _setup(db_path)
    res = cm.query([0.0, 1.0], budget_tokens=4000)
    assert res[0]["id"] == a


def test_hybrid_recovers_with_lexical(db_path):
    cm, a, b = _setup(db_path)
    res = cm.query_hybrid("clave secreta del despliegue", [0.0, 1.0],
                          vec_weight=0.5)
    assert res[0]["id"] == b


def test_query_hybrid_empty_vector_falls_to_bm25(db_path):
    cm, a, b = _setup(db_path)
    res = cm.query_hybrid("clave secreta", [], vec_weight=0.5)
    assert res[0]["id"] == b


def test_query_text_hybrid(db_path):
    cm, a, b = _setup(db_path)
    embed_fn = lambda t: [0.0, 1.0]
    res = cm.query_text_hybrid("clave secreta del despliegue", embed_fn)
    assert res[0]["id"] == b
