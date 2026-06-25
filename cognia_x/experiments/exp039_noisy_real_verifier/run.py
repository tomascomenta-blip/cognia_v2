r"""
exp039 — CYCLE 53 / H-V4-2f: ¿la tolerancia al RUIDO del verificador (ε*≈0.15, exp017/oráculo) TRANSFIERE a un
VERIFICADOR REAL-CHEQUEABLE, y la GUARDIA (replay limpio) SUBE ese umbral?

CONTEXTO: exp017 (H-LEARN-2, CYCLE 30) halló que la auto-mejora verificada DECAE con el ruido falso-positivo
del verificador y sobrevive hasta ε*≈0.15 — pero con el ORÁCULO aritmético EXACTO. CYCLE 51-52 mostraron que el
lazo iterado + guardia funciona con un VERIFICADOR REAL (sandbox) y bootstrapea desde base débil. Hilo abierto
más citado por exp037 Y exp038: el verificador real PARCIAL/RUIDOSO. Este ciclo: corre el MISMO dosis-respuesta
de exp017 (barrido de ε falso-positivo, volumen FIJO) pero con el VERIFICADOR REAL FUERTE, PLANO vs GUARDED.

MODELO DE RUIDO (idéntico a exp017): un verificador con ruido ε acepta una generación si es STRONG-correcta
(sandbox: valor==target Y usa operador), o si es incorrecta con prob ε. ε=0 = verificador perfecto. Volumen
FIJO (submuestreo a fixed_n) + pasos FIJOS -> la ÚNICA variable que cambia con ε es la CONTAMINACIÓN del set.

ANALOGÍA: tu corrector de programas ahora se EQUIVOCA: a veces da por bueno un programa que NO computa lo
pedido (falso positivo, tasa ε). ¿Hasta qué tasa de error del corrector seguís mejorando? ¿Y tener un cuaderno
de soluciones correctas a mano (replay de la verdad) te hace aguantar MÁS error del corrector?

DISEÑO (modelo propio; funde exp017 + exp037). base_steps=200 -> base real_acc~0.44 (banda, con margen). Por
seed y por ε en {0.0,0.15,0.30,0.50}: dos lazos de R rondas, PLANO (entrena con el set aceptado-ruidoso,
volumen fijo) vs GUARDED (set aceptado-ruidoso DEDUP + replay de la verdad). Métrica: real_acc CLEAN (verificador
FUERTE sin ruido en test held-out) -> net-sobre-base media-sobre-rondas. 3 seeds. ε* por brazo = mayor ε con
net>0 consistente entre seeds.

PREDICCIÓN FALSABLE (pre-registrada):
  - APOYADA si el net del GUARDED DECAE con ε (mejora limpia en ε=0 Y caída ε=0 -> ε=0.50 > 2σ) y sobrevive
    hasta un ε* > 0 -> la dosis-respuesta TRANSFIERE del oráculo al verificador REAL. (Bonus: ε*_guarded >=
    ε*_plain -> la guardia sube/mantiene el umbral de ruido.)
  - REFUTADA si la curva es PLANA en ε (el ruido no importa -> el verificador no era el motor, tensión con
    H-LEARN-1/2) o si ε=0 no mejora sobre base.
  - MIXTA si decae pero la caída no supera 2σ (señal débil).

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp039_noisy_real_verifier.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp039_noisy_real_verifier.run            # FULL
"""
import argparse
import copy
import json
import math
import os
import platform
import sys
import time

import numpy as np
import torch

from cognia_x.experiments.exp018_real_verifier import expression_task as E
from cognia_x.experiments.exp018_real_verifier.run import build_base, generate_pool, train_arm
from cognia_x.experiments.exp037_iterated_real_verifier.run import seed_correct, LO, HI

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")
EPS_SWEEP = [0.0, 0.15, 0.30, 0.50]
ARMS = ["plain", "guarded"]


def noisy_accept_real(pool, eps, rng):
    """Verificador REAL con ruido FALSO-POSITIVO ε: acepta (prompt, emit) si es STRONG-correcta (sandbox), o si
    NO lo es con prob ε. pool = [(p, e, weak_ok, strong_ok)]."""
    return [(p, e) for (p, e, w, s) in pool if s or (rng.random() < eps)]


