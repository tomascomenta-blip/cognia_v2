"""
bdraft/data.py
==============
Data utilities for Cognia-BDraft training, per
planes/DSPARK_GEMMA_DRAFT_MODEL.md section 2.3:

  - masking ratio sampled per block, t ~ U(0,1) (discrete-diffusion style);
  - a random cut position splits each sequence into [context | canvas]: the
    block right after the cut is the canvas, ratio t of its positions gets
    masked and the model must denoise them;
  - a deterministic synthetic dataset (periodic motif sequences, NOT uniform
    noise) for CPU tests and overfit sanity runs — real training uses
    target-regenerated instruction data (doc 2.3), out of scope here.
"""

import torch


def sample_mask_ratio(generator: torch.Generator) -> float:
    """t ~ U(0,1) masking ratio for one block (discrete-diffusion style).
    Clamped to the open interval so a block is never fully given/fully free."""
    t = torch.rand((), generator=generator).item()
    return min(max(t, 1e-6), 1.0 - 1e-6)


def make_canvas_batch(token_ids: torch.Tensor, block_size: int,
                      generator: torch.Generator,
                      mask_token_id: int = -1) -> dict:
    """token_ids [B, S] -> one training batch for the block-diffusion draft.

    Picks ONE cut position for the whole batch (context length T is shared),
    takes the next block_size tokens as the canvas, and masks ratio ~t of the
    canvas positions (same count per row, random positions per row; at least
    one masked so there is always a training signal).

    Returns dict with:
      ctx_tokens   [B, T]     tokens before the cut (context)
      canvas_tokens[B, block] canvas with mask_token_id at masked positions
      canvas_mask  [B, block] bool, True = masked
      labels       [B, block] the original canvas tokens
      mask_ratio   float      the sampled t (for logging/tests)
    """
    B, S = token_ids.shape
    if S < block_size + 1:
        raise ValueError("need S >= block_size + 1, got S=%d block=%d"
                         % (S, block_size))
    # Cut in [1, S - block_size]: always >=1 context token, canvas fits.
    cut = int(torch.randint(1, S - block_size + 1, (1,),
                            generator=generator).item())
    ctx_tokens = token_ids[:, :cut]
    labels = token_ids[:, cut:cut + block_size].clone()
    t = sample_mask_ratio(generator)
    n_masked = max(1, int(round(t * block_size)))
    canvas_mask = torch.zeros(B, block_size, dtype=torch.bool)
    for b in range(B):
        pos = torch.randperm(block_size, generator=generator)[:n_masked]
        canvas_mask[b, pos] = True
    canvas_tokens = labels.clone()
    canvas_tokens[canvas_mask] = mask_token_id  # BDraftConfig.mask_token_id sentinel
    return {"ctx_tokens": ctx_tokens, "canvas_tokens": canvas_tokens,
            "canvas_mask": canvas_mask, "labels": labels, "mask_ratio": t}


def build_synthetic_dataset(cfg, n_samples: int, seed: int) -> torch.Tensor:
    """Deterministic synthetic sequences [n_samples, 4*block_size] with
    learnable structure: each row tiles one of a few random motifs (period 4)
    at a random phase, so masked canvas tokens are recoverable by attending
    to visible copies of the motif. NOT uniform noise on purpose — an overfit
    run on this must drive the loss down (tests / gate sanity)."""
    g = torch.Generator().manual_seed(seed)
    period = 4
    n_motifs = 8
    seq_len = 4 * cfg.block_size
    motifs = torch.randint(0, cfg.vocab_size, (n_motifs, period), generator=g)
    which = torch.randint(0, n_motifs, (n_samples,), generator=g)
    phase = torch.randint(0, period, (n_samples,), generator=g)
    idx = (torch.arange(seq_len)[None, :] + phase[:, None]) % period  # [N, S]
    return motifs[which[:, None], idx]  # [N, S] long
