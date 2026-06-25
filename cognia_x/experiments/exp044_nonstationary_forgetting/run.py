r"""
exp044 — CYCLE 58 / H-V4-1d (North-Star R-VALOR x memoria): en un mundo NO-ESTACIONARIO (la causa CAMBIA),
¿el OLVIDO dirigido por valor (descontar evidencia vieja) permite ADAPTARSE, donde un agente COMMITTED
(acumula toda la evidencia) queda ATASCADO en la causa vieja?

CONTEXTO: el North-Star del lab (decomposition_tree) pide un valor endógeno "persiguiendo un objetivo en un
mundo NO-ESTACIONARIO, de qué información merece predecirse, escribirse, recordarse u OLVIDARSE". CYCLE 56/57
mostraron valor endógeno (info-gain) y su señal (confianza calibrada) — pero en un mundo ESTACIONARIO. Este
ciclo introduce la NO-ESTACIONARIEDAD: la causa SE MUEVE a mitad de presupuesto. Un Bayesiano que ACUMULA toda
la evidencia se queda LOCKED en la causa vieja (su posterior está committeado). Olvidar (descontar lo viejo) es
una decisión de VALOR: "la info vieja ya no vale". ¿Olvidar permite re-identificar la causa nueva? Conecta
R-VALOR con MEMORIA (escribir≡olvidar, H-V4-5).

ANALOGÍA: estudiaste para un examen y dominaste el tema (causa vieja). El temario CAMBIA. Si seguís repasando lo
viejo con la misma fe (no olvidás), seguís sabiendo lo viejo y fallás lo nuevo. Si soltás lo viejo (olvido) y
re-estudiás, te adaptás. ¿Cuánto conviene olvidar?

DISEÑO (modelo bayesiano, reusa primitivas de exp022). Mundo NO-estacionario: clúster confundido (todo vale z
en observacional); c_old=clúster[0], c_new=clúster[1]. y = x[c_old] en la 1ra mitad de las consultas, x[c_new]
en la 2da. La MISMA política (info-gain, interviene) para TODOS; lo ÚNICO que cambia es el OLVIDO: update
descontado logpost = decay*logpost + log(verosimilitud). decay=1.0 = COMMITTED (exp022); decay<1 = OLVIDO.
Barrido decay in {1.0, 0.9, 0.8, 0.7}. Métricas: post_on_c_new al final (ADAPTACIÓN), post_on_c_old (atasco),
post_on_c_old en el midpoint (que la 1ra fase SÍ identificó la vieja). 24 seeds.

PREDICCIÓN FALSABLE (pre-registrada):
  - APOYADA si el COMMITTED (decay=1) NO se adapta (post_c_new final BAJO, <=0.40, y sigue con post_c_old alto)
    Y algún OLVIDO (decay<1) SÍ se adapta (post_c_new final ALTO, >=0.60, superando al committed por >0.20),
    con la 1ra fase identificando c_old en ambos (post_c_old midpoint alto). => el olvido dirigido por valor es
    necesario para adaptarse a la no-estacionariedad.
  - REFUTADA si el committed se adapta igual (post_c_new alto aun con decay=1) o ningún olvido supera al
    committed.
  - MIXTA si el olvido ayuda pero poco, o desestabiliza (la 1ra fase no identifica).

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp044_nonstationary_forgetting.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp044_nonstationary_forgetting.run            # FULL
"""
import argparse
import json
import os
import platform
import sys

import numpy as np

from cognia_x.experiments.exp022_endogenous_value.run import (
    binary_entropy, posterior_from_log, sample_intervention, observe_y)

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")
DECAYS = [1.0, 0.9, 0.8, 0.7]


def make_ns_world(rng, D, cluster):
    """Clúster confundido; c_old=clúster[0] (causa fase 1), c_new=clúster[1] (causa fase 2)."""
    perm = rng.permutation(D)
    cluster_idx = perm[:cluster]
    return int(cluster_idx[0]), int(cluster_idx[1]), cluster_idx


def discounted_update(logpost, x, y, p_obs, decay):
    """Bayesiano DESCONTADO: la evidencia vieja se desvanece geométricamente (decay<1 = olvido)."""
    like = np.where(x == y, 1.0 - p_obs, p_obs)
    logpost = decay * logpost + np.log(like)
    return logpost - logpost.max()


