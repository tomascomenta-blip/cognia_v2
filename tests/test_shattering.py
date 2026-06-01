"""
tests/test_shattering.py
========================
Test suite for the Shattering architecture:
  GlobalRouter, ManifestLoader, FragmentManager, MoELayer/MoERouter,
  ShatteringOrchestrator.

All tests use simulation mode — no real model weights required.
Fragment manager tests clean up temporary directories.
"""

import json
import os
import sys
import tempfile
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


# ─────────────────────────────────────────────────────────────────────
# GlobalRouter
# ─────────────────────────────────────────────────────────────────────

class TestGlobalRouter:

    @pytest.fixture(autouse=True)
    def router(self):
        from shattering.router import GlobalRouter
        self.router = GlobalRouter()

    def test_code_prompt_routes_to_techne(self):
        decision = self.router.route("write a python function to sort a list")
        assert decision.sub_model == "techne"

    def test_debug_prompt_routes_to_techne(self):
        decision = self.router.route("debug this javascript code with an exception")
        assert decision.sub_model == "techne"

    def test_philosophy_routes_to_logos(self):
        decision = self.router.route("explain the concept of consciousness in philosophy")
        assert decision.sub_model == "logos"

    def test_analysis_routes_to_logos(self):
        decision = self.router.route("analyze the cause and effect of climate change")
        assert decision.sub_model == "logos"

    def test_essay_routes_to_rhetor(self):
        decision = self.router.route("write an essay and draft a narrative paragraph")
        assert decision.sub_model == "rhetor"

    def test_summarize_routes_to_rhetor(self):
        decision = self.router.route("summarize this paragraph and rewrite it")
        assert decision.sub_model == "rhetor"

    def test_empty_string_defaults_to_logos(self):
        decision = self.router.route("")
        assert decision.sub_model == "logos"
        assert decision.confidence == pytest.approx(0.3)

    def test_no_crash_on_10k_input(self):
        big_prompt = "x " * 5000  # 10000 chars
        decision = self.router.route(big_prompt)
        assert decision.sub_model in ("logos", "techne", "rhetor")

    def test_truncation_limits_to_2000_chars(self):
        # Long prompt with only code keywords past the 2000 char mark
        preamble = "write an essay " * 100          # ~1500 chars — rhetor territory
        suffix   = " code python function " * 200   # code keywords after position 2000
        decision = self.router.route(preamble + suffix)
        # Rhetor keywords dominate the first 2000 chars → rhetor wins
        assert decision.sub_model == "rhetor"

    def test_route_decision_has_required_fields(self):
        from shattering.router import RouteDecision
        decision = self.router.route("what is recursion")
        assert isinstance(decision, RouteDecision)
        assert hasattr(decision, "sub_model")
        assert hasattr(decision, "confidence")
        assert hasattr(decision, "scores")
        assert hasattr(decision, "reason")
        assert 0.0 <= decision.confidence <= 1.0

    def test_scores_dict_has_all_domains(self):
        decision = self.router.route("hello")
        assert set(decision.scores.keys()) == {"techne", "rhetor", "logos"}


# ─────────────────────────────────────────────────────────────────────
# ManifestLoader
# ─────────────────────────────────────────────────────────────────────

MANIFEST_IDS = [
    "cognia_desktop",
    "cognia_code",
    "cognia_writing",
    "cognia_android",
    "cognia_writing_android",
]


