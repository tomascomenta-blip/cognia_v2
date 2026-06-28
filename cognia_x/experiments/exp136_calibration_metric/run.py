r"""
exp136 — CYCLE 154 / H-V4-9n (FRONTERA REAL §4.2, el test DECISIVO que el 153 definió): el 153 halló un 1er positivo-leaning del
residuo genérico (ls_lo) bajo escasez PERO la verificación cazó un ERROR DE CATEGORÍA: precision@top-m (vía argsort) es RANK-ONLY
(invariante a transformaciones monótonas de la confianza, IGUAL que AUROC) -> NO testea CALIBRACIÓN, RE-EXPRESA el AUROC del 151.
Para tocar de verdad la tesis 123 ("la calibración paga en la decisión") hace falta una métrica SENSIBLE A MAGNITUDES de confianza,
NO invariante-a-monótonas, que SEPARE calibración de ranking.

PREGUNTA: ¿la CALIBRACIÓN del residuo genérico (ls_lo) -no su ranking- paga, independiente de la ventaja de ranking del 151? Si el
"payoff" del 153 era puro ranking (AUROC re-expresado), entonces sobre métricas de CALIBRACIÓN PURA (que el ranking no captura) la
ventaja del ls_lo DEBE desvanecerse. Si ls_lo está genuinamente MEJOR CALIBRADO, sobrevive.

DISEÑO (reusa exp135/exp018; lazo torch CPU). 3 brazos (naive, durable=cura 119, ls_lo). Pool fijo COMPARTIDO ESCASO (base-rate
~0.125, idéntico al 153, desconfound del 151 preservado), 2 pools INDIST/HELDOUT. La confianza endógena es mean-logprob -> se convierte
a PROBABILIDAD p = exp(mean_logprob) ∈ (0,1]. Por brazo/ronda/pool se miden métricas SENSIBLES A MAGNITUDES:
  - BRIER = mean((p − correct)²)  (proper scoring; magnitude-sensitive; menor=mejor).
  - ECE (10 bins) = Σ_bins |conf_bin − acc_bin|·(n_bin/N)  (CALIBRACIÓN PURA; NO la captura el ranking; menor=mejor).
  - NET umbral-abstención cost-weighted: accept iff p ≥ τ*=λ/(1+λ) (trata p como P(correct) calibrada -> magnitude-sensitive);
    net = Σ_accept (correct?+1:−λ); net_norm = net/#correct. λ ∈ {1,3,7}. (Una decisión que USA la magnitud de la confianza.)
  - AUROC (rank-only) en paralelo -> el CONTRASTE: si la ventaja ls_lo vive en AUROC pero NO en ECE/Brier/NET -> era RANKING, no calibración.

PREGUNTA FALSABLE (sobre ls_lo−naive en métricas de CALIBRACIÓN):
  - APOYADA-calibración si ls_lo tiene ventaja ROBUSTA (CI excl 0 + t-test, f-pre-registrado-análogo: λ central=3) en ECE/Brier/NET
    en un pool informativo -> la calibración del residuo paga independiente del ranking (toca la 123).
  - REFUTADA-calibración si la ventaja de CALIBRACIÓN se desvanece (≈0/reversa) mientras la de AUROC persiste -> el payoff del 153 era
    RANKING re-expresado; la calibración del residuo NO paga (cierra el arco: el residuo es ranking, no calibración).
  - MIXTA si parcial (paga en Brier/NET pero no ECE, o sólo un pool/λ).

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp136_calibration_metric.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp136_calibration_metric.run --seeds 0-5 --rounds 4 --steps 50 --base_steps 180
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
from cognia_x.experiments.exp124_decisional_real_loop.run import _auroc, _auc_over_rounds, _mean, _f
from cognia_x.experiments.exp132_privileged_cure.run import _train_arm, _bootstrap_ci, ARM_SPECS
from cognia_x.experiments.exp133_deconfound_calibration.run import _t_crit, _robust_positive, _sign_positive
from cognia_x.experiments.exp134_downstream_payoff.run import _canon_pos, _novel_pos
from cognia_x.experiments.exp135_scarce_downstream.run import _build_scarce_pool

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")
ARMS = ["naive", "durable", "ls_lo"]
POOLS = ["indist", "heldout"]
LAMBDAS = [1, 3, 7]            # costo de aceptar un incorrecto; τ*=λ/(1+λ) ∈ {0.5, 0.75, 0.875}
PREREG_LAMBDA = 3             # λ central pre-registrado (τ*=0.75)
N_BINS = 10


def _to_prob(conf_logprob):
    """mean-logprob -> probabilidad p=exp(logprob) ∈ (0,1] (per-token geometric-mean prob)."""
    return np.clip(np.exp(np.asarray(conf_logprob, dtype=float)), 1e-9, 1.0)


def _brier(p, strong):
    return float(np.mean((p - strong) ** 2)) if len(p) else None


def _ece(p, strong, n_bins=N_BINS):
    """Expected Calibration Error: |conf_bin − acc_bin| ponderado por tamaño de bin. CALIBRACIÓN PURA (no rank-invariante)."""
    if len(p) == 0:
        return None
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1]), 0, n_bins - 1)
    ece = 0.0
    for b in range(n_bins):
        m = idx == b
        nb = int(np.sum(m))
        if nb > 0:
            ece += (nb / len(p)) * abs(float(np.mean(p[m])) - float(np.mean(strong[m])))
    return float(ece)


def _net_abstain(p, strong, lam):
    """Decisión umbral-abstención: accept iff p>=τ*=λ/(1+λ) (p como P(correct) calibrada). net=Σ_accept(correct?+1:−λ); /#correct."""
    if len(p) == 0:
        return None
    tau = lam / (1.0 + lam)
    acc = p >= tau
    ncorr = float(np.sum(strong))
    if ncorr == 0:
        return None
    reward = float(np.sum(strong[acc])) - lam * float(np.sum((1.0 - strong)[acc]))
    return reward / ncorr


