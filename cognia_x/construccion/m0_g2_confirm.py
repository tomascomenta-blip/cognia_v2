r"""
G2 CONFIRM — verificación dirigida de las configs CRÍTICAS (regla 10×: no aceptar un "no cruza" del sweep
sin descartar undertraining y el efecto de AMP fp16 en la CALIDAD del recall).

Cuándo se usa: si el sweep `m0_g2_recall_colab.py` deja un veredicto ambiguo (p.ej. ni la atención-pura
cruza 0.8), este script entrena SOLO las configs que importan (atención-pura ae1 y mitad ae2) con MÁS
pasos y compara fp16(AMP) vs fp32, para separar 3 causas posibles de un "no cruza":
  (a) la arquitectura no puede (verdadero techo)   -> fp32 tampoco cruza ni con más pasos
  (b) undertraining                                 -> con más pasos cruza
  (c) AMP fp16 degradó la precisión del matching    -> fp32 cruza pero fp16 no (=> AMP NO es neutral aquí)

Reutiliza train_one del sweep (single source). Importa de m0_g2_recall_colab.
USO (T4): %run m0_g2_confirm.py   |   CPU smoke: venv312\...python m0_g2_confirm.py --smoke
"""
import argparse
import json
import time

import torch

from m0_g2_recall_colab import train_one


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--steps", type=int, default=15000)
    args = ap.parse_args()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cpu":
        torch.set_num_threads(3)

    if args.smoke:
        p = dict(d_model=64, n_heads=4, n_layers=4, n_keys=64, n_vals=16, n_pairs=12, n_queries=8, batch=32, lr=1e-3)
        steps, warmup = 200, 20
    else:
        p = dict(d_model=256, n_heads=8, n_layers=12, n_keys=256, n_vals=32, n_pairs=32, n_queries=16, batch=64, lr=1e-3)
        steps, warmup = args.steps, 200

    def log(s):
        print(s, flush=True)

    t0 = time.time()
    runs = []
    # configs CRÍTICAS: atención-pura (ae1=100%) y mitad (ae2=50%); fp16(AMP) y fp32; SIN plateau early-stop
    # (patience enorme) para no matar late-learners; deadline generoso.
    for amp in [True, False]:
        for ae, nm in [(1, "attn_pura"), (2, "mitad")]:
            name = f"{nm}_ae{ae}_{'fp16' if amp else 'fp32'}"
            dl = time.time() + (4000 if not args.smoke else 120)
            r = train_one(name, ae, "linear_first", 1.0, p, steps, warmup, device, 0, dl, log,
                          amp=amp, use_compile=False, patience=10**9)  # patience inf => sin plateau-stop
            runs.append(r)
            with open("g2_confirm_results.json", "w", encoding="utf-8") as f:
                json.dump({"runs": runs, "steps": steps, "p": p}, f, indent=2, ensure_ascii=False)

    print("\n===== G2 CONFIRM — atención cruza recall? (fp16 vs fp32) =====", flush=True)
    for r in runs:
        print(f"  {r['name']:>22} attn={r['attn_frac']:.0%} amp={r.get('amp')} "
              f"final_acc={r['final_acc']} best={r.get('best_acc')}", flush=True)
    print(f"[confirm] {round((time.time()-t0)/60,1)} min", flush=True)
    print(">>> CONFIRM JSON:")
    print(json.dumps({"runs": runs, "steps": steps}, ensure_ascii=False))


if __name__ == "__main__":
    main()
