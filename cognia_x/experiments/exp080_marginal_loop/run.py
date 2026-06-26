r"""
exp080 — CYCLE 96 / H-V4-8b (rama R-VALOR, sintetiza CYCLE 94 + 95; versión PRINCIPISTA del lazo): en el LAZO CERRADO con
el MODELO REAL bajo presupuesto, la selección por CONFIANZA absoluta (top-B) COLAPSA la diversidad (CYCLE 93); la guardia
dedup+replay la rescata (CYCLE 94) pero con un CRUTCH (replay de verdad canónica clean). CYCLE 95 mostró que el valor
debe ser MARGINAL bajo cobertura. APLICADO al lazo: seleccionar qué verificar por CONFIANZA + COBERTURA de los TARGETS
(selección MARGINAL: cubrir targets distintos en vez de re-verificar los mismos) ¿da downstream sano SIN el crutch del
replay, manteniendo el yield? => la selección marginal (submodular) SUBSUME a la guardia.

CONTEXTO. CYCLE 93 (exp077): confianza-greedy maximiza yield pero narrowing → downstream regresiona. CYCLE 94 (exp078):
la guardia dedup+replay rescata el downstream PERO parte del rescate es el REPLAY de verdad canónica (caveat honesto).
CYCLE 95 (exp079): bajo objetivo de cobertura el valor es MARGINAL, no absoluto. Aquí la diversidad del lazo = cobertura
de TARGETS (cada candidato responde un target N; entrenar sobre targets diversos cubre mejor el test held-out).

DISEÑO (PyTorch CPU; reusa exp018/exp077/exp078). Igual lazo (base débil + temp alta; presupuesto B≪pool). Brazos:
  - conf_alloc:       top-B por confianza (baseline de 93, narrowing).
  - marginal_alloc:   selección MARGINAL = cobertura de targets (ronda-robin: el mejor-confianza de cada target no-cubierto
                      primero, luego el 2º mejor, etc.) -> diversifica los targets verificados/entrenados. SIN replay clean.
  - conf_alloc_guard: confianza-greedy + dedup + replay (la receta de 94, referencia).
  - verify_all:       techo (B=M).
MÉTRICA: YIELD (#strong-correctas/ronda con B) + real_acc held-out. 4 seeds.

PREGUNTA FALSABLE:
  - APOYADA si marginal_alloc RESCATA el downstream sobre conf_alloc (+>0.05) SIN el crutch del replay clean, alcanzando
    ≈ conf_alloc_guard (>= guard − 0.03) y manteniendo el yield (≈ conf). => la selección MARGINAL (cobertura) subsume a
    la guardia dedup+replay; el valor marginal es el principio correcto también en el lazo real.
  - REFUTADA si marginal_alloc ≈ conf_alloc (la cobertura de targets no rescata) o destruye el yield.
  - MIXTA si rescata parcial / no alcanza a la guardia.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp080_marginal_loop.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp080_marginal_loop.run            # FULL
"""
import argparse
import copy
import json
import os
import platform
import sys
from collections import defaultdict

import numpy as np
import torch

from cognia_x.experiments.exp018_real_verifier import expression_task as E
from cognia_x.experiments.exp018_real_verifier.run import build_base, generate_pool, train_arm, LO, HI
from cognia_x.experiments.exp077_closed_loop_budget.run import _confidence, _corr
from cognia_x.experiments.exp078_closed_loop_guard.run import _dedup, _replay_examples

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")
ARMS = ["conf_alloc", "marginal_alloc", "conf_alloc_guard", "verify_all"]


def _marginal_alloc(conf, prompts, B):
    """Selección MARGINAL = cobertura de TARGETS: agrupa por prompt, ordena cada grupo por confianza desc, y toma en
    ronda-robin (cubrir todos los targets con su mejor, luego el 2º mejor, ...). Maximiza la cobertura de targets a
    presupuesto B (submodular)."""
    by_t = defaultdict(list)
    for i, p in enumerate(prompts):
        by_t[bytes(p)].append(i)
    for t in by_t:
        by_t[t].sort(key=lambda i: -conf[i])
    keys = list(by_t.keys())
    picks, depth = [], 0
    while len(picks) < B:
        added = False
        for t in keys:
            if depth < len(by_t[t]):
                picks.append(by_t[t][depth]); added = True
                if len(picks) >= B:
                    break
        if not added:
            break
        depth += 1
    return picks[:B]


