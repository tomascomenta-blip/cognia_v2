#!/usr/bin/env python3
"""Full shattering test battery. Run with: python scripts/test_shattering_full.py"""
import sys
import os
import time
import json
import asyncio

# Ensure repo root is on sys.path
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ".")

results = []


def test(name, fn):
    try:
        t0 = time.time()
        fn()
        ms = int((time.time() - t0) * 1000)
        results.append({"test": name, "status": "PASS", "ms": ms})
        print(f"  PASS  {name} ({ms}ms)")
    except Exception as e:
        results.append({"test": name, "status": "FAIL", "error": str(e)[:120]})
        print(f"  FAIL  {name}: {str(e)[:80]}")


# ── Test 1: core imports ──────────────────────────────────────────────────────
def t_imports():
    from shattering.orchestrator import ShatteringOrchestrator
    from shattering.router import GlobalRouter
    from shattering.fragment_manager import FragmentManager
    from coordinator.relay import RelayManager, InferenceSession
    from node.shard_engine import ShardEngine


# ── Test 2: router accuracy (lowercase output) ────────────────────────────────
def t_router():
    from shattering.router import GlobalRouter
    r = GlobalRouter()
    assert r.route("write a python function to sort a list").sub_model == "techne", \
        "Expected techne for coding prompt"
    assert r.route("explain the philosophy of consciousness").sub_model == "logos", \
        "Expected logos for philosophy prompt"
    assert r.route("write a poem about the sea").sub_model == "rhetor", \
        "Expected rhetor for creative writing prompt"


# ── Test 3: orchestrator creation + shards_available check ───────────────────
def t_shards_available():
    os.environ.setdefault("SHARD_WEIGHTS_DIR", "model_shards/qwen-coder-3b-q4")
    from shattering.orchestrator import ShatteringOrchestrator
    orch = ShatteringOrchestrator(manifest_path="shattering/manifests/cognia_desktop.json")
    # Must not raise; value depends on local shards
    result = orch._shards_available()
    assert isinstance(result, bool), "Expected bool from _shards_available()"


# ── Test 4: simulation inference (no weights, no llama.cpp) ──────────────────
def t_simulation():
    """Force simulation mode by pointing to a non-existent shard dir."""
    env_backup = os.environ.get("SHARD_WEIGHTS_DIR")
    try:
        os.environ["SHARD_WEIGHTS_DIR"] = "/nonexistent_shard_dir_ci_test"
        # Also temporarily hide the LLAMA_GGUF_PATH so llama.cpp is skipped
        gguf_backup = os.environ.pop("LLAMA_GGUF_PATH", None)
        try:
            from shattering.orchestrator import ShatteringOrchestrator
            from shattering.fragment_manager import FragmentManager
            # Re-import to clear cached state
            import importlib
            import shattering.orchestrator as _orch_mod
            importlib.reload(_orch_mod)
            from shattering.orchestrator import ShatteringOrchestrator as _Fresh
            orch = _Fresh(manifest_path="shattering/manifests/cognia_desktop.json")
            result = orch.infer("Say hello.")
            assert result is not None, "Expected non-None result"
            assert isinstance(result.text, str), "Expected string text"
            assert len(result.text) > 0, "Expected non-empty result text"
            print(f"      mode={result.mode}, text={result.text[:50]!r}")
        finally:
            if gguf_backup is not None:
                os.environ["LLAMA_GGUF_PATH"] = gguf_backup
    finally:
        if env_backup is not None:
            os.environ["SHARD_WEIGHTS_DIR"] = env_backup
        else:
            os.environ.pop("SHARD_WEIGHTS_DIR", None)


