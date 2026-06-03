"""
tests/test_fatiga_cognitiva.py
Tests for cognia/fatiga_cognitiva.py -- CognitiveFatigueMonitor.

No psutil required; the module handles missing psutil gracefully.
All tests run in-process with controlled inputs.
"""

from __future__ import annotations

import time
import threading
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_monitor():
    from cognia.fatiga_cognitiva import CognitiveFatigueMonitor
    return CognitiveFatigueMonitor()


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

class TestConstruction:
    def test_initial_score_is_zero(self):
        m = _make_monitor()
        assert m.score == 0.0

    def test_initial_level_is_baja(self):
        m = _make_monitor()
        assert m.level == "baja"

    def test_initial_trend_is_estable(self):
        m = _make_monitor()
        assert m.trend == "estable"


# ---------------------------------------------------------------------------
# start_cycle / end_cycle
# ---------------------------------------------------------------------------

class TestCycleBasics:
    def test_end_cycle_without_start_returns_float(self):
        m = _make_monitor()
        result = m.end_cycle()
        assert isinstance(result, float)
        assert 0.0 <= result <= 100.0

    def test_end_cycle_after_start_returns_float(self):
        m = _make_monitor()
        m.start_cycle()
        time.sleep(0.01)
        result = m.end_cycle(ops_count=1)
        assert isinstance(result, float)
        assert 0.0 <= result <= 100.0

    def test_repeated_end_cycles_increment_total_cycles(self):
        m = _make_monitor()
        for _ in range(5):
            m.end_cycle()
        state = m.get_state()
        assert state["total_cycles"] == 5

    def test_expensive_ops_increment_total_expensive(self):
        m = _make_monitor()
        m.end_cycle(expensive=3, cache_misses=2)
        state = m.get_state()
        assert state["total_expensive_ops"] == 5  # expensive + cache_misses


# ---------------------------------------------------------------------------
# Score bounds
# ---------------------------------------------------------------------------

class TestScoreBounds:
    def test_score_never_exceeds_100(self):
        m = _make_monitor()
        for i in range(30):
            m.start_cycle()
            m.end_cycle(expensive=10, cache_misses=5, ops_count=50)
        assert m.score <= 100.0

    def test_score_never_below_zero(self):
        m = _make_monitor()
        m.end_cycle(ops_count=0, cache_hits=100)
        assert m.score >= 0.0


# ---------------------------------------------------------------------------
# Level thresholds
# ---------------------------------------------------------------------------

class TestLevelThresholds:
    def test_score_above_threshold_gives_moderada(self):
        from cognia.fatiga_cognitiva import CognitiveFatigueMonitor, THRESHOLD_MODERATE
        m = CognitiveFatigueMonitor()
        m._fatigue_score = float(THRESHOLD_MODERATE + 1)
        assert m.level == "moderada"

    def test_score_above_high_gives_alta(self):
        from cognia.fatiga_cognitiva import CognitiveFatigueMonitor, THRESHOLD_HIGH
        m = CognitiveFatigueMonitor()
        m._fatigue_score = float(THRESHOLD_HIGH + 1)
        assert m.level == "alta"

    def test_score_above_critical_gives_critica(self):
        from cognia.fatiga_cognitiva import CognitiveFatigueMonitor, THRESHOLD_CRITICAL
        m = CognitiveFatigueMonitor()
        m._fatigue_score = float(THRESHOLD_CRITICAL + 1)
        assert m.level == "critica"

    def test_zero_ops_cycles_keep_level_low(self):
        from cognia.fatiga_cognitiva import CognitiveFatigueMonitor, THRESHOLD_HIGH
        m = CognitiveFatigueMonitor()
        # Score just below HIGH threshold → not "alta" or "critica"
        m._fatigue_score = float(THRESHOLD_HIGH - 1)
        assert m.level in ("baja", "moderada")


# ---------------------------------------------------------------------------
# Trend detection
# ---------------------------------------------------------------------------

class TestTrend:
    def test_trend_estable_on_fresh_monitor(self):
        m = _make_monitor()
        assert m.trend == "estable"

    def test_trend_subiendo_with_increasing_scores(self):
        m = _make_monitor()
        for i in range(10):
            m.end_cycle(expensive=i, cache_misses=i)
        assert m.trend in ("subiendo", "estable")


# ---------------------------------------------------------------------------
# get_adaptations
# ---------------------------------------------------------------------------

