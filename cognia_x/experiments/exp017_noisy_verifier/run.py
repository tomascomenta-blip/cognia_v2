"""
exp017 — CYCLE 30: H-LEARN-2. ¿Hasta qué RUIDO del verificador sobrevive la auto-mejora verificada?

CONTEXTO (CYCLE 29, exp016, H-LEARN-1 apoyada): con un oráculo PERFECTO, entrenar SOLO con las
auto-generaciones VERIFICADO-CORRECTAS produce auto-mejora (STaR); la señal de corrección es el motor.
Pero los verificadores reales son RUIDOSOS. H-LEARN-2: ¿hasta qué tasa de FALSO POSITIVO del verificador
(acepta una generación INCORRECTA) sobrevive la auto-mejora, antes de degradar hacia el régimen naive?

MODELO DE RUIDO (falso-positivo, el peligroso/realista): un verificador con ruido eps acepta una
generación si es CORRECTA, o si es INCORRECTA con probabilidad eps. eps=0 = oráculo perfecto (= verified
de exp016); eps=1 = acepta TODO (= naive_all). El barrido de eps es una curva DOSIS-RESPUESTA de la
auto-mejora vs la contaminación del set de entrenamiento.

CONFOUND CONTROLADO (volumen): al subir eps se aceptan MÁS generaciones. Para aislar la CONTAMINACIÓN
(corrección degradada) del VOLUMEN, se SUBMUESTREA el set aceptado a un N FIJO por ronda y se entrena un
nº FIJO de pasos en TODOS los eps. Así la ÚNICA variable que cambia con eps es la FRACCIÓN de incorrectas
en el set de entrenamiento (la contaminación), no la cantidad de datos ni los pasos de gradiente.

HIPOTESIS H-LEARN-2: el net-sobre-base de verified_eps DECAE (monótono-ish) al subir eps; existe un
umbral eps* > 0 hasta el cual la auto-mejora SOBREVIVE (net > 0), y por encima colapsa al nivel de naive
(eps=1). APOYADA si: net(eps=0) claramente > net(eps=1) y la curva decae con consistencia de signo entre
seeds (robusta a algo de ruido pero rompe pasado eps*). REFUTADA si: la curva es PLANA en eps (el ruido no
importa -> el verificador no era el motor, contradiría H-LEARN-1) o si eps=0 no mejora sobre base.

Reusa exp016 (build_base, generate_pool, train_arm, acc_sigma) + addition_task (oráculo, split disjunto).

Uso:
  venv312\\Scripts\\python.exe -m cognia_x.experiments.exp017_noisy_verifier.run --smoke
  venv312\\Scripts\\python.exe -m cognia_x.experiments.exp017_noisy_verifier.run
"""
import argparse
import copy
import json
import os
import statistics
import sys
import time

import numpy as np
import torch

from cognia_x.experiments.exp016_verified_bootstrap import addition_task as T
from cognia_x.experiments.exp016_verified_bootstrap.run import build_base, generate_pool, train_arm, acc_sigma

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")
LO, HI = 0, 19
EPS_SWEEP = [0.0, 0.15, 0.30, 0.50, 1.0]


def noisy_accept(pool, eps, rng):
    """Verificador con ruido FALSO-POSITIVO eps: acepta (prompt, emit) si es correcta, o si es incorrecta
    con prob eps. Devuelve la lista de ejemplos (prompt, emit) aceptados."""
    out = []
    for (p, e, ok) in pool:
        if ok or (rng.random() < eps):
            out.append((p, e))
    return out