class TestManifestLoader:

    @pytest.fixture(autouse=True)
    def clear_cache(self):
        from shattering.manifest import ManifestLoader
        ManifestLoader.invalidate_cache()
        yield
        ManifestLoader.invalidate_cache()

    def test_loads_all_5_manifests_without_error(self):
        from shattering.manifest import ManifestLoader, AppManifest
        for app_id in MANIFEST_IDS:
            m = ManifestLoader.load(app_id)
            assert isinstance(m, AppManifest), f"Failed to load: {app_id}"
            assert m.app_id == app_id

    def test_available_apps_returns_all_5(self):
        from shattering.manifest import ManifestLoader
        apps = ManifestLoader.available_apps()
        for app_id in MANIFEST_IDS:
            assert app_id in apps

    def test_desktop_manifest_logos_fragment_count(self):
        from shattering.manifest import ManifestLoader
        m = ManifestLoader.load("cognia_desktop")
        logos_frags = m.fragments_for_sub_model("logos")
        assert len(logos_frags) == 4  # shards 0-3 bundled

    def test_code_manifest_techne_is_primary(self):
        from shattering.manifest import ManifestLoader
        m = ManifestLoader.load("cognia_code")
        assert m.primary_sub_model() == "techne"

    def test_env_var_coordinator_url_resolved(self):
        from shattering.manifest import ManifestLoader
        test_url = "http://test-coordinator:9000"
        with patch.dict(os.environ, {"COGNIA_COORDINATOR_URL": test_url}):
            ManifestLoader.invalidate_cache()
            m = ManifestLoader.load("cognia_desktop")
        assert m.coordinator_url == test_url

    def test_env_var_empty_gives_empty_string(self):
        from shattering.manifest import ManifestLoader
        env = {k: v for k, v in os.environ.items() if k != "COGNIA_COORDINATOR_URL"}
        with patch.dict(os.environ, env, clear=True):
            ManifestLoader.invalidate_cache()
            m = ManifestLoader.load("cognia_desktop")
        assert m.coordinator_url == ""

    def test_fragment_spec_fields_present(self):
        from shattering.manifest import ManifestLoader, FragmentSpec
        m = ManifestLoader.load("cognia_desktop")
        spec = m.bundled[0]
        assert isinstance(spec, FragmentSpec)
        assert spec.sub_model == "logos"
        assert spec.shard_index == 0
        assert isinstance(spec.layer_range, list)
        assert len(spec.layer_range) == 2

    def test_all_fragments_includes_bundled_on_demand_optional(self):
        from shattering.manifest import ManifestLoader
        m = ManifestLoader.load("cognia_desktop")
        all_f = m.all_fragments()
        assert len(all_f) == len(m.bundled) + len(m.on_demand) + len(m.optional)


# ─────────────────────────────────────────────────────────────────────
# FragmentManager
# ─────────────────────────────────────────────────────────────────────

def _make_spec(sub_model: str, shard_index: int):
    from shattering.manifest import FragmentSpec
    return FragmentSpec(
        fragment_id=f"{sub_model}/{shard_index}/q4_k_m",
        sub_model=sub_model,
        shard_index=shard_index,
        quantization="q4_k_m",
        layer_range=[shard_index * 7, shard_index * 7 + 6],
        size_bytes=500_000_000,
        sha256="",
        hf_repo=f"cognia-ai/{sub_model}-3.2-3b-q4",
        hf_filename=f"shard_{shard_index}.safetensors",
    )


class _FakeEngine:
    """Lightweight stand-in for ShardEngine in tests."""
    def __init__(self, config, weights_path=None):
        self.config = config
        self.mode = "simulation"


class _FakeConfig:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class TestFragmentManager:

    @pytest.fixture
    def tmpdir(self):
        with tempfile.TemporaryDirectory() as d:
            yield d

    def _manager(self, tmpdir, max_sm=2):
        from shattering.fragment_manager import FragmentManager
        return FragmentManager(base_dir=tmpdir, max_loaded_submodels=max_sm)

    def _load_patched(self, fm, spec):
        with patch("node.shard_engine.ShardConfig", _FakeConfig), \
             patch("node.shard_engine.ShardEngine", _FakeEngine):
            return fm.load(spec)

    def test_load_returns_engine(self, tmpdir):
        fm = self._manager(tmpdir)
        spec = _make_spec("logos", 0)
        engine = self._load_patched(fm, spec)
        assert engine is not None

    def test_is_loaded_after_load(self, tmpdir):
        fm = self._manager(tmpdir)
        spec = _make_spec("logos", 0)
        self._load_patched(fm, spec)
        assert fm.is_loaded("logos") is True

    def test_is_not_loaded_before_load(self, tmpdir):
        fm = self._manager(tmpdir)
        assert fm.is_loaded("logos") is False

    def test_is_loaded_specific_shard(self, tmpdir):
        fm = self._manager(tmpdir)
        spec = _make_spec("logos", 0)
        self._load_patched(fm, spec)
        assert fm.is_loaded("logos", 0) is True
        assert fm.is_loaded("logos", 1) is False

    def test_evict_removes_sub_model(self, tmpdir):
        fm = self._manager(tmpdir)
        spec = _make_spec("logos", 0)
        self._load_patched(fm, spec)
        fm.evict("logos")
        assert fm.is_loaded("logos") is False

    def test_lru_eviction_on_third_sub_model(self, tmpdir):
        fm = self._manager(tmpdir, max_sm=2)
        specs = [_make_spec("logos", 0), _make_spec("techne", 0), _make_spec("rhetor", 0)]

        with patch("node.shard_engine.ShardConfig", _FakeConfig), \
             patch("node.shard_engine.ShardEngine", _FakeEngine):
            fm.load(specs[0])  # logos loaded — LRU: logos
            fm.load(specs[1])  # techne loaded — LRU: logos, techne
            fm.load(specs[2])  # rhetor loaded — logos evicted (LRU victim)

        # logos should have been evicted to make room for rhetor
        assert not fm.is_loaded("logos")
        assert fm.is_loaded("techne")
        assert fm.is_loaded("rhetor")

    def test_status_returns_expected_keys(self, tmpdir):
        fm = self._manager(tmpdir)
        s = fm.status()
        assert "loaded_fragments" in s
        assert "loaded_sub_models" in s
        assert "lru_order" in s
        assert "max_sub_models" in s


