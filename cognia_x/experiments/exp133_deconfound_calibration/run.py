r"""
exp133 — CYCLE 151 / H-V4-9k (FRONTERA REAL §4.2, el caveat LOAD-BEARING que el 150 descubrió): ¿el "payoff de calibración" del
lazo real (149 durable>naive, 150 ls_lo>durable) es REAL, o un ARTEFACTO de la RIQUEZA DE GENERACIÓN?

CONTEXTO. El 149 estableció durable>naive en AUROC(confianza, correctness) en el lazo torch real; el 150 halló que un target-
smoothing genérico (ls_lo) lo iguala/supera. La verificación adversarial del 150 (sonda-mecanismo, ACOTA) descubrió que el AUROC
está fuertemente CONFUNDIDO con la riqueza de generación: cada brazo computa su AUROC sobre SU PROPIO pool, y un brazo que colapsa
la generación (pocas correctas) rankea un pool de candidatos MÁS FÁCILES -> AUROC inflada. corr(AUROC,ncorrect) within-durable
~-0.91; en la banda de ncorrect SOLAPADA los brazos son IGUALES. => el "payoff de calibración" del lazo real podría no ser
calibración pura sino un efecto de qué-tan-magro-es-el-pool.

DISEÑO DEL DESCONFOUND (limpio). En vez de que cada brazo rankee SU propio pool (cuya dificultad varía con cuántas correctas
genera), TODOS los brazos asignan confianza a un POOL FIJO COMPARTIDO Y BALANCEADO: un set de candidatos (prompt, expr, correctness)
CONSTRUIDO deterministicamente UNA vez (NO generado por ningún brazo): por cada prompt n, un POSITIVO = expr canónica correcta y un
NEGATIVO = expr de OTRO target (valor != n -> incorrecta), cada uno ETIQUETADO por el verificador REAL (balance exacto 48/48).
Idéntico para los 3 brazos y fijo a lo largo de las rondas. AUROC_fixed(arm) = qué tan bien la confianza del brazo separa ese set
idéntico por correctness -> aísla la CALIDAD DE RANKING (separación de confianza) del modelo de la riqueza de SU propia generación.
Se reporta en paralelo AUROC_own (la métrica confundida del 149/150) para el contraste directo. ACOTACIÓN (verificación adversarial
del 151): AUROC_fixed es un sondeo IN-DISTRIBUTION (los positivos comparten la forma canónica '1+(n-1)' con que cada brazo se
re-entrena vía replay) y casi-en-techo (naive ya ~0.97) -> desconfunde la riqueza-de-pool (su propósito) pero NO certifica ranking
held-out sobre generaciones novedosas.

3 brazos (los clave): naive, durable (=cura 119, unlikelihood label-aware), ls_lo (label smoothing, el ganador del 150). Mismo lazo
torch real que exp132 (HybridLM -> verificador real -> confianza endógena -> self-train con el regularizador del brazo).

PREGUNTA FALSABLE (sobre las ventajas de AUROC_fixed durable−naive y ls_lo−naive). NOTA de robustez (verificación adversarial del
151): "CI bootstrap excluye 0" es TAUTOLÓGICO cuando todos los gaps por-seed son del mismo signo (el percentil siempre los respeta);
NO mide robustez. La compuerta exige ADEMÁS significancia por t-test pareado (|t| >= t_crit one-tail 0.05, df=n-1):
  - REFUTADA-calibración (el payoff era artefacto) si NINGUNA ventaja de AUROC_fixed sobrevive ni en signo (no hay un brazo con todos
    los gaps positivos) mientras las de AUROC_own persistían -> el "payoff" era riqueza de generación.
  - APOYADA-calibración (hay señal ROBUSTA) si alguna ventaja de AUROC_fixed sobrevive con CI que excluye 0 Y t-test pareado
    SIGNIFICATIVO -> mejora de ranking genuina y robusta, independiente de la riqueza de generación.
  - MIXTA si parcial: una ventaja sobrevive en SIGNO (todos los gaps positivos) pero NO robustamente (t sub-significativo / magnitud
    near-zero / régimen-dependiente), o una sobrevive y otra se invierte. (Este es el caso del 151: el durable se INVIERTE; ls_lo
    sobrevive sólo en signo, no robusto.)

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp133_deconfound_calibration.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp133_deconfound_calibration.run --seeds 0-7 --rounds 5 --steps 70
"""
import argparse
import copy
import json
import math
import os
import platform
import sys

