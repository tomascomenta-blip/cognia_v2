r"""
exp059 — CYCLE 75 / H-V4-5e (arco "R-VALOR bajo realismo", capstone CONCEPTUAL): el VALOR != FRECUENCIA. El valor
de recordar un item es task-definido (frecuencia de consulta × COSTO de fallarlo), NO su mera frecuencia. Cuando el
costo VARÍA (el valor diverge de la frecuencia), un estimador de VALOR (costo acumulado observado) vence a la
frecuencia pura (LFU), que optimiza la señal EQUIVOCADA; cuando el costo es UNIFORME (valor proporcional a
frecuencia) convergen. Rebate la crítica "esto es sólo LFU textbook": LFU FALLA cuando el valor != frecuencia.

CONTEXTO: el sub-arco 72-73-74 estimó el valor por FRECUENCIA -- pero ahí el valor ERA la frecuencia (prob de
consulta), así que la frecuencia era un estimador perfecto del valor. El thesis v4 dice que el valor es
task-definido (info mutua con consultas/recompensas FUTURAS), no un proxy de frecuencia. Aquí lo separamos: cada
item tiene una FRECUENCIA de consulta f_i Y un COSTO de fallarlo c_i (independiente). El valor verdadero es
v_i = f_i * c_i. La señal que el agente ESTIMA (frecuencia sola vs frecuencia×costo) decide si rinde.

TAREA (memoria online, valor task-definido): n items, capacidad m<n. f_i ~ power-law (Pareto). En cada consulta
(IID ~ f) el agente OBSERVA el costo c del item consultado (stakes reveladas). Objetivo = MINIMIZAR el costo de
los fallos = maximizar el HIT-RATE PONDERADO POR COSTO (fracción del costo de consulta cubierta por la memoria).
DOS escenarios: COST_UNIFORM (c_i=1 -> v proporcional a f) y COST_VARYING (c_i ~ Pareto indep. de f -> v != f).
5 brazos:
  - oracle_value: top-m por v VERDADERO (= f*c). Cota superior.
  - lfu_freq:     top-m por FRECUENCIA observada (cuenta). Ignora el costo -> guarda lo frecuente-barato.
  - value_est:    top-m por COSTO ACUMULADO observado (suma de c de las consultas a i) = estimador MC de f*c.
  - recency:      LRU (value-free).
  - random:       m fijos al azar.

PREDICCIÓN FALSABLE (pre-registrada):
  - APOYADA si en COST_VARYING value_est supera a lfu_freq (+>0.05) Y recupera >=70% de la ventaja del oráculo
    Y en COST_UNIFORM value_est ~ lfu_freq (|dif|<0.04: la ventaja la DRIVE la divergencia valor!=frecuencia, no
    que value_est sea genéricamente mejor). => el valor es task-definido; estimar la FRECUENCIA (proxy) falla
    cuando el valor diverge de ella; estimar el VALOR (frecuencia×costo) acierta.
  - REFUTADA si value_est no supera a lfu en cost-varying (el costo no importa) O daña en cost-uniform.
  - MIXTA si ayuda pero recupera poco o no converge limpio en uniform.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp059_value_vs_frequency.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp059_value_vs_frequency.run            # FULL
"""
import argparse
import json
import os
import platform
import sys

import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")
ARMS = ["oracle_value", "lfu_freq", "value_est", "recency", "random"]


def gen_pareto(rng, n, alpha):
    return rng.pareto(alpha, size=n) + 1.0


def _topm(score, tiebreak, m):
    return set(np.argsort(score + 1e-9 * tiebreak)[-m:].tolist())


