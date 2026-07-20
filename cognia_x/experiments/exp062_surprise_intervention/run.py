r"""
exp062 — CYCLE 78 / H-V4-5h (arco "R-VALOR bajo realismo", CIERRA el sub-tema memoria): la intervención BARATA
dirigida por SORPRESA. El CYCLE 77 (exp061, H-V4-5g REFUTADA) mostró que el problema (drift+obs gateada degrada lo
cacheado) es real pero el re-sondeo por SLOT FIJO no paga (cuesta ~1/m de capacidad permanente > el gap). ¿Una
intervención OCASIONAL gateada por sorpresa (re-sondar SÓLO cuando el hit-rate cae, devolviendo la capacidad full
el resto del tiempo) paga donde el slot fijo no pagó? Reusa el detector de cambio endógeno del CYCLE 59.

CONTEXTO: el slot fijo de exp061 sacrificaba 1 de m slots SIEMPRE (-0.065 sin drift, -0.029 con drift). La idea
barata: usar capacidad full normalmente y re-sondar (evictar el cacheado más viejo) SÓLO durante una ráfaga corta
tras detectar que el hit-rate cayó (sorpresa). Si el detector no se dispara sin drift, no paga el costo del slot;
si se dispara con drift, re-observa lo cacheado-que-derivó. Test directo de si la INTERVENCIÓN sobre la memoria
puede ser cheap/targeted.

TAREA (idéntica a exp061): memoria online m=10/n=50, frecuencia f estacionaria, costo c que en DRIFT se re-permuta
cada K_phase. Costo observado SÓLO al fallar; cost_est = último observado. Métrica = hit-rate ponderado por costo
ACTUAL. DOS escenarios: COST_STATIONARY y COST_DRIFT. 7 brazos:
  - oracle_value, value_full, value_miss (sin intervenir), value_explore (slot FIJO = el perdedor del 77),
  - value_surprise: capacidad full normal; EMA rápida vs lenta del hit; si la rápida cae bajo la lenta -margen
                    (SORPRESA) dispara una ráfaga de P pasos re-sondando el cacheado más viejo (sacrifica 1 slot
                    SÓLO durante la ráfaga). Intervención OCASIONAL y targeted.
  - lfu_freq, random.

PREDICCIÓN FALSABLE (pre-registrada):
  - APOYADA si en COST_DRIFT value_surprise supera a value_miss (+>0.02) Y supera a value_explore (la barata vence a
    la burda) Y en COST_STATIONARY value_surprise ~ value_miss (|dif|<0.02: no se dispara sin cambio -> no paga el
    costo). => la intervención sobre la memoria SÍ paga si es cheap/targeted (sorpresa-gateada).
  - REFUTADA si value_surprise no supera a value_miss bajo drift (ni la intervención barata paga: el gap es
    demasiado chico / la observación pasiva del contrafáctico es robusta aun con drift).
  - MIXTA si ayuda parcial o el control estacionario no separa.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp062_surprise_intervention.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp062_surprise_intervention.run            # FULL
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
ARMS = ["oracle_value", "value_full", "value_miss", "value_explore", "value_surprise", "lfu_freq", "random"]


def gen_pareto(rng, n, alpha):
    return rng.pareto(alpha, size=n) + 1.0


def simulate_arm(queries, phase_of_t, c_by_phase, f, m, n, arm, rng, warmup, probe_len, surp_margin):
    """Hit-rate ponderado por el costo ACTUAL (tras warmup). value_surprise re-sonda en ráfaga tras detectar caída."""
    count = np.zeros(n, dtype=np.float64)
    cost_est = np.zeros(n, dtype=np.float64)
    seen = np.zeros(n, dtype=bool)
    stale = np.zeros(n, dtype=np.float64)
    tb = rng.random(n)
    fixed_random = set(rng.choice(n, size=m, replace=False).tolist())
    T = len(queries)
    num = 0.0
    den = 0.0
    h_fast, h_slow = 0.5, 0.5
    probe_timer = 0

    def value_priority():
        gm = cost_est[seen].mean() if seen.any() else 1.0
        ce = np.where(seen, cost_est, gm)
        return count * ce + 1e-9 * tb

    for t in range(T):
        q = int(queries[t])
        ph = phase_of_t[t]
        ct = float(c_by_phase[ph][q])
        probing = False
        if arm == "oracle_value":
            v_now = f * c_by_phase[ph]
            mem = set(np.argsort(v_now)[-m:].tolist())
        elif arm == "random":
            mem = fixed_random
        elif arm == "lfu_freq":
            mem = set(np.argsort(count + 1e-9 * tb)[-m:].tolist())
        elif arm in ("value_full", "value_miss"):
            mem = set(np.argsort(value_priority())[-m:].tolist())
        elif arm == "value_explore":
            pr = value_priority()
            top = list(np.argsort(pr)[-m:])
            drop = max((stale[i], i) for i in top)[1] if m >= 2 else None
            mem = set(top) - ({drop} if drop is not None else set())
        else:  # value_surprise: full normal; re-sonda sólo durante ráfaga gateada por sorpresa
            pr = value_priority()
            top = list(np.argsort(pr)[-m:])
            if probe_timer > 0 and m >= 2:
                probing = True
                drop = max((stale[i], i) for i in top)[1]
                mem = set(top) - {drop}
            else:
                mem = set(top)
        hit = 1.0 if q in mem else 0.0
        if t >= warmup:
            num += ct * hit
            den += ct
        count[q] += 1.0
        observe = (arm == "value_full") or (arm in ("value_miss", "value_explore", "value_surprise") and hit == 0.0)
        if observe:
            cost_est[q] = ct
            seen[q] = True
        if arm in ("value_explore", "value_surprise"):
            stale += 1.0
            if observe:
                stale[q] = 0.0
            not_mem = np.ones(n, dtype=bool)
            not_mem[list(mem)] = False
            stale[not_mem] = 0.0
        if arm == "value_surprise":
            h_fast = 0.96 * h_fast + 0.04 * hit
            h_slow = 0.995 * h_slow + 0.005 * hit
            if probe_timer > 0:
                probe_timer -= 1
            elif h_fast < h_slow - surp_margin:
                probe_timer = probe_len            # dispara una ráfaga de re-sondeo
    return float(num / den) if den > 0 else 0.0


def run_scenario(n, m, alpha_f, alpha_c, K_phase, n_phases, n_seeds, drift, probe_len, surp_margin):
    T = K_phase * n_phases
    warmup = K_phase
    acc = {a: [] for a in ARMS}
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed)
        f = gen_pareto(rng, n, alpha_f)
        p = f / f.sum()
        c0 = gen_pareto(rng, n, alpha_c)
        if drift:
            c_by_phase = [c0[rng.permutation(n)] for _ in range(n_phases)]
        else:
            c_by_phase = [c0 for _ in range(n_phases)]
        phase_of_t = [t // K_phase for t in range(T)]
        qrng = np.random.default_rng(seed * 104729 + (1 if drift else 0))
        queries = qrng.choice(n, size=T, p=p)
        for a in ARMS:
            arng = np.random.default_rng(seed * 7919 + ARMS.index(a) + 1)
            acc[a].append(simulate_arm(queries, phase_of_t, c_by_phase, f, m, n, a, arng, warmup, probe_len, surp_margin))
    return {a: round(float(np.mean(acc[a])), 4) for a in ARMS}


def _f(x):
    return "{:.3f}".format(x)


def build_summary(stat, drift, n, m):
    miss_s, surp_s = stat["value_miss"], stat["value_surprise"]
    miss_d, exp_d, surp_d, full_d, o_d = (drift["value_miss"], drift["value_explore"], drift["value_surprise"],
                                          drift["value_full"], drift["oracle_value"])
    surprise_helps_drift = (surp_d - miss_d) > 0.02
    surprise_beats_explore = surp_d > exp_d
    surprise_neutral_stat = abs(surp_s - miss_s) < 0.02
    gap_obs = full_d - miss_d
    recovered = (surp_d - miss_d) / gap_obs if gap_obs > 1e-6 else 0.0

    if surprise_helps_drift and surprise_beats_explore and surprise_neutral_stat:
        status = "apoyada"
        verdict = ("H-V4-5h APOYADA: la intervención sobre la memoria SÍ paga si es CHEAP/TARGETED (sorpresa-gateada). "
                   "COST_DRIFT: value_surprise {sd} supera a value_miss {md} (+{adv}, recupera {pct}% del gap de "
                   "observación full {fd}) Y supera al slot FIJO value_explore {ed} (la barata vence a la burda del "
                   "CYCLE 77). COST_STATIONARY: value_surprise {ss} ~ value_miss {ms} (|dif| {difs}): el detector NO "
                   "se dispara sin cambio -> no paga el costo del slot. => cierra la hija del 77: re-sondar OCASIONAL "
                   "gateado por sorpresa (detector de CYCLE 59) recupera el valor que la observación gateada pierde "
                   "bajo drift, donde el slot fijo no podía. R-INTERVENCIÓN sobre la memoria aterriza CON un mecanismo "
                   "barato.").format(
                       sd=_f(surp_d), md=_f(miss_d), adv=_f(surp_d - miss_d), pct=int(round(recovered * 100)),
                       fd=_f(full_d), ed=_f(exp_d), ss=_f(surp_s), ms=_f(miss_s), difs=_f(abs(surp_s - miss_s)))
    elif not surprise_helps_drift:
        status = "refutada"
        verdict = ("H-V4-5h REFUTADA: ni la intervención barata sorpresa-gateada paga. COST_DRIFT value_surprise {sd} "
                   "no supera a value_miss {md} (+{adv}) -> el gap de observación bajo drift ({gap}) es demasiado "
                   "chico para que CUALQUIER intervención lo recupere; la observación pasiva del contrafáctico es "
                   "robusta aun con drift. Confirma y generaliza el 77: el problema es real pero MENOR; intervenir no "
                   "paga ni barato.").format(sd=_f(surp_d), md=_f(miss_d), adv=_f(surp_d - miss_d), gap=_f(gap_obs))
    else:
        status = "mixta"
        verdict = ("H-V4-5h MIXTA: value_surprise {sd} ayuda algo bajo drift (vs miss {md}) pero no limpio -- "
                   "{be} al slot fijo {ed} y el control estacionario {se} (surprise {ss} vs miss {ms}).").format(
                       sd=_f(surp_d), md=_f(miss_d), be="supera" if surprise_beats_explore else "NO supera",
                       ed=_f(exp_d), se="separa" if surprise_neutral_stat else "no separa", ss=_f(surp_s), ms=_f(miss_s))

    return {"stationary": stat, "drift": drift, "surprise_helps_drift": bool(surprise_helps_drift),
            "surprise_beats_explore": bool(surprise_beats_explore), "surprise_neutral_stationary": bool(surprise_neutral_stat),
            "obs_gap_drift": round(gap_obs, 4), "surprise_recovers_gap": round(float(recovered), 4),
            "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=int, default=32)
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--m", type=int, default=10)
    ap.add_argument("--alpha_f", type=float, default=1.5)
    ap.add_argument("--alpha_c", type=float, default=1.5)
    ap.add_argument("--K_phase", type=int, default=300)
    ap.add_argument("--n_phases", type=int, default=6)
    ap.add_argument("--probe_len", type=int, default=40, help="pasos de ráfaga de re-sondeo tras una sorpresa")
    ap.add_argument("--surp_margin", type=float, default=0.04, help="caída de hit EMA que dispara la sorpresa")
    args = ap.parse_args()
    if args.smoke:
        args.seeds = 6
        args.K_phase = 150
        args.n_phases = 4

    logs = []

    def log(mm):
        print(mm, flush=True); logs.append(mm)

    log("[exp062] CYCLE 78 / H-V4-5h — intervención BARATA sorpresa-gateada (re-sondar ocasional, no slot fijo)")
    log(f"[exp062] n={args.n} m={args.m} K_phase={args.K_phase} n_phases={args.n_phases} probe_len={args.probe_len} "
        f"surp_margin={args.surp_margin} seeds={args.seeds}")

    stat = run_scenario(args.n, args.m, args.alpha_f, args.alpha_c, args.K_phase, args.n_phases, args.seeds, False,
                        args.probe_len, args.surp_margin)
    drift = run_scenario(args.n, args.m, args.alpha_f, args.alpha_c, args.K_phase, args.n_phases, args.seeds, True,
                         args.probe_len, args.surp_margin)
    sm = build_summary(stat, drift, args.n, args.m)

    log(f"[exp062] COST_STATIONARY: oracle={stat['oracle_value']:.3f} full={stat['value_full']:.3f} "
        f"miss={stat['value_miss']:.3f} explore={stat['value_explore']:.3f} surprise={stat['value_surprise']:.3f} lfu={stat['lfu_freq']:.3f}")
    log(f"[exp062] COST_DRIFT:      oracle={drift['oracle_value']:.3f} full={drift['value_full']:.3f} "
        f"miss={drift['value_miss']:.3f} explore={drift['value_explore']:.3f} surprise={drift['value_surprise']:.3f} lfu={drift['lfu_freq']:.3f}")
    log(f"[exp062] DRIFT: surprise-miss={drift['value_surprise']-drift['value_miss']:+.3f} (recupera "
        f"{sm['surprise_recovers_gap']*100:.0f}% del gap {sm['obs_gap_drift']:.3f}); STAT: surprise-miss={stat['value_surprise']-stat['value_miss']:+.3f}")
    log(f"[exp062] VEREDICTO H-V4-5h: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp062_surprise_intervention", "cycle": 78, "hypothesis": "H-V4-5h",
           "claim": "una intervencion barata gateada por sorpresa (re-sondar ocasional, no slot fijo) recupera el "
                    "valor que la observacion gateada pierde bajo drift, donde el slot fijo del CYCLE 77 no podia",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp062] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
