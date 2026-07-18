"""
bdraft/train.py
===============
Training loop for Cognia-BDraft, per planes/DSPARK_GEMMA_DRAFT_MODEL.md
section 2.3:

  - objective: cross-entropy over the MASKED canvas tokens only, target
    tokens as hard labels, exponential position weighting (DFlash) and
    per-block masking ratio t ~ U(0,1);
  - chunked cross-entropy: with the real 152K vocab the [N, vocab] logits
    matrix must NEVER be materialized at once (doc 2.3 "punto de dolor");
  - AdamW over TRAINABLE params only (shared embedding/LM head are frozen).

--mini mode: BDraftConfig.mini() + synthetic periodic dataset, runs on CPU
in minutes. Real training (target Qwen2.5-7B hidden states on-the-fly,
NF4 target in the loop) requires torch cu128+ under WSL2 — gate G0 — and
is NOT implemented here.
"""

import argparse

import torch
import torch.nn.functional as F

from bdraft.data import build_synthetic_dataset, make_canvas_batch
from bdraft.model import BDraft, BDraftConfig


def chunked_cross_entropy(hidden: torch.Tensor, lm_head_weight: torch.Tensor,
                          labels: torch.Tensor, chunk_size: int = 8192,
                          pos_weights: torch.Tensor | None = None) -> torch.Tensor:
    """CE(hidden @ lm_head_weight.T, labels) without ever materializing the
    full [N, vocab] logits. hidden [N, d], lm_head_weight [V, d] (no bias),
    labels [N]; pos_weights [N] or None -> weighted mean, plain mean if None.
    Equals F.cross_entropy on the full matmul up to float tolerance."""
    n = hidden.shape[0]
    loss_sum = hidden.new_zeros(())
    w_sum = hidden.new_zeros(())
    for start in range(0, n, chunk_size):
        h = hidden[start:start + chunk_size]
        y = labels[start:start + chunk_size]
        logits = h @ lm_head_weight.T                     # [chunk, V] only
        ce = F.cross_entropy(logits, y, reduction="none")  # [chunk]
        if pos_weights is None:
            loss_sum = loss_sum + ce.sum()
            w_sum = w_sum + ce.numel()
        else:
            w = pos_weights[start:start + chunk_size]
            loss_sum = loss_sum + (ce * w).sum()
            w_sum = w_sum + w.sum()
    return loss_sum / w_sum


def exp_position_weights(block_size: int, decay: float = 0.8) -> torch.Tensor:
    """DFlash-style exponentially decreasing per-position loss weights:
    early block positions matter more (they decide the accepted prefix)."""
    return decay ** torch.arange(block_size, dtype=torch.float32)


def _step_loss(model: BDraft, batch: dict, pos_w: torch.Tensor,
               device: str) -> torch.Tensor:
    """Loss of one canvas batch. In mini/synthetic mode there is no target
    model, so the (shared or own) token embedding stands in for the target's
    last-layer hidden states over the context."""
    ctx_tokens = batch["ctx_tokens"].to(device)
    canvas_tokens = batch["canvas_tokens"].to(device)
    canvas_mask = batch["canvas_mask"].to(device)
    labels = batch["labels"].to(device)
    ctx_hidden = model.embedding(ctx_tokens)               # [B, T, target_d]
    hidden = model.forward_hidden(ctx_hidden, canvas_tokens, canvas_mask)
    up = model.up_proj(hidden)                             # [B, block, target_d]
    # CE over MASKED positions only (diffusion objective), weighted by the
    # block position of each masked slot.
    up_m = up[canvas_mask]                                 # [M, target_d]
    labels_m = labels[canvas_mask]                         # [M]
    cols = canvas_mask.nonzero(as_tuple=True)[1]           # [M] block positions
    return chunked_cross_entropy(up_m, model.lm_head.weight, labels_m,
                                 pos_weights=pos_w[cols])


def train_loop(model: BDraft, dataset: torch.Tensor, steps: int, lr: float,
               device: str = "cpu", log_every: int = 50) -> list[float]:
    """AdamW over trainable params only. dataset: LongTensor [N, S] of token
    sequences (build_synthetic_dataset output in mini mode). Returns the
    per-step loss list."""
    model = model.to(device).train()
    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=lr)
    g = torch.Generator().manual_seed(1234)  # batch + mask sampling
    pos_w = exp_position_weights(model.cfg.block_size).to(device)
    batch_size = min(16, dataset.shape[0])
    losses: list[float] = []
    for step in range(steps):
        rows = torch.randint(0, dataset.shape[0], (batch_size,), generator=g)
        batch = make_canvas_batch(dataset[rows], model.cfg.block_size, g,
                                  mask_token_id=model.cfg.mask_token_id)
        loss = _step_loss(model, batch, pos_w, device)
        opt.zero_grad()
        loss.backward()
        opt.step()
        losses.append(loss.item())
        if log_every and (step + 1) % log_every == 0:
            print("step %4d/%d  loss %.4f" % (step + 1, steps, losses[-1]))
    return losses


def main():
    ap = argparse.ArgumentParser(description="Cognia-BDraft training")
    ap.add_argument("--mini", action="store_true",
                    help="mini config + synthetic dataset (CPU smoke run)")
    ap.add_argument("--steps", type=int, default=200)
    ap.add_argument("--lr", type=float, default=3e-3)
    args = ap.parse_args()
    if not args.mini:
        raise SystemExit(
            "Real training is not implemented in this stage: it needs the "
            "target (Qwen2.5-7B) hidden states on-the-fly and torch cu128+ "
            "under WSL2 (gate G0, planes/DSPARK_GEMMA_DRAFT_MODEL.md). "
            "Run with --mini for the CPU smoke mode.")
    cfg = BDraftConfig.mini()
    torch.manual_seed(0)
    model = BDraft(cfg)
    dataset = build_synthetic_dataset(cfg, n_samples=256, seed=0)
    print("mini run: %d trainable params, %d synthetic sequences, "
          "%d steps, lr %g" % (model.num_trainable_params(),
                               dataset.shape[0], args.steps, args.lr))
    losses = train_loop(model, dataset, steps=args.steps, lr=args.lr,
                        log_every=10)
    print("initial loss %.4f  final loss %.4f  (ratio %.2f)"
          % (losses[0], losses[-1], losses[-1] / losses[0]))


if __name__ == "__main__":
    main()
