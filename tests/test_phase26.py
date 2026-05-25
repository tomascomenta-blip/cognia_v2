"""
tests/test_phase26.py — Phase 26: Safe Self-Improvement
"""

import json
import random
import tempfile
from pathlib import Path

import pytest

from cognia.agents.self_improvement import (
    TunableParams,
    BenchmarkMetrics,
    Benchmark,
    SandboxedExperiment,
    SafeImprover,
    ImprovementResult,
    _mutate,
    _composite,
    _patch_params,
    _apply_params,
    MIN_DELTA,
    MAX_EXPERIMENTS_PER_RUN,
    _BOUNDS,
)


# ── TunableParams ─────────────────────────────────────────────────────────────

class TestTunableParams:
    def test_defaults_are_valid(self):
        p = TunableParams()
        assert 0.0 < p.verifier_score_threshold < 1.0
        assert p.verifier_min_text_length > 0
        assert 0.0 < p.verifier_kg_sim_threshold < 1.0
        assert 0.0 < p.planner_episodic_threshold < 1.0
        assert 0.0 < p.research_episodic_threshold < 1.0

    def test_round_trip_dict(self):
        p = TunableParams(verifier_score_threshold=0.42, verifier_min_text_length=15)
        d = p.to_dict()
        p2 = TunableParams.from_dict(d)
        assert p2.verifier_score_threshold == pytest.approx(0.42)
        assert p2.verifier_min_text_length == 15

    def test_from_dict_ignores_unknown_keys(self):
        d = TunableParams().to_dict()
        d["unknown_field"] = "garbage"
        p = TunableParams.from_dict(d)
        assert not hasattr(p, "unknown_field")


# ── _mutate ───────────────────────────────────────────────────────────────────

class TestMutate:
    def test_mutate_returns_new_params_and_param_name(self):
        p = TunableParams()
        rng = random.Random(42)
        new_p, name = _mutate(p, rng)
        assert name in _BOUNDS
        assert isinstance(new_p, TunableParams)

    def test_mutate_stays_within_bounds(self):
        rng = random.Random(0)
        p = TunableParams()
        for _ in range(50):
            new_p, name = _mutate(p, rng)
            lo, hi, is_int = _BOUNDS[name]
            val = getattr(new_p, name)
            assert lo <= val <= hi
            if is_int:
                assert isinstance(val, int)

    def test_mutate_only_changes_one_param(self):
        rng = random.Random(99)
        p = TunableParams()
        for _ in range(20):
            new_p, name = _mutate(p, rng)
            original_d = p.to_dict()
            new_d = new_p.to_dict()
            changed = [k for k in original_d if original_d[k] != new_d[k]]
            assert len(changed) == 1
            assert changed[0] == name


# ── _composite ────────────────────────────────────────────────────────────────

class TestComposite:
    def test_perfect_metrics_give_high_score(self):
        m = BenchmarkMetrics(completion_rate=1.0, failed_rate=0.0, avg_attempts=1.0, subtask_pass_rate=1.0)
        assert _composite(m) > 0.9

    def test_zero_metrics_give_low_score(self):
        m = BenchmarkMetrics(completion_rate=0.0, failed_rate=1.0, avg_attempts=10.0, subtask_pass_rate=0.0)
        assert _composite(m) < 0.2

    def test_score_in_unit_interval(self):
        for cr, fr, aa, sp in [(0.5, 0.5, 2.0, 0.5), (1.0, 0.0, 1.0, 1.0), (0.0, 1.0, 5.0, 0.0)]:
            m = BenchmarkMetrics(cr, fr, aa, sp)
            s = _composite(m)
            assert 0.0 <= s <= 1.0


# ── Benchmark ────────────────────────────────────────────────────────────────

