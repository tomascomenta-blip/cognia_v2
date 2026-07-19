"""
bdraft/train_real.py
====================
REAL v0 training loop for Cognia-BDraft (runs in venv312gpu, RTX 5060 Ti),
per planes/DSPARK_GEMMA_DRAFT_MODEL.md sections 2.2/2.3 and gate G3 (sec. 3).

  - Target Qwen2.5-7B-Instruct loaded in NF4 (bitsandbytes; lm_head kept
    bf16 via llm_int8_skip_modules), frozen, eval(). bnb only quantizes
    Linear layers, so the nn.Embedding stays bf16: embedding + lm_head are
    SHARED with the draft (BDraft freezes them again — they carry no grads).
  - Per micro-batch: 7B forward (base model, LAST-layer hidden states, no
    LM-head materialization) over the left-padded context under no_grad ->
    BDraft(ctx_hidden, canvas, mask, ctx_attn) -> chunked_cross_entropy over
    the masked canvas positions with exp_position_weights.
  - AdamW over trainable params only (fp32 master weights, bf16 autocast
    compute), grad accumulation, grad clip 1.0, linear lr warmup.
  - Checkpoint/resume: trainable state + optimizer + token counter, atomic
    save every --save-every steps; JSONL metric log (train_log.jsonl).
  - G3 eval every --eval-every steps and at the end:
      (a) top1_acc: draft argmax of the block's FIRST token (canvas fully
          masked) vs the dataset label;
      (b) tau_greedy: the SAME 7B forward over [ctx ; canvas labels] yields
          the target's teacher-forced argmax at the 8 positions (causality
          makes the ctx part identical to a ctx-only forward, so one pass
          serves both the ctx_hidden and the argmax); the draft generates
          its 8 greedy tokens and tau = mean matched-prefix length.
          ANTI-FRAUD: tau is measured against the TARGET'S ARGMAX, never
          against the T=0.7 dataset labels.
  - On exhausting --tokens-budget (default 15M = 10% of v0, the G3
    checkpoint): final eval + '### G3: PASS/FAIL top1=X tau=Y ###'.
"""

import argparse
import json
import time
from pathlib import Path

import torch

from bdraft.model import BDraft, BDraftConfig
from bdraft.real_data import RealBatcher, load_pairs, split_pairs
from bdraft.train import chunked_cross_entropy, exp_position_weights
from bdraft.gates import G3_TAU_MIN, G3_TOP1_MIN, g3_early_signal  # noqa: F401

DEFAULT_DATA = str(Path.home() / ".cognia" / "bdraft_data" / "v0.jsonl")
DEFAULT_CKPT_DIR = str(Path.home() / ".cognia" / "bdraft_ckpt")
EVAL_SEED = 424242            # fixed: every eval sees the same val stream


# ---------------------------------------------------------------------------
# Pure, testable pieces (no GPU / no transformers needed)
# ---------------------------------------------------------------------------

def compute_tau(draft_tokens, target_argmax) -> float:
    """Mean matched-PREFIX length between the draft's greedy block and the
    target's argmax at the same positions ([B, block] tensors or nested
    lists). This is the accepted length under greedy verification. It is
    computed against the TARGET'S ARGMAX — never against dataset labels."""
    d = torch.as_tensor(draft_tokens)
    t = torch.as_tensor(target_argmax)
    if d.dim() == 1:
        d, t = d[None, :], t[None, :]
    eq = (d == t).long()
    # cumprod stays 1 only while every previous position matched.
    return eq.cumprod(dim=1).sum(dim=1).float().mean().item()


def warmup_lr(base_lr: float, step: int, warmup_steps: int) -> float:
    """Linear warmup to base_lr over warmup_steps, then constant."""
    if warmup_steps <= 0 or step >= warmup_steps:
        return base_lr
    return base_lr * (step + 1) / warmup_steps


def real_step_loss(draft: BDraft, ctx_hidden, batch: dict,
                   pos_w: torch.Tensor) -> torch.Tensor:
    """CE over the MASKED canvas positions only, exponentially weighted by
    block position (same objective as bdraft.train._step_loss but with real
    target hidden states + context padding mask)."""
    canvas_mask = batch["canvas_mask"]
    hidden = draft.forward_hidden(ctx_hidden, batch["canvas_tokens"],
                                  canvas_mask, ctx_attn=batch["ctx_attn"])
    up = draft.up_proj(hidden)                    # [B, block, target_d]
    up_m = up[canvas_mask]
    labels_m = batch["labels"][canvas_mask]
    cols = canvas_mask.nonzero(as_tuple=True)[1]  # block position per slot
    return chunked_cross_entropy(up_m, draft.lm_head.weight, labels_m,
                                 pos_weights=pos_w[cols])


