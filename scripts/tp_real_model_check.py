"""
scripts/tp_real_model_check.py
==============================
Phase 3 REAL-WEIGHTS check: run the tensor-parallel engine on the actual
Qwen2.5-Coder-3B INT4 shards on disk and verify it generates the IDENTICAL
greedy token sequence as the single-device reference.

This is the strongest correctness gate for the rediseño: not random weights, but
the production model. Qwen2.5-Coder-3B has n_kv_heads=2, so the meaningful TP
degree is 2 (the North Star minimum). If the tokenizer is present the generated
continuation is decoded to text so the output is human-checkable.

Usage:
    venv312\\Scripts\\python.exe scripts\\tp_real_model_check.py
    venv312\\Scripts\\python.exe scripts\\tp_real_model_check.py --shard-dir model_shards/qwen-coder-3b-q4 --n-new 8
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

import numpy as np  # noqa: E402

from shattering.tp_engine import (  # noqa: E402
    load_qwen_int4_model, generate_reference, generate_tp,
)
from shattering.model_constants import (  # noqa: E402
    COGNIA_SYSTEM_PROMPT, QWEN_SYSTEM_PROMPT, QWEN_USER_PROMPT,
)


def _load_tokenizer(shard_dir: str):
    try:
        from tokenizers import Tokenizer
        tok_path = os.path.join(shard_dir, "tokenizer.json")
        if os.path.exists(tok_path):
            return Tokenizer.from_file(tok_path)
    except Exception:
        pass
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard-dir", default="model_shards/qwen-coder-3b-q4")
    ap.add_argument("--n-new", type=int, default=8)
    ap.add_argument("--tp", type=int, default=2)
    ap.add_argument("--user", default="Escribe una funcion en Python que sume dos numeros.")
    args = ap.parse_args()

    print("=== Phase 3: tensor-parallel on the REAL Qwen2.5-Coder-3B INT4 ===")
    t0 = time.perf_counter()
    model = load_qwen_int4_model(args.shard_dir)
    print(f"loaded {len(model.layers)} layers from {args.shard_dir} in {time.perf_counter()-t0:.1f}s")

    tok = _load_tokenizer(args.shard_dir)
    if tok is not None:
        text = (QWEN_SYSTEM_PROMPT.format(system=COGNIA_SYSTEM_PROMPT)
                + QWEN_USER_PROMPT.format(user=args.user))
        prompt_ids = list(tok.encode(text).ids)
        print(f"tokenizer: OK ({len(prompt_ids)} prompt tokens)")
    else:
        prompt_ids = [40, 1234, 5, 99, 500, 71, 8]
        print("tokenizer: not found -> using fixed token-id prompt (ids only, no text)")

    t0 = time.perf_counter()
    ref = generate_reference(model, prompt_ids, args.n_new, session_id="real_ref")
    t_ref = time.perf_counter() - t0

    t0 = time.perf_counter()
    tp = generate_tp(model, prompt_ids, args.n_new, tp_degree=args.tp, session_id="real_tp")
    t_tp = time.perf_counter() - t0

    match = tp == ref
    print(f"\n  reference (single-device): {ref}")
    print(f"  TP={args.tp} (in-process)  : {tp}")
    if tok is not None:
        print(f"\n  reference text: {tok.decode(ref)!r}")
        print(f"  TP={args.tp} text     : {tok.decode(tp)!r}")
    print(f"\n  timing (in-process, NOT the LAN thesis): ref {t_ref:.1f}s, TP={args.tp} {t_tp:.1f}s")
    print(f"  tokens {'MATCH' if match else 'DIVERGE'}")
    print(f"\nCHECK: {'PASS' if match else 'FAIL'}")
    return 0 if match else 1


if __name__ == "__main__":
    sys.exit(main())