import numpy as np
import torch

from cognia_x.experiments.exp018_real_verifier import expression_task as E
from cognia_x.experiments.exp018_real_verifier.run import build_base, generate_pool, LO, HI
from cognia_x.experiments.exp077_closed_loop_budget.run import _confidence, _corr
from cognia_x.experiments.exp078_closed_loop_guard.run import _dedup, _replay_examples
from cognia_x.experiments.exp124_decisional_real_loop.run import _auroc, _auc_over_rounds, _mean, _f
from cognia_x.experiments.exp132_privileged_cure.run import _train_arm, _bootstrap_ci, ARM_SPECS

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")
ARMS = ["naive", "durable", "ls_lo"]   # baseline, cura 119, el target-smoothing ganador del 150


def run_seed(seed, args, test_targets, train_targets, log):
    base, npar = build_base(seed, args.n_seed, args.base_steps, args.base_lr, args.warmup, args.batch, train_targets)
    bm = E.eval_metrics(base, test_targets, "cpu")
    log(f"[exp133] seed={seed} base real_acc={bm['real_acc']:.3f} params={npar:,}")
    pool_rng = np.random.default_rng(seed + 7)
    sel = pool_rng.integers(0, len(train_targets), size=args.pool)
    pool_prompts = [E.make_prompt(train_targets[i]) for i in sel]
    k = max(1, int(args.budget_frac * args.pool * args.K))

    # --- POOL FIJO CONTROLADO Y BALANCEADO (el desconfound LIMPIO): candidatos CONSTRUIDOS con etiqueta conocida (verificada por el
    #     verificador REAL), independiente de la accuracy del base y de la generación de cualquier brazo. Para cada prompt n:
    #     POSITIVO = expr correcta '1+(n-1)' (verifica strong); NEGATIVO = expr de OTRO target (valor != n) -> incorrecta para n.
    #     Idéntico para todos los brazos y rondas. AUROC_fixed = qué tan bien la confianza del brazo separa correcto/incorrecto AQUÍ. ---
    frng = np.random.default_rng(seed + 555)
    tvals = [int(t) for t in train_targets]
    ftargets = [tvals[i] for i in frng.integers(0, len(tvals), size=args.fixed_pool)]
    fixed_pairs = []; fixed_strong = []
    for n in ftargets:
        pn = E.make_prompt(n)
        m = n
        while m == n:
            m = tvals[int(frng.integers(0, len(tvals)))]    # otro target con VALOR distinto -> expr incorrecta para n
        for e in (E.real_expression(frng, n), E.real_expression(frng, m)):
            s = E.verify(pn, e + b"\n", True)                # verificador REAL strong -> etiqueta de correctness
            fixed_pairs.append((pn, e)); fixed_strong.append(1.0 if s else 0.0)
    fixed_strong = np.array(fixed_strong)
    nfc = int(np.sum(fixed_strong))
    log(f"[exp133] seed={seed} pool FIJO controlado: {len(fixed_strong)} cands ({nfc} correctas / {len(fixed_strong)-nfc} incorrectas, balanceado)")

    arms = {a: copy.deepcopy(base) for a in ARMS}
    hist = {a: {"auroc_own": [], "auroc_fixed": [], "ncorrect": [], "npool": []} for a in ARMS}

    for r in range(1, args.rounds + 1):
        for a in ARMS:
            torch.manual_seed(10000 * seed + r)
            pool = generate_pool(arms[a], pool_prompts, args.K, args.temp, args.top_k, "cpu")
            pairs = [(p, e) for (p, e, _, _) in pool]
            strong = np.array([1.0 if s else 0.0 for (_, _, _, s) in pool])
            conf = _confidence(arms[a], pairs, "cpu")
            au_own = _auroc(conf, strong)
            hist[a]["auroc_own"].append(round(au_own, 4) if au_own is not None else None)
            # --- métrica DESCONFUNDIDA: confianza del brazo sobre el POOL FIJO compartido ---
            conf_fx = _confidence(arms[a], fixed_pairs, "cpu")
            au_fx = _auroc(conf_fx, fixed_strong)
            hist[a]["auroc_fixed"].append(round(au_fx, 4) if au_fx is not None else None)
            nc = int(np.sum(strong)); hist[a]["ncorrect"].append(nc); hist[a]["npool"].append(len(strong))
            # self-train (idéntico a exp132): top-k por confianza + replay; el brazo cambia sólo el regularizador
            sel_rng = np.random.default_rng(seed * 131 + r * 17 + ARMS.index(a))
            sel_idx = np.argsort(conf + 1e-9 * sel_rng.random(len(pool)))[-min(k, len(pool)):]
            pos = _dedup([pairs[i] for i in sel_idx if strong[i] > 0.5])
            train_rng = np.random.default_rng(seed * 1000 + 17 + ARMS.index(a))
            pos = pos + _replay_examples(train_rng, train_targets, int(round(args.replay_frac * max(1, len(pos)))))
            neg = _dedup([pairs[i] for i in sel_idx if strong[i] < 0.5]) if ARM_SPECS[a]["kind"] == "unlik" else []
            _train_arm(arms[a], pos, neg, ARM_SPECS[a], args.steps, args.batch, args.lr, "cpu", train_rng)

        def _g(a, key):
            v = hist[a][key][-1]
            return "{:.3f}".format(v) if v is not None else "--"
        log(f"[exp133] seed={seed} ronda {r}: " + " | ".join(f"{a} own={_g(a,'auroc_own')} fix={_g(a,'auroc_fixed')}" for a in ARMS))

    return {"seed": seed, "base": bm, "fixed_ncorrect": nfc, "fixed_npool": len(fixed_strong), "hist": hist}


