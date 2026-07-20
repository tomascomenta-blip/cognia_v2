r"""
exp030 — CYCLE 44 / H-V4-1i (gran salto): razonamiento MULTI-PASO. ¿La verificación INTERMEDIA (step-wise
act-and-verify) supera a la verificación SÓLO-FINAL (end-to-end best-of-k) a IGUAL cómputo, y la ventaja CRECE
con la longitud de la cadena porque los errores se COMPONEN?

CONTEXTO: el sub-arco 40-43 cerró el act-and-verify de UN paso (control + política adaptativa). El razonamiento
real es MULTI-PASO: un error temprano descarrila todo lo que sigue. Pregunta raíz: ¿conviene verificar/corregir
PASO A PASO (caro por paso pero corta el error temprano) o sólo al FINAL (barato pero el error se propaga)?

ANALOGÍA: resolver un problema largo de varios pasos. Si revisás SÓLO el resultado final y está mal, no sabés
en qué paso te equivocaste y re-hacés todo (y la probabilidad de que TODA la cadena salga bien de un tirón
decae geométricamente). Si revisás CADA paso y corregís ahí mismo, un paso malo no contamina los siguientes:
la precisión se mantiene aunque la cadena sea larga.

DISEÑO (modelo propio del lab; reusa la suma de exp016). Cadena de K sumas IN-DISTRIBUTION con wrap modular
(para no salir del rango entrenado): r_0 dado; en cada paso i el modelo computa (r_{i-1} + a_i) con a_i∈[0,9],
r_{i-1}∈[0,19]; el siguiente estado es r_i = (valor commiteado) mod 20. CADA paso es una suma in-range que el
oráculo (int) verifica. Final correcto = r_K coincide con la cadena de referencia (un paso malo la descarrila).
Dos estrategias a IGUAL presupuesto total = k·K llamadas al modelo por cadena:
  - END-TO-END (verif sólo-final): muestrea k cadenas completas (una muestra/paso, sin verificar pasos);
    acepta si ALGUNA da el r_K final correcto (best-of-k sobre el final).
  - STEP-WISE (act-and-verify intermedio): en cada paso muestrea hasta k candidatos, VERIFICA el paso con el
    oráculo, commitea el primero correcto (si ninguno, el primero) y sigue. k·K llamadas igual.
Barrido de K, 4 seeds. Verificador PERFECTO (el compounding es ortogonal al ruido, ya estudiado en 41-43).

PREDICCIÓN FALSABLE (pre-registrada):
  - APOYADA si (a) end-to-end decae fuerte con K (≈ p_paso^K) mientras step-wise se mantiene casi PLANO, y
    (b) el GAP (step-wise − end-to-end) CRECE monótono con K, siendo > 0.20 en el K más largo. => verificar
    intermedio es el lever del razonamiento multi-paso.
  - REFUTADA si el gap NO crece con K (a igual cómputo da lo mismo verificar intermedio que sólo-final) o
    step-wise <= end-to-end en el K más largo.
  - MIXTA si el gap crece pero modesto (<0.20) o no-monótono.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp030_multistep_reasoning.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp030_multistep_reasoning.run            # FULL
"""
import argparse
import json
import math
import os
import platform
import sys
import time

import numpy as np
import torch

from cognia_x.experiments.exp016_verified_bootstrap import addition_task as T
from cognia_x.experiments.exp016_verified_bootstrap.run import build_base
from cognia_x.experiments.exp026_ttc_allocation.run import sample_counts, acc_sigma

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")
MOD = 20                          # wrap modular -> estado r_i siempre en [0,19] (in-distribution)


def parse_value(answer_bytes):
    """Valor entero de una respuesta emitida 'digits\\n' (o None si no parsea)."""
    g = bytes(answer_bytes)
    nl = g.find(T.NEWLINE)
    resp = g[:nl] if nl >= 0 else g
    if len(resp) == 0 or not resp.isdigit():
        return None
    return int(resp)


