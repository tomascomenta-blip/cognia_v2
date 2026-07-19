"""
tests/test_bdraft_real.py
=========================
Tests for bdraft/gen_dataset.py (Spanish templates, prompt plan, resume),
bdraft/real_data.py (build_example, RealBatcher, split) and
bdraft/train_real.py (compute_tau as a pure function).

All CPU, no network, no GPU (repo pattern: tmp_path + importorskip). The
tokenizer is a minimal PreTrainedTokenizerFast (WordLevel + Whitespace) so
no model files are needed.
"""

import json

import pytest

torch = pytest.importorskip("torch")

from bdraft.gen_dataset import (SPANISH_TEMPLATES, build_prompt_plan,  # noqa: E402
                                build_spanish_prompts, resume_point)
from bdraft.model import BDraft, BDraftConfig  # noqa: E402
from bdraft.real_data import (RealBatcher, build_example, chatml_prompt,  # noqa: E402
                              load_pairs, split_pairs)
from bdraft.train_real import compute_tau, warmup_lr  # noqa: E402


# ---------------------------------------------------------------------------
# Tiny tokenizer (no network, no model files)
# ---------------------------------------------------------------------------

def _tiny_tokenizer():
    pytest.importorskip("tokenizers", reason="tokenizers not installed")
    transformers = pytest.importorskip(
        "transformers", reason="transformers not installed")
    from tokenizers import Tokenizer
    from tokenizers.models import WordLevel
    from tokenizers.pre_tokenizers import Whitespace
    words = ("hola como estas muy bien gracias por preguntar explica que es "
             "la vida el de un una en y a para con historia respuesta larga "
             "texto palabras repetidas siempre").split()
    vocab = {"[UNK]": 0, "[PAD]": 1}
    for w in words + [str(i) for i in range(10)]:
        vocab.setdefault(w, len(vocab))
    tok = Tokenizer(WordLevel(vocab, unk_token="[UNK]"))
    tok.pre_tokenizer = Whitespace()
    return transformers.PreTrainedTokenizerFast(
        tokenizer_object=tok, unk_token="[UNK]", pad_token="[PAD]")


def _pairs(n=40):
    resp = "hola como estas muy bien gracias por preguntar " \
           "texto palabras repetidas siempre "
    return [{"prompt": "explica que es la vida %d" % i,
             "respuesta": (resp * 3).strip()} for i in range(n)]


# ---------------------------------------------------------------------------
# gen_dataset: templates, plan, resume
# ---------------------------------------------------------------------------

def test_spanish_templates_deterministic_and_realistic():
    assert len(SPANISH_TEMPLATES) >= 30
    a = build_spanish_prompts(60, seed=3)
    b = build_spanish_prompts(60, seed=3)
    c = build_spanish_prompts(60, seed=4)
    assert a == b                      # deterministic per seed
    assert a != c                      # seed actually matters
    assert len(a) == 60
    for p in a:
        assert isinstance(p, str) and len(p) >= 20
        assert "lorem" not in p.lower()
        assert "{" not in p and "}" not in p   # every slot got filled
        assert len(p.split()) >= 4             # realistic, not a stub
    assert len(set(a)) >= 30           # varied, not one template repeated


def test_build_prompt_plan_mix_and_determinism():
    code = ["code prompt %d" % i for i in range(50)]
    plan1 = build_prompt_plan(20, seed=0, code_prompts=code)
    plan2 = build_prompt_plan(20, seed=0, code_prompts=code)
    assert plan1 == plan2
    assert len(plan1) == 20
    code_set = set(code)
    # Position i is code iff i % 5 < 3 -> exactly 60% code / 40% Spanish.
    for i, p in enumerate(plan1):
        assert (p in code_set) == (i % 5 < 3)
    assert sum(p in code_set for p in plan1) == 12


def test_resume_point_counts_lines(tmp_path):
    out = tmp_path / "v0.jsonl"
    assert resume_point(out) == 0      # missing file -> start at 0
    with open(out, "w", encoding="utf-8") as f:
        for i in range(5):
            f.write(json.dumps({"prompt": "p%d" % i, "respuesta": "r" * 30},
                               ensure_ascii=False) + "\n")
    assert resume_point(out) == 5      # 5 lines -> resume at plan index 5
    # A resumed run processes plan[5:] of the SAME deterministic plan.
    code = ["code prompt %d" % i for i in range(50)]
    plan = build_prompt_plan(10, seed=1, code_prompts=code)
    assert plan[resume_point(out):] == plan[5:]