# ---------------------------------------------------------------------------
# Target model (Qwen2.5-7B-Instruct NF4)
# ---------------------------------------------------------------------------

def load_target(target_dir: str, device: str = "cuda"):
    """Frozen NF4 target with bf16 compute; lm_head skipped from quantization
    so the shared LM head is bf16. Returns the CausalLM model."""
    from transformers import AutoModelForCausalLM, BitsAndBytesConfig
    bnb = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        llm_int8_skip_modules=["lm_head"],
    )
    model = AutoModelForCausalLM.from_pretrained(
        target_dir, quantization_config=bnb, dtype=torch.bfloat16,
        device_map={"": 0} if device.startswith("cuda") else device)
    model.eval()
    model.requires_grad_(False)
    return model


def _base_model(target):
    """The decoder stack (skips the LM head: no [B,T,152K] logits over the
    full context, doc 2.3 'punto de dolor')."""
    base = getattr(target, "model", None)
    return base if base is not None else target.get_decoder()


def _positions(attn: torch.Tensor) -> torch.Tensor:
    """position_ids for left-padded rows: pads repeat 0, real tokens count
    0..n-1, so the target's RoPE matches the unpadded sequence."""
    return (attn.long().cumsum(-1) - 1).clamp_min(0)


@torch.no_grad()
def target_ctx_hidden(target, ctx_tokens, ctx_attn) -> torch.Tensor:
    """LAST-layer (post-norm) hidden states over the context only."""
    out = _base_model(target)(input_ids=ctx_tokens,
                              attention_mask=ctx_attn.long(),
                              position_ids=_positions(ctx_attn),
                              use_cache=False)
    return out.last_hidden_state


@torch.no_grad()
def target_eval_forward(target, ctx_tokens, ctx_attn, labels):
    """ONE 7B forward over [ctx ; canvas labels] -> (ctx_hidden [B,T,d_t],
    target_argmax [B,block]). Causal attention makes h[:, :T] identical to a
    ctx-only forward; the prediction for canvas position j lives at index
    T-1+j (left padding puts the last real ctx token at T-1). The LM head is
    applied to those block positions only."""
    B, T = ctx_tokens.shape
    block = labels.shape[1]
    full = torch.cat([ctx_tokens, labels], dim=1)
    attn = torch.cat([ctx_attn, torch.ones(B, block, dtype=torch.bool,
                                           device=ctx_attn.device)], dim=1)
    h = _base_model(target)(input_ids=full, attention_mask=attn.long(),
                            position_ids=_positions(attn),
                            use_cache=False).last_hidden_state
    logits = target.get_output_embeddings()(h[:, T - 1:T - 1 + block])
    return h[:, :T], logits.argmax(dim=-1)


# ---------------------------------------------------------------------------
# G3 eval
# ---------------------------------------------------------------------------

@torch.no_grad()
def run_eval(target, draft: BDraft, tokenizer, val_pairs, args,
             device: str) -> tuple[float, float]:
    """(top1_acc, tau_greedy) over --eval-batches val batches. Fresh batcher
    with a fixed seed => identical val stream on every call."""
    batcher = RealBatcher(tokenizer, val_pairs, seq_len=args.seq_len,
                          block_size=args.block_size,
                          micro_batch=args.micro_batch, seed=EVAL_SEED)
    draft.eval()
    hits = rows = 0
    taus = []
    it = iter(batcher)
    for _ in range(args.eval_batches):
        batch = next(it, None)
        if batch is None:
            break
        batch = {k: v.to(device) for k, v in batch.items()}
        labels = batch["labels"]
        ctx_hidden, tgt_argmax = target_eval_forward(
            target, batch["ctx_tokens"], batch["ctx_attn"], labels)
        # Draft greedy: canvas FULLY masked, one forward, argmax per position.
        masked_canvas = torch.full_like(labels, draft.cfg.mask_token_id)
        full_mask = torch.ones_like(labels, dtype=torch.bool)
        with torch.autocast(device_type="cuda", dtype=torch.bfloat16,
                            enabled=device.startswith("cuda")):
            logits = draft(ctx_hidden, masked_canvas, full_mask,
                           ctx_attn=batch["ctx_attn"])
        draft_tokens = logits.argmax(dim=-1)
        hits += (draft_tokens[:, 0] == labels[:, 0]).sum().item()  # (a) vs label
        rows += labels.shape[0]
        taus.append(compute_tau(draft_tokens, tgt_argmax))         # (b) vs argmax
    draft.train()
    top1 = hits / rows if rows else 0.0
    tau = sum(taus) / len(taus) if taus else 0.0
    return top1, tau