def run_loop(base, pool_prompts, test_targets, args, guarded, eps, replay_pairs, gen_seed):
    model = copy.deepcopy(base)
    train_rng = np.random.default_rng(gen_seed)
    noise_rng = np.random.default_rng(gen_seed + 1234)
    hist = [round(E.eval_metrics(model, test_targets, "cpu")["real_acc"], 4)]
    for r in range(1, args.rounds + 1):
        torch.manual_seed(gen_seed + 100 * r + int(eps * 100))
        pool = generate_pool(model, pool_prompts, args.K, args.temperature, args.top_k, "cpu")
        accepted = noisy_accept_real(pool, eps, noise_rng)
        # CONTROL DE VOLUMEN (como exp017): submuestrear el aceptado a N FIJO antes de dedup/replay; así
        # entre ε la única variable es la CONTAMINACIÓN, no el volumen ni los pasos.
        if len(accepted) > args.fixed_n:
            idx = train_rng.integers(0, len(accepted), size=args.fixed_n)
            accepted = [accepted[i] for i in idx]
        if guarded:
            uniq = list(dict.fromkeys((bytes(p), bytes(e)) for (p, e) in accepted))
            train_set = [(bytes(p), bytes(e)) for (p, e) in uniq] + replay_pairs
        else:
            train_set = accepted
        if train_set:
            train_arm(model, train_set, args.steps, args.batch, args.lr, "cpu",
                      np.random.default_rng(98000 + r))
        hist.append(round(E.eval_metrics(model, test_targets, "cpu")["real_acc"], 4))
    return hist


def run_seed(seed, args, train_targets, test_targets, log):
    t0 = time.time()
    base, npar = build_base(seed, args.n_seed, args.base_steps, args.base_lr, args.warmup, args.batch,
                            train_targets)
    base_acc = round(E.eval_metrics(base, test_targets, "cpu")["real_acc"], 4)
    log(f"[exp039] seed={seed} base real_acc={base_acc:.3f} params={npar:,}")
    pool_rng = np.random.default_rng(seed + 7)
    sel = pool_rng.integers(0, len(train_targets), size=args.pool)
    pool_prompts = [E.make_prompt(train_targets[i]) for i in sel]
    replay = seed_correct(train_targets, args.replay_n, np.random.default_rng(99000 + seed))

    hist = {a: {} for a in ARMS}
    for eps in EPS_SWEEP:
        for a in ARMS:
            hist[a][str(eps)] = run_loop(base, pool_prompts, test_targets, args, a == "guarded", eps,
                                         replay, 95000 + seed * 17)
        log(f"[exp039] seed={seed} eps={eps}: plain={hist['plain'][str(eps)][-1]:.3f} "
            f"guarded={hist['guarded'][str(eps)][-1]:.3f}")
    dt = time.time() - t0
    log(f"[exp039] seed={seed} {dt:.1f}s")
    return {"seed": seed, "base_acc": base_acc, "npar": npar, "secs": round(dt, 2), "hist": hist}


def eps_star(net_mean, sign_consistent):
    survivors = [e for e in EPS_SWEEP if net_mean[e] > 0 and sign_consistent[e]]
    return max(survivors) if survivors else None


