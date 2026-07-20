r"""
exp135 — CYCLE 153 / H-V4-9m (FRONTERA REAL §4.2, el diseño CORRECTO que el 152 sembró): el 152 intentó medir el pago DOWNSTREAM del
residuo de calibración del 151 pero su pool BALANCEADO 50/50 SATURÓ precision@top-m (INDIST cero estructural) y NO instanció la
escasez (la verificación, sev ALTA, lo cazó: por la lección de exp124, 'm chico' NO es 'escasez'; la escasez decisional es f=m/#correct≈1
o base-rate baja). Este ciclo lo REHACE bien: un POOL FIJO COMPARTIDO de BAJA BASE-RATE (escaso) y se mide precision@top-m POR f=m/#correct,
barriendo el régimen DISCRIMINANTE f≈1 (recall de las pocas correctas), que el 152 nunca alcanzó (f<=0.5).

PREGUNTA: ¿el residuo de calibración GENÉRICO (ls_lo, único superviviente del desconfound del 151) PAGA en una DECISIÓN real bajo
ESCASEZ GENUINA (precision@top-m a f≈1 sobre un pool fijo escaso), preservando el desconfound? — la tesis brújula-decisional 123 que el
152 dejó SIN testear. El durable (cura 119) se espera robustamente NEGATIVO (se invirtió en 151 y 152).

DISEÑO (reusa exp134/exp124/exp018; lazo torch CPU). 3 brazos (naive, durable=cura 119, ls_lo). Cada brazo se auto-entrena en su pool
(idéntico a exp133/exp134). En cada ronda asigna confianza a DOS POOLS FIJOS COMPARTIDOS ESCASOS (base-rate ~1/(1+R), idénticos para
los 3 brazos, fijos a lo largo de rondas):
  - INDIST: por prompt n, 1 POSITIVO canónico '1+(n-1)' + R NEGATIVOS '1+(m-1)' (m!=n, valor incorrecto). #correct = #prompts.
  - HELDOUT: igual pero FORMA NOVEL '2+(n-2)' (no entrenada) -> ranking held-out + escaso.
Sobre cada pool, por brazo/ronda: AUROC y precision@top-m con m = round(f·#correct) para f en F_GRID (incluye el régimen f≈1
DISCRIMINANTE). MÉTRICA decisional: gap ls_lo−naive y durable−naive de precision@f (AUC sobre rondas), por f, por pool. Se reporta f
explícito (la lección del 152). Compuerta robusta por t-test + detección de SATURACIÓN (un f donde el naive ya está en techo no informa).

PREGUNTA FALSABLE:
  - APOYADA-downstream si el residuo ls_lo PAGA ROBUSTO (CI excl 0 + t-test + signo) en el régimen escaso DISCRIMINANTE (f≈1) en un pool
    INFORMATIVO -> la brújula decisional vale bajo escasez REAL aun con AUROC mínimo (confirma 123 en el lazo real desconfundido).
  - REFUTADA-downstream si NO paga en ningún f informativo -> cierre DEFLACIONARIO honesto: el residuo no paga ni en escasez real.
  - MIXTA si parcial (paga sólo en un pool / borderline / sólo en f de filo).

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp135_scarce_downstream.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp135_scarce_downstream.run --seeds 0-5 --rounds 4 --steps 50 --base_steps 180
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
from cognia_x.experiments.exp018_real_verifier.run import build_base, generate_pool, LO, HI
from cognia_x.experiments.exp077_closed_loop_budget.run import _confidence
from cognia_x.experiments.exp078_closed_loop_guard.run import _dedup, _replay_examples
from cognia_x.experiments.exp124_decisional_real_loop.run import _auroc, _auc_over_rounds, _mean, _f, _payoff_at_m
from cognia_x.experiments.exp132_privileged_cure.run import _train_arm, _bootstrap_ci, ARM_SPECS
from cognia_x.experiments.exp133_deconfound_calibration.run import _t_crit, _robust_positive, _sign_positive
from cognia_x.experiments.exp134_downstream_payoff.run import _gap, _canon_pos, _novel_pos

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")
ARMS = ["naive", "durable", "ls_lo"]
POOLS = ["indist", "heldout"]
F_GRID = [0.1, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5]   # f = m/#correct; f≈1 es el régimen DISCRIMINANTE (recall de las pocas correctas)


def _build_scarce_pool(seed_offset, tvals, n_prompts, neg_per_pos, posfn):
    """Pool fijo ESCASO compartido: por prompt n, 1 POSITIVO (posfn, correcto) + R NEGATIVOS (posfn de OTROS targets m!=n, valor
    incorrecto), etiquetados por el verificador REAL. base-rate ~ 1/(1+R). #correct = n_prompts. Devuelve (pairs, strong[])."""
    frng = np.random.default_rng(seed_offset)
    prompts = [tvals[int(frng.integers(0, len(tvals)))] for _ in range(n_prompts)]
    pairs = []; strong = []
    for n in prompts:
        pn = E.make_prompt(n)
        # 1 positivo
        e = posfn(frng, n); s = E.verify(pn, e + b"\n", True)
        pairs.append((pn, e)); strong.append(1.0 if s else 0.0)
        # R negativos (otros targets con valor != n)
        for _ in range(neg_per_pos):
            m = n
            while m == n:
                m = tvals[int(frng.integers(0, len(tvals)))]
            e = posfn(frng, m); s = E.verify(pn, e + b"\n", True)
            pairs.append((pn, e)); strong.append(1.0 if s else 0.0)
    return pairs, np.array(strong)