def run_seed(seed, args, test_targets, train_targets, log):
    base, npar = build_base(seed, args.n_seed, args.base_steps, args.base_lr, args.warmup, args.batch, train_targets)
    bm = E.eval_metrics(base, test_targets, "cpu")
    log(f"[exp080] seed={seed} base real_acc={bm['real_acc']:.3f} params={npar:,}")
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
            prompts = [p for (p, _, _, _) in pool]
            strong = np.array([1.0 if s else 0.0 for (_, _, _, s) in pool])
            n = len(pool)
            rng_a = np.random.default_rng(seed * 131 + r * 17 + ARMS.index(a))
            if a == "verify_all":
                sel_idx = list(range(n))
            else:
                conf = _confidence(arms[a], pairs, "cpu")
                if a == "conf_alloc" and r == 1:
                    corrs.append(round(_corr(conf, strong), 4))
                if a == "marginal_alloc":
                    sel_idx = _marginal_alloc(conf, prompts, B)
                else:  # conf_alloc y conf_alloc_guard: top-B por confianza
                    sel_idx = list(np.argsort(conf + 1e-9 * rng_a.random(n))[-min(B, n):])
            ex = [pairs[i] for i in sel_idx if strong[i] > 0.5]
            hist[a]["yield"].append(len(ex))
            if a == "conf_alloc_guard":
                ex = _dedup(ex)
                ex = ex + _replay_examples(train_rng, train_targets, int(round(args.replay_frac * max(1, len(ex)))))
            elif a == "marginal_alloc":
                ex = _dedup(ex)                      # marginal: SÓLO dedup (sin replay clean) -> sin crutch
            hist[a]["ntrain"].append(len(ex))
            if ex:
                train_arm(arms[a], ex, args.steps, args.batch, args.lr, "cpu", train_rng)
            mm = E.eval_metrics(arms[a], test_targets, "cpu")
            hist[a]["real"].append(round(mm["real_acc"], 4))
        log(f"[exp080] seed={seed} ronda {r} (B={B}/{M}): "
            + " | ".join(f"{a}: y={hist[a]['yield'][-1]} ntr={hist[a]['ntrain'][-1]} real={hist[a]['real'][-1]:.3f}" for a in ARMS))

    return {"seed": seed, "base": bm, "hist": hist, "B": B, "M": M, "conf_strong_corr": (corrs[0] if corrs else 0.0)}


def _mean(xs):
    return float(np.mean(xs)) if len(xs) else 0.0