def run_seed(seed, args, test, train_pairs, log):
    base, nparams = build_base(seed, args.n_seed, args.base_steps, args.base_lr, args.warmup,
                               args.batch, train_pairs, log)
    base_acc, _, m = T.eval_accuracy(base, test, "cpu")
    log(f"[exp017] seed={seed} base acc held-out={base_acc:.3f} (banda [0.20,0.50]) params={nparams:,}")
    pool_rng = np.random.default_rng(seed + 7)
    sel = pool_rng.integers(0, len(train_pairs), size=args.pool)
    pool_prompts = [T.make_prompt(a, b) for a, b in (train_pairs[i] for i in sel)]

    arms = {eps: copy.deepcopy(base) for eps in EPS_SWEEP}
    hist = {eps: [round(base_acc, 4)] for eps in EPS_SWEEP}
    nkept = {eps: [] for eps in EPS_SWEEP}
    train_rng = np.random.default_rng(seed + 99)
    noise_rng = np.random.default_rng(seed + 1234)

    for r in range(1, args.rounds + 1):
        for eps in EPS_SWEEP:
            torch.manual_seed(10000 * seed + 100 * r + int(eps * 100))   # pareado por (seed,ronda,eps)
            pool = generate_pool(arms[eps], pool_prompts, args.K, 0.8, 20, "cpu")
            accepted = noisy_accept(pool, eps, noise_rng)
            # CONTROL DE VOLUMEN: submuestrear a N FIJO (si hay menos, usar todo; train_arm resamplea).
            if len(accepted) > args.fixed_n:
                idx = train_rng.integers(0, len(accepted), size=args.fixed_n)
                accepted = [accepted[i] for i in idx]
            nkept[eps].append(len(accepted))
            if accepted:
                train_arm(arms[eps], accepted, args.steps, args.batch, args.lr, "cpu", train_rng)
            a, _, _ = T.eval_accuracy(arms[eps], test, "cpu")
            hist[eps].append(round(a, 4))
        log(f"[exp017] seed={seed} ronda {r}: "
            + " ".join(f"e{eps}={hist[eps][-1]:.3f}" for eps in EPS_SWEEP))

    return {"seed": seed, "base_acc": round(base_acc, 4), "M": m, "hist": {str(e): hist[e] for e in EPS_SWEEP},
            "n_kept": {str(e): nkept[e] for e in EPS_SWEEP}}


