"""
tests/test_bdraft_model.py
==========================
Tests for bdraft/model.py (Cognia-BDraft, block-diffusion draft model).

All tests run on CPU with the mini config except the parameter-count test,
which builds the default config on the meta device (no RAM) with a CPU
fallback. bdraft is training-machine-only code (never runs on nodes), so
torch is an optional dependency of the repo: skip cleanly if missing.
"""

import pytest

torch = pytest.importorskip("torch")

import torch.nn as nn  # noqa: E402  (after importorskip on purpose)

from bdraft import BDraft, BDraftConfig  # noqa: E402


def _mini_inputs(cfg, batch=2, ctx_len=12, seed=0):
    g = torch.Generator().manual_seed(seed)
    ctx_hidden = torch.randn(batch, ctx_len, cfg.target_d_model, generator=g)
    canvas_tokens = torch.randint(0, cfg.vocab_size, (batch, cfg.block_size),
                                  generator=g)
    canvas_mask = torch.zeros(batch, cfg.block_size, dtype=torch.bool)
    canvas_mask[:, cfg.block_size // 2:] = True  # second half masked
    canvas_tokens[canvas_mask] = cfg.mask_token_id  # exercise the -1 sentinel
    return ctx_hidden, canvas_tokens, canvas_mask


def test_forward_shape_and_dtype():
    cfg = BDraftConfig.mini()
    model = BDraft(cfg)
    ctx_hidden, canvas_tokens, canvas_mask = _mini_inputs(cfg)
    logits = model(ctx_hidden, canvas_tokens, canvas_mask)
    assert logits.shape == (2, cfg.block_size, cfg.vocab_size)
    assert logits.is_floating_point()


def test_shared_target_modules_frozen_and_not_counted():
    cfg = BDraftConfig.mini()
    emb = nn.Embedding(cfg.vocab_size, cfg.target_d_model)
    head = nn.Linear(cfg.target_d_model, cfg.vocab_size, bias=False)
    model = BDraft(cfg, target_embedding=emb, target_lm_head=head)
    assert emb.weight.requires_grad is False
    assert head.weight.requires_grad is False
    shared = emb.weight.numel() + head.weight.numel()
    total = sum(p.numel() for p in model.parameters())
    assert model.num_trainable_params() == total - shared
    # Cross-check vs a model that owns (trainable) embedding + head.
    own = BDraft(cfg)
    assert own.num_trainable_params() == model.num_trainable_params() + shared


def test_bidirectional_attention_inside_block():
    # Changing the token at the LAST canvas position must alter the logits at
    # the FIRST position (both unmasked) — impossible under a causal mask.
    cfg = BDraftConfig.mini()
    torch.manual_seed(1)
    model = BDraft(cfg)
    model.eval()
    ctx_hidden, canvas_tokens, _ = _mini_inputs(cfg, seed=1)
    canvas_mask = torch.zeros_like(canvas_tokens, dtype=torch.bool)  # all given
    canvas_tokens = canvas_tokens.clamp_min(0)
    variant = canvas_tokens.clone()
    variant[:, -1] = (variant[:, -1] + 1) % cfg.vocab_size
    with torch.no_grad():
        base = model(ctx_hidden, canvas_tokens, canvas_mask)
        changed = model(ctx_hidden, variant, canvas_mask)
    assert not torch.allclose(base[:, 0], changed[:, 0])


def test_ctx_hidden_conditions_the_logits():
    # The context reaches the canvas via the K/V injection: perturbing
    # ctx_hidden must change the output.
    cfg = BDraftConfig.mini()
    torch.manual_seed(2)
    model = BDraft(cfg)
    model.eval()
    ctx_hidden, canvas_tokens, canvas_mask = _mini_inputs(cfg, seed=2)
    with torch.no_grad():
        base = model(ctx_hidden, canvas_tokens, canvas_mask)
        changed = model(ctx_hidden + 1.0, canvas_tokens, canvas_mask)
    assert not torch.allclose(base, changed)


def test_confidence_shape_and_range():
    cfg = BDraftConfig.mini()
    model = BDraft(cfg)
    ctx_hidden, canvas_tokens, canvas_mask = _mini_inputs(cfg)
    with torch.no_grad():
        hidden = model.forward_hidden(ctx_hidden, canvas_tokens, canvas_mask)
        conf = model.confidence(hidden)
    assert conf.shape == (2, cfg.block_size)
    assert torch.all(conf >= 0.0) and torch.all(conf <= 1.0)


def test_default_config_trainable_params_in_budget():
    # Doc section 2.2: trainable core ~110M. Build on the meta device so the
    # 152K x 3584 embedding/head cost no RAM; fall back to CPU if meta fails.
    cfg = BDraftConfig()
    try:
        with torch.device("meta"):
            emb = nn.Embedding(cfg.vocab_size, cfg.target_d_model)
            head = nn.Linear(cfg.target_d_model, cfg.vocab_size, bias=False)
            model = BDraft(cfg, target_embedding=emb, target_lm_head=head)
    except (RuntimeError, NotImplementedError):
        emb = nn.Embedding(cfg.vocab_size, cfg.target_d_model)
        head = nn.Linear(cfg.target_d_model, cfg.vocab_size, bias=False)
        model = BDraft(cfg, target_embedding=emb, target_lm_head=head)
    n = model.num_trainable_params()
    assert 80_000_000 <= n <= 140_000_000, "trainable params = %d" % n
