"""
Orquestador del entrenamiento nocturno de Cognia-X v0. Corre hasta el deadline y deja
checkpoints + resultados en cognia_x/runs/overnight_v0/. Pensado para correr SIN atender.

Fase 1 — recall: entrena lineal-puro vs hibrido vs atencion-pura y compara accuracy de recall
          (cierra H-MEZ-4 end-to-end, la pregunta abierta del ciclo-2).
Fase 2 — char-LM: entrena el hibrido byte-level sobre el texto local; loss + muestras.

Uso:
  python -m cognia_x.train.run_overnight --deadline <epoch>
  python -m cognia_x.train.run_overnight --smoke      (verificacion rapida ~2 min)
"""
import argparse
import json
import os
import sys
import time
import traceback

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import torch  # noqa: E402

RUN_DIR = os.path.join(REPO_ROOT, "cognia_x", "runs", "overnight_v0")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deadline", type=float, default=0.0, help="epoch (s) a partir del cual parar")
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()

    torch.set_num_threads(3)  # vault: 3 hilos optimo en i3-10110U
    os.makedirs(RUN_DIR, exist_ok=True)
    logpath = os.path.join(RUN_DIR, "run.log")

    def log(msg):
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        print(line, flush=True)
        with open(logpath, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    if args.smoke:
        deadline = time.time() + 120
    elif args.deadline > 0:
        deadline = args.deadline
    else:
        deadline = time.time() + 3600

    log(f"=== Cognia-X overnight v0 === smoke={args.smoke} | quedan {int(deadline-time.time())}s")
    log(f"torch {torch.__version__} | threads={torch.get_num_threads()}")

    summary = {"smoke": args.smoke, "phases": {}, "started": time.time()}

    # ---- FASE 1: recall (cierra H-MEZ-4 end-to-end) ----
    try:
        from cognia_x.train import recall_task
        steps = 30 if args.smoke else 2500
        recall_dl = None if args.smoke else time.time() + min(0.4 * (deadline - time.time()), 5400)
        rem = int(recall_dl - time.time()) if recall_dl else 0
        log(f"--- FASE 1: recall (steps={steps}, presupuesto_recall={rem}s) ---")
        res = recall_task.run_comparison(steps, log, seed=0, deadline=recall_dl)
        summary["phases"]["recall"] = res
        with open(os.path.join(RUN_DIR, "recall_results.json"), "w", encoding="utf-8") as fh:
            json.dump(res, fh, indent=2, ensure_ascii=False)
        accs = {r.get("name"): round(r["final_acc"], 3) for r in res if "final_acc" in r}
        log(f"[recall] RESUMEN accuracy: {accs}")
    except Exception:
        log("FASE 1 ERROR:\n" + traceback.format_exc())

    # ---- FASE 2: char-LM (aprende lenguaje) ----
    try:
        from cognia_x.train import charlm
        log("--- FASE 2: char-LM ---")
        if args.smoke:
            res = charlm.train(REPO_ROOT, RUN_DIR, log, deadline=time.time() + 200,
                               d_model=96, n_layers=4, n_heads=4, L=96, batch=8,
                               ckpt_every=8, sample_every=8, max_steps=16)
        else:
            res = charlm.train(REPO_ROOT, RUN_DIR, log, deadline=deadline)
        summary["phases"]["charlm"] = res
    except Exception:
        log("FASE 2 ERROR:\n" + traceback.format_exc())

    summary["finished"] = time.time()
    with open(os.path.join(RUN_DIR, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, ensure_ascii=False, default=str)
    log("=== FIN ===")


if __name__ == "__main__":
    main()