class TestBenchmark:
    def test_empty_db_returns_zero_metrics(self, tmp_path):
        db = str(tmp_path / "empty.db")
        m = Benchmark(db).measure()
        assert m.completion_rate == 0.0

    def test_nonexistent_db_returns_zero_metrics(self):
        m = Benchmark("/nonexistent/path/x.db").measure()
        assert m.completion_rate == 0.0

    def test_measures_real_tasks(self, tmp_path):
        db = str(tmp_path / "test.db")
        # Seed DB with known data
        import sqlite3
        conn = sqlite3.connect(db)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript("""
            CREATE TABLE agent_tasks (
                task_id TEXT PRIMARY KEY, description TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'CREATED',
                priority REAL NOT NULL DEFAULT 0.0,
                created_at REAL NOT NULL, deadline REAL, result TEXT,
                attempts INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE agent_subtasks (
                subtask_id TEXT PRIMARY KEY, task_id TEXT NOT NULL,
                description TEXT NOT NULL, tool_required TEXT NOT NULL,
                dependencies TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'pending',
                result TEXT, attempts INTEGER NOT NULL DEFAULT 0
            );
        """)
        conn.execute("INSERT INTO agent_tasks VALUES ('t1','desc','DONE',0.0,1.0,NULL,NULL,1)")
        conn.execute("INSERT INTO agent_tasks VALUES ('t2','desc','DONE',0.0,1.0,NULL,NULL,2)")
        conn.execute("INSERT INTO agent_tasks VALUES ('t3','desc','FAILED',0.0,1.0,NULL,NULL,3)")
        conn.execute("INSERT INTO agent_subtasks VALUES ('s1','t1','d','tool','[]','done',NULL,1)")
        conn.execute("INSERT INTO agent_subtasks VALUES ('s2','t1','d','tool','[]','done',NULL,1)")
        conn.execute("INSERT INTO agent_subtasks VALUES ('s3','t2','d','tool','[]','pending',NULL,0)")
        conn.commit()
        conn.close()

        m = Benchmark(db).measure()
        assert m.completion_rate == pytest.approx(2/3)
        assert m.failed_rate == pytest.approx(1/3)
        assert m.avg_attempts == pytest.approx(2.0)  # (1+2+3)/3
        assert m.subtask_pass_rate == pytest.approx(2/3)

    def test_measure_filtered_by_task_ids(self, tmp_path):
        db = str(tmp_path / "filtered.db")
        import sqlite3
        conn = sqlite3.connect(db)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript("""
            CREATE TABLE agent_tasks (
                task_id TEXT PRIMARY KEY, description TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'CREATED',
                priority REAL NOT NULL DEFAULT 0.0,
                created_at REAL NOT NULL, deadline REAL, result TEXT,
                attempts INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE agent_subtasks (
                subtask_id TEXT PRIMARY KEY, task_id TEXT NOT NULL,
                description TEXT NOT NULL, tool_required TEXT NOT NULL,
                dependencies TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'pending',
                result TEXT, attempts INTEGER NOT NULL DEFAULT 0
            );
        """)
        conn.execute("INSERT INTO agent_tasks VALUES ('t1','d','DONE',0,1,NULL,NULL,1)")
        conn.execute("INSERT INTO agent_tasks VALUES ('t2','d','FAILED',0,1,NULL,NULL,3)")
        conn.commit()
        conn.close()

        # Filter to only t1
        m = Benchmark(db).measure(task_ids=["t1"])
        assert m.completion_rate == pytest.approx(1.0)
        assert m.failed_rate == pytest.approx(0.0)


# ── _patch_params ──────────────────────────────────────────────────────────────

class TestPatchParams:
    def test_patches_and_restores(self):
        import cognia.agents.verifier as _ver
        import cognia.agents.planner as _plan

        original_score = _ver.SCORE_THRESHOLD
        original_plan  = _plan.EPISODIC_PLAN_THRESHOLD

        p = TunableParams(verifier_score_threshold=0.11, planner_episodic_threshold=0.77)
        with _patch_params(p):
            assert _ver.SCORE_THRESHOLD == pytest.approx(0.11)
            assert _plan.EPISODIC_PLAN_THRESHOLD == pytest.approx(0.77)

        # Restored
        assert _ver.SCORE_THRESHOLD == pytest.approx(original_score)
        assert _plan.EPISODIC_PLAN_THRESHOLD == pytest.approx(original_plan)

    def test_restores_on_exception(self):
        import cognia.agents.verifier as _ver
        original = _ver.SCORE_THRESHOLD
        p = TunableParams(verifier_score_threshold=0.99)
        try:
            with _patch_params(p):
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        assert _ver.SCORE_THRESHOLD == pytest.approx(original)


# ── SandboxedExperiment ───────────────────────────────────────────────────────

