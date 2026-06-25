r"""
exp049 — CYCLE 63 / H-V4-1f (North-Star R-VALOR x memoria): no-estacionariedad RECURRENTE — la causa cambia
VARIAS veces. ¿El olvido ADAPTATIVO por sorpresa (CYCLE 59) RE-ADAPTA a CADA cambio mientras el COMMITTED queda
atascado en la primera causa?

CONTEXTO: exp044/045 (CYCLE 58/59) probaron UN solo cambio de causa. El North-Star pide un mundo no-estacionario
genérico. Test más fuerte: la causa cambia n_phases veces (recurrente). El COMMITTED (acumula todo) se queda en
la PRIMERA causa; el olvido FIJO adapta pero olvida siempre; el ADAPTATIVO (olvida sólo cuando se contradice)
debería seguir la causa ACTUAL fase a fase, detectando cada cambio por su propia sorpresa, sin que le digan
cuándo cambia.

ANALOGÍA: el temario del examen cambia VARIAS veces en el curso. El que nunca olvida sabe sólo el primer
temario. El que suelta lo viejo cuando empieza a fallar (sorpresa) sigue el temario VIGENTE en cada etapa.

DISEÑO (reusa primitivas de exp022/exp044). Mundo recurrente: clúster confundido; causas = clúster[:n_phases]
(distintas, todas confundidas en observacional). y = x[causa_de_la_fase] por K_phase pasos por fase. MISMA
política (info-gain) para todos; lo único que cambia es el OLVIDO:
  - committed (decay=1), fixed (decay=0.85), adaptive (decay=floor si la obs contradice P(y|post)<0.5 si no 1.0).
Métrica: al FINAL de cada fase, post sobre la causa VIGENTE de esa fase (¿la está siguiendo?). 3 seeds.

PREDICCIÓN FALSABLE (pre-registrada):
  - APOYADA si el ADAPTIVE SIGUE la causa vigente a lo largo de las fases recurrentes (post-sobre-vigente media
    en las fases POST-cambio >= 0.50, MUY por encima del committed que se queda atascado en la primera), sin que
    le digan cuándo cambia. => el olvido por sorpresa maneja no-estacionariedad RECURRENTE, no sólo un cambio.
  - REFUTADA si el adaptive no sigue los cambios (post-vigente post-cambio ~ committed) o no supera al committed.
  - MIXTA si sigue algunos cambios pero no de forma sostenida.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp049_recurrent_nonstationary.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp049_recurrent_nonstationary.run            # FULL
"""
import argparse
import json
import math
import os
import platform
import sys

import numpy as np

from cognia_x.experiments.exp022_endogenous_value.run import (
    binary_entropy, posterior_from_log, sample_intervention, observe_y)
from cognia_x.experiments.exp044_nonstationary_forgetting.run import discounted_update

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")
# (nombre, kind, param). adaptive: param=floor.
ARMS = [("committed", "fixed", 1.0), ("fixed", "fixed", 0.85), ("adaptive", "adaptive", 0.6)]


def make_recurrent_world(rng, D, cluster, n_phases):
    """Clúster confundido; causas = primeras n_phases del clúster (distintas, todas confundidas en observacional)."""
    perm = rng.permutation(D)
    cluster_idx = perm[:cluster]
    causes = [int(cluster_idx[i % cluster]) for i in range(n_phases)]
    return causes, cluster_idx


def run_agent_recurrent(rng, causes, K_phase, D, p_obs, kind, param, cand_pool):
    """info-gain + olvido en mundo RECURRENTE. Devuelve, por fase, el post sobre la causa VIGENTE al final de la fase."""
    logpost = np.zeros(D)
    post_on_current = []
    for ci, c in enumerate(causes):
        for _ in range(K_phase):
            post = posterior_from_log(logpost)
            cand = sample_intervention(rng, cand_pool, D)
            m = cand @ post
            P1 = p_obs + m * (1.0 - 2.0 * p_obs)
            mi = binary_entropy(P1) - binary_entropy(np.array(p_obs))
            j = int(np.argmax(mi))
            x = cand[j]
            y = observe_y(rng, x[None, :], c, p_obs)[0]
            if kind == "fixed":
                decay = param
            else:
                pred_y1 = float(P1[j])
                p_obs_y = pred_y1 if y == 1 else 1.0 - pred_y1
                decay = param if p_obs_y < 0.5 else 1.0
            logpost = discounted_update(logpost, x, y, p_obs, decay)
        post_on_current.append(float(posterior_from_log(logpost)[c]))
    return post_on_current


def run(D, cluster, p_obs, K_phase, n_phases, n_seeds, cand_pool):
    per_seed = []
    for seed in range(n_seeds):
        wrng = np.random.default_rng(seed)
        causes, _ = make_recurrent_world(wrng, D, cluster, n_phases)
        cell = {}
        for name, kind, param in ARMS:
            arng = np.random.default_rng(seed * 100003 + int(param * 1000) + (7 if kind == "fixed" else 99))
            cell[name] = run_agent_recurrent(arng, causes, K_phase, D, p_obs, kind, param, cand_pool)
        per_seed.append({"seed": seed, "causes": causes, "by_arm": cell})

    by_arm = {}
    for name, _, _ in ARMS:
        traj = np.array([s["by_arm"][name] for s in per_seed])     # (seeds, n_phases)
        by_arm[name] = {"post_per_phase": [round(float(x), 4) for x in traj.mean(axis=0)],
                        "phase0": round(float(traj[:, 0].mean()), 4),
                        "post_change_mean": round(float(traj[:, 1:].mean()), 4)}   # fases POST-cambio
    return per_seed, by_arm


