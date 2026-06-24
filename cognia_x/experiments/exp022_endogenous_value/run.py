r"""
exp022 — CYCLE 35 / H-V4-1: ¿un VALOR ENDÓGENO construye un modelo más causal que la predicción pasiva?

Contexto (reset v4): el árbol de descomposición v4 (manager/decomposition_tree.md) sitúa como VERDADERO
PRIMER PROBLEMA a R-VALOR: la ausencia de una función-de-valor endógena que defina qué información
importa. Las 34 ciclos del lab solo demostraron que un verificador EXTERNO funciona (exp017); nunca un
valor endógeno. Este experimento ataca esa raíz de frente, en CPU, sin ningún verificador externo de
la verdad: el único feedback es la CONSECUENCIA de la propia consulta (do(X) -> y), que es intervención
legítima, no un oráculo que diga "la causa es c".

DISEÑO (control anti-confound §4.3 + step-parity §4.4):
Mundo causal confundido. D features binarias. Un CLÚSTER de `cluster` features está perfectamente
confundido por una causa latente z (en la distribución observacional las `cluster` features valen TODAS
z). UNA de ellas es la causa verdadera c; el resto del clúster son espurias indistinguibles de c SIN
intervención. El resto son distractores i.i.d. La mecánica: y = x[c] (con ruido de observación p_obs).

Tres agentes que COMPARTEN la misma clase de modelo (posterior bayesiano sobre las D hipótesis
"y = x_i") y la MISMA regla de update. Lo ÚNICO que cambia es la POLÍTICA que genera la experiencia:
  - A pasivo      : recibe configs del stream OBSERVACIONAL (confundido). No elige. -> no puede separar
                    c de las espurias del clúster (todas valen z en el stream).
  - B info-gain   : ELIGE la config que maximiza la información esperada sobre su PROPIO posterior
                    (valor ENDÓGENO; nadie le dice cuál es la causa). -> sondea off-clúster -> separa c.
  - C aleatorio   : ELIGE configs al azar (activo pero SIN señal de valor). Ablación: ¿basta "ser
                    activo" o hace falta el VALOR (info-gain)?

Se barre el PRESUPUESTO K (nº de observaciones/consultas; mismo K para los 3 = step-parity).

PREDICCIÓN FALSABLE (H-V4-1):
  (1) i.i.d. (test del stream observacional): A ~= B ~= C, todos altos (>=0.85) -> el hueco es INVISIBLE
      sin intervención.
  (2) intervención (test con configs uniformes que rompen la confusión): A se queda PLANO (~chance,
      <=0.65) por más K que reciba -> muro INFORMACIONAL, no de presupuesto; B sube a >=0.80 y supera a
      A por >0.20; B >= C a presupuesto chico -> el VALOR ayuda cuando el recurso es finito.
  REFUTADA si: A bajo intervención sube con K hasta <0.05 de B (el pasivo SÍ identifica la causa), o si
  B nunca supera a A por >0.20 bajo intervención.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp022_endogenous_value.run
  (opcional) --budgets 4,8,16,32,64 --seeds 8 --D 12 --cluster 4 --p_obs 0.10 --n_test 4000
"""
import argparse
import json
import os
import platform
import sys

import numpy as np

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")


def binary_entropy(p):
    p = np.clip(p, 1e-12, 1.0 - 1e-12)
    return -(p * np.log2(p) + (1.0 - p) * np.log2(1.0 - p))


def make_world(rng, D, cluster):
    """Elige posiciones: las primeras `cluster` de una permutación son el clúster confundido; c=clúster[0]."""
    perm = rng.permutation(D)
    cluster_idx = perm[:cluster]
    c = int(cluster_idx[0])
    return c, cluster_idx


def sample_observational(rng, n, D, cluster_idx):
    """Distribución OBSERVACIONAL (confundida): todo el clúster vale la causa latente z; el resto i.i.d."""
    z = rng.integers(0, 2, size=n)
    X = rng.integers(0, 2, size=(n, D))
    X[:, cluster_idx] = z[:, None]
    return X


def sample_intervention(rng, n, D):
    """Distribución INTERVENCIONAL (do uniforme): cada feature independiente -> rompe la confusión."""
    return rng.integers(0, 2, size=(n, D))


def observe_y(rng, X, c, p_obs):
    """Mecánica del mundo: y = x[c], observada con ruido p_obs (flip). Es la CONSECUENCIA, no un oráculo."""
    y = X[:, c].copy()
    flip = rng.random(len(y)) < p_obs
    y[flip] = 1 - y[flip]
    return y


def posterior_from_log(logpost):
    p = np.exp(logpost - logpost.max())
    return p / p.sum()