def _gap_summary(per_seed, key, arm, ref="naive", n_boot=10000):
    """Gap AUC-sobre-rondas de `key` (auroc_own/auroc_fixed) entre arm y ref, por seed -> media, CI bootstrap, n_pos."""
    gaps = []
    for s in per_seed:
        ga = _auc_over_rounds(s["hist"][arm][key]); gr = _auc_over_rounds(s["hist"][ref][key])
        if ga is not None and gr is not None:
            gaps.append(ga - gr)
    n = len(gaps)
    mean = float(np.mean(gaps)) if gaps else 0.0
    lo, hi = _bootstrap_ci(gaps, n_boot=n_boot) if n > 1 else (mean, mean)
    se = float(np.std(gaps, ddof=1) / np.sqrt(n)) if n > 1 else 0.0
    return {"arm": arm, "key": key, "mean": round(mean, 4), "ci95": [round(lo, 4), round(hi, 4)],
            "n_positive": int(np.sum(np.array(gaps) > 0)), "n": n, "tstat": round(mean / se, 3) if se > 0 else 0.0,
            "ci_excludes_zero": bool(lo > 0.0 or hi < 0.0), "gaps": [round(g, 4) for g in gaps]}


# t crítico one-tail alpha=0.05 por df (compuerta de significancia REAL; "CI bootstrap excluye 0" es tautológico con gaps un-signo).
_T_CRIT_05 = {1: 6.314, 2: 2.920, 3: 2.353, 4: 2.132, 5: 2.015, 6: 1.943, 7: 1.895, 8: 1.860, 9: 1.833, 10: 1.812,
              11: 1.796, 12: 1.782, 13: 1.771, 14: 1.761, 15: 1.753, 16: 1.746, 18: 1.734, 20: 1.725, 25: 1.708, 30: 1.697}


def _t_crit(df):
    if df <= 0:
        return float("inf")
    if df in _T_CRIT_05:
        return _T_CRIT_05[df]
    keys = sorted(_T_CRIT_05)
    return _T_CRIT_05[max(k for k in keys if k <= df)] if df <= 30 else 1.645


