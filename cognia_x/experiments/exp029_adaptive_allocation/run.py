r"""
exp029 — CYCLE 43 / H-V4-1h (capstone del sub-arco integrador): política ADAPTATIVA. ¿Estimar ONLINE la
fiabilidad del verificador (sin ground-truth) y MEZCLAR la señal de control verifier-dependiente (CONSEC_V,
buena con verificador confiable) con la verifier-free (CONSEC_FREE, robusta al ruido) logra "lo mejor de
ambas" — NO-REGRET en todos los regímenes de ruido?

CONTEXTO: exp028 (CYCLE 42) cerró que NO hay señal de asignación única dominante: CONSEC_V domina a
verificador bueno y colapsa a ruido alto; CONSEC_FREE es robusta pero no recupera el edge. La salida obvia:
una política que SEPA cuánto confiar en el verificador y se adapte.

IDEA RAÍZ (analogía): el estudiante calibra a su corrector. Compara lo que el corrector aprueba con su
PROPIO consenso (self-consistency): si el corrector aprueba lo que él ya cree correcto y tacha lo que cree
mal, el corrector es CONFIABLE -> le hace caso (señal verifier-dependiente). Si el corrector aprueba/tacha al
azar respecto de su consenso, NO es confiable -> se guía por su propio consenso (verifier-free). Estima la
confianza SIN respuestas correctas, sólo cruzando dos pistas imperfectas.

DISEÑO (extiende exp028; mismo HybridLM + verificador ruidoso, commit verifier-based igual para todas). La
fiabilidad GLOBAL r se estima del probe SIN ground-truth por TEST-RETEST del verificador: se lo consulta DOS
veces (independientes) por cada sample del probe y se mide su AUTO-ACUERDO. r = clip(2·P(coinciden) − 1, 0, 1).
Verificador perfecto (vnoise=0): siempre coincide -> r≈1; verificador azar (vnoise=0.5): coincide la mitad ->
r≈0. NO depende de que el modelo acierte (el consenso de un modelo débil es malo) — sólo de la CONSISTENCIA
del verificador (relanzarlo es barato = la premisa del TTS). Caveat: detecta ruido ALEATORIO, no sesgo
sistemático. Peso ADAPTATIVO por problema:
  w_adapt = r * w_consec_v + (1 − r) * w_consec_free.
Políticas comparadas (mismo presupuesto B=M·avg, avg=5, n_probe=3): CONSEC_V, CONSEC_FREE, ADAPT, y el
ORÁCULO-DE-POLÍTICA (best-of {V,FREE} por nivel de ruido, cota superior NO implementable, sólo referencia).
Barrido de vnoise, 4 seeds. La r estimada debe BAJAR monótona con vnoise.

PREDICCIÓN FALSABLE (pre-registrada):
  - APOYADA (NO-REGRET) si ADAPT (a) a verificador bueno (vnoise=0) >= CONSEC_V − 0.02 (no pierde el edge) Y
    (b) a ruido alto (vnoise=0.20) >= CONSEC_V + 0.02 (ESCAPA el colapso del verifier-dependiente), es decir
    ADAPT rastrea a la MEJOR de las dos en ambos extremos. Y la r estimada baja con el ruido (sanity de la
    calibración).
  - REFUTADA si ADAPT < min(CONSEC_V, CONSEC_FREE) en algún extremo (la mezcla es peor que cualquiera de las
    dos -> la estimación de fiabilidad no sirve) O r no baja con el ruido (no calibra).
  - MIXTA si rastrea a la mejor en un extremo pero no en el otro.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp029_adaptive_allocation.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp029_adaptive_allocation.run            # FULL
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
from cognia_x.experiments.exp026_ttc_allocation.run import sample_counts, largest_remainder, acc_sigma
from cognia_x.experiments.exp027_noisy_verifier_ttc.run import noisy_accept, commit_true_correct
from cognia_x.experiments.exp028_robust_control_signal.run import signal_weight, p_top

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")

POLICIES = ["consequence_v", "consequence_free", "adapt"]


def estimate_reliability(agreements):
    """r global SIN ground-truth por TEST-RETEST: agreements = lista de bool (las dos consultas del verificador
    sobre el mismo sample coincidieron). r = clip(2·P(coinciden) − 1, 0, 1). vnoise=0 -> r=1; vnoise=0.5 -> r=0."""
    if not agreements:
        return 0.0
    p_agree = sum(agreements) / len(agreements)
    return float(max(0.0, min(1.0, 2.0 * p_agree - 1.0)))


def run_policies(model, test, B, n_probe, vnoise, nrng, temperature, top_k, device):
    """Una pasada: probe -> estima r -> evalúa CONSEC_V, CONSEC_FREE, ADAPT (mismo probe y mismas asignaciones
    base). Devuelve (acc_dict, r_estimada, oracle_best). Commit verifier-based, accuracy REAL."""
    M = len(test)
    extra = max(0, B - M * n_probe)

    # PROBE compartido (mismas muestras para las 3 políticas -> aísla la ASIGNACIÓN)
    probes = []                      # por problema: (p, samples)
    w_v, w_free = [], []
    agreements = []                  # test-retest: las dos consultas del verificador coincidieron
    for (p, _, _) in test:
        s = sample_counts(model, p, n_probe, temperature, top_k, device)
        solved_obs = False
        for ans, tc in s:
            acc1 = noisy_accept(tc, vnoise, nrng)        # decisión "real" (la que usa solved_obs)
            acc2 = noisy_accept(tc, vnoise, nrng)        # re-consulta independiente -> mide consistencia
            solved_obs = solved_obs or acc1
            agreements.append(acc1 == acc2)
        probes.append((p, s))
        w_v.append(signal_weight("consequence_v", s, solved_obs))
        w_free.append(signal_weight("consequence_free", s, solved_obs))

    r = estimate_reliability(agreements)
    w_adapt = [r * a + (1.0 - r) * b for a, b in zip(w_v, w_free)]

    def eval_alloc(weights):
        alloc = largest_remainder(weights, extra)
        hits = 0
        for (p, ps), k in zip(probes, alloc):
            full = list(ps)
            if k > 0:
                full += sample_counts(model, p, k, temperature, top_k, device)
            tc, _ = commit_true_correct(full, vnoise, nrng)
            hits += int(tc)
        return hits / max(1, M)

    a_v = eval_alloc(w_v)
    a_free = eval_alloc(w_free)
    a_adapt = eval_alloc(w_adapt)
    return {"consequence_v": a_v, "consequence_free": a_free, "adapt": a_adapt}, r, max(a_v, a_free)


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
        nrng = np.random.default_rng(9000 + seed * 19 + int(round(vn * 1000)))
        accs, r, oracle = run_policies(base, test, B, args.n_probe, vn, nrng,
                                       args.temperature, args.top_k, "cpu")
        accs["greedy"] = greedy_acc
        accs["r_est"] = r
        accs["oracle_best"] = oracle
        by_noise[vn] = accs
        log(f"[exp029]   seed={seed} vnoise={vn}: CONSEC_V={accs['consequence_v']:.3f} "
            f"CONSEC_FREE={accs['consequence_free']:.3f} ADAPT={accs['adapt']:.3f} "
            f"(oracle={oracle:.3f} r_est={r:.2f} greedy={greedy_acc:.3f})")
    dt = time.time() - t0
    log(f"[exp029] seed={seed} greedy={greedy_acc:.3f} ({band}) {dt:.1f}s npar={npar}")
    return {"seed": seed, "greedy_acc": greedy_acc, "in_band": 0.20 <= greedy_acc <= 0.50,
            "M": M, "B": B, "npar": npar, "secs": round(dt, 2), "by_noise": by_noise}


def verdict(seeds_res, noises, margin):
    inb = [r for r in seeds_res if r["in_band"]]
    use = inb if inb else seeds_res
    M = use[0]["M"]
    lo, hi = noises[0], noises[-1]
    curve = {}
    for vn in noises:
        row = {m: float(np.mean([r["by_noise"][vn][m] for r in use])) for m in
               ["consequence_v", "consequence_free", "adapt", "oracle_best", "r_est", "greedy"]}
        curve[vn] = row
    sig = acc_sigma(curve[lo]["adapt"], M) / math.sqrt(len(use))
    keeps_edge = curve[lo]["adapt"] >= curve[lo]["consequence_v"] - margin            # (a) no pierde el edge
    escapes_collapse = curve[hi]["adapt"] >= curve[hi]["consequence_v"] + margin      # (b) escapa el colapso
    r_drops = curve[hi]["r_est"] < curve[lo]["r_est"] - 1e-6                          # calibración: r baja con ruido
    worst_regret = min(curve[vn]["adapt"] - min(curve[vn]["consequence_v"], curve[vn]["consequence_free"])
                       for vn in noises)
    if keeps_edge and escapes_collapse and r_drops:
        v = "APOYADA"
    elif worst_regret < -margin or not r_drops:
        v = "REFUTADA"
    else:
        v = "MIXTA"
    return v, {"lo": lo, "hi": hi, "curve": curve, "keeps_edge_at_lo": keeps_edge,
               "escapes_collapse_at_hi": escapes_collapse, "r_drops_with_noise": r_drops,
               "worst_regret_vs_min": worst_regret, "two_sigma": 2 * sig,
               "n_seeds_used": len(use), "n_in_band": len(inb)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=str, default="0,1,2,3")
    ap.add_argument("--M", type=int, default=120)
    ap.add_argument("--avg", type=int, default=5)
    ap.add_argument("--n_probe", type=int, default=3)
    ap.add_argument("--noises", type=str, default="0,0.1,0.2")
    ap.add_argument("--top_k", type=int, default=16)
    ap.add_argument("--temperature", type=float, default=1.0)
    ap.add_argument("--margin", type=float, default=0.02)
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

    log(f"[exp029] CYCLE 43 / H-V4-1h — política ADAPTATIVA (estima fiabilidad del verificador y mezcla)")
    log(f"[exp029] suma [{args.lo},{args.hi}] test={len(test)} avg={args.avg} n_probe={args.n_probe} "
        f"noises={noises} seeds={seeds}")

    res = [run_seed(s, args, test, train_pairs, noises, log) for s in seeds]
    v, stats = verdict(res, noises, args.margin)
    log(f"[exp029] VEREDICTO H-V4-1h: {v} | keeps_edge@{stats['lo']}={stats['keeps_edge_at_lo']} "
        f"escapes_collapse@{stats['hi']}={stats['escapes_collapse_at_hi']} r_drops={stats['r_drops_with_noise']} "
        f"worst_regret={stats['worst_regret_vs_min']:+.3f}")
    log(f"[exp029] CURVA vnoise->CONSEC_V/CONSEC_FREE/ADAPT/oracle(r_est): " +
        " | ".join("{}:{:.3f}/{:.3f}/{:.3f}/{:.3f}(r={:.2f})".format(
            vn, stats['curve'][vn]['consequence_v'], stats['curve'][vn]['consequence_free'],
            stats['curve'][vn]['adapt'], stats['curve'][vn]['oracle_best'],
            stats['curve'][vn]['r_est']) for vn in noises))

    out = {"exp": "exp029_adaptive_allocation", "cycle": 43, "hypothesis": "H-V4-1h",
           "claim": "una política adaptativa que estima la fiabilidad del verificador y mezcla control "
                    "verifier-dependiente/verifier-free logra no-regret (lo mejor de ambas) en todos los regímenes",
           "verdict": v, "stats": stats, "args": vars(args), "noises": noises, "seeds": res,
           "platform": {"python": platform.python_version(), "numpy": np.__version__, "torch": torch.__version__},
           "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    path = os.path.join(RESULTS, "results.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp029] escrito {path}")


if __name__ == "__main__":
    main()
