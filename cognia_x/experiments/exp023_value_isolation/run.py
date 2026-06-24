r"""
exp023 — CYCLE 36 / H-V4-1b: ¿el VALOR (info-gain) está AISLADO de la "intervención activa per se"?

Contexto (deriva de exp022/CYCLE 35): H-V4-1 salió MIXTA. exp022 demostró R-INTERVENCIÓN (el agente
PASIVO queda plano bajo intervención; los ACTIVOS identifican la causa) pero NO aisló el VALOR: el
azar-activo (C) alcanzaba al info-gain (B) con presupuesto suficiente porque el mundo era chico y el azar
lo cubría. La pregunta hija: en un régimen DURO — donde el azar NO pueda cubrir por fuerza bruta — ¿el
VALOR endógeno (info-gain) le gana al azar-activo? Eso aislaría R-VALOR del mero "actuar".

RÉGIMEN DURO (vs exp022: D=12, clúster=4, p_obs=0.10):
  D=40 features, CLÚSTER confundido de 8 (1 causa + 7 espurias indistinguibles sin intervención),
  ruido de observación p_obs=0.25 (alto: cada observación es débil -> la EFICIENCIA de muestreo importa),
  presupuesto K ajustado al espacio. Misma mecánica/agentes que exp022 (REUTILIZADOS): tres políticas con
  idéntica clase de modelo (posterior bayesiano sobre "y=x_i") y update; sólo cambia la política:
    A pasivo (stream observacional), B info-gain (valor endógeno), C azar-activo (ablación de valor).

PREDICCIÓN FALSABLE (pre-registrada ANTES de correr):
  (a) AISLADO / H-V4-1b APOYADA: B (info-gain) supera a C (azar-activo) por margen CLARO (>0.08 en los
      presupuestos chico/medio donde la eficiencia importa; promedio >0.05), y ambos superan a A.
      => el VALOR (no sólo la actividad) es el lever -> R-VALOR sube hacia 'real'.
  (b) NO AISLADO / H-V4-1b REFUTADA: B ~= C aun en este régimen duro (margen máx <=0.05).
      => el lever demostrado es ACTUAR/INTERVENIR, no el valor info-gain. R-VALOR sigue 'asumido' y la
      hipótesis del VALOR específico se reorienta (valor AUTO-generado, no info-gain diseñado).
  (c) MIXTA: separación parcial / dependiente del presupuesto.

Mide además COSTO/VELOCIDAD (objetivo del proyecto): wall-time total y por celda en CPU.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp023_value_isolation.run
  (opcional) --budgets 8,16,32,64,128 --seeds 24 --D 40 --cluster 8 --p_obs 0.25
"""
import argparse
import json
import os
import platform
import sys
import time

import numpy as np

# REUTILIZA el mundo causal y los agentes de exp022 (DRY: misma clase de modelo + update).
from cognia_x.experiments.exp022_endogenous_value.run import (
    make_world, sample_observational, sample_intervention, run_agent, eval_acc,
)

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")


