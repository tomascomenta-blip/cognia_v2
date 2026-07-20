r"""
exp028 — CYCLE 42 / H-V4-1g: una señal de CONTROL robusta-al-ruido. ¿Estimar la consecuencia por
AUTO-CONSISTENCIA de los rollouts (SIN usar el veredicto del verificador) recupera la ventaja de exp026 Y
resiste el ruido del verificador que hundió a la señal verifier-dependiente (exp027)?

CONTEXTO: exp027 (CYCLE 41) encontró que la señal de consecuencia de exp026 usa `solved_observed` (depende
del verificador) → hereda su ruido → la ventaja se invierte a vnoise=0.20. La pasiva-entropía es robusta al
ruido pero peor sin ruido. PREGUNTA: ¿existe una señal de control que sea robusta (verifier-free) Y buena?

IDEA RAÍZ (analogía cotidiana): sin un corrector confiable, ¿cómo sabés en qué problema insistir? Mirás tus
PROPIOS intentos: si todos coinciden, ya lo tenés claro (no insistas); si son un caos total de respuestas
distintas, no lo controlás (no insistas); pero si EMERGE un acuerdo PARCIAL (varios coinciden, otros no),
estás "en el filo" — insistir CONCENTRA la respuesta. Eso es controlabilidad medida por AUTO-CONSISTENCIA,
sin preguntarle a nadie si está bien (self-consistency, Wang 2022).

DISEÑO (extiende exp027; mismo HybridLM + verificador ruidoso para el COMMIT). 4 políticas de ASIGNACIÓN del
mismo presupuesto B=M·avg (avg=5, n_probe=3 para granularidad de p_top):
  - AZAR (uniforme)
  - PASIVA (∝ entropía del probe = incertidumbre; verifier-free pero peor)
  - CONSEC_V (∝ control verifier-dependiente de exp026: 0 si solved_observed, ∝ diversidad si no) — el frágil
  - CONSEC_FREE (∝ p_top·(1−p_top), sweet-spot de auto-consistencia; p_top = fracción de la respuesta
    plural en el probe) — VERIFIER-FREE: 0 si todos coinciden (confiado) y 0 si todos distintos (caos), máximo
    en acuerdo PARCIAL. La señal candidata robusta.
COMMIT = primer sample aceptado por el verificador ruidoso (igual para las 4 → aísla la ASIGNACIÓN). ACCURACY
REAL = el commit es verdaderamente correcto. Barrido de vnoise, 4 seeds. La asignación de CONSEC_FREE NO
toca el verificador → su calidad NO debe degradarse con el ruido (sí el commit, igual para todas).

PREDICCIÓN FALSABLE (pre-registrada):
  - APOYADA si CONSEC_FREE (a) a vnoise=0 iguala o supera a PASIVA y a AZAR (recupera la ventaja de control)
    Y (b) a ruido alto (vnoise=0.20) supera a CONSEC_V por >=0.02 (su asignación es más robusta al ruido).
  - REFUTADA si CONSEC_FREE <= PASIVA a vnoise=0 (no aporta sobre la incertidumbre) O CONSEC_FREE <= CONSEC_V
    a vnoise=0.20 (no es más robusta: la auto-consistencia no ayuda).
  - MIXTA si cumple una condición pero no la otra.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp028_robust_control_signal.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp028_robust_control_signal.run            # FULL
"""
import argparse
import json
import math
import os
import platform
import sys
import time
from collections import Counter

import numpy as np
import torch

from cognia_x.experiments.exp016_verified_bootstrap import addition_task as T
from cognia_x.experiments.exp016_verified_bootstrap.run import build_base
from cognia_x.experiments.exp026_ttc_allocation.run import sample_counts, largest_remainder, answer_entropy, acc_sigma
from cognia_x.experiments.exp027_noisy_verifier_ttc.run import noisy_accept, commit_true_correct

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")

POLICIES = ["uniform", "passive", "consequence_v", "consequence_free"]
MODE_OFFSET = {"uniform": 1, "passive": 2, "consequence_v": 3, "consequence_free": 4}  # determinista (NO hash())


def p_top(samples):
    """Fracción de la respuesta PLURAL en el probe (auto-consistencia). 1.0 = todos coinciden."""
    if not samples:
        return 0.0
    c = Counter(a for a, _ in samples)
    return max(c.values()) / sum(c.values())


