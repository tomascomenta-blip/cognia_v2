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
from types import SimpleNamespace

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


def test_sesgo_de_mascara_lleva_el_regimen_de_inferencia_al_entrenamiento():
    """Con U(0,1) y bloque 8, round(8t)==8 solo si t>=0.9375: apenas el 6.25%
    de los ejemplos entrena el canvas completo, que es el UNICO regimen que usa
    la inferencia. Este es el desajuste que el reintento de G3 ataca."""
    from bdraft.data import sample_mask_ratio

    def fraccion_completa(prob, n=20000):
        g = torch.Generator().manual_seed(7)
        completos = sum(1 for _ in range(n)
                        if max(1, int(round(sample_mask_ratio(g, prob) * 8))) == 8)
        return completos / n

    # El comportamiento del v0 (defecto): ~6.25%.
    assert fraccion_completa(0.0) == pytest.approx(0.0625, abs=0.01)
    # Sesgado a la mitad: ~53% (el 50% forzado mas el 6.25% del resto).
    assert fraccion_completa(0.5) == pytest.approx(0.53, abs=0.02)
    # Y sigue habiendo variedad de niveles de ruido, no colapsa a t=1 siempre.
    g = torch.Generator().manual_seed(7)
    ts = [sample_mask_ratio(g, 0.5) for _ in range(2000)]
    assert len(set(round(t, 3) for t in ts)) > 500
    # El defecto no cambia nada de lo pre-registrado.
    g1 = torch.Generator().manual_seed(3)
    g2 = torch.Generator().manual_seed(3)
    assert [sample_mask_ratio(g1) for _ in range(50)] == \
           [sample_mask_ratio(g2, 0.0) for _ in range(50)]


def test_veredicto_indeciso_solo_cuando_la_decision_puede_darse_vuelta():
    """El caso real del run v0: tau fallo por 14x su barra de error mientras
    top1 quedaba pegado a 0.30, y un OR ingenuo lo reportaba como indecidible.
    El gate es un AND: si una metrica falla sin margen, no hay indecision."""
    from bdraft.train_real import veredicto_indeciso

    # El veredicto real del run v0: FAIL inequivoco, no indeciso.
    assert veredicto_indeciso(0.2667, 0.311, 0.0646, 0.082) is False
    # Las dos fallando pero las dos dentro del ruido: ahi si es indeciso.
    assert veredicto_indeciso(0.28, 1.45, 0.05, 0.10) is True
    # Aprueba pero una esta pegada al umbral: podria estar fallando.
    assert veredicto_indeciso(0.31, 1.9, 0.05, 0.10) is True
    # Aprueba con holgura en las dos: decision firme.
    assert veredicto_indeciso(0.55, 3.0, 0.04, 0.10) is False
    # Falla sin margen en las dos: decision firme.
    assert veredicto_indeciso(0.05, 0.10, 0.02, 0.03) is False


def test_lr_coseno_calienta_y_despues_decae():
    """El schedule que el run v0 NO tenia: warmup y despues coseno.

    El v0 corrio a 6e-4 constante y su loss se planto en ~6.03 (paso 2000) y
    despues subio a 6.69, con top1 y tau en meseta. Este es el arreglo que el
    reintento pre-registrado tiene reservado.
    """
    from bdraft.train_real import lr_coseno

    base, warm = 6e-4, 200
    # Durante el warmup se comporta igual que el schedule viejo.
    assert lr_coseno(base, 0, warm, 0.0) == pytest.approx(base / warm)
    assert lr_coseno(base, 99, warm, 0.0) == pytest.approx(base * 100 / warm)
    # Al terminar el warmup esta en el pico...
    assert lr_coseno(base, warm, warm, 0.0) == pytest.approx(base)
    # ...a mitad del presupuesto, a mitad de camino entre el pico y el minimo...
    medio = lr_coseno(base, 1000, warm, 0.5)
    assert medio == pytest.approx(base * (0.1 + 0.9 * 0.5))
    # ...y al agotarlo, en el 10% del pico.
    assert lr_coseno(base, 5000, warm, 1.0) == pytest.approx(base * 0.1)
    # Monotono decreciente despues del warmup: nunca vuelve a subir.
    valores = [lr_coseno(base, 1000, warm, p / 20) for p in range(21)]
    assert all(a >= b for a, b in zip(valores, valores[1:]))
    # Un progreso fuera de rango no rompe ni dispara el lr.
    assert lr_coseno(base, 1000, warm, 1.5) == pytest.approx(base * 0.1)
    assert lr_coseno(base, 1000, warm, -0.3) == pytest.approx(base)