# ---------------------------------------------------------------------------
# Checkpoint / logging
# ---------------------------------------------------------------------------

def _trainable_state(draft: BDraft) -> dict:
    """Draft state dict WITHOUT the shared frozen embedding/lm_head (they are
    the target's own weights — reloaded from the target, never saved)."""
    return {k: v for k, v in draft.state_dict().items()
            if not (k.startswith("embedding.") or k.startswith("lm_head."))}


def save_ckpt(ckpt_dir: Path, draft: BDraft, opt, step: int,
              tokens_seen: int):
    path = ckpt_dir / "ckpt.pt"
    tmp = ckpt_dir / "ckpt.pt.tmp"
    torch.save({"draft": _trainable_state(draft), "opt": opt.state_dict(),
                "step": step, "tokens_seen": tokens_seen}, tmp)
    tmp.replace(path)


def load_ckpt(ckpt_dir: Path, draft: BDraft, opt) -> tuple[int, int]:
    state = torch.load(ckpt_dir / "ckpt.pt", map_location="cpu",
                       weights_only=True)
    missing, unexpected = draft.load_state_dict(state["draft"], strict=False)
    # Only the shared frozen modules may be absent from the checkpoint.
    bad = [k for k in missing
           if not (k.startswith("embedding.") or k.startswith("lm_head."))]
    if bad or unexpected:
        raise RuntimeError("checkpoint incompatible: missing %s unexpected %s"
                           % (bad, unexpected))
    opt.load_state_dict(state["opt"])
    return int(state["step"]), int(state["tokens_seen"])