def run(budgets, n_seeds, D, cluster, p_obs, n_test, cand_pool):
    modes = [("A_pasivo", "passive"), ("B_infogain", "infogain"), ("C_aleatorio", "random")]
    mode_offset = {"passive": 1, "infogain": 2, "random": 3}
    per_seed = []
    cell_times = []
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed)
        c, cluster_idx = make_world(rng, D, cluster)
        X_iid = sample_observational(rng, n_test, D, cluster_idx)
        y_iid = X_iid[:, c]
        X_int = sample_intervention(rng, n_test, D)
        y_int = X_int[:, c]
        row = {"seed": seed, "cause": c, "cluster": [int(i) for i in cluster_idx], "by_budget": {}}
        for K in budgets:
            cell = {}
            for name, mode in modes:
                arng = np.random.default_rng(seed * 100003 + K * 101 + mode_offset[mode])
                t0 = time.perf_counter()
                post = run_agent(arng, mode, K, D, c, cluster_idx, p_obs, cand_pool)
                dt = time.perf_counter() - t0
                cell_times.append(dt)
                cell[name] = {
                    "iid": eval_acc(arng, post, X_iid, y_iid),
                    "interv": eval_acc(arng, post, X_int, y_int),
                    "post_on_cause": float(post[c]),
                    "secs": dt,
                }
            row["by_budget"][str(K)] = cell
        per_seed.append(row)

    def agg(K, name, metric):
        vals = [per_seed[s]["by_budget"][str(K)][name][metric] for s in range(n_seeds)]
        return float(np.mean(vals)), float(np.std(vals))

    summary = {"budgets": budgets, "by_budget": {}}
    for K in budgets:
        d = {}
        for name, _ in modes:
            d[name] = {"iid_mean": agg(K, name, "iid")[0],
                       "interv_mean": agg(K, name, "interv")[0],
                       "interv_std": agg(K, name, "interv")[1],
                       "post_on_cause_mean": agg(K, name, "post_on_cause")[0]}
        d["value_margin_B_minus_C"] = d["B_infogain"]["interv_mean"] - d["C_aleatorio"]["interv_mean"]
        d["active_margin_C_minus_A"] = d["C_aleatorio"]["interv_mean"] - d["A_pasivo"]["interv_mean"]
        summary["by_budget"][str(K)] = d

    def at(K, name, metric):
        return summary["by_budget"][str(K)][name][metric]

    # ---- veredicto contra la predicción PRE-REGISTRADA ----
    low_mid = budgets[:max(1, len(budgets) - 1)]   # todos menos el más grande (donde el azar satura)
    margins = [summary["by_budget"][str(K)]["value_margin_B_minus_C"] for K in budgets]
    margins_lowmid = [summary["by_budget"][str(K)]["value_margin_B_minus_C"] for K in low_mid]
    max_margin = max(margins)
    mean_margin = float(np.mean(margins))
    value_clear_lowmid = all(m > 0.08 for m in margins_lowmid)
    both_beat_A = all(at(K, "B_infogain", "interv_mean") - at(K, "A_pasivo", "interv_mean") > 0.15
                      and at(K, "C_aleatorio", "interv_mean") - at(K, "A_pasivo", "interv_mean") > 0.10
                      for K in [budgets[-1]])

    if max_margin <= 0.05:
        verdict = "refutada"   # el valor info-gain NO está aislado: el lever es la acción
    elif value_clear_lowmid and mean_margin > 0.05 and both_beat_A:
        verdict = "apoyada"    # el VALOR (info-gain) está aislado del azar-activo
    else:
        verdict = "mixta"

    summary["prereg_prediction"] = ("APOYADA si B-C>0.08 en presupuestos chico/medio y prom>0.05 (valor "
                                    "aislado); REFUTADA si margen máx<=0.05 (lever=acción, no valor); "
                                    "MIXTA si parcial. Registrada ANTES de correr.")
    summary["value_isolation"] = {
        "margins_B_minus_C_por_budget": {str(K): round(summary["by_budget"][str(K)]["value_margin_B_minus_C"], 4) for K in budgets},
        "max_margin": round(max_margin, 4),
        "mean_margin": round(mean_margin, 4),
        "value_clear_lowmid(>0.08)": value_clear_lowmid,
        "both_active_beat_passive": both_beat_A,
    }
    summary["verdict"] = verdict
    summary["cost"] = {
        "total_agent_runs": len(cell_times),
        "wall_secs_all_agent_runs": round(float(np.sum(cell_times)), 3),
        "mean_secs_per_agent_run": round(float(np.mean(cell_times)), 5),
        "note": "CPU puro (numpy), sin GPU. Cada 'agent run' = aprender un modelo causal completo a presupuesto K.",
    }
    return per_seed, summary


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(prog="python -m cognia_x.experiments.exp023_value_isolation.run")
    ap.add_argument("--budgets", type=str, default="8,16,32,64,128")
    ap.add_argument("--seeds", type=int, default=24)
    ap.add_argument("--D", type=int, default=40)
    ap.add_argument("--cluster", type=int, default=8)
    ap.add_argument("--p_obs", type=float, default=0.25)
    ap.add_argument("--n_test", type=int, default=4000)
    ap.add_argument("--candidates", type=int, default=160)
    args = ap.parse_args(argv)
    budgets = [int(x) for x in args.budgets.split(",")]

    t0 = time.perf_counter()
    per_seed, summary = run(budgets, args.seeds, args.D, args.cluster, args.p_obs,
                            args.n_test, args.candidates)
    wall = time.perf_counter() - t0

    out = {
        "experiment": "exp023_value_isolation",
        "hypothesis": "H-V4-1b",
        "question": ("¿El VALOR endógeno (info-gain) está AISLADO de la intervención activa per se? "
                     "(¿info-gain > azar-activo en un régimen donde el azar NO cubre por fuerza bruta?)"),
        "env": {"python": platform.python_version(), "numpy": np.__version__,
                "platform": platform.platform()},
        "params": {"D": args.D, "cluster": args.cluster, "p_obs": args.p_obs, "budgets": budgets,
                   "seeds": args.seeds, "n_test": args.n_test, "candidates": args.candidates},
        "wall_secs_total": round(wall, 3),
        "per_seed": per_seed,
        "summary": summary,
    }
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    print("=" * 84)
    print("exp023 — H-V4-1b: ¿el VALOR (info-gain) está AISLADO del azar-activo? (régimen duro)")
    print("=" * 84)
    print("params: D={D} clúster={cluster} p_obs={p_obs} seeds={seeds} n_test={n_test}".format(**out["params"]))
    print("")
    print("INTERVENCIÓN (acc causal):")
    print("  {:>6} | {:>13} | {:>13} | {:>13} | {:>9} | {:>9}".format(
        "K", "A_pasivo", "B_infogain", "C_aleatorio", "B-C(valor)", "C-A(activo)"))
    for K in budgets:
        d = summary["by_budget"][str(K)]
        print("  {:>6} | {:>13} | {:>13} | {:>13} | {:>+9.3f} | {:>+9.3f}".format(
            K,
            "{:.3f}±{:.3f}".format(d["A_pasivo"]["interv_mean"], 0.0),
            "{:.3f}±{:.3f}".format(d["B_infogain"]["interv_mean"], d["B_infogain"]["interv_std"]),
            "{:.3f}±{:.3f}".format(d["C_aleatorio"]["interv_mean"], d["C_aleatorio"]["interv_std"]),
            d["value_margin_B_minus_C"], d["active_margin_C_minus_A"]))
    print("")
    print("AISLAMIENTO DEL VALOR:")
    print("  ", json.dumps(summary["value_isolation"], ensure_ascii=False))
    print("COSTO/VELOCIDAD:", json.dumps(summary["cost"], ensure_ascii=False))
    print("  pre-registro:", summary["prereg_prediction"])
    print("  VEREDICTO H-V4-1b :", summary["verdict"].upper())
    print("=" * 84)
    return 0


if __name__ == "__main__":
    sys.exit(main())
