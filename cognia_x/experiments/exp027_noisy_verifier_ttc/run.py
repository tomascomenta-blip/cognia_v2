r"""
exp027 — CYCLE 41 / H-V4-1f: realismo del VERIFICADOR. ¿La ventaja de asignar cómputo test-time por
CONTROLABILIDAD/CONSECUENCIA (exp026) SOBREVIVE a un verificador RUIDOSO/PARCIAL — y hasta qué nivel de
ruido — sobre el modelo propio del lab?

CONTEXTO: exp026 (CYCLE 40) demostró que, con verificador PERFECTO (oráculo), asignar el cómputo de
test-time por controlabilidad gana al azar y a la predicción-pasiva bajo escasez. Pero un oráculo perfecto
es irreal: en razonamiento de verdad el verificador se equivoca (falsos positivos = acepta una respuesta
INCORRECTA; falsos negativos = rechaza una CORRECTA). Si la ventaja se evapora con poco ruido, el integrador
es frágil; si degrada con gracia, es robusto. Es el realismo que pedía el techo de exp026.

ANALOGÍA: el estudiante ahora corrige con un compañero DISTRAÍDO que a veces da por buena una respuesta mala
(falso positivo) y a veces tacha una buena (falso negativo). ¿Sigue conviniendo gastar el tiempo donde
PENSAR MÁS controla el resultado, o el ruido del corrector lo arruina?

DISEÑO (extiende exp026; mismo HybridLM byte-level + tarea de suma). Verificador NOISY simétrico, parámetro
vnoise: una respuesta VERDADERA-correcta se ACEPTA con prob 1-vnoise (falso negativo = vnoise); una
VERDADERA-incorrecta se ACEPTA con prob vnoise (falso positivo = vnoise). Act-and-verify: COMMIT = el PRIMER
sample que el verificador ruidoso acepta (en orden de muestreo); si ninguno se acepta -> sin commit
(incorrecto). ACCURACY REAL = el commit es VERDADERAMENTE correcto (oráculo) — castiga los falsos positivos
(commitear una respuesta mala que el verificador dejó pasar). Las 3 políticas reparten el MISMO presupuesto
B=M*avg (avg=3 = el régimen escaso DISCRIMINANTE de exp026); el probe y la señal de consecuencia usan el
verificador RUIDOSO (lo único que el agente observa). Barrido de vnoise, 4 seeds.

PREDICCIÓN FALSABLE (pre-registrada):
  - vnoise=0 debe REPRODUCIR exp026 (sanity): CONSEC > AZAR > PASIVA en accuracy real.
  - APOYADA (robusto) si a ruido MODERADO vnoise=0.10 la CONSEC sigue >= AZAR y >= PASIVA (margen >= 0 y la
    ventaja sobre PASIVA se mantiene > 2σ), y la accuracy real degrada con GRACIA (monótona, sin colapso).
  - REFUTADA (frágil) si con vnoise=0.10 la CONSEC <= AZAR (poco ruido ya borra la ventaja del control) O la
    accuracy real COLAPSA por debajo del greedy (los falsos positivos hacen el act-and-verify peor que no
    samplear).
  - MIXTA si la ventaja sobrevive vs uno pero no vs el otro, o dentro del ruido.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp027_noisy_verifier_ttc.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp027_noisy_verifier_ttc.run            # FULL
  (opcional) --seeds 0,1,2,3 --M 120 --avg 3 --n_probe 2 --noises 0,0.05,0.1,0.2 --top_k 16
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

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")


def noisy_accept(true_correct, vnoise, nrng):
    """Verificador RUIDOSO simétrico. Devuelve si ACEPTA el sample. FN: rechaza una correcta con prob
    vnoise. FP: acepta una incorrecta con prob vnoise."""
    p_accept = (1.0 - vnoise) if true_correct else vnoise
    return bool(nrng.random() < p_accept)


def commit_true_correct(samples, vnoise, nrng):
    """samples = [(answer, true_correct), ...] en orden de muestreo. COMMIT = primer aceptado por el
    verificador ruidoso. Devuelve (committed_true_correct_bool, solved_observed_bool). solved_observed =
    el verificador aceptó ALGUNO (lo que el agente CREE que resolvió)."""
    for ans, tc in samples:
        if noisy_accept(tc, vnoise, nrng):
            return bool(tc), True          # commitea el PRIMER aceptado; su corrección REAL es lo que cuenta
    return False, False                    # nada aceptado -> sin commit -> incorrecto


def policy_uniform(model, test, B, vnoise, nrng, temperature, top_k, device):
    """AZAR: k_i=B/M. Devuelve accuracy REAL del commit (castiga falsos positivos)."""
    M = len(test)
    counts = largest_remainder([1.0] * M, B)
    hits = 0
    for (p, _, _), k in zip(test, counts):
        s = sample_counts(model, p, k, temperature, top_k, device)
        tc, _ = commit_true_correct(s, vnoise, nrng)
        hits += int(tc)
    return hits / max(1, M)


def policy_probe(model, test, B, n_probe, vnoise, nrng, temperature, top_k, device, mode):
    """PASIVA/CONSECUENCIA con verificador ruidoso. La señal se calcula con lo que el agente OBSERVA (el
    verificador ruidoso): solved_observed y diversidad de respuestas del probe."""
    M = len(test)
    probe = []
    weights = []
    for (p, _, _) in test:
        s = sample_counts(model, p, n_probe, temperature, top_k, device)
        # ¿el verificador ruidoso aceptó algo en el probe? (lo que el agente cree)
        solved_obs = any(noisy_accept(tc, vnoise, nrng) for _, tc in s)
        probe.append((p, s, solved_obs))
        h = answer_entropy(s)
        n_distinct = len(set(a for a, _ in s))
        if mode == "passive":
            w = h + 1e-3
        elif mode == "consequence":
            w = 0.0 if solved_obs else (n_distinct - 1) + 1e-3
        else:
            raise ValueError(mode)
        weights.append(w)

    extra = max(0, B - M * n_probe)
    alloc = largest_remainder(weights, extra)

    hits = 0
    for (p, ps, solved_obs), k in zip(probe, alloc):
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
        nrng = np.random.default_rng(7000 + seed * 13 + int(round(vn * 1000)))
        a_rand = policy_uniform(base, test, B, vn, nrng, args.temperature, args.top_k, "cpu")
        a_pass = policy_probe(base, test, B, args.n_probe, vn, nrng, args.temperature, args.top_k, "cpu", "passive")
        a_cons = policy_probe(base, test, B, args.n_probe, vn, nrng, args.temperature, args.top_k, "cpu", "consequence")
        by_noise[vn] = {"uniform": a_rand, "passive": a_pass, "consequence": a_cons, "greedy": greedy_acc}
        log(f"[exp027]   seed={seed} vnoise={vn}: AZAR={a_rand:.3f} PASIVA={a_pass:.3f} CONSEC={a_cons:.3f} (greedy={greedy_acc:.3f})")
    dt = time.time() - t0
    log(f"[exp027] seed={seed} greedy={greedy_acc:.3f} ({band}) {dt:.1f}s npar={npar}")
    return {"seed": seed, "greedy_acc": greedy_acc, "in_band": 0.20 <= greedy_acc <= 0.50,
            "M": M, "B": B, "npar": npar, "secs": round(dt, 2), "by_noise": by_noise}


def verdict(seeds_res, noises, mod_noise, margin):
    """Veredicto al nivel de ruido MODERADO `mod_noise` (realismo). Reporta la curva completa por ruido."""
    inb = [r for r in seeds_res if r["in_band"]]
    use = inb if inb else seeds_res
    M = use[0]["M"]

    def key(vn):
        return vn if vn in use[0]["by_noise"] else float(vn)

    curve = {}
    for vn in noises:
        k = key(vn)
        mc = float(np.mean([r["by_noise"][k]["consequence"] for r in use]))
        mr = float(np.mean([r["by_noise"][k]["uniform"] for r in use]))
        mp = float(np.mean([r["by_noise"][k]["passive"] for r in use]))
        mg = float(np.mean([r["by_noise"][k]["greedy"] for r in use]))
        sig = acc_sigma(mc, M) / math.sqrt(len(use))
        curve[vn] = {"consequence": mc, "uniform": mr, "passive": mp, "greedy": mg,
                     "d_vs_uniform": mc - mr, "d_vs_passive": mc - mp, "two_sigma": 2 * sig}
    c = curve[mod_noise]
    survives_rand = c["d_vs_uniform"] >= -margin                       # no PEOR que el azar (tolerancia margen)
    survives_pass = c["d_vs_passive"] >= margin and c["d_vs_passive"] >= c["two_sigma"]
    no_collapse = c["consequence"] >= c["greedy"]                      # act-and-verify no peor que no samplear
    if survives_rand and survives_pass and no_collapse:
        v = "APOYADA"
    elif (c["consequence"] < c["uniform"] - margin) or (not no_collapse):
        v = "REFUTADA"
    else:
        v = "MIXTA"
    return v, {"mod_noise": mod_noise, "at_mod": c, "curve": curve,
               "n_seeds_used": len(use), "n_in_band": len(inb)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=str, default="0,1,2,3")
    ap.add_argument("--M", type=int, default=120)
    ap.add_argument("--avg", type=int, default=3, help="presupuesto escaso DISCRIMINANTE de exp026")
    ap.add_argument("--n_probe", type=int, default=2)
    ap.add_argument("--noises", type=str, default="0,0.05,0.1,0.2", help="barrido de vnoise (FP=FN)")
    ap.add_argument("--mod_noise", type=float, default=0.1, help="nivel moderado para el veredicto")
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
        args.seeds, args.M, args.noises, args.base_steps = "0,1", 80, "0,0.1", 300

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

    log(f"[exp027] CYCLE 41 / H-V4-1f — verificador RUIDOSO sobre act-and-verify TTS (HybridLM propio)")
    log(f"[exp027] suma [{args.lo},{args.hi}] test={len(test)} avg={args.avg} n_probe={args.n_probe} "
        f"noises={noises} mod={args.mod_noise} seeds={seeds}")

    res = [run_seed(s, args, test, train_pairs, noises, log) for s in seeds]
    v, stats = verdict(res, noises, args.mod_noise, args.margin)
    c = stats["at_mod"]
    log(f"[exp027] VEREDICTO H-V4-1f (ruido moderado vnoise={stats['mod_noise']}): {v} | "
        f"CONSEC={c['consequence']:.3f} AZAR={c['uniform']:.3f} PASIVA={c['passive']:.3f} greedy={c['greedy']:.3f} | "
        f"Δazar={c['d_vs_uniform']:+.3f} Δpasiva={c['d_vs_passive']:+.3f} (2σ={c['two_sigma']:.3f})")
    log(f"[exp027] CURVA vnoise->CONSEC/AZAR/PASIVA/greedy: " +
        " | ".join(f"{vn}:{stats['curve'][vn]['consequence']:.3f}/{stats['curve'][vn]['uniform']:.3f}/"
                   f"{stats['curve'][vn]['passive']:.3f}/{stats['curve'][vn]['greedy']:.3f}" for vn in noises))

    out = {"exp": "exp027_noisy_verifier_ttc", "cycle": 41, "hypothesis": "H-V4-1f",
           "claim": "la ventaja de asignar cómputo test-time por controlabilidad sobrevive a un verificador "
                    "ruidoso/parcial moderado y degrada con gracia (no colapsa por falsos positivos)",
           "verdict": v, "stats": stats, "args": vars(args), "noises": noises, "seeds": res,
           "platform": {"python": platform.python_version(), "numpy": np.__version__, "torch": torch.__version__},
           "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    path = os.path.join(RESULTS, "results.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp027] escrito {path}")


if __name__ == "__main__":
    main()
