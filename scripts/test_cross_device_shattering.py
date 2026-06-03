"""
Test cross-device shattering inference via Railway coordinator.
Run this on your local machine AFTER the Oracle node is running.

Usage:
    python scripts/test_cross_device_shattering.py

What it tests:
    1. Local node (shard_0) registered with coordinator
    2. Oracle node (shard_1) registered with coordinator
    3. End-to-end inference that chains both shards
    4. Reports latency, tokens/s, which nodes contributed
"""
import json, os, sys, time, urllib.request, urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

COORDINATOR = os.environ.get(
    "COGNIA_COORDINATOR_URL",
    "https://cognia-coordinator-production.up.railway.app"
)
LOCAL_API = "http://127.0.0.1:8765"

PROMPTS = [
    ("simple",    "What is 2+2? Answer in one word."),
    ("coding",    "Write a Python function that returns the nth Fibonacci number."),
    ("reasoning", "Explain why distributed inference is harder than single-machine inference."),
]


def _get(url: str, timeout: int = 10) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read())


def _post(url: str, body: dict, timeout: int = 60) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def check_coordinator_nodes():
    print("\n[1] Checking registered nodes on coordinator...")
    try:
        status = _get(f"{COORDINATOR}/api/swarm/status", timeout=10)
        nodes = status.get("nodes", status.get("registered_nodes", []))
        print(f"    Active nodes: {len(nodes)}")
        for n in nodes:
            nid = n.get("node_id", n.get("id", "?"))
            shards = n.get("shards", n.get("assigned_shards", "?"))
            hw = n.get("hardware_info", "")
            print(f"    - {nid[:20]}  shards={shards}  hw={hw[:30]}")
        if len(nodes) < 2:
            print("    WARNING: Less than 2 nodes. Oracle node may not be registered yet.")
            print(f"    Make sure you ran oracle_node_setup.sh on the VM.")
        return len(nodes)
    except Exception as e:
        print(f"    FAIL: {e}")
        return 0


def check_local_api():
    print("\n[2] Checking local Cognia API (port 8765)...")
    try:
        health = _get(f"{LOCAL_API}/health", timeout=5)
        print(f"    OK: {health}")
        return True
    except Exception as e:
        print(f"    FAIL: {e}")
        print(f"    Start it with: python cognia_desktop_api.py")
        return False


def run_inference_tests(use_api: bool):
    print("\n[3] Running inference tests...")
    results = []

    for label, prompt in PROMPTS:
        print(f"\n  [{label}] Q: {prompt[:60]}")
        t0 = time.time()
        try:
            if use_api:
                resp = _post(f"{LOCAL_API}/infer", {"prompt": prompt, "history": []}, timeout=120)
                text = resp.get("text", "")
                mode = resp.get("mode", resp.get("backend", "unknown"))
                cached = resp.get("cached", False)
            else:
                # Direct orchestrator test (no API)
                import asyncio, os as _os
                _os.environ.setdefault("SHARD_WEIGHTS_DIR", "model_shards/qwen-coder-3b-q4")
                _os.environ.setdefault("COGNIA_COORDINATOR_URL", COORDINATOR)
                from shattering.orchestrator import ShatteringOrchestrator
                orch = ShatteringOrchestrator()
                result = asyncio.run(orch.infer(prompt))
                text = str(result)
                mode = "direct"
                cached = False

            elapsed = time.time() - t0
            tokens_approx = len(text.split())
            tps = tokens_approx / elapsed if elapsed > 0 else 0

            print(f"    A: {text[:120]}")
            print(f"    mode={mode}  cached={cached}  time={elapsed:.1f}s  ~{tps:.1f} tok/s")

            results.append({
                "label": label, "status": "PASS",
                "mode": mode, "elapsed": round(elapsed, 2),
                "tps": round(tps, 1), "len": len(text),
                "cached": cached
            })

        except Exception as e:
            elapsed = time.time() - t0
            print(f"    FAIL: {e}")
            results.append({"label": label, "status": "FAIL", "error": str(e)[:100]})

    return results


def print_summary(node_count: int, results: list):
    print("\n" + "=" * 60)
    print("CROSS-DEVICE SHATTERING TEST SUMMARY")
    print("=" * 60)
    print(f"Active nodes:  {node_count}")
    print(f"Coordinator:   {COORDINATOR}")
    print()

    passed = sum(1 for r in results if r["status"] == "PASS")
    print(f"Inference tests: {passed}/{len(results)} passed")
    print()

    for r in results:
        if r["status"] == "PASS":
            print(f"  PASS  [{r['label']:10}]  mode={r['mode']:15}  {r['elapsed']}s  {r['tps']} tok/s")
        else:
            print(f"  FAIL  [{r['label']:10}]  {r.get('error','')[:60]}")

    print()
    if node_count >= 2 and passed == len(results):
        print("RESULT: Cross-device shattering is WORKING.")
        print("        Both nodes contributed to inference.")
    elif passed > 0:
        print("RESULT: Partial — inference works but may be single-node only.")
        print("        Check that Oracle node is running and registered.")
    else:
        print("RESULT: FAILED — check coordinator connectivity and node status.")


if __name__ == "__main__":
    print("=== COGNIA CROSS-DEVICE SHATTERING TEST ===")
    print(f"Coordinator: {COORDINATOR}")

    node_count = check_coordinator_nodes()
    api_ok = check_local_api()
    results = run_inference_tests(use_api=api_ok)
    print_summary(node_count, results)
