"""
tests/test_self_improvement.py
===============================
Unit tests for cognia/agents/self_improvement.py (Phase 26).

Only tests pure/SQLite components — no LLM calls, no CogniaAgentRuntime.
All DB operations use tmp_path for isolation.
"""

import json
import os
import random
import sqlite3
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from cognia.agents.self_improvement import (
    _BOUNDS,
    _composite,
    _mutate,
    Benchmark,
    BenchmarkMetrics,
    ImprovementResult,
    SafeImprover,
    TunableParams,
)


# ---------------------------------------------------------------------------
# TunableParams
# ---------------------------------------------------------------------------

def test_tunable_params_defaults():
    p = TunableParams()
    assert 0.0 < p.verifier_score_threshold < 1.0
    assert p.verifier_min_text_length > 0
    assert 0.0 < p.planner_episodic_threshold < 1.0


def test_tunable_params_round_trip():
    p = TunableParams(
        verifier_score_threshold=0.55,
        verifier_min_text_length=30,
        verifier_kg_sim_threshold=0.25,
        planner_episodic_threshold=0.80,
        research_episodic_threshold=0.70,
    )
    d = p.to_dict()
    p2 = TunableParams.from_dict(d)
    assert p2.verifier_score_threshold == pytest.approx(0.55)
    assert p2.verifier_min_text_length == 30
    assert p2.planner_episodic_threshold == pytest.approx(0.80)


def test_tunable_params_from_dict_ignores_unknown_keys():
    d = {
        "verifier_score_threshold": 0.65,
        "verifier_min_text_length": 25,
        "verifier_kg_sim_threshold": 0.20,
        "planner_episodic_threshold": 0.88,
        "research_episodic_threshold": 0.72,
        "nonexistent_key": 999,
    }
    p = TunableParams.from_dict(d)
    assert p.verifier_score_threshold == pytest.approx(0.65)
    assert not hasattr(p, "nonexistent_key")


# ---------------------------------------------------------------------------
# _mutate
# ---------------------------------------------------------------------------

def test_mutate_stays_within_bounds():
    rng = random.Random(42)
    params = TunableParams()
    for _ in range(50):
        new_params, mutated = _mutate(params, rng)
        lo, hi, is_int = _BOUNDS[mutated]
        val = getattr(new_params, mutated)
        assert lo <= val <= hi, f"{mutated}={val} out of [{lo}, {hi}]"
        if is_int:
            assert isinstance(val, int)


def test_mutate_changes_exactly_one_param():
    rng = random.Random(7)
    params = TunableParams()
    new_params, mutated_name = _mutate(params, rng)
    changed = [
        k for k in params.to_dict()
        if getattr(params, k) != getattr(new_params, k)
    ]
    assert len(changed) == 1
    assert changed[0] == mutated_name


# ---------------------------------------------------------------------------
# _composite
# ---------------------------------------------------------------------------

def test_composite_perfect_metrics():
    m = BenchmarkMetrics(
        completion_rate=1.0,
        failed_rate=0.0,
        avg_attempts=1.0,
        subtask_pass_rate=1.0,
    )
    score = _composite(m)
    assert 0.0 <= score <= 1.0
    assert score > 0.9


def test_composite_worst_metrics():
    m = BenchmarkMetrics(
        completion_rate=0.0,
        failed_rate=1.0,
        avg_attempts=10.0,
        subtask_pass_rate=0.0,
    )
    score = _composite(m)
    assert 0.0 <= score <= 1.0
    assert score < 0.2


def test_composite_neutral_metrics():
    m = BenchmarkMetrics(
        completion_rate=0.5,
        failed_rate=0.5,
        avg_attempts=2.0,
        subtask_pass_rate=0.5,
    )
    score = _composite(m)
    assert 0.0 < score < 1.0


# ---------------------------------------------------------------------------
# Benchmark
# ---------------------------------------------------------------------------

def test_benchmark_returns_empty_when_db_missing(tmp_path):
    bench = Benchmark(str(tmp_path / "does_not_exist.db"))
    m = bench.measure()
    assert m.completion_rate == 0.0
    assert m.failed_rate == 0.0
    assert m.subtask_pass_rate == 0.0


def test_benchmark_computes_metrics_from_seeded_db(tmp_path):
    db_file = str(tmp_path / "agents.db")
    conn = sqlite3.connect(db_file)
    conn.executescript("""
        CREATE TABLE agent_tasks (
            task_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE agent_subtasks (
            id INTEGER PRIMARY KEY,
            task_id TEXT,
            status TEXT
        );
    """)
    # 3 DONE, 1 FAILED, 1 ABORTED -> completion_rate=0.6, failed_rate=0.2
    conn.executemany(
        "INSERT INTO agent_tasks VALUES (?,?,?)",
        [
            ("t1", "DONE",    1),
            ("t2", "DONE",    2),
            ("t3", "DONE",    3),
            ("t4", "FAILED",  1),
            ("t5", "ABORTED", 1),
        ],
    )
    # 2 subtasks done out of 4 -> subtask_pass_rate=0.5
    conn.executemany(
        "INSERT INTO agent_subtasks (task_id, status) VALUES (?,?)",
        [("t1", "done"), ("t1", "done"), ("t2", "pending"), ("t2", "pending")],
    )
    conn.commit()
    conn.close()

    bench = Benchmark(db_file)
    m = bench.measure()

    assert m.completion_rate == pytest.approx(0.6)
    assert m.failed_rate == pytest.approx(0.2)
    assert m.avg_attempts == pytest.approx((1 + 2 + 3 + 1 + 1) / 5)
    assert m.subtask_pass_rate == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# ImprovementResult.summary
# ---------------------------------------------------------------------------

def test_improvement_result_summary_adopted():
    result = ImprovementResult(
        adopted=True,
        baseline_score=0.50,
        best_score=0.55,
        delta=0.05,
        mutated_param="verifier_score_threshold",
        params=TunableParams(),
    )
    s = result.summary()
    assert "ADOPTED" in s
    assert "+0.0500" in s or "0.05" in s


def test_improvement_result_summary_no_change():
    result = ImprovementResult(
        adopted=False,
        baseline_score=0.50,
        best_score=0.50,
        delta=0.00,
        mutated_param=None,
        params=TunableParams(),
    )
    s = result.summary()
    assert "NO_CHANGE" in s


# ---------------------------------------------------------------------------
# SafeImprover persistence
# ---------------------------------------------------------------------------

def test_safe_improver_load_params_returns_defaults_when_no_json(tmp_path):
    db = str(tmp_path / "agents.db")
    improver = SafeImprover(agents_db_path=db)
    params = improver.current_params()
    defaults = TunableParams()
    assert params.verifier_score_threshold == defaults.verifier_score_threshold
    assert params.verifier_min_text_length == defaults.verifier_min_text_length


def test_safe_improver_save_and_load_round_trip(tmp_path):
    db = str(tmp_path / "agents.db")
    improver = SafeImprover(agents_db_path=db)
    custom = TunableParams(
        verifier_score_threshold=0.77,
        verifier_min_text_length=42,
        verifier_kg_sim_threshold=0.15,
        planner_episodic_threshold=0.91,
        research_episodic_threshold=0.88,
    )
    improver._save_params(custom)
    loaded = improver._load_params()
    assert loaded.verifier_score_threshold == pytest.approx(0.77)
    assert loaded.verifier_min_text_length == 42
    assert loaded.research_episodic_threshold == pytest.approx(0.88)
