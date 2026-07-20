r"""
exp099 — CYCLE 115 / H-V4-8t (rama R-VALOR, STRESS-TEST de la asunción más load-bearing del arco): toda la validación real
(93/105/107/110) descansa en que la CONFIANZA endógena es buena señal de valor (corr~0.6 con la corrección). PERO en un
lazo de auto-mejora el modelo entrena sobre sus PROPIAS salidas filtradas -> riesgo de SOBRECONFIANZA: que la
corr(confianza, corrección) DEGRADE ronda a ronda y el lazo se AUTO-SOCAVE. ¿El lazo de confianza-asignación es
AUTO-SOSTENIDO o se auto-socava? ¿La guardia (CYCLE 94: replay de verdad canónica) mantiene la confianza honesta?

CONTEXTO. Es la pregunta adversarial sobre el fundamento del arco: si la señal de valor (confianza) colapsa al entrenar
sobre sí misma, toda la asignación R-VALOR del lazo real se degrada. Test de robustez del fundamento.

DISEÑO (PyTorch CPU; reusa exp018/exp077/exp078). Lazo cerrado real. Cada ronda se MIDE corr(confianza, strong) sobre el
pool generado (calidad de la señal de valor ESE round). Brazos:
  - conf_plain:  conf-alloc SIN guardia (entrena sobre sus verificado-correctas).
  - conf_guard:  conf-alloc + GUARDIA (dedup + replay de verdad canónica, CYCLE 94).
MÉTRICA: TENDENCIA de corr(conf,strong) sobre las rondas (últimas − primeras) por brazo + real_acc.

PREGUNTA FALSABLE:
  - APOYADA si conf_plain DEGRADA la corr (tendencia < −margen: sobreconfianza/colapso de la señal) MIENTRAS conf_guard la
    mantiene estable o mejor (tendencia_guard − tendencia_plain > margen). => el lazo de confianza-asignación NO es
    auto-sostenido por sí solo (la señal de valor se erosiona al entrenar sobre sí misma) y la guardia (replay de verdad
    canónica) es lo que lo mantiene honesto. Stress-test que IDENTIFICA una dependencia crítica del arco.
  - REFUTADA si conf_plain NO degrada (la corr se mantiene sin guardia) -> el lazo es auto-sostenido; la asunción del arco
    es robusta sin corrector.
  - MIXTA en otro caso.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp099_confidence_drift.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp099_confidence_drift.run            # FULL
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
from cognia_x.experiments.exp078_closed_loop_guard.run import _dedup, _replay_examples

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")
ARMS = ["conf_plain", "conf_guard"]


def run_seed(seed, args, test_targets, train_targets, log):
    base, npar = build_base(seed, args.n_seed, args.base_steps, args.base_lr, args.warmup, args.batch, train_targets)
    bm = E.eval_metrics(base, test_targets, "cpu")
    log(f"[exp099] seed={seed} base real_acc={bm['real_acc']:.3f} params={npar:,}")
    pool_rng = np.random.default_rng(seed + 7)
    sel = pool_rng.integers(0, len(train_targets), size=args.pool)
    pool_prompts = [E.make_prompt(train_targets[i]) for i in sel]
    k = max(1, int(args.budget_frac * args.pool * args.K))

    arms = {a: copy.deepcopy(base) for a in ARMS}
    hist = {a: {"real": [round(bm["real_acc"], 4)], "corr": []} for a in ARMS}
    train_rng = np.random.default_rng(seed + 99)

    for r in range(1, args.rounds + 1):
        for a in ARMS:
            torch.manual_seed(10000 * seed + r)
            pool = generate_pool(arms[a], pool_prompts, args.K, args.temp, args.top_k, "cpu")
            pairs = [(p, e) for (p, e, _, _) in pool]
            strong = np.array([1.0 if s else 0.0 for (_, _, _, s) in pool])
            conf = _confidence(arms[a], pairs, "cpu")
            hist[a]["corr"].append(round(_corr(conf, strong), 4))     # calidad de la señal de valor ESTE round
            rng_a = np.random.default_rng(seed * 131 + r * 17 + ARMS.index(a))
            sel_idx = np.argsort(conf + 1e-9 * rng_a.random(len(pool)))[-min(k, len(pool)):]
            ex = [pairs[i] for i in sel_idx if strong[i] > 0.5]
            if a == "conf_guard":
                ex = _dedup(ex)
                ex = ex + _replay_examples(train_rng, train_targets, int(round(args.replay_frac * max(1, len(ex)))))
            if ex:
                train_arm(arms[a], ex, args.steps, args.batch, args.lr, "cpu", train_rng)
            mm = E.eval_metrics(arms[a], test_targets, "cpu")
            hist[a]["real"].append(round(mm["real_acc"], 4))
        log(f"[exp099] seed={seed} ronda {r}: "
            + " | ".join(f"{a}: corr={hist[a]['corr'][-1]:.3f} real={hist[a]['real'][-1]:.3f}" for a in ARMS))

    return {"seed": seed, "base": bm, "hist": hist}


def _mean(xs):
    return float(np.mean(xs)) if len(xs) else 0.0


def _f(x):
    return "{:.3f}".format(x)


def _trend(corr_list):
    """Tendencia = media(segunda mitad) − media(primera mitad) de la corr por rondas."""
    n = len(corr_list)
    if n < 2:
        return 0.0
    h = n // 2
    first = corr_list[:h] if h > 0 else corr_list[:1]
    second = corr_list[h:]
    return float(np.mean(second) - np.mean(first))


def build_summary(per_seed):
    trends = {a: [_trend(s["hist"][a]["corr"]) for s in per_seed] for a in ARMS}
    corr_first = {a: _mean([s["hist"][a]["corr"][0] for s in per_seed]) for a in ARMS}
    corr_last = {a: _mean([s["hist"][a]["corr"][-1] for s in per_seed]) for a in ARMS}
    real_last = {a: _mean([s["hist"][a]["real"][-1] for s in per_seed]) for a in ARMS}
    t_plain = round(_mean(trends["conf_plain"]), 4)
    t_guard = round(_mean(trends["conf_guard"]), 4)
    guard_minus_plain = round(t_guard - t_plain, 4)
    nseed = len(per_seed)

    DEGRADE = 0.05            # plain degrada si su tendencia < −0.05
    GAP = 0.05               # la guardia ayuda si su tendencia supera a la de plain por >0.05
    plain_degrades = t_plain < -DEGRADE
    guard_helps = guard_minus_plain > GAP

    if plain_degrades and guard_helps:
        status = "apoyada"
        verdict = ("H-V4-8t APOYADA: el lazo de confianza-asignación NO es auto-sostenido por sí solo. SIN guardia, la "
                   "calidad de la señal de valor DEGRADA ronda a ronda -- corr(conf,strong) conf_plain {cf}->{cl} "
                   "(tendencia {tp}: sobreconfianza al entrenar sobre sus propias salidas). La GUARDIA (replay de verdad "
                   "canónica, CYCLE 94) la mantiene honesta -- conf_guard {gf}->{gl} (tendencia {tg}; guard−plain "
                   "+{gmp}). => la señal de valor (confianza) se EROSIONA al entrenar sobre sí misma; el replay de verdad "
                   "canónica es la dependencia CRÍTICA que mantiene el lazo R-VALOR honesto. real_acc final: plain={rp} "
                   "guard={rg}.").format(cf=_f(corr_first["conf_plain"]), cl=_f(corr_last["conf_plain"]), tp=_f(t_plain),
                                         gf=_f(corr_first["conf_guard"]), gl=_f(corr_last["conf_guard"]), tg=_f(t_guard),
                                         gmp=_f(guard_minus_plain), rp=_f(real_last["conf_plain"]), rg=_f(real_last["conf_guard"]))
    elif not plain_degrades:
        status = "refutada"
        verdict = ("H-V4-8t REFUTADA: la corr NO degrada sin guardia (conf_plain tendencia {tp} >= −{d}: {cf}->{cl}) -> el "
                   "lazo de confianza-asignación es AUTO-SOSTENIDO; la asunción del arco es robusta sin corrector.").format(
                       tp=_f(t_plain), d=DEGRADE, cf=_f(corr_first["conf_plain"]), cl=_f(corr_last["conf_plain"]))
    else:
        status = "mixta"
        verdict = ("H-V4-8t MIXTA: conf_plain degrada (tendencia {tp}) pero la guardia no lo corrige limpio (guard−plain "
                   "{gmp}); conf_guard tendencia {tg}.").format(tp=_f(t_plain), gmp=_f(guard_minus_plain), tg=_f(t_guard))

    return {"arms": ARMS, "n_seeds": nseed, "trend_plain": t_plain, "trend_guard": t_guard,
            "guard_minus_plain": guard_minus_plain, "corr_first": {a: round(corr_first[a], 4) for a in ARMS},
            "corr_last": {a: round(corr_last[a], 4) for a in ARMS}, "real_last": {a: round(real_last[a], 4) for a in ARMS},
            "trend_plain_by_seed": [round(x, 4) for x in trends["conf_plain"]],
            "plain_degrades": bool(plain_degrades), "guard_helps": bool(guard_helps), "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=str, default="0,1,2,3")
    ap.add_argument("--rounds", type=int, default=6)
    ap.add_argument("--K", type=int, default=8)
    ap.add_argument("--pool", type=int, default=64)
    ap.add_argument("--budget_frac", type=float, default=0.15)
    ap.add_argument("--temp", type=float, default=1.3)
    ap.add_argument("--replay_frac", type=float, default=0.5)
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
        args.seeds, args.rounds, args.pool, args.steps, args.base_steps = "0,1", 4, 48, 60, 200

    seeds = [int(s) for s in args.seeds.split(",")]
    train_targets, test_targets = E.build_split(LO, HI, args.test_frac)
    logs = []

    def log(mm):
        print(mm, flush=True); logs.append(mm)

    log("[exp099] CYCLE 115 / H-V4-8t — STRESS-TEST: ¿la confianza (señal de valor) degrada al entrenar sobre sí misma?")
    log(f"[exp099] seeds={seeds} rango=[{LO},{HI}] rounds={args.rounds} K={args.K} pool={args.pool} budget_frac={args.budget_frac} "
        f"temp={args.temp} replay_frac={args.replay_frac} base_steps={args.base_steps}")

    per_seed = [run_seed(s, args, test_targets, train_targets, log) for s in seeds]
    sm = build_summary(per_seed)

    log(f"[exp099] corr(conf,strong) conf_plain: {sm['corr_first']['conf_plain']:.3f}->{sm['corr_last']['conf_plain']:.3f} (tendencia {sm['trend_plain']:+.3f})")
    log(f"[exp099] corr(conf,strong) conf_guard: {sm['corr_first']['conf_guard']:.3f}->{sm['corr_last']['conf_guard']:.3f} (tendencia {sm['trend_guard']:+.3f})")
    log(f"[exp099] guard−plain (tendencia)=+{sm['guard_minus_plain']:.3f} | plain_degrades={sm['plain_degrades']} guard_helps={sm['guard_helps']}")
    log(f"[exp099] real_acc final: plain={sm['real_last']['conf_plain']:.3f} guard={sm['real_last']['conf_guard']:.3f}")
    log(f"[exp099] VEREDICTO H-V4-8t: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp099_confidence_drift", "cycle": 115, "hypothesis": "H-V4-8t",
           "claim": "el lazo de confianza-asignacion no es auto-sostenido: sin guardia la corr(confianza,correccion) "
                    "degrada ronda a ronda (sobreconfianza al entrenar sobre si misma); la guardia (replay de verdad "
                    "canonica CYCLE 94) la mantiene honesta -> dependencia critica del arco",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__, "torch": torch.__version__},
           "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp099] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