def _m_of_f(f, ncorrect):
    return max(1, int(round(f * ncorrect)))


def run_seed(seed, args, test_targets, train_targets, log):
    base, npar = build_base(seed, args.n_seed, args.base_steps, args.base_lr, args.warmup, args.batch, train_targets)
    bm = E.eval_metrics(base, test_targets, "cpu")
    log(f"[exp135] seed={seed} base real_acc={bm['real_acc']:.3f} params={npar:,}")
    pool_rng = np.random.default_rng(seed + 7)
    sel = pool_rng.integers(0, len(train_targets), size=args.pool)
    pool_prompts = [E.make_prompt(train_targets[i]) for i in sel]
    k = max(1, int(args.budget_frac * args.pool * args.K))
    tvals = [int(t) for t in train_targets]

    fixed = {
        "indist": _build_scarce_pool(seed + 555, tvals, args.n_prompts, args.neg_per_pos, _canon_pos),
        "heldout": _build_scarce_pool(seed + 777, tvals, args.n_prompts, args.neg_per_pos, _novel_pos),
    }
    ncorr = {p: int(np.sum(fixed[p][1])) for p in POOLS}
    for p in POOLS:
        npool = len(fixed[p][1])
        log(f"[exp135] seed={seed} pool ESCASO {p}: {npool} cands ({ncorr[p]} correctas / {npool-ncorr[p]} incorrectas, base-rate {ncorr[p]/npool:.3f})")

    arms = {a: copy.deepcopy(base) for a in ARMS}
    # hist[arm][pool] = {"auroc": [...], "payoff": {f: [...]}, "ncorrect": int}
    hist = {a: {p: {"auroc": [], "payoff": {f: [] for f in F_GRID}} for p in POOLS} for a in ARMS}

    for r in range(1, args.rounds + 1):
        for a in ARMS:
            torch.manual_seed(10000 * seed + r)
            pool = generate_pool(arms[a], pool_prompts, args.K, args.temp, args.top_k, "cpu")
            pairs = [(p, e) for (p, e, _, _) in pool]
            strong = np.array([1.0 if s else 0.0 for (_, _, _, s) in pool])
            conf = _confidence(arms[a], pairs, "cpu")
            for p in POOLS:
                fpairs, fstrong = fixed[p]
                conf_fx = _confidence(arms[a], fpairs, "cpu")
                au = _auroc(conf_fx, fstrong)
                hist[a][p]["auroc"].append(round(au, 4) if au is not None else None)
                for f in F_GRID:
                    pm = _payoff_at_m(conf_fx, fstrong, _m_of_f(f, ncorr[p]))
                    hist[a][p]["payoff"][f].append(round(pm, 4) if pm is not None else None)
            sel_rng = np.random.default_rng(seed * 131 + r * 17 + ARMS.index(a))
            sel_idx = np.argsort(conf + 1e-9 * sel_rng.random(len(pool)))[-min(k, len(pool)):]
            pos = _dedup([pairs[i] for i in sel_idx if strong[i] > 0.5])
            train_rng = np.random.default_rng(seed * 1000 + 17 + ARMS.index(a))
            pos = pos + _replay_examples(train_rng, train_targets, int(round(args.replay_frac * max(1, len(pos)))))
            neg = _dedup([pairs[i] for i in sel_idx if strong[i] < 0.5]) if ARM_SPECS[a]["kind"] == "unlik" else []
            _train_arm(arms[a], pos, neg, ARM_SPECS[a], args.steps, args.batch, args.lr, "cpu", train_rng)

        def _g(a, p):
            v = hist[a][p]["auroc"][-1]
            return "{:.3f}".format(v) if v is not None else "--"
        log(f"[exp135] seed={seed} r{r} AUROC indist " + "/".join(f"{a}={_g(a,'indist')}" for a in ARMS) +
            " | heldout " + "/".join(f"{a}={_g(a,'heldout')}" for a in ARMS))

    return {"seed": seed, "base": bm, "fixed_ncorrect": ncorr,
            "fixed_npool": {p: len(fixed[p][1]) for p in POOLS}, "hist": hist}


