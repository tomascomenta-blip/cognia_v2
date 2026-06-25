r"""
exp045 — CYCLE 59 / H-V4-1e (North-Star R-VALOR x memoria): OLVIDO ADAPTATIVO dirigido por SORPRESA. El agente
detecta ENDÓGENAMENTE que el mundo cambió (sus predicciones se CONTRADICEN) y SUBE el olvido automáticamente,
SIN que le digan cuándo cambió la causa. Unifica CYCLE 57 (confianza/sorpresa) + CYCLE 58 (olvido).

CONTEXTO: exp044 (CYCLE 58, H-V4-1d) mostró que el olvido FIJO (decay<1) adapta donde el committed (decay=1)
queda atascado — pero el decay FIJO (a) hay que elegirlo a priori y (b) olvida SIEMPRE, aun cuando el mundo es
estable (un decay agresivo 0.7 estropea la fase 1). Límites #1/#2 de exp044: olvido ADAPTATIVO + detección de
cambio ENDÓGENA. Idea: cuando la observación CONTRADICE la creencia confiada del agente (predijo el resultado
equivocado -> sorpresa alta), el mundo probablemente cambió -> olvidar. Cuando confirma -> committear (decay=1).
Así el agente es ESTABLE cuando el mundo es estable y PLÁSTICO cuando cambió, SIN saber cuándo cambió.

ANALOGÍA: estudiás un tema y te va bien en los ejercicios (tus respuestas aciertan -> seguís con lo que sabés).
De golpe empezás a fallar TODO (sorpresa) -> 'algo cambió' -> soltás lo viejo y re-estudiás. No necesitás que
nadie te avise que cambió el temario: lo detectás por tus propios errores.

DISEÑO (reusa exp044/exp022). Mundo no-estacionario: c_old por K1 (commitment), c_new por K2 (adaptación). 4
brazos, MISMA política (info-gain), distinto OLVIDO:
  - committed:        decay=1.0 (acumula todo) -> atascado (control de exp044).
  - fixed_mild:       decay=0.9 fijo (mejor olvido fijo de exp044).
  - fixed_aggressive: decay=0.6 fijo (olvida mucho -> estropea fase 1).
  - ADAPTIVE:         decay_t = floor si la obs CONTRADICE (P(y_obs|posterior) < 0.5) si no 1.0 -> olvida SÓLO
                      cuando se sorprende. Detección de cambio endógena, sin saber cuándo.
Métricas: post sobre la causa NUEVA al final (adaptación) y sobre la vieja al fin de fase 1 (estabilidad). 24 seeds.

PREDICCIÓN FALSABLE (pre-registrada):
  - APOYADA si el ADAPTIVE logra el trade-off estabilidad-plasticidad ENDÓGENO: (a) ADAPTA (post_c_new >= 0.40 Y
    >committed por >0.20, usando SÓLO su sorpresa, sin saber cuándo cambió) Y (b) mantiene ESTABILIDAD de fase 1
    (post_c_old_midpoint >= 0.80, MUY por encima del fixed_aggressive que la estropea). => el olvido dirigido por
    sorpresa detecta el cambio y se adapta sin perder lo aprendido cuando el mundo era estable.
  - REFUTADA si el ADAPTIVE no adapta (post_c_new ~ committed) o sacrifica la fase 1 (midpoint < fixed_aggressive).
  - MIXTA si adapta pero su estabilidad o adaptación quedan a medias.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp045_adaptive_forgetting.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp045_adaptive_forgetting.run            # FULL
"""
import argparse
import json
import os
import platform
import sys

import numpy as np

from cognia_x.experiments.exp022_endogenous_value.run import (
    binary_entropy, posterior_from_log, sample_intervention, observe_y)
from cognia_x.experiments.exp044_nonstationary_forgetting.run import make_ns_world, discounted_update

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")
# (nombre, tipo, param). tipo "fixed"=decay constante; "adaptive"=decay por sorpresa con floor=param.
ARMS = [("committed", "fixed", 1.0), ("fixed_mild", "fixed", 0.9), ("fixed_aggressive", "fixed", 0.6),
        ("adaptive", "adaptive", 0.6)]
