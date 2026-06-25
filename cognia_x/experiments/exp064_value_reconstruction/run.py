r"""
exp064 — CYCLE 80 / H-V4-6b (rama R-CONTROL, capstone CONSTRUCTIVO del par 79-80): R-VALOR se RECONSTRUYE de dos
marginales endógenas. El CYCLE 79 (exp063) ACOTÓ: el empowerment es la marginal-de-controlabilidad del valor
(ctrl×rel), no el valor universal. La pieza positiva: si el agente ESTIMA AMBAS marginales -- controlabilidad
(empowerment, de sus consecuencias) Y relevancia (de la recompensa observada) -- y las COMBINA (ctrl_est × rel_est),
¿reconstruye el valor COMPLETO y vence a cualquier marginal sola, justo donde control ⊥ relevancia (donde ninguna
marginal basta)?

CONTEXTO: ni control (empowerment) ni predicción/relevancia PURA es el valor; el general es R-VALOR = ctrl×rel
(referido al objetivo). Si R-VALOR es el PRODUCTO de las marginales, combinar dos estimadores endógenos baratos
debería reconstruirlo SIN oráculo -- el resultado positivo que cierra la rama: el valor se CONSTRUYE de señales
endógenas, no se postula.

TAREA (idéntica a exp063, régimen discriminante rho=0 donde control ⊥ relevancia): n levers con ctrl_i, rel_i;
valor=ctrl×rel; atender k<n. El agente OBSERVA S muestras ruidosas de cada marginal: ctrl_est = ctrl + ruido/√S,
rel_est = rel + ruido/√S (abstrae estimar controlabilidad de consecuencias y relevancia de recompensa). 5 brazos:
  - oracle_value:  top-k por ctrl×rel verdadero (cota).
  - empowerment:   top-k por ctrl_est (sólo control -- la marginal del 79).
  - relevance:     top-k por rel_est (sólo relevancia -- la otra marginal).
  - rvalue_est:    top-k por ctrl_est × rel_est (R-VALOR reconstruido de las DOS marginales).
  - random.
Sweep de muestras S (más S = estimación más fina). DOS regímenes: rho=0 (marginales divergen, discriminante) y
rho=1 (alineadas, control: cualquier marginal basta).

PREDICCIÓN FALSABLE (pre-registrada):
  - APOYADA si en rho=0 y S suficiente (>=16) rvalue_est supera a AMBAS marginales (+>0.05 sobre max(emp, rel)) Y
    recupera >=0.85 del oráculo, mientras cada marginal sola se queda ~0.72 (no puede reconstruir el valor). => R-VALOR
    se reconstruye combinando dos estimadores endógenos baratos; ni control ni relevancia solos bastan.
  - REFUTADA si rvalue_est no supera a las marginales (combinar no reconstruye el valor).
  - MIXTA si ayuda pero no recupera el oráculo o no supera limpio a las marginales.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp064_value_reconstruction.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp064_value_reconstruction.run            # FULL
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
ARMS = ["oracle_value", "empowerment", "relevance", "rvalue_est", "random"]
SAMPLES = [1, 4, 16, 64]


def _phi(x):
    from math import erf, sqrt
    vfun = np.vectorize(lambda z: 0.5 * (1.0 + erf(z / sqrt(2.0))))
    return vfun(x)


def gen_levers(rng, n, rho):
    z = rng.normal(size=n)
    w = rng.normal(size=n)
    ctrl = _phi(z)
    rel = _phi(rho * z + np.sqrt(max(0.0, 1.0 - rho * rho)) * w)
    return ctrl, rel


def perf_of(picks, value):
    k = len(picks)
    best = np.sort(value)[-k:].sum()
    got = value[list(picks)].sum()
    return float(got / best) if best > 1e-12 else 0.0


def estimate(rng, true_vals, S, obs_noise):
    """Estimador ruidoso de una marginal: media de S observaciones -> ruido ~ obs_noise/sqrt(S). Clip a [0,1]."""
    est = true_vals + rng.normal(0.0, obs_noise / np.sqrt(S), size=len(true_vals))
    return np.clip(est, 0.0, 1.0)


def run_cell(n, k, rho, S, obs_noise, n_seeds):
    acc = {a: [] for a in ARMS}
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed * 977 + int((rho + 1) * 131) + S * 7)
        ctrl, rel = gen_levers(rng, n, rho)
        value = ctrl * rel
        ctrl_est = estimate(rng, ctrl, S, obs_noise)
        rel_est = estimate(rng, rel, S, obs_noise)
        picks = {
            "oracle_value": np.argsort(value)[-k:],
            "empowerment": np.argsort(ctrl_est)[-k:],
            "relevance": np.argsort(rel_est)[-k:],
            "rvalue_est": np.argsort(ctrl_est * rel_est)[-k:],
            "random": rng.choice(n, size=k, replace=False),
        }
        for a in ARMS:
            acc[a].append(perf_of(picks[a], value))
    return {a: round(float(np.mean(acc[a])), 4) for a in ARMS}


def run(n, k, obs_noise, n_seeds):
    out = {"rho0": {}, "rho1": {}}
    for S in SAMPLES:
        out["rho0"][S] = run_cell(n, k, 0.0, S, obs_noise, n_seeds)
        out["rho1"][S] = run_cell(n, k, 1.0, S, obs_noise, n_seeds)
    return out


def _f(x):
    return "{:.3f}".format(x)


def build_summary(by, n, k):
    # régimen discriminante rho=0, S alto (=64)
    hi = by["rho0"][64]
    rv, emp, rel, rnd = hi["rvalue_est"], hi["empowerment"], hi["relevance"], hi["random"]
    best_marginal = max(emp, rel)
    beats_marginals = (rv - best_marginal) > 0.05
    recovers_oracle = rv >= 0.85
    marginals_stuck = best_marginal < 0.85          # cada marginal sola no reconstruye el valor
    # convergencia: rvalue crece con S en rho=0
    rv_curve = [by["rho0"][S]["rvalue_est"] for S in SAMPLES]
    converges = rv_curve[-1] >= rv_curve[0]

    if beats_marginals and recovers_oracle and marginals_stuck:
        status = "apoyada"
        verdict = ("H-V4-6b APOYADA: R-VALOR se RECONSTRUYE de dos marginales endógenas. En rho=0 (control ⊥ "
                   "relevancia, S=64): rvalue_est (ctrl_est × rel_est) captura {rv} del óptimo, venciendo a CADA "
                   "marginal sola -- empowerment {emp} (sólo control) y relevance {rel} (sólo relevancia) -- por "
                   "+{adv}, y recupera >=85% del oráculo. Ninguna marginal sola pasa de ~{bm} (no puede reconstruir el "
                   "valor); su PRODUCTO sí. Curva de muestras rvalue {curve} (converge={conv}). => el valor general "
                   "R-VALOR (ctrl×rel) se CONSTRUYE combinando dos estimadores endógenos baratos (control de las "
                   "consecuencias + relevancia de la recompensa), SIN oráculo; ni control ni predicción/relevancia "
                   "solos bastan. Cierra el par R-CONTROL: 79 acotó (empowerment=marginal), 80 reconstruye (R-VALOR="
                   "producto de marginales endógenas).").format(
                       rv=_f(rv), emp=_f(emp), rel=_f(rel), adv=_f(rv - best_marginal), bm=_f(best_marginal),
                       curve=[_f(x) for x in rv_curve], conv="sí" if converges else "no")
    elif not beats_marginals:
        status = "refutada"
        verdict = ("H-V4-6b REFUTADA: combinar las marginales no reconstruye el valor. rvalue_est {rv} no supera a la "
                   "mejor marginal {bm} en rho=0 -> el producto de estimadores no mejora sobre el mejor solo a esta "
                   "escala.").format(rv=_f(rv), bm=_f(best_marginal))
    else:
        status = "mixta"
        verdict = ("H-V4-6b MIXTA: rvalue_est {rv} supera a las marginales (max {bm}) en rho=0 pero no recupera >=85% "
                   "del oráculo -> reconstruye PARCIAL (ruido de estimación). Curva {curve}.").format(
                       rv=_f(rv), bm=_f(best_marginal), curve=[_f(x) for x in rv_curve])

    return {"by": {reg: {str(S): by[reg][S] for S in SAMPLES} for reg in ("rho0", "rho1")},
            "rho0_S64": hi, "rvalue_curve_rho0": [round(x, 4) for x in rv_curve],
            "beats_marginals": bool(beats_marginals), "recovers_oracle": bool(recovers_oracle),
            "marginals_stuck": bool(marginals_stuck), "converges": bool(converges),
            "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=int, default=48)
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--k", type=int, default=8)
    ap.add_argument("--obs_noise", type=float, default=0.5, help="std del ruido de observación de cada marginal")
    args = ap.parse_args()
    if args.smoke:
        args.seeds = 12

    logs = []

    def log(mm):
        print(mm, flush=True); logs.append(mm)

    log("[exp064] CYCLE 80 / H-V4-6b — R-VALOR reconstruido de marginales endógenas (control_est × relevancia_est)")
    log(f"[exp064] n={args.n} k={args.k} obs_noise={args.obs_noise} seeds={args.seeds} S={SAMPLES}")

    by = run(args.n, args.k, args.obs_noise, args.seeds)
    sm = build_summary(by, args.n, args.k)

    for reg, name in (("rho0", "rho=0 (control _|_ relevancia)"), ("rho1", "rho=1 (alineadas)")):
        h = by[reg][64]
        log(f"[exp064] {name} S=64: oracle={h['oracle_value']:.3f} empowerment={h['empowerment']:.3f} "
            f"relevance={h['relevance']:.3f} rvalue_est={h['rvalue_est']:.3f} random={h['random']:.3f}")
    log(f"[exp064] rho=0 curva rvalue_est por S {SAMPLES}: {[round(by['rho0'][S]['rvalue_est'],3) for S in SAMPLES]}")
    log(f"[exp064] VEREDICTO H-V4-6b: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp064_value_reconstruction", "cycle": 80, "hypothesis": "H-V4-6b",
           "claim": "R-VALOR (ctrl x rel) se reconstruye combinando dos estimadores endogenos baratos (control de "
                    "consecuencias + relevancia de recompensa); ni control ni relevancia solos bastan donde divergen",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp064] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
