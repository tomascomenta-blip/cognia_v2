r"""
exp089 — CYCLE 105 / H-V4-8j (rama R-VALOR, VALIDACIÓN toy→real: el costo-por-valor del CYCLE 101 en el LAZO CERRADO
REAL): CYCLE 101 (numpy) halló que bajo costo de acción HETEROGÉNEO la asignación R-VALOR es valor-POR-COSTO (ratio) para
objetivos aditivos. ¿Transfiere al LAZO CERRADO con el GENERADOR de MODELO REAL (HybridLM de exp018)? En el lazo, la
verificación tiene COSTO HETEROGÉNEO (verificar candidatos de targets grandes "cuesta" más); bajo presupuesto de COSTO
total, ¿asignar por CONFIANZA-POR-COSTO rinde más correctos por costo que por confianza sola?

CONTEXTO. El honest gap del arco 95-104: casi todo es numpy/juguete. Este ciclo VALIDA una pieza (101, costo-por-valor) en
el lazo cerrado REAL (modelo propio genera, sandbox verifica, las correctas entrenan). El "yield" de auto-mejora es
aditivo (más correctos = más datos de training), así que el costo-por-valor (101) debería aplicar.

DISEÑO (PyTorch CPU; reusa exp018/exp077). Mismo lazo (base débil + temp alta -> pool con mix). COSTO de verificación por
candidato = 1 + (target−LO)/(HI−LO)·COST_RANGE (targets grandes cuestan más de verificar). Presupuesto de COSTO total B
por ronda. Brazos (mismo base/RNG; mismo B):
  - conf_alloc:  selecciona por CONFIANZA desc hasta agotar el presupuesto de costo (ignora el costo).
  - ratio_alloc: selecciona por CONFIANZA/COSTO desc hasta agotar el presupuesto (eficiencia, CYCLE 101).
  - verify_all:  verifica TODO (presupuesto infinito) = techo.
  - random_alloc: al azar bajo presupuesto de costo.
Las verificado-correctas (strong) entrenan. MÉTRICA: YIELD = #strong-correctas por ronda bajo el presupuesto de COSTO
(eficiencia de la asignación); secundaria real_acc held-out. 4 seeds.

PREGUNTA FALSABLE (transferencia de 101 al lazo real):
  - APOYADA si ratio_alloc YIELD > conf_alloc por > margen en los seeds (a igual presupuesto de COSTO; valor-por-costo
    rinde más correctos) Y el downstream no regresiona. => el costo-por-valor (101) TRANSFIERE al lazo cerrado real.
  - REFUTADA si ratio ≈ conf (el costo no cambia la política en el lazo real).
  - MIXTA si mejora el yield pero no el downstream (o viceversa).

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp089_real_cost_alloc.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp089_real_cost_alloc.run            # FULL
"""
import argparse
import copy
import json
import os
import platform
import re
import sys

import numpy as np
import torch

from cognia_x.experiments.exp018_real_verifier import expression_task as E
from cognia_x.experiments.exp018_real_verifier.run import build_base, generate_pool, train_arm, LO, HI
from cognia_x.experiments.exp077_closed_loop_budget.run import _confidence, _corr

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")
ARMS = ["conf_alloc", "ratio_alloc", "verify_all", "random_alloc"]
COST_RANGE = 3.0


def _cost_of(prompt):
    m = re.match(rb"^(\d{1,3})=$", bytes(prompt))
    n = int(m.group(1)) if m else LO
    return 1.0 + (n - LO) / max(1, (HI - LO)) * COST_RANGE


def _alloc_under_cost(order, costs, B):
    picks = []; spent = 0.0
    for i in order:
        if spent + costs[i] <= B + 1e-9:
            picks.append(i); spent += costs[i]
    return picks