ARM_OFFSET = {name: i + 1 for i, (name, _, _) in enumerate(ARMS)}   # determinista (NO hash(): randomizado por proceso)


def run_agent(rng, K1, K2, D, c_old, c_new, p_obs, cand_pool, kind, param):
    """info-gain en mundo no-estacionario, con OLVIDO fijo (kind='fixed', decay=param) o ADAPTATIVO
    (kind='adaptive', decay_t=floor=param si la obs contradice P(y|post)<0.5, si no 1.0)."""
    logpost = np.zeros(D)
    K = K1 + K2
    p_old_mid = p_new_mid = 0.0
    n_forget = 0
    for t in range(K):
        c = c_old if t < K1 else c_new
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
        else:                                                # adaptativo: ¿la obs contradice mi predicción?
            pred_y1 = float(P1[j])                            # P(y=1|x, posterior actual)
            p_obs_y = pred_y1 if y == 1 else 1.0 - pred_y1    # verosimilitud predictiva de lo observado
            decay = param if p_obs_y < 0.5 else 1.0           # contradicho -> olvida; confirmado -> committea
            if p_obs_y < 0.5:
                n_forget += 1
        logpost = discounted_update(logpost, x, y, p_obs, decay)
        if t == K1 - 1:
            pm = posterior_from_log(logpost)
            p_old_mid, p_new_mid = float(pm[c_old]), float(pm[c_new])
    post = posterior_from_log(logpost)
    return post, p_old_mid, p_new_mid, n_forget


def run(D, cluster, p_obs, K1, K2, n_seeds, cand_pool):
    per_seed = []
    for seed in range(n_seeds):
        wrng = np.random.default_rng(seed)
        c_old, c_new, _ = make_ns_world(wrng, D, cluster)
        cell = {}
        for name, kind, param in ARMS:
            arng = np.random.default_rng(seed * 100003 + ARM_OFFSET[name] * 101 + 7)
            post, p_old_mid, p_new_mid, n_forget = run_agent(arng, K1, K2, D, c_old, c_new, p_obs,
                                                             cand_pool, kind, param)
            cell[name] = {"post_c_new_final": float(post[c_new]), "post_c_old_final": float(post[c_old]),
                          "post_c_old_midpoint": p_old_mid, "n_forget_steps": n_forget}
        per_seed.append({"seed": seed, "c_old": c_old, "c_new": c_new, "by_arm": cell})

    def mean(name, key):
        return round(float(np.mean([s["by_arm"][name][key] for s in per_seed])), 4)

    by_arm = {name: {"post_c_new_final": mean(name, "post_c_new_final"),
                     "post_c_old_final": mean(name, "post_c_old_final"),
                     "post_c_old_midpoint": mean(name, "post_c_old_midpoint"),
                     "n_forget_steps": mean(name, "n_forget_steps")} for name, _, _ in ARMS}
    return per_seed, by_arm


