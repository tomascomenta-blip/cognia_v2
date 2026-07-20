r"""
exp025 — CYCLE 39 / H-V4-1d: ¿el EMPOWERMENT como VALOR hace a un agente MEJOR en una tarea (no solo lo mide)?

Contexto (deriva de CYCLE 38): exp024 mostró el MECANISMO (empowerment aísla lo controlable; predicción
pasiva se queda con el reloj inútil). Falta el paso crítico: que ese valor MEJORE una tarea downstream. Si no
mejora nada, R-VALOR sería una curiosidad de medición, no un lever. H-V4-1d lo pone a prueba.

IDEA RAÍZ (analogía cotidiana): tenés POCA atención y muchas cosas alrededor (tus manos, un reloj, el ruido
de la calle). Para LOGRAR algo (servir un vaso de agua) conviene gastar tu atención en lo que PODÉS AFECTAR
(tus manos), no en lo más predecible (el reloj). Repartir la atención por controlabilidad debería ganarle a
repartirla por predictibilidad.

DISEÑO (numpy puro, CPU; reutiliza exp024). Mundo con factores etiquetados: n_ctrl CONTROLABLES (f'=acción),
n_clock RELOJES (predecibles, NO controlables), n_rand ALEATORIOS. El agente tiene CAPACIDAD LIMITADA k:
sólo puede ATENDER/controlar k de los D factores. Tarea: llevar los factores CONTROLABLES a un objetivo.
  - Un factor controlable ATENDIDO se pone en el objetivo (lo controla).
  - Un factor controlable NO atendido sólo cae en el objetivo por azar (1/K).
  score = (#ctrl atendidos + (n_ctrl - #ctrl atendidos)/K) / n_ctrl.
Tres estrategias de asignación del presupuesto k (qué factores atender):
  - EMPOWERMENT: top-k por empowerment medido (Blahut-Arimoto) -> atiende los controlables.
  - PREDICTIBILIDAD: top-k por predictibilidad medida -> atiende los relojes (inútiles para controlar).
  - AZAR: k al azar.
Se barre la capacidad k.

PREDICCIÓN FALSABLE (pre-registrada):
  (a) APOYADA si a capacidad limitada (k<D) la asignación por EMPOWERMENT logra MÁS tarea que por
      PREDICTIBILIDAD por margen claro (>0.3 en k=n_ctrl) y >= que el azar; y empowerment llega a ~1.0 en
      k=n_ctrl. (Predicción extra: predictibilidad <= azar, porque elegir el reloj es ANTI-útil.)
  (b) REFUTADA si empowerment no supera a predictibilidad por >0.1 (el valor no mejora la tarea).
  (c) MIXTA si parcial.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp025_empowerment_downstream.run
"""
import argparse
import json
import os
import platform
import sys
import time

import numpy as np

from cognia_x.experiments.exp024_empowerment.run import measure_factor

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")


def rank_pick(scores, k, rng):
    """Devuelve los índices top-k por score, con desempate ALEATORIO (no por orden de aparición)."""
    jitter = rng.random(len(scores)) * 1e-9
    order = np.argsort(-(np.asarray(scores) + jitter))
    return list(order[:k])


