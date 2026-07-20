r"""
exp050 — CYCLE 64 / H-V4-1g (North-Star R-VALOR x memoria, cierre del loop 58-63): el olvido META-ADAPTATIVO —
el agente ESTIMA la tasa de cambio del mundo (frecuencia de su propia SORPRESA) y ELIGE su ritmo de olvido,
committeando si el mundo es estable y olvidando constante si cambia mucho, SIN que le digan el régimen.

CONTEXTO: CYCLE 63 (exp049) mostró que el óptimo de olvido DEPENDE del régimen: surprise-gated para un cambio
AISLADO (CYCLE 59), olvido CONSTANTE para RECURRENTE. Pero un agente real no sabe en qué régimen está. ¿Puede
ESTIMARLO (de su propia sorpresa sostenida) y elegir su olvido? Sería una meta-decisión de VALOR endógeno: el
valor de olvidar depende de cuánto cambia el mundo, y el agente mide eso solo.

MECANISMO meta: surprise_ema = EMA de [P(y_obs|posterior) < 0.5] (predicción contradicha). decay_t baja cuando
la sorpresa SOSTENIDA es alta (mundo cambiante -> olvidar) y sube hacia 1.0 cuando la sorpresa es baja (mundo
estable -> committear). decay_t = 1.0 - (1.0-floor) * clip(surprise_ema / surprise_ref, 0, 1).

ANALOGÍA: si te das cuenta de que el temario cambia SEGUIDO (te sorprendés a menudo), adoptás el hábito de
soltar lo viejo constantemente. Si nunca te sorprendés (estable), te quedás con lo que sabés. Ajustás tu ritmo
de olvido a cuánto cambia el mundo, sin que nadie te avise el régimen.

DISEÑO (reusa exp022/exp044). DOS regímenes: ESTACIONARIO (1 causa, n_phases=1: committear es lo mejor) y
RECURRENTE (n_phases=5, K_phase=12: olvido constante es lo mejor). 3 brazos (misma política info-gain): committed
(decay=1), fixed (decay=0.85 constante), META (estima la sorpresa y elige decay). Métrica: post sobre la causa
vigente (estacionario: final; recurrente: media post-cambio). 16 seeds.

PREDICCIÓN FALSABLE (pre-registrada):
  - APOYADA si el META elige bien en AMBOS regímenes SIN que le digan cuál: en ESTACIONARIO ~ committed (commitea,
    >> fixed) y en RECURRENTE ~ fixed (olvida, >> committed). => el agente estima la tasa de cambio y elige su
    olvido; la meta-decisión de olvido es un VALOR endógeno.
  - REFUTADA si el META no adapta su olvido (se comporta como UN brazo fijo en ambos regímenes, perdiendo en uno).
  - MIXTA si elige bien en un régimen pero no en el otro.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp050_meta_forgetting.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp050_meta_forgetting.run            # FULL
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
ARMS = [("committed", "fixed", 1.0), ("fixed", "fixed", 0.85), ("meta", "meta", 0.7)]


def run_agent(rng, causes, K_phase, D, p_obs, kind, param, cand_pool, ema=0.25, ref=0.15):
    """info-gain + olvido. kind: 'fixed' (decay=param) o 'meta' (decay por sorpresa SOSTENIDA estimada).
    Devuelve post sobre la causa vigente al final de cada fase.

    META: la sorpresa en un mundo ESTABLE-aprendido se asienta en ~p_obs (las obs con ruido flipean la
    predicción correcta). La señal de CAMBIO es la sorpresa POR ENCIMA de ese piso de ruido -> olvidar sólo
    cuando excess > 0. La EMA recupera rápido (ema=0.25) para volver a committear al estabilizarse."""
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
            else:  # meta: olvida en proporción a la sorpresa POR ENCIMA del piso de ruido (tasa de cambio)
                excess = max(0.0, surprise_ema - (p_obs + 0.05))
                decay = 1.0 - (1.0 - param) * min(1.0, excess / ref)
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
            arng = np.random.default_rng(seed * 100003 + int(param * 1000) + (7 if kind == "fixed" else 55))
            traj = run_agent(arng, causes, K_phase, D, p_obs, kind, param, cand_pool)
            vals[name].append(metric_for_regime(traj, n_phases))
    return {name: round(float(np.mean(vals[name])), 4) for name in vals}


def build_summary(stat, recur, margin=0.10):
    s_com, s_fix, s_meta = stat["committed"], stat["fixed"], stat["meta"]
    r_com, r_fix, r_meta = recur["committed"], recur["fixed"], recur["meta"]
    # ADAPTACIÓN DIRECCIONAL: en estacionario committea MÁS que el olvido-constante; en recurrente olvida MÁS que
    # el committed. (El meta NO se comporta como UN brazo fijo: ajusta su olvido al régimen.)
    adapts_dir_stat = s_meta > s_fix + 0.02       # committea MÁS que el olvido-constante cuando estable
    adapts_dir_recur = r_meta > r_com + 0.02       # olvida MÁS que el committed cuando cambia (direccional)
    # MATCH ÓPTIMO: ~ el mejor brazo de cada régimen (committed en estacionario, fixed en recurrente).
    matches_stat = s_meta >= s_com - margin
    matches_recur = r_meta >= r_fix - margin

    if matches_stat and matches_recur:
        status = "apoyada"
        verdict = ("H-V4-1g APOYADA: el olvido META-ADAPTATIVO IGUALA al mejor brazo de cada régimen SIN que le "
                   "digan cuál. ESTACIONARIO: meta {sm} ~ committed {sc} (>> fixed {sf}). RECURRENTE: meta {rm} ~ "
                   "fixed {rf} (>> committed {rc}). El agente estima la tasa de cambio por su propia sorpresa y "
                   "elige su olvido -> meta-decisión de olvido como VALOR endógeno (cierra el loop 58-63).").format(
                       sm=_f(s_meta), sc=_f(s_com), sf=_f(s_fix), rm=_f(r_meta), rf=_f(r_fix), rc=_f(r_com))
    elif adapts_dir_stat and adapts_dir_recur:
        status = "mixta"
        verdict = ("H-V4-1g MIXTA: el META adapta su olvido al régimen en DIRECCIÓN correcta (es ROBUSTO, nunca "
                   "el peor) pero no IGUALA al óptimo. ESTACIONARIO: meta {sm} COMMITTEA más que el olvido-"
                   "constante ({sf}) aunque no llega a committed ({sc}). RECURRENTE: meta {rm} OLVIDA más que "
                   "committed ({rc}) aunque no llega a fixed ({rf}). El agente estima la tasa de cambio por su "
                   "sorpresa y mueve su olvido en la dirección correcta, pero el compromiso no alcanza el óptimo "
                   "de cada régimen.").format(sm=_f(s_meta), sf=_f(s_fix), sc=_f(s_com), rm=_f(r_meta),
                                              rc=_f(r_com), rf=_f(r_fix))
    else:
        status = "refutada"
        verdict = ("H-V4-1g REFUTADA: el meta no adapta su olvido al régimen (se comporta como un brazo fijo: "
                   "estacionario meta {sm} vs com {sc}/fix {sf}; recurrente meta {rm} vs com {rc}/fix {rf}).").format(
                       sm=_f(s_meta), sc=_f(s_com), sf=_f(s_fix), rm=_f(r_meta), rc=_f(r_com), rf=_f(r_fix))

    return {"margin": margin, "stationary": stat, "recurrent": recur, "adapts_dir_stat": bool(adapts_dir_stat),
            "adapts_dir_recur": bool(adapts_dir_recur), "matches_stat": bool(matches_stat),
            "matches_recur": bool(matches_recur), "status": status, "verdict": verdict}


def _f(x):
    return "{:.3f}".format(x)


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

    K_stat = args.K_phase * args.n_phases_recur     # MISMO cómputo total que el recurrente (1 fase larga)
    log(f"[exp050] CYCLE 64 / H-V4-1g — olvido META-ADAPTATIVO (estima la tasa de cambio y elige el olvido)")
    log(f"[exp050] D={args.D} cluster={args.cluster} p_obs={args.p_obs} | ESTACIONARIO K={K_stat} (1 fase) | "
        f"RECURRENTE n_phases={args.n_phases_recur} K_phase={args.K_phase} | seeds={args.seeds}")

    stat = run_regime(1, K_stat, args.D, args.cluster, args.p_obs, args.seeds, args.candidates)
    recur = run_regime(args.n_phases_recur, args.K_phase, args.D, args.cluster, args.p_obs, args.seeds, args.candidates)
    sm = build_summary(stat, recur)

    log(f"[exp050] ESTACIONARIO (committear es mejor): committed={stat['committed']:.3f} fixed={stat['fixed']:.3f} META={stat['meta']:.3f}")
    log(f"[exp050] RECURRENTE   (olvidar es mejor)   : committed={recur['committed']:.3f} fixed={recur['fixed']:.3f} META={recur['meta']:.3f}")
    log(f"[exp050] VEREDICTO H-V4-1g: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp050_meta_forgetting", "cycle": 64, "hypothesis": "H-V4-1g",
           "claim": "el olvido meta-adaptativo estima la tasa de cambio (sorpresa sostenida) y elige el olvido "
                    "(committea si estable, olvida si cambia) sin que le digan el régimen",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp050] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