def run_agent_ns(rng, K1, K2, D, c_old, c_new, p_obs, decay, cand_pool):
    """info-gain + olvido, mundo no-estacionario: causa c_old por K1 pasos (commitment profundo), luego c_new
    por K2 pasos (presupuesto de adaptación). Devuelve posterior final y post sobre c_old/c_new al fin de fase 1."""
    logpost = np.zeros(D)
    K = K1 + K2
    p_old_mid = p_new_mid = 0.0
    for t in range(K):
        c = c_old if t < K1 else c_new                       # la causa CAMBIA en K1
        post = posterior_from_log(logpost)
        cand = sample_intervention(rng, cand_pool, D)
        m = cand @ post
        P1 = p_obs + m * (1.0 - 2.0 * p_obs)
        mi = binary_entropy(P1) - binary_entropy(np.array(p_obs))
        x = cand[int(np.argmax(mi))]
        y = observe_y(rng, x[None, :], c, p_obs)[0]
        logpost = discounted_update(logpost, x, y, p_obs, decay)
        if t == K1 - 1:                                      # fin de fase 1: ¿identificó la causa vieja?
            pm = posterior_from_log(logpost)
            p_old_mid, p_new_mid = float(pm[c_old]), float(pm[c_new])
    return posterior_from_log(logpost), p_old_mid, p_new_mid


def run(D, cluster, p_obs, K1, K2, n_seeds, cand_pool):
    per_seed = []
    for seed in range(n_seeds):
        wrng = np.random.default_rng(seed)
        c_old, c_new, _ = make_ns_world(wrng, D, cluster)
        cell = {}
        for decay in DECAYS:
            arng = np.random.default_rng(seed * 100003 + int(decay * 1000) + 7)
            post, p_old_mid, p_new_mid = run_agent_ns(arng, K1, K2, D, c_old, c_new, p_obs, decay, cand_pool)
            cell[str(decay)] = {
                "post_c_old_final": float(post[c_old]), "post_c_new_final": float(post[c_new]),
                "post_c_old_midpoint": p_old_mid,     # ¿identificó la causa vieja al fin de fase 1?
                "post_c_new_atmid": p_new_mid,
            }
        per_seed.append({"seed": seed, "c_old": c_old, "c_new": c_new, "by_decay": cell})

    def mean(decay, key):
        return float(np.mean([s["by_decay"][str(decay)][key] for s in per_seed]))

    by_decay = {}
    for decay in DECAYS:
        by_decay[str(decay)] = {
            "post_c_new_final": round(mean(decay, "post_c_new_final"), 4),
            "post_c_old_final": round(mean(decay, "post_c_old_final"), 4),
            "post_c_old_midpoint": round(mean(decay, "post_c_old_midpoint"), 4),
        }
    return per_seed, by_decay


