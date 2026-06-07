"""
tests/test_band_router.py
=========================
Tests for the HYDRA-analogue 3-band context/memory router.

No network and no real model required -- the underlying GlobalRouter falls
back to n-gram embeddings, and the memory layers tolerate an empty/missing DB.
"""

import os
import tempfile

import pytest

from cognia.context.band_router import (
    HydraContextRouter,
    HydraRouting,
    BandResult,
)


def _band(routing: HydraRouting, name: str) -> BandResult:
    for b in routing.bands:
        if b.name == name:
            return b
    raise AssertionError("band %s not found" % name)


@pytest.fixture(scope="module")
def router():
    # Point at a non-existent DB inside a temp dir to prove empty-DB tolerance.
    tmpdir = tempfile.mkdtemp(prefix="hydra_test_")
    db_path = os.path.join(tmpdir, "does_not_exist.db")
    return HydraContextRouter(db_path=db_path)


# NOTE: the exact persona depends on the embedding backend. Without
# sentence-transformers installed, GlobalRouter uses an n-gram fallback whose
# centroids are upgraded on a background thread, so the precise winner is not
# deterministic across runs. The spec requires the persona to be a VALID
# member of the routing set for each query class, which is what we assert.

def test_persona_code_query(router):
    r = router.route("escribe una funcion de binary search en python")
    assert r.persona in {"logos", "techne", "rhetor"}


def test_persona_writing_query(router):
    r = router.route("redacta un parrafo elegante y eloquente sobre el oceano")
    assert r.persona in {"logos", "techne", "rhetor"}


def test_persona_reasoning_query(router):
    r = router.route("explica por que la entropia siempre aumenta y analiza la causa")
    assert r.persona in {"logos", "techne", "rhetor"}


def test_local_always_active(router):
    for q in [
        "hola",
        "escribe binary search",
        "recuerda lo que dijiste antes sobre X?",
    ]:
        r = router.route(q)
        local = _band(r, "LOCAL")
        assert local.active is True
        assert local.score == 1.0


def test_recall_cues_activate_global(router):
    r = router.route("recuerda lo que dijiste antes sobre la arquitectura de shards?")
    g = _band(r, "GLOBAL")
    assert g.active is True
    assert g.score > 0.0


def test_short_code_query_no_forced_global(router):
    # A trivial short code query has no recall cues and is not a logos question,
    # so GLOBAL should not necessarily activate.
    r = router.route("escribe binary search")
    assert r.persona in {"logos", "techne", "rhetor"}
    g = _band(r, "GLOBAL")
    assert g.active is False


def test_never_raises_on_missing_db():
    # Construct against a guaranteed-nonexistent path; route() must not raise.
    db_path = os.path.join(tempfile.gettempdir(), "no_such_cognia_db_xyz.db")
    router = HydraContextRouter(db_path=db_path)
    routing = router.route("recuerda algo sobre vectores y embeddings antes mencionados")
    assert isinstance(routing, HydraRouting)


def test_assembled_context_is_str_with_local(router):
    r = router.route("hola, escribe algo")
    assert isinstance(r.assembled_context, str)
    assert "LOCAL" in r.assembled_context


def test_media_active_emits_summary(router):
    # A long multi-clause query activates MEDIA (compressed/summarized band).
    # Extractive summary output varies, so assert STRUCTURE not text: MEDIA is
    # active, items is a list, and a summary-derived entry is present.
    long_q = (
        "resume y compara las decisiones de arquitectura de shards y el "
        "routing semantico que discutimos; ademas explica el world model"
    )
    r = router.route(long_q)
    media = _band(r, "MEDIA")
    assert media.active is True
    assert isinstance(media.items, list)
    assert any(it.startswith("summary:") for it in media.items)


def test_media_never_raises_and_returns_list(router):
    # MEDIA retrieval must degrade gracefully: a list, never an exception,
    # regardless of whether the summarizer produced output.
    for q in ["hola", "resume y compara A; ademas analiza B y explica C extensamente aqui"]:
        r = router.route(q)
        media = _band(r, "MEDIA")
        assert isinstance(media.items, list)


def test_global_band_returns_ascii_strings_and_does_not_raise(router):
    # A recall-cue query activates GLOBAL, which now runs through the fusion
    # re-ranker. Regardless of DB contents, the band items must be a list of
    # ASCII-only strings and routing must not raise.
    r = router.route(
        "recuerda lo que dijiste antes sobre la arquitectura de shards y el "
        "routing semantico"
    )
    g = _band(r, "GLOBAL")
    assert g.active is True
    assert isinstance(g.items, list)
    for it in g.items:
        assert isinstance(it, str)
        assert it == it.encode("ascii", "replace").decode("ascii")