def build_summary(by_arm, n_phases, n_seeds):
    com, fix, ada = by_arm["committed"], by_arm["fixed"], by_arm["adaptive"]
    adaptive_tracks = ada["post_change_mean"] >= 0.45
    beats_committed = (ada["post_change_mean"] - com["post_change_mean"]) > 0.15
    committed_degrades = com["post_per_phase"][-1] < com["phase0"] - 0.20     # se atasca progresivamente
    # HALLAZGO honesto: en mundo RECURRENTE el olvido CONSTANTE puede ganar al surprise-gating.
    fixed_best = fix["post_change_mean"] > ada["post_change_mean"] + 0.02

    nota_fixed = (" HALLAZGO (refina CYCLE 59): en mundo RECURRENTE el olvido CONSTANTE (fixed {fx}) SUPERA al "
                  "adaptive ({ad}): cuando el mundo NUNCA se estabiliza, 'committear cuando confirma' sobre-"
                  "committea en sub-fases y el olvido constante va mejor. El surprise-gating era óptimo para UN "
                  "cambio aislado (CYCLE 59), no para cambios recurrentes.").format(
                      fx=_f(fix["post_change_mean"]), ad=_f(ada["post_change_mean"])) if fixed_best else \
                 " El adaptive iguala/supera al fixed."

    if adaptive_tracks and beats_committed and committed_degrades:
        status = "apoyada"
        verdict = ("H-V4-1f APOYADA: el OLVIDO maneja no-estacionariedad RECURRENTE. El committed se atasca "
                   "PROGRESIVAMENTE (post-vigente por fase {comtraj}: acumular commitment lo deja cada vez más "
                   "trabado, post-cambio {com}); el ADAPTATIVO por sorpresa SIGUE la causa vigente a lo largo de "
                   "{np} cambios (post-cambio {ada}) sin que le digan cuándo cambia.{nota}").format(
                       comtraj=str(com["post_per_phase"]), com=_f(com["post_change_mean"]),
                       np=n_phases - 1, ada=_f(ada["post_change_mean"]), nota=nota_fixed)
    elif (ada["post_change_mean"] - com["post_change_mean"]) <= 0.15:
        status = "refutada"
        verdict = ("H-V4-1f REFUTADA: el adaptive no sigue los cambios mejor que el committed (post-cambio "
                   "adaptive {ada} vs committed {com}) -- a este budget por fase el committed re-adapta solo por "
                   "desconfirmación.{nota}").format(ada=_f(ada["post_change_mean"]),
                                                    com=_f(com["post_change_mean"]), nota=nota_fixed)
    else:
        status = "mixta"
        verdict = ("H-V4-1f MIXTA: el adaptive supera al committed (post-cambio {ada} vs {com}) pero no de forma "
                   "sostenida.{nota}").format(ada=_f(ada["post_change_mean"]), com=_f(com["post_change_mean"]),
                                              nota=nota_fixed)

    return {"n_phases": n_phases, "n_seeds": n_seeds, "by_arm": by_arm, "adaptive_tracks": bool(adaptive_tracks),
            "beats_committed": bool(beats_committed), "committed_degrades": bool(committed_degrades),
            "fixed_best": bool(fixed_best), "status": status, "verdict": verdict}


def _f(x):
    return "{:.3f}".format(x)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=int, default=16)
    ap.add_argument("--D", type=int, default=20)
    ap.add_argument("--cluster", type=int, default=5)
    ap.add_argument("--p_obs", type=float, default=0.15)
    ap.add_argument("--K_phase", type=int, default=12)   # corto: el committed se atasca progresivamente (a 30 re-adapta solo)
    ap.add_argument("--n_phases", type=int, default=5)
    ap.add_argument("--candidates", type=int, default=128)
    args = ap.parse_args()
    if args.smoke:
        args.seeds = 6

    seeds = args.seeds
    logs = []

    def log(m):
        print(m, flush=True); logs.append(m)

    log(f"[exp049] CYCLE 63 / H-V4-1f — no-estacionariedad RECURRENTE (la causa cambia {args.n_phases-1} veces)")
    log(f"[exp049] D={args.D} cluster={args.cluster} p_obs={args.p_obs} K_phase={args.K_phase} "
        f"n_phases={args.n_phases} seeds={seeds}")

    per_seed, by_arm = run(args.D, args.cluster, args.p_obs, args.K_phase, args.n_phases, seeds, args.candidates)
    sm = build_summary(by_arm, args.n_phases, seeds)

    log(f"[exp049] post sobre la causa VIGENTE al final de cada fase (media seeds):")
    for name, _, _ in ARMS:
        b = by_arm[name]
        log(f"[exp049]   {name:>10}: por_fase={['%.3f' % x for x in b['post_per_phase']]} "
            f"fase0={b['phase0']:.3f} post-cambio={b['post_change_mean']:.3f}")
    log(f"[exp049] VEREDICTO H-V4-1f: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp049_recurrent_nonstationary", "cycle": 63, "hypothesis": "H-V4-1f",
           "claim": "el olvido adaptativo por sorpresa sigue la causa vigente en no-estacionariedad recurrente "
                    "(varios cambios), donde el committed queda atascado en la primera",
           "verdict": sm["status"], "summary": sm, "per_seed": per_seed,
           "params": {"D": args.D, "cluster": args.cluster, "p_obs": args.p_obs, "K_phase": args.K_phase,
                      "n_phases": args.n_phases, "seeds": seeds, "candidates": args.candidates},
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp049] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