class TestAdaptations:
    def test_adaptations_returns_dict_with_required_keys(self):
        m = _make_monitor()
        a = m.get_adaptations()
        required = {"top_k_retrieval", "attention_threshold", "inference_max_steps",
                    "enable_temporal", "enable_bridge", "embedding_cache_only",
                    "consolidation_defer", "mode"}
        assert required.issubset(a.keys())

    def test_normal_mode_has_max_retrieval(self):
        m = _make_monitor()
        a = m.get_adaptations()
        assert a["top_k_retrieval"] == 10
        assert a["mode"] == "normal"

    def test_critical_mode_disables_inference(self):
        from cognia.fatiga_cognitiva import CognitiveFatigueMonitor, THRESHOLD_CRITICAL
        m = CognitiveFatigueMonitor()
        # Force score into critical range
        m._fatigue_score = float(THRESHOLD_CRITICAL + 1)
        a = m.get_adaptations()
        assert a["mode"] == "critica"
        assert a["embedding_cache_only"] is True
        assert a["consolidation_defer"] is True

    def test_idle_reset_triggers_via_adaptations(self):
        from cognia.fatiga_cognitiva import CognitiveFatigueMonitor, THRESHOLD_HIGH
        m = CognitiveFatigueMonitor()
        m._fatigue_score = float(THRESHOLD_HIGH + 5)
        # Fake last_activity to be far in the past
        m._last_activity = time.time() - (m._IDLE_RESET_SECONDS + 1)
        m.get_adaptations()
        assert m.score == 0.0  # reset was triggered


# ---------------------------------------------------------------------------
# get_state
# ---------------------------------------------------------------------------

class TestGetState:
    def test_get_state_returns_required_keys(self):
        m = _make_monitor()
        s = m.get_state()
        expected = {
            "fatigue_score", "fatigue_level", "fatigue_trend",
            "avg_cycle_ms", "current_cpu_pct", "current_mem_mb",
            "cache_hit_rate", "total_cycles", "total_expensive_ops",
            "total_cheap_ops", "active_strategies", "uptime_minutes",
            "score_history", "energy_watts",
        }
        assert expected.issubset(s.keys())

    def test_cache_hit_rate_between_0_and_1(self):
        m = _make_monitor()
        m.end_cycle(cache_hits=5, cache_misses=5)
        s = m.get_state()
        assert 0.0 <= s["cache_hit_rate"] <= 1.0

    def test_energy_watts_positive(self):
        m = _make_monitor()
        s = m.get_state()
        assert s["energy_watts"] >= 0.0


# ---------------------------------------------------------------------------
# reset()
# ---------------------------------------------------------------------------

class TestReset:
    def test_reset_zeroes_score(self):
        from cognia.fatiga_cognitiva import CognitiveFatigueMonitor, THRESHOLD_HIGH
        m = CognitiveFatigueMonitor()
        m._fatigue_score = float(THRESHOLD_HIGH)
        m.reset()
        assert m.score == 0.0

    def test_reset_clears_cycle_times(self):
        m = _make_monitor()
        for _ in range(5):
            m.end_cycle()
        m.reset()
        state = m.get_state()
        assert state["avg_cycle_ms"] == 0.0

    def test_reset_sets_level_back_to_baja(self):
        from cognia.fatiga_cognitiva import CognitiveFatigueMonitor, THRESHOLD_HIGH
        m = CognitiveFatigueMonitor()
        m._fatigue_score = float(THRESHOLD_HIGH + 10)
        m.reset()
        assert m.level == "baja"


# ---------------------------------------------------------------------------
# reset_state()
# ---------------------------------------------------------------------------

class TestResetState:
    def test_reset_state_clears_total_cycles(self):
        m = _make_monitor()
        for _ in range(10):
            m.end_cycle()
        assert m.get_state()["total_cycles"] == 10
        m.reset_state()
        assert m.get_state()["total_cycles"] == 0

    def test_reset_state_clears_arch_proposal_time(self):
        from cognia.fatiga_cognitiva import CognitiveFatigueMonitor
        m = CognitiveFatigueMonitor()
        m._last_arch_proposal = time.time()
        m.reset_state()
        assert m._last_arch_proposal is None


# ---------------------------------------------------------------------------
# record_embedding helpers
# ---------------------------------------------------------------------------