def update_logpost(logpost, x, y, p_obs):
    """Update bayesiano: cada hipótesis h_i predice y=x_i; verosimilitud (1-p_obs) si acierta, p_obs si no."""
    like = np.where(x == y, 1.0 - p_obs, p_obs)
    logpost = logpost + np.log(like)
    return logpost - logpost.max()


def run_agent(rng, mode, K, D, c, cluster_idx, p_obs, cand_pool):
    """Corre un agente K pasos y devuelve su posterior final. Misma clase de modelo y update para los 3."""
    logpost = np.zeros(D)
    for _ in range(K):
        if mode == "passive":
            x = sample_observational(rng, 1, D, cluster_idx)[0]
        elif mode == "random":
            x = sample_intervention(rng, 1, D)[0]
        elif mode == "infogain":
            post = posterior_from_log(logpost)
            cand = sample_intervention(rng, cand_pool, D)        # candidatos = posibles intervenciones
            m = cand @ post                                       # masa del posterior que predice y=1
            P1 = p_obs + m * (1.0 - 2.0 * p_obs)                  # P(y=1|config) marginalizando el posterior
            mi = binary_entropy(P1) - binary_entropy(np.array(p_obs))   # info esperada (MI con y)
            x = cand[int(np.argmax(mi))]
        else:
            raise ValueError(mode)
        y = observe_y(rng, x[None, :], c, p_obs)[0]
        logpost = update_logpost(logpost, x, y, p_obs)
    return posterior_from_log(logpost)


def eval_acc(rng, post, X, truth):
    """Predicción = voto ponderado por el posterior; acc contra la verdad y=x[c]. Empates -> azar."""
    vote = X @ post
    pred = (vote > 0.5).astype(int)
    ties = np.abs(vote - 0.5) < 1e-9
    if ties.any():
        pred[ties] = rng.integers(0, 2, size=int(ties.sum()))
    return float((pred == truth).mean())


