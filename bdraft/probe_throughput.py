"""
bdraft/probe_throughput.py
==========================
Sondeo de rendimiento previo al run v0: mide tokens/s reales del camino de
entrenamiento de train_real con distintos (micro_batch, accum) que dejan el
MISMO batch efectivo de ejemplos por paso de optimizador.

Por que existe: con el dataset v0 real el contexto medio es ~160 tokens (no
los 1024 de --seq-len), asi que el forward del 7B en NF4 esta limitado por
ancho de banda (leer 5.5 GB de pesos), no por computo. Con --micro-batch 4
--accum 4 se leen los pesos CUATRO veces por paso; con --micro-batch 16
--accum 1, una sola vez. Este script mide si esa hipotesis es cierta en la
5060 Ti en vez de asumirla.

No guarda checkpoint, no toca train_log.jsonl y no modifica nada: solo mide.
Usar venv312gpu y con el llama-server APAGADO (necesita la VRAM).

    .\\venv312gpu\\Scripts\\python.exe -m bdraft.probe_throughput \\
        --data C:\\Users\\usuario\\.cognia\\bdraft_data\\v0.jsonl \\
        --target-dir C:\\Users\\usuario\\.cognia\\models_hf\\qwen2.5-7b-instruct
"""

import argparse
import time

import torch

from bdraft.model import BDraft, BDraftConfig
from bdraft.real_data import RealBatcher, load_pairs, split_pairs
from bdraft.train import exp_position_weights
from bdraft.train_real import (DEFAULT_DATA, load_target, real_step_loss,
                               target_ctx_hidden)

# Configuraciones con batch efectivo IDENTICO (16 ejemplos por paso), para que
# la comparacion sea de rendimiento puro y no cambie la dinamica de optimizacion.
CONFIGS = [(4, 4), (8, 2), (16, 1)]


def probe(target, tokenizer, pairs, micro: int, accum: int, args,
          device: str) -> dict:
    """Corre --steps pasos de optimizador completos y devuelve metricas."""
    torch.manual_seed(args.seed)
    cfg = BDraftConfig(block_size=args.block_size,
                       target_d_model=target.config.hidden_size,
                       vocab_size=target.config.vocab_size)
    draft = BDraft(cfg, target_embedding=target.get_input_embeddings(),
                   target_lm_head=target.get_output_embeddings()).to(device)
    draft.train()
    trainable = [p for p in draft.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(trainable, lr=args.lr)
    pos_w = exp_position_weights(cfg.block_size).to(device)

    batcher = RealBatcher(tokenizer, pairs, seq_len=args.seq_len,
                          block_size=args.block_size, micro_batch=micro,
                          seed=args.seed)
    it = iter(batcher)

    torch.cuda.reset_peak_memory_stats()
    tokens = padded = 0
    # Pasos de calentamiento: la primera iteracion paga compilacion de kernels
    # y alocacion del caching allocator; medirla contaminaria la comparacion.
    for phase in ("warmup", "medir"):
        n_steps = args.warmup_steps if phase == "warmup" else args.steps
        if phase == "medir":
            torch.cuda.synchronize()
            t0 = time.time()
            tokens = padded = 0
        for _ in range(n_steps):
            opt.zero_grad(set_to_none=True)
            for _ in range(accum):
                batch = next(it, None)
                if batch is None:
                    it = iter(batcher)
                    batch = next(it)
                batch = {k: v.to(device) for k, v in batch.items()}
                ctx_hidden = target_ctx_hidden(target, batch["ctx_tokens"],
                                               batch["ctx_attn"])
                with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                    loss = real_step_loss(draft, ctx_hidden, batch, pos_w)
                (loss / accum).backward()
                tokens += int(batch["ctx_attn"].sum().item()) \
                    + batch["labels"].numel()
                padded += batch["ctx_tokens"].numel() + batch["labels"].numel()
            torch.nn.utils.clip_grad_norm_(trainable, 1.0)
            opt.step()
    torch.cuda.synchronize()
    dt = time.time() - t0

    peak = torch.cuda.max_memory_allocated() / 2**30
    del draft, opt, trainable
    torch.cuda.empty_cache()
    return {"micro": micro, "accum": accum, "s": dt, "tokens": tokens,
            "tok_s": tokens / dt, "pasos_s": args.steps / dt,
            "padding_pct": 100 * (padded - tokens) / max(padded, 1),
            "vram_pico_gb": peak}


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Sondeo de tokens/s del camino real de train_real")
    ap.add_argument("--data", default=DEFAULT_DATA)
    ap.add_argument("--target-dir", required=True)
    ap.add_argument("--seq-len", type=int, default=1024)
    ap.add_argument("--block-size", type=int, default=8)
    ap.add_argument("--lr", type=float, default=6e-4)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--steps", type=int, default=25)
    ap.add_argument("--warmup-steps", type=int, default=5)
    ap.add_argument("--device", default="cuda")
    args = ap.parse_args(argv)

    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(args.target_dir)
    train_pairs, _ = split_pairs(load_pairs(args.data))
    print("[probe] %d pares de entrenamiento | cargando target NF4 ..."
          % len(train_pairs), flush=True)
    target = load_target(args.target_dir, args.device)
    print("[probe] target cargado, VRAM %.2f GB"
          % (torch.cuda.memory_allocated() / 2**30), flush=True)

    filas = []
    for micro, accum in CONFIGS:
        r = probe(target, tokenizer, train_pairs, micro, accum, args,
                  args.device)
        filas.append(r)
        print("[probe] micro %2d x accum %2d -> %7.0f tok/s  %.2f pasos/s  "
              "padding %.1f%%  VRAM pico %.2f GB"
              % (r["micro"], r["accum"], r["tok_s"], r["pasos_s"],
                 r["padding_pct"], r["vram_pico_gb"]), flush=True)

    mejor = max(filas, key=lambda r: r["tok_s"])
    base = next(r for r in filas if (r["micro"], r["accum"]) == (4, 4))
    print("\n=== RESULTADO ===")
    print("mejor: micro %d x accum %d con %.0f tok/s (%.2fx vs micro 4 x accum 4)"
          % (mejor["micro"], mejor["accum"], mejor["tok_s"],
             mejor["tok_s"] / base["tok_s"]))
    for presupuesto, nombre in ((15_000_000, "G3"), (150_000_000, "v0 completo")):
        h_base = presupuesto / base["tok_s"] / 3600
        h_mejor = presupuesto / mejor["tok_s"] / 3600
        print("%-12s (%3.0fM tokens): %5.1f h con micro 4 x accum 4  ->  "
              "%5.1f h con la mejor config"
              % (nombre, presupuesto / 1e6, h_base, h_mejor))
    print("(tope duro pre-registrado del plan: 60 h de GPU para la Pista 1 v0)")


if __name__ == "__main__":
    main()