def signal_weight(mode, samples, solved_obs):
    """Peso de asignación por política, calculado SOLO del probe."""
    if mode == "passive":
        return answer_entropy(samples) + 1e-3
    if mode == "consequence_v":                       # verifier-dependiente (exp026): hereda el ruido
        n_distinct = len(set(a for a, _ in samples))
        return 0.0 if solved_obs else (n_distinct - 1) + 1e-3
    if mode == "consequence_free":                    # auto-consistencia: CONSENSO EMERGENTE (verifier-free)
        # value alto cuando hay una respuesta plural EMERGIENDO (probable correcta, self-consistency) pero
        # aún no unánime -> samplear más la CONCENTRA y la lleva a commit. 0 si ya unánime (controlabilidad
        # nula: determinista, resuelto o atascado) -> NO simétrica (distingue caos 1/3 de consenso 2/3).
        pt = p_top(samples)
        return (0.0 if pt >= 1.0 - 1e-9 else pt) + 1e-3
    raise ValueError(mode)


def eval_policy(model, test, B, n_probe, vnoise, nrng, temperature, top_k, device, mode):
    """Asigna por `mode`; COMMIT por verificador ruidoso (igual para todas). Accuracy REAL del commit.
    AZAR no usa probe (reparte uniforme y commitea); las otras: probe (cuenta al presupuesto) + extra."""
    M = len(test)
    if mode == "uniform":
        counts = largest_remainder([1.0] * M, B)
        hits = 0
        for (p, _, _), k in zip(test, counts):
            s = sample_counts(model, p, k, temperature, top_k, device)
            tc, _ = commit_true_correct(s, vnoise, nrng)
            hits += int(tc)
        return hits / max(1, M)

    probe, weights = [], []
    for (p, _, _) in test:
        s = sample_counts(model, p, n_probe, temperature, top_k, device)
        solved_obs = any(noisy_accept(tc, vnoise, nrng) for _, tc in s)
        probe.append((p, s))
        weights.append(signal_weight(mode, s, solved_obs))
    extra = max(0, B - M * n_probe)
    alloc = largest_remainder(weights, extra)
    hits = 0
    for (p, ps), k in zip(probe, alloc):
        full = list(ps)
        if k > 0:
            full += sample_counts(model, p, k, temperature, top_k, device)
        tc, _ = commit_true_correct(full, vnoise, nrng)
        hits += int(tc)
    return hits / max(1, M)


def run_seed(seed, args, test, train_pairs, noises, log):
    t0 = time.time()
    base, npar = build_base(seed, args.n_seed, args.base_steps, args.base_lr, args.warmup,
                            args.batch, train_pairs, log)
    greedy_acc, _, _ = T.eval_accuracy(base, test, "cpu")
    M = len(test)
    B = M * args.avg
    band = "EN-banda" if 0.20 <= greedy_acc <= 0.50 else "FUERA-banda"
    by_noise = {}
    for vn in noises:
        row = {"greedy": greedy_acc}
        for mode in POLICIES:
            nrng = np.random.default_rng(8000 + seed * 17 + int(round(vn * 1000)) * 10 + MODE_OFFSET[mode])
            row[mode] = eval_policy(base, test, B, args.n_probe, vn, nrng,
                                    args.temperature, args.top_k, "cpu", mode)
        by_noise[vn] = row
        log(f"[exp028]   seed={seed} vnoise={vn}: AZAR={row['uniform']:.3f} PASIVA={row['passive']:.3f} "
            f"CONSEC_V={row['consequence_v']:.3f} CONSEC_FREE={row['consequence_free']:.3f} (greedy={greedy_acc:.3f})")
    dt = time.time() - t0
    log(f"[exp028] seed={seed} greedy={greedy_acc:.3f} ({band}) {dt:.1f}s npar={npar}")
    return {"seed": seed, "greedy_acc": greedy_acc, "in_band": 0.20 <= greedy_acc <= 0.50,
            "M": M, "B": B, "npar": npar, "secs": round(dt, 2), "by_noise": by_noise}


