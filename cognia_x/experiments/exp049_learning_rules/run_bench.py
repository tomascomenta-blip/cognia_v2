r"""exp049 — runner: métodos × seeds con presupuesto igual, calidad Y costo. Ver README.md.

USO:
  venv312\Scripts\python.exe -m cognia_x.experiments.exp049_learning_rules.run_bench --smoke
  venv312\Scripts\python.exe -m cognia_x.experiments.exp049_learning_rules.run_bench --methods bp,dfa
"""
import argparse
import importlib
import json
import time

import torch

from cognia_x.experiments.exp049_learning_rules.common import CFG, RESULTS_DIR, load_mnist

METHODS = ["bp", "dfa", "ff", "pc", "dtp", "eqprop", "es"]
SEEDS = [42, 7, 123]


def save(out, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true", help="2000/1000 muestras, 1 epoch, 1 seed")
    ap.add_argument("--methods", type=str, default=",".join(METHODS))
    ap.add_argument("--seeds", type=str, default=None)
    ap.add_argument("--epochs", type=int, default=None)
    ap.add_argument("--out", type=str, default=None)
    args = ap.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cpu":
        torch.set_num_threads(3)
    cfg = dict(CFG, device=device)
    seeds = [int(s) for s in args.seeds.split(",")] if args.seeds else SEEDS
    if args.smoke:
        cfg["epochs"] = 1
        seeds = seeds[:1]
    if args.epochs:
        cfg["epochs"] = args.epochs
    n_train, n_test = (2000, 1000) if args.smoke else (None, None)

    print(f"[exp049] device={device} epochs={cfg['epochs']} seeds={seeds} smoke={args.smoke}", flush=True)
    data = load_mnist(device, n_train, n_test)
    print(f"[exp049] MNIST train={len(data[0])} test={len(data[2])}", flush=True)

    out_path = RESULTS_DIR / (args.out or ("results_smoke.json" if args.smoke else "results.json"))
    out = {"experiment": "exp049_learning_rules", "device": device, "torch": torch.__version__,
           "cfg": {k: v for k, v in cfg.items()}, "seeds": seeds, "methods": {}}
    method_list = [m.strip() for m in args.methods.split(",") if m.strip()]
    bp_wall = bp_acc = None
    if "bp" in method_list:                       # BP primero: es el denominador (y el budget de ES)
        method_list = ["bp"] + [m for m in method_list if m != "bp"]

    for name in method_list:
        print(f"\n==== {name} ====", flush=True)
        try:
            mod = importlib.import_module(f"cognia_x.experiments.exp049_learning_rules.methods.{name}")
        except Exception as e:  # noqa: BLE001
            out["methods"][name] = {"error": f"import: {e!r}"}
            save(out, out_path)
            continue
        runs = []
        for seed in seeds:
            mcfg = dict(cfg)
            if name == "es" and bp_wall:
                mcfg["wall_budget_s"] = 3.0 * bp_wall   # protocolo: ES = 3x el wall de BP
            t0 = time.time()
            try:
                r = mod.train(data, mcfg, seed, log=lambda s: print(s, flush=True))
                r["seed"] = seed
                runs.append(r)
                print(f"  [{name} seed={seed}] test_acc={r['test_acc']:.4f} wall={r['wall_s']}s", flush=True)
            except Exception as e:  # noqa: BLE001
                runs.append({"seed": seed, "error": repr(e)[:400], "wall_s": round(time.time() - t0, 1)})
                print(f"  [{name} seed={seed}] ERROR {e!r}", flush=True)
            save(dict(out, methods=dict(out["methods"], **{name: {"runs": runs}})), out_path)
        ok = [r for r in runs if "test_acc" in r]
        summ = {"runs": runs}
        if ok:
            accs = [r["test_acc"] for r in ok]
            walls = [r["wall_s"] for r in ok]
            summ.update(acc_mean=round(sum(accs) / len(accs), 4), acc_min=round(min(accs), 4),
                        wall_mean_s=round(sum(walls) / len(walls), 1))
            if name == "bp":
                bp_acc, bp_wall = summ["acc_mean"], summ["wall_mean_s"]
            elif bp_acc:
                summ["ratio_vs_bp"] = round(summ["acc_min"] / bp_acc, 4)      # decide el MIN (protocolo)
                summ["cost_vs_bp"] = round(summ["wall_mean_s"] / bp_wall, 2) if bp_wall else None
        out["methods"][name] = summ
        save(out, out_path)

    print("\n==== RESUMEN ====", flush=True)
    for name, s in out["methods"].items():
        if "acc_mean" in s:
            extra = f" ratio_vs_bp={s.get('ratio_vs_bp')} cost_vs_bp={s.get('cost_vs_bp')}x" if name != "bp" else ""
            print(f"  {name:8} acc_mean={s['acc_mean']} acc_min={s['acc_min']} wall={s['wall_mean_s']}s{extra}", flush=True)
        else:
            print(f"  {name:8} SIN RUNS OK", flush=True)
    print(f"\n[exp049] resultados -> {out_path}", flush=True)


if __name__ == "__main__":
    main()