# ---------------------------------------------------------------------------
# real_data: build_example, RealBatcher, split
# ---------------------------------------------------------------------------

def test_build_example_cut_always_inside_response():
    tok = _tiny_tokenizer()
    pairs = _pairs(10)
    g = torch.Generator().manual_seed(0)
    seq_len, block = 128, 8
    n_built = 0
    for _ in range(6):
        for pair in pairs:
            ex = build_example(tok, pair, seq_len, block, g)
            assert ex is not None
            n_built += 1
            prompt_len = len(tok.encode(chatml_prompt(pair["prompt"]),
                                        add_special_tokens=False))
            assert ex["prompt_len"] == prompt_len
            # The cut is NEVER inside the prompt: the whole canvas is
            # response tokens.
            assert ex["cut"] >= prompt_len
            assert len(ex["ctx_ids"]) == ex["cut"]
            assert ex["cut"] + block <= seq_len
            # Labels are exactly the block after the cut in the full stream.
            ids = (tok.encode(chatml_prompt(pair["prompt"]),
                              add_special_tokens=False)
                   + tok.encode(pair["respuesta"] + "<|im_end|>",
                                add_special_tokens=False))[:seq_len]
            assert ex["labels"].tolist() == ids[ex["cut"]:ex["cut"] + block]
            mask = ex["canvas_mask"]
            assert mask.sum().item() >= 1
            assert torch.all(ex["canvas_tokens"][mask] == -1)
            assert torch.equal(ex["canvas_tokens"][~mask], ex["labels"][~mask])
    assert n_built == 60


def test_build_example_mask_ratio_varies():
    tok = _tiny_tokenizer()
    pair = _pairs(1)[0]
    g = torch.Generator().manual_seed(7)
    counts = {build_example(tok, pair, 128, 8, g)["canvas_mask"].sum().item()
              for _ in range(60)}
    assert len(counts) >= 3            # t ~ U(0,1): mask count truly varies


def test_real_batcher_shapes_padding_and_determinism():
    tok = _tiny_tokenizer()
    pairs = _pairs(40)
    rb = RealBatcher(tok, pairs, seq_len=128, block_size=8, micro_batch=4,
                     seed=0)
    batches = list(iter(rb))
    assert len(batches) == 10          # 40 valid pairs / micro_batch 4
    for batch in batches:
        B, T = batch["ctx_tokens"].shape
        assert B == 4 and T >= 1
        assert batch["ctx_tokens"].dtype == torch.long
        assert batch["ctx_attn"].shape == (B, T)
        assert batch["ctx_attn"].dtype == torch.bool
        # LEFT padding: once attention turns True it stays True.
        attn_int = batch["ctx_attn"].long()
        assert torch.all(attn_int[:, :-1] <= attn_int[:, 1:])
        assert torch.all(batch["ctx_attn"].any(dim=1))
        assert batch["canvas_tokens"].shape == (B, 8)
        assert batch["canvas_mask"].shape == (B, 8)
        assert batch["labels"].shape == (B, 8)
        assert torch.all(batch["canvas_mask"].sum(dim=1) >= 1)
        m = batch["canvas_mask"]
        assert torch.all(batch["canvas_tokens"][m] == -1)
        assert torch.equal(batch["canvas_tokens"][~m], batch["labels"][~m])
        # Pad id fell back to the declared [PAD] token.
        pad_zone = ~batch["ctx_attn"]
        if pad_zone.any():
            assert torch.all(batch["ctx_tokens"][pad_zone] == tok.pad_token_id)
    # Fresh instance, same seed -> identical first batch.
    rb2 = RealBatcher(tok, pairs, seq_len=128, block_size=8, micro_batch=4,
                      seed=0)
    first2 = next(iter(rb2))
    for key in ("ctx_tokens", "ctx_attn", "canvas_tokens", "canvas_mask",
                "labels"):
        assert torch.equal(batches[0][key], first2[key])
    # Second epoch reshuffles (epoch counter advances the stream).
    second_epoch_first = next(iter(rb))
    assert not all(torch.equal(batches[0][k], second_epoch_first[k])
                   for k in ("ctx_tokens", "labels"))


def test_batcher_skips_too_short_responses():
    tok = _tiny_tokenizer()
    pairs = [{"prompt": "hola", "respuesta": "bien"}] * 8   # < block tokens
    rb = RealBatcher(tok, pairs, seq_len=128, block_size=8, micro_batch=4,
                     seed=0)
    assert list(iter(rb)) == []


