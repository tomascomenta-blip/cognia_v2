"""
tests/test_chimera.py
=====================
Real pytest coverage for the Chimera CAPSTONE orchestrator (cognia/chimera.py).
Offline, deterministic, no LLM. Uses an isolated temp DB (tmp_path) so nothing
touches the live cognia DB.
"""

import pytest

from cognia.chimera import ChimeraSystem, ChimeraResult


# Demo queries -- one per cognitive-loop route (FAST/RECALL/DELIBERATE/ACT).
_QUERIES = [
    "hola",
    "recuerda lo que dijiste antes sobre la arquitectura de shards",
    "refactoriza el orchestrator paso a paso e implementa y prueba",
    "calcula 2+2",
]


def _fresh_db(tmp_path):
    """Return a temp DB path with the real schema initialised."""
    db = str(tmp_path / "chimera_test.db")
    from cognia.database import init_db
    init_db(db)
    return db


@pytest.mark.parametrize("query", _QUERIES)
def test_run_returns_chimera_result(tmp_path, query):
    db = _fresh_db(tmp_path)
    system = ChimeraSystem(db_path=db)
    result = system.run(query)
    assert isinstance(result, ChimeraResult)
    assert result.query == query


@pytest.mark.parametrize("query", _QUERIES)
def test_loop_output_is_non_empty_str(tmp_path, query):
    db = _fresh_db(tmp_path)
    system = ChimeraSystem(db_path=db)
    result = system.run(query)
    assert isinstance(result.loop_trace.output, str)
    assert result.loop_trace.output.strip() != ""


@pytest.mark.parametrize("query", _QUERIES)
def test_write_result_fields(tmp_path, query):
    db = _fresh_db(tmp_path)
    system = ChimeraSystem(db_path=db)
    result = system.run(query)
    w = result.write_result
    assert isinstance(w.stored_episodic, bool)
    assert 0.0 <= w.surprise <= 1.0


@pytest.mark.parametrize("query", _QUERIES)
def test_recalled_is_list(tmp_path, query):
    db = _fresh_db(tmp_path)
    system = ChimeraSystem(db_path=db)
    result = system.run(query)
    assert isinstance(result.recalled, list)


@pytest.mark.parametrize("query", _QUERIES)
def test_format_report_contains_all_markers(tmp_path, query):
    db = _fresh_db(tmp_path)
    system = ChimeraSystem(db_path=db)
    result = system.run(query)
    report = system.format_report(result)
    assert isinstance(report, str)
    for marker in ("INPUT", "HYDRA", "OUTPUT", "MEMORY WRITTEN"):
        assert marker in report
    # ASCII-only guarantee for Windows CP1252 stdout.
    report.encode("ascii")


def test_run_never_raises_on_nonexistent_db(tmp_path):
    # DB path that is never created -> system must degrade, never crash.
    missing = str(tmp_path / "does_not_exist.db")
    system = ChimeraSystem(db_path=missing)
    for query in _QUERIES:
        result = system.run(query)
        assert isinstance(result, ChimeraResult)
        assert isinstance(result.loop_trace.output, str)
        assert result.loop_trace.output.strip() != ""
