"""
tests/test_bdraft_train.py
==========================
Tests for bdraft/data.py, bdraft/train.py and bdraft/gates.py.

All CPU with the mini config. bdraft is training-machine-only code (never
runs on nodes), so torch is an optional dependency: skip cleanly if missing.
"""

import pytest

torch = pytest.importorskip("torch")

import torch.nn.functional as F  # noqa: E402  (after importorskip on purpose)

from bdraft import BDraft, BDraftConfig  # noqa: E402
from bdraft.data import (build_synthetic_dataset, make_canvas_batch,  # noqa: E402
                         sample_mask_ratio)
from bdraft.gates import (G2_TECHO_MIN, g2_techo, g3_early_signal,  # noqa: E402
                          g4_final)
from bdraft.train import (chunked_cross_entropy, exp_position_weights,  # noqa: E402
                          train_loop)


def test_make_canvas_batch_shapes_ratio_labels_determinism():
    B, S, block = 4, 32, 8
    g = torch.Generator().manual_seed(7)
    token_ids = torch.randint(0, 512, (B, S), generator=g)

    g1 = torch.Generator().manual_seed(123)
    batch = make_canvas_batch(token_ids, block, g1)
    T = batch["ctx_tokens"].shape[1]
    assert 1 <= T <= S - block
    assert batch["ctx_tokens"].shape == (B, T)
    assert batch["canvas_tokens"].shape == (B, block)
    assert batch["canvas_mask"].shape == (B, block)
    assert batch["canvas_mask"].dtype == torch.bool
    assert batch["labels"].shape == (B, block)
    # Context and labels come straight from the source sequence at the cut.
    assert torch.equal(batch["ctx_tokens"], token_ids[:, :T])
    assert torch.equal(batch["labels"], token_ids[:, T:T + block])
    # Masked positions carry the -1 sentinel, given positions the true token.
    mask = batch["canvas_mask"]
    assert torch.all(batch["canvas_tokens"][mask] == -1)
    assert torch.equal(batch["canvas_tokens"][~mask], batch["labels"][~mask])
    # Mask ratio ~ t: same count per row, count = max(1, round(t*block)).
    t = batch["mask_ratio"]
    assert 0.0 < t < 1.0
    per_row = mask.sum(dim=1)
    assert torch.all(per_row == per_row[0]) and per_row[0].item() >= 1
    assert abs(mask.float().mean().item() - t) <= 0.5 / block + 1.0 / block
    # Deterministic with a seeded generator.
    g2 = torch.Generator().manual_seed(123)
    again = make_canvas_batch(token_ids, block, g2)
    for key in ("ctx_tokens", "canvas_tokens", "canvas_mask", "labels"):
        assert torch.equal(batch[key], again[key])
    assert again["mask_ratio"] == t


def test_sample_mask_ratio_in_open_interval():
    g = torch.Generator().manual_seed(0)
    for _ in range(100):
        t = sample_mask_ratio(g)
        assert 0.0 < t < 1.0


def test_chunked_cross_entropy_matches_naive():
    g = torch.Generator().manual_seed(3)
    N, d, V = 20, 16, 64
    hidden = torch.randn(N, d, generator=g)
    weight = torch.randn(V, d, generator=g)
    labels = torch.randint(0, V, (N,), generator=g)
    naive = F.cross_entropy(hidden @ weight.T, labels)
    # chunk_size < N forces multiple chunks.
    chunked = chunked_cross_entropy(hidden, weight, labels, chunk_size=7)
    assert torch.allclose(chunked, naive, atol=1e-5)
    # Weighted case: weighted mean sum(w*ce)/sum(w).
    w = torch.rand(N, generator=g) + 0.1
    ce_none = F.cross_entropy(hidden @ weight.T, labels, reduction="none")
    naive_w = (ce_none * w).sum() / w.sum()
    chunked_w = chunked_cross_entropy(hidden, weight, labels, chunk_size=7,
                                      pos_weights=w)
    assert torch.allclose(chunked_w, naive_w, atol=1e-5)