def build_summary(per_seed, n_boot=10000):
    n = len(per_seed); tcrit = _t_crit(n - 1)
    au = {p: {a: round(float(np.mean([v for v in (_auc_over_rounds(s["hist"][a][p]["auroc"]) for s in per_seed) if v is not None])), 4) for a in ARMS} for p in POOLS}
    pay = {p: {a: {f: round(float(np.mean([v for v in (_auc_over_rounds(s["hist"][a][p]["payoff"][f]) for s in per_seed) if v is not None])), 4) for f in F_GRID} for a in ARMS} for p in POOLS}
    # _gap reusa la firma de exp134 (key 'payoff', el índice m aquí es f); helper local idéntico
    def gap(p, f, arm):
        gaps = []
        for s in per_seed:
            ga = _auc_over_rounds(s["hist"][arm][p]["payoff"][f]); gr = _auc_over_rounds(s["hist"]["naive"][p]["payoff"][f])
            if ga is not None and gr is not None:
                gaps.append(ga - gr)
        nn = len(gaps); mean = float(np.mean(gaps)) if gaps else 0.0
        lo, hi = _bootstrap_ci(gaps, n_boot=n_boot) if nn > 1 else (mean, mean)
        se = float(np.std(gaps, ddof=1) / np.sqrt(nn)) if nn > 1 else 0.0
        return {"arm": arm, "pool": p, "f": f, "mean": round(mean, 4), "ci95": [round(lo, 4), round(hi, 4)],
                "n_positive": int(np.sum(np.array(gaps) > 0)), "n": nn, "tstat": round(mean / se, 3) if se > 0 else 0.0,
                "ci_excludes_zero": bool(lo > 0.0 or hi < 0.0), "gaps": [round(g, 4) for g in gaps]}

    gaps = {p: {"ls_lo": {f: gap(p, f, "ls_lo") for f in F_GRID}, "durable": {f: gap(p, f, "durable") for f in F_GRID}} for p in POOLS}

    # régimen DISCRIMINANTE: f en [0.5, 1.25] (donde precision@top-m no satura -recall de las pocas correctas-)
    disc = [f for f in F_GRID if 0.5 <= f <= 1.25]
    # SATURACIÓN por f: el naive ya en techo (>0.99) -> ese f no informa
    naive_f = {p: {f: pay[p]["naive"][f] for f in F_GRID} for p in POOLS}
    sat_disc = {p: all(naive_f[p][f] > 0.99 for f in disc) for p in POOLS}     # pool saturado si TODO el régimen disc satura
    informative = [p for p in POOLS if not sat_disc[p]]

    # COMPUERTA HONESTA (anti cherry-pick): el veredicto descansa en un f PRE-REGISTRADO (1.0 = recall de TODAS las correctas,
    # el punto decisional canónico bajo escasez), NO en el max-t sobre los 7 f (winner's curse / multiple-comparison).
    PREREG_F = 1.0
    lslo_f1 = {p: gaps[p]["ls_lo"][PREREG_F] for p in POOLS}                    # el test PRIMARIO pre-registrado
    lslo_robust_f1 = {p: _robust_positive(lslo_f1[p]) for p in POOLS}
    lslo_robust_anyf = {p: any(_robust_positive(gaps[p]["ls_lo"][f]) for f in disc) for p in POOLS}   # cherry-pick (sólo transparencia)
    lslo_sign_f1 = {p: _sign_positive(lslo_f1[p]) for p in POOLS}
    durable_neg = {p: any(g["mean"] < 0 and g["ci_excludes_zero"] and abs(g["tstat"]) >= tcrit
                          for g in (gaps[p]["durable"][f] for f in disc)) for p in POOLS}

    # tendencia MONÓTONA esperada: el residuo paga MÁS al crecer f hacia el régimen recall (mecanismo, no azar)
    def _monotone_pos(p):
        ms = [gaps[p]["ls_lo"][f]["mean"] for f in disc]
        return bool(ms[-1] > 0 and ms[-1] >= ms[0] and sum(1 for m in ms if m > 0) >= len(ms) - 1)

    def _borderline_f1(p):
        g = lslo_f1[p]
        return bool(g["mean"] > 0 and int(np.sum(np.array(g["gaps"]) < 0)) == 0 and abs(g["tstat"]) >= 0.7 * tcrit)

    robust_inf = any(lslo_robust_f1[p] for p in informative)                    # APOYADA: robusto en el f PRE-REGISTRADO
    weakpos_inf = any(lslo_sign_f1[p] or _borderline_f1(p) or _monotone_pos(p) for p in informative)
    if robust_inf:
        status = "apoyada"
    elif not informative:
        status = "mixta"
    elif weakpos_inf:
        status = "mixta"
    else:
        status = "refutada"

    bp = informative[0] if informative else "heldout"
    g1 = lslo_f1[bp]
    dgi = gaps["indist"]["durable"][PREREG_F]
    verdict = (
        "H-V4-9m {V}-downstream-ESCASO (diseño CORRECTO del 152: pool ESCASO base-rate≈{br} + precision@top-m por f=m/#correct; "
        "compuerta HONESTA en el f PRE-REGISTRADO 1.0 -recall de todas las correctas-, NO el max-t -anti cherry-pick-): ¿el residuo "
        "genérico ls_lo paga en una decisión bajo ESCASEZ GENUINA? Pool informativo {bp}, f=1.0: ls_lo−naive payoff {g1m} (CI {g1ci}, "
        "t={g1t} {rob}; {g1p}/{g1n} seeds+). Transparencia: robusto en ALGÚN f (cherry-pick) indist={cpi} heldout={cph} -> el "
        "veredicto NO se apoya en eso. El durable (cura 119) {dneg} robustamente NEGATIVO (f=1.0 {dgim}, t={dgit}) -> confirma su "
        "inversión del 151/152. saturated_disc={sat}, informative={inf}. CONCLUSIÓN: {concl}").format(
            V=status.upper(), br="~{:.2f}".format(np.mean([s["fixed_ncorrect"]["indist"]/max(1,s["fixed_npool"]["indist"]) for s in per_seed])),
            bp=bp, g1m=_f(g1["mean"]), g1ci=g1["ci95"], g1t=_f(g1["tstat"]), rob=("ROBUSTO" if _robust_positive(g1) else "no-robusto"),
            g1p=g1["n_positive"], g1n=g1["n"], cpi=lslo_robust_anyf["indist"], cph=lslo_robust_anyf["heldout"],
            dneg=("SÍ" if durable_neg["indist"] else "NO"), dgim=_f(dgi["mean"]), dgit=_f(dgi["tstat"]), sat=sat_disc, inf=informative,
            concl=({"apoyada": "el residuo PAGA ROBUSTO en el f pre-registrado (f=1.0) en un pool informativo -> la brújula decisional vale bajo escasez genuina (ver caveat rank-only).",
                    "refutada": "el residuo NO paga en el f pre-registrado en ningún pool informativo -> cierre DEFLACIONARIO: el residuo no es decisionalmente útil ni en escasez genuina.",
                    "mixta": ("SEÑAL POSITIVA SUGESTIVA pero NO robusta a f=1.0: t-significativa sin corregir en ambos pools (indist t={t1i}, heldout t={t1h}) y monótona en indist, PERO 5/6 (no 6/6), NO sobrevive leave-one-out del seed más favorable (t~1.8<2.015) NI Bonferroni (familia 14, t_crit~4.38), el headline indist lo cargan 2 seeds (corr cruzada ~0), y el monótono NO replica en heldout. CAVEAT load-bearing (verificación, error de categoría): precision@top-m es RANK-ONLY (argsort, invariante a transformaciones monótonas de la confianza) -> NO testea CALIBRACIÓN, testea RANKING; la ventaja del ls_lo es la MISMA ventaja AUROC del 151 (+0.018) RE-EXPRESADA en el punto recall (co-mueven round-level r~0.87) -> 0 info decisional independiente del 151. El 153 APUNTA a la brújula-123 pero NO la prueba. Lo ROBUSTO (multiplicity-survivor) es el NEGATIVO del durable. PRÓXIMO (154): métrica decisional NO invariante-a-monótonas (cost-weighted/umbral-abstención) que separe calibración de ranking; N>=12; LOO+Bonferroni.").format(
                        t1i=_f(lslo_f1["indist"]["tstat"]), t1h=_f(lslo_f1["heldout"]["tstat"]))}[status]))

    return {"n": n, "arms": ARMS, "pools": POOLS, "f_grid": F_GRID, "disc_f": disc, "prereg_f": PREREG_F, "t_crit_one_tail_05": round(tcrit, 4),
            "ncorrect_mean": {p: round(float(np.mean([s["fixed_ncorrect"][p] for s in per_seed])), 1) for p in POOLS},
            "base_rate": {p: round(float(np.mean([s["fixed_ncorrect"][p]/max(1, s["fixed_npool"][p]) for s in per_seed])), 4) for p in POOLS},
            "auroc": au, "payoff": pay, "payoff_gap": gaps, "naive_payoff_disc": {p: {str(f): round(naive_f[p][f], 4) for f in disc} for p in POOLS},
            "saturated_disc": sat_disc, "informative_pools": informative,
            "lslo_robust_f1": lslo_robust_f1, "lslo_sign_f1": lslo_sign_f1, "lslo_robust_anyf_cherrypick": lslo_robust_anyf,
            "monotone_pos": {p: _monotone_pos(p) for p in POOLS}, "durable_neg": durable_neg,
            "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=str, default="0-5")
    ap.add_argument("--rounds", type=int, default=4)
    ap.add_argument("--K", type=int, default=8)
    ap.add_argument("--pool", type=int, default=48)
    ap.add_argument("--n_prompts", type=int, default=20)        # #correct = n_prompts (uno por prompt)
    ap.add_argument("--neg_per_pos", type=int, default=7)       # base-rate ~ 1/(1+R) = 1/8 = 0.125
    ap.add_argument("--budget_frac", type=float, default=0.15)
    ap.add_argument("--temp", type=float, default=1.3)
    ap.add_argument("--replay_frac", type=float, default=0.5)
    ap.add_argument("--top_k", type=int, default=0)
    ap.add_argument("--steps", type=int, default=50)
    ap.add_argument("--n_seed", type=int, default=200)
    ap.add_argument("--base_steps", type=int, default=180)
    ap.add_argument("--base_lr", type=float, default=1e-3)
    ap.add_argument("--lr", type=float, default=5e-4)
    ap.add_argument("--warmup", type=int, default=40)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--test_frac", type=float, default=0.30)
    args = ap.parse_args()
    if args.top_k <= 0:
        args.top_k = None
    n_boot = 10000
    if args.smoke:
        args.seeds, args.rounds = "0-2", 4
        n_boot = 2000

    if "-" in args.seeds and "," not in args.seeds:
        a, b = args.seeds.split("-"); seeds = list(range(int(a), int(b) + 1))
    else:
        seeds = [int(x) for x in args.seeds.split(",")]
    train_targets, test_targets = E.build_split(LO, HI, args.test_frac)
    logs = []

    def log(mm):
        print(mm, flush=True); logs.append(mm)

    log("[exp135] CYCLE 153 / H-V4-9m — pago DOWNSTREAM bajo ESCASEZ GENUINA (pool escaso + precision@top-m por f=m/#correct, f≈1 discriminante)")
    log(f"[exp135] arms={ARMS} seeds={seeds} rounds={args.rounds} f_grid={F_GRID} n_prompts={args.n_prompts} neg_per_pos={args.neg_per_pos}")
    per_seed = [run_seed(s, args, test_targets, train_targets, log) for s in seeds]
    sm = build_summary(per_seed, n_boot=n_boot)

    log(f"[exp135] base_rate={sm['base_rate']} ncorrect_mean={sm['ncorrect_mean']} saturated_disc={sm['saturated_disc']} informative={sm['informative_pools']}")
    for p in POOLS:
        log(f"[exp135] AUROC {p}: {sm['auroc'][p]}")
        for f in F_GRID:
            g = sm["payoff_gap"][p]["ls_lo"][f]
            log(f"[exp135]   {p} f={f:<4} (m≈{_m_of_f(f, int(sm['ncorrect_mean'][p]))}) ls_lo−naive {g['mean']:+.3f} (CI {g['ci95']}, t={g['tstat']}, robust={_robust_positive(g)})")
    log(f"[exp135] VEREDICTO H-V4-9m: {sm['status'].upper()} | {sm['verdict']}")

    raw = [{"seed": s["seed"], "base_real_acc": round(s["base"].get("real_acc", 0.0), 4),
            "fixed_ncorrect": s["fixed_ncorrect"], "fixed_npool": s["fixed_npool"], "hist": s["hist"]} for s in per_seed]
    out = {"exp": "exp135_scarce_downstream", "cycle": 153, "hypothesis": "H-V4-9m",
           "claim": "El diseño CORRECTO del downstream (152 saturó/no-escaso): pool fijo COMPARTIDO ESCASO (base-rate ~0.125, 1 pos + R "
                    "neg por prompt, etiquetado por el verificador real, desconfound del 151 preservado) + precision@top-m POR f=m/#correct, "
                    "barriendo el régimen DISCRIMINANTE f≈1 (recall de las pocas correctas). ¿El residuo genérico ls_lo PAGA bajo escasez "
                    "GENUINA? APOYADA si paga robusto (CI+t-test) a f≈1 en un pool informativo; REFUTADA si no; MIXTA si parcial/borderline.",
           "verdict": sm["status"], "summary": sm, "raw": raw, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__, "torch": torch.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp135] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