def run_seed(seed, args, test_targets, train_targets, log):
    base, npar = build_base(seed, args.n_seed, args.base_steps, args.base_lr, args.warmup, args.batch, train_targets)
    bm = E.eval_metrics(base, test_targets, "cpu")
    log(f"[exp136] seed={seed} base real_acc={bm['real_acc']:.3f} params={npar:,}")
    pool_rng = np.random.default_rng(seed + 7)
    sel = pool_rng.integers(0, len(train_targets), size=args.pool)
    pool_prompts = [E.make_prompt(train_targets[i]) for i in sel]
    k = max(1, int(args.budget_frac * args.pool * args.K))
    tvals = [int(t) for t in train_targets]

    fixed = {
        "indist": _build_scarce_pool(seed + 555, tvals, args.n_prompts, args.neg_per_pos, _canon_pos),
        "heldout": _build_scarce_pool(seed + 777, tvals, args.n_prompts, args.neg_per_pos, _novel_pos),
    }
    for p in POOLS:
        npool = len(fixed[p][1]); ncp = int(np.sum(fixed[p][1]))
        log(f"[exp136] seed={seed} pool ESCASO {p}: {npool} cands (base-rate {ncp/npool:.3f})")

    arms = {a: copy.deepcopy(base) for a in ARMS}
    # hist[arm][pool] = {"auroc":[], "brier":[], "ece":[], "net":{lam:[]}}
    hist = {a: {p: {"auroc": [], "brier": [], "ece": [], "net": {lam: [] for lam in LAMBDAS}} for p in POOLS} for a in ARMS}

    for r in range(1, args.rounds + 1):
        for a in ARMS:
            torch.manual_seed(10000 * seed + r)
            pool = generate_pool(arms[a], pool_prompts, args.K, args.temp, args.top_k, "cpu")
            pairs = [(p, e) for (p, e, _, _) in pool]
            strong = np.array([1.0 if s else 0.0 for (_, _, _, s) in pool])
            conf = _confidence(arms[a], pairs, "cpu")
            for p in POOLS:
                fpairs, fstrong = fixed[p]
                conf_fx = _to_prob(_confidence(arms[a], fpairs, "cpu"))
                au = _auroc(conf_fx, fstrong)
                hist[a][p]["auroc"].append(round(au, 4) if au is not None else None)
                br = _brier(conf_fx, fstrong); ec = _ece(conf_fx, fstrong)
                hist[a][p]["brier"].append(round(br, 4) if br is not None else None)
                hist[a][p]["ece"].append(round(ec, 4) if ec is not None else None)
                for lam in LAMBDAS:
                    nv = _net_abstain(conf_fx, fstrong, lam)
                    hist[a][p]["net"][lam].append(round(nv, 4) if nv is not None else None)
            sel_rng = np.random.default_rng(seed * 131 + r * 17 + ARMS.index(a))
            sel_idx = np.argsort(conf + 1e-9 * sel_rng.random(len(pool)))[-min(k, len(pool)):]
            pos = _dedup([pairs[i] for i in sel_idx if strong[i] > 0.5])
            train_rng = np.random.default_rng(seed * 1000 + 17 + ARMS.index(a))
            pos = pos + _replay_examples(train_rng, train_targets, int(round(args.replay_frac * max(1, len(pos)))))
            neg = _dedup([pairs[i] for i in sel_idx if strong[i] < 0.5]) if ARM_SPECS[a]["kind"] == "unlik" else []
            _train_arm(arms[a], pos, neg, ARM_SPECS[a], args.steps, args.batch, args.lr, "cpu", train_rng)

        def _g(a, p, key):
            v = hist[a][p][key][-1]
            return "{:.3f}".format(v) if v is not None else "--"
        log(f"[exp136] seed={seed} r{r} indist BRIER " + "/".join(f"{a}={_g(a,'indist','brier')}" for a in ARMS) +
            " ECE " + "/".join(f"{a}={_g(a,'indist','ece')}" for a in ARMS))

    return {"seed": seed, "base": bm, "fixed_ncorrect": {p: int(np.sum(fixed[p][1])) for p in POOLS},
            "fixed_npool": {p: len(fixed[p][1]) for p in POOLS}, "hist": hist}


