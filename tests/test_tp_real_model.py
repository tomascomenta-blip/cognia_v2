"""
tests/test_tp_real_model.py
===========================
Phase 3 real-weights regression: the TP engine on the actual Qwen2.5-Coder-3B
INT4 shards must generate the same greedy tokens as the single-device reference.

Heavy (loads ~1.5 GB, real 36-layer forward), so it is OPT-IN: it skips unless
COGNIA_TP_REAL_TEST=1 AND the shard directory is present. The primary real check
is scripts/tp_real_model_check.py; this just makes it reproducible in CI when the
weights are available.
"""

from __future__ import annotations

import os

import pytest

_SHARD_DIR = os.path.join("model_shards", "qwen-coder-3b-q4")
_ENABLED = os.environ.get("COGNIA_TP_REAL_TEST") == "1" and os.path.isdir(_SHARD_DIR)

pytestmark = pytest.mark.skipif(
    not _ENABLED,
    reason="set COGNIA_TP_REAL_TEST=1 and provide model_shards/qwen-coder-3b-q4 to run",
)


def test_tp_matches_reference_on_real_qwen_3b():
    from shattering.tp_engine import load_qwen_int4_model, generate_reference, generate_tp

    model = load_qwen_int4_model(_SHARD_DIR)
    assert len(model.layers) == 36

    prompt_ids = [40, 1234, 5, 99, 500, 71, 8]
    ref = generate_reference(model, prompt_ids, n_new=4, session_id="rt_ref")
    tp = generate_tp(model, prompt_ids, n_new=4, tp_degree=2, session_id="rt_tp")
    assert tp == ref, f"TP=2 diverged from reference on real weights: {tp} != {ref}"