class TestEmbeddingRecording:
    def test_record_computed_increments_total(self):
        m = _make_monitor()
        m.end_cycle()  # seed at least one entry so the deque has an element
        before = m.get_state()["total_expensive_ops"]
        m.record_embedding_computed()
        assert m.get_state()["total_expensive_ops"] == before + 1

    def test_record_cached_increments_cheap_ops(self):
        m = _make_monitor()
        m.end_cycle()
        before = m.get_state()["total_cheap_ops"]
        m.record_embedding_cached()
        assert m.get_state()["total_cheap_ops"] == before + 1


# ---------------------------------------------------------------------------
# should_propose_optimization
# ---------------------------------------------------------------------------

class TestShouldProposeOptimization:
    def test_returns_false_below_critical(self):
        from cognia.fatiga_cognitiva import CognitiveFatigueMonitor, THRESHOLD_CRITICAL
        m = CognitiveFatigueMonitor()
        m._fatigue_score = float(THRESHOLD_CRITICAL - 1)
        assert m.should_propose_optimization() is False

    def test_returns_false_when_recently_proposed(self):
        from cognia.fatiga_cognitiva import CognitiveFatigueMonitor, THRESHOLD_CRITICAL
        m = CognitiveFatigueMonitor()
        m._fatigue_score = float(THRESHOLD_CRITICAL + 5)
        m._last_arch_proposal = time.time() - 100  # 100s ago (< 3600)
        assert m.should_propose_optimization() is False


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------

class TestThreadSafety:
    def test_concurrent_end_cycle_no_crash(self):
        m = _make_monitor()
        errors = []

        def worker():
            for _ in range(20):
                try:
                    m.start_cycle()
                    m.end_cycle(ops_count=1)
                except Exception as e:
                    errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        assert not errors, f"Thread errors: {errors}"


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

class TestSingleton:
    def test_get_fatigue_monitor_returns_same_instance(self):
        from cognia.fatiga_cognitiva import get_fatigue_monitor
        a = get_fatigue_monitor()
        b = get_fatigue_monitor()
        assert a is b

    def test_singleton_is_cognitive_fatigue_monitor(self):
        from cognia.fatiga_cognitiva import get_fatigue_monitor, CognitiveFatigueMonitor
        m = get_fatigue_monitor()
        assert isinstance(m, CognitiveFatigueMonitor)


# ---------------------------------------------------------------------------
# _normalize helper
# ---------------------------------------------------------------------------

class TestNormalize:
    def test_value_below_low_returns_zero(self):
        from cognia.fatiga_cognitiva import CognitiveFatigueMonitor
        assert CognitiveFatigueMonitor._normalize(5.0, 10.0, 50.0, 100.0) == 0.0

    def test_value_at_low_returns_zero(self):
        from cognia.fatiga_cognitiva import CognitiveFatigueMonitor
        assert CognitiveFatigueMonitor._normalize(10.0, 10.0, 50.0, 100.0) == 0.0

    def test_value_at_high_returns_one(self):
        from cognia.fatiga_cognitiva import CognitiveFatigueMonitor
        assert CognitiveFatigueMonitor._normalize(100.0, 10.0, 50.0, 100.0) == 1.0

    def test_value_above_high_clamps_to_one(self):
        from cognia.fatiga_cognitiva import CognitiveFatigueMonitor
        assert CognitiveFatigueMonitor._normalize(200.0, 10.0, 50.0, 100.0) == 1.0

    def test_midpoint_returns_half(self):
        from cognia.fatiga_cognitiva import CognitiveFatigueMonitor
        result = CognitiveFatigueMonitor._normalize(50.0, 10.0, 50.0, 100.0)
        assert abs(result - 0.5) < 1e-9

    def test_interpolation_between_low_and_mid(self):
        from cognia.fatiga_cognitiva import CognitiveFatigueMonitor
        # 30 is halfway between 10 and 50 → normalized to 0.25
        result = CognitiveFatigueMonitor._normalize(30.0, 10.0, 50.0, 100.0)
        assert abs(result - 0.25) < 1e-9

    def test_interpolation_between_mid_and_high(self):
        from cognia.fatiga_cognitiva import CognitiveFatigueMonitor
        # 75 is halfway between 50 and 100 → normalized to 0.75
        result = CognitiveFatigueMonitor._normalize(75.0, 10.0, 50.0, 100.0)
        assert abs(result - 0.75) < 1e-9
