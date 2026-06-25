r"""
exp032 — CYCLE 46 / H-V4-1k: ABSTENCIÓN calibrada + verificador RUIDOSO per-step en cadenas multi-paso.
Combina los dos realismos pendientes de 44-45.

CONTEXTO: exp031 (CYCLE 45) dejó dos cabos: (1) cuando un paso agota su presupuesto sin verificar, step-wise
commitea uno malo y DESCARRILA en silencio; (2) el verificador per-step era perfecto. Pregunta: ¿ABSTENERSE
(decir "no sé") cuando ningún sample de un paso verifica convierte errores silenciosos en abstenciones
flagueadas, subiendo la PRECISIÓN-sobre-respondidas — incluso con verificador RUIDOSO per-step?

ANALOGÍA: en una cuenta larga, si en un paso NO te convence ninguno de tus intentos, más vale DECIR "no estoy
seguro" que escribir cualquier número y arrastrar el error hasta el final. Abstenerse cuesta cobertura
(respondés menos) pero lo que SÍ respondés es mucho más confiable — y un sistema honesto sabe cuándo no sabe.

DISEÑO (extiende exp031: cadena de sumas mod 20, presupuesto ADAPTATIVO per-step gastar-hasta-verificar,
modelo propio). El verificador per-step es RUIDOSO (vnoise=FP=FN). En cada paso se commitea el primer sample
NOISY-aceptado. Dos políticas:
  - COMMIT-SIEMPRE (baseline 45): si ningún sample se acepta, commitea el primero igual y sigue. Métrica:
    accuracy REAL de la traza final (commitea basura -> descarrila).
  - ABSTENER: si ningún sample de un paso se acepta, la cadena ABSTIENE (no responde). Métricas:
    COBERTURA = fracción de cadenas respondidas; PRECISIÓN = fracción VERDADERAMENTE correcta entre las
    respondidas (con verificador ruidoso, los falsos positivos bajan la precisión de 1.0).
Barrido (K, vnoise), 4 seeds.

PREDICCIÓN FALSABLE (pre-registrada):
  - APOYADA si la PRECISIÓN-sobre-respondidas (abstener) supera a la accuracy COMMIT-SIEMPRE por margen claro
    (>=0.15) en cadenas largas y a ruido moderado, con COBERTURA útil (>=0.2) -> abstenerse es un lever de
    HONESTIDAD: lo respondido es mucho más confiable.
  - REFUTADA si precisión(abstener) <= accuracy(commit-siempre) (abstener no ayuda) o la cobertura se vuelve
    ~0 (abstiene todo, inútil).
  - MIXTA si sube la precisión pero modesto, o la cobertura colapsa salvo a ruido cero.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp032_abstention_noisy.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp032_abstention_noisy.run            # FULL
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
from cognia_x.experiments.exp030_multistep_reasoning.run import MOD, parse_value, make_chain, step_pool
from cognia_x.experiments.exp027_noisy_verifier_ttc.run import noisy_accept

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")


def _step_commit(pool, vnoise, nrng):
    """Recorre el pool [(value, true_correct)] aplicando el verificador RUIDOSO. Devuelve (value, accepted):
    value del primer NOISY-aceptado (accepted=True); si ninguno, (pool[0][0], False)."""
    for val, tc in pool:
        if noisy_accept(tc, vnoise, nrng):
            return val, True
    return (pool[0][0] if pool else None), False


def run_commit_always(model, chains, avg, per_step_cap, vnoise, nrng, temperature, top_k, device):
    """Nunca abstiene: si ningún sample se acepta, commitea el primero. Accuracy REAL de la traza."""
    hits = 0
    for r0, a, ref in chains:
        K = len(a)
        B = avg * K
        spent, r, trace = 0, r0, []
        for i, ai in enumerate(a):
            avail = max(1, min(per_step_cap, B - spent - (K - i - 1)))
            pool = step_pool(model, r, ai, avail, temperature, top_k, device)
            val, _ = _step_commit(pool, vnoise, nrng)
            spent += avail                                    # commit-siempre gasta su avail (no para temprano)
            r = (val % MOD) if val is not None else -1
            trace.append(r)
        hits += int(trace == ref)
    return hits / max(1, len(chains))


def run_abstain(model, chains, avg, per_step_cap, vnoise, nrng, temperature, top_k, device):
    """Abstiene la cadena si en algún paso NINGÚN sample se acepta. Devuelve (coverage, precision_answered)."""
    answered = 0
    correct_answered = 0
    for r0, a, ref in chains:
        K = len(a)
        B = avg * K
        spent, r, trace, abstain = 0, r0, [], False
        for i, ai in enumerate(a):
            avail = max(1, min(per_step_cap, B - spent - (K - i - 1)))
            pool = step_pool(model, r, ai, avail, temperature, top_k, device)
            val, accepted = _step_commit(pool, vnoise, nrng)
            spent += avail
            if not accepted:
                abstain = True
                break                                          # paso sin verificar -> abstener (no arrastrar error)
            r = (val % MOD) if val is not None else -1
            trace.append(r)
        if not abstain:
            answered += 1
            correct_answered += int(trace == ref)
    coverage = answered / max(1, len(chains))
    precision = correct_answered / answered if answered > 0 else 0.0
    return coverage, precision


def run_seed(seed, args, train_pairs, Ks, noises, log):
    t0 = time.time()
    base, npar = build_base(seed, args.n_seed, args.base_steps, args.base_lr, args.warmup,
                            args.batch, train_pairs, log)
    by = {}
    for K in Ks:
        crng = np.random.default_rng(60000 + seed * 31 + K)    # MISMAS cadenas que exp030/031
        chains = [make_chain(crng, K) for _ in range(args.M)]
        for vn in noises:
            nrng = np.random.default_rng(70000 + seed * 23 + K * 7 + int(round(vn * 1000)))
            acc_ca = run_commit_always(base, chains, args.avg, args.per_step_cap, vn, nrng,
                                       args.temperature, args.top_k, "cpu")
            cov, prec = run_abstain(base, chains, args.avg, args.per_step_cap, vn, nrng,
                                    args.temperature, args.top_k, "cpu")
            by[(K, vn)] = {"commit_always": acc_ca, "coverage": cov, "precision": prec}
            log(f"[exp032]   seed={seed} K={K} vnoise={vn}: COMMIT_ALWAYS={acc_ca:.3f} | "
                f"ABSTAIN cov={cov:.3f} prec={prec:.3f}")
    dt = time.time() - t0
    log(f"[exp032] seed={seed} {dt:.1f}s npar={npar}")
    return {"seed": seed, "npar": npar, "secs": round(dt, 2),
            "by": {"{}|{}".format(K, vn): val for (K, vn), val in by.items()}}


def verdict(seeds_res, Ks, noises, margin):
    use = seeds_res
    curve = {}
    for K in Ks:
        for vn in noises:
            key = "{}|{}".format(K, vn)
            ca = float(np.mean([r["by"][key]["commit_always"] for r in use]))
            cov = float(np.mean([r["by"][key]["coverage"] for r in use]))
            prec = float(np.mean([r["by"][key]["precision"] for r in use]))
            curve[key] = {"commit_always": ca, "coverage": cov, "precision": prec, "prec_gain": prec - ca}
    # Veredicto según el texto pre-registrado (toda la curva), no sólo Kmax:
    #  APOYADA si el lever se sostiene en el punto DURO (Kmax, ruido moderado): prec_gain>=margin Y cov>=0.2.
    #  MIXTA si funciona en ALGÚN régimen (cov>=0.2 Y prec_gain>=margin) pero colapsa en el duro (cobertura
    #    cae / precisión se erosiona) -> "la cobertura colapsa salvo a ruido/cadena cortos".
    #  REFUTADA si NO funciona en ningún régimen (la precisión nunca sube de forma útil, o abstiene todo).
    Kmax = Ks[-1]
    vmod = noises[len(noises) // 2] if len(noises) >= 3 else noises[-1]
    hard = curve["{}|{}".format(Kmax, vmod)]
    holds_at_hard = hard["prec_gain"] >= margin and hard["coverage"] >= 0.2
    works_somewhere = any(c["coverage"] >= 0.2 and c["prec_gain"] >= margin for c in curve.values())
    best = max(curve.items(), key=lambda kv: (kv[1]["coverage"] >= 0.2, kv[1]["prec_gain"]))
    if holds_at_hard:
        v = "APOYADA"
    elif works_somewhere:
        v = "MIXTA"
    else:
        v = "REFUTADA"
    return v, {"Kmax": Kmax, "vmod": vmod, "at_hard": hard, "best_regime": best[0], "best": best[1],
               "curve": curve, "holds_at_hard": holds_at_hard, "works_somewhere": works_somewhere,
               "n_seeds": len(use)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=str, default="0,1,2,3")
    ap.add_argument("--M", type=int, default=120)
    ap.add_argument("--avg", type=int, default=4)
    ap.add_argument("--per_step_cap", type=int, default=10)
    ap.add_argument("--Ks", type=str, default="2,4,6")
    ap.add_argument("--noises", type=str, default="0,0.1,0.2")
    ap.add_argument("--top_k", type=int, default=16)
    ap.add_argument("--temperature", type=float, default=1.0)
    ap.add_argument("--margin", type=float, default=0.15)
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
        args.seeds, args.M, args.Ks, args.noises, args.base_steps = "0,1", 60, "2,6", "0,0.2", 300

    seeds = [int(s) for s in args.seeds.split(",") if s.strip() != ""]
    Ks = [int(x) for x in args.Ks.split(",") if x.strip() != ""]
    noises = [float(x) for x in args.noises.split(",") if x.strip() != ""]
    logs = []

    def log(m):
        print(m, flush=True)
        logs.append(m)

    train_pairs, _ = T.build_split(args.lo, args.hi, args.test_frac)

    log(f"[exp032] CYCLE 46 / H-V4-1k — ABSTENCIÓN calibrada + verificador RUIDOSO per-step (modelo propio)")
    log(f"[exp032] cadena mod {MOD}, M={args.M} avg={args.avg} cap={args.per_step_cap} Ks={Ks} noises={noises} seeds={seeds}")

    res = [run_seed(s, args, train_pairs, Ks, noises, log) for s in seeds]
    v, stats = verdict(res, Ks, noises, args.margin)
    h = stats["at_hard"]
    b = stats["best"]
    log(f"[exp032] VEREDICTO H-V4-1k: {v} | DURO(K={stats['Kmax']},vn={stats['vmod']}): "
        f"COMMIT={h['commit_always']:.3f} PREC={h['precision']:.3f} COV={h['coverage']:.3f} gain={h['prec_gain']:+.3f} "
        f"| MEJOR_RÉGIMEN[{stats['best_regime']}]: PREC={b['precision']:.3f} COV={b['coverage']:.3f} gain={b['prec_gain']:+.3f} (req>={args.margin})")
    log(f"[exp032] CURVA K|vnoise->COMMIT/PREC/COV: " +
        " | ".join("{}:{:.3f}/{:.3f}/{:.3f}".format(
            k, stats['curve'][k]['commit_always'], stats['curve'][k]['precision'],
            stats['curve'][k]['coverage']) for k in sorted(stats['curve'].keys())))

    out = {"exp": "exp032_abstention_noisy", "cycle": 46, "hypothesis": "H-V4-1k",
           "claim": "abstenerse cuando un paso no verifica (con verificador ruidoso per-step) sube la precisión "
                    "sobre las cadenas respondidas vs commitear-siempre, a costa de cobertura (lever de honestidad)",
           "verdict": v, "stats": stats, "args": vars(args), "Ks": Ks, "noises": noises, "seeds": res,
           "platform": {"python": platform.python_version(), "numpy": np.__version__, "torch": torch.__version__},
           "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    path = os.path.join(RESULTS, "results.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp032] escrito {path}")


if __name__ == "__main__":
    main()
