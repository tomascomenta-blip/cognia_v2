r"""
exp052 — CYCLE 66 / H-V4-1i (North-Star R-VALOR x memoria, cierre del arco): SELECTOR DE ESTRATEGIA de memoria —
el agente CLASIFICA el régimen de su propia sorpresa SOSTENIDA y CONMUTA la ESTRATEGIA (committear vs
olvidar-fuerte), una decisión DISCRETA, en vez de modular la TASA de olvido.

CONTEXTO: CYCLE 64/65 mostraron que modular la TASA de olvido (meta, combined) NO alcanza el óptimo en regímenes
opuestos -- el trade-off estabilidad-plasticidad es fundamental para un escalar. CYCLE 65 concluyó: hace falta
DETECTAR el régimen y CAMBIAR de ESTRATEGIA (discreto). Este ciclo lo prueba: el agente estima su sorpresa
sostenida (EMA por encima del piso de ruido); si es BAJA persistente -> régimen ESTABLE -> estrategia COMMITTEAR
(decay=1); si es ALTA persistente -> régimen CAMBIANTE -> estrategia OLVIDAR-FUERTE (decay=forget). Decisión
binaria de estrategia, no un escalar continuo.

ANALOGÍA: en vez de "olvidar un poquito proporcional a tu sorpresa", DECIDÍS: si el temario está estable, te
quedás con lo que sabés (committear); si cambia seguido, adoptás el modo "soltar y re-estudiar" (olvidar-fuerte).
Es una decisión de MODO, no de intensidad.

DISEÑO (reusa exp050/exp051). DOS regímenes: ESTACIONARIO (committear ~ mejor) y RECURRENTE (olvidar-fuerte ~
mejor). 3 brazos (misma política info-gain): committed (decay=1), fixed (0.85 constante), SELECTOR (clasifica el
régimen de su sorpresa sostenida y conmuta committear<->olvidar-fuerte). Métrica: post sobre la causa vigente
(estacionario: final; recurrente: media post-cambio). 16 seeds.

PREDICCIÓN FALSABLE (pre-registrada):
  - APOYADA si el SELECTOR alcanza el ÓPTIMO de cada régimen (lo que rate-modulation no pudo): ESTACIONARIO
    selector ~ committed (>= committed - margen, >> fixed) Y RECURRENTE selector ~ fixed (>= fixed - margen, >>
    committed). => el valor endógeno elige la ESTRATEGIA de memoria (decisión discreta), cerrando el arco.
  - REFUTADA si el selector no alcanza el óptimo en algún régimen (clasifica mal o conmuta tarde).
  - MIXTA si alcanza el óptimo en un régimen pero no en el otro.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp052_strategy_selector.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp052_strategy_selector.run            # FULL
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
ARMS = [("committed", "fixed", 1.0), ("fixed", "fixed", 0.85), ("selector", "selector", 0.85)]


def run_agent(rng, causes, K_phase, D, p_obs, kind, param, cand_pool, ema=0.15, thresh_buf=0.12):
    """info-gain + olvido. kind: fixed (decay=param) o selector (clasifica el régimen de la sorpresa SOSTENIDA y
    conmuta committear<->olvidar-fuerte). Devuelve post sobre la causa vigente al final de cada fase."""
    logpost = np.zeros(D)
    surprise_ema = p_obs
    thresh = p_obs + thresh_buf       # umbral de sorpresa por encima del piso de ruido -> régimen CAMBIANTE
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
            else:  # selector: DECISIÓN DISCRETA de estrategia según el régimen clasificado
                decay = param if surprise_ema > thresh else 1.0   # cambiante -> olvidar-fuerte; estable -> committear
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
            arng = np.random.default_rng(seed * 100003 + {"committed": 7, "fixed": 13, "selector": 91}[name])
            traj = run_agent(arng, causes, K_phase, D, p_obs, kind, param, cand_pool)
            vals[name].append(metric_for_regime(traj, n_phases))
    return {name: round(float(np.mean(vals[name])), 4) for name in vals}


def _f(x):
    return "{:.3f}".format(x)


def build_summary(stat, recur, margin=0.10):
    s_com, s_fix, s_sel = stat["committed"], stat["fixed"], stat["selector"]
    r_com, r_fix, r_sel = recur["committed"], recur["fixed"], recur["selector"]
    # ÓPTIMO de cada régimen: committed en estacionario, fixed en recurrente.
    sel_optimal_stat = (s_sel >= s_com - margin) and (s_sel > s_fix + margin / 2)
    sel_optimal_recur = (r_sel >= r_fix - margin) and (r_sel > r_com + margin)

    if sel_optimal_stat and sel_optimal_recur:
        status = "apoyada"
        verdict = ("H-V4-1i APOYADA: el SELECTOR DE ESTRATEGIA alcanza el ÓPTIMO de cada régimen (lo que la "
                   "modulación de TASA no pudo, CYCLE 64/65). ESTACIONARIO: selector {ss} ~ committed {sc} (>> "
                   "fixed {sf}) -> clasifica ESTABLE y COMMITTEA. RECURRENTE: selector {rs} ~ fixed {rf} (>> "
                   "committed {rc}) -> clasifica CAMBIANTE y OLVIDA-FUERTE. El agente DETECTA el régimen de su "
                   "propia sorpresa sostenida y CONMUTA la ESTRATEGIA (decisión discreta) -> el valor endógeno "
                   "elige la ESTRATEGIA de memoria, no sólo el ritmo. CIERRA el arco R-VALOR x memoria.").format(
                       ss=_f(s_sel), sc=_f(s_com), sf=_f(s_fix), rs=_f(r_sel), rf=_f(r_fix), rc=_f(r_com))
    elif not sel_optimal_stat and not sel_optimal_recur:
        status = "refutada"
        verdict = ("H-V4-1i REFUTADA: el selector no alcanza el óptimo en ningún régimen (estacionario sel {ss} "
                   "vs com {sc}/fix {sf}; recurrente sel {rs} vs com {rc}/fix {rf}) -> clasifica/conmuta mal.").format(
                       ss=_f(s_sel), sc=_f(s_com), sf=_f(s_fix), rs=_f(r_sel), rc=_f(r_com), rf=_f(r_fix))
    else:
        status = "mixta"
        verdict = ("H-V4-1i MIXTA: el selector alcanza el óptimo en UN régimen pero no en el otro (estacionario "
                   "óptimo={os}; recurrente óptimo={or_}). ESTAC sel {ss}/com {sc}/fix {sf}; RECUR sel {rs}/com "
                   "{rc}/fix {rf}.").format(os=sel_optimal_stat, or_=sel_optimal_recur, ss=_f(s_sel), sc=_f(s_com),
                                            sf=_f(s_fix), rs=_f(r_sel), rc=_f(r_com), rf=_f(r_fix))

    return {"margin": margin, "stationary": stat, "recurrent": recur,
            "sel_optimal_stat": bool(sel_optimal_stat), "sel_optimal_recur": bool(sel_optimal_recur),
            "status": status, "verdict": verdict}


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
    log(f"[exp052] CYCLE 66 / H-V4-1i — SELECTOR DE ESTRATEGIA (clasifica el régimen y conmuta committear/olvidar)")
    log(f"[exp052] D={args.D} cluster={args.cluster} p_obs={args.p_obs} | ESTAC K={K_stat} | RECUR n_phases="
        f"{args.n_phases_recur} K_phase={args.K_phase} | seeds={args.seeds}")

    stat = run_regime(1, K_stat, args.D, args.cluster, args.p_obs, args.seeds, args.candidates)
    recur = run_regime(args.n_phases_recur, args.K_phase, args.D, args.cluster, args.p_obs, args.seeds, args.candidates)
    sm = build_summary(stat, recur)

    log(f"[exp052] ESTACIONARIO (committear óptimo): committed={stat['committed']:.3f} fixed={stat['fixed']:.3f} SELECTOR={stat['selector']:.3f}")
    log(f"[exp052] RECURRENTE  (olvidar óptimo)    : committed={recur['committed']:.3f} fixed={recur['fixed']:.3f} SELECTOR={recur['selector']:.3f}")
    log(f"[exp052] VEREDICTO H-V4-1i: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp052_strategy_selector", "cycle": 66, "hypothesis": "H-V4-1i",
           "claim": "un selector de estrategia (clasifica el régimen de la sorpresa y conmuta committear/olvidar-"
                    "fuerte, decisión discreta) alcanza el óptimo en ambos regímenes, lo que la modulación de tasa no pudo",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp052] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