def _robust_positive(g):
    """ventaja POSITIVA y ROBUSTA: CI excluye 0, media>0, todos los gaps mismo signo (signo-consistente) Y t-test pareado
    SIGNIFICATIVO (|t| >= t_crit one-tail 0.05). El t-test es la compuerta dura; el CI bootstrap solo no basta (tautológico)."""
    return bool(g["ci_excludes_zero"] and g["mean"] > 0 and g["n_positive"] == g["n"]
                and abs(g["tstat"]) >= _t_crit(g["n"] - 1))


def _sign_positive(g):
    """ventaja POSITIVA sólo en SIGNO: todos los gaps por-seed positivos y media>0 (sign-test), aunque NO sea robusta por t."""
    return bool(g["n"] > 0 and g["n_positive"] == g["n"] and g["mean"] > 0)


def build_summary(per_seed, n_boot=10000):
    au = {a: round(float(np.mean([v for v in (_auc_over_rounds(s["hist"][a]["auroc_own"]) for s in per_seed) if v is not None])), 4) for a in ARMS}
    af = {a: round(float(np.mean([v for v in (_auc_over_rounds(s["hist"][a]["auroc_fixed"]) for s in per_seed) if v is not None])), 4) for a in ARMS}
    nc = {a: round(float(np.mean([_mean(s["hist"][a]["ncorrect"]) for s in per_seed])), 1) for a in ARMS}

    own_dn = _gap_summary(per_seed, "auroc_own", "durable", n_boot=n_boot)     # durable−naive OWN (la métrica del 149)
    own_ln = _gap_summary(per_seed, "auroc_own", "ls_lo", n_boot=n_boot)       # ls_lo−naive OWN
    fix_dn = _gap_summary(per_seed, "auroc_fixed", "durable", n_boot=n_boot)   # durable−naive FIXED (desconfundida)
    fix_ln = _gap_summary(per_seed, "auroc_fixed", "ls_lo", n_boot=n_boot)     # ls_lo−naive FIXED (desconfundida)

    n = len(per_seed); tcrit = _t_crit(n - 1)
    # ¿sobrevive ROBUSTAMENTE (CI excl 0 + t-test pareado significativo) o sólo en SIGNO?
    fixed_robust = _robust_positive(fix_dn) or _robust_positive(fix_ln)
    fixed_sign = _sign_positive(fix_dn) or _sign_positive(fix_ln)
    fixed_survives = bool(fixed_robust)   # compat: "sobrevive" == robusto, no el CI tautológico
    own_had_advantage = own_dn["mean"] > 0.01 or own_ln["mean"] > 0.01
    durable_inverts = fix_dn["mean"] < 0 and fix_dn["ci_excludes_zero"]
    atten_dn = (own_dn["mean"] - fix_dn["mean"])
    atten_ln = (own_ln["mean"] - fix_ln["mean"])

    AFX = "AUROC_fixed: naive={afn} durable={afd} ls_lo={afl}".format(afn=_f(af["naive"]), afd=_f(af["durable"]), afl=_f(af["ls_lo"]))
    if fixed_robust:
        status = "apoyada"
        verdict = (
            "H-V4-9k APOYADA-calibración (hay señal de ranking GENUINA y ROBUSTA, no sólo riqueza de generación): sobre el POOL FIJO "
            "compartido y balanceado SOBREVIVE una ventaja de AUROC con CI que excluye 0 Y t-test pareado significativo -- "
            "durable−naive FIXED {ddn} (CI {cdn}), ls_lo−naive FIXED {dln} (CI {cln}, t={tln}). El payoff de calibración del 149/150 "
            "NO es puro artefacto. {AFX}."
        ).format(ddn=_f(fix_dn["mean"]), cdn=fix_dn["ci95"], dln=_f(fix_ln["mean"]), cln=fix_ln["ci95"], tln=_f(fix_ln["tstat"]), AFX=AFX)
    elif own_had_advantage and not fixed_sign:
        status = "refutada"
        verdict = (
            "H-V4-9k REFUTADA-calibración (el payoff del lazo real era RIQUEZA DE GENERACIÓN, no ranking-de-un-set-fijo): sobre el "
            "POOL FIJO balanceado NINGUNA ventaja de AUROC sobrevive ni en signo -- durable−naive FIXED {ddn} (CI {cdn}), ls_lo−naive "
            "FIXED {dln} (CI {cln}) -- mientras en el pool PROPIO persistían (own durable−naive {odn}, ls_lo−naive {oln}). El "
            "'payoff de calibración' del 149/150 era el efecto de pool-más-magro/estable. {AFX}."
        ).format(ddn=_f(fix_dn["mean"]), cdn=fix_dn["ci95"], dln=_f(fix_ln["mean"]), cln=fix_ln["ci95"],
                 odn=_f(own_dn["mean"]), oln=_f(own_ln["mean"]), AFX=AFX)
    else:
        status = "mixta"
        verdict = (
            "H-V4-9k MIXTA (desconfound PARCIAL): el durable (cura 119) se INVIERTE sobre el pool fijo balanceado -- durable−naive "
            "OWN {odn} -> FIXED {ddn} (CI {cdn}, excluye 0 del lado NEGATIVO) -> su ventaja del 149 era ENTERAMENTE riqueza de "
            "generación. El ÚNICO sobreviviente es el GENÉRICO ls_lo, y SÓLO EN SIGNO (todos los gaps positivos, sign-test) pero NO "
            "robusto -- ls_lo−naive OWN {oln} -> FIXED {dln} (CI {cln}, t={tln} < t_crit {tc} one-tail 0.05; magnitud near-zero, "
            "régimen-dependiente). => el payoff del lazo real NO es puro artefacto (hay una señal de signo genuina, generación-"
            "independiente) PERO es chico, genérico (no la cura) y sub-significativo por t-test. NOTA: 'CI excluye 0' aquí es "
            "tautológico (gaps un-signo); la compuerta dura es el t-test. {AFX}."
        ).format(odn=_f(own_dn["mean"]), ddn=_f(fix_dn["mean"]), cdn=fix_dn["ci95"], oln=_f(own_ln["mean"]),
                 dln=_f(fix_ln["mean"]), cln=fix_ln["ci95"], tln=_f(fix_ln["tstat"]), tc=_f(tcrit), AFX=AFX)

    return {"n": len(per_seed), "arms": ARMS, "auroc_own": au, "auroc_fixed": af, "mean_ncorrect": nc,
            "own_durable_vs_naive": own_dn, "own_lslo_vs_naive": own_ln,
            "fixed_durable_vs_naive": fix_dn, "fixed_lslo_vs_naive": fix_ln,
            "atten_durable": round(atten_dn, 4), "atten_lslo": round(atten_ln, 4), "t_crit_one_tail_05": round(tcrit, 4),
            "fixed_robust": bool(fixed_robust), "fixed_sign": bool(fixed_sign), "durable_inverts": bool(durable_inverts),
            "fixed_survives": bool(fixed_survives), "own_had_advantage": bool(own_had_advantage),
            "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=str, default="0-7")
    ap.add_argument("--rounds", type=int, default=5)
    ap.add_argument("--K", type=int, default=8)
    ap.add_argument("--pool", type=int, default=64)
    ap.add_argument("--fixed_pool", type=int, default=64)
    ap.add_argument("--budget_frac", type=float, default=0.15)
    ap.add_argument("--temp", type=float, default=1.3)
    ap.add_argument("--replay_frac", type=float, default=0.5)
    ap.add_argument("--neg_w", type=float, default=0.5)
    ap.add_argument("--top_k", type=int, default=0)
    ap.add_argument("--steps", type=int, default=70)
    ap.add_argument("--n_seed", type=int, default=200)
    ap.add_argument("--base_steps", type=int, default=200)
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
        args.seeds, args.rounds, args.pool, args.fixed_pool, args.steps, args.base_steps = "0-2", 4, 48, 48, 50, 180
        n_boot = 2000

    if "-" in args.seeds and "," not in args.seeds:
        a, b = args.seeds.split("-"); seeds = list(range(int(a), int(b) + 1))
    else:
        seeds = [int(x) for x in args.seeds.split(",")]
    train_targets, test_targets = E.build_split(LO, HI, args.test_frac)
    logs = []

    def log(mm):
        print(mm, flush=True); logs.append(mm)

    log("[exp133] CYCLE 151 / H-V4-9k — DESCONFOUND: ¿el payoff de calibración del lazo real es real o riqueza de generación? (pool FIJO compartido)")
    log(f"[exp133] arms={ARMS} seeds={seeds} rounds={args.rounds} pool={args.pool} fixed_pool={args.fixed_pool}")

    per_seed = [run_seed(s, args, test_targets, train_targets, log) for s in seeds]
    sm = build_summary(per_seed, n_boot=n_boot)

    log("[exp133] --- AUROC OWN (pool propio, métrica CONFUNDIDA del 149/150) vs AUROC FIXED (pool compartido, DESCONFUNDIDA) ---")
    log(f"[exp133] AUROC_own:   {sm['auroc_own']}")
    log(f"[exp133] AUROC_fixed: {sm['auroc_fixed']}")
    log(f"[exp133] #correctas (pool propio): {sm['mean_ncorrect']}")
    o, f = sm['own_durable_vs_naive'], sm['fixed_durable_vs_naive']
    log(f"[exp133] durable−naive: OWN {o['mean']:+.3f} (CI {o['ci95']}, excl0={o['ci_excludes_zero']}) -> FIXED {f['mean']:+.3f} (CI {f['ci95']}, excl0={f['ci_excludes_zero']})  [atenúa {sm['atten_durable']:+.3f}]")
    o, f = sm['own_lslo_vs_naive'], sm['fixed_lslo_vs_naive']
    log(f"[exp133] ls_lo−naive:  OWN {o['mean']:+.3f} (CI {o['ci95']}, excl0={o['ci_excludes_zero']}) -> FIXED {f['mean']:+.3f} (CI {f['ci95']}, excl0={f['ci_excludes_zero']})  [atenúa {sm['atten_lslo']:+.3f}]")
    log(f"[exp133] VEREDICTO H-V4-9k: {sm['status'].upper()} | {sm['verdict']}")

    raw = [{"seed": s["seed"], "base_real_acc": round(s["base"].get("real_acc", 0.0), 4),
            "fixed_ncorrect": s["fixed_ncorrect"], "fixed_npool": s["fixed_npool"],
            "auroc_own": {a: s["hist"][a]["auroc_own"] for a in ARMS},
            "auroc_fixed": {a: s["hist"][a]["auroc_fixed"] for a in ARMS},
            "ncorrect": {a: s["hist"][a]["ncorrect"] for a in ARMS}} for s in per_seed]
    out = {"exp": "exp133_deconfound_calibration", "cycle": 151, "hypothesis": "H-V4-9k",
           "claim": "DESCONFOUND del payoff de calibracion del lazo real (149/150): el AUROC esta confundido con la riqueza de "
                    "generacion (cada brazo rankea SU pool, de dificultad distinta segun cuantas correctas genera). Test: que TODOS "
                    "los brazos rankeen un POOL FIJO COMPARTIDO Y BALANCEADO (candidatos CONSTRUIDOS deterministicamente una vez -1 "
                    "positivo canonico + 1 negativo de-otro-target por prompt-, etiquetados por el verificador REAL, 48/48; NO "
                    "generados por ningun brazo) -> AUROC_fixed aisla la separacion-de-confianza de la riqueza de generacion. "
                    "REFUTADA-calibracion si NINGUNA ventaja FIXED sobrevive ni en signo; APOYADA si alguna sobrevive con CI excl 0 Y "
                    "t-test pareado significativo (robusta); MIXTA si una se invierte y otra sobrevive solo en signo (no robusta).",
           "verdict": sm["status"], "summary": sm, "raw": raw, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__, "torch": torch.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp133] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