def simulate_arm(queries, costs, f, c, m, n, arm, rng, warmup):
    """Hit-rate PONDERADO POR COSTO (tras warmup) de un brazo. costs[t]=c[queries[t]] (stakes reveladas)."""
    count = np.zeros(n, dtype=np.float64)        # frecuencia observada
    cost_sum = np.zeros(n, dtype=np.float64)     # costo acumulado observado por item (estima f*c)
    tb = rng.random(n)
    lru = []
    fixed_random = set(rng.choice(n, size=m, replace=False).tolist())
    v_true = f * c                               # valor verdadero (no observable directamente)
    topm_true = set(np.argsort(v_true)[-m:].tolist())
    T = len(queries)
    num = 0.0
    den = 0.0
    for t in range(T):
        q = int(queries[t])
        ct = float(costs[t])
        if arm == "oracle_value":
            mem = topm_true
        elif arm == "random":
            mem = fixed_random
        elif arm == "recency":
            mem = set(lru[:m])
        elif arm == "lfu_freq":
            mem = _topm(count, tb, m)
        else:  # value_est: por costo acumulado observado
            mem = _topm(cost_sum, tb, m)
        hit = 1.0 if q in mem else 0.0
        if t >= warmup:
            num += ct * hit
            den += ct
        # actualizar
        count[q] += 1.0
        cost_sum[q] += ct
        if arm == "recency":
            if q in lru:
                lru.remove(q)
            lru.insert(0, q)
            del lru[m:]
    return float(num / den) if den > 0 else 0.0


def run_scenario(n, m, alpha_f, alpha_c, T, n_seeds, cost_varying):
    warmup = T // 4
    acc = {a: [] for a in ARMS}
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed)
        f = gen_pareto(rng, n, alpha_f)
        p = f / f.sum()
        c = gen_pareto(rng, n, alpha_c) if cost_varying else np.ones(n)
        qrng = np.random.default_rng(seed * 104729 + (1 if cost_varying else 0))
        queries = qrng.choice(n, size=T, p=p)
        costs = c[queries]
        for a in ARMS:
            arng = np.random.default_rng(seed * 7919 + ARMS.index(a) + 1)
            acc[a].append(simulate_arm(queries, costs, f, c, m, n, a, arng, warmup))
    return {a: round(float(np.mean(acc[a])), 4) for a in ARMS}


def _f(x):
    return "{:.3f}".format(x)


