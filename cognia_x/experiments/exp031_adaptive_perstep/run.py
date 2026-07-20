r"""
exp031 — CYCLE 45 / H-V4-1j: presupuesto ADAPTATIVO per-step en cadenas largas. ¿Gastar el cómputo "hasta
verificar" con un pool COMPARTIDO entre pasos (más a los pasos difíciles, menos a los fáciles) rescata las
cadenas largas que el presupuesto por-paso FIJO dejaba colapsar (exp030), a IGUAL cómputo total?

CONTEXTO: exp030 (CYCLE 44) mostró que la verificación intermedia frena el compounding, pero con presupuesto
por-paso FIJO (k por paso) las cadenas largas igual colapsan: el presupuesto se MALGASTA en los pasos fáciles
(que verifican al primer intento) mientras los difíciles fallan. Aplica el control adaptativo (43) ACROSS the
chain: repartir el cómputo por dificultad del paso.

ANALOGÍA: examen con varios ejercicios y tiempo total fijo. Si das el MISMO tiempo a cada uno, malgastás en
los fáciles (que resolvés al toque) y te quedás corto en los difíciles. Si avanzás rápido en los fáciles
(parás en cuanto te sale) y reinvertís ese tiempo en los difíciles, resolvés más en total.

DISEÑO (extiende exp030; misma cadena de sumas mod 20). Presupuesto TOTAL por cadena B = avg·K (mismo que el
uniforme). Dos políticas:
  - UNIFORME: cada paso recibe exactamente `avg` muestras; commitea el primer verificado (si ninguno, el 1ro).
  - ADAPTATIVO (gastar-hasta-verificar, pool compartido): reserva 1 muestra por paso futuro (anti-starvation);
    en cada paso dibuja hasta cap=min(per_step_cap, 1+pool_extra) muestras pero PARA en cuanto una verifica;
    el costo real = índice del primer verificado +1 (o cap si ninguno). Lo NO gastado queda en el pool para los
    pasos difíciles siguientes. Mismo B total. (Se dibuja en batch y se cuenta el costo como si fuera
    secuencial-hasta-verificar -> idéntico y rápido.)
Barrido de K, 4 seeds. Verificador PERFECTO per-step (el ruido per-step es el siguiente realismo).

PREDICCIÓN FALSABLE (pre-registrada):
  - APOYADA si ADAPT > UNIFORME a IGUAL B en las cadenas largas (margen >= 0.03 en Kmax) y la ventaja CRECE
    (o no decrece) con K -> reasignar por dificultad rescata cadenas largas.
  - REFUTADA si ADAPT <= UNIFORME en Kmax (reasignar no ayuda) o la ventaja decrece con K.
  - MIXTA si ayuda pero modesto/no-monótono.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp031_adaptive_perstep.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp031_adaptive_perstep.run            # FULL
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

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")


def _first_verified(pool):
    """(value_commiteado, costo) de un pool [(value, is_correct)] gastando-hasta-verificar: para en el primer
    correcto. costo = índice del primer correcto +1; si ninguno, len(pool) y commitea el primero."""
    for j, (val, c) in enumerate(pool):
        if c:
            return val, j + 1
    return (pool[0][0] if pool else None), len(pool)


def run_uniform(model, chains, avg, temperature, top_k, device):
    """Cada paso recibe `avg` muestras; commitea el primer verificado. B = avg·K por cadena."""
    hits = 0
    for r0, a, ref in chains:
        r, trace = r0, []
        for ai in a:
            pool = step_pool(model, r, ai, avg, temperature, top_k, device)
            picked = next((v for v, c in pool if c), pool[0][0] if pool else None)
            r = (picked % MOD) if picked is not None else -1
            trace.append(r)
        hits += int(trace == ref)
    return hits / max(1, len(chains))


def run_adaptive(model, chains, avg, per_step_cap, temperature, top_k, device):
    """Gastar-hasta-verificar con pool compartido B=avg·K; reserva 1/paso futuro (anti-starvation); cap por
    paso. El presupuesto no gastado en pasos fáciles se reinvierte en los difíciles. Mismo B total."""
    hits = 0
    for r0, a, ref in chains:
        K = len(a)
        B = avg * K
        spent = 0
        r, trace = r0, []
        for i, ai in enumerate(a):
            steps_left_after = K - i - 1
            avail = min(per_step_cap, B - spent - steps_left_after)   # reserva 1 por paso futuro
            avail = max(1, avail)
            pool = step_pool(model, r, ai, avail, temperature, top_k, device)
            picked, cost = _first_verified(pool)
            spent += cost
            r = (picked % MOD) if picked is not None else -1
            trace.append(r)
        hits += int(trace == ref)
    return hits / max(1, len(chains))


def run_seed(seed, args, train_pairs, Ks, log):
    t0 = time.time()
    base, npar = build_base(seed, args.n_seed, args.base_steps, args.base_lr, args.warmup,
                            args.batch, train_pairs, log)
    by_K = {}
    for K in Ks:
        crng = np.random.default_rng(60000 + seed * 31 + K)   # MISMAS cadenas que exp030
        chains = [make_chain(crng, K) for _ in range(args.M)]
        a_uni = run_uniform(base, chains, args.avg, args.temperature, args.top_k, "cpu")
        a_ada = run_adaptive(base, chains, args.avg, args.per_step_cap, args.temperature, args.top_k, "cpu")
        by_K[K] = {"uniform": a_uni, "adaptive": a_ada, "gain": a_ada - a_uni}
        log(f"[exp031]   seed={seed} K={K}: UNIFORME={a_uni:.3f} ADAPT={a_ada:.3f} gain={a_ada - a_uni:+.3f}")
    dt = time.time() - t0
    log(f"[exp031] seed={seed} {dt:.1f}s npar={npar}")
    return {"seed": seed, "npar": npar, "secs": round(dt, 2), "by_K": by_K}


def verdict(seeds_res, Ks, margin):
    use = seeds_res
    curve = {}
    for K in Ks:
        mu = float(np.mean([r["by_K"][K]["uniform"] for r in use]))
        ma = float(np.mean([r["by_K"][K]["adaptive"] for r in use]))
        curve[K] = {"uniform": mu, "adaptive": ma, "gain": ma - mu}
    Kmax = Ks[-1]
    gains = [curve[K]["gain"] for K in Ks]
    grows = all(gains[i + 1] >= gains[i] - 0.02 for i in range(len(gains) - 1))   # no decrece (tol)
    big_at_max = curve[Kmax]["gain"] >= margin
    if big_at_max and grows:
        v = "APOYADA"
    elif curve[Kmax]["gain"] <= 0:
        v = "REFUTADA"
    else:
        v = "MIXTA"
    return v, {"Kmax": Kmax, "curve": curve, "gains_grow": grows, "gain_at_Kmax": curve[Kmax]["gain"],
               "big_at_max": big_at_max, "n_seeds": len(use)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=str, default="0,1,2,3")
    ap.add_argument("--M", type=int, default=120)
    ap.add_argument("--avg", type=int, default=4, help="muestras promedio por paso (B = avg·K)")
    ap.add_argument("--per_step_cap", type=int, default=10, help="tope de muestras que un paso difícil puede tomar")
    ap.add_argument("--Ks", type=str, default="2,4,6,8")
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
        args.seeds, args.M, args.Ks, args.base_steps = "0,1", 60, "2,6", 300

    seeds = [int(s) for s in args.seeds.split(",") if s.strip() != ""]
    Ks = [int(x) for x in args.Ks.split(",") if x.strip() != ""]
    logs = []

    def log(m):
        print(m, flush=True)
        logs.append(m)

    train_pairs, _ = T.build_split(args.lo, args.hi, args.test_frac)

    log(f"[exp031] CYCLE 45 / H-V4-1j — presupuesto ADAPTATIVO per-step (gastar-hasta-verificar) en cadenas largas")
    log(f"[exp031] cadena mod {MOD}, M={args.M} avg={args.avg} (B=avg·K) cap={args.per_step_cap} Ks={Ks} seeds={seeds}")

    res = [run_seed(s, args, train_pairs, Ks, log) for s in seeds]
    v, stats = verdict(res, Ks, args.margin)
    log(f"[exp031] VEREDICTO H-V4-1j: {v} | gain@K={stats['Kmax']}={stats['gain_at_Kmax']:+.3f} "
        f"(req>={args.margin}) crece={stats['gains_grow']}")
    log(f"[exp031] CURVA K->UNIFORME/ADAPT/gain: " +
        " | ".join("K{}:{:.3f}/{:.3f}/{:+.3f}".format(
            K, stats['curve'][K]['uniform'], stats['curve'][K]['adaptive'], stats['curve'][K]['gain']) for K in Ks))

    out = {"exp": "exp031_adaptive_perstep", "cycle": 45, "hypothesis": "H-V4-1j",
           "claim": "asignar el presupuesto de cómputo por paso de forma adaptativa (gastar-hasta-verificar con "
                    "pool compartido) rescata cadenas largas vs presupuesto por-paso fijo, a igual cómputo total",
           "verdict": v, "stats": stats, "args": vars(args), "Ks": Ks, "seeds": res,
           "platform": {"python": platform.python_version(), "numpy": np.__version__, "torch": torch.__version__},
           "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    path = os.path.join(RESULTS, "results.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp031] escrito {path}")


if __name__ == "__main__":
    main()
