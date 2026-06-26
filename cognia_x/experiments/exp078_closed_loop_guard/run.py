r"""
exp078 — CYCLE 94 / H-V4-7j (rama R-VALOR, cierra la tensión de CYCLE 93; hija): en el LAZO CERRADO con el GENERADOR de
MODELO REAL bajo presupuesto, la asignación por CONFIANZA ENDÓGENA maximiza el YIELD (CYCLE 93) PERO COLAPSA la
diversidad (narrowing, CYCLE 49-50) → el downstream se gatea. ¿La GUARDIA dedup+replay (CYCLE 50) RESCATA el downstream
SIN perder el yield? => la RECETA COMPLETA: R-VALOR-allocation + guardia de diversidad.

CONTEXTO. CYCLE 93 (exp077) mostró: asignar la verificación escasa por confianza endógena rinde MUCHo más correctas por
verificación que al azar (yield +35, corr confianza-strong 0.59), pero el downstream real_acc del lazo REGRESIONA
(conf 0.40 < random 0.56) porque entrenar siempre lo de alta confianza NARROWING (CYCLE 49-50). El remedio conocido es la
GUARDIA de CYCLE 50: dedup de los verificados-correctos (no re-entrenar lo mismo) + replay de datos-semilla CLEAN (verdad
canónica) para sostener cobertura/diversidad. Esta hija lo combina.

DISEÑO (PyTorch CPU; reusa exp018/exp077). Igual lazo que exp077 (base débil + temp alta → pool con mix; presupuesto
B≪pool; asignación por confianza). Brazos (mismo base/RNG; mismo B): conf_alloc (greedy, baseline de 93), conf_alloc_guard
(greedy + dedup + replay), random_alloc, verify_all (techo). La GUARDIA sólo cambia la COMPOSICIÓN del entrenamiento
(dedup verificados + replay seed), NO la asignación. 4 seeds.

PREGUNTA FALSABLE:
  - APOYADA si la guardia RESCATA el downstream: real_acc guard > conf (+>margen, deshace el narrowing) Y guard >= random
    (la confianza-greedy se vuelve viable) MIENTRAS mantiene el yield (yield guard ≈ conf). => receta completa:
    allocation R-VALOR + guardia de diversidad.
  - REFUTADA si la guardia NO rescata (guard ≈ conf) o destruye el yield.
  - MIXTA si rescata parcialmente (mejora sobre conf pero no alcanza a random / cuesta yield).

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp078_closed_loop_guard.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp078_closed_loop_guard.run            # FULL
"""
import argparse
import copy
import json
import os
import platform
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
ARMS = ["conf_alloc", "conf_alloc_guard", "random_alloc", "verify_all"]


def _dedup(pairs):
    seen = set(); out = []
    for p, e in pairs:
        k = (bytes(p), bytes(e))
        if k not in seen:
            seen.add(k); out.append((p, e))
    return out


def _replay_examples(rng, train_targets, count):
    """Replay de la VERDAD CANÓNICA (CYCLE 50): (prompt, real_expression) para targets al azar = datos-semilla clean."""
    if count <= 0:
        return []
    sel = rng.integers(0, len(train_targets), size=count)
    return [(E.make_prompt(train_targets[i]), E.real_expression(rng, train_targets[i])) for i in sel]


