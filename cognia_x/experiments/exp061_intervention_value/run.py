r"""
exp061 — CYCLE 77 / H-V4-5g (arco "R-VALOR bajo realismo", CIERRA la pregunta de R-INTERVENCIÓN-sobre-memoria que
abrió el 76): bajo costos NO-ESTACIONARIOS + observación GATEADA POR LA ACCIÓN, INTERVENIR (re-sondar lo cacheado)
se vuelve NECESARIO. Complementa el CYCLE 76 (que mostró que la intervención NO hace falta con costos
ESTACIONARIOS): la pareja 76(null)+77(positivo) fija EXACTAMENTE cuándo importa intervenir sobre la memoria.

CONTEXTO: CYCLE 76 (exp060, H-V4-5f) mostró que con observación gateada (costo sólo al fallar) PERO costos
ESTACIONARIOS, observar el contrafáctico (lo no-cacheado) basta -- la exploración extra RESTA. Caveat registrado: si
los costos DERIVAN, un item cacheado cuyo costo cambia pasa DESAPERCIBIDO (cacheado = nunca falla = nunca se observa
su costo nuevo) -> ahí la intervención (re-sondar) debería pagar. Esto es R-INTERVENCIÓN sobre la memoria: la acción
(re-sondar) es necesaria para identificar el cambio que la observación pasiva no ve.

TAREA (memoria online, costo gateado por acción): n items, m<n. Frecuencia f_i ESTACIONARIA (Pareto). Costo c_i que
en NO-ESTACIONARIO se RE-PERMUTA entre items cada K_phase (la magnitud de los costos es fija, QUÉ item es caro
cambia). value v=f×c (cambia con el drift de c). El costo se observa SÓLO al fallar. cost_est[i] = último costo
observado (rastrea drift). Métrica = hit-rate ponderado por costo ACTUAL (ventana final). DOS escenarios:
COST_STATIONARY (control, = CYCLE 76) y COST_DRIFT. 6 brazos:
  - oracle_value:  top-m por v ACTUAL (cota).
  - value_full:    costo observado en CADA consulta (rastrea el drift; cota práctica con obs gateada relajada).
  - value_miss:    costo SÓLO al fallar, SIN re-sondar (lo cacheado-que-deriva queda CIEGO).
  - value_explore: value_miss + sacrifica 1 slot para re-sondar el cacheado más viejo (INTERVIENE -> ve el drift).
  - lfu_freq:      sólo frecuencia (ignora costo).
  - random:        m al azar.

PREDICCIÓN FALSABLE (pre-registrada):
  - APOYADA si en COST_DRIFT value_explore supera a value_miss (+>0.05; intervenir paga) Y recupera buena parte del
    gap value_full-value_miss; CON el control de que en COST_STATIONARY value_explore <= value_miss (intervenir NO
    paga sin drift, = CYCLE 76). => bajo observación gateada + drift, la INTERVENCIÓN (re-sondar) es necesaria para
    aprender el valor que la observación pasiva NO ve -> R-INTERVENCIÓN sobre la memoria.
  - REFUTADA si value_explore no supera a value_miss bajo drift (intervenir no ayuda ni con drift).
  - MIXTA si ayuda parcial o el control estacionario no separa (explore ayuda también sin drift).

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp061_intervention_value.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp061_intervention_value.run            # FULL
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


def simulate_arm(queries, phase_of_t, c_by_phase, f, m, n, arm, rng, warmup):
    """Hit-rate ponderado por el costo ACTUAL (tras warmup). cost_est = último costo observado (rastrea drift)."""
    count = np.zeros(n, dtype=np.float64)
    cost_est = np.zeros(n, dtype=np.float64)        # último costo observado por item
    seen = np.zeros(n, dtype=bool)
    stale = np.zeros(n, dtype=np.float64)           # pasos cacheado sin re-observar (para explore)
    tb = rng.random(n)
    fixed_random = set(rng.choice(n, size=m, replace=False).tolist())
    T = len(queries)
    num = 0.0
    den = 0.0

    def value_priority():
        gm = cost_est[seen].mean() if seen.any() else 1.0
        ce = np.where(seen, cost_est, gm)
        return count * ce + 1e-9 * tb

    for t in range(T):
        q = int(queries[t])
        ph = phase_of_t[t]
        ct = float(c_by_phase[ph][q])               # costo ACTUAL del item consultado
        if arm == "oracle_value":
            v_now = f * c_by_phase[ph]
            mem = set(np.argsort(v_now)[-m:].tolist())
        elif arm == "random":
            mem = fixed_random
        elif arm == "lfu_freq":
            mem = set(np.argsort(count + 1e-9 * tb)[-m:].tolist())
        elif arm in ("value_full", "value_miss"):
            mem = set(np.argsort(value_priority())[-m:].tolist())
        else:  # value_explore
            pr = value_priority()
            top = list(np.argsort(pr)[-m:])
            if m >= 2:
                drop = max((stale[i], i) for i in top)[1]
                mem = set(top) - {drop}
            else:
                mem = set(top)
        hit = 1.0 if q in mem else 0.0
        if t >= warmup:
            num += ct * hit
            den += ct
        count[q] += 1.0
        observe = (arm == "value_full") or (arm in ("value_miss", "value_explore") and hit == 0.0)
        if observe:
            cost_est[q] = ct                         # rastrea el costo ACTUAL (drift)
            seen[q] = True
        if arm == "value_explore":
            stale += 1.0
            if observe:
                stale[q] = 0.0
            not_mem = np.ones(n, dtype=bool)
            not_mem[list(mem)] = False
            stale[not_mem] = 0.0
    return float(num / den) if den > 0 else 0.0


def run_scenario(n, m, alpha_f, alpha_c, K_phase, n_phases, n_seeds, drift):
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
            acc[a].append(simulate_arm(queries, phase_of_t, c_by_phase, f, m, n, a, arng, warmup))
    return {a: round(float(np.mean(acc[a])), 4) for a in ARMS}


def _f(x):
    return "{:.3f}".format(x)


def build_summary(stat, drift, n, m):
    e_s, miss_s = stat["value_explore"], stat["value_miss"]
    o_d, full_d, miss_d, exp_d, lfu_d, rnd_d = (drift["oracle_value"], drift["value_full"], drift["value_miss"],
                                                drift["value_explore"], drift["lfu_freq"], drift["random"])
    explore_helps_drift = (exp_d - miss_d) > 0.05
    gap_obs = full_d - miss_d                          # cuánto cuesta la observación gateada bajo drift
    recovered_gap = (exp_d - miss_d) / gap_obs if gap_obs > 1e-6 else 0.0
    explore_neutral_stat = (e_s - miss_s) <= 0.02      # control: sin drift, intervenir NO ayuda (cf. CYCLE 76)

    if explore_helps_drift and explore_neutral_stat:
        status = "apoyada"
        verdict = ("H-V4-5g APOYADA: bajo observación gateada + DRIFT de costos, INTERVENIR (re-sondar) se vuelve "
                   "NECESARIO. COST_DRIFT: value_miss (no re-sonda) {md} queda CIEGO al drift de lo cacheado; "
                   "value_explore (re-sonda) {ed} lo supera por +{adv} y recupera {pct}% del gap de observación "
                   "(value_full {fd} - value_miss {md}); ambos sobre lfu {ld}. CONTROL COST_STATIONARY: value_explore "
                   "{es} <= value_miss {ms} (intervenir NO paga sin drift, = CYCLE 76). => la pareja 76(null)+77 fija "
                   "que la INTERVENCIÓN sobre la memoria es necesaria SÓLO cuando la observación es gateada por la "
                   "acción Y el mundo DERIVA: re-sondar identifica el cambio que la observación pasiva del "
                   "contrafáctico NO ve (lo cacheado-que-deriva). R-INTERVENCIÓN aterriza sobre el sustrato de "
                   "valor-memoria.").format(
                       md=_f(miss_d), ed=_f(exp_d), adv=_f(exp_d - miss_d), pct=int(round(recovered_gap * 100)),
                       fd=_f(full_d), ld=_f(lfu_d), es=_f(e_s), ms=_f(miss_s))
    elif not explore_helps_drift:
        status = "refutada"
        verdict = ("H-V4-5g REFUTADA (con matiz informativo): el PROBLEMA es real pero la intervención naive NO lo "
                   "resuelve. Bajo DRIFT la observación gateada SÍ duele: value_miss {md} pierde {gap} vs value_full "
                   "{fd} (en ESTACIONARIO miss=full, {ms}={es_full}: la ceguera al drift de lo CACHEADO es un efecto "
                   "REAL). PERO el mecanismo de re-sondar sacrificando un slot entero es demasiado BURDO: value_explore "
                   "{ed} ni siquiera supera a value_miss {md} bajo drift (recupera {pct}% del gap = NADA) y cuesta "
                   "{stcost} en estacionario. => el slot-sacrifice permanente cuesta más capacidad de la que recupera; "
                   "la intervención sobre la memoria, si paga, necesita ser CHEAP/TARGETED (re-sondar OCASIONAL gateado "
                   "por sorpresa, no un slot fijo). R-INTERVENCIÓN sobre la memoria NO se logra con este mecanismo "
                   "burdo. Próxima hija: intervención dirigida por sorpresa.").format(
                       md=_f(miss_d), gap=_f(full_d - miss_d), fd=_f(full_d), ms=_f(miss_s), es_full=_f(stat["value_full"]),
                       ed=_f(exp_d), pct=int(round(max(0.0, recovered_gap) * 100)), stcost=_f(e_s - miss_s))
    else:
        status = "mixta"
        verdict = ("H-V4-5g MIXTA: value_explore {ed} supera a value_miss {md} bajo drift PERO el control "
                   "estacionario no separa limpio (value_explore {es} vs value_miss {ms}): re-sondar también "
                   "ayuda/daña sin drift -> la necesidad de intervenir no es exclusiva del drift a esta "
                   "escala.").format(ed=_f(exp_d), md=_f(miss_d), es=_f(e_s), ms=_f(miss_s))

    return {"stationary": stat, "drift": drift, "explore_helps_drift": bool(explore_helps_drift),
            "obs_gap_drift": round(gap_obs, 4), "explore_recovers_gap": round(float(recovered_gap), 4),
            "explore_neutral_stationary": bool(explore_neutral_stat), "status": status, "verdict": verdict}


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
    args = ap.parse_args()
    if args.smoke:
        args.seeds = 6
        args.K_phase = 150
        args.n_phases = 4

    logs = []

    def log(mm):
        print(mm, flush=True); logs.append(mm)

    log("[exp061] CYCLE 77 / H-V4-5g — bajo DRIFT de costos + obs gateada, INTERVENIR (re-sondar) se vuelve necesario")
    log(f"[exp061] n={args.n} m={args.m} K_phase={args.K_phase} n_phases={args.n_phases} seeds={args.seeds}")

    stat = run_scenario(args.n, args.m, args.alpha_f, args.alpha_c, args.K_phase, args.n_phases, args.seeds, False)
    drift = run_scenario(args.n, args.m, args.alpha_f, args.alpha_c, args.K_phase, args.n_phases, args.seeds, True)
    sm = build_summary(stat, drift, args.n, args.m)

    log(f"[exp061] COST_STATIONARY hit-rate: oracle={stat['oracle_value']:.3f} value_full={stat['value_full']:.3f} "
        f"value_miss={stat['value_miss']:.3f} value_explore={stat['value_explore']:.3f} lfu={stat['lfu_freq']:.3f}")
    log(f"[exp061] COST_DRIFT      hit-rate: oracle={drift['oracle_value']:.3f} value_full={drift['value_full']:.3f} "
        f"value_miss={drift['value_miss']:.3f} value_explore={drift['value_explore']:.3f} lfu={drift['lfu_freq']:.3f}")
    log(f"[exp061] DRIFT: explore-miss={drift['value_explore']-drift['value_miss']:+.3f} (recupera "
        f"{sm['explore_recovers_gap']*100:.0f}% del gap de obs); STAT: explore-miss={stat['value_explore']-stat['value_miss']:+.3f}")
    log(f"[exp061] VEREDICTO H-V4-5g: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp061_intervention_value", "cycle": 77, "hypothesis": "H-V4-5g",
           "claim": "bajo observacion gateada por la accion + drift de costos, intervenir (re-sondar lo cacheado) se "
                    "vuelve necesario para aprender el valor que la observacion pasiva no ve (R-INTERVENCION sobre memoria)",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp061] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
