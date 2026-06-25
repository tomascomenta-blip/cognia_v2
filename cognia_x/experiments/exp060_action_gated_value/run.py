r"""
exp060 — CYCLE 76 / H-V4-5f (arco "R-VALOR bajo realismo", hija del 75): el valor con OBSERVACIÓN GATEADA POR LA
ACCIÓN. En CYCLE 75 el costo se observaba en CADA consulta (stakes reveladas). En la realidad, cachear un item te
CIEGA a su costo: si lo tenés, no sentís el dolor de fallarlo -> el costo se revela SÓLO al FALLAR (miss). Así, el
agente observa los costos justo de los items que NO cachea (su propio CONTRAFÁCTICO). ¿Estimar el valor
task-definido sobrevive a esta observación gateada por la acción, o necesita explorar?

CONTEXTO: CYCLE 75 (exp059, H-V4-5e) mostró que el valor es task-definido (frecuencia×costo) y estimarlo vence a la
frecuencia sola. Pero asumió el costo OBSERVABLE en cada consulta. Aquí la observación está GATEADA por la acción de
cachear (estructura tipo R-INTERVENCIÓN débil: la acción del agente decide qué observa). Hipótesis: bajo costos
ESTACIONARIOS, observar-al-fallar BASTA -- porque el cold-start (cache vacía -> todo falla -> todo se observa) y el
hecho de que el agente observe los costos de lo que NO cachea (lo que necesita para decidir si conviene cambiarlo)
hacen que el valor sea aprendible SIN exploración extra.

TAREA (idéntica a exp059 cost-varying): n items, m<n, valor v=f×c (c indep de f). Métrica = hit-rate ponderado por
costo (ventana final). 6 brazos, todos estiman value = frecuencia_observada × costo_estimado:
  - oracle_value:  top-m por v VERDADERO (cota).
  - value_full:    costo observado en CADA consulta (la observabilidad fácil de exp059).
  - value_miss:    costo observado SÓLO al fallar (observación GATEADA por la acción; lo realista).
  - value_explore: value_miss + sacrifica 1 slot para RE-SONDAR (deja fuera el item cacheado más "viejo" sin
                   re-observar, forzando su re-observación). Control: ¿hace falta exploración extra?
  - lfu_freq:      sólo frecuencia (ignora el costo).
  - random:        m al azar.

PREDICCIÓN FALSABLE (pre-registrada):
  - APOYADA si value_miss recupera >=70% de la ventaja del oráculo Y value_miss >> lfu_freq (+>0.05) Y value_miss ~
    value_full (|dif|<0.05: la observación gateada NO rompe el aprendizaje del valor bajo estacionariedad). =>
    estimar el valor task-definido sobrevive a la observación gateada por la acción; el agente observa su propio
    contrafáctico (los costos de lo que no cachea) y eso basta.
  - REFUTADA si value_miss colapsa hacia lfu_freq (la observación gateada rompe el aprendizaje del valor).
  - MIXTA si value_miss ayuda pero queda lejos de value_full (necesita exploración: value_explore recupera el gap).

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp060_action_gated_value.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp060_action_gated_value.run            # FULL
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
ARMS = ["oracle_value", "value_full", "value_miss", "value_explore", "lfu_freq", "random"]


def gen_pareto(rng, n, alpha):
    return rng.pareto(alpha, size=n) + 1.0


def simulate_arm(queries, costs, f, c, m, n, arm, rng, warmup):
    """Hit-rate ponderado por costo (tras warmup). El costo se observa segun la regla de observabilidad del brazo."""
    count = np.zeros(n, dtype=np.float64)
    cost_sum = np.zeros(n, dtype=np.float64)        # suma de costos observados por item
    cost_obs = np.zeros(n, dtype=np.int64)          # cuantas veces se observo el costo de i
    stale = np.zeros(n, dtype=np.float64)           # pasos que i lleva cacheado sin re-observar (para explore)
    tb = rng.random(n)
    v_true = f * c
    topm_true = set(np.argsort(v_true)[-m:].tolist())
    fixed_random = set(rng.choice(n, size=m, replace=False).tolist())
    T = len(queries)
    num = 0.0
    den = 0.0
    mem = set()

    def value_priority():
        gm = (cost_sum.sum() / cost_obs.sum()) if cost_obs.sum() > 0 else 1.0
        cost_est = np.where(cost_obs > 0, cost_sum / np.maximum(cost_obs, 1), gm)
        return count * cost_est + 1e-9 * tb

    for t in range(T):
        q = int(queries[t])
        ct = float(costs[t])
        if arm == "oracle_value":
            mem = topm_true
        elif arm == "random":
            mem = fixed_random
        elif arm == "lfu_freq":
            mem = set(np.argsort(count + 1e-9 * tb)[-m:].tolist())
        elif arm in ("value_full", "value_miss"):
            mem = set(np.argsort(value_priority())[-m:].tolist())
        else:  # value_explore: top-(m-1) por valor + 1 slot deja FUERA el cacheado mas viejo (re-sonda)
            pr = value_priority()
            top = list(np.argsort(pr)[-m:])
            # el item cacheado mas "stale" se deja fuera este paso (se re-sonda si lo consultan)
            if m >= 2:
                stale_in_top = [(stale[i], i) for i in top]
                drop = max(stale_in_top)[1]
                mem = set(top) - {drop}
            else:
                mem = set(top)
        hit = 1.0 if q in mem else 0.0
        if t >= warmup:
            num += ct * hit
            den += ct
        # actualizacion de estado
        count[q] += 1.0
        observe = False
        if arm == "value_full":
            observe = True
        elif arm in ("value_miss", "value_explore"):
            observe = (hit == 0.0)              # costo observado SOLO al fallar
        if observe:
            cost_sum[q] += ct
            cost_obs[q] += 1
        # staleness para explore: crece si esta en mem y no se observo; se resetea si se observo o salio
        if arm == "value_explore":
            stale += 1.0
            if observe:
                stale[q] = 0.0
            # los que NO estan en mem no acumulan staleness de cacheo
            not_mem = np.ones(n, dtype=bool)
            not_mem[list(mem)] = False
            stale[not_mem] = 0.0
    return float(num / den) if den > 0 else 0.0


def run_scenario(n, m, alpha_f, alpha_c, T, n_seeds):
    warmup = T // 4
    acc = {a: [] for a in ARMS}
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed)
        f = gen_pareto(rng, n, alpha_f)
        p = f / f.sum()
        c = gen_pareto(rng, n, alpha_c)
        qrng = np.random.default_rng(seed * 104729 + 7)
        queries = qrng.choice(n, size=T, p=p)
        costs = c[queries]
        for a in ARMS:
            arng = np.random.default_rng(seed * 7919 + ARMS.index(a) + 1)
            acc[a].append(simulate_arm(queries, costs, f, c, m, n, a, arng, warmup))
    return {a: round(float(np.mean(acc[a])), 4) for a in ARMS}


def _f(x):
    return "{:.3f}".format(x)


def build_summary(res, n, m):
    o, vfull, vmiss, vexp, lfu, rnd = (res["oracle_value"], res["value_full"], res["value_miss"],
                                       res["value_explore"], res["lfu_freq"], res["random"])
    gap = o - rnd
    recovered = (vmiss - rnd) / gap if gap > 1e-9 else 0.0
    miss_recovers = recovered >= 0.70
    miss_beats_lfu = (vmiss - lfu) > 0.05
    miss_matches_full = abs(vmiss - vfull) < 0.05
    explore_helps = (vexp - vmiss) > 0.03

    if miss_recovers and miss_beats_lfu and miss_matches_full:
        status = "apoyada"
        verdict = ("H-V4-5f APOYADA: estimar el valor task-definido SOBREVIVE a la observación gateada por la acción. "
                   "value_miss (costo observado SÓLO al fallar) {vm} recupera {pct}% de la ventaja del oráculo ({o}) y "
                   "vence a lfu_freq ({lfu}) por +{adv}; ~ value_full ({vf}, costo siempre visible, |dif| {dif}) -> la "
                   "observación gateada NO rompe el aprendizaje del valor bajo estacionariedad. Mecanismo: el agente "
                   "observa los costos justo de lo que NO cachea (su CONTRAFÁCTICO -- lo que necesita para decidir si "
                   "cambiarlo), y el cold-start observa todo una vez. value_explore {ve} no agrega (Δ {dexp}): no hace "
                   "falta exploración extra con costos estacionarios. => el valor es aprendible aun cuando la acción "
                   "de cachear ciega su observación; liga R-VALOR (qué vale) con la acción (R-INTERVENCIÓN débil: "
                   "la acción decide qué se observa).").format(
                       vm=_f(vmiss), pct=int(round(recovered * 100)), o=_f(o), lfu=_f(lfu), adv=_f(vmiss - lfu),
                       vf=_f(vfull), dif=_f(abs(vmiss - vfull)), ve=_f(vexp), dexp=_f(vexp - vmiss))
    elif not miss_beats_lfu:
        status = "refutada"
        verdict = ("H-V4-5f REFUTADA: la observación gateada por la acción ROMPE el aprendizaje del valor. value_miss "
                   "{vm} colapsa hacia lfu_freq {lfu} (no lo supera por +0.05) -> sin observar el costo de lo cacheado "
                   "el agente no aprende el valor.").format(vm=_f(vmiss), lfu=_f(lfu))
    else:
        status = "mixta"
        verdict = ("H-V4-5f MIXTA: value_miss {vm} supera a lfu {lfu} y recupera {pct}% del oráculo ({o}) pero queda "
                   "lejos de value_full {vf} (|dif| {dif}); value_explore {ve} {rec} el gap (Δ {dexp}) -> la "
                   "observación gateada cuesta y la exploración {recw}.").format(
                       vm=_f(vmiss), lfu=_f(lfu), pct=int(round(recovered * 100)), o=_f(o), vf=_f(vfull),
                       dif=_f(abs(vmiss - vfull)), ve=_f(vexp), dexp=_f(vexp - vmiss),
                       rec="recupera" if explore_helps else "no recupera", recw="ayuda" if explore_helps else "no ayuda")

    return {"by_arm": res, "oracle_advantage": round(gap, 4), "fraction_recovered_miss": round(float(recovered), 4),
            "miss_recovers": bool(miss_recovers), "miss_beats_lfu": bool(miss_beats_lfu),
            "miss_matches_full": bool(miss_matches_full), "explore_helps": bool(explore_helps),
            "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=int, default=48)
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--m", type=int, default=10)
    ap.add_argument("--alpha_f", type=float, default=1.5)
    ap.add_argument("--alpha_c", type=float, default=1.5)
    ap.add_argument("--T", type=int, default=4000)
    args = ap.parse_args()
    if args.smoke:
        args.seeds = 8
        args.T = 1500

    logs = []

    def log(mm):
        print(mm, flush=True); logs.append(mm)

    log("[exp060] CYCLE 76 / H-V4-5f — valor con OBSERVACIÓN GATEADA POR LA ACCIÓN (costo revelado sólo al fallar)")
    log(f"[exp060] n={args.n} m={args.m} alpha_f={args.alpha_f} alpha_c={args.alpha_c} T={args.T} seeds={args.seeds}")

    res = run_scenario(args.n, args.m, args.alpha_f, args.alpha_c, args.T, args.seeds)
    sm = build_summary(res, args.n, args.m)

    log(f"[exp060] hit-rate pond.costo: oracle={res['oracle_value']:.3f} value_full={res['value_full']:.3f} "
        f"value_miss={res['value_miss']:.3f} value_explore={res['value_explore']:.3f} lfu_freq={res['lfu_freq']:.3f} "
        f"random={res['random']:.3f}")
    log(f"[exp060] value_miss recupera {sm['fraction_recovered_miss']*100:.0f}% del oráculo; ~value_full "
        f"({sm['miss_matches_full']}); explore agrega {res['value_explore']-res['value_miss']:+.3f}")
    log(f"[exp060] VEREDICTO H-V4-5f: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp060_action_gated_value", "cycle": 76, "hypothesis": "H-V4-5f",
           "claim": "estimar el valor task-definido sobrevive a la observación gateada por la accion (costo revelado "
                    "solo al fallar): el agente observa el costo de lo que NO cachea (su contrafactual) y eso basta",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp060] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
