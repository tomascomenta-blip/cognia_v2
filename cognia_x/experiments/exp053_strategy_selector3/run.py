r"""
exp053 — CYCLE 68 / H-V4-1j (North-Star R-VALOR x memoria, capstone): SELECTOR DE 3 ESTRATEGIAS — el agente
clasifica TRES regímenes de no-estacionariedad (ESTACIONARIO / AISLADO / RECURRENTE) de su propia sorpresa en
DOS escalas de tiempo y selecciona la estrategia de memoria correcta (committear / surprise-gate / olvidar-fuerte).

CONTEXTO: CYCLE 66 (selector de 2 estrategias) alcanzó el óptimo en estacionario y recurrente. Falta el régimen
INTERMEDIO: un cambio AISLADO tras commitment profundo (CYCLE 58/59), donde lo óptimo es surprise-gating (no
committear -> queda atascado; no olvidar-fuerte -> estropea la fase larga). Para distinguir AISLADO de RECURRENTE
(ambos tienen spikes de sorpresa) hace falta DOS escalas: una LENTA (tasa de cambio de largo plazo: alta en
recurrente, baja en aislado) y una RÁPIDA (detecta el shift inmediato).

SELECTOR3 (clasificación de 2 escalas):
  - slow_ema > slow_thresh  -> RECURRENTE  -> olvidar-fuerte (decay constante 0.85)
  - elif fast_ema > fast_thresh -> shift AISLADO en curso -> surprise-gate (decay=floor 0.6)
  - else -> ESTABLE / post-shift -> committear (decay=1)

DISEÑO (reusa exp052/049). TRES regímenes con FASES ASIMÉTRICAS: ESTACIONARIO [60] (committear óptimo); AISLADO
[48,12] (commit largo + adapt corto -> surprise-gate óptimo); RECURRENTE [12,12,12,12,12] (olvidar-fuerte óptimo).
4 brazos: committed, fixed(0.85), surprise_gate(0.6), SELECTOR3. Métrica: post sobre la causa vigente (estac:
final; aislado: post causa nueva al final; recur: media post-cambio). 16 seeds.

PREDICCIÓN FALSABLE (pre-registrada):
  - APOYADA si el SELECTOR3 es ~ÓPTIMO en los TRES regímenes (estacionario ~ committed; aislado ~ surprise_gate
    >> committed; recurrente ~ fixed >> committed), clasificando de su propia sorpresa en 2 escalas. => el valor
    endógeno selecciona la estrategia de memoria correcta entre TRES regímenes.
  - REFUTADA si el selector3 falla en >=2 regímenes (clasifica mal).
  - MIXTA si acierta 2 de 3 (p.ej. no separa aislado de recurrente).

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp053_strategy_selector3.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp053_strategy_selector3.run            # FULL
"""
import argparse
import json
import os
import platform
import sys

import numpy as np

from cognia_x.experiments.exp022_endogenous_value.run import (
    binary_entropy, posterior_from_log, sample_intervention, observe_y)
from cognia_x.experiments.exp044_nonstationary_forgetting.run import discounted_update
from cognia_x.experiments.exp049_recurrent_nonstationary.run import make_recurrent_world

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")
ARMS = [("committed", "fixed", 1.0), ("fixed", "fixed", 0.85), ("surprise_gate", "sgate", 0.6),
        ("selector3", "selector3", 0.6)]
# regímenes: (nombre, n_phases, phase_lengths, metric_kind)
REGIMES = [("estacionario", 1, [60], "final"), ("aislado", 2, [48, 12], "final"),
           ("recurrente", 5, [12, 12, 12, 12, 12], "postchange")]
FORGET_HARD = 0.85


def run_agent(rng, causes, phase_lengths, D, p_obs, kind, param, cand_pool,
              fast_rate=0.25, slow_rate=0.03):
    """info-gain + olvido con FASES ASIMÉTRICAS. kinds: fixed (decay=param), sgate (surprise-gate binario),
    selector3 (clasifica 3 regímenes en 2 escalas de sorpresa y elige committear/surprise-gate/olvidar-fuerte)."""
    logpost = np.zeros(D)
    fast_ema = slow_ema = p_obs
    fast_thresh, slow_thresh = p_obs + 0.18, p_obs + 0.06
    post_on_current = []
    for c, plen in zip(causes, phase_lengths):
        for _ in range(plen):
            post = posterior_from_log(logpost)
            cand = sample_intervention(rng, cand_pool, D)
            m = cand @ post
            P1 = p_obs + m * (1.0 - 2.0 * p_obs)
            mi = binary_entropy(P1) - binary_entropy(np.array(p_obs))
            j = int(np.argmax(mi))
            x = cand[j]
            y = observe_y(rng, x[None, :], c, p_obs)[0]
            pred_y1 = float(P1[j])
            contradicted = 1.0 if (pred_y1 if y == 1 else 1.0 - pred_y1) < 0.5 else 0.0
            fast_ema = (1 - fast_rate) * fast_ema + fast_rate * contradicted
            slow_ema = (1 - slow_rate) * slow_ema + slow_rate * contradicted
            if kind == "fixed":
                decay = param
            elif kind == "sgate":
                decay = param if contradicted else 1.0
            else:  # selector3: clasifica el régimen y elige la ESTRATEGIA
                if slow_ema > slow_thresh:
                    decay = FORGET_HARD                       # RECURRENTE -> olvidar-fuerte
                elif fast_ema > fast_thresh:
                    decay = param                             # shift AISLADO -> surprise-gate (floor)
                else:
                    decay = 1.0                               # ESTABLE -> committear
            logpost = discounted_update(logpost, x, y, p_obs, decay)
        post_on_current.append(float(posterior_from_log(logpost)[c]))
    return post_on_current


