"""
Regression test for the _distributed_infer / _local_infer tuple-arity bug.

Bug (fixed this session):
    `_distributed_infer` is contracted to return a 2-tuple `(text, mode)`, but its
    two fallback branches did `return self._local_infer(...)`, which returns a
    3-tuple `(text, mode, tokens)`. When the coordinator was unavailable,
    `infer()` did `text, mode_used = self._distributed_infer(...)` and raised
    `ValueError: too many values to unpack (expected 2)`.

Fix:
    Both fallbacks now do `text, mode, _ = self._local_infer(...); return text, mode`.

This test builds a minimal orchestrator DIRECTLY from the manifest (no full
`Cognia()` -> no mesh node / global singletons, so it is immune to cross-test
state pollution that made an earlier Cognia()-based version order-dependent).
`_local_infer` is stubbed to a deterministic 3-tuple so the test is fast and does
not spawn llama-server, while STILL exercising the real `_distributed_infer`
fallback path: if the fix is reverted, the 3-tuple reaches infer()'s 2-tuple
unpack and the test fails with the exact regression.
"""

import pytest

from shattering.orchestrator import InferResult, ShatteringOrchestrator

_MANIFEST = "shattering/manifests/cognia_desktop.json"


def test_distributed_fallback_no_unpack_crash():
    orch = ShatteringOrchestrator(manifest_path=_MANIFEST)

    # Force the distributed branch in infer(): mode == 'distributed' AND coord set.
    # Port 9 (discard) is unreachable -> pipeline.is_available() is False -> the
    # fallback-to-local branch fires (the branch that carried the arity bug).
    orch._mode = "distributed"
    orch._coord_url = "http://127.0.0.1:9"

    # Deterministic local inference: a real 3-tuple (text, mode, tokens), exactly
    # what _local_infer returns. The fallback MUST unpack it to 2 values.
    orch._local_infer = lambda prompt, decision, **kw: ("hola!", "simulation", 0)

    try:
        result = orch.infer("di hola")
    except ValueError as exc:
        if "too many values to unpack" in str(exc):
            pytest.fail(
                "Regression: _distributed_infer returned a 3-tuple from its "
                f"fallback branch -- {exc}"
            )
        raise

    assert isinstance(result, InferResult)
    assert result.text == "hola!"
    # Coordinator was unreachable, so the result is from the local fallback,
    # never the distributed backend.
    assert result.mode != "distributed"
