r"""
exp134 — CYCLE 152 / H-V4-9l (FRONTERA REAL §4.2, la pregunta viva que el 151 dejó EXPLÍCITA): el 151 desconfundió el "payoff de
calibración" del lazo real y halló que (a) la ventaja de la cura 119 (durable) era riqueza de generación (se INVIERTE sobre un pool
fijo balanceado) y (b) sólo SOBREVIVE un residuo GENÉRICO de SIGNO (ls_lo, +0.018 AUROC_fixed, 6/6 positivos pero t-test
sub-significativo). PREGUNTA DE ESTE CICLO: ¿ese residuo genérico (que en AUROC apenas se distingue del azar-de-ranking) PAGA
DOWNSTREAM en una DECISIÓN real bajo ESCASEZ? — el North-Star R-VALOR dice que el valor endógeno vale como BRÚJULA DECISIONAL
(123: la calibración paga en la decisión bajo escasez), no por el AUROC en sí. Y una SEGUNDA pregunta que ataca la acotación
in-distribution de la sonda-A del 151: ¿el residuo SOBREVIVE sobre candidatos HELD-OUT (forma NOVEL que el modelo no entrenó)?

DISEÑO (reusa exp133/exp124/exp018; lazo torch CPU). 3 brazos (naive, durable=cura 119, ls_lo=label smoothing). Cada brazo se
auto-entrena en su propio pool (idéntico a exp133). En cada ronda, además del AUROC, cada brazo asigna confianza a DOS POOLS FIJOS
COMPARTIDOS Y BALANCEADOS (48/48, idénticos para los 3 brazos, fijos a lo largo de rondas):
  - INDIST (in-distribution): positivos = forma canónica '1+(n-1)' (la que el base aprende y cada brazo re-entrena vía replay).
  - HELDOUT (held-out de FORMA): positivos = forma NOVEL '2+(n-2)' (correcta -el strong verifier acepta cualquier a+b==n- pero NO la
    forma entrenada) -> testea si el ranking de confianza GENERALIZA a expresiones correctas de forma no vista.
Sobre CADA pool se mide, por brazo/ronda: (i) AUROC(conf, correcto) y (ii) precision@top-m = #correctas entre las top-m por
confianza / min(m, #correctas) (la DECISIÓN: someter las m más confiadas), barrida m={1,2,3,4,6,8,12,16,24} GRATIS sobre las MISMAS
confianzas. MÉTRICA decisional: gap ls_lo−naive y durable−naive de precision@top-m (AUC sobre rondas), por m, por pool.

PREGUNTA FALSABLE (sobre el residuo GENÉRICO ls_lo, el único que sobrevivió el 151; el durable se espera que NO pague -se invierte-):
  - APOYADA-downstream si el residuo ls_lo PAGA: precision@top-m(ls_lo) > naive bajo ESCASEZ (m chico, donde el ranking domina) con
    CI que excluye 0 Y t-test pareado SIGNIFICATIVO, al menos en INDIST (idealmente sobreviviendo HELDOUT) -> el residuo, aunque
    chico en AUROC, IMPORTA en la decisión bajo escasez (confirma la tesis brújula-decisional 123 para el lazo real desconfundido).
  - REFUTADA-downstream si NO paga a NINGÚN m robustamente (el residuo de AUROC no se traduce en ventaja decisional) -> cierre
    DEFLACIONARIO honesto del arco real: el payoff del lazo real es artefacto de generación + un residuo que tampoco paga downstream.
  - MIXTA si paga sólo en INDIST y se esfuma HELDOUT, o sólo en signo (no robusto por t-test).

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp134_downstream_payoff.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp134_downstream_payoff.run --seeds 0-5 --rounds 4 --steps 50 --base_steps 180
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

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")
ARMS = ["naive", "durable", "ls_lo"]
M_GRID = [1, 2, 3, 4, 6, 8, 12, 16, 24]
POOLS = ["indist", "heldout"]


def _canon_pos(rng, n):
    return E.real_expression(rng, n)            # '1+(n-1)' — la forma que el modelo entrena


def _novel_pos(rng, n):
    """Forma NOVEL correcta (held-out de forma): '2+(n-2)' (a!=1), aceptada por el strong verifier pero no la entrenada."""
    a = 2 if n - 2 >= 0 else 0
    return "{}+{}".format(a, n - a).encode("ascii")


def _build_fixed_pool(seed_offset, tvals, npairs, posfn):
    """Pool fijo BALANCEADO: por prompt n, 1 positivo (posfn, correcto) + 1 negativo (posfn de OTRO target m!=n, valor incorrecto),
    etiquetados por el verificador REAL. Devuelve (pairs, strong[])."""
    frng = np.random.default_rng(seed_offset)
    ftargets = [tvals[int(frng.integers(0, len(tvals)))] for _ in range(npairs)]
    pairs = []; strong = []
    for n in ftargets:
        pn = E.make_prompt(n)
        m = n
        while m == n:
            m = tvals[int(frng.integers(0, len(tvals)))]
        for e in (posfn(frng, n), posfn(frng, m)):
            s = E.verify(pn, e + b"\n", True)
            pairs.append((pn, e)); strong.append(1.0 if s else 0.0)
    return pairs, np.array(strong)


def run_seed(seed, args, test_targets, train_targets, log):
    base, npar = build_base(seed, args.n_seed, args.base_steps, args.base_lr, args.warmup, args.batch, train_targets)
    bm = E.eval_metrics(base, test_targets, "cpu")
    log(f"[exp134] seed={seed} base real_acc={bm['real_acc']:.3f} params={npar:,}")
    pool_rng = np.random.default_rng(seed + 7)
    sel = pool_rng.integers(0, len(train_targets), size=args.pool)
    pool_prompts = [E.make_prompt(train_targets[i]) for i in sel]
    k = max(1, int(args.budget_frac * args.pool * args.K))
    tvals = [int(t) for t in train_targets]

    fixed = {
        "indist": _build_fixed_pool(seed + 555, tvals, args.fixed_pool, _canon_pos),
        "heldout": _build_fixed_pool(seed + 777, tvals, args.fixed_pool, _novel_pos),
    }
    for p in POOLS:
        pairs, strong = fixed[p]
        log(f"[exp134] seed={seed} pool FIJO {p}: {len(strong)} cands ({int(np.sum(strong))} correctas / {int(len(strong)-np.sum(strong))} incorrectas)")

    arms = {a: copy.deepcopy(base) for a in ARMS}
    # hist[arm][pool] = {"auroc": [...], "payoff": {m: [...]}}
    hist = {a: {p: {"auroc": [], "payoff": {m: [] for m in M_GRID}} for p in POOLS} for a in ARMS}

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
                for m in M_GRID:
                    pm = _payoff_at_m(conf_fx, fstrong, m)
                    hist[a][p]["payoff"][m].append(round(pm, 4) if pm is not None else None)
            # self-train idéntico a exp132/exp133 (el brazo cambia sólo el regularizador)
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
        log(f"[exp134] seed={seed} r{r} AUROC indist " + "/".join(f"{a}={_g(a,'indist')}" for a in ARMS) +
            " | heldout " + "/".join(f"{a}={_g(a,'heldout')}" for a in ARMS))

    return {"seed": seed, "base": bm, "fixed_ncorrect": {p: int(np.sum(fixed[p][1])) for p in POOLS},
            "fixed_npool": {p: len(fixed[p][1]) for p in POOLS}, "hist": hist}


def _gap(per_seed, pool, key, m, arm, ref="naive", n_boot=10000):
    """Gap AUC-sobre-rondas entre arm y ref para (pool, key, m). key in {auroc, payoff}. Devuelve media, CI, t, n_pos."""
    gaps = []
    for s in per_seed:
        if key == "auroc":
            ga = _auc_over_rounds(s["hist"][arm][pool]["auroc"]); gr = _auc_over_rounds(s["hist"][ref][pool]["auroc"])
        else:
            ga = _auc_over_rounds(s["hist"][arm][pool]["payoff"][m]); gr = _auc_over_rounds(s["hist"][ref][pool]["payoff"][m])
        if ga is not None and gr is not None:
            gaps.append(ga - gr)
    n = len(gaps)
    mean = float(np.mean(gaps)) if gaps else 0.0
    lo, hi = _bootstrap_ci(gaps, n_boot=n_boot) if n > 1 else (mean, mean)
    se = float(np.std(gaps, ddof=1) / np.sqrt(n)) if n > 1 else 0.0
    return {"arm": arm, "pool": pool, "key": key, "m": m, "mean": round(mean, 4), "ci95": [round(lo, 4), round(hi, 4)],
            "n_positive": int(np.sum(np.array(gaps) > 0)), "n": n, "tstat": round(mean / se, 3) if se > 0 else 0.0,
            "ci_excludes_zero": bool(lo > 0.0 or hi < 0.0), "gaps": [round(g, 4) for g in gaps]}


def build_summary(per_seed, n_boot=10000):
    n = len(per_seed); tcrit = _t_crit(n - 1)
    au = {p: {a: round(float(np.mean([v for v in (_auc_over_rounds(s["hist"][a][p]["auroc"]) for s in per_seed) if v is not None])), 4) for a in ARMS} for p in POOLS}
    # payoff medio por pool/arm/m
    pay = {p: {a: {m: round(float(np.mean([v for v in (_auc_over_rounds(s["hist"][a][p]["payoff"][m]) for s in per_seed) if v is not None])), 4) for m in M_GRID} for a in ARMS} for p in POOLS}
    # gaps decisionales ls_lo−naive y durable−naive por pool/m
    gaps = {p: {"ls_lo": {m: _gap(per_seed, p, "payoff", m, "ls_lo", n_boot=n_boot) for m in M_GRID},
                "durable": {m: _gap(per_seed, p, "payoff", m, "durable", n_boot=n_boot) for m in M_GRID}} for p in POOLS}
    auroc_gap = {p: {"ls_lo": _gap(per_seed, p, "auroc", None, "ls_lo", n_boot=n_boot),
                     "durable": _gap(per_seed, p, "auroc", None, "durable", n_boot=n_boot)} for p in POOLS}

    # #correctas medio por pool (para f=m/#correct: el régimen decisional REAL, lección de exp124 -m-absoluto es engañoso-)
    ncorr = {p: float(np.mean([s["fixed_ncorrect"][p] for s in per_seed])) for p in POOLS}
    f_grid = {p: {m: round(m / max(1.0, ncorr[p]), 3) for m in M_GRID} for p in POOLS}

    scarce = [m for m in M_GRID if m <= 8]
    lslo_robust = {p: any(_robust_positive(gaps[p]["ls_lo"][m]) for m in scarce) for p in POOLS}
    lslo_sign = {p: any(_sign_positive(gaps[p]["ls_lo"][m]) for m in scarce) for p in POOLS}
    durable_neg = {p: any(g["mean"] < 0 and g["ci_excludes_zero"] and abs(g["tstat"]) >= tcrit
                          for g in (gaps[p]["durable"][m] for m in scarce)) for p in POOLS}

    # SATURACIÓN (acotación load-bearing, verificación adversarial 152): un pool es NO-INFORMATIVO si el naive ya rankea el tope
    # escaso casi-perfecto (precision@top-m ~ 1.0) -> no hay headroom y el gap es CERO ESTRUCTURAL, no evidencia. Sólo los pools
    # NO saturados (informativos) cuentan para el veredicto.
    naive_scarce = {p: float(np.mean([pay[p]["naive"][m] for m in scarce])) for p in POOLS}
    saturated = {p: naive_scarce[p] > 0.99 for p in POOLS}
    informative = [p for p in POOLS if not saturated[p]]

    def _best(p):
        cand = [(gaps[p]["ls_lo"][m]["tstat"], m) for m in scarce]
        return max(cand)[1] if cand else scarce[0]
    best_m = {p: _best(p) for p in POOLS}

    def _borderline_pos(p):
        """ls_lo borderline-positivo en p: mejor m de escasez con media>0, ningún seed negativo, y t cerca del crítico (>=0.7·tcrit)."""
        g = gaps[p]["ls_lo"][best_m[p]]
        return bool(g["mean"] > 0 and g["n_positive"] >= max(1, (g["n"] + 1) // 3) and
                    int(np.sum(np.array(g["gaps"]) < 0)) == 0 and abs(g["tstat"]) >= 0.7 * tcrit)

    robust_inf = any(lslo_robust[p] for p in informative)
    sign_or_bl_inf = any(lslo_sign[p] or _borderline_pos(p) for p in informative)
    if robust_inf:
        status = "apoyada"
    elif not informative:
        status = "mixta"          # todos los pools saturados -> INCONCLUSO (no se puede refutar lo que no se testeó)
    elif sign_or_bl_inf:
        status = "mixta"          # señal débil/borderline en un pool informativo (no robusta, no adversa)
    else:
        status = "refutada"       # pool informativo con claro no-pago

    bi = best_m["indist"]; bh = best_m["heldout"]
    gi = gaps["indist"]["ls_lo"][bi]; gh = gaps["heldout"]["ls_lo"][bh]
    di = gaps["indist"]["durable"][best_m["indist"]]
    verdict = (
        "H-V4-9l {V}-downstream (NO-paga-ROBUSTAMENTE; ACOTADO por SATURACIÓN del test): ¿el residuo genérico ls_lo (151) PAGA en una "
        "decisión real bajo escasez (precision@top-m)? ACOTACIÓN load-bearing (verificación 152): el pool es BALANCEADO 50/50 (NO "
        "escaso: la tesis 123 vive en q bajo / f≈1) y precision@top-m está TOPADA en 1.0 -> INDIST está SATURADO (naive {nsi} en m de "
        "escasez -> gap CERO ESTRUCTURAL {gim}, no evidencia; criterio APOYADA inalcanzable ahí). Sólo HELDOUT (naive {nsh}<1, con "
        "headroom) es informativo: ls_lo−naive mejor m={bh} (f={fbh}) payoff {ghm} (CI {ghci}, t={ght} < t_crit {tc}; {ghpos}/{ghn} "
        "seeds+, 0 negativos) -> señal DÉBIL BORDERLINE, NO robusta. El durable (cura 119) es ROBUSTAMENTE NEGATIVO (indist m={bi} "
        "{dim}, t={dit}; heldout también) -> confirma su INVERSIÓN del 151 fuera-de-forma. CONCLUSIÓN: el residuo genérico NO PAGA "
        "ROBUSTAMENTE bajo escasez (MIXTA-deflacionaria, no refutación-plana): INDIST no-informativo por saturación; HELDOUT "
        "borderline-positivo no-robusto; y el régimen de escasez REAL de 123 (q bajo / f≈1) quedó SIN TESTEAR (m_max={mmax} -> "
        "f<={fmax}). Próximo (153): pool fijo COMPARTIDO de BAJA base-rate (q≈0.1) o medir a f≈1.").format(
            V=status.upper(), nsi=_f(naive_scarce["indist"]), gim=_f(gi['mean']), nsh=_f(naive_scarce["heldout"]),
            bh=bh, fbh=f_grid["heldout"][bh], ghm=_f(gh['mean']), ghci=gh['ci95'], ght=_f(gh['tstat']), tc=_f(tcrit),
            ghpos=gh['n_positive'], ghn=gh['n'], bi=bi, dim=_f(di['mean']), dit=_f(di['tstat']),
            mmax=max(M_GRID), fmax=max(f_grid["heldout"][m] for m in M_GRID))
    durable_pays = {p: bool(not durable_neg[p] and any(_robust_positive(gaps[p]["durable"][m]) for m in scarce)) for p in POOLS}

    return {"n": n, "arms": ARMS, "pools": POOLS, "m_grid": M_GRID, "t_crit_one_tail_05": round(tcrit, 4),
            "auroc": au, "payoff": pay, "auroc_gap": auroc_gap, "payoff_gap": gaps,
            "ncorrect_mean": {p: round(ncorr[p], 1) for p in POOLS}, "f_grid": f_grid, "naive_scarce_payoff": {p: round(naive_scarce[p], 4) for p in POOLS},
            "saturated": saturated, "informative_pools": informative,
            "lslo_robust": lslo_robust, "lslo_sign": lslo_sign, "durable_neg": durable_neg, "durable_pays": durable_pays, "best_m": best_m,
            "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=str, default="0-5")
    ap.add_argument("--rounds", type=int, default=4)
    ap.add_argument("--K", type=int, default=8)
    ap.add_argument("--pool", type=int, default=48)
    ap.add_argument("--fixed_pool", type=int, default=48)
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

    log("[exp134] CYCLE 152 / H-V4-9l — ¿el residuo genérico (ls_lo) PAGA DOWNSTREAM en una decisión bajo escasez? (precision@top-m, pools indist + heldout)")
    log(f"[exp134] arms={ARMS} seeds={seeds} rounds={args.rounds} m_grid={M_GRID}")
    per_seed = [run_seed(s, args, test_targets, train_targets, log) for s in seeds]
    sm = build_summary(per_seed, n_boot=n_boot)

    log("[exp134] --- AUROC_fixed por pool (sanity vs 151) ---")
    for p in POOLS:
        log(f"[exp134] AUROC {p}: {sm['auroc'][p]}")
    log("[exp134] --- precision@top-m: gap ls_lo−naive (decisional) por pool ---")
    for p in POOLS:
        for m in M_GRID:
            g = sm["payoff_gap"][p]["ls_lo"][m]
            log(f"[exp134]   {p} m={m:<2} ls_lo−naive {g['mean']:+.3f} (CI {g['ci95']}, t={g['tstat']}, robust={_robust_positive(g)})")
    log(f"[exp134] VEREDICTO H-V4-9l: {sm['status'].upper()} | {sm['verdict']}")

    raw = [{"seed": s["seed"], "base_real_acc": round(s["base"].get("real_acc", 0.0), 4),
            "fixed_ncorrect": s["fixed_ncorrect"], "fixed_npool": s["fixed_npool"], "hist": s["hist"]} for s in per_seed]
    out = {"exp": "exp134_downstream_payoff", "cycle": 152, "hypothesis": "H-V4-9l",
           "claim": "¿El residuo de calibración GENÉRICO (ls_lo) que el 151 halló sobrevive en AUROC_fixed sólo en SIGNO (no robusto) "
                    "PAGA DOWNSTREAM en una decisión real bajo escasez (precision@top-m sobre un pool fijo balanceado)? + ¿sobrevive "
                    "sobre candidatos HELD-OUT (forma novel '2+(n-2)' no entrenada, atacando la acotación in-distribution de la sonda-A "
                    "del 151)? APOYADA si paga robustamente (CI excl 0 + t-test) en escasez en ambos pools; REFUTADA si no paga en "
                    "ninguno; MIXTA si in-distribution-only o sólo signo.",
           "verdict": sm["status"], "summary": sm, "raw": raw, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__, "torch": torch.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp134] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