def _gap(per_seed, pool, getter, n_boot=10000):
    """Gap ls_lo−naive y durable−naive de un escalar AUC-sobre-rondas (getter(s,arm,pool) -> serie). signo: + = ls_lo MEJOR."""
    def _series(s, arm):
        return _auc_over_rounds(getter(s, arm, pool))
    out = {}
    for arm in ("durable", "ls_lo"):
        gaps = []
        for s in per_seed:
            ga = _series(s, arm); gr = _series(s, "naive")
            if ga is not None and gr is not None:
                gaps.append(ga - gr)
        nn = len(gaps); mean = float(np.mean(gaps)) if gaps else 0.0
        lo, hi = _bootstrap_ci(gaps, n_boot=n_boot) if nn > 1 else (mean, mean)
        se = float(np.std(gaps, ddof=1) / np.sqrt(nn)) if nn > 1 else 0.0
        out[arm] = {"arm": arm, "mean": round(mean, 4), "ci95": [round(lo, 4), round(hi, 4)],
                    "n_positive": int(np.sum(np.array(gaps) > 0)), "n": nn, "tstat": round(mean / se, 3) if se > 0 else 0.0,
                    "ci_excludes_zero": bool(lo > 0.0 or hi < 0.0), "gaps": [round(g, 4) for g in gaps]}
    return out


