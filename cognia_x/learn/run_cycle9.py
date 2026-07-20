"""
CYCLE 9 — "ir más allá": aprendizaje por CURIOSIDAD/SORPRESA (mecanismo creativo).

Hipótesis (transformación cotidiana): el estudiante experto no recopia el libro entero; solo subraya
las frases que lo SORPRENDEN. Si la IA aplica gradiente SOLO a los bytes sorprendentes (mayor pérdida
= lo novedoso) y deja intacto el ~50-75% redundante, debería **aprender lo nuevo arrastrando MENOS
los pesos** → menos olvido de lo viejo, a igual presupuesto de pasos.

Compara 3 brazos a IGUAL nº de pasos, sin compuerta ni replay (para aislar el efecto del mecanismo):
  - naive        : supervisión densa (todos los bytes).
  - sorpresa-50  : gradiente solo en el 50% de bytes de mayor pérdida.
  - sorpresa-25  : gradiente solo en el 25% de mayor pérdida.
Mide: cuánto APRENDE lo nuevo (val cross-book ↓) vs cuánto OLVIDA el español (val español ↑).
FALSADOR: si sorpresa NO reduce el olvido del español a igual ganancia en lo nuevo, la idea cae.

Uso: python -m cognia_x.learn.run_cycle9 [--base_steps N] [--learn_steps N] [--smoke]
"""
import argparse
import copy
import json
import os
import sys

import torch

from cognia_x.model.hybrid import HybridConfig, HybridLM
from cognia_x.train.charlm import get_batch, load_corpus_dir
from cognia_x.learn.continual import (eval_at, freeze_recall_trunk, learn_steps,
                                      learn_steps_surprise)
from cognia_x.learn.run_cycle8 import book, tt, split

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CORPUS = os.path.join(ROOT, "cognia_x", "data", "corpus")
RUN_DIR = os.path.join(ROOT, "cognia_x", "runs", "cycle9")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--base_steps", type=int, default=3500)
    ap.add_argument("--learn_steps", type=int, default=500)
    ap.add_argument("--d_model", type=int, default=128)
    ap.add_argument("--n_layers", type=int, default=4)
    ap.add_argument("--L", type=int, default=160)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--lr", type=float, default=5e-4)
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    if args.smoke:
        args.base_steps, args.learn_steps = 500, 150

    torch.set_num_threads(3)
    os.makedirs(RUN_DIR, exist_ok=True)
    logf = open(os.path.join(RUN_DIR, "run.log"), "a", encoding="utf-8")

    def log(s):
        print(s, flush=True)
        logf.write(s + "\n"); logf.flush()

    docs = load_corpus_dir(CORPUS)
    en, es = book(docs, "en_alice"), book(docs, "es_49836")
    nt, nv = book(docs, "en_frankenstein"), book(docs, "en_dracula")
    if not all([en, es, nt, nv]):
        log("[cycle9] faltan libros; corré get_corpus"); return
    en_tr, en_va = split(en)
    es_tr, es_va = split(es)
    en_tr_t, es_tr_t = tt(en_tr), tt(es_tr)
    es_va_t, new_tr, new_va = tt(es_va), tt(nt), tt(nv)

    torch.manual_seed(0)
    cfg = HybridConfig(vocab_size=256, d_model=args.d_model, n_layers=args.n_layers,
                       n_heads=4, window=args.L + 1, attn_every=4, max_seq_len=args.L)
    base = HybridLM(cfg)
    opt = torch.optim.AdamW(base.parameters(), lr=args.lr, weight_decay=0.01)
    log(f"[cycle9] entrenando base ({base.num_params():,} params) {args.base_steps} pasos (ingles+espanol)...")
    base.train()
    for s in range(1, args.base_steps + 1):
        if s <= 150:
            for g in opt.param_groups:
                g["lr"] = args.lr * s / 150
        src = en_tr_t if s % 2 == 0 else es_tr_t
        x, y = get_batch(src, args.batch, args.L, "cpu")
        _, loss = base(x, y)
        opt.zero_grad(); loss.backward()
        torch.nn.utils.clip_grad_norm_(base.parameters(), 1.0); opt.step()
    b_es = eval_at(base, es_va_t, args.L, "cpu")
    b_new = eval_at(base, new_va, args.L, "cpu")
    log(f"[cycle9] base listo. espanol {b_es:.3f} | nuevo {b_new:.3f}")

    def run_arm(kind, lo=None, hi=None):
        m = copy.deepcopy(base)
        if kind == "congelar":
            trainable = freeze_recall_trunk(m)
            o = torch.optim.AdamW(trainable, lr=args.lr, weight_decay=0.01)
            learn_steps(m, o, new_tr, args.learn_steps, args.L, args.batch, "cpu")
        elif kind == "naive":
            o = torch.optim.AdamW(m.parameters(), lr=args.lr, weight_decay=0.01)
            learn_steps(m, o, new_tr, args.learn_steps, args.L, args.batch, "cpu")
        else:
            o = torch.optim.AdamW(m.parameters(), lr=args.lr, weight_decay=0.01)
            learn_steps_surprise(m, o, new_tr, args.learn_steps, args.L, args.batch, "cpu",
                                 low_q=lo, high_q=hi)
        new_a = eval_at(m, new_va, args.L, "cpu")
        es_a = eval_at(m, es_va_t, args.L, "cpu")
        r = {"new_before": round(b_new, 4), "new_after": round(new_a, 4),
             "new_gain": round(b_new - new_a, 4), "es_before": round(b_es, 4),
             "es_after": round(es_a, 4), "es_forget": round(es_a - b_es, 4)}
        log(f"[cycle9] {kind:>14}: aprende nuevo {r['new_gain']:+.3f} (gain) | OLVIDA espanol {r['es_forget']:+.3f}")
        return r

    results = {"base": {"espanol": round(b_es, 4), "nuevo": round(b_new, 4)},
               "naive": run_arm("naive"),
               "banda_50_95": run_arm("s", 0.5, 0.95),        # sorpresa (refutada): contraste
               "congelar_tronco": run_arm("congelar")}        # congelar embed+atención (anti-olvido)
    with open(os.path.join(RUN_DIR, "summary.json"), "w", encoding="utf-8") as f:
        json.dump({"config": vars(args), "results": results}, f, indent=2)

    log("\n[cycle9] ===== RESUMEN: aprender arrastrando MENOS los pesos viejos =====")
    log(f"  {'brazo':>15} | {'gana nuevo':>10} | {'olvida esp':>10} | eficiencia (gana/olvida)")
    for k in ("naive", "banda_50_95", "congelar_tronco"):
        r = results[k]
        eff = r["new_gain"] / max(0.001, abs(r["es_forget"]))
        log(f"  {k:>15} | {r['new_gain']:>+10.3f} | {r['es_forget']:>+10.3f} | {eff:>6.2f}")
    log("  -> si sorpresa olvida MENOS a igual ganancia, la curiosidad concentra la señal (idea apoyada).")
    logf.close()


if __name__ == "__main__":
    main()