# ─────────────────────────────────────────────────────────────────────
# MoERouter
# ─────────────────────────────────────────────────────────────────────

class TestMoERouter:

    @pytest.fixture(autouse=True)
    def setup(self):
        from shattering.moe_layer import MoERouter, ShatteringMoEConfig
        self.cfg = ShatteringMoEConfig()
        self.router = MoERouter(self.cfg, seed=0)

    def test_route_returns_correct_shapes(self):
        x = np.random.randn(8, self.cfg.hidden_dim).astype(np.float32)
        ids, weights, _ = self.router.route(x)
        assert ids.shape    == (8, self.cfg.top_k)
        assert weights.shape == (8, self.cfg.top_k)

    def test_routing_weights_sum_to_one(self):
        x = np.random.randn(16, self.cfg.hidden_dim).astype(np.float32)
        _, weights, _ = self.router.route(x)
        row_sums = weights.sum(axis=-1)
        np.testing.assert_allclose(row_sums, 1.0, atol=1e-5)

    def test_all_zeros_input_no_crash(self):
        x = np.zeros((5, self.cfg.hidden_dim), dtype=np.float32)
        ids, weights, aux = self.router.route(x)
        assert ids.shape == (5, self.cfg.top_k)
        assert not np.any(np.isnan(aux))

    def test_expert_ids_in_valid_range(self):
        x = np.random.randn(10, self.cfg.hidden_dim).astype(np.float32)
        ids, _, _ = self.router.route(x)
        assert np.all(ids >= 0)
        assert np.all(ids < self.cfg.num_experts)

    def test_routing_stats_tracks_tokens(self):
        x = np.random.randn(7, self.cfg.hidden_dim).astype(np.float32)
        self.router.reset_stats()
        self.router.route(x)
        stats = self.router.routing_stats()
        assert stats["total_tokens"] == 7
        total_counted = sum(v["count"] for v in stats["per_expert"].values())
        assert total_counted == 7

    def test_reset_stats_zeroes_counts(self):
        x = np.random.randn(5, self.cfg.hidden_dim).astype(np.float32)
        self.router.route(x)
        self.router.reset_stats()
        stats = self.router.routing_stats()
        assert stats["total_tokens"] == 0
        for v in stats["per_expert"].values():
            assert v["count"] == 0


# ─────────────────────────────────────────────────────────────────────
# MoELayer
# ─────────────────────────────────────────────────────────────────────

class TestMoELayer:

    @pytest.fixture(autouse=True)
    def setup(self):
        from shattering.moe_layer import MoELayer, ShatteringMoEConfig
        self.cfg = ShatteringMoEConfig()
        self.layer = MoELayer(self.cfg, simulation=True, router_seed=1)

    def test_output_shape_preserved(self):
        x = np.random.randn(10, self.cfg.hidden_dim).astype(np.float32)
        out, _ = self.layer(x)
        assert out.shape == x.shape

    def test_aux_loss_in_valid_range(self):
        x = np.random.randn(10, self.cfg.hidden_dim).astype(np.float32)
        _, aux = self.layer(x)
        assert 0.0 <= aux <= self.cfg.num_experts

    def test_routing_stats_total_equals_seq_len(self):
        seq_len = 12
        x = np.random.randn(seq_len, self.cfg.hidden_dim).astype(np.float32)
        self.layer.reset_stats()
        self.layer(x)
        stats = self.layer.routing_stats()
        total = sum(v["count"] for v in stats["per_expert"].values())
        assert total == seq_len

    def test_reset_stats_zeroes(self):
        x = np.random.randn(5, self.cfg.hidden_dim).astype(np.float32)
        self.layer(x)
        self.layer.reset_stats()
        stats = self.layer.routing_stats()
        assert stats["total_tokens"] == 0
        for v in stats["per_expert"].values():
            assert v["count"] == 0

    def test_top_k_2_no_crash(self):
        from shattering.moe_layer import MoELayer, ShatteringMoEConfig
        cfg = ShatteringMoEConfig(top_k=2)
        layer = MoELayer(cfg, simulation=True)
        x = np.random.randn(8, cfg.hidden_dim).astype(np.float32)
        out, aux = layer(x)
        assert out.shape == x.shape
        assert 0.0 <= aux <= cfg.num_experts

    def test_callable_via_dunder_call(self):
        x = np.random.randn(4, self.cfg.hidden_dim).astype(np.float32)
        out, aux = self.layer(x)
        assert out is not None

    def test_per_expert_fractions_sum_to_one(self):
        x = np.random.randn(100, self.cfg.hidden_dim).astype(np.float32)
        self.layer.reset_stats()
        self.layer(x)
        stats = self.layer.routing_stats()
        total_fraction = sum(v["fraction"] for v in stats["per_expert"].values())
        assert total_fraction == pytest.approx(1.0, abs=0.01)