def build_summary(per_seed, n_boot=10000):
    n = len(per_seed); tcrit = _t_crit(n - 1)
    # getters (signo: + = ls_lo MEJOR): AUROC mayor mejor; Brier/ECE MENOR mejor -> negar; NET mayor mejor.
    g_auroc = lambda s, a, p: s["hist"][a][p]["auroc"]
    g_negbrier = lambda s, a, p: [(-v if v is not None else None) for v in s["hist"][a][p]["brier"]]
    g_negece = lambda s, a, p: [(-v if v is not None else None) for v in s["hist"][a][p]["ece"]]
    def g_net(lam):
        return lambda s, a, p: s["hist"][a][p]["net"][lam]

    means = {p: {a: {
        "auroc": round(float(np.mean([v for v in (_auc_over_rounds(s["hist"][a][p]["auroc"]) for s in per_seed) if v is not None])), 4),
        "brier": round(float(np.mean([v for v in (_auc_over_rounds(s["hist"][a][p]["brier"]) for s in per_seed) if v is not None])), 4),
        "ece": round(float(np.mean([v for v in (_auc_over_rounds(s["hist"][a][p]["ece"]) for s in per_seed) if v is not None])), 4),
    } for a in ARMS} for p in POOLS}

    gaps = {p: {
        "auroc": _gap(per_seed, p, g_auroc, n_boot),
        "neg_brier": _gap(per_seed, p, g_negbrier, n_boot),
        "neg_ece": _gap(per_seed, p, g_negece, n_boot),
        "net": {lam: _gap(per_seed, p, g_net(lam), n_boot) for lam in LAMBDAS},
    } for p in POOLS}

    # CALIBRACIÓN PURA pre-registrada: ECE (no rank-invariante). + Brier + NET(λ=3). El veredicto pide ROBUSTEZ en CALIBRACIÓN.
    def _robust_cal(p):
        return (_robust_positive(gaps[p]["neg_ece"]["ls_lo"]) or _robust_positive(gaps[p]["neg_brier"]["ls_lo"])
                or _robust_positive(gaps[p]["net"][PREREG_LAMBDA]["ls_lo"]))
    def _sign_cal(p):
        return (_sign_positive(gaps[p]["neg_ece"]["ls_lo"]) or _sign_positive(gaps[p]["neg_brier"]["ls_lo"])
                or _sign_positive(gaps[p]["net"][PREREG_LAMBDA]["ls_lo"]))
    # ¿la ventaja vive en RANKING (AUROC) pero NO en CALIBRACIÓN (ECE)? -> rank-only (refuta calibración)
    auroc_pos = {p: gaps[p]["auroc"]["ls_lo"]["mean"] > 0 and gaps[p]["auroc"]["ls_lo"]["ci_excludes_zero"] for p in POOLS}
    # ECE = ÚNICA reliability PURA (threshold-free). "ECE no paga" = ls_lo NO mejor calibrado (mean<=0 o CI no excluye 0).
    ece_vanishes = {p: not (gaps[p]["neg_ece"]["ls_lo"]["mean"] > 0 and gaps[p]["neg_ece"]["ls_lo"]["ci_excludes_zero"]) for p in POOLS}

    # NET DEGENERADO (verificación 154, sonda-C): si nadie cruza τ (todos los NET≈0) el NET es CERO ESTRUCTURAL, no evidencia.
    net_level = {p: {a: float(np.mean([v for v in (_auc_over_rounds(s["hist"][a][p]["net"][PREREG_LAMBDA]) for s in per_seed) if v is not None])) for a in ARMS} for p in POOLS}
    net_degenerate = {p: max(abs(net_level[p][a]) for a in ARMS) < 0.01 for p in POOLS}

    # robust_cal: el gate cuenta Brier/NET además de ECE -> GENEROSO hacia APOYADA (Brier/NET contienen resolution=ranking);
    # si aun así no es robusto, refuerza el negativo. La compuerta DURA de reliability es ECE (anclar el veredicto ahí).
    robust_cal = any(_robust_cal(p) for p in POOLS)
    robust_ece = any(_robust_positive(gaps[p]["neg_ece"]["ls_lo"]) for p in POOLS)   # reliability PURA robusta
    sign_cal = any(_sign_cal(p) for p in POOLS)
    rank_only = any(auroc_pos[p] and ece_vanishes[p] for p in POOLS)   # AUROC+ pero ECE no -> la ventaja es RANKING, no reliability

    if robust_ece:
        status = "apoyada"            # APOYADA sólo si la reliability PURA (ECE) paga robusto
    elif rank_only and not sign_cal:
        status = "refutada"
    else:
        status = "mixta"

    ge = gaps["indist"]["neg_ece"]["ls_lo"]; gb = gaps["indist"]["neg_brier"]["ls_lo"]
    gnet = gaps["indist"]["net"][PREREG_LAMBDA]["ls_lo"]; gau = gaps["heldout"]["auroc"]["ls_lo"]
    geh = gaps["heldout"]["neg_ece"]["ls_lo"]
    verdict = (
        "H-V4-9n {V}-de-RELIABILITY (el test DECISIVO del 153: ¿la CALIBRACIÓN-qua-reliability del residuo paga, SEPARADA del "
        "ranking? métrica de reliability PURA = ECE threshold-free, vs AUROC/resolution rank-only): la reliability del ls_lo NO paga "
        "-- ECE plano-a-PEOR en AMBOS pools (indist −ECE {gem} t={get} -ls_lo levemente PEOR-; heldout −ECE {gehm} t={geht}; el durable "
        "también peor). El ÚNICO payoff ROBUSTO del residuo es RANKING (heldout AUROC {gaum} CI {gauci} t={gaut}, disociación limpia "
        "sólo aquí). ACOTACIÓN load-bearing (verificación 154): NO 'todo se desvanece' -- en INDIST −Brier {gbm} (t={gbt}) y NET(λ{pl}) "
        "{gnm} (t={gnt}) SÍ son positivos SUB-ROBUSTOS (CI excl 0, fallan el gate por 6/6/t) PERO son RESOLUTION (discriminación que "
        "co-mueve con AUROC ~0.82), ranking RE-EXPRESADO, no reliability; el NET heldout es DEGENERADO ({nd}, cero estructural -nadie "
        "cruza τ OOD-), NO evidencia. robust_ece={re}, rank_only={ro}. CONCLUSIÓN: {concl}").format(
            V=status.upper(), gem=_f(ge['mean']), get=_f(ge['tstat']), gehm=_f(geh['mean']), geht=_f(geh['tstat']),
            gaum=_f(gau['mean']), gauci=gau['ci95'], gaut=_f(gau['tstat']), gbm=_f(gb['mean']), gbt=_f(gb['tstat']),
            pl=PREREG_LAMBDA, gnm=_f(gnet['mean']), gnt=_f(gnet['tstat']), nd=net_degenerate['heldout'], re=robust_ece, ro=rank_only,
            concl=({"apoyada": "la reliability PURA (ECE) del residuo paga robusto -> toca la tesis 123 en el lazo real desconfundido.",
                    "refutada": "la reliability PURA (ECE) del residuo NO paga (plano-a-peor en ambos pools/lotes); el único payoff robusto es RANKING (AUROC) + RESOLUTION -> el payoff del 153 era ranking re-expresado, no calibración. Cierra el arco downstream 'calibración o ranking?' del lado RANKING -- ACOTADO: N=6 smoke, el label es frágil a lote (un sub-lote daría APOYADA vía Brier/resolution), pendiente réplica N>=12 con barra simétrica + umbral EV-óptimo por-brazo.",
                    "mixta": "parcial: la reliability no paga robusto pero hay trazas magnitude-sensitive (Brier/NET) atribuibles a resolution -> sugestivo, no concluyente."}[status]))

    return {"n": n, "arms": ARMS, "pools": POOLS, "lambdas": LAMBDAS, "prereg_lambda": PREREG_LAMBDA, "t_crit_one_tail_05": round(tcrit, 4),
            "means": means, "auroc_gap": {p: gaps[p]["auroc"] for p in POOLS},
            "neg_ece_gap": {p: gaps[p]["neg_ece"] for p in POOLS}, "neg_brier_gap": {p: gaps[p]["neg_brier"] for p in POOLS},
            "net_gap": {p: {str(lam): gaps[p]["net"][lam] for lam in LAMBDAS} for p in POOLS},
            "net_level": {p: {a: round(net_level[p][a], 4) for a in ARMS} for p in POOLS}, "net_degenerate": net_degenerate,
            "base_rate": {p: round(float(np.mean([s["fixed_ncorrect"][p]/max(1, s["fixed_npool"][p]) for s in per_seed])), 4) for p in POOLS},
            "auroc_pos": auroc_pos, "ece_vanishes": ece_vanishes, "robust_cal": bool(robust_cal), "robust_ece": bool(robust_ece),
            "sign_cal": bool(sign_cal), "rank_only": bool(rank_only), "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=str, default="0-5")
    ap.add_argument("--rounds", type=int, default=4)
    ap.add_argument("--K", type=int, default=8)
    ap.add_argument("--pool", type=int, default=48)
    ap.add_argument("--n_prompts", type=int, default=20)
    ap.add_argument("--neg_per_pos", type=int, default=7)
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

    log("[exp136] CYCLE 154 / H-V4-9n — ¿la CALIBRACIÓN del residuo paga SEPARADA del ranking? (Brier/ECE/NET magnitude-sensitive vs AUROC rank-only)")
    log(f"[exp136] arms={ARMS} seeds={seeds} rounds={args.rounds} lambdas={LAMBDAS} prereg_lambda={PREREG_LAMBDA}")
    per_seed = [run_seed(s, args, test_targets, train_targets, log) for s in seeds]
    sm = build_summary(per_seed, n_boot=n_boot)

    log(f"[exp136] base_rate={sm['base_rate']} robust_cal={sm['robust_cal']} sign_cal={sm['sign_cal']} rank_only={sm['rank_only']} auroc_pos={sm['auroc_pos']} ece_vanishes={sm['ece_vanishes']}")
    for p in POOLS:
        a = sm["auroc_gap"][p]["ls_lo"]; e = sm["neg_ece_gap"][p]["ls_lo"]; b = sm["neg_brier_gap"][p]["ls_lo"]; nt = sm["net_gap"][p][str(PREREG_LAMBDA)]["ls_lo"]
        log(f"[exp136] {p} ls_lo−naive: AUROC {a['mean']:+.3f}(t={a['tstat']}) | −ECE {e['mean']:+.3f}(t={e['tstat']},rob={_robust_positive(e)}) | −Brier {b['mean']:+.3f}(t={b['tstat']}) | NET(λ{PREREG_LAMBDA}) {nt['mean']:+.3f}(t={nt['tstat']})")
    log(f"[exp136] VEREDICTO H-V4-9n: {sm['status'].upper()} | {sm['verdict']}")

    raw = [{"seed": s["seed"], "base_real_acc": round(s["base"].get("real_acc", 0.0), 4),
            "fixed_ncorrect": s["fixed_ncorrect"], "fixed_npool": s["fixed_npool"], "hist": s["hist"]} for s in per_seed]
    out = {"exp": "exp136_calibration_metric", "cycle": 154, "hypothesis": "H-V4-9n",
           "claim": "El test DECISIVO del 153 (su payoff era rank-only=AUROC re-expresado): ¿la CALIBRACIÓN del residuo genérico (ls_lo) "
                    "paga SEPARADA del ranking? Métricas SENSIBLES A MAGNITUDES (Brier, ECE=calibración pura, NET umbral-abstención "
                    "cost-weighted) vs AUROC rank-only, sobre el pool fijo escaso del 153. APOYADA-calibración si ls_lo tiene ventaja "
                    "robusta en ECE/Brier/NET; REFUTADA-calibración si la ventaja vive en AUROC pero se desvanece en calibración "
                    "(ranking re-expresado); MIXTA si parcial.",
           "verdict": sm["status"], "summary": sm, "raw": raw, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__, "torch": torch.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp136] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
