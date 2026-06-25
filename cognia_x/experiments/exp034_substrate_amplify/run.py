r"""
exp034 — CYCLE 48 / H-V4-2 (salto al SUSTRATO): auto-mejora VERIFICADA + AMPLIFICACIÓN multi-paso. El cierre
del arco v4: el lazo act-and-verify no sólo asigna cómputo (40-47) — genera DATOS verificados que MEJORAN el
sustrato barato, y por p^K esa mejora se AMPLIFICA en cadenas largas.

CONTEXTO: el sub-arco 44-47 concluyó que el cuello de botella del razonamiento multi-paso es la PRECISIÓN POR
PASO, no la orquestación. exp016 (CYCLE 29) ya mostró que entrenar con las auto-salidas VERIFICADO-correctas
(STaR) mejora la precisión de la suma. Pregunta nueva: ¿esa mejora de precisión POR PASO se AMPLIFICA en
multi-paso (Δcadena a K grande >> Δpaso), y es la SEÑAL DE CORRECCIÓN (no el volumen) la que la produce?

ANALOGÍA: si mejorás un poco tu precisión en CADA cuenta simple (de 50% a 65%), tu chance de clavar una
cuenta de 6 pasos de un tirón salta MUCHO más que ese poco (0.5^6=1.6% -> 0.65^6=7.5%, ~4.7×). Arreglar el
ladrillo barato (el paso) rinde de forma compuesta en lo largo. Y el lazo verificar->reentrenar te da ese
ladrillo mejor gratis, de tus propias salidas correctas.

DISEÑO (modelo propio del lab; reusa exp016 STaR + exp030 cadenas). (1) Base débil. (2) Genera K completaciones
por prompt de TRAIN; arma 2 sets del MISMO tamaño: VERIFICADO (sólo las correctas por oráculo) y CONTROL
(subconjunto ALEATORIO de TODAS, incl. incorrectas) -> aísla la señal de CORRECCIÓN del volumen. (3) Fine-tune
2 copias del base (verified / control), mismos N_steps. (4) Mide PRECISIÓN POR PASO (suma held-out) y
ACCURACY DE CADENA greedy (sin orquestación, para aislar el SUSTRATO) a K=1,2,4,6, para base/verified/control.

PREDICCIÓN FALSABLE (pre-registrada):
  - APOYADA si (a) VERIFIED sube la precisión por paso sobre BASE y sobre CONTROL (la corrección, no el
    volumen), Y (b) la mejora se AMPLIFICA: el ratio de mejora en cadena (verified/base) a Kmax es claramente
    MAYOR que a K=1 (la mejora del sustrato rinde compuesto en lo largo). => mejorar el sustrato barato es el
    lever dominante del multi-paso, y el lazo verify->reentrenar lo entrega. (Ks cortos 1,2,3: a K>=4 la
    accuracy de cadena greedy con este base es ~0 = piso de medición; declarado.)
  - REFUTADA si VERIFIED no supera al BASE en precisión por paso, o no supera al CONTROL (era volumen), o la
    cadena NO se amplifica (ratio a Kmax <= ratio a K=1).
  - MIXTA si mejora el paso pero la amplificación es marginal, o verified ~ control.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp034_substrate_amplify.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp034_substrate_amplify.run            # FULL
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

from cognia_x.experiments.exp016_verified_bootstrap import addition_task as T
from cognia_x.experiments.exp016_verified_bootstrap.run import build_base, generate_pool, train_arm
from cognia_x.experiments.exp030_multistep_reasoning.run import MOD, parse_value, make_chain

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")


@torch.no_grad()
def chain_acc_greedy(model, chains, device):
    """Accuracy de cadena con decode GREEDY (top_k=1, 1 muestra/paso) -> aísla la calidad del SUSTRATO (sin
    orquestación/TTS). Correcto = traza completa == referencia."""
    model.eval()
    hits = 0
    for r0, a, ref in chains:
        r, trace = r0, []
        for ai in a:
            prompt = T.make_prompt(r, ai)
            idx = torch.tensor([list(bytes(prompt))], dtype=torch.long, device=device)
            gen = model.generate(idx, n_new=T.N_NEW, temperature=1.0, top_k=1)   # argmax determinista
            val = parse_value(bytes(gen[0].tolist()[len(prompt):]))
            r = (val % MOD) if val is not None else -1
            trace.append(r)
        hits += int(trace == ref)
    model.train()
    return hits / max(1, len(chains))


def build_starsets(base, train_pairs, n_prompts, K, temperature, top_k, rng, device):
    """Genera K completaciones por prompt y arma (verified, control) del MISMO tamaño. verified = correctas por
    oráculo; control = subconjunto ALEATORIO de TODAS (incl. incorrectas). Devuelve (verified, control)."""
    sel = rng.integers(0, len(train_pairs), size=n_prompts)
    prompts = [T.make_prompt(*train_pairs[i]) for i in sel]
    pool = generate_pool(base, prompts, K, temperature, top_k, device)  # [(prompt, emitted, is_correct)]
    verified = [(p, e) for (p, e, c) in pool if c]
    n = len(verified)
    allpairs = [(p, e) for (p, e, c) in pool]
    idx = rng.permutation(len(allpairs))[:n]
    control = [allpairs[i] for i in idx]
    return verified, control


def run_seed(seed, args, train_pairs, test, Ks, log):
    t0 = time.time()
    base, npar = build_base(seed, args.n_seed, args.base_steps, args.base_lr, args.warmup,
                            args.batch, train_pairs, log)
    rng = np.random.default_rng(90000 + seed)
    verified, control = build_starsets(base, train_pairs, args.n_prompts, args.K, args.temperature,
                                       args.top_k, rng, "cpu")

    torch.manual_seed(1000 + seed)
    m_ver = copy.deepcopy(base)
    train_arm(m_ver, verified, args.star_steps, args.batch, args.star_lr, "cpu",
              np.random.default_rng(91000 + seed))
    torch.manual_seed(1000 + seed)
    m_ctl = copy.deepcopy(base)
    train_arm(m_ctl, control, args.star_steps, args.batch, args.star_lr, "cpu",
              np.random.default_rng(91000 + seed))

    # precisión POR PASO (suma held-out)
    step_base = T.eval_accuracy(base, test, "cpu")[0]
    step_ver = T.eval_accuracy(m_ver, test, "cpu")[0]
    step_ctl = T.eval_accuracy(m_ctl, test, "cpu")[0]

    by_K = {}
    for K in Ks:
        crng = np.random.default_rng(60000 + seed * 31 + K)   # MISMAS cadenas que el resto del arco
        chains = [make_chain(crng, K) for _ in range(args.M)]
        cb = chain_acc_greedy(base, chains, "cpu")
        cv = chain_acc_greedy(m_ver, chains, "cpu")
        cc = chain_acc_greedy(m_ctl, chains, "cpu")
        by_K[K] = {"base": cb, "verified": cv, "control": cc}
        log(f"[exp034]   seed={seed} K={K}: BASE={cb:.3f} VERIFIED={cv:.3f} CONTROL={cc:.3f}")
    dt = time.time() - t0
    log(f"[exp034] seed={seed} step_acc base={step_base:.3f} verified={step_ver:.3f} control={step_ctl:.3f} "
        f"| n_verified={len(verified)} {dt:.1f}s npar={npar}")
    return {"seed": seed, "npar": npar, "secs": round(dt, 2), "n_verified": len(verified),
            "step": {"base": step_base, "verified": step_ver, "control": step_ctl}, "by_K": by_K}


def _ratio(a, b):
    return a / b if b > 1e-9 else float('inf')


def verdict(seeds_res, Ks, margin):
    use = seeds_res
    step = {m: float(np.mean([r["step"][m] for r in use])) for m in ("base", "verified", "control")}
    curve = {}
    for K in Ks:
        curve[K] = {m: float(np.mean([r["by_K"][K][m] for r in use])) for m in ("base", "verified", "control")}
    Kmax = Ks[-1]
    # (a) verified mejora el paso sobre base y control
    beats_base_step = (step["verified"] - step["base"]) >= margin
    beats_ctl_step = (step["verified"] - step["control"]) >= margin
    # (b) amplificación: ratio verified/base en cadena a Kmax > a K=1 (o el menor K)
    r_lo = _ratio(curve[Ks[0]]["verified"], curve[Ks[0]]["base"])
    r_hi = _ratio(curve[Kmax]["verified"], curve[Kmax]["base"])
    amplifies = r_hi > r_lo + 1e-6
    if beats_base_step and beats_ctl_step and amplifies:
        v = "APOYADA"
    elif (step["verified"] <= step["base"]) or (step["verified"] <= step["control"]) or (not amplifies):
        v = "REFUTADA"
    else:
        v = "MIXTA"
    return v, {"Kmax": Kmax, "step": step, "curve": curve, "beats_base_step": beats_base_step,
               "beats_ctl_step": beats_ctl_step, "amplifies": amplifies, "ratio_lo": r_lo, "ratio_hi": r_hi,
               "n_seeds": len(use)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=str, default="0,1,2,3")
    ap.add_argument("--M", type=int, default=150, help="cadenas por K (eval)")
    ap.add_argument("--Ks", type=str, default="1,2,3")
    ap.add_argument("--n_prompts", type=int, default=384, help="prompts de train para generar STaR")
    ap.add_argument("--K", type=int, default=6, help="completaciones por prompt en la generación STaR")
    ap.add_argument("--star_steps", type=int, default=250, help="pasos de fine-tune por brazo")
    ap.add_argument("--star_lr", type=float, default=5e-4)
    ap.add_argument("--top_k", type=int, default=16)
    ap.add_argument("--temperature", type=float, default=1.0)
    ap.add_argument("--margin", type=float, default=0.03)
    ap.add_argument("--n_seed", type=int, default=256)
    ap.add_argument("--base_steps", type=int, default=600)
    ap.add_argument("--base_lr", type=float, default=1e-3)
    ap.add_argument("--warmup", type=int, default=50)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--lo", type=int, default=0)
    ap.add_argument("--hi", type=int, default=19)
    ap.add_argument("--test_frac", type=float, default=0.30)
    args = ap.parse_args()

    if args.smoke:
        args.seeds, args.M, args.Ks, args.base_steps, args.star_steps, args.n_prompts = "0,1", 60, "1,4", 300, 100, 128

    seeds = [int(s) for s in args.seeds.split(",") if s.strip() != ""]
    Ks = [int(x) for x in args.Ks.split(",") if x.strip() != ""]
    logs = []

    def log(m):
        print(m, flush=True)
        logs.append(m)

    train_pairs, test_pairs = T.build_split(args.lo, args.hi, args.test_frac)
    test = T.test_from_pairs(test_pairs)

    log(f"[exp034] CYCLE 48 / H-V4-2 — sustrato: auto-mejora VERIFICADA + amplificación multi-paso (modelo propio)")
    log(f"[exp034] suma [{args.lo},{args.hi}] test={len(test)} M={args.M} Ks={Ks} n_prompts={args.n_prompts} "
        f"K_gen={args.K} star_steps={args.star_steps} seeds={seeds}")

    res = [run_seed(s, args, train_pairs, test, Ks, log) for s in seeds]
    v, stats = verdict(res, Ks, args.margin)
    s = stats["step"]
    log(f"[exp034] VEREDICTO H-V4-2: {v} | PASO base={s['base']:.3f} verified={s['verified']:.3f} "
        f"control={s['control']:.3f} (Δvs_base={s['verified'] - s['base']:+.3f} Δvs_ctl={s['verified'] - s['control']:+.3f}) "
        f"| AMPLIF ratio_cadena K{Ks[0]}={stats['ratio_lo']:.2f}× -> K{stats['Kmax']}={stats['ratio_hi']:.2f}× ({stats['amplifies']})")
    log(f"[exp034] CURVA K->BASE/VERIFIED/CONTROL: " +
        " | ".join("K{}:{:.3f}/{:.3f}/{:.3f}".format(
            K, stats['curve'][K]['base'], stats['curve'][K]['verified'], stats['curve'][K]['control']) for K in Ks))

    out = {"exp": "exp034_substrate_amplify", "cycle": 48, "hypothesis": "H-V4-2",
           "claim": "la auto-mejora VERIFICADA (STaR) sube la precisión por paso por la señal de corrección "
                    "(no el volumen) y esa mejora se AMPLIFICA en cadenas largas (p^K) -> el sustrato es el lever dominante",
           "verdict": v, "stats": stats, "args": vars(args), "Ks": Ks, "seeds": res,
           "platform": {"python": platform.python_version(), "numpy": np.__version__, "torch": torch.__version__},
           "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    path = os.path.join(RESULTS, "results.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp034] escrito {path}")


if __name__ == "__main__":
    main()