def log_jsonl(path: Path, record: dict):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Cognia-BDraft REAL v0 training (target NF4 in the loop)")
    ap.add_argument("--data", default=DEFAULT_DATA)
    ap.add_argument("--target-dir", required=True)
    ap.add_argument("--ckpt-dir", default=DEFAULT_CKPT_DIR)
    ap.add_argument("--tokens-budget", type=int, default=15_000_000,
                    help="G3 checkpoint: 10%% of the v0 budget (doc 2.3)")
    ap.add_argument("--seq-len", type=int, default=1024)
    ap.add_argument("--block-size", type=int, default=8)
    ap.add_argument("--micro-batch", type=int, default=4)
    ap.add_argument("--accum", type=int, default=4)
    ap.add_argument("--lr", type=float, default=6e-4)
    ap.add_argument("--warmup", type=int, default=200)
    ap.add_argument("--save-every", type=int, default=200)
    ap.add_argument("--eval-every", type=int, default=500)
    ap.add_argument("--eval-batches", type=int, default=16)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--device", default="cuda")
    args = ap.parse_args(argv)

    device = args.device
    ckpt_dir = Path(args.ckpt_dir)
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    log_path = ckpt_dir / "train_log.jsonl"

    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(args.target_dir)
    pairs = load_pairs(args.data)
    train_pairs, val_pairs = split_pairs(pairs)
    if not train_pairs or not val_pairs:
        raise SystemExit("dataset insuficiente: %d train / %d val pares en %s"
                         % (len(train_pairs), len(val_pairs), args.data))

    print("[train_real] cargando target NF4 desde %s ..." % args.target_dir,
          flush=True)
    target = load_target(args.target_dir, device)
    cfg = BDraftConfig(block_size=args.block_size,
                       target_d_model=target.config.hidden_size,
                       vocab_size=target.config.vocab_size)
    torch.manual_seed(args.seed)
    draft = BDraft(cfg, target_embedding=target.get_input_embeddings(),
                   target_lm_head=target.get_output_embeddings()).to(device)
    trainable = [p for p in draft.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(trainable, lr=args.lr)
    pos_w = exp_position_weights(cfg.block_size).to(device)

    step, tokens_seen = 0, 0
    if args.resume:
        if not (ckpt_dir / "ckpt.pt").exists():
            raise SystemExit("--resume pero no existe %s"
                             % (ckpt_dir / "ckpt.pt"))
        step, tokens_seen = load_ckpt(ckpt_dir, draft, opt)
        print("[train_real] resume: step %d, %.2fM tokens"
              % (step, tokens_seen / 1e6), flush=True)

    print("[train_real] %d train / %d val pares | %s params entrenables | "
          "budget %.1fM tokens | micro %d x accum %d | lr %g warmup %d"
          % (len(train_pairs), len(val_pairs),
             format(draft.num_trainable_params(), ","),
             args.tokens_budget / 1e6, args.micro_batch, args.accum,
             args.lr, args.warmup), flush=True)

    # Seed offset by the resumed step so a resumed run sees a fresh sample
    # order instead of replaying the epoch from scratch.
    batcher = RealBatcher(tokenizer, train_pairs, seq_len=args.seq_len,
                          block_size=args.block_size,
                          micro_batch=args.micro_batch,
                          seed=args.seed + step)
    data_iter = iter(batcher)

    def next_batch():
        nonlocal data_iter
        for _ in range(2):
            batch = next(data_iter, None)
            if batch is not None:
                return batch
            data_iter = iter(batcher)   # next epoch (reshuffled)
        raise SystemExit("RealBatcher no produce batches: respuestas "
                         "demasiado cortas para block_size=%d?"
                         % args.block_size)

    draft.train()
    t_last, tokens_last = time.time(), tokens_seen
    loss_val = float("nan")
    while tokens_seen < args.tokens_budget:
        opt.zero_grad(set_to_none=True)
        accum_loss = 0.0
        for _ in range(args.accum):
            batch = {k: v.to(device) for k, v in next_batch().items()}
            ctx_hidden = target_ctx_hidden(target, batch["ctx_tokens"],
                                           batch["ctx_attn"])
            with torch.autocast(device_type="cuda", dtype=torch.bfloat16,
                                enabled=device.startswith("cuda")):
                loss = real_step_loss(draft, ctx_hidden, batch, pos_w)
            (loss / args.accum).backward()
            accum_loss += loss.item() / args.accum
            tokens_seen += int(batch["ctx_attn"].sum().item()) \
                + batch["labels"].numel()
        torch.nn.utils.clip_grad_norm_(trainable, 1.0)
        lr_now = warmup_lr(args.lr, step, args.warmup)
        for group in opt.param_groups:
            group["lr"] = lr_now
        opt.step()
        step += 1
        loss_val = accum_loss

        if step % 20 == 0:
            now = time.time()
            tok_s = (tokens_seen - tokens_last) / max(now - t_last, 1e-9)
            t_last, tokens_last = now, tokens_seen
            print("[train_real] step %6d  loss %.4f  tokens %.2fM/%.0fM  "
                  "%.0f tok/s  lr %.2e" % (step, loss_val, tokens_seen / 1e6,
                                           args.tokens_budget / 1e6, tok_s,
                                           lr_now), flush=True)
            log_jsonl(log_path, {"step": step, "loss": round(loss_val, 5),
                                 "tokens": tokens_seen,
                                 "tok_s": round(tok_s, 1), "lr": lr_now,
                                 "t": time.time()})
        if args.save_every and step % args.save_every == 0:
            save_ckpt(ckpt_dir, draft, opt, step, tokens_seen)
        if args.eval_every and step % args.eval_every == 0:
            top1, tau = run_eval(target, draft, tokenizer, val_pairs, args,
                                 device)
            ok = g3_early_signal(top1, tau)
            print("[train_real] EVAL step %d  top1 %.4f (min %.2f)  tau %.3f "
                  "(min %.2f)  g3=%s" % (step, top1, G3_TOP1_MIN, tau,
                                         G3_TAU_MIN, "PASS" if ok else "fail"),
                  flush=True)
            log_jsonl(log_path, {"type": "eval", "step": step,
                                 "tokens": tokens_seen, "top1": round(top1, 5),
                                 "tau": round(tau, 4), "g3_pass": ok,
                                 "t": time.time()})

    # Budget exhausted: final checkpoint + final G3 eval + verdict.
    save_ckpt(ckpt_dir, draft, opt, step, tokens_seen)
    top1, tau = run_eval(target, draft, tokenizer, val_pairs, args, device)
    ok = g3_early_signal(top1, tau)
    log_jsonl(log_path, {"type": "eval_final", "step": step,
                         "tokens": tokens_seen, "top1": round(top1, 5),
                         "tau": round(tau, 4), "g3_pass": ok,
                         "t": time.time()})
    print("### G3: %s top1=%.4f tau=%.3f ###"
          % ("PASS" if ok else "FAIL", top1, tau), flush=True)


if __name__ == "__main__":
    main()