def test_exp_position_weights_decreasing_positive():
    block = 8
    w = exp_position_weights(block)
    assert w.shape == (block,)
    assert torch.all(w > 0)
    assert torch.all(w[1:] < w[:-1])  # strictly decreasing
    assert torch.allclose(w, 0.8 ** torch.arange(block, dtype=torch.float32))


def test_synthetic_dataset_deterministic_and_structured():
    cfg = BDraftConfig.mini()
    ds1 = build_synthetic_dataset(cfg, n_samples=32, seed=5)
    ds2 = build_synthetic_dataset(cfg, n_samples=32, seed=5)
    assert torch.equal(ds1, ds2)
    assert ds1.shape == (32, 4 * cfg.block_size)
    assert ds1.min() >= 0 and ds1.max() < cfg.vocab_size
    # Periodic structure (period 4): each row repeats its motif exactly.
    assert torch.equal(ds1[:, 4:], ds1[:, :-4])


def test_overfit_synthetic_mini():
    # THE key test: the full pipeline must actually learn. Mini config +
    # periodic synthetic data, 200 steps of AdamW at 3e-3 on CPU.
    cfg = BDraftConfig.mini()
    torch.manual_seed(0)
    model = BDraft(cfg)
    dataset = build_synthetic_dataset(cfg, n_samples=256, seed=0)
    losses = train_loop(model, dataset, steps=200, lr=3e-3, device="cpu",
                        log_every=0)
    assert len(losses) == 200
    assert losses[-1] < 0.5 * losses[0], \
        "no learning: initial %.4f final %.4f" % (losses[0], losses[-1])


def test_g2_techo():
    # Doc example: t_ciclo 0.1 s, base token 0.025 s, block 8 -> ceiling 2.0.
    techo, pasa = g2_techo(0.1, 0.025, block_size=8)
    assert abs(techo - 2.0) < 1e-9
    assert pasa is True
    # Fast target (4 ms/token): ceiling 0.4 -> KILL, same math as the CPU era.
    techo, pasa = g2_techo(0.1, 0.005, block_size=8)
    assert abs(techo - 0.4) < 1e-9
    assert pasa is False
    # Threshold is inclusive: ceiling exactly 1.5 passes.
    techo, pasa = g2_techo(0.1, G2_TECHO_MIN / 8 * 0.1, block_size=8)
    assert abs(techo - G2_TECHO_MIN) < 1e-9
    assert pasa is True


def test_g3_early_signal_edges():
    assert g3_early_signal(0.30, 1.5) is True     # both exactly at threshold
    assert g3_early_signal(0.299, 1.5) is False   # top1 just below
    assert g3_early_signal(0.30, 1.49) is False   # tau just below
    assert g3_early_signal(0.5, 3.0) is True


def test_g4_final_edges():
    # Everything exactly at threshold: all sub-gates pass.
    v = g4_final(tau_code=2.5, tau_chat=1.8, speedup_rel=1.8, speedup_abs=1.2)
    assert v == {"g4a_tau_code": True, "g4a_tau_chat": True, "g4a": True,
                 "g4b_rel": True, "g4b_abs": True, "g4b": True, "pasa": True}
    # One sub-metric just under its floor flips its sub-gate and the verdict.
    v = g4_final(tau_code=2.49, tau_chat=1.8, speedup_rel=1.8, speedup_abs=1.2)
    assert v["g4a_tau_code"] is False and v["g4a"] is False
    assert v["g4b"] is True and v["pasa"] is False
    v = g4_final(tau_code=2.5, tau_chat=1.8, speedup_rel=1.8, speedup_abs=1.19)
    assert v["g4b_abs"] is False and v["g4b"] is False
    assert v["g4a"] is True and v["pasa"] is False