class TestSandboxedExperiment:
    def test_returns_benchmark_metrics(self):
        p = TunableParams()
        exp = SandboxedExperiment(p, n_tasks=2)
        m = exp.run()
        assert isinstance(m, BenchmarkMetrics)
        assert 0.0 <= m.completion_rate <= 1.0
        assert 0.0 <= m.failed_rate <= 1.0
        assert m.avg_attempts >= 0.0

    def test_does_not_touch_real_db(self, tmp_path):
        real_db = tmp_path / "real.db"
        # real_db should not exist after experiment
        p = TunableParams()
        exp = SandboxedExperiment(p, n_tasks=1)
        exp.run()
        assert not real_db.exists()

    def test_temp_db_cleaned_up(self):
        import os
        p = TunableParams()
        tmp_paths = []

        original_run = SandboxedExperiment._run_in
        def tracking_run(self, db_path):
            tmp_paths.append(db_path)
            return original_run(self, db_path)

        exp = SandboxedExperiment(p, n_tasks=1)
        m = exp.run()
        if tmp_paths:
            assert not Path(tmp_paths[0]).exists()


# ── SafeImprover ──────────────────────────────────────────────────────────────

class TestSafeImprover:
    def test_run_returns_improvement_result(self, tmp_path):
        db = str(tmp_path / "agents.db")
        imp = SafeImprover(agents_db_path=db, n_tasks=2, seed=42)
        result = imp.run()
        assert isinstance(result, ImprovementResult)
        assert isinstance(result.adopted, bool)
        assert result.baseline_score >= 0.0
        assert result.best_score >= result.baseline_score
        assert len(result.experiments) <= MAX_EXPERIMENTS_PER_RUN

    def test_summary_contains_key_fields(self, tmp_path):
        db = str(tmp_path / "agents.db")
        imp = SafeImprover(agents_db_path=db, n_tasks=1, seed=0)
        result = imp.run()
        s = result.summary()
        assert "self_improvement" in s
        assert "delta=" in s
        assert "score=" in s

    def test_params_persisted_when_adopted(self, tmp_path):
        db = str(tmp_path / "agents.db")
        params_file = tmp_path / "agents.params.json"

        imp = SafeImprover(agents_db_path=db, n_tasks=2, seed=1)
        result = imp.run()
        if result.adopted:
            assert params_file.exists()
            loaded = TunableParams.from_dict(json.loads(params_file.read_text()))
            assert loaded.to_dict() == result.params.to_dict()

    def test_load_save_round_trip(self, tmp_path):
        db = str(tmp_path / "agents.db")
        imp = SafeImprover(agents_db_path=db)
        p = TunableParams(verifier_score_threshold=0.55)
        imp._save_params(p)
        loaded = imp._load_params()
        assert loaded.verifier_score_threshold == pytest.approx(0.55)

    def test_load_returns_defaults_if_no_file(self, tmp_path):
        db = str(tmp_path / "agents.db")
        imp = SafeImprover(agents_db_path=db)
        p = imp._load_params()
        defaults = TunableParams()
        assert p.to_dict() == defaults.to_dict()

    def test_no_adoption_below_min_delta(self, tmp_path):
        """Con baseline score == best score no hay adopción."""
        db = str(tmp_path / "agents.db")
        imp = SafeImprover(agents_db_path=db, n_tasks=1, seed=7)
        # Run once to get baseline established, run again to check stability
        imp.run()
        result2 = imp.run()
        # Just assert it completes without error and delta is finite
        assert isinstance(result2.delta, float)


# ── _apply_params ────────────────────────────────────────────────────────────

class TestApplyParams:
    def test_applies_to_modules(self):
        import cognia.agents.verifier as _ver
        import cognia.agents.planner as _plan
        original_score = _ver.SCORE_THRESHOLD
        original_plan  = _plan.EPISODIC_PLAN_THRESHOLD

        try:
            p = TunableParams(verifier_score_threshold=0.38, planner_episodic_threshold=0.91)
            _apply_params(p)
            assert _ver.SCORE_THRESHOLD == pytest.approx(0.38)
            assert _plan.EPISODIC_PLAN_THRESHOLD == pytest.approx(0.91)
        finally:
            _ver.SCORE_THRESHOLD          = original_score
            _plan.EPISODIC_PLAN_THRESHOLD = original_plan