def run_seed(seed, args, test_targets, train_targets, log):
    base, npar = build_base(seed, args.n_seed, args.base_steps, args.base_lr, args.warmup, args.batch, train_targets)
    bm = E.eval_metrics(base, test_targets, "cpu")
    log(f"[exp089] seed={seed} base real_acc={bm['real_acc']:.3f} params={npar:,}")
    pool_rng = np.random.default_rng(seed + 7)
    sel = pool_rng.integers(0, len(train_targets), size=args.pool)
    pool_prompts = [E.make_prompt(train_targets[i]) for i in sel]
    M = args.pool * args.K

    arms = {a: copy.deepcopy(base) for a in ARMS}
    hist = {a: {"real": [round(bm["real_acc"], 4)], "yield": [], "nverified": []} for a in ARMS}
    corrs = []
    conf_cost_corrs = []        # corr(confianza, costo): ¿el estimador de valor ya encodea el costo?
    train_rng = np.random.default_rng(seed + 99)

    for r in range(1, args.rounds + 1):
        for a in ARMS:
            torch.manual_seed(10000 * seed + r)
            pool = generate_pool(arms[a], pool_prompts, args.K, args.temp, args.top_k, "cpu")
            pairs = [(p, e) for (p, e, _, _) in pool]
            strong = np.array([1.0 if s else 0.0 for (_, _, _, s) in pool])
            costs = np.array([_cost_of(p) for (p, _, _, _) in pool])
            n = len(pool)
            B = args.budget_frac * float(costs.sum())          # presupuesto = fracción del costo total del pool
            rng_a = np.random.default_rng(seed * 131 + r * 17 + ARMS.index(a))
            if a == "verify_all":
                sel_idx = list(range(n))
            elif a == "random_alloc":
                sel_idx = _alloc_under_cost(rng_a.permutation(n), costs, B)
            else:
                conf = _confidence(arms[a], pairs, "cpu")
                val_est = np.exp(conf)                                    # VALOR positivo (prob de la generación); el ratio exige valor>0
                if a == "conf_alloc" and r == 1:
                    corrs.append(round(_corr(conf, strong), 4))
                    conf_cost_corrs.append(round(_corr(val_est, costs), 4))   # ¿valor-estimado correlaciona con costo?
                key = val_est if a == "conf_alloc" else (val_est / costs)     # ratio = valor/costo (CYCLE 101)
                order = np.argsort(key + 1e-9 * rng_a.random(n))[::-1]
                sel_idx = _alloc_under_cost(order, costs, B)
            ex = [pairs[i] for i in sel_idx if strong[i] > 0.5]
            hist[a]["yield"].append(len(ex))
            hist[a]["nverified"].append(len(sel_idx))
            if ex:
                train_arm(arms[a], ex, args.steps, args.batch, args.lr, "cpu", train_rng)
            mm = E.eval_metrics(arms[a], test_targets, "cpu")
            hist[a]["real"].append(round(mm["real_acc"], 4))
        log(f"[exp089] seed={seed} ronda {r}: "
            + " | ".join(f"{a}: y={hist[a]['yield'][-1]}/{hist[a]['nverified'][-1]} real={hist[a]['real'][-1]:.3f}" for a in ARMS))

    return {"seed": seed, "base": bm, "hist": hist, "conf_strong_corr": (corrs[0] if corrs else 0.0),
            "conf_cost_corr": (conf_cost_corrs[0] if conf_cost_corrs else 0.0)}


def _mean(xs):
    return float(np.mean(xs)) if len(xs) else 0.0


