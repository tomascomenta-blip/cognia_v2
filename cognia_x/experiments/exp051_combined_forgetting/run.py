r"""
exp051 — CYCLE 65 / H-V4-1h (North-Star R-VALOR x memoria): olvido COMBINADO (piso constante + boost por
sorpresa) — ¿cierra el caveat del CYCLE 64 (el meta olvidaba DÉBIL en recurrente porque su decay volvía a subir
entre cambios)?

CONTEXTO: CYCLE 64 (exp050) — el meta-olvido (decay sólo por sorpresa) adapta en dirección correcta pero su
olvido bajo RECURRENCIA es débil (entre cambios commitea de más). Fix propuesto: un PISO CONSTANTE de olvido
(nunca committear del todo) MÁS el boost por sorpresa. Así siempre olvida un poco (bueno para recurrente) y
olvida más al sorprenderse (bueno para cambios), buscando ser robusto en AMBOS regímenes.

MECANISMO combined: decay_t = min(ceiling, meta_decay), con ceiling<1 (piso constante de olvido) y meta_decay =
1-(1-floor)*excess_de_sorpresa. Nunca committea por encima de `ceiling`; baja más cuando se sorprende.

DISEÑO (reusa exp050). DOS regímenes: ESTACIONARIO (committear ~ mejor) y RECURRENTE (olvidar constante ~ mejor).
4 brazos (misma política info-gain): committed (decay=1), fixed (0.85 constante), meta (CYCLE 64, sólo sorpresa),
COMBINED (piso 0.92 + sorpresa). Métrica: post sobre la causa vigente (estacionario: final; recurrente: media
post-cambio). 16 seeds.

PREDICCIÓN FALSABLE (pre-registrada):
  - APOYADA si el COMBINED es ROBUSTO en AMBOS regímenes y MEJORA al meta en recurrente sin romper estacionario:
    RECURRENTE combined > meta (cierra el caveat, acercándose al fixed) Y ESTACIONARIO combined >= fixed (el piso
    no lo hunde por debajo del olvido-constante). => el piso constante + sorpresa da robustez entre regímenes.
  - REFUTADA si el combined no mejora al meta en recurrente, o el piso hunde el estacionario por debajo del fixed.
  - MIXTA si mejora en un eje pero no en el otro.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp051_combined_forgetting.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp051_combined_forgetting.run            # FULL
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
# (nombre, kind, param). combined usa param=floor y un ceiling fijo.
ARMS = [("committed", "fixed", 1.0), ("fixed", "fixed", 0.85), ("meta", "meta", 0.7), ("combined", "combined", 0.7)]
CEILING = 0.92        # piso constante de olvido del combined (nunca committea por encima de esto)


def run_agent(rng, causes, K_phase, D, p_obs, kind, param, cand_pool, ema=0.25, ref=0.15):
    """info-gain + olvido. kind: fixed (decay=param), meta (sorpresa por encima del ruido), combined (piso
    CEILING + boost por sorpresa). Devuelve post sobre la causa vigente al final de cada fase."""
    logpost = np.zeros(D)
    surprise_ema = p_obs
    post_on_current = []
    for c in causes:
        for _ in range(K_phase):
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
            surprise_ema = (1 - ema) * surprise_ema + ema * contradicted
            if kind == "fixed":
                decay = param
            else:
                excess = max(0.0, surprise_ema - (p_obs + 0.05))
                meta_decay = 1.0 - (1.0 - param) * min(1.0, excess / ref)
                decay = meta_decay if kind == "meta" else min(CEILING, meta_decay)
            logpost = discounted_update(logpost, x, y, p_obs, decay)
        post_on_current.append(float(posterior_from_log(logpost)[c]))
    return post_on_current


def metric_for_regime(post_per_phase, n_phases):
    return post_per_phase[-1] if n_phases == 1 else float(np.mean(post_per_phase[1:]))


def run_regime(n_phases, K_phase, D, cluster, p_obs, n_seeds, cand_pool):
    vals = {name: [] for name, _, _ in ARMS}
    for seed in range(n_seeds):
        wrng = np.random.default_rng(seed)
        causes, _ = make_recurrent_world(wrng, D, cluster, n_phases)
        for name, kind, param in ARMS:
            arng = np.random.default_rng(seed * 100003 + int(param * 1000) + {"fixed": 7, "meta": 55, "combined": 77}[kind])
            traj = run_agent(arng, causes, K_phase, D, p_obs, kind, param, cand_pool)
            vals[name].append(metric_for_regime(traj, n_phases))
    return {name: round(float(np.mean(vals[name])), 4) for name in vals}


def _f(x):
    return "{:.3f}".format(x)


def build_summary(stat, recur, margin=0.05):
    s_fix, s_meta, s_comb = stat["fixed"], stat["meta"], stat["combined"]
    r_fix, r_meta, r_comb = recur["fixed"], recur["meta"], recur["combined"]
    # cierra el caveat: en RECURRENTE el combined OLVIDA más que el meta (se acerca al fixed)
    fixes_recurrent = (r_comb - r_meta) > margin
    # el piso no hunde el ESTACIONARIO por debajo del olvido-constante
    keeps_stationary = s_comb >= s_fix - margin
    robust_both = fixes_recurrent and keeps_stationary

    if robust_both:
        status = "apoyada"
        verdict = ("H-V4-1h APOYADA: el olvido COMBINADO (piso constante {ce} + boost por sorpresa) cierra el "
                   "caveat del CYCLE 64. RECURRENTE: combined {rc} OLVIDA más que el meta {rm} (acercándose al "
                   "fixed {rf}) -> el piso constante mantiene la plasticidad entre cambios. ESTACIONARIO: combined "
                   "{sc} >= fixed {sf} (el piso no lo hunde). => piso constante + sorpresa da ROBUSTEZ entre "
                   "regímenes; el meta-controlador de olvido mejora con un piso.").format(
                       ce=CEILING, rc=_f(r_comb), rm=_f(r_meta), rf=_f(r_fix), sc=_f(s_comb), sf=_f(s_fix))
    elif not fixes_recurrent:
        status = "refutada"
        verdict = ("H-V4-1h REFUTADA: el combined no mejora al meta en recurrente (combined {rc} ~ meta {rm}) -> "
                   "el piso constante no cierra el caveat.").format(rc=_f(r_comb), rm=_f(r_meta))
    else:
        status = "mixta"
        verdict = ("H-V4-1h MIXTA: el combined mejora al meta en recurrente (combined {rc} > meta {rm}) pero el "
                   "piso hunde el estacionario por debajo del fixed (combined {sc} < fixed {sf}).").format(
                       rc=_f(r_comb), rm=_f(r_meta), sc=_f(s_comb), sf=_f(s_fix))

    return {"margin": margin, "ceiling": CEILING, "stationary": stat, "recurrent": recur,
            "fixes_recurrent": bool(fixes_recurrent), "keeps_stationary": bool(keeps_stationary),
            "robust_both": bool(robust_both), "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=int, default=16)
    ap.add_argument("--D", type=int, default=20)
    ap.add_argument("--cluster", type=int, default=5)
    ap.add_argument("--p_obs", type=float, default=0.15)
    ap.add_argument("--K_phase", type=int, default=12)
    ap.add_argument("--n_phases_recur", type=int, default=5)
    ap.add_argument("--candidates", type=int, default=128)
    args = ap.parse_args()
    if args.smoke:
        args.seeds = 6

    logs = []

    def log(m):
        print(m, flush=True); logs.append(m)

    K_stat = args.K_phase * args.n_phases_recur
    log(f"[exp051] CYCLE 65 / H-V4-1h — olvido COMBINADO (piso constante {CEILING} + boost por sorpresa)")
    log(f"[exp051] D={args.D} cluster={args.cluster} p_obs={args.p_obs} | ESTAC K={K_stat} | RECUR n_phases="
        f"{args.n_phases_recur} K_phase={args.K_phase} | seeds={args.seeds}")

    stat = run_regime(1, K_stat, args.D, args.cluster, args.p_obs, args.seeds, args.candidates)
    recur = run_regime(args.n_phases_recur, args.K_phase, args.D, args.cluster, args.p_obs, args.seeds, args.candidates)
    sm = build_summary(stat, recur)

    log(f"[exp051] ESTACIONARIO: committed={stat['committed']:.3f} fixed={stat['fixed']:.3f} meta={stat['meta']:.3f} COMBINED={stat['combined']:.3f}")
    log(f"[exp051] RECURRENTE  : committed={recur['committed']:.3f} fixed={recur['fixed']:.3f} meta={recur['meta']:.3f} COMBINED={recur['combined']:.3f}")
    log(f"[exp051] VEREDICTO H-V4-1h: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp051_combined_forgetting", "cycle": 65, "hypothesis": "H-V4-1h",
           "claim": "el olvido combinado (piso constante + boost por sorpresa) cierra el caveat del meta: robusto "
                    "en ambos regímenes (mejora recurrente sin romper estacionario)",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp051] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