def test_load_pairs_and_split_no_leak(tmp_path):
    path = tmp_path / "v0.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        for i in range(800):
            row = {"prompt": "prompt unico %d" % i, "respuesta": "r" * 30}
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.write(json.dumps(row, ensure_ascii=False) + "\n")  # duplicate
        f.write("\n")                       # blank line: ignored
        f.write("{bad json")                # truncated line: ignored
    pairs = load_pairs(path)
    assert len(pairs) == 1600
    train, val = split_pairs(pairs)
    assert len(train) + len(val) == 1600
    train_prompts = {p["prompt"] for p in train}
    val_prompts = {p["prompt"] for p in val}
    # NO leakage: a prompt (even duplicated) is never on both sides.
    assert not (train_prompts & val_prompts)
    # ~2% of 800 unique prompts on val, and never zero/degenerate.
    assert 1 <= len(val_prompts) <= 48
    # Deterministic across calls.
    train2, val2 = split_pairs(pairs)
    assert [p["prompt"] for p in val2] == [p["prompt"] for p in val]


# ---------------------------------------------------------------------------
# model: ctx_attn padding mask correctness
# ---------------------------------------------------------------------------

def test_ctx_attn_left_padding_matches_unpadded():
    # RoPE is relative: left-padding the context and masking the pads must
    # give the same logits as the unpadded forward (this is exactly what
    # RealBatcher + BDraft(ctx_attn=...) rely on).
    cfg = BDraftConfig.mini()
    torch.manual_seed(0)
    model = BDraft(cfg).eval()
    g = torch.Generator().manual_seed(1)
    T, pad = 5, 3
    ctx = torch.randn(1, T, cfg.target_d_model, generator=g)
    labels = torch.randint(0, cfg.vocab_size, (1, cfg.block_size),
                           generator=g)
    mask = torch.zeros(1, cfg.block_size, dtype=torch.bool)
    mask[0, :4] = True
    canvas = labels.clone()
    canvas[mask] = -1
    with torch.no_grad():
        ref = model(ctx, canvas, mask)
        # ctx_attn all-True on the unpadded input == no mask at all.
        same = model(ctx, canvas, mask,
                     ctx_attn=torch.ones(1, T, dtype=torch.bool))
        garbage = 5.0 * torch.randn(1, pad, cfg.target_d_model, generator=g)
        padded_ctx = torch.cat([garbage, ctx], dim=1)
        attn = torch.cat([torch.zeros(1, pad, dtype=torch.bool),
                          torch.ones(1, T, dtype=torch.bool)], dim=1)
        out = model(padded_ctx, canvas, mask, ctx_attn=attn)
    assert torch.allclose(ref, same, atol=1e-5)
    assert torch.allclose(ref, out, atol=1e-3), \
        "padded+masked forward diverges: max diff %.2e" % (ref - out).abs().max()


# ---------------------------------------------------------------------------
# train_real: compute_tau (pure) + warmup
# ---------------------------------------------------------------------------

def test_compute_tau_pure_cases():
    full = list(range(8))
    assert compute_tau([full], [full]) == 8.0                     # match total
    nomatch = [99] + full[1:]
    assert compute_tau([nomatch], [full]) == 0.0                  # sin match
    prefix3 = full[:3] + [77] + full[4:]
    assert compute_tau([prefix3], [full]) == 3.0                  # prefijo 3
    # A later match after the first mismatch must NOT count (prefix, not sum).
    scattered = [full[0], 88, full[2], full[3], 88, full[5], 88, full[7]]
    assert compute_tau([scattered], [full]) == 1.0
    # Batch: mean over rows; tensors accepted too.
    assert compute_tau(torch.tensor([full, nomatch]),
                       torch.tensor([full, full])) == 4.0
    # 1-D convenience.
    assert compute_tau(full, full) == 8.0


def test_warmup_lr_linear_then_constant():
    assert warmup_lr(6e-4, 0, 200) == pytest.approx(6e-4 / 200)
    assert warmup_lr(6e-4, 99, 200) == pytest.approx(6e-4 * 100 / 200)
    assert warmup_lr(6e-4, 200, 200) == 6e-4
    assert warmup_lr(6e-4, 10_000, 200) == 6e-4
    assert warmup_lr(6e-4, 0, 0) == 6e-4