def make_chain(rng, K):
    """Cadena de K pasos: r0 in [0,19], a_i in [0,9]. Devuelve (r0, [a_1..a_K], [r_1..r_K] referencia)."""
    r0 = int(rng.integers(0, MOD))
    a = [int(rng.integers(0, 10)) for _ in range(K)]
    ref = []
    r = r0
    for ai in a:
        r = (r + ai) % MOD
        ref.append(r)
    return r0, a, ref


def step_pool(model, r_prev, a_i, k, temperature, top_k, device):
    """k muestras del modelo para 'r_prev + a_i='. Devuelve list[(value_or_None, is_correct)] en orden."""
    prompt = T.make_prompt(r_prev, a_i)
    samples = sample_counts(model, prompt, k, temperature, top_k, device)  # [(answer_bytes, is_correct)]
    out = []
    for ans, correct in samples:
        out.append((parse_value(ans), bool(correct)))
    return out


def run_end_to_end(model, chains, k, temperature, top_k, device):
    """k cadenas completas, 1 muestra/paso, sin verificar pasos. Correcto si ALGUNA produce la TRAZA completa
    [r_1..r_K] correcta (verificación SÓLO-FINAL del output completo, sin piso de suerte)."""
    hits = 0
    for r0, a, ref in chains:
        ok = False
        for _ in range(k):
            r = r0
            trace = []
            for ai in a:
                val, _ = step_pool(model, r, ai, 1, temperature, top_k, device)[0]
                r = (val % MOD) if val is not None else -1         # basura -> estado inválido (descarrila)
                trace.append(r)
            if trace == ref:
                ok = True
                break
        hits += int(ok)
    return hits / max(1, len(chains))


def run_step_wise(model, chains, k, temperature, top_k, device):
    """En cada paso: hasta k muestras, verifica el paso (oráculo), commitea el primero correcto (si ninguno,
    el primero). Correcto = traza producida == referencia. Mismo presupuesto k·K que end-to-end."""
    hits = 0
    for r0, a, ref in chains:
        r = r0
        trace = []
        for ai in a:
            pool = step_pool(model, r, ai, k, temperature, top_k, device)
            picked = next((v for v, c in pool if c), None)         # primer correcto (act-and-verify)
            if picked is None:
                picked = pool[0][0]                                # ninguno verifica -> commitea el primero
            r = (picked % MOD) if picked is not None else -1
            trace.append(r)
        hits += int(trace == ref)
    return hits / max(1, len(chains))


def run_seed(seed, args, train_pairs, Ks, log):
    t0 = time.time()
    base, npar = build_base(seed, args.n_seed, args.base_steps, args.base_lr, args.warmup,
                            args.batch, train_pairs, log)
    # accuracy de UN paso (greedy) para contextualizar el compounding
    rng = np.random.default_rng(50000 + seed)
    by_K = {}
    for K in Ks:
        crng = np.random.default_rng(60000 + seed * 31 + K)
        chains = [make_chain(crng, K) for _ in range(args.M)]
        a_e2e = run_end_to_end(base, chains, args.k, args.temperature, args.top_k, "cpu")
        a_sw = run_step_wise(base, chains, args.k, args.temperature, args.top_k, "cpu")
        by_K[K] = {"end_to_end": a_e2e, "step_wise": a_sw, "gap": a_sw - a_e2e}
        log(f"[exp030]   seed={seed} K={K}: END_TO_END={a_e2e:.3f} STEP_WISE={a_sw:.3f} gap={a_sw - a_e2e:+.3f}")
    dt = time.time() - t0
    log(f"[exp030] seed={seed} {dt:.1f}s npar={npar}")
    return {"seed": seed, "npar": npar, "secs": round(dt, 2), "by_K": by_K}