def build_summary(by_decay, per_seed):
    committed = by_decay["1.0"]
    forgetters = {d: by_decay[d] for d in by_decay if d != "1.0"}
    best_d = max(forgetters, key=lambda d: forgetters[d]["post_c_new_final"])
    best = forgetters[best_d]
    # ¿la 1ra fase identificó c_old en ambos? (no es que el olvido sea inestable desde el arranque)
    phase1_ok = committed["post_c_old_midpoint"] >= 0.50 and best["post_c_old_midpoint"] >= 0.50
    committed_stuck = committed["post_c_new_final"] <= 0.40
    forgetting_adapts = best["post_c_new_final"] >= 0.60 and (best["post_c_new_final"] - committed["post_c_new_final"]) > 0.20

    if phase1_ok and committed_stuck and forgetting_adapts:
        status = "apoyada"
        verdict = ("H-V4-1d APOYADA: en un mundo NO-ESTACIONARIO (la causa se mueve en K/2) el agente COMMITTED "
                   "(decay=1) queda ATASCADO en la causa vieja (post_c_new final={cm:.3f}, sigue con "
                   "post_c_old={co:.3f}), mientras el OLVIDO (decay={bd}) se ADAPTA (post_c_new final={bn:.3f}, "
                   "+{gap:.3f} sobre committed). Ambos identifican c_old en la 1ra fase (post_c_old midpoint "
                   "committed={c1:.3f}/olvido={b1:.3f}). => OLVIDAR (descontar lo viejo) es una decisión de VALOR "
                   "necesaria para adaptarse a la no-estacionariedad; conecta R-VALOR con memoria "
                   "(escribir≡olvidar).").format(cm=committed["post_c_new_final"], co=committed["post_c_old_final"],
                                                 bd=best_d, bn=best["post_c_new_final"],
                                                 gap=best["post_c_new_final"] - committed["post_c_new_final"],
                                                 c1=committed["post_c_old_midpoint"], b1=best["post_c_old_midpoint"])
    elif not committed_stuck:
        status = "refutada"
        verdict = ("H-V4-1d REFUTADA: el committed (decay=1) se adapta igual (post_c_new final={cm:.3f}>0.40) -> "
                   "el olvido no es necesario a esta escala.").format(cm=committed["post_c_new_final"])
    elif not phase1_ok:
        status = "mixta"
        verdict = ("H-V4-1d MIXTA: el olvido desestabiliza (la 1ra fase no identifica c_old: midpoint "
                   "committed={c1:.3f}/olvido={b1:.3f}); señal ambigua.").format(
                       c1=committed["post_c_old_midpoint"], b1=best["post_c_old_midpoint"])
    else:
        status = "mixta"
        verdict = ("H-V4-1d MIXTA: el olvido ayuda pero no supera el umbral fuerte (best post_c_new "
                   "final={bn:.3f}, committed={cm:.3f}).").format(bn=best["post_c_new_final"],
                                                                  cm=committed["post_c_new_final"])

    return {"decays": DECAYS, "n_seeds": len(per_seed), "by_decay": by_decay, "best_forgetter": best_d,
            "committed_stuck": bool(committed_stuck), "forgetting_adapts": bool(forgetting_adapts),
            "phase1_ok": bool(phase1_ok), "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=int, default=24)
    ap.add_argument("--D", type=int, default=20)
    ap.add_argument("--cluster", type=int, default=5)
    ap.add_argument("--p_obs", type=float, default=0.15)
    ap.add_argument("--K1", type=int, default=60, help="fase 1 (commitment profundo a c_old)")
    ap.add_argument("--K2", type=int, default=12, help="fase 2 (presupuesto corto de adaptación a c_new)")
    ap.add_argument("--candidates", type=int, default=128)
    args = ap.parse_args()
    if args.smoke:
        args.seeds = 8

    logs = []

    def log(m):
        print(m, flush=True); logs.append(m)

    log(f"[exp044] CYCLE 58 / H-V4-1d — mundo NO-estacionario: olvido (decay) vs committed (acumula todo)")
    log(f"[exp044] D={args.D} cluster={args.cluster} p_obs={args.p_obs} K1={args.K1} (commitment) K2={args.K2} "
        f"(adaptación) decays={DECAYS} seeds={args.seeds}")

    per_seed, by_decay = run(args.D, args.cluster, args.p_obs, args.K1, args.K2, args.seeds, args.candidates)
    sm = build_summary(by_decay, per_seed)

    log(f"[exp044] ADAPTACIÓN (post sobre la causa NUEVA al final) por decay:")
    for d in DECAYS:
        b = by_decay[str(d)]
        tag = "COMMITTED" if d == 1.0 else "olvido"
        log(f"[exp044]   decay={d} ({tag:>9}): post_c_new_final={b['post_c_new_final']:.3f} "
            f"post_c_old_final={b['post_c_old_final']:.3f} post_c_old_midpoint={b['post_c_old_midpoint']:.3f}")
    log(f"[exp044] VEREDICTO H-V4-1d: {sm['status'].upper()} (best_forgetter=decay {sm['best_forgetter']})")
    log(f"[exp044] {sm['verdict']}")

    out = {"exp": "exp044_nonstationary_forgetting", "cycle": 58, "hypothesis": "H-V4-1d",
           "claim": "en un mundo no-estacionario el olvido dirigido por valor (descontar evidencia vieja) permite "
                    "adaptarse a un cambio de causa, donde el agente committed queda atascado",
           "verdict": sm["status"], "summary": sm, "per_seed": per_seed,
           "params": {"D": args.D, "cluster": args.cluster, "p_obs": args.p_obs, "K1": args.K1,
                      "K2": args.K2, "seeds": args.seeds, "candidates": args.candidates},
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    path = os.path.join(RESULTS, "results.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp044] escrito {path}")


if __name__ == "__main__":
    main()
