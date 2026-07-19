"""
bdraft/real_data.py
===================
From the v0 JSONL ({"prompt","respuesta"}) to real training batches for
Cognia-BDraft, per planes/DSPARK_GEMMA_DRAFT_MODEL.md section 2.3.

Per sample: tokenize ChatML(prompt) + respuesta + <|im_end|>, truncate to
seq_len, pick a cut point INSIDE the response (never in the prompt): context
= everything up to the cut, canvas = the next block_size tokens, mask ratio
t ~ U(0,1) per sample (bdraft.data.sample_mask_ratio). Contexts are
LEFT-padded per batch with an attention mask up to the cut: RoPE is relative,
so left padding keeps the canvas adjacent to each row's last real context
token, and the pad positions are excluded from the draft's attention via
ctx_attn (see BDraft.forward_hidden) and from the target's via its
attention_mask + position_ids (train_real).

Train/val split: deterministic 98/2 by sha1 of the prompt (hashlib, NOT the
salted builtin hash), so duplicated prompts can never leak across the split.
"""

import hashlib
import json
from pathlib import Path

import torch

from bdraft.data import sample_mask_ratio
from node.inference_pipeline import _apply_qwen_template

IM_END = "<|im_end|>"


def chatml_prompt(prompt: str) -> str:
    """The exact ChatML prefix the answers were regenerated with (ends with
    '<|im_start|>assistant\\n'): tokenizing THIS + respuesta reproduces the
    stream the target produced in gen_dataset."""
    return _apply_qwen_template(prompt)


def load_pairs(jsonl_path) -> list[dict]:
    """v0.jsonl -> list of {'prompt','respuesta'}; blank/invalid lines are
    dropped (a killed gen_dataset run can leave a truncated last line)."""
    pairs = []
    with open(Path(jsonl_path), encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            p, r = row.get("prompt"), row.get("respuesta")
            if p and r:
                pairs.append({"prompt": p, "respuesta": r})
    return pairs


def split_pairs(pairs: list[dict], val_pct: int = 2) -> tuple[list, list]:
    """Deterministic 98/2 split by sha1(prompt): the same prompt ALWAYS lands
    on the same side (no leakage even with duplicated prompts), and the split
    is stable across runs/machines (PYTHONHASHSEED-independent)."""
    train, val = [], []
    for pair in pairs:
        digest = hashlib.sha1(pair["prompt"].encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:8], "big") % 100
        (val if bucket < val_pct else train).append(pair)
    return train, val


def build_example(tokenizer, pair: dict, seq_len: int, block_size: int,
                  generator: torch.Generator,
                  mask_token_id: int = -1,
                  prob_mascara_completa: float = 0.0) -> dict | None:
    """One pair -> one training example, or None if the truncated response
    cannot fit a full canvas. The cut is uniform in
    [prompt_len, total_len - block_size]: the canvas is ALWAYS made of
    response tokens (cut == prompt_len is the 'start of the answer' case the
    draft sees first at inference)."""
    prompt_ids = tokenizer.encode(chatml_prompt(pair["prompt"]),
                                  add_special_tokens=False)
    resp_ids = tokenizer.encode(pair["respuesta"] + IM_END,
                                add_special_tokens=False)
    ids = (prompt_ids + resp_ids)[:seq_len]
    prompt_len = len(prompt_ids)
    if prompt_len >= seq_len or len(ids) < prompt_len + block_size:
        return None
    lo, hi = prompt_len, len(ids) - block_size
    cut = lo + int(torch.randint(0, hi - lo + 1, (1,),
                                 generator=generator).item())
    labels = torch.tensor(ids[cut:cut + block_size], dtype=torch.long)
    t = sample_mask_ratio(generator, prob_completo=prob_mascara_completa)
    n_masked = max(1, int(round(t * block_size)))
    pos = torch.randperm(block_size, generator=generator)[:n_masked]
    canvas_mask = torch.zeros(block_size, dtype=torch.bool)
    canvas_mask[pos] = True
    canvas_tokens = labels.clone()
    canvas_tokens[canvas_mask] = mask_token_id
    return {"ctx_ids": ids[:cut], "canvas_tokens": canvas_tokens,
            "canvas_mask": canvas_mask, "labels": labels, "cut": cut,
            "prompt_len": prompt_len, "mask_ratio": t}


class RealBatcher:
    """Iterable over micro-batches of CPU tensors ready for .to(device).

    Each __iter__() is ONE epoch: a deterministic shuffle of the pairs whose
    seed advances with an internal epoch counter (same seed => same stream of
    batches, fresh instance => reproducible from the start). Pairs whose
    truncated response is shorter than block_size are skipped; the last
    partial batch is dropped (stable shapes). Yields dicts:
      ctx_tokens [B, T] long, LEFT-padded with the tokenizer pad id
      ctx_attn   [B, T] bool, True = real token (False = pad)
      canvas_tokens [B, block] long (-1 sentinel at masked positions)
      canvas_mask   [B, block] bool
      labels        [B, block] long
    """

    def __init__(self, tokenizer, pairs: list[dict], seq_len: int = 1024,
                 block_size: int = 8, micro_batch: int = 4, seed: int = 0,
                 mask_token_id: int = -1, prob_mascara_completa: float = 0.0):
        self.tokenizer = tokenizer
        self.pairs = pairs
        self.seq_len = seq_len
        self.block_size = block_size
        self.micro_batch = micro_batch
        self.seed = seed
        self.mask_token_id = mask_token_id
        # Ver bdraft.data.sample_mask_ratio: sesga el muestreo hacia el canvas
        # totalmente enmascarado, que es el unico regimen que usa la inferencia.
        self.prob_mascara_completa = prob_mascara_completa
        pad = tokenizer.pad_token_id
        if pad is None:
            pad = tokenizer.eos_token_id
        self.pad_id = 0 if pad is None else int(pad)
        self._epoch = 0

    def __iter__(self):
        g = torch.Generator().manual_seed(self.seed * 100003 + self._epoch)
        self._epoch += 1
        order = torch.randperm(len(self.pairs), generator=g).tolist()
        buf = []
        for idx in order:
            ex = build_example(self.tokenizer, self.pairs[idx], self.seq_len,
                               self.block_size, g, self.mask_token_id,
                               self.prob_mascara_completa)
            if ex is None:
                continue
            buf.append(ex)
            if len(buf) == self.micro_batch:
                yield self._collate(buf)
                buf = []

    def _collate(self, examples: list[dict]) -> dict:
        B = len(examples)
        T = max(len(e["ctx_ids"]) for e in examples)
        ctx = torch.full((B, T), self.pad_id, dtype=torch.long)
        attn = torch.zeros(B, T, dtype=torch.bool)
        for i, e in enumerate(examples):
            n = len(e["ctx_ids"])
            ctx[i, T - n:] = torch.tensor(e["ctx_ids"], dtype=torch.long)
            attn[i, T - n:] = True
        return {"ctx_tokens": ctx, "ctx_attn": attn,
                "canvas_tokens": torch.stack(
                    [e["canvas_tokens"] for e in examples]),
                "canvas_mask": torch.stack(
                    [e["canvas_mask"] for e in examples]),
                "labels": torch.stack([e["labels"] for e in examples])}