def test_warmup_lr_linear_then_constant():
    assert warmup_lr(6e-4, 0, 200) == pytest.approx(6e-4 / 200)
    assert warmup_lr(6e-4, 99, 200) == pytest.approx(6e-4 * 100 / 200)
    assert warmup_lr(6e-4, 200, 200) == 6e-4
    assert warmup_lr(6e-4, 10_000, 200) == 6e-4
    assert warmup_lr(6e-4, 0, 0) == 6e-4


# ---------------------------------------------------------------------------
# train_real: run_eval mide tau bajo verificacion greedy REAL
#
# Regresion del bug encontrado en la auditoria: target_eval_forward se llamaba
# con los LABELS del dataset, asi que el argmax del target quedaba condicionado
# a una muestra T=0.7 en vez de al prefijo que el draft realmente propuso. Solo
# la posicion 0 quedaba bien medida; las 1..7 —las que deciden tau >= 1.5— se
# comparaban contra una continuacion que el stream aceptado nunca contuvo.
# ---------------------------------------------------------------------------

class _FakeTargetBase(torch.nn.Module):
    """hidden[i] = one_hot(token[i]), de modo que el argmax del target sea
    siempre 'el token anterior + 1': una continuacion greedy predecible."""

    def __init__(self, vocab):
        super().__init__()
        self.vocab = vocab

    def forward(self, input_ids=None, attention_mask=None, position_ids=None,
                use_cache=False):
        h = torch.nn.functional.one_hot(input_ids, self.vocab).float()
        return SimpleNamespace(last_hidden_state=h)


class _FakeTarget(torch.nn.Module):
    def __init__(self, vocab):
        super().__init__()
        self.model = _FakeTargetBase(vocab)
        head = torch.nn.Linear(vocab, vocab, bias=False)
        with torch.no_grad():
            w = torch.zeros(vocab, vocab)
            for k in range(vocab):
                w[(k + 1) % vocab, k] = 1.0     # logits pico en tok+1
            head.weight.copy_(w)
        self._head = head

    def get_output_embeddings(self):
        return self._head


class _FakeDraft(torch.nn.Module):
    """Emite EXACTAMENTE la continuacion greedy del target falso (c+1, c+2...),
    leyendo el ultimo token real del contexto desde ctx_hidden (one-hot)."""

    def __init__(self, block, vocab):
        super().__init__()
        self.cfg = SimpleNamespace(mask_token_id=-1)
        self.block = block
        self.vocab = vocab

    def forward(self, ctx_hidden, canvas_tokens, canvas_mask, ctx_attn=None):
        last = ctx_hidden[:, -1].argmax(-1)                      # [B]
        steps = torch.arange(1, self.block + 1, device=last.device)
        toks = (last[:, None] + steps[None, :]) % self.vocab     # [B, block]
        return torch.nn.functional.one_hot(toks, self.vocab).float()


def test_run_eval_tau_se_condiciona_al_prefijo_del_draft():
    from bdraft.train_real import compute_tau, run_eval, target_eval_forward

    tok = _tiny_tokenizer()
    vocab, block = len(tok), 8
    target, draft = _FakeTarget(vocab), _FakeDraft(block, vocab)
    args = SimpleNamespace(seq_len=64, block_size=block, micro_batch=2)

    ev = run_eval(target, draft, tok, _pairs(12), args, "cpu")

    # El draft emite justo lo que el target continuaria: se acepta el bloque
    # entero. Con el bug (condicionar en labels) solo sobrevivia la posicion 0.
    assert ev["rows"] > 0
    assert ev["tau"] == pytest.approx(float(block))
    assert ev["tau_ci"] == pytest.approx(0.0)      # sin dispersion: todas 8

    # Y el test discrimina de verdad: recalcular tau condicionando en los
    # labels del dataset (el bug) da un valor estrictamente menor.
    batcher = RealBatcher(tok, _pairs(12), seq_len=args.seq_len,
                          block_size=block, micro_batch=args.micro_batch,
                          seed=424242)
    batch = next(iter(batcher))
    ctx_hidden = torch.nn.functional.one_hot(batch["ctx_tokens"], vocab).float()
    d_tokens = draft(ctx_hidden, batch["canvas_tokens"],
                     batch["canvas_mask"]).argmax(-1)
    _, argmax_bug = target_eval_forward(target, batch["ctx_tokens"],
                                        batch["ctx_attn"], batch["labels"])
    assert compute_tau(d_tokens, argmax_bug) < float(block)
