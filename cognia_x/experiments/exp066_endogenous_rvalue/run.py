r"""
exp066 — CYCLE 82 / H-V4-6d (rama R-CONTROL, capstone EMPÍRICO de la unificación 79-81): R-VALOR TOTALMENTE
ENDÓGENO. Cierra el caveat "control exacto" del CYCLE 81: estima AMBAS marginales online y ruidosas a la vez --
controlabilidad (con S muestras ruidosas, como exp064) Y relevancia (de un verificador con error ε, como exp065) --
y combina (ctrl_est × verificador). SIN oráculo en ningún lado. ¿Vence a cada marginal sola (empowerment puro /
verificador puro) en el régimen realista de ruido?

CONTEXTO: el cuadro unificado de la corrida -- R-VALOR = control × relevancia; el empowerment estima la
controlabilidad (79-80), el verificador estima la relevancia (81). Este ciclo lo prueba EMPÍRICAMENTE con AMBAS
fuentes de ruido presentes a la vez (el caso realista): el agente no tiene NINGUNA señal exacta, sólo sus dos
estimadores endógenos. Es la prueba de que combinar las dos marginales ENDÓGENAS supera a cualquiera sola.

TAREA: n levers, ctrl_i continuo, rel_i BINARIO (p_rel relevantes). valor = ctrl × rel. El agente estima:
ctrl_est = ctrl + ruido/√S (controlabilidad de las consecuencias) y rel_hat = rel flipeado con prob ε (verificador
de relevancia). Atiende k<n. 5 brazos, NINGUNO usa el valor verdadero salvo el oracle:
  - oracle_value:    top-k por ctrl×rel (cota).
  - empowerment:     top-k por ctrl_est (sólo control estimado).
  - verifier:        top-k por rel_hat (sólo relevancia del verificador).
  - rvalue_full:     top-k por ctrl_est × rel_hat (R-VALOR totalmente endógeno: las DOS marginales ruidosas).
  - random.
Grid de ruido: S (muestras de control) ∈ {2,8,32} × ε (error del verificador) ∈ {0.1, 0.3}.

PREDICCIÓN FALSABLE (pre-registrada): en el punto realista (S=8, ε=0.1):
  - APOYADA si rvalue_full supera a AMBAS marginales (empowerment, verifier) por +>0.05 Y recupera >=80% del oráculo,
    usando SÓLO estimadores endógenos. => combinar las dos marginales endógenas (ninguna suficiente) supera a
    cualquiera sola; R-VALOR endógeno funciona sin oráculo. Prueba empírica de la unificación 79-81.
  - REFUTADA si rvalue_full no supera a la mejor marginal (combinar dos ruidosos no ayuda).
  - MIXTA si supera pero no recupera >=80% (el ruido combinado lo degrada).

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp066_endogenous_rvalue.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp066_endogenous_rvalue.run            # FULL
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
ARMS = ["oracle_value", "empowerment", "verifier", "rvalue_full", "random"]
S_LIST = [2, 8, 32]
EPS_LIST = [0.1, 0.3]


def perf_of(picks, value):
    k = len(picks)
    best = np.sort(value)[-k:].sum()
    got = value[list(picks)].sum()
    return float(got / best) if best > 1e-12 else 0.0


def run_cell(n, k, p_rel, S, eps, ctrl_noise, n_seeds):
    acc = {a: [] for a in ARMS}
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed * 769 + S * 31 + int(eps * 100) + 5)
        ctrl = rng.random(n)
        rel = (rng.random(n) < p_rel).astype(float)
        value = ctrl * rel
        tb = rng.random(n)
        ctrl_est = np.clip(ctrl + rng.normal(0.0, ctrl_noise / np.sqrt(S), size=n), 0.0, 1.0)
        rel_hat = np.where(rng.random(n) < eps, 1.0 - rel, rel)
        picks = {
            "oracle_value": np.argsort(value)[-k:],
            "empowerment": np.argsort(ctrl_est)[-k:],
            "verifier": np.argsort(rel_hat + 1e-6 * tb)[-k:],
            "rvalue_full": np.argsort(ctrl_est * rel_hat + 1e-9 * tb)[-k:],
            "random": rng.choice(n, size=k, replace=False),
        }
        for a in ARMS:
            acc[a].append(perf_of(picks[a], value))
    return {a: round(float(np.mean(acc[a])), 4) for a in ARMS}


def run(n, k, p_rel, ctrl_noise, n_seeds):
    grid = {}
    for S in S_LIST:
        for e in EPS_LIST:
            grid["S{}_e{}".format(S, e)] = run_cell(n, k, p_rel, S, e, ctrl_noise, n_seeds)
    return grid


def _f(x):
    return "{:.3f}".format(x)


def build_summary(grid, n, k):
    rep = grid["S8_e0.1"]                              # punto realista representativo
    rv, emp, ver = rep["rvalue_full"], rep["empowerment"], rep["verifier"]
    best_marg = max(emp, ver)
    beats_both = (rv - best_marg) > 0.05
    recovers = rv >= 0.80
    # robustez: ¿rvalue_full vence a ambas marginales en TODAS las celdas?
    beats_all_cells = all(c["rvalue_full"] > max(c["empowerment"], c["verifier"]) for c in grid.values())

    if beats_both and recovers:
        status = "apoyada"
        verdict = ("H-V4-6d APOYADA: R-VALOR TOTALMENTE ENDÓGENO supera a cada marginal sola. En el punto realista "
                   "(S=8, ε=0.1): rvalue_full (ctrl_est × verificador, AMBOS ruidosos, SIN oráculo) {rv} vence a "
                   "empowerment {emp} (control estimado solo) y verifier {ver} (relevancia sola) por +{adv}, y recupera "
                   ">=80% del oráculo. rvalue_full vence a ambas marginales en TODAS las celdas del grid de ruido: {ba}. "
                   "=> combinar las DOS marginales ENDÓGENAS (ninguna suficiente: el control solo capta poco con pocos "
                   "relevantes, la relevancia sola ignora el control) supera a cualquiera sola, SIN ninguna señal "
                   "exacta. Prueba EMPÍRICA de la unificación 79-81: el agente que estima control (empowerment) Y "
                   "relevancia (verificador) y los combina reconstruye y USA R-VALOR endógeno. Cierra el caveat "
                   "'control exacto' del CYCLE 81.").format(
                       rv=_f(rv), emp=_f(emp), ver=_f(ver), adv=_f(rv - best_marg), ba="sí" if beats_all_cells else "no")
    elif not beats_both:
        status = "refutada"
        verdict = ("H-V4-6d REFUTADA: combinar dos marginales ruidosas no supera a la mejor sola. rvalue_full {rv} ~ "
                   "max(empowerment {emp}, verifier {ver}) en el punto realista -> el ruido combinado anula la ventaja "
                   "de combinar.").format(rv=_f(rv), emp=_f(emp), ver=_f(ver))
    else:
        status = "mixta"
        verdict = ("H-V4-6d MIXTA: rvalue_full {rv} supera a las marginales (max {bm}) pero no recupera >=80% del "
                   "oráculo en el punto realista -> el ruido combinado lo degrada (reconstruye parcial).").format(
                       rv=_f(rv), bm=_f(best_marg))

    return {"grid": grid, "rep_point": "S8_e0.1", "rep": rep, "beats_both": bool(beats_both),
            "recovers": bool(recovers), "beats_all_cells": bool(beats_all_cells),
            "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=int, default=48)
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--p_rel", type=float, default=0.3)
    ap.add_argument("--ctrl_noise", type=float, default=0.5)
    args = ap.parse_args()
    if args.smoke:
        args.seeds = 12

    logs = []

    def log(mm):
        print(mm, flush=True); logs.append(mm)

    log("[exp066] CYCLE 82 / H-V4-6d — R-VALOR totalmente ENDÓGENO (control_est × verificador, ambos ruidosos)")
    log(f"[exp066] n={args.n} k={args.k} p_rel={args.p_rel} ctrl_noise={args.ctrl_noise} seeds={args.seeds} "
        f"S={S_LIST} eps={EPS_LIST}")

    grid = run(args.n, args.k, args.p_rel, args.ctrl_noise, args.seeds)
    sm = build_summary(grid, args.n, args.k)

    for key in ("S2_e0.1", "S8_e0.1", "S32_e0.1", "S2_e0.3", "S8_e0.3", "S32_e0.3"):
        c = grid[key]
        log(f"[exp066] {key}: oracle={c['oracle_value']:.3f} empowerment={c['empowerment']:.3f} "
            f"verifier={c['verifier']:.3f} rvalue_full={c['rvalue_full']:.3f} random={c['random']:.3f}")
    log(f"[exp066] punto realista S8_e0.1: rvalue_full={sm['rep']['rvalue_full']:.3f} vence a ambas marginales "
        f"(beats_both={sm['beats_both']}); en TODAS las celdas={sm['beats_all_cells']}")
    log(f"[exp066] VEREDICTO H-V4-6d: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp066_endogenous_rvalue", "cycle": 82, "hypothesis": "H-V4-6d",
           "claim": "R-VALOR totalmente endogeno (control estimado x verificador, ambos ruidosos, sin oraculo) supera "
                    "a cada marginal sola; prueba empirica de la unificacion 79-81",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp066] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
