"""
expert_forge/train_expert_maker.py
==================================
Entrena y evalua el meta-modelo creador de expertos (LoRA sobre el 0.5B, CPU).

GATE pre-registrado (antes de correr):
  - PASS v0: >= 60% de specs JSON validas en VAL con el adapter.
  - Si (adapter - base) < 30 puntos, el fine-tune no aporta: reportar honesto.

Uso:
    .\\venv312\\Scripts\\python.exe -m expert_forge.train_expert_maker
        [--steps 300] [--n 150] [--quick]  (--quick: 30 steps para estimar tiempo)
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from expert_forge.expert_maker_dataset import (build_dataset, eval_json_validity,
                                               split_dataset)
from expert_forge.lora_trainer import generate_with_adapter, train_lora

MODEL_DIR = str(Path.home() / ".cognia" / "models_hf" / "qwen2.5-0.5b-instruct")
OUT_DIR = str(Path.home() / ".cognia" / "experts" / "meta_maker_adapter")


def _eval_outputs(model_dir: str, adapter_dir: str | None, val: list[dict],
                  max_new: int = 120) -> list[str]:
    """Genera las specs para cada prompt de val (greedy CPU)."""
    outs = []
    for i, ex in enumerate(val):
        text = generate_with_adapter(model_dir, adapter_dir, ex["prompt"],
                                     max_new_tokens=max_new)
        outs.append(text or "")
        print(f"  eval {i + 1}/{len(val)}", flush=True)
    return outs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=300)
    ap.add_argument("--n", type=int, default=150)
    ap.add_argument("--quick", action="store_true", help="30 steps (estimacion)")
    args = ap.parse_args()
    steps = 30 if args.quick else args.steps

    data = build_dataset(n=args.n)
    train, val = split_dataset(data)
    print(f"dataset: {len(train)} train / {len(val)} val | steps={steps}", flush=True)

    t0 = time.time()
    res = train_lora(MODEL_DIR, train, OUT_DIR, steps=steps, seq_len=384,
                     progress_fn=lambda s, tot, l: (
                         print(f"  step {s}/{tot} loss {l:.4f}", flush=True)
                         if s % 10 == 0 else None))
    t_train = time.time() - t0
    print(f"train: loss {res['initial_loss']:.4f} -> {res['final_loss']:.4f} "
          f"| rank {res['rank']} | {t_train / 60:.1f} min", flush=True)

    print("eval BASE (sin adapter):", flush=True)
    base_outs = _eval_outputs(MODEL_DIR, None, val)
    base_pct = eval_json_validity(base_outs)

    print("eval ADAPTER:", flush=True)
    ada_outs = _eval_outputs(MODEL_DIR, res["adapter_dir"], val)
    ada_pct = eval_json_validity(ada_outs)

    reporte = {
        "steps": steps, "rank": res["rank"],
        "initial_loss": round(res["initial_loss"], 4),
        "final_loss": round(res["final_loss"], 4),
        "train_min": round(t_train / 60, 1),
        "val_n": len(val),
        "json_valido_base_pct": round(base_pct * 100, 1),
        "json_valido_adapter_pct": round(ada_pct * 100, 1),
        "delta_pp": round((ada_pct - base_pct) * 100, 1),
        "gate_pass_60pct": ada_pct >= 0.60,
        "adapter_aporta_30pp": (ada_pct - base_pct) >= 0.30,
        "adapter_dir": res["adapter_dir"],
    }
    print("### REPORTE ###", flush=True)
    print(json.dumps(reporte, indent=2, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
