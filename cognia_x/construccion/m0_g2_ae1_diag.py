r"""
DIAGNÓSTICO G2 (regla 10×): ¿por qué la ATENCIÓN PURA no aprende el recall a escala?

El sweep dio ~0.09-0.10 (azar 0.031) para TODAS las configs, incluida atención pura (100%). Como la
atención pura es el mejor caso posible para recall asociativo, "nada cruza" = undertraining/optimización,
NO arquitectura. Este script aísla la causa probando atención pura (attn_every=1) con:
  1) L4 + lr=3e-4 fp32  — SANITY: pure-attn shallow DEBE aprender si la tarea+código están bien a escala d=256.
  2) L12 + lr=3e-4 fp32 — deep + LR más bajo.
  3) L12 + lr=1e-4 fp32 — deep + LR mucho más bajo.
Sin plateau-stop (patience inf, no matar late-learners), early-stop al 0.9, deadline por variante.
Si (1) aprende y (2/3) no -> el 12-capas necesita LR/schedule (hallazgo de ENTRENABILIDAD, clave para el
harness). Si (1) tampoco -> bug más profundo (tarea/código a escala). Reutiliza train_one (single source).
"""
import argparse
import json
import time

import torch

from m0_g2_recall_colab import train_one


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cpu":
        torch.set_num_threads(3)

    base = dict(d_model=256, n_heads=8, n_layers=12, n_keys=256, n_vals=32, n_pairs=32,
                n_queries=16, batch=64, lr=1e-3)
    if args.smoke:
        base = dict(base, d_model=64, n_heads=4, n_keys=64, n_vals=16, n_pairs=12, n_queries=8, batch=32)
        steps, perdl = 120, 60
        variants = [("sanity_L4_lr3e4", dict(n_layers=4, lr=3e-4), False)]
    else:
        steps, perdl = 6000, 450
        variants = [
            ("sanity_L4_lr3e4_fp32", dict(n_layers=4, lr=3e-4), False),
            ("deep_L12_lr3e4_fp32",  dict(n_layers=12, lr=3e-4), False),
            ("deep_L12_lr1e4_fp32",  dict(n_layers=12, lr=1e-4), False),
        ]

    def log(s):
        print(s, flush=True)

    runs = []
    t0 = time.time()
    for name, over, amp in variants:
        p = dict(base); p.update(over)
        dl = time.time() + perdl
        try:
            r = train_one(name, 1, "linear_first", 1.0, p, steps, 200, device, 0, dl, log,
                          early_stop=0.9, amp=amp, use_compile=False, patience=10**9)
        except Exception as e:  # noqa: BLE001
            log(f"[{name}] ERROR {e!r}")
            r = {"name": name, "error": repr(e)}
        r["lr"] = p["lr"]; r["n_layers"] = p["n_layers"]
        runs.append(r)
        with open("g2_ae1_diag_results.json", "w", encoding="utf-8") as f:
            json.dump({"runs": runs}, f, indent=2, ensure_ascii=False)

    print("\n===== DIAGNÓSTICO ae1 (atención pura) — ¿aprende el recall? =====", flush=True)
    for r in runs:
        if "final_acc" in r:
            print(f"  {r['name']:>22} L={r['n_layers']} lr={r['lr']} -> final {r['final_acc']} best {r.get('best_acc')}",
                  flush=True)
    print(f"[diag] {round((time.time()-t0)/60,1)} min", flush=True)
    print(">>> DIAG JSON:")
    print(json.dumps({"runs": runs}, ensure_ascii=False))


if __name__ == "__main__":
    main()