# ── Test 5: coordinator startup + health + node registration ─────────────────
def t_coordinator():
    import subprocess
    import urllib.request
    import urllib.error

    p = subprocess.Popen(
        [sys.executable, "coordinator/run.py"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        # Wait up to 12s for startup
        for _ in range(12):
            time.sleep(1)
            try:
                with urllib.request.urlopen("http://127.0.0.1:8001/health", timeout=2) as r:
                    data = json.loads(r.read())
                    assert data.get("ok") is True, f"Health check returned ok=False: {data}"
                    break
            except (urllib.error.URLError, OSError):
                pass
        else:
            raise RuntimeError("Coordinator did not start within 12s")

        # Test node registration
        reg_data = json.dumps({
            "node_id": "ci-test-node-001",
            "shards": [0],
            "endpoint": "http://127.0.0.1:9000",
            "contributor_token": "ci-test-token",
        }).encode()
        req = urllib.request.Request(
            "http://127.0.0.1:8001/api/node/register",
            data=reg_data,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                resp = json.loads(r.read())
                assert "node_id" in resp or "shard" in resp, \
                    f"Unexpected registration response: {resp}"
        except urllib.error.HTTPError as e:
            # 401/403 is acceptable if auth is required
            if e.code not in (401, 403):
                raise
    finally:
        p.terminate()
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()


# ── Test 6: llama.cpp backend detection ──────────────────────────────────────
def t_llama_detection():
    """Verify LlamaBackend.try_load() doesn't raise (returns None or backend)."""
    from node.llama_backend import LlamaBackend, _find_gguf
    gguf = _find_gguf()
    backend = LlamaBackend.try_load()
    if gguf is not None:
        assert backend is not None, f"GGUF found at {gguf} but backend is None"
        print(f"      backend={type(backend._impl).__name__}, gguf={gguf.name}")
    else:
        print("      No GGUF found, backend=None (OK for CI)")


# ── Test 7: shard engine real-mode loading ───────────────────────────────────
def t_shard_engine():
    """Load shard_0 if SHARD_WEIGHTS_DIR exists and contains shards."""
    import numpy as np
    from node.shard_engine import ShardEngine, ShardConfig
    from shattering.model_constants import QWEN25_CODER_3B

    shard_dir = os.environ.get("SHARD_WEIGHTS_DIR", "model_shards/qwen-coder-3b-q4")
    if not os.path.isfile(os.path.join(shard_dir, "shard_0.npz")) and \
       not os.path.isdir(os.path.join(shard_dir, "shard_0")):
        print("      No local shards found, skipping real-mode test")
        return

    cfg = QWEN25_CODER_3B
    shard_cfg = ShardConfig(
        model_name="qwen-coder-3b-q4", shard_index=0,
        n_shards=cfg["n_shards"], total_layers=cfg["total_layers"],
        hidden_dim=cfg["hidden_dim"], intermediate_dim=cfg["intermediate_dim"],
        n_heads=cfg["n_heads"], n_kv_heads=cfg["n_kv_heads"],
        head_dim=cfg["head_dim"], rope_theta=cfg["rope_theta"],
        rms_norm_eps=cfg["rms_norm_eps"], vocab_size=cfg["vocab_size"],
        eos_token_id=cfg["eos_token_id"],
    )
    engine = ShardEngine(shard_cfg, weights_path=shard_dir)
    assert engine.mode == "real", f"Expected mode=real, got mode={engine.mode}"

    # Run a dummy forward pass
    dummy = np.zeros((1, cfg["hidden_dim"]), dtype=np.float16)
    out = engine.forward(dummy)
    assert out is not None, "Forward pass returned None"
    print(f"      shard_0 mode=real, forward OK, out type={type(out).__name__}")


# ── Run all tests ─────────────────────────────────────────────────────────────

print("\n=== SHATTERING TEST BATTERY ===\n")
test("imports", t_imports)
test("router_accuracy", t_router)
test("shards_available_check", t_shards_available)
test("simulation_inference", t_simulation)
test("coordinator_startup", t_coordinator)
test("llama_detection", t_llama_detection)
test("shard_engine_real_mode", t_shard_engine)

# Summary
passed = sum(1 for r in results if r["status"] == "PASS")
total  = len(results)
print(f"\n=== RESULTS: {passed}/{total} PASSED ===")
for r in results:
    if r["status"] == "FAIL":
        print(f"  FAIL  {r['test']}: {r['error']}")

if passed < total:
    sys.exit(1)