def regime_metric(post_per_phase, metric_kind):
    return post_per_phase[-1] if metric_kind == "final" else float(np.mean(post_per_phase[1:]))


def run_regime(n_phases, phase_lengths, metric_kind, D, cluster, p_obs, n_seeds, cand_pool):
    vals = {name: [] for name, _, _ in ARMS}
    for seed in range(n_seeds):
        wrng = np.random.default_rng(seed)
        causes, _ = make_recurrent_world(wrng, D, cluster, n_phases)
        for name, kind, param in ARMS:
            arng = np.random.default_rng(seed * 100003 + {"committed": 7, "fixed": 13, "surprise_gate": 31, "selector3": 91}[name])
            traj = run_agent(arng, causes, phase_lengths, D, p_obs, kind, param, cand_pool)
            vals[name].append(regime_metric(traj, metric_kind))
    return {name: round(float(np.mean(vals[name])), 4) for name in vals}


def _f(x):
    return "{:.3f}".format(x)


def build_summary(by_regime, margin=0.10):
    # mejor brazo esperado por régimen
    best_arm = {"estacionario": "committed", "aislado": "surprise_gate", "recurrente": "fixed"}
    near_optimal = {}
    for reg, vals in by_regime.items():
        sel = vals["selector3"]
        best = vals[best_arm[reg]]
        beats_committed = sel > vals["committed"] + margin if reg != "estacionario" else True
        near_optimal[reg] = (sel >= best - margin) and beats_committed
    n_ok = sum(near_optimal.values())

    if n_ok == 3:
        status = "apoyada"
        verdict = ("H-V4-1j APOYADA: el SELECTOR de 3 ESTRATEGIAS clasifica los TRES regímenes de su propia "
                   "sorpresa (2 escalas) y elige la estrategia correcta -- ~ÓPTIMO en los 3. {det}. El valor "
                   "endógeno selecciona la estrategia de memoria entre múltiples regímenes; completa el selector "
                   "del CYCLE 66.").format(det=_det(by_regime, best_arm))
    elif n_ok <= 1:
        status = "refutada"
        verdict = ("H-V4-1j REFUTADA: el selector3 falla en >=2 regímenes (clasifica mal). {det}.").format(
            det=_det(by_regime, best_arm))
    else:
        status = "mixta"
        verdict = ("H-V4-1j MIXTA: el selector3 acierta {n}/3 regímenes (probablemente no separa limpio aislado "
                   "de recurrente). {det}.").format(n=n_ok, det=_det(by_regime, best_arm))

    return {"margin": margin, "by_regime": by_regime, "best_arm": best_arm,
            "near_optimal": {k: bool(v) for k, v in near_optimal.items()}, "n_optimal": n_ok,
            "status": status, "verdict": verdict}


def _det(by_regime, best_arm):
    parts = []
    for reg, vals in by_regime.items():
        parts.append("{}: selector3={} (mejor={} {}; committed={})".format(
            reg, _f(vals["selector3"]), best_arm[reg], _f(vals[best_arm[reg]]), _f(vals["committed"])))
    return " | ".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=int, default=16)
    ap.add_argument("--D", type=int, default=20)
    ap.add_argument("--cluster", type=int, default=5)
    ap.add_argument("--p_obs", type=float, default=0.15)
    ap.add_argument("--candidates", type=int, default=128)
    args = ap.parse_args()
    if args.smoke:
        args.seeds = 6

    logs = []

    def log(m):
        print(m, flush=True); logs.append(m)

    log(f"[exp053] CYCLE 68 / H-V4-1j — SELECTOR de 3 ESTRATEGIAS (clasifica estac/aislado/recurrente en 2 escalas)")
    log(f"[exp053] D={args.D} cluster={args.cluster} p_obs={args.p_obs} seeds={args.seeds} regímenes={[(r[0], r[2]) for r in REGIMES]}")

    by_regime = {}
    for name, n_phases, plen, metric_kind in REGIMES:
        by_regime[name] = run_regime(n_phases, plen, metric_kind, args.D, args.cluster, args.p_obs,
                                     args.seeds, args.candidates)
    sm = build_summary(by_regime)

    for name, _, plen, _ in REGIMES:
        v = by_regime[name]
        log(f"[exp053] {name:>12} {str(plen):>22}: committed={v['committed']:.3f} fixed={v['fixed']:.3f} "
            f"sgate={v['surprise_gate']:.3f} SELECTOR3={v['selector3']:.3f} (óptimo={sm['near_optimal'][name]})")
    log(f"[exp053] VEREDICTO H-V4-1j: {sm['status'].upper()} ({sm['n_optimal']}/3) | {sm['verdict']}")

    out = {"exp": "exp053_strategy_selector3", "cycle": 68, "hypothesis": "H-V4-1j",
           "claim": "un selector de 3 estrategias clasifica 3 regímenes de su sorpresa (2 escalas) y elige la "
                    "estrategia de memoria correcta, alcanzando el óptimo en los tres",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp053] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