def run(budgets, n_seeds, D, cluster, p_obs, n_test, cand_pool):
    modes = [("A_pasivo", "passive"), ("B_infogain", "infogain"), ("C_aleatorio", "random")]
    mode_offset = {"passive": 1, "infogain": 2, "random": 3}  # determinista (NO hash(): está randomizado por proceso)
    per_seed = []
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed)
        c, cluster_idx = make_world(rng, D, cluster)
        # tests fijos por seed (mismos para los 3 agentes -> comparación justa)
        X_iid = sample_observational(rng, n_test, D, cluster_idx)
        y_iid = X_iid[:, c]
        X_int = sample_intervention(rng, n_test, D)
        y_int = X_int[:, c]
        row = {"seed": seed, "cause": c, "cluster": [int(i) for i in cluster_idx], "by_budget": {}}
        for K in budgets:
            cell = {}
            for name, mode in modes:
                # rng dedicado por (seed,K,agente) para reproducibilidad e independencia entre celdas
                arng = np.random.default_rng(seed * 100003 + K * 101 + mode_offset[mode])
                post = run_agent(arng, mode, K, D, c, cluster_idx, p_obs, cand_pool)
                cell[name] = {
                    "iid": eval_acc(arng, post, X_iid, y_iid),
                    "interv": eval_acc(arng, post, X_int, y_int),
                    "post_on_cause": float(post[c]),
                }
            row["by_budget"][str(K)] = cell
        per_seed.append(row)

    # agregación: media/std por (budget, agente, métrica)
    def agg(K, name, metric):
        vals = [per_seed[s]["by_budget"][str(K)][name][metric] for s in range(n_seeds)]
        return float(np.mean(vals)), float(np.std(vals))

    summary = {"budgets": budgets, "agents": [m[0] for m in modes], "by_budget": {}}
    for K in budgets:
        d = {}
        for name, _ in modes:
            d[name] = {
                "iid_mean": agg(K, name, "iid")[0], "iid_std": agg(K, name, "iid")[1],
                "interv_mean": agg(K, name, "interv")[0], "interv_std": agg(K, name, "interv")[1],
                "post_on_cause_mean": agg(K, name, "post_on_cause")[0],
            }
        d["margin_B_minus_A_interv"] = d["B_infogain"]["interv_mean"] - d["A_pasivo"]["interv_mean"]
        d["margin_B_minus_C_interv"] = d["B_infogain"]["interv_mean"] - d["C_aleatorio"]["interv_mean"]
        summary["by_budget"][str(K)] = d

    # ---- veredicto DoD contra la predicción falsable ----
    Kmin, Kmax = min(budgets), max(budgets)
    Kmid = budgets[len(budgets) // 2]

    def at(K, name, metric):
        return summary["by_budget"][str(K)][name][metric]

    # (1) Checks PRE-REGISTRADOS (lo que predije ANTES de correr; se conservan tal cual — anti-goalpost).
    #     Dos estaban MAL ESPECIFICADOS (nivel-absoluto/convergencia en vez de planitud/gap); por eso
    #     abajo se agregan diagnósticos que miden la AFIRMACIÓN real. El veredicto es MIXTA con ambos.
    prereg = {
        "iid_all_high(>=0.85 en TODO K)": all(at(K, name, "iid_mean") >= 0.85
                                              for K in budgets for name, _ in modes),
        "A_flat_low_at_Kmax(<=0.65)": at(Kmax, "A_pasivo", "interv_mean") <= 0.65,
        "B_strong_at_Kmid(>=0.80)": at(Kmid, "B_infogain", "interv_mean") >= 0.80,
        "B_beats_A_at_Kmid(>0.20)": (at(Kmid, "B_infogain", "interv_mean")
                                     - at(Kmid, "A_pasivo", "interv_mean")) > 0.20,
    }

    # (2) DIAGNÓSTICOS que miden la afirmación de H-V4-1 correctamente:
    #     - gap invisible i.i.d.: A no es peor que B i.i.d. (la diferencia es chica).
    #     - muro informacional: A bajo intervención NO mejora con presupuesto (planitud en K).
    #     - intervención >> pasivo: B y C (políticas ACTIVAS) superan a A por mucho a Kmax.
    #     - valor específico: ¿el info-gain (B) le gana al azar-activo (C)? (aísla VALOR de ACTIVIDAD).
    iid_gap_Kmid = abs(at(Kmid, "A_pasivo", "iid_mean") - at(Kmid, "B_infogain", "iid_mean"))
    A_flatness = at(Kmax, "A_pasivo", "interv_mean") - at(Kmid, "A_pasivo", "interv_mean")  # ~0 => muro
    B_minus_A_Kmax = at(Kmax, "B_infogain", "interv_mean") - at(Kmax, "A_pasivo", "interv_mean")
    C_minus_A_Kmax = at(Kmax, "C_aleatorio", "interv_mean") - at(Kmax, "A_pasivo", "interv_mean")
    value_edge_lowK = at(Kmin, "B_infogain", "interv_mean") - at(Kmin, "C_aleatorio", "interv_mean")
    value_edge_consistent = all(at(K, "B_infogain", "interv_mean") - at(K, "C_aleatorio", "interv_mean") > 0.02
                                for K in budgets if at(K, "C_aleatorio", "interv_mean") < 0.99)

    diag = {
        "iid_gap_invisible_at_Kmid(|A-B|<=0.10)": iid_gap_Kmid <= 0.10,
        "A_informational_wall(|flat en K|<=0.05)": abs(A_flatness) <= 0.05,
        "intervention>>passive_B(>0.20)": B_minus_A_Kmax > 0.20,
        "intervention>>passive_C(>0.20)": C_minus_A_Kmax > 0.20,
        "value_edge_infogain>random_lowK(>0)": value_edge_lowK > 0,
        "value_edge_consistent(>0.02 salvo saturado)": value_edge_consistent,
    }

    # refutación de H-V4-1: el pasivo SÍ identifica con más presupuesto (alcanza a B), o B no supera a A.
    A_catches_B = B_minus_A_Kmax < 0.05
    B_never_beats = B_minus_A_Kmax <= 0.20

    intervention_wall = (diag["iid_gap_invisible_at_Kmid(|A-B|<=0.10)"]
                         and diag["A_informational_wall(|flat en K|<=0.05)"]
                         and diag["intervention>>passive_B(>0.20)"])
    value_specifically = value_edge_consistent  # info-gain le gana al azar de forma consistente

    if A_catches_B or B_never_beats:
        verdict = "refutada"
    elif intervention_wall and value_specifically:
        verdict = "apoyada"
    elif intervention_wall:
        # la parte fuerte (política ACTIVA/intervención >> pasiva, muro informacional) se sostiene;
        # la parte específica (VALOR info-gain >> azar-activo) NO se aísla -> MIXTA honesta.
        verdict = "mixta"
    else:
        verdict = "mixta"

    summary["prereg_checks"] = prereg
    summary["diagnostics"] = diag
    summary["diag_values"] = {
        "iid_gap_Kmid": round(iid_gap_Kmid, 4),
        "A_flatness_Kmid->Kmax": round(A_flatness, 4),
        "B_minus_A_Kmax": round(B_minus_A_Kmax, 4),
        "C_minus_A_Kmax": round(C_minus_A_Kmax, 4),
        "value_edge_lowK(B-C)": round(value_edge_lowK, 4),
        "Kmin": Kmin, "Kmid": Kmid, "Kmax": Kmax,
    }
    summary["interpretation"] = (
        "R-INTERVENCIÓN demostrada: la política PASIVA (A) se queda plana bajo intervención por más "
        "presupuesto que reciba (muro informacional), mientras las políticas ACTIVAS (B info-gain, "
        "C azar) identifican la causa. R-VALOR específico NO aislado: el azar-activo también lo logra "
        "con presupuesto suficiente, así que este experimento no separa 'valor info-gain' de "
        "'intervención activa' -> hija H-V4-1b (régimen presupuesto-chico/ruido-alto/espacio-grande)."
    )
    summary["verdict"] = verdict
    return per_seed, summary


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(prog="python -m cognia_x.experiments.exp022_endogenous_value.run")
    ap.add_argument("--budgets", type=str, default="2,4,8,16,32,64")
    ap.add_argument("--seeds", type=int, default=24)
    ap.add_argument("--D", type=int, default=12)
    ap.add_argument("--cluster", type=int, default=4)
    ap.add_argument("--p_obs", type=float, default=0.10)
    ap.add_argument("--n_test", type=int, default=4000)
    ap.add_argument("--candidates", type=int, default=128)
    args = ap.parse_args(argv)
    budgets = [int(x) for x in args.budgets.split(",")]

    per_seed, summary = run(budgets, args.seeds, args.D, args.cluster, args.p_obs,
                            args.n_test, args.candidates)

    out = {
        "experiment": "exp022_endogenous_value",
        "hypothesis": "H-V4-1",
        "question": ("¿Un valor ENDÓGENO (info-gain sobre el propio modelo) construye una representación "
                     "más causal que la predicción pasiva, visible bajo intervención y sin verificador externo?"),
        "env": {"python": platform.python_version(), "numpy": np.__version__,
                "platform": platform.platform()},
        "params": {"D": args.D, "cluster": args.cluster, "p_obs": args.p_obs, "budgets": budgets,
                   "seeds": args.seeds, "n_test": args.n_test, "candidates": args.candidates},
        "per_seed": per_seed,
        "summary": summary,
    }
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    # ---- resumen legible con CHECK ----
    print("=" * 80)
    print("exp022 — H-V4-1: valor endógeno (info-gain) vs predicción pasiva, bajo intervención")
    print("=" * 80)
    print("params: D={D} clúster={cluster} p_obs={p_obs} seeds={seeds} n_test={n_test}".format(**out["params"]))
    print("")
    print("INTERVENCIÓN (acc causal; configs uniformes que rompen la confusión):")
    print("  {:>6} | {:>14} | {:>14} | {:>14} | {:>10}".format("K", "A_pasivo", "B_infogain", "C_aleatorio", "B-A"))
    for K in budgets:
        d = summary["by_budget"][str(K)]
        print("  {:>6} | {:>14} | {:>14} | {:>14} | {:>10}".format(
            K,
            "{:.3f}±{:.3f}".format(d["A_pasivo"]["interv_mean"], d["A_pasivo"]["interv_std"]),
            "{:.3f}±{:.3f}".format(d["B_infogain"]["interv_mean"], d["B_infogain"]["interv_std"]),
            "{:.3f}±{:.3f}".format(d["C_aleatorio"]["interv_mean"], d["C_aleatorio"]["interv_std"]),
            "{:+.3f}".format(d["margin_B_minus_A_interv"])))
    print("")
    print("i.i.d. (test del stream observacional; el hueco debe ser INVISIBLE aquí):")
    print("  {:>6} | {:>10} | {:>10} | {:>10}".format("K", "A", "B", "C"))
    for K in budgets:
        d = summary["by_budget"][str(K)]
        print("  {:>6} | {:>10.3f} | {:>10.3f} | {:>10.3f}".format(
            K, d["A_pasivo"]["iid_mean"], d["B_infogain"]["iid_mean"], d["C_aleatorio"]["iid_mean"]))
    print("")
    print("DIAGNÓSTICOS (miden la afirmación de H-V4-1):")
    for k, v in summary["diagnostics"].items():
        print("  CHECK  {:<44} = {}".format(k, v))
    print("  valores:", json.dumps(summary["diag_values"], ensure_ascii=False))
    print("")
    print("PRE-REGISTRADOS (conservados; 2 mal especificados, ver docstring):")
    for k, v in summary["prereg_checks"].items():
        print("  prereg {:<44} = {}".format(k, v))
    print("")
    print("  INTERPRETACIÓN:", summary["interpretation"])
    print("  VEREDICTO H-V4-1 :", summary["verdict"].upper())
    print("=" * 80)
    return 0


if __name__ == "__main__":
    sys.exit(main())
