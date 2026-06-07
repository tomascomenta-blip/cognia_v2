"""
tests/test_continuous_learning.py
=================================
Real pytest coverage for the Chimera 3-speed continuous-learning controller.
Uses a tmp_path-backed DB so the live cognia DB is never touched. No mocks.
"""

import pytest

from cognia.learning.continuous_learning import (
    ContinuousLearning,
    LearnResult,
    format_report,
)


@pytest.fixture
def db_path(tmp_path):
    # WHY: a fresh, empty SQLite file path under tmp_path. The controller
    # builds its subsystems lazily and tolerates an empty/uninitialised DB.
    return str(tmp_path / "cl_test.db")


def test_learn_fast_returns_fast_and_bool_stored(db_path):
    cl = ContinuousLearning(db_path=db_path, user_id="t")
    r = cl.learn_fast("Decidi que siempre usare numpy puro en los nodos.")
    assert isinstance(r, LearnResult)
    assert r.speed == "fast"
    # stored_episodic is reported as a real boolean when a backend is present.
    if "stored_episodic" in r.detail:
        assert isinstance(r.detail["stored_episodic"], bool)


def test_learn_fast_never_raises_empty_and_weird_input(db_path):
    cl = ContinuousLearning(db_path=db_path, user_id="t")
    for obs in ["", "ok", "x" * 500, "acentuacion: nino cafe"]:
        r = cl.learn_fast(obs)
        assert r.speed == "fast"


def test_distillation_status_shape(db_path):
    cl = ContinuousLearning(db_path=db_path, user_id="t")
    st = cl.distillation_status()
    assert isinstance(st, dict)
    assert isinstance(st["episode_count"], int)
    assert isinstance(st["should_distill"], bool)
    assert "high_importance_count" in st
    assert "adapter_present" in st
    assert "note" in st


def test_distillation_should_distill_false_on_empty_db(db_path):
    cl = ContinuousLearning(db_path=db_path, user_id="t")
    st = cl.distillation_status()
    # Empty DB -> far below the episode threshold.
    assert st["episode_count"] >= 0
    assert st["should_distill"] is False


def test_learn_medium_returns_medium_with_valid_action(db_path):
    cl = ContinuousLearning(db_path=db_path, user_id="t")
    r = cl.learn_medium()
    assert r.speed == "medium"
    assert r.action in {"distill_triggered", "no_distill_needed"}
    # Honest scope: medium tier never trains weights.
    assert r.detail.get("trains_weights") is False


def test_consolidate_slow_returns_slow_dict(db_path):
    cl = ContinuousLearning(db_path=db_path, user_id="t")
    r = cl.consolidate_slow()
    assert r.speed == "slow"
    assert isinstance(r.detail, dict)
    assert "decay" in r.detail


def test_cycle_covers_three_speeds(db_path):
    cl = ContinuousLearning(db_path=db_path, user_id="t")
    summary = cl.cycle([
        "Decidi que siempre usare numpy puro en los nodos.",
        "Probe el cafe de la esquina hoy.",
    ])
    assert set(["fast", "medium", "slow"]).issubset(summary.keys())
    assert isinstance(summary["fast"], list)
    assert summary["medium"].speed == "medium"
    assert summary["slow"].speed == "slow"
    # format_report must produce an ASCII string covering all three speeds.
    report = format_report(summary)
    assert "FAST" in report and "MEDIUM" in report and "SLOW" in report
    report.encode("ascii")  # raises if any non-ASCII slipped through


def test_never_raises_on_nonexistent_db_path(tmp_path):
    bogus = str(tmp_path / "does" / "not" / "exist" / "nope.db")
    cl = ContinuousLearning(db_path=bogus, user_id="t")
    # Every public method must degrade gracefully, never raise.
    cl.learn_fast("hola")
    cl.distillation_status()
    cl.learn_medium()
    cl.consolidate_slow()
    summary = cl.cycle(["uno", "dos"])
    assert "fast" in summary