def build_summary(by_arm, per_seed, K2):
    committed = by_arm["committed"]
    aggressive = by_arm["fixed_aggressive"]
    adaptive = by_arm["adaptive"]
    adapts = (adaptive["post_c_new_final"] >= 0.40 and
              (adaptive["post_c_new_final"] - committed["post_c_new_final"]) > 0.20)
    stable_phase1 = adaptive["post_c_old_midpoint"] >= 0.80
    beats_aggressive_stability = adaptive["post_c_old_midpoint"] > aggressive["post_c_old_midpoint"] + 0.05

    if adapts and stable_phase1 and beats_aggressive_stability:
        status = "apoyada"
        verdict = ("H-V4-1e APOYADA: el OLVIDO ADAPTATIVO dirigido por SORPRESA logra el trade-off "
                   "estabilidad-plasticidad ENDÓGENO, SIN saber cuándo cambió la causa. ADAPTA (post_c_new "
                   "adaptive={an:.3f} vs committed={cn:.3f}, +{g:.3f}) Y mantiene la fase 1 (midpoint "
                   "adaptive={am:.3f} >> fixed_aggressive={gm:.3f}). El agente OLVIDA sólo cuando sus "
                   "predicciones se contradicen ({nf:.1f} pasos de olvido de {K2} de adaptación) -> detección "
                   "de cambio endógena. Une CYCLE 57 (sorpresa/confianza) + CYCLE 58 (olvido).").format(
                       an=adaptive["post_c_new_final"], cn=committed["post_c_new_final"],
                       g=adaptive["post_c_new_final"] - committed["post_c_new_final"],
                       am=adaptive["post_c_old_midpoint"], gm=aggressive["post_c_old_midpoint"],
                       nf=adaptive["n_forget_steps"], K2=K2)
    elif not adapts:
        status = "refutada"
        verdict = ("H-V4-1e REFUTADA: el olvido adaptativo NO adapta (post_c_new={an:.3f} ~ committed={cn:.3f}) "
                   "-> la sorpresa no dispara olvido suficiente.").format(
                       an=adaptive["post_c_new_final"], cn=committed["post_c_new_final"])
    else:
        status = "mixta"
        verdict = ("H-V4-1e MIXTA: el adaptativo adapta (post_c_new={an:.3f}) pero su estabilidad de fase 1 "
                   "(midpoint={am:.3f}) no domina claramente al fixed_aggressive ({gm:.3f}); trade-off a medias.").format(
                       an=adaptive["post_c_new_final"], am=adaptive["post_c_old_midpoint"],
                       gm=aggressive["post_c_old_midpoint"])

    return {"arms": [a[0] for a in ARMS], "n_seeds": len(per_seed), "by_arm": by_arm, "adapts": bool(adapts),
            "stable_phase1": bool(stable_phase1), "beats_aggressive_stability": bool(beats_aggressive_stability),
            "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=int, default=24)
    ap.add_argument("--D", type=int, default=20)
    ap.add_argument("--cluster", type=int, default=5)
    ap.add_argument("--p_obs", type=float, default=0.15)
    ap.add_argument("--K1", type=int, default=60)
    ap.add_argument("--K2", type=int, default=12)
    ap.add_argument("--candidates", type=int, default=128)
    args = ap.parse_args()
    if args.smoke:
        args.seeds = 8

    logs = []

    def log(m):
        print(m, flush=True); logs.append(m)

    log(f"[exp045] CYCLE 59 / H-V4-1e — olvido ADAPTATIVO dirigido por sorpresa (detección de cambio endógena)")
    log(f"[exp045] D={args.D} cluster={args.cluster} p_obs={args.p_obs} K1={args.K1} K2={args.K2} seeds={args.seeds}")

    per_seed, by_arm = run(args.D, args.cluster, args.p_obs, args.K1, args.K2, args.seeds, args.candidates)
    sm = build_summary(by_arm, per_seed, args.K2)

    log(f"[exp045] por brazo (ADAPTACIÓN = post causa nueva final; ESTABILIDAD = post causa vieja midpoint):")
    for name, _, _ in ARMS:
        b = by_arm[name]
        log(f"[exp045]   {name:>16}: post_c_new={b['post_c_new_final']:.3f} midpoint={b['post_c_old_midpoint']:.3f} "
            f"n_forget={b['n_forget_steps']:.1f}")
    log(f"[exp045] VEREDICTO H-V4-1e: {sm['status'].upper()}")
    log(f"[exp045] {sm['verdict']}")

    out = {"exp": "exp045_adaptive_forgetting", "cycle": 59, "hypothesis": "H-V4-1e",
           "claim": "el olvido adaptativo dirigido por sorpresa logra el trade-off estabilidad-plasticidad "
                    "endógeno (adapta sin saber cuándo cambió la causa, sin perder la fase 1)",
           "verdict": sm["status"], "summary": sm, "per_seed": per_seed,
           "params": {"D": args.D, "cluster": args.cluster, "p_obs": args.p_obs, "K1": args.K1, "K2": args.K2,
                      "seeds": args.seeds, "candidates": args.candidates},
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    path = os.path.join(RESULTS, "results.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp045] escrito {path}")


if __name__ == "__main__":
    main()