def verdict(seeds_res, noises, margin):
    inb = [r for r in seeds_res if r["in_band"]]
    use = inb if inb else seeds_res
    M = use[0]["M"]
    lo, hi = noises[0], noises[-1]
    curve = {}
    for vn in noises:
        row = {m: float(np.mean([r["by_noise"][vn][m] for r in use])) for m in POLICIES}
        row["greedy"] = float(np.mean([r["by_noise"][vn]["greedy"] for r in use]))
        curve[vn] = row
    sig = acc_sigma(curve[lo]["consequence_free"], M) / math.sqrt(len(use))
    # (a) a ruido bajo recupera la ventaja: CONSEC_FREE >= PASIVA y >= AZAR
    recovers = (curve[lo]["consequence_free"] >= curve[lo]["passive"] - 1e-9) and \
               (curve[lo]["consequence_free"] >= curve[lo]["uniform"] - 1e-9)
    # (b) a ruido alto es más robusta que la verifier-dependiente
    robust = (curve[hi]["consequence_free"] - curve[hi]["consequence_v"]) >= margin_robust(margin)
    if recovers and robust:
        v = "APOYADA"
    elif (curve[lo]["consequence_free"] < curve[lo]["passive"] - margin) or \
         (curve[hi]["consequence_free"] <= curve[hi]["consequence_v"] - 1e-9):
        v = "REFUTADA"
    else:
        v = "MIXTA"
    return v, {"lo": lo, "hi": hi, "curve": curve, "recovers_at_lo": recovers, "robust_at_hi": robust,
               "free_minus_v_at_hi": curve[hi]["consequence_free"] - curve[hi]["consequence_v"],
               "free_minus_passive_at_lo": curve[lo]["consequence_free"] - curve[lo]["passive"],
               "two_sigma": 2 * sig, "n_seeds_used": len(use), "n_in_band": len(inb)}


def margin_robust(margin):
    return max(0.02, margin - 0.01)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=str, default="0,1,2,3")
    ap.add_argument("--M", type=int, default=120)
    ap.add_argument("--avg", type=int, default=5, help="presupuesto (n_probe=3 + extra=2/problema)")
    ap.add_argument("--n_probe", type=int, default=3, help="probe (>=3 para granularidad de p_top)")
    ap.add_argument("--noises", type=str, default="0,0.1,0.2", help="barrido de vnoise (FP=FN)")
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
        args.seeds, args.M, args.noises, args.base_steps = "0,1", 80, "0,0.2", 300

    seeds = [int(s) for s in args.seeds.split(",") if s.strip() != ""]
    noises = [float(x) for x in args.noises.split(",") if x.strip() != ""]
    logs = []

    def log(m):
        print(m, flush=True)
        logs.append(m)

    train_pairs, test_pairs = T.build_split(args.lo, args.hi, args.test_frac)
    test_full = T.test_from_pairs(test_pairs)
    rng = np.random.default_rng(20260624)
    if len(test_full) > args.M:
        sel = rng.choice(len(test_full), size=args.M, replace=False)
        test = [test_full[i] for i in sel]
    else:
        test = test_full

    log(f"[exp028] CYCLE 42 / H-V4-1g — señal de control verifier-free (auto-consistencia) vs ruido")
    log(f"[exp028] suma [{args.lo},{args.hi}] test={len(test)} avg={args.avg} n_probe={args.n_probe} "
        f"noises={noises} seeds={seeds}")

    res = [run_seed(s, args, test, train_pairs, noises, log) for s in seeds]
    v, stats = verdict(res, noises, args.margin)
    cl, ch = stats["curve"][stats["lo"]], stats["curve"][stats["hi"]]
    log(f"[exp028] VEREDICTO H-V4-1g: {v} | recupera@vnoise={stats['lo']} (FREE-PASIVA={stats['free_minus_passive_at_lo']:+.3f}): "
        f"{stats['recovers_at_lo']} | robusta@vnoise={stats['hi']} (FREE-CONSEC_V={stats['free_minus_v_at_hi']:+.3f}): {stats['robust_at_hi']}")
    log(f"[exp028] CURVA vnoise->AZAR/PASIVA/CONSEC_V/CONSEC_FREE/greedy: " +
        " | ".join("{}:{:.3f}/{:.3f}/{:.3f}/{:.3f}/{:.3f}".format(
            vn, stats['curve'][vn]['uniform'], stats['curve'][vn]['passive'],
            stats['curve'][vn]['consequence_v'], stats['curve'][vn]['consequence_free'],
            stats['curve'][vn]['greedy']) for vn in noises))

    out = {"exp": "exp028_robust_control_signal", "cycle": 42, "hypothesis": "H-V4-1g",
           "claim": "una señal de control por auto-consistencia (verifier-free) recupera la ventaja de exp026 "
                    "y es más robusta al ruido del verificador que la señal verifier-dependiente",
           "verdict": v, "stats": stats, "args": vars(args), "noises": noises, "seeds": res,
           "platform": {"python": platform.python_version(), "numpy": np.__version__, "torch": torch.__version__},
           "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    path = os.path.join(RESULTS, "results.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp028] escrito {path}")


if __name__ == "__main__":
    main()