def verdict(seeds_res, Ks, margin):
    use = seeds_res
    M = None
    curve = {}
    for K in Ks:
        me = float(np.mean([r["by_K"][K]["end_to_end"] for r in use]))
        ms = float(np.mean([r["by_K"][K]["step_wise"] for r in use]))
        curve[K] = {"end_to_end": me, "step_wise": ms, "gap": ms - me}
    Kmax = Ks[-1]
    gaps = [curve[K]["gap"] for K in Ks]
    grows = all(gaps[i + 1] >= gaps[i] - 1e-6 for i in range(len(gaps) - 1))   # monótono no-decreciente
    big_at_max = curve[Kmax]["gap"] >= margin
    e2e_decays = curve[Kmax]["end_to_end"] < curve[Ks[0]]["end_to_end"] - 1e-6
    if grows and big_at_max and e2e_decays:
        v = "APOYADA"
    elif (not e2e_decays) or curve[Kmax]["gap"] <= 0:
        v = "REFUTADA"
    else:
        v = "MIXTA"
    return v, {"Kmax": Kmax, "curve": curve, "gaps_grow_monotonic": grows,
               "gap_at_Kmax": curve[Kmax]["gap"], "big_at_max": big_at_max, "e2e_decays": e2e_decays,
               "n_seeds": len(use)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=str, default="0,1,2,3")
    ap.add_argument("--M", type=int, default=120, help="cadenas por K")
    ap.add_argument("--k", type=int, default=4, help="muestras por paso (= cadenas en end-to-end); cómputo k·K")
    ap.add_argument("--Ks", type=str, default="1,2,4,6", help="longitudes de cadena")
    ap.add_argument("--top_k", type=int, default=16)
    ap.add_argument("--temperature", type=float, default=1.0)
    ap.add_argument("--margin", type=float, default=0.20, help="gap requerido en Kmax para APOYADA")
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
        args.seeds, args.M, args.Ks, args.base_steps = "0,1", 60, "1,4", 300

    seeds = [int(s) for s in args.seeds.split(",") if s.strip() != ""]
    Ks = [int(x) for x in args.Ks.split(",") if x.strip() != ""]
    logs = []

    def log(m):
        print(m, flush=True)
        logs.append(m)

    train_pairs, _ = T.build_split(args.lo, args.hi, args.test_frac)  # base entrenado igual que exp016/026

    log(f"[exp030] CYCLE 44 / H-V4-1i — razonamiento MULTI-PASO: verif intermedia vs sólo-final (modelo propio)")
    log(f"[exp030] cadena de sumas mod {MOD}, M={args.M} k={args.k} (cómputo k·K) Ks={Ks} seeds={seeds}")

    res = [run_seed(s, args, train_pairs, Ks, log) for s in seeds]
    v, stats = verdict(res, Ks, args.margin)
    log(f"[exp030] VEREDICTO H-V4-1i: {v} | gap@K={stats['Kmax']}={stats['gap_at_Kmax']:+.3f} "
        f"(req>={args.margin}) crece_monotono={stats['gaps_grow_monotonic']} e2e_decae={stats['e2e_decays']}")
    log(f"[exp030] CURVA K->END_TO_END/STEP_WISE/gap: " +
        " | ".join("K{}:{:.3f}/{:.3f}/{:+.3f}".format(
            K, stats['curve'][K]['end_to_end'], stats['curve'][K]['step_wise'], stats['curve'][K]['gap']) for K in Ks))

    out = {"exp": "exp030_multistep_reasoning", "cycle": 44, "hypothesis": "H-V4-1i",
           "claim": "la verificación intermedia (step-wise act-and-verify) supera a la sólo-final (end-to-end) "
                    "a igual cómputo, y la ventaja crece con la longitud de cadena (compounding de errores)",
           "verdict": v, "stats": stats, "args": vars(args), "Ks": Ks, "seeds": res,
           "platform": {"python": platform.python_version(), "numpy": np.__version__, "torch": torch.__version__},
           "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    path = os.path.join(RESULTS, "results.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp030] escrito {path}")


if __name__ == "__main__":
    main()
