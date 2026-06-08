"""
tests/test_tp_engine.py
=======================
Phase 3a: full-model tensor-parallel generation (shattering/tp_engine.py).

Gate: a model whose every layer is split into T tensor-parallel ranks generates
the IDENTICAL greedy token sequence as the single-device reference, end-to-end
(embedding -> layer stack -> final norm -> lm_head -> argmax), including the
KV-cached decode steps. This proves a whole model — not just one layer — runs
split across ranks and produces the same output.

Run directly for the CHECK + in-process tok/s:
    venv312\\Scripts\\python.exe tests\\test_tp_engine.py
"""

from __future__ import annotations

import numpy as np

from node.qwen2_ops import RealTransformerLayer, INT4Weights
from shattering.tp_engine import (
    TPModelWeights, generate_reference, generate_tp, timed_generate_tp,
)


def _make_model(vocab: int, H: int, KH: int, D: int, inter: int, n_layers: int, seed: int) -> TPModelWeights:
    rng = np.random.default_rng(seed)
    hidden = H * D

    def w(out, inp, s=0.05):
        return INT4Weights.from_float32((rng.standard_normal((out, inp)) * s).astype(np.float32))

    layers = [
        RealTransformerLayer(
            n_heads=H, n_kv_heads=KH, head_dim=D, rope_theta=1_000_000.0, rms_norm_eps=1e-6,
            w_q=w(H * D, hidden), w_k=w(KH * D, hidden), w_v=w(KH * D, hidden), w_o=w(hidden, H * D),
            w_gate=w(inter, hidden), w_up=w(inter, hidden), w_down=w(hidden, inter),
            norm1=(1.0 + rng.standard_normal(hidden) * 0.05).astype(np.float32),
            norm2=(1.0 + rng.standard_normal(hidden) * 0.05).astype(np.float32),
        )
        for _ in range(n_layers)
    ]
    return TPModelWeights(
        embed=w(vocab, hidden), layers=layers,
        final_norm=(1.0 + rng.standard_normal(hidden) * 0.05).astype(np.float32),
        lm_head=w(vocab, hidden), rms_eps=1e-6,
    )


# KH=8 so the same model supports TP in {1,2,4,8}
_MODEL_ARGS = dict(vocab=512, H=16, KH=8, D=16, inter=256, n_layers=3, seed=21)
_PROMPT = [3, 17, 42, 8, 100]
_N_NEW = 10


def test_tp_generation_identical_t2():
    model = _make_model(**_MODEL_ARGS)
    ref = generate_reference(model, _PROMPT, _N_NEW)
    tp2 = generate_tp(model, _PROMPT, _N_NEW, tp_degree=2)
    assert tp2 == ref, f"T=2 diverged: {tp2} != {ref}"


def test_tp_generation_identical_t4():
    model = _make_model(**_MODEL_ARGS)
    ref = generate_reference(model, _PROMPT, _N_NEW)
    tp4 = generate_tp(model, _PROMPT, _N_NEW, tp_degree=4)
    assert tp4 == ref, f"T=4 diverged: {tp4} != {ref}"


def test_tp_generation_nontrivial():
    """Guard against a degenerate all-same-token sequence masking a real bug."""
    model = _make_model(**_MODEL_ARGS)
    ref = generate_reference(model, _PROMPT, _N_NEW)
    assert len(set(ref)) > 1


def _check():
    print("=== Phase 3a: full-model tensor-parallel generation ===")
    model = _make_model(**_MODEL_ARGS)
    ref = generate_reference(model, _PROMPT, _N_NEW)
    print(f"reference (single-device) tokens: {ref}")
    ok = True
    for T in (1, 2, 4, 8):
        ids, tps = timed_generate_tp(model, _PROMPT, _N_NEW, T)
        match = ids == ref
        ok = ok and match
        print(f"  TP={T}: tokens {'MATCH' if match else 'DIVERGE'}  "
              f"({tps:.1f} tok/s in-process, NOT the LAN thesis)")
    print(f"\nCHECK: {'PASS' if ok else 'FAIL'}")
    return ok


if __name__ == "__main__":
    import sys
    sys.exit(0 if _check() else 1)