def build_summary(uniform, varying, n, m):
    o_v, lfu_v, val_v, rnd_v = (varying["oracle_value"], varying["lfu_freq"], varying["value_est"], varying["random"])
    lfu_u, val_u = uniform["lfu_freq"], uniform["value_est"]
    gap_v = o_v - rnd_v
    recovered_v = (val_v - rnd_v) / gap_v if gap_v > 1e-9 else 0.0
    value_beats_lfu = (val_v - lfu_v) > 0.05
    value_recovers = recovered_v >= 0.70
    no_divergence_uniform = abs(val_u - lfu_u) < 0.04
    lfu_suboptimal_varying = (o_v - lfu_v) > 0.08

    if value_beats_lfu and value_recovers and no_divergence_uniform:
        status = "apoyada"
        verdict = ("H-V4-5e APOYADA: el VALOR != FRECUENCIA -- el valor es task-definido (frecuencia×costo). "
                   "COST_VARYING (v!=f): value_est (estima el costo acumulado) {vv} recupera {pct}% de la ventaja del "
                   "oráculo ({ov}); lfu_freq (sólo frecuencia) se queda en {lv} (+{adv} a favor de value_est) -- LFU "
                   "deja {sub} de valor sobre la mesa porque optimiza la señal EQUIVOCADA (guarda lo frecuente-barato, "
                   "falla lo raro-caro). COST_UNIFORM (v proporcional a f): value_est {vu} ~ lfu_freq {lu} (|dif| "
                   "{difu}): SIN divergencia no hay ventaja -> la ventaja la DRIVE que el valor diverja de la "
                   "frecuencia, no que value_est sea genéricamente mejor. => estimar la FRECUENCIA es un PROXY que "
                   "falla; hay que estimar el VALOR de la tarea. Rebate 'esto es sólo LFU': LFU es óptimo SÓLO cuando "
                   "valor=frecuencia.").format(
                       vv=_f(val_v), pct=int(round(recovered_v * 100)), ov=_f(o_v), lv=_f(lfu_v), adv=_f(val_v - lfu_v),
                       sub=_f(o_v - lfu_v), vu=_f(val_u), lu=_f(lfu_u), difu=_f(abs(val_u - lfu_u)))
    elif not value_beats_lfu:
        status = "refutada"
        verdict = ("H-V4-5e REFUTADA: estimar el valor (frecuencia×costo) no supera a la frecuencia sola en "
                   "cost-varying (value_est {vv} vs lfu {lv}) -> el costo no agrega valor a esta escala.").format(
                       vv=_f(val_v), lv=_f(lfu_v))
    else:
        status = "mixta"
        verdict = ("H-V4-5e MIXTA: value_est {vv} supera a lfu {lv} en cost-varying pero recupera sólo {pct}% del "
                   "oráculo ({ov}) o no converge limpio en uniform (value {vu} vs lfu {lu}).").format(
                       vv=_f(val_v), lv=_f(lfu_v), pct=int(round(recovered_v * 100)), ov=_f(o_v), vu=_f(val_u), lu=_f(lfu_u))

    return {"uniform": uniform, "varying": varying, "oracle_advantage_varying": round(gap_v, 4),
            "fraction_recovered_varying": round(float(recovered_v), 4), "value_beats_lfu": bool(value_beats_lfu),
            "value_recovers": bool(value_recovers), "no_divergence_uniform": bool(no_divergence_uniform),
            "lfu_suboptimal_varying": bool(lfu_suboptimal_varying), "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=int, default=48)
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--m", type=int, default=10)
    ap.add_argument("--alpha_f", type=float, default=1.5, help="Pareto de la frecuencia de consulta")
    ap.add_argument("--alpha_c", type=float, default=1.5, help="Pareto del costo de fallar (cost-varying)")
    ap.add_argument("--T", type=int, default=4000)
    args = ap.parse_args()
    if args.smoke:
        args.seeds = 8
        args.T = 1500

    logs = []

    def log(mm):
        print(mm, flush=True); logs.append(mm)

    log("[exp059] CYCLE 75 / H-V4-5e — el VALOR != FRECUENCIA (valor task-definido = frecuencia×costo de fallar)")
    log(f"[exp059] n={args.n} m={args.m} alpha_f={args.alpha_f} alpha_c={args.alpha_c} T={args.T} seeds={args.seeds}")

    uniform = run_scenario(args.n, args.m, args.alpha_f, args.alpha_c, args.T, args.seeds, False)
    varying = run_scenario(args.n, args.m, args.alpha_f, args.alpha_c, args.T, args.seeds, True)
    sm = build_summary(uniform, varying, args.n, args.m)

    log(f"[exp059] COST_UNIFORM   hit-rate pond.costo: oracle={uniform['oracle_value']:.3f} lfu_freq={uniform['lfu_freq']:.3f} "
        f"value_est={uniform['value_est']:.3f} recency={uniform['recency']:.3f} random={uniform['random']:.3f}")
    log(f"[exp059] COST_VARYING   hit-rate pond.costo: oracle={varying['oracle_value']:.3f} lfu_freq={varying['lfu_freq']:.3f} "
        f"value_est={varying['value_est']:.3f} recency={varying['recency']:.3f} random={varying['random']:.3f}")
    log(f"[exp059] cuando v!=f: value_est recupera {sm['fraction_recovered_varying']*100:.0f}% del oráculo; lfu deja "
        f"{varying['oracle_value']-varying['lfu_freq']:.3f} sobre la mesa. cuando v~f: value~lfu ({sm['no_divergence_uniform']})")
    log(f"[exp059] VEREDICTO H-V4-5e: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp059_value_vs_frequency", "cycle": 75, "hypothesis": "H-V4-5e",
           "claim": "el valor de recordar es task-definido (frecuencia×costo), no la frecuencia: cuando el valor "
                    "diverge de la frecuencia, estimar el VALOR vence a estimar la frecuencia (LFU)",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp059] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