def run_seed(seed, args, test_targets, train_targets, log):
    base, npar = build_base(seed, args.n_seed, args.base_steps, args.base_lr, args.warmup, args.batch, train_targets)
    bm = E.eval_metrics(base, test_targets, "cpu")
    log(f"[exp078] seed={seed} base real_acc={bm['real_acc']:.3f} weak={bm['weak_acc']:.3f} deg={bm['degenerate']:.3f} params={npar:,}")
    pool_rng = np.random.default_rng(seed + 7)
    sel = pool_rng.integers(0, len(train_targets), size=args.pool)
    pool_prompts = [E.make_prompt(train_targets[i]) for i in sel]
    M = args.pool * args.K
    B = max(1, int(round(args.budget_frac * M)))

    arms = {a: copy.deepcopy(base) for a in ARMS}
    hist = {a: {"real": [round(bm["real_acc"], 4)], "yield": [], "ntrain": []} for a in ARMS}
    corrs = []
    train_rng = np.random.default_rng(seed + 99)

    for r in range(1, args.rounds + 1):
        for a in ARMS:
            torch.manual_seed(10000 * seed + r)
            pool = generate_pool(arms[a], pool_prompts, args.K, args.temp, args.top_k, "cpu")
            pairs = [(p, e) for (p, e, _, _) in pool]
            strong = np.array([1.0 if s else 0.0 for (_, _, _, s) in pool])
            n = len(pool)
            rng_a = np.random.default_rng(seed * 131 + r * 17 + ARMS.index(a))
            if a == "verify_all":
                sel_idx = np.arange(n)
            elif a == "random_alloc":
                sel_idx = rng_a.choice(n, size=min(B, n), replace=False)
            else:  # conf_alloc y conf_alloc_guard: misma asignación por confianza
                conf = _confidence(arms[a], pairs, "cpu")
                if a == "conf_alloc" and r == 1:
                    corrs.append(round(_corr(conf, strong), 4))
                sel_idx = np.argsort(conf + 1e-9 * rng_a.random(n))[-min(B, n):]
            ex = [pairs[i] for i in sel_idx if strong[i] > 0.5]
            hist[a]["yield"].append(len(ex))
            # GUARDIA (sólo conf_alloc_guard): dedup de verificados + replay de verdad canónica
            if a == "conf_alloc_guard":
                ex = _dedup(ex)
                ex = ex + _replay_examples(train_rng, train_targets, int(round(args.replay_frac * max(1, len(ex)))))
            hist[a]["ntrain"].append(len(ex))
            if ex:
                train_arm(arms[a], ex, args.steps, args.batch, args.lr, "cpu", train_rng)
            mm = E.eval_metrics(arms[a], test_targets, "cpu")
            hist[a]["real"].append(round(mm["real_acc"], 4))
        log(f"[exp078] seed={seed} ronda {r} (B={B}/{M}): "
            + " | ".join(f"{a}: yield={hist[a]['yield'][-1]} ntr={hist[a]['ntrain'][-1]} real={hist[a]['real'][-1]:.3f}" for a in ARMS))

    return {"seed": seed, "base": bm, "params": npar, "hist": hist, "B": B, "M": M,
            "conf_strong_corr": (corrs[0] if corrs else 0.0)}