def build_summary(per_seed, m):
    """Curva dosis-respuesta: net-sobre-base de verified_eps (media-sobre-rondas) vs eps, agregada sobre
    seeds. eps* = mayor eps con net > 0 consistente. Veredicto honesto."""
    def mean_rounds(s, eps):
        h = s["hist"][str(eps)][1:]
        return sum(h) / len(h)
    net = {}                       # eps -> [net por seed]
    for eps in EPS_SWEEP:
        net[eps] = [round(mean_rounds(s, eps) - s["base_acc"], 4) for s in per_seed]
    net_mean = {eps: round(sum(net[eps]) / len(net[eps]), 4) for eps in EPS_SWEEP}
    sign_consistent = {eps: all(x > 0 for x in net[eps]) for eps in EPS_SWEEP}
    sigma2 = round(2 * acc_sigma(0.5, m), 4)
    # eps* = mayor eps con net medio > 0 Y signo consistente (la auto-mejora sobrevive hasta ahí).
    survivors = [eps for eps in EPS_SWEEP if net_mean[eps] > 0 and sign_consistent[eps]]
    eps_star = max(survivors) if survivors else None
    decays = net_mean[0.0] > net_mean[1.0]                     # net cae de oráculo-perfecto a acepta-todo
    clean_improves = net_mean[0.0] > 0 and sign_consistent[0.0]
    monotone_ish = sum(1 for i in range(len(EPS_SWEEP) - 1) if net_mean[EPS_SWEEP[i]] >= net_mean[EPS_SWEEP[i + 1]] - 0.02) >= (len(EPS_SWEEP) - 2)

    if not clean_improves:
        status, verdict = "inconcluso", ("eps=0 no mejora sobre base ({:+.3f}) -> recalibrar; sin base de "
                                         "auto-mejora no hay dosis-respuesta.").format(net_mean[0.0])
    elif decays and (net_mean[0.0] - net_mean[1.0]) > sigma2:
        status = "apoyada"
        verdict = ("H-LEARN-2 APOYADA: la auto-mejora DECAE con el ruido del verificador (net eps=0={:+.3f} "
                   "-> eps=1={:+.3f}, caída {:.3f} > 2σ {:.3f}); sobrevive hasta eps*={} (net>0 consistente), "
                   "y colapsa hacia el régimen naive al subir el falso-positivo. El verificador (su CORRECCIÓN) "
                   "es el motor — degradarlo degrada la mejora; con volumen/pasos FIJOS la única variable es la "
                   "contaminación.").format(net_mean[0.0], net_mean[1.0], net_mean[0.0] - net_mean[1.0], sigma2, eps_star)
    elif not decays:
        status = "refutada"
        verdict = ("H-LEARN-2 REFUTADA: la curva NO decae con eps (net eps=0={:+.3f} ~ eps=1={:+.3f}) -> el "
                   "ruido del verificador no cambia el resultado a esta escala (tensión con H-LEARN-1).").format(
                       net_mean[0.0], net_mean[1.0])
    else:
        status = "mixta"
        verdict = ("H-LEARN-2 MIXTA: decae pero la caída no supera 2σ; señal débil de dosis-respuesta.")

    return {"eps_sweep": EPS_SWEEP, "net_by_eps_mean": net_mean, "net_by_eps_per_seed": {str(e): net[e] for e in EPS_SWEEP},
            "sign_consistent": {str(e): sign_consistent[e] for e in EPS_SWEEP}, "eps_star": eps_star,
            "sigma_2": sigma2, "decays": bool(decays), "clean_improves": bool(clean_improves),
            "monotone_ish": bool(monotone_ish), "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser(description="exp017 — robustez de la auto-mejora al ruido del verificador (H-LEARN-2)")
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=str, default="0,1,2")
    ap.add_argument("--rounds", type=int, default=4)
    ap.add_argument("--K", type=int, default=6)
    ap.add_argument("--pool", type=int, default=256)
    ap.add_argument("--steps", type=int, default=200)
    ap.add_argument("--fixed_n", type=int, default=400, help="N fijo del set de entrenamiento por ronda (control de volumen)")
    ap.add_argument("--n_seed", type=int, default=256)
    ap.add_argument("--base_steps", type=int, default=1500)
    ap.add_argument("--base_lr", type=float, default=1e-3)
    ap.add_argument("--lr", type=float, default=5e-4)
    ap.add_argument("--warmup", type=int, default=50)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--test_frac", type=float, default=0.30)
    args = ap.parse_args()
    if args.smoke:
        args.rounds, args.K, args.pool, args.steps, args.base_steps, args.fixed_n = 2, 4, 96, 60, 300, 120

    torch.set_num_threads(3)
    os.makedirs(RESULTS, exist_ok=True)
    logf = open(os.path.join(RESULTS, "run.log"), "a", encoding="utf-8")

    def log(s):
        print(s, flush=True); logf.write(s + "\n"); logf.flush()

    seeds = [int(x) for x in args.seeds.split(",") if x.strip() != ""]
    train_pairs, test_pairs = T.build_split(LO, HI, args.test_frac)
    test = T.test_from_pairs(test_pairs)
    log(f"[exp017] inicio smoke={args.smoke} seeds={seeds} eps={EPS_SWEEP} rounds={args.rounds} K={args.K} "
        f"pool={args.pool} steps={args.steps} fixed_n={args.fixed_n} rango=[{LO},{HI}] test_heldout={len(test)}")

    t0 = time.time()
    per_seed = []
    for seed in seeds:
        per_seed.append(run_seed(seed, args, test, train_pairs, log))
        _dump(per_seed, args, len(test), summary=None)
    summary = build_summary(per_seed, len(test))
    _dump(per_seed, args, len(test), summary=summary)

    log("[exp017] ===== RESUMEN H-LEARN-2 (dosis-respuesta al ruido del verificador) =====")
    for eps in EPS_SWEEP:
        log(f"  eps={eps}: net-sobre-base(mean)={summary['net_by_eps_mean'][eps]:+.3f} "
            f"por_seed={summary['net_by_eps_per_seed'][str(eps)]} signo_consistente={summary['sign_consistent'][str(eps)]}")
    log(f"  eps*={summary['eps_star']} 2σ={summary['sigma_2']:.3f} decae={summary['decays']}")
    log(f"  VEREDICTO: {summary['verdict']}")
    log(f"  tiempo total {(time.time()-t0)/60:.1f} min")
    logf.close()


def _dump(per_seed, args, M, summary=None):
    out = {"experiment": "exp017_noisy_verifier",
           "hypothesis": ("H-LEARN-2: la auto-mejora verificada DECAE al subir el ruido (falso-positivo) del "
                          "verificador; sobrevive hasta un eps* y colapsa hacia naive. Volumen/pasos FIJOS -> "
                          "la única variable es la contaminación."),
           "smoke": args.smoke, "eps_sweep": EPS_SWEEP, "M": M,
           "config": {"rounds": args.rounds, "K": args.K, "pool": args.pool, "steps": args.steps,
                      "fixed_n": args.fixed_n, "n_seed": args.n_seed, "base_steps": args.base_steps,
                      "task_range": [LO, HI]},
           "per_seed": per_seed}
    if summary is not None:
        out["summary"] = summary
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)


if __name__ == "__main__":
    main()