def run(K, eta, n_ctrl, n_clock, n_rand, samples, caps, seeds):
    kinds = (["ctrl"] * n_ctrl) + (["clock"] * n_clock) + (["rand"] * n_rand)
    D = len(kinds)
    ctrl_idx = set(range(n_ctrl))   # los primeros n_ctrl son controlables
    strategies = ["empowerment", "predictibilidad", "azar"]

    per_seed = []
    for seed in range(seeds):
        rng = np.random.default_rng(seed)
        # medir empowerment y predictibilidad de CADA factor (estimación con muestreo)
        emp = np.zeros(D)
        pred = np.zeros(D)
        for i, kind in enumerate(kinds):
            e, p = measure_factor(rng, kind, K, eta, samples)
            emp[i], pred[i] = e, p

        row = {"seed": seed, "by_cap": {}}
        for k in caps:
            sc = {}
            picks = {
                "empowerment": rank_pick(emp, k, rng),
                "predictibilidad": rank_pick(pred, k, rng),
                "azar": list(rng.permutation(D)[:k]),
            }
            for strat in strategies:
                attended_ctrl = len([i for i in picks[strat] if i in ctrl_idx])
                score = (attended_ctrl + (n_ctrl - attended_ctrl) * (1.0 / K)) / n_ctrl
                sc[strat] = {"score": float(score), "attended_ctrl": attended_ctrl}
            row["by_cap"][str(k)] = sc
        per_seed.append(row)

    def agg(k, strat):
        vals = [per_seed[s]["by_cap"][str(k)][strat]["score"] for s in range(seeds)]
        return float(np.mean(vals)), float(np.std(vals))

    summary = {"D": D, "n_ctrl": n_ctrl, "caps": caps, "by_cap": {}}
    for k in caps:
        d = {}
        for strat in strategies:
            d[strat] = {"score_mean": agg(k, strat)[0], "score_std": agg(k, strat)[1]}
        d["emp_minus_pred"] = d["empowerment"]["score_mean"] - d["predictibilidad"]["score_mean"]
        d["emp_minus_rand"] = d["empowerment"]["score_mean"] - d["azar"]["score_mean"]
        d["pred_minus_rand"] = d["predictibilidad"]["score_mean"] - d["azar"]["score_mean"]
        summary["by_cap"][str(k)] = d

    # veredicto contra el pre-registro. k* = n_ctrl (capacidad justa para los controlables).
    kstar = str(n_ctrl) if n_ctrl in caps else str(caps[len(caps) // 2])

    def at(k, strat, m="score_mean"):
        return summary["by_cap"][k][strat][m]

    emp_beats_pred = (at(kstar, "empowerment") - at(kstar, "predictibilidad")) > 0.3
    emp_ge_rand = (at(kstar, "empowerment") - at(kstar, "azar")) > -0.02
    emp_high_at_kstar = at(kstar, "empowerment") > 0.9
    pred_anti_useful = (at(kstar, "predictibilidad") - at(kstar, "azar")) < 0.0  # elegir el reloj es peor que azar
    refute = (at(kstar, "empowerment") - at(kstar, "predictibilidad")) <= 0.1

    if refute:
        verdict = "refutada"
    elif emp_beats_pred and emp_ge_rand and emp_high_at_kstar:
        verdict = "apoyada"
    else:
        verdict = "mixta"

    summary["kstar"] = kstar
    summary["checks"] = {
        "emp_beats_pred_at_kstar(>0.3)": emp_beats_pred,
        "emp_ge_rand_at_kstar": emp_ge_rand,
        "emp_high_at_kstar(>0.9)": emp_high_at_kstar,
        "pred_anti_useful(pred<rand)": pred_anti_useful,
        "REFUTE_emp_not_beats_pred(<=0.1)": refute,
    }
    summary["interpretation"] = (
        "Si APOYADA: repartir un presupuesto de atención/control LIMITADO por EMPOWERMENT (controlabilidad) "
        "logra la tarea; repartirlo por PREDICTIBILIDAD falla (se va al reloj) — incluso PEOR que al azar. "
        "=> el valor endógeno (empowerment) no sólo MIDE: MEJORA al agente en una tarea, barato. Es R-VALOR "
        "APLICADO. Límite honesto: tarea tabular de juguete; el salto a lenguaje sigue pendiente (integrador)."
    )
    summary["verdict"] = verdict
    return per_seed, summary


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(prog="python -m cognia_x.experiments.exp025_empowerment_downstream.run")
    ap.add_argument("--K", type=int, default=4)
    ap.add_argument("--eta", type=float, default=0.05)
    ap.add_argument("--n_ctrl", type=int, default=4)
    ap.add_argument("--n_clock", type=int, default=4)
    ap.add_argument("--n_rand", type=int, default=4)
    ap.add_argument("--samples", type=int, default=4000)
    ap.add_argument("--caps", type=str, default="2,4,6,8,12")
    ap.add_argument("--seeds", type=int, default=12)
    args = ap.parse_args(argv)
    caps = [int(x) for x in args.caps.split(",")]

    t0 = time.perf_counter()
    per_seed, summary = run(args.K, args.eta, args.n_ctrl, args.n_clock, args.n_rand,
                            args.samples, caps, args.seeds)
    wall = time.perf_counter() - t0

    out = {
        "experiment": "exp025_empowerment_downstream",
        "hypothesis": "H-V4-1d",
        "question": ("¿Asignar un presupuesto de atención/control LIMITADO por EMPOWERMENT mejora una tarea "
                     "vs asignarlo por predictibilidad o al azar?"),
        "env": {"python": platform.python_version(), "numpy": np.__version__, "platform": platform.platform()},
        "params": {"K": args.K, "eta": args.eta, "n_ctrl": args.n_ctrl, "n_clock": args.n_clock,
                   "n_rand": args.n_rand, "samples": args.samples, "caps": caps, "seeds": args.seeds},
        "wall_secs": round(wall, 3),
        "per_seed": per_seed,
        "summary": summary,
    }
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    print("=" * 84)
    print("exp025 — H-V4-1d: empowerment como VALOR mejora una tarea (asignación de capacidad limitada)")
    print("=" * 84)
    print("params: D={D} n_ctrl={n_ctrl} (clock={n_clock}, rand={n_rand}) K={K} seeds={seeds}".format(
        D=args.n_ctrl + args.n_clock + args.n_rand, **out["params"]))
    print("")
    print("TAREA (score = fracción de controlables llevados al objetivo):")
    print("  {:>5} | {:>14} | {:>16} | {:>10} | {:>10}".format(
        "cap k", "EMPOWERMENT", "PREDICTIBILIDAD", "AZAR", "emp-pred"))
    for k in caps:
        d = summary["by_cap"][str(k)]
        print("  {:>5} | {:>14} | {:>16} | {:>10} | {:>+10.3f}".format(
            k,
            "{:.3f}±{:.3f}".format(d["empowerment"]["score_mean"], d["empowerment"]["score_std"]),
            "{:.3f}±{:.3f}".format(d["predictibilidad"]["score_mean"], d["predictibilidad"]["score_std"]),
            "{:.3f}".format(d["azar"]["score_mean"]),
            d["emp_minus_pred"]))
    print("")
    print("k* =", summary["kstar"])
    for kk, vv in summary["checks"].items():
        print("  CHECK  {:<36} = {}".format(kk, vv))
    print("")
    print("  costo: {:.3f}s CPU".format(wall))
    print("  INTERPRETACIÓN:", summary["interpretation"])
    print("  VEREDICTO H-V4-1d :", summary["verdict"].upper())
    print("=" * 84)
    return 0


if __name__ == "__main__":
    sys.exit(main())