def build_summary(per_seed, m):
    margin = round(2 * math.sqrt(0.25 / max(1, m)), 4)

    def mean_rounds(s, arm, eps):
        h = s["hist"][arm][str(eps)][1:]
        return sum(h) / len(h)

    out = {"eps_sweep": EPS_SWEEP, "arms": ARMS, "sigma_2": margin, "n_seeds": len(per_seed),
           "net_mean": {}, "net_per_seed": {}, "sign_consistent": {}, "eps_star": {}}
    for a in ARMS:
        net = {e: [round(mean_rounds(s, a, e) - s["base_acc"], 4) for s in per_seed] for e in EPS_SWEEP}
        net_mean = {e: round(sum(net[e]) / len(net[e]), 4) for e in EPS_SWEEP}
        sign = {e: all(x > 0 for x in net[e]) for e in EPS_SWEEP}
        out["net_mean"][a] = net_mean
        out["net_per_seed"][a] = {str(e): net[e] for e in EPS_SWEEP}
        out["sign_consistent"][a] = {str(e): sign[e] for e in EPS_SWEEP}
        out["eps_star"][a] = eps_star(net_mean, sign)

    ng = out["net_mean"]["guarded"]
    clean_improves = ng[0.0] > 0 and out["sign_consistent"]["guarded"]["0.0"]
    decays = ng[0.0] > ng[0.50]
    big_drop = (ng[0.0] - ng[0.50]) > margin
    esg, esp = out["eps_star"]["guarded"], out["eps_star"]["plain"]
    guard_raises = (esg is not None) and (esp is None or esg >= esp)
    out["clean_improves"] = bool(clean_improves)
    out["decays"] = bool(decays)
    out["guard_raises_eps_star"] = bool(guard_raises)

    if not clean_improves:
        status = "inconcluso"
        verdict = ("ε=0 no mejora sobre base ({:+.3f}) -> recalibrar base; sin auto-mejora limpia no hay "
                   "dosis-respuesta.").format(ng[0.0])
    elif decays and big_drop:
        status = "apoyada"
        verdict = ("H-V4-2f APOYADA: la tolerancia al ruido del verificador TRANSFIERE del oráculo (exp017, "
                   "ε*≈0.15) al VERIFICADOR REAL. net guarded DECAE con ε ({:+.3f}@0 -> {:+.3f}@0.50, caída "
                   "{:.3f} > 2σ {:.3f}); sobrevive hasta ε*={} (guarded) vs ε*={} (plano). guard_raises_eps*={} "
                   "-> la guardia (replay limpio) {} el umbral de ruido. El verificador (su CORRECCIÓN) sigue "
                   "siendo el motor con un verificador REAL.").format(
                       ng[0.0], ng[0.50], ng[0.0] - ng[0.50], margin, esg, esp, guard_raises,
                       "sube/mantiene" if guard_raises else "no sube")
    elif not decays:
        status = "refutada"
        verdict = ("H-V4-2f REFUTADA: net guarded NO decae con ε ({:+.3f}@0 ~ {:+.3f}@0.50) -> el ruido del "
                   "verificador real no cambia el resultado (tensión con H-LEARN-1/2).").format(ng[0.0], ng[0.50])
    else:
        status = "mixta"
        verdict = ("H-V4-2f MIXTA: decae pero la caída ({:.3f}) no supera 2σ ({:.3f}); dosis-respuesta débil.").format(
            ng[0.0] - ng[0.50], margin)
    out["status"] = status
    out["verdict"] = verdict
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=str, default="0,1,2")
    ap.add_argument("--rounds", type=int, default=4)
    ap.add_argument("--K", type=int, default=6)
    ap.add_argument("--pool", type=int, default=256)
    ap.add_argument("--replay_n", type=int, default=128)
    ap.add_argument("--fixed_n", type=int, default=400, help="N fijo del set aceptado por ronda (control de volumen)")
    ap.add_argument("--steps", type=int, default=200)
    ap.add_argument("--lr", type=float, default=5e-4)
    ap.add_argument("--top_k", type=int, default=20)
    ap.add_argument("--temperature", type=float, default=0.9)
    ap.add_argument("--n_seed", type=int, default=256)
    ap.add_argument("--base_steps", type=int, default=200)   # base real_acc~0.44 (banda, con margen)
    ap.add_argument("--base_lr", type=float, default=1e-3)
    ap.add_argument("--warmup", type=int, default=50)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--test_frac", type=float, default=0.30)
    args = ap.parse_args()

    if args.smoke:
        args.seeds, args.rounds, args.pool, args.steps = "0,1", 2, 128, 80

    torch.set_num_threads(3)
    seeds = [int(s) for s in args.seeds.split(",") if s.strip() != ""]
    os.makedirs(RESULTS, exist_ok=True)
    logf = open(os.path.join(RESULTS, "run.log"), "a", encoding="utf-8")
    logs = []

    def log(m):
        print(m, flush=True)
        logs.append(m)
        logf.write(m + "\n"); logf.flush()

    train_targets, test_targets = E.build_split(LO, HI, args.test_frac)
    log(f"[exp039] CYCLE 53 / H-V4-2f — dosis-respuesta al RUIDO del VERIFICADOR REAL (plano vs guardia)")
    log(f"[exp039] exprs [{LO},{HI}] test={len(test_targets)} eps={EPS_SWEEP} rounds={args.rounds} "
        f"fixed_n={args.fixed_n} base_steps={args.base_steps} seeds={seeds}")

    res = [run_seed(s, args, train_targets, test_targets, log) for s in seeds]
    summary = build_summary(res, len(test_targets))
    log(f"[exp039] VEREDICTO: {summary['verdict']}")
    for a in ARMS:
        log(f"[exp039] {a:>7} net-sobre-base por ε: "
            + " ".join(f"e{e}={summary['net_mean'][a][e]:+.3f}" for e in EPS_SWEEP)
            + f"  ε*={summary['eps_star'][a]}")

    out = {"exp": "exp039_noisy_real_verifier", "cycle": 53, "hypothesis": "H-V4-2f",
           "claim": "la tolerancia al ruido del verificador (ε*≈0.15, exp017/oráculo) transfiere a un verificador "
                    "REAL-CHEQUEABLE; la guardia (replay limpio) sube/mantiene el umbral de ruido",
           "verdict": summary["status"], "summary": summary, "args": vars(args), "seeds": res,
           "task_range": [LO, HI],
           "platform": {"python": platform.python_version(), "numpy": np.__version__, "torch": torch.__version__},
           "log": logs}
    path = os.path.join(RESULTS, "results.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp039] escrito {path}")
    logf.close()


if __name__ == "__main__":
    main()