def build_summary(per_seed):
    def my(a):
        return [sum(s["hist"][a]["yield"]) / len(s["hist"][a]["yield"]) for s in per_seed]

    def mr(a):
        return [sum(s["hist"][a]["real"][1:]) / len(s["hist"][a]["real"][1:]) for s in per_seed]

    yc, ym, yg, yva = my("conf_alloc"), my("marginal_alloc"), my("conf_alloc_guard"), my("verify_all")
    rc, rm, rg, rva = mr("conf_alloc"), mr("marginal_alloc"), mr("conf_alloc_guard"), mr("verify_all")

    rescue = round(_mean(rm) - _mean(rc), 4)               # >0: la selección marginal rescata el downstream
    vs_guard = round(_mean(rm) - _mean(rg), 4)            # >=~0: alcanza a la guardia (sin crutch de replay clean)
    keeps_yield = round(_mean(ym) - _mean(yc), 4)         # ~0/+: mantiene el yield
    margin = 0.03

    rescues = rescue > 0.05
    subsumes_guard = vs_guard >= -margin
    yield_ok = _mean(ym) >= _mean(yc) - max(2.0, 0.15 * _mean(yc))

    if rescues and subsumes_guard and yield_ok:
        status = "apoyada"
        verdict = ("H-V4-8b APOYADA: la selección MARGINAL (cobertura de targets) SUBSUME a la guardia dedup+replay SIN "
                   "el crutch del replay clean. real_acc marginal={rm:.3f} > conf={rc:.3f} (+{re}, rescata el narrowing) "
                   "Y ≈ guard={rg:.3f} ({vg}); el yield se mantiene (marginal={ym:.1f} vs conf={yc:.1f}, Δ={ky}). "
                   "verify_all techo={rva:.3f}. => el valor MARGINAL (CYCLE 95) es el principio correcto también EN el "
                   "lazo cerrado real: diversificar QUÉ se verifica (cobertura) rescata la diversidad del entrenamiento "
                   "sin inyectar datos clean externos. La guardia de 94 era una aproximación; la cobertura marginal es "
                   "la versión principista.").format(rm=_mean(rm), rc=_mean(rc), re=_f(rescue), rg=_mean(rg),
                                                     vg=_f(vs_guard), ym=_mean(ym), yc=_mean(yc), ky=_f(keeps_yield), rva=_mean(rva))
    elif not rescues:
        status = "refutada"
        verdict = ("H-V4-8b REFUTADA: la cobertura de targets NO rescata el downstream (marginal={rm:.3f} vs conf={rc:.3f}"
                   ", +{re} <= 0.05) -> diversificar los targets verificados no basta en este lazo.").format(
                       rm=_mean(rm), rc=_mean(rc), re=_f(rescue))
    else:
        status = "mixta"
        verdict = ("H-V4-8b MIXTA: rescues={rs} (+{re}) subsumes_guard={sg} (vs_guard={vg}) yield_ok={yk} "
                   "(marginal={ym:.1f} vs conf={yc:.1f}).").format(rs=rescues, re=_f(rescue), sg=subsumes_guard,
                                                                   vg=_f(vs_guard), yk=yield_ok, ym=_mean(ym), yc=_mean(yc))

    return {"arms": ARMS, "n_seeds": len(per_seed), "B": per_seed[0]["B"], "M": per_seed[0]["M"],
            "conf_strong_corr_by_seed": [s["conf_strong_corr"] for s in per_seed],
            "yield_conf": [round(x, 2) for x in yc], "yield_marginal": [round(x, 2) for x in ym],
            "yield_guard": [round(x, 2) for x in yg], "yield_verify_all": [round(x, 2) for x in yva],
            "real_conf": [round(x, 3) for x in rc], "real_marginal": [round(x, 3) for x in rm],
            "real_guard": [round(x, 3) for x in rg], "real_verify_all": [round(x, 3) for x in rva],
            "rescue": rescue, "vs_guard": vs_guard, "keeps_yield": keeps_yield,
            "rescues": bool(rescues), "subsumes_guard": bool(subsumes_guard), "yield_ok": bool(yield_ok),
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

    log(f"[exp080] CYCLE 96 / H-V4-8b — selección MARGINAL (cobertura de targets) vs guardia dedup+replay en el lazo cerrado real")
    log(f"[exp080] seeds={seeds} rango=[{LO},{HI}] train={len(train_targets)} test={len(test_targets)} rounds={args.rounds} "
        f"K={args.K} pool={args.pool} budget_frac={args.budget_frac} temp={args.temp} steps={args.steps} base_steps={args.base_steps}")

    per_seed = [run_seed(s, args, test_targets, train_targets, log) for s in seeds]
    sm = build_summary(per_seed)

    log(f"[exp080] corr(confianza,strong)={sm['conf_strong_corr_by_seed']}")
    log(f"[exp080] YIELD/ronda (B={sm['B']}/{sm['M']}): conf={sm['yield_conf']} marginal={sm['yield_marginal']} guard={sm['yield_guard']} verify_all={sm['yield_verify_all']}")
    log(f"[exp080] real_acc media-rondas: conf={sm['real_conf']} marginal={sm['real_marginal']} guard={sm['real_guard']} verify_all={sm['real_verify_all']}")
    log(f"[exp080] rescue=+{sm['rescue']:.3f} | vs_guard={sm['vs_guard']:+.3f} | keeps_yield={sm['keeps_yield']:+.2f}")
    log(f"[exp080] VEREDICTO H-V4-8b: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp080_marginal_loop", "cycle": 96, "hypothesis": "H-V4-8b",
           "claim": "en el lazo cerrado real, la seleccion MARGINAL (cobertura de targets) subsume a la guardia "
                    "dedup+replay sin el crutch del replay clean: rescata el downstream sobre confianza-greedy y alcanza "
                    "a la guardia manteniendo el yield -> el valor marginal (CYCLE 95) es el principio correcto en el lazo",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__, "torch": torch.__version__},
           "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp080] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
