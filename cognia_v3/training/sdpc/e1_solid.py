"""
E1 "sólido": corre el experimento completo con múltiples seeds.
Criterio de PASS sólido: ratio SDPC/BP >= 0.95 en TODAS las seeds
(no alcanza con una corrida afortunada).

Run: .\\venv312\\Scripts\\python.exe -m cognia_v3.training.sdpc.e1_solid
"""
import json
import datetime
from pathlib import Path

from cognia_v3.training.sdpc.e1_mnist import run_e1, EVAL_DIR

SEEDS = [42, 7, 123]


def main():
    runs = []
    for seed in SEEDS:
        print(f"\n################ SEED {seed} ################")
        out = run_e1(epochs=5, batch_size=64, sdpc_lr=1e-3, seed=seed)
        runs.append({"seed": seed, "ratio": out["ratio"],
                     "sdpc": out["sdpc_final_test_acc"], "bp": out["bp_final_test_acc"]})

    ratios = [r["ratio"] for r in runs]
    solid_pass = all(r >= 0.95 for r in ratios)
    print("\n================ E1 SOLID ================")
    for r in runs:
        print(f"  seed {r['seed']:4d}: SDPC={r['sdpc']:.4f} BP={r['bp']:.4f} ratio={r['ratio']:.4f}")
    print(f"  min ratio: {min(ratios):.4f}  |  mean: {sum(ratios)/len(ratios):.4f}")
    verdict = "SOLID PASS" if solid_pass else "NOT SOLID (alguna seed < 0.95)"
    print(f"  VERDICT: {verdict}")

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    path = Path(EVAL_DIR) / f"sdpc_e1_solid_{ts}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"timestamp": datetime.datetime.now().isoformat(),
                   "seeds": SEEDS, "runs": runs, "min_ratio": min(ratios),
                   "verdict": verdict}, f, indent=2)
    print(f"Saved: {path}")


if __name__ == "__main__":
    main()