# ─────────────────────────────────────────────────────────────────────
# ShatteringOrchestrator
# ─────────────────────────────────────────────────────────────────────

DESKTOP_MANIFEST = str(ROOT / "shattering" / "manifests" / "cognia_desktop.json")


class TestShatteringOrchestrator:

    @pytest.fixture(autouse=True)
    def _mock_llm(self):
        """Prevent actual LLM calls (llama-server cold start / shard inference / Ollama timeout) during unit tests."""
        from shattering.orchestrator import ShatteringOrchestrator
        with patch.object(ShatteringOrchestrator, '_try_load_llama', lambda self: None), \
             patch.object(ShatteringOrchestrator, '_shards_available', lambda self: False), \
             patch.object(ShatteringOrchestrator, '_ollama_infer',
                          lambda self, prompt, sub_model, n_passes=1: "[Simulation] Test mock response."):
            yield

    @pytest.fixture
    def tmpdir(self):
        with tempfile.TemporaryDirectory() as d:
            yield d

    def _orch(self, tmpdir):
        from shattering.orchestrator import ShatteringOrchestrator
        return ShatteringOrchestrator(
            manifest_path=DESKTOP_MANIFEST,
            base_dir=tmpdir,
            mode="local",
        )

    def test_init_with_manifest_path(self, tmpdir):
        orch = self._orch(tmpdir)
        assert orch is not None

    def test_init_with_manifest_object(self, tmpdir):
        from shattering.manifest import ManifestLoader
        from shattering.orchestrator import ShatteringOrchestrator
        ManifestLoader.invalidate_cache()
        m = ManifestLoader.load_from_file(DESKTOP_MANIFEST)
        orch = ShatteringOrchestrator(manifest=m, base_dir=tmpdir, mode="local")
        assert orch is not None

    def test_infer_returns_infer_result(self, tmpdir):
        from shattering.orchestrator import InferResult
        orch = self._orch(tmpdir)
        result = orch.infer("explain recursion")
        assert isinstance(result, InferResult)

    def test_infer_result_has_required_fields(self, tmpdir):
        orch = self._orch(tmpdir)
        result = orch.infer("write a python function")
        assert result.text
        assert result.sub_model in ("logos", "techne", "rhetor")
        assert 0.0 <= result.confidence <= 1.0
        assert result.latency_ms >= 0.0
        assert result.mode in ("local", "simulation", "distributed", "llama.cpp")
        assert result.route_reason

    def test_simulation_response_nonempty(self, tmpdir):
        orch = self._orch(tmpdir)
        result = orch.infer("hello world")
        assert len(result.text.strip()) > 0

    def test_route_only_matches_infer_sub_model(self, tmpdir):
        from shattering.router import RouteDecision
        orch = self._orch(tmpdir)
        prompt = "write a python function"
        decision = orch.route_only(prompt)
        infer_result = orch.infer(prompt)
        assert isinstance(decision, RouteDecision)
        # Routing decisions should be consistent
        assert decision.sub_model == infer_result.sub_model

    def test_status_returns_expected_keys(self, tmpdir):
        orch = self._orch(tmpdir)
        s = orch.status()
        assert "manifest" in s
        assert "mode" in s
        assert "fragments" in s
        assert "bundles" in s

    def test_status_manifest_id(self, tmpdir):
        orch = self._orch(tmpdir)
        s = orch.status()
        assert s["manifest"] == "cognia_desktop"