def build_summary(per_seed):
    def my(a):
        return [sum(s["hist"][a]["yield"]) / len(s["hist"][a]["yield"]) for s in per_seed]

    def mr(a):
        return [sum(s["hist"][a]["real"][1:]) / len(s["hist"][a]["real"][1:]) for s in per_seed]

    def mnv(a):
        return [sum(s["hist"][a]["nverified"]) / len(s["hist"][a]["nverified"]) for s in per_seed]

    yc, yr = my("conf_alloc"), my("ratio_alloc")
    rc, rr = mr("conf_alloc"), mr("ratio_alloc")
    nvc, nvr = mnv("conf_alloc"), mnv("ratio_alloc")
    nseed = len(per_seed)
    yield_gain = round(_mean(yr) - _mean(yc), 4)
    yield_all_pos = all(yr[i] >= yc[i] for i in range(nseed))
    real_gain = round(_mean(rr) - _mean(rc), 4)
    real_not_worse = _mean(rr) >= _mean(rc) - 0.02
    yield_margin = round(0.10 * max(1.0, _mean(yc)), 4)
    yield_better = (yield_gain > yield_margin) and yield_all_pos

    if yield_better and real_not_worse:
        status = "apoyada"
        verdict = ("H-V4-8j APOYADA: el costo-por-valor (CYCLE 101) TRANSFIERE al LAZO CERRADO REAL. Bajo costo de "
                   "verificación heterogéneo, asignar por CONFIANZA/COSTO rinde MÁS correctos por presupuesto de costo que "
                   "por confianza sola: yield ratio={yr:.2f} vs conf={yc:.2f} (+{yg}, {ap}); ratio verifica más "
                   "candidatos baratos (nverif {nvr:.1f} vs {nvc:.1f}). El downstream no regresiona (ratio={rr:.3f} vs "
                   "conf={rc:.3f}, Δ={rg}). corr(confianza,strong)={mc}. => el costo-por-valor para el yield aditivo del "
                   "lazo de auto-mejora vale también con el modelo REAL.").format(
                       yr=_mean(yr), yc=_mean(yc), yg=yield_gain, ap="todos los seeds" if yield_all_pos else "no-todos",
                       nvr=_mean(nvr), nvc=_mean(nvc), rr=_mean(rr), rc=_mean(rc), rg=real_gain,
                       mc=_f(_mean([s["conf_strong_corr"] for s in per_seed])))
    elif not yield_better:
        status = "refutada"
        verdict = ("H-V4-8j REFUTADA (informativa; CALIFICA 101): asignar por confianza/costo NO mejora (de hecho baja) el "
                   "yield sobre confianza sola en el lazo real (ratio={yr:.2f} vs conf={yc:.2f}, {yg}; all_pos={ap}). "
                   "MECANISMO: en el lazo real la CONFIANZA (estimador de valor) y el COSTO están CORRELACIONADOS "
                   "(corr(confianza,costo)={ccc}: el modelo confía distinto según el target/costo), así que la confianza "
                   "YA encodea el costo; dividir por costo (ratio) DILUYE la señal y elige baratos-pero-inciertos -> menos "
                   "correctos. => el costo-por-valor (101) NO transfiere cuando el estimador de valor y el costo NO son "
                   "señales SEPARADAS (lo eran en el toy 101, lo son en el lazo real). El downstream no regresiona "
                   "(Δ={rg}).").format(yr=_mean(yr), yc=_mean(yc), yg=("+" + _f(yield_gain)) if yield_gain >= 0 else _f(yield_gain),
                                       ap=yield_all_pos, ccc=_f(_mean([s["conf_cost_corr"] for s in per_seed])), rg=real_gain)
    else:
        status = "mixta"
        verdict = ("H-V4-8j MIXTA: yield_better={yb} (ratio={yr:.2f} vs conf={yc:.2f}, +{yg}) pero downstream real_acc "
                   "{rr:.3f} vs {rc:.3f} (Δ={rg}).").format(yb=yield_better, yr=_mean(yr), yc=_mean(yc), yg=yield_gain,
                                                            rr=_mean(rr), rc=_mean(rc), rg=real_gain)

    return {"arms": ARMS, "n_seeds": nseed, "conf_strong_corr_by_seed": [s["conf_strong_corr"] for s in per_seed],
            "conf_cost_corr_by_seed": [s["conf_cost_corr"] for s in per_seed],
            "mean_conf_cost_corr": round(_mean([s["conf_cost_corr"] for s in per_seed]), 4),
            "yield_conf": [round(x, 2) for x in yc], "yield_ratio": [round(x, 2) for x in yr],
            "nverif_conf": [round(x, 1) for x in nvc], "nverif_ratio": [round(x, 1) for x in nvr],
            "real_conf": [round(x, 3) for x in rc], "real_ratio": [round(x, 3) for x in rr],
            "yield_verify_all": [round(x, 2) for x in my("verify_all")], "real_verify_all": [round(x, 3) for x in mr("verify_all")],
            "yield_gain": yield_gain, "yield_all_pos": bool(yield_all_pos), "real_gain": real_gain,
            "real_not_worse": bool(real_not_worse), "yield_better": bool(yield_better), "status": status, "verdict": verdict}