def build_summary(per_seed):
    def my(a):
        return [sum(s["hist"][a]["yield"]) / len(s["hist"][a]["yield"]) for s in per_seed]

    def mr(a):
        return [sum(s["hist"][a]["real"][1:]) / len(s["hist"][a]["real"][1:]) for s in per_seed]

    yc, yg, yn, yva = my("conf_alloc"), my("conf_alloc_guard"), my("random_alloc"), my("verify_all")
    rc, rg, rn, rva = mr("conf_alloc"), mr("conf_alloc_guard"), mr("random_alloc"), mr("verify_all")
    nseed = len(per_seed)

    def mean(xs):
        return float(np.mean(xs))

    guard_rescue = round(mean(rg) - mean(rc), 4)              # >0: la guardia deshace el narrowing
    guard_vs_random = round(mean(rg) - mean(rn), 4)          # >=0: la confianza-greedy+guardia se vuelve viable
    guard_keeps_yield = round(mean(yg) - mean(yc), 4)        # ~0: la guardia no destruye el yield (misma asignación)
    margin = 0.03

    rescues = guard_rescue > margin
    viable = guard_vs_random >= -margin
    keeps_yield = mean(yg) >= mean(yc) - max(2.0, 0.15 * mean(yc))

    if rescues and viable and keeps_yield:
        status = "apoyada"
        verdict = ("H-V4-7j APOYADA: la GUARDIA dedup+replay (CYCLE 50) RESCATA el downstream de la asignación "
                   "confidence-greedy SIN perder el yield. real_acc guard={rg:.3f} > conf={rc:.3f} (+{gr}, deshace el "
                   "narrowing de CYCLE 93) Y >= random={rn:.3f} ({gvr}); el yield se mantiene (guard={yg:.1f} vs "
                   "conf={yc:.1f}, Δ={gky}). verify_all techo={rva:.3f}. => RECETA COMPLETA del lazo de auto-mejora bajo "
                   "presupuesto: R-VALOR-allocation (confianza endógena, alto yield) + guardia de diversidad "
                   "(dedup+replay) -> alto yield Y downstream sano. Cierra la tensión allocation↔diversidad de "
                   "CYCLE 93.").format(rg=mean(rg), rc=mean(rc), gr=_f(guard_rescue), rn=mean(rn), gvr=_f(guard_vs_random),
                                       yg=mean(yg), yc=mean(yc), gky=_f(guard_keeps_yield), rva=mean(rva))
    elif not rescues:
        status = "refutada"
        verdict = ("H-V4-7j REFUTADA: la guardia NO rescata el downstream (guard={rg:.3f} vs conf={rc:.3f}, "
                   "+{gr} <= {m}) -> dedup+replay no deshace el narrowing en este lazo.").format(
                       rg=mean(rg), rc=mean(rc), gr=_f(guard_rescue), m=margin)
    else:
        status = "mixta"
        verdict = ("H-V4-7j MIXTA: la guardia rescata PARCIALMENTE (guard={rg:.3f} > conf={rc:.3f}, +{gr}) pero "
                   "guard_vs_random={gvr} (viable={v}) / keeps_yield={ky} (guard yield={yg:.1f} vs conf={yc:.1f}).").format(
                       rg=mean(rg), rc=mean(rc), gr=_f(guard_rescue), gvr=_f(guard_vs_random), v=viable, ky=keeps_yield,
                       yg=mean(yg), yc=mean(yc))

    return {"arms": ARMS, "n_seeds": nseed, "B": per_seed[0]["B"], "M": per_seed[0]["M"],
            "conf_strong_corr_by_seed": [s["conf_strong_corr"] for s in per_seed],
            "yield_conf": [round(x, 2) for x in yc], "yield_guard": [round(x, 2) for x in yg],
            "yield_random": [round(x, 2) for x in yn], "yield_verify_all": [round(x, 2) for x in yva],
            "real_conf": [round(x, 3) for x in rc], "real_guard": [round(x, 3) for x in rg],
            "real_random": [round(x, 3) for x in rn], "real_verify_all": [round(x, 3) for x in rva],
            "guard_rescue": guard_rescue, "guard_vs_random": guard_vs_random, "guard_keeps_yield": guard_keeps_yield,
            "rescues": bool(rescues), "viable": bool(viable), "keeps_yield": bool(keeps_yield),
            "status": status, "verdict": verdict}


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
    ap.add_argument("--replay_frac", type=float, default=0.5)
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

    log(f"[exp078] CYCLE 94 / H-V4-7j — guardia dedup+replay rescata el downstream de la asignación R-VALOR (cierra tensión de CYCLE 93)")
    log(f"[exp078] seeds={seeds} rango=[{LO},{HI}] train={len(train_targets)} test={len(test_targets)} rounds={args.rounds} "
        f"K={args.K} pool={args.pool} budget_frac={args.budget_frac} temp={args.temp} replay_frac={args.replay_frac} steps={args.steps} base_steps={args.base_steps}")

    per_seed = [run_seed(s, args, test_targets, train_targets, log) for s in seeds]
    sm = build_summary(per_seed)

    log(f"[exp078] corr(confianza,strong)={sm['conf_strong_corr_by_seed']}")
    log(f"[exp078] YIELD/ronda (B={sm['B']}/{sm['M']}): conf={sm['yield_conf']} guard={sm['yield_guard']} random={sm['yield_random']} verify_all={sm['yield_verify_all']}")
    log(f"[exp078] real_acc media-rondas: conf={sm['real_conf']} guard={sm['real_guard']} random={sm['real_random']} verify_all={sm['real_verify_all']}")
    log(f"[exp078] guard_rescue=+{sm['guard_rescue']:.3f} | guard_vs_random={sm['guard_vs_random']:+.3f} | guard_keeps_yield={sm['guard_keeps_yield']:+.2f}")
    log(f"[exp078] VEREDICTO H-V4-7j: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp078_closed_loop_guard", "cycle": 94, "hypothesis": "H-V4-7j",
           "claim": "la guardia dedup+replay (CYCLE 50) rescata el downstream de la asignacion confidence-greedy en el "
                    "lazo cerrado real sin perder el yield: receta completa = R-VALOR-allocation + guardia de diversidad",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__, "torch": torch.__version__},
           "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp078] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
