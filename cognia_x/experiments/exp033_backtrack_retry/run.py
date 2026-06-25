r"""
exp033 — CYCLE 47 / H-V4-1l: BACKTRACKING/RETRY del paso fallido. ¿Reintentar un paso que no verificó
(reinvertir presupuesto del pool en él, segunda oportunidad) en vez de abstener la cadena entera recupera
COBERTURA sin perder PRECISIÓN — a IGUAL presupuesto total?

CONTEXTO: exp032 (CYCLE 46) mostró que abstenerse al primer paso fallido sube la precisión pero la COBERTURA
COLAPSA en cadenas largas (toda cadena larga falla en algún paso -> abstiene todo). Muchas de esas
abstenciones son prematuras: el paso sólo necesitaba unas muestras más. RETRY ataca eso: ante un paso fallido,
darle una segunda tanda de muestras del pool antes de rendirse.

ANALOGÍA: en la cuenta larga, si un paso no te sale al primer intento, no tires toda la cuenta — INSISTÍ un
poco más en ESE paso. Si tras insistir sigue sin salir, ahí sí decí "no sé". Insistir cuesta presupuesto (que
sale del pool compartido), pero rescata cuentas que abandonabas por un solo paso difícil.

DISEÑO (extiende exp032: cadena mod 20, verificador RUIDOSO per-step, pool adaptativo, modelo propio). Dos
políticas a IGUAL presupuesto total B=avg·K:
  - ABSTAIN (baseline 46): en cada paso dibuja `avail` (adaptativo); si ningún sample se acepta -> abstiene la
    cadena.
  - RETRY: igual, pero si el paso falla y queda pool, dibuja hasta `retry_extra` muestras MÁS (segunda
    oportunidad) tomadas del pool; si alguna verifica -> commitea y sigue; si no (o pool agotado) -> abstiene.
    El presupuesto extra de los retries sale del MISMO pool (los pasos fáciles dejan pool para los difíciles).
Métricas: COBERTURA (fracción respondida) y PRECISIÓN (correctas entre respondidas). Barrido (K, vnoise),
4 seeds.

PREDICCIÓN FALSABLE (pre-registrada):
  - APOYADA si RETRY sube la COBERTURA de forma material (>=+0.10 en cadenas largas/ruido moderado) SIN bajar
    la precisión más de 0.10 -> RETRY mueve la frontera precisión/cobertura (rescata cobertura barato).
  - REFUTADA si RETRY no sube la cobertura (>=+0.10) en ningún régimen, o la sube pero hunde la precisión
    (>0.10) -> insistir no rescata / arruina la confiabilidad.
  - MIXTA si sube la cobertura modesto, o la sube a costa de precisión en algunos regímenes.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp033_backtrack_retry.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp033_backtrack_retry.run            # FULL
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
from cognia_x.experiments.exp032_abstention_noisy.run import _step_commit

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")


def _commit_cost(pool, vnoise, nrng):
    """Recorre el pool aplicando el verificador RUIDOSO, PARANDO en el primer aceptado (gastar-hasta-verificar).
    Devuelve (val, accepted, cost): cost = índice del primer aceptado +1; si ninguno, cost = len(pool)."""
    for j, (val, tc) in enumerate(pool):
        if noisy_accept(tc, vnoise, nrng):
            return val, True, j + 1
    return (pool[0][0] if pool else None), False, len(pool)


def run_chain(model, chains, avg, per_step_cap, retry_extra, vnoise, nrng, temperature, top_k, device, do_retry):
    """Devuelve (coverage, precision). Pool compartido B=avg·K con gastar-hasta-verificar (los pasos fáciles
    cuestan poco -> dejan pool para los difíciles). do_retry=False -> ABSTAIN (al fallar un paso, abstiene).
    do_retry=True -> RETRY: al fallar, segunda tanda desde el pool antes de abstener."""
    answered = 0
    correct_answered = 0
    for r0, a, ref in chains:
        K = len(a)
        B = avg * K
        spent, r, trace, abstain = 0, r0, [], False
        for i, ai in enumerate(a):
            avail = max(1, min(per_step_cap, B - spent - (K - i - 1)))   # reserva 1 por paso futuro
            pool = step_pool(model, r, ai, avail, temperature, top_k, device)
            val, accepted, cost = _commit_cost(pool, vnoise, nrng)
            spent += cost                                                # gastar-hasta-verificar (no el avail entero)
            if not accepted and do_retry:
                budget_left = B - spent - (K - i - 1)
                extra = max(0, min(retry_extra, budget_left))
                if extra > 0:
                    pool2 = step_pool(model, r, ai, extra, temperature, top_k, device)
                    v2, acc2, cost2 = _commit_cost(pool2, vnoise, nrng)
                    spent += cost2
                    if acc2:
                        val, accepted = v2, True
            if not accepted:
                abstain = True
                break
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
        crng = np.random.default_rng(60000 + seed * 31 + K)     # MISMAS cadenas que exp030/031/032
        chains = [make_chain(crng, K) for _ in range(args.M)]
        for vn in noises:
            # MISMO estado de RNG (torch+noise) para las dos políticas -> ven las MISMAS muestras base;
            # RETRY difiere SÓLO por las muestras extra en los pasos fallidos (aísla el efecto del retry).
            rng_state = torch.get_rng_state()
            nrng_a = np.random.default_rng(80000 + seed * 23 + K * 7 + int(round(vn * 1000)))
            cov_ab, prec_ab = run_chain(base, chains, args.avg, args.per_step_cap, args.retry_extra, vn,
                                        nrng_a, args.temperature, args.top_k, "cpu", do_retry=False)
            torch.set_rng_state(rng_state)
            nrng_r = np.random.default_rng(80000 + seed * 23 + K * 7 + int(round(vn * 1000)))
            cov_re, prec_re = run_chain(base, chains, args.avg, args.per_step_cap, args.retry_extra, vn,
                                        nrng_r, args.temperature, args.top_k, "cpu", do_retry=True)
            by["{}|{}".format(K, vn)] = {"abstain_cov": cov_ab, "abstain_prec": prec_ab,
                                         "retry_cov": cov_re, "retry_prec": prec_re,
                                         "cov_gain": cov_re - cov_ab, "prec_drop": prec_ab - prec_re}
            log(f"[exp033]   seed={seed} K={K} vn={vn}: ABSTAIN(cov={cov_ab:.3f} prec={prec_ab:.3f}) "
                f"RETRY(cov={cov_re:.3f} prec={prec_re:.3f}) Δcov={cov_re - cov_ab:+.3f} Δprec={prec_re - prec_ab:+.3f}")
    dt = time.time() - t0
    log(f"[exp033] seed={seed} {dt:.1f}s npar={npar}")
    return {"seed": seed, "npar": npar, "secs": round(dt, 2), "by": by}


def verdict(seeds_res, Ks, noises, cov_margin, prec_tol):
    use = seeds_res
    curve = {}
    for K in Ks:
        for vn in noises:
            key = "{}|{}".format(K, vn)
            curve[key] = {m: float(np.mean([r["by"][key][m] for r in use]))
                          for m in ("abstain_cov", "abstain_prec", "retry_cov", "retry_prec", "cov_gain", "prec_drop")}
    # PRE-REGISTRADO: RETRY recupera cobertura (Δcov>=cov_margin) SIN bajar precisión (prec_drop<=prec_tol).
    # Refinamiento HONESTO (reportado, no para mover el poste): la cobertura recuperada es ÚTIL sólo si las
    # respondidas son mayormente correctas (retry_prec>=PREC_FLOOR); con verificador ruidoso se rescatan
    # cadenas confiadamente-MAL. APOYADA = recupera Y útil; MIXTA = recupera pero gateado por la precisión del
    # régimen (verificador); REFUTADA = no recupera en ningún régimen o hunde la precisión.
    PREC_FLOOR = 0.5

    def recovers(c):
        return c["cov_gain"] >= cov_margin and c["prec_drop"] <= prec_tol

    def useful(c):
        return recovers(c) and c["retry_prec"] >= PREC_FLOOR

    Kmax = Ks[-1]
    vmod = noises[len(noises) // 2] if len(noises) >= 3 else noises[-1]
    hard = curve["{}|{}".format(Kmax, vmod)]
    recovers_at_hard = recovers(hard)
    useful_somewhere = any(useful(c) for c in curve.values())
    recovers_somewhere = any(recovers(c) for c in curve.values())
    best = max(curve.items(), key=lambda kv: (useful(kv[1]), recovers(kv[1]), kv[1]["cov_gain"]))
    if useful(hard):
        v = "APOYADA"
    elif recovers_at_hard or recovers_somewhere:
        v = "MIXTA"            # recupera cobertura sin dañar precisión, pero su utilidad está gateada por el verificador
    else:
        v = "REFUTADA"
    return v, {"Kmax": Kmax, "vmod": vmod, "at_hard": hard, "best_regime": best[0], "best": best[1],
               "curve": curve, "recovers_at_hard": recovers_at_hard, "useful_somewhere": useful_somewhere,
               "recovers_somewhere": recovers_somewhere, "prec_floor": PREC_FLOOR, "n_seeds": len(use)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=str, default="0,1,2,3")
    ap.add_argument("--M", type=int, default=120)
    ap.add_argument("--avg", type=int, default=4)
    ap.add_argument("--per_step_cap", type=int, default=8)
    ap.add_argument("--retry_extra", type=int, default=8, help="muestras extra de la 2da oportunidad por paso fallido")
    ap.add_argument("--Ks", type=str, default="2,4,6")
    ap.add_argument("--noises", type=str, default="0,0.1,0.2")
    ap.add_argument("--top_k", type=int, default=16)
    ap.add_argument("--temperature", type=float, default=1.0)
    ap.add_argument("--cov_margin", type=float, default=0.10, help="ganancia de cobertura requerida")
    ap.add_argument("--prec_tol", type=float, default=0.10, help="caída de precisión tolerada")
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

    log(f"[exp033] CYCLE 47 / H-V4-1l — BACKTRACKING/RETRY del paso fallido vs abstención (modelo propio)")
    log(f"[exp033] cadena mod {MOD}, M={args.M} avg={args.avg} cap={args.per_step_cap} retry={args.retry_extra} "
        f"Ks={Ks} noises={noises} seeds={seeds}")

    res = [run_seed(s, args, train_pairs, Ks, noises, log) for s in seeds]
    v, stats = verdict(res, Ks, noises, args.cov_margin, args.prec_tol)
    h = stats["at_hard"]
    b = stats["best"]
    log(f"[exp033] VEREDICTO H-V4-1l: {v} | DURO(K={stats['Kmax']},vn={stats['vmod']}): "
        f"Δcov={h['cov_gain']:+.3f} prec_drop={h['prec_drop']:+.3f} (req Δcov>={args.cov_margin}, drop<={args.prec_tol}) "
        f"| MEJOR[{stats['best_regime']}]: ABST(cov={b['abstain_cov']:.3f}) RETRY(cov={b['retry_cov']:.3f}) Δcov={b['cov_gain']:+.3f} drop={b['prec_drop']:+.3f}")
    log(f"[exp033] CURVA K|vn->ABST_cov/RETRY_cov/Δcov | ABST_prec/RETRY_prec: " +
        " | ".join("{}:{:.2f}/{:.2f}/{:+.2f} p{:.2f}/{:.2f}".format(
            k, stats['curve'][k]['abstain_cov'], stats['curve'][k]['retry_cov'], stats['curve'][k]['cov_gain'],
            stats['curve'][k]['abstain_prec'], stats['curve'][k]['retry_prec']) for k in sorted(stats['curve'].keys())))

    out = {"exp": "exp033_backtrack_retry", "cycle": 47, "hypothesis": "H-V4-1l",
           "claim": "reintentar el paso fallido (RETRY desde el pool) en vez de abstener la cadena recupera "
                    "cobertura sin perder precisión, a igual presupuesto total",
           "verdict": v, "stats": stats, "args": vars(args), "Ks": Ks, "noises": noises, "seeds": res,
           "platform": {"python": platform.python_version(), "numpy": np.__version__, "torch": torch.__version__},
           "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    path = os.path.join(RESULTS, "results.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp033] escrito {path}")


if __name__ == "__main__":
    main()