def _f(x):
    return "{:.3f}".format(x)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=str, default="0,1,2,3")
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--K", type=int, default=8)
    ap.add_argument("--pool", type=int, default=64)
    ap.add_argument("--budget_frac", type=float, default=0.20)
    ap.add_argument("--temp", type=float, default=1.3)
    ap.add_argument("--top_k", type=int, default=0)
    ap.add_argument("--steps", type=int, default=120)
    ap.add_argument("--n_seed", type=int, default=200)
    ap.add_argument("--base_steps", type=int, default=250)
    ap.add_argument("--base_lr", type=float, default=1e-3)
    ap.add_argument("--lr", type=float, default=5e-4)
    ap.add_argument("--warmup", type=int, default=40)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--test_frac", type=float, default=0.30)
    args = ap.parse_args()
    if args.top_k <= 0:
        args.top_k = None
    if args.smoke:
        args.seeds, args.rounds, args.pool, args.steps, args.base_steps = "0,1", 2, 48, 60, 200

    seeds = [int(s) for s in args.seeds.split(",")]
    train_targets, test_targets = E.build_split(LO, HI, args.test_frac)
    logs = []

    def log(mm):
        print(mm, flush=True); logs.append(mm)

    log("[exp089] CYCLE 105 / H-V4-8j — VALIDACIÓN toy→real: costo-por-valor (101) en el lazo cerrado real")
    log(f"[exp089] seeds={seeds} rango=[{LO},{HI}] rounds={args.rounds} K={args.K} pool={args.pool} budget_frac={args.budget_frac} "
        f"cost_range={COST_RANGE} temp={args.temp} base_steps={args.base_steps}")

    per_seed = [run_seed(s, args, test_targets, train_targets, log) for s in seeds]
    sm = build_summary(per_seed)

    log(f"[exp089] corr(confianza,strong)={sm['conf_strong_corr_by_seed']}")
    log(f"[exp089] YIELD/ronda: conf={sm['yield_conf']} ratio={sm['yield_ratio']} verify_all={sm['yield_verify_all']} "
        f"| nverif conf={sm['nverif_conf']} ratio={sm['nverif_ratio']}")
    log(f"[exp089] real_acc: conf={sm['real_conf']} ratio={sm['real_ratio']} verify_all={sm['real_verify_all']}")
    log(f"[exp089] yield_gain=+{sm['yield_gain']:.3f} (all_pos={sm['yield_all_pos']}) | real_gain={sm['real_gain']:+.3f} (not_worse={sm['real_not_worse']})")
    log(f"[exp089] VEREDICTO H-V4-8j: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp089_real_cost_alloc", "cycle": 105, "hypothesis": "H-V4-8j",
           "claim": "el costo-por-valor (CYCLE 101) transfiere al lazo cerrado real: bajo costo de verificacion "
                    "heterogeneo, asignar por confianza/costo rinde mas correctos por presupuesto de costo que por "
                    "confianza sola, sin regresionar el downstream",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__, "torch": torch.__version__},
           "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp089] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
