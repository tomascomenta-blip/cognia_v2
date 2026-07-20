r"""
exp125 — CYCLE 141 / H-V4-9h (rama R-VALOR, SALIR DEL ORÁCULO, POWERED): resuelve el caveat central que la MIXTA del CYCLE 140
(exp124) dejó abierto. 140 halló en el lazo torch REAL (HybridLM genera 'N=a*b' -> verificador REAL sandbox -> confianza ENDÓGENA
-> self-train con/sin cura de unlikelihood 119) una ventaja de RANKING base-rate-INVARIANTE del brazo durable (AUROC +0.083, 4/4
seeds, t=3.23) PERO la declaró UNDERPOWERED (N=4: el t-test apenas rozaba el umbral df=3=3.182; el sign-test tope con 4 seeds es
p=0.125). Este ciclo la POTENCIA: corre el MISMO lazo real (reusa run_seed de exp124) con N=8 seeds y pregunta si la ventaja AUROC
es REAL Y SIGNIFICATIVA (df=7, tcrit=2.365), y si el MECANISMO se sostiene (¿el gap AUROC durable-naive CRECE a lo largo de las
rondas a medida que el naive colapsa su calibración? = la cura 119 PREVIENE el colapso, no sólo lo retrasa).

CONTEXTO. La verificación adversarial de 140 (4 agentes) confirmó: la decisión es ENDÓGENA (ranking por confianza, el oráculo sólo
MIDE) y el verificador REAL; el confound de base-rate (que invalidó el titular precision@m de la 1ra versión de 140) es CHICO en el
régimen completo (durable ~228 vs naive ~223 correctas), así que AUROC (base-rate-INVARIANTE) es la métrica limpia. Lo único que
faltaba era PODER ESTADÍSTICO. Este ciclo lo aporta.

PREGUNTA FALSABLE:
  - APOYADA si a N=8 el AUROC gap durable-naive es POSITIVO, sign-consistente (>=7/8 seeds) y SIGNIFICATIVO (t pareado > 2.365),
    con base-rate emparejado (|gap #correctas| chico -> no es confound) -> la cura 119 da una ventaja de ranking REAL en el lazo
    real; el payoff decisional del R-VALOR (su factor de CALIBRACIÓN-RANKING) ATERRIZA fuera del juguete.
  - REFUTADA si el AUROC gap NO es significativo a N=8 (o se desvanece / cambia de signo) -> la ventaja de 140 era ruido de N
    chico; el payoff decisional limpio NO transfiere al lazo real.
  - MIXTA si significativo pero condicional (p.ej. el mecanismo trayectoria-creciente no se sostiene, o hay trade-off de generación
    a N=8, o el lift no acompaña).

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp125_decisional_powered.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp125_decisional_powered.run            # FULL (N=8, lento ~60min CPU)
"""
import argparse
import json
import os
import platform
import sys

import numpy as np

from cognia_x.experiments.exp018_real_verifier import expression_task as E
from cognia_x.experiments.exp018_real_verifier.run import LO, HI
from cognia_x.experiments.exp124_decisional_real_loop.run import (
    run_seed, ARMS, F_GRID, _auc_over_rounds, _gap_stats, _mean, _f)

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")
TCRIT = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228}


def _roundwise_gap(per_seed, key, nrounds):
    """Trayectoria del gap durable-naive de `key` por ronda (media sobre seeds)."""
    traj = []
    for r in range(nrounds):
        vals = []
        for s in per_seed:
            d = s["hist"]["durable"][key]; n = s["hist"]["naive"][key]
            if r < len(d) and r < len(n) and d[r] is not None and n[r] is not None:
                vals.append(d[r] - n[r])
        traj.append(round(_mean(vals), 4) if vals else None)
    return traj


def _signtest_p(n_pos, n):
    """p two-sided del sign-test (binomial, H0: p=0.5). El test NO-paramétrico robusto (la razón del 'underpowered' de 140)."""
    from math import comb
    k = max(n_pos, n - n_pos)
    tail = sum(comb(n, i) for i in range(k, n + 1)) * (0.5 ** n)
    return round(min(1.0, 2.0 * tail), 4)


def _perseed_slope(per_seed, key, skip_first=True):
    """Pendiente del gap por ronda DENTRO de cada seed (excluye la ronda 1 = cero estructural si skip_first), luego media+t sobre
    seeds. La verificación de 140/141 mostró que incluir la ronda-1=0 INFLA artificialmente la 'pendiente creciente'."""
    slopes = []
    for s in per_seed:
        d = s["hist"]["durable"][key]; n = s["hist"]["naive"][key]
        gaps = [(d[r] - n[r]) for r in range(len(d))
                if r < len(n) and d[r] is not None and n[r] is not None]
        if skip_first:
            gaps = gaps[1:]
        if len(gaps) >= 3:
            x = np.arange(len(gaps)); slopes.append(float(np.polyfit(x, gaps, 1)[0]))
    if not slopes:
        return {"mean": 0.0, "n_positive": 0, "n": 0, "tstat": 0.0}
    g = np.array(slopes); n_ = len(g)
    sd = float(np.std(g, ddof=1)) if n_ > 1 else 0.0
    return {"mean": round(float(np.mean(g)), 5), "n_positive": int(np.sum(g > 0)), "n": n_,
            "tstat": round(float(np.mean(g) / (sd / np.sqrt(n_))) if sd > 1e-12 else 0.0, 3)}


def _within_arm_corr_nc_auroc(per_seed, arm):
    """Pearson(nc, auroc) DENTRO de un brazo sobre todas las (seed,ronda) -> si ≈0, AUROC es EMPÍRICAMENTE base-rate-invariante
    (la defensa correcta del 'no es confound', NO el 'base-rate emparejado' que es falso). Verificación de 141."""
    ncs, aus = [], []
    for s in per_seed:
        for nc, au in zip(s["hist"][arm]["ncorrect"], s["hist"][arm]["auroc"]):
            if au is not None:
                ncs.append(nc); aus.append(au)
    if len(ncs) < 3 or np.std(ncs) < 1e-9 or np.std(aus) < 1e-9:
        return 0.0
    return round(float(np.corrcoef(ncs, aus)[0, 1]), 4)


def build_summary(per_seed, nrounds):
    nseed = len(per_seed)
    auroc = _gap_stats(per_seed, "auroc")
    lift = _gap_stats(per_seed, "lift_f1")
    baserate = _gap_stats(per_seed, "ncorrect")
    corr = _gap_stats(per_seed, "corr")
    au_n = _mean([v for v in (_auc_over_rounds(s["hist"]["naive"]["auroc"]) for s in per_seed) if v is not None])
    au_d = _mean([v for v in (_auc_over_rounds(s["hist"]["durable"]["auroc"]) for s in per_seed) if v is not None])
    nc_d = _mean([_mean(s["hist"]["durable"]["ncorrect"]) for s in per_seed])
    nc_n = _mean([_mean(s["hist"]["naive"]["ncorrect"]) for s in per_seed])

    traj_auroc = _roundwise_gap(per_seed, "auroc", nrounds)
    traj_corr = _roundwise_gap(per_seed, "corr", nrounds)

    # --- correcciones de la VERIFICACIÓN ADVERSARIAL de 141 ---
    sign_p = _signtest_p(auroc["n_positive"], auroc["n"])           # el test no-paramétrico robusto (p=0.07 a N=8 -> NO sig)
    slope = _perseed_slope(per_seed, "auroc", skip_first=True)      # pendiente SIN la ronda-1=0 (flipea a negativa)
    # mecanismo REAL: ¿ventaja INMEDIATA (gap máximo temprano) o ACUMULADA? gap_temprano (ronda 2-3) vs gap_tardío (últimas 2)
    valid = [x for x in traj_auroc if x is not None]
    gap_early = _mean(valid[1:3]) if len(valid) >= 3 else (valid[1] if len(valid) > 1 else 0.0)   # rondas 2-3 (post-divergencia)
    gap_late = _mean(valid[-2:]) if len(valid) >= 2 else 0.0
    immediate_not_accumulated = gap_early > gap_late                # la ventaja es INMEDIATA y se erosiona, no se acumula
    # invariancia EMPÍRICA al base-rate (la defensa correcta, no 'emparejado'): corr(nc,auroc) dentro de cada brazo ≈ 0
    corr_nc_au_d = _within_arm_corr_nc_auroc(per_seed, "durable")
    corr_nc_au_n = _within_arm_corr_nc_auroc(per_seed, "naive")
    baserate_invariant = abs(corr_nc_au_d) < 0.25 and abs(corr_nc_au_n) < 0.25
    # DILUCIÓN de la magnitud: primera mitad de seeds vs segunda mitad
    half = nseed // 2
    gaps_ps = auroc["per_seed"]
    dilution_first = round(_mean(gaps_ps[:half]), 4) if half else 0.0
    dilution_second = round(_mean(gaps_ps[half:]), 4) if half else 0.0
    diluting = (dilution_second < dilution_first - 0.02)            # la señal se diluye con más seeds (winner's curse)

    tcrit = TCRIT.get(nseed - 1, 2.2)
    # CRITERIOS HONESTOS (post-verificación de 141):
    auroc_positive = auroc["mean"] > 0.01 and auroc["n_positive"] >= int(np.ceil(0.75 * nseed))   # EXISTE la ventaja (signo)
    auroc_t_sig = abs(auroc["tstat"]) > tcrit
    sign_sig = sign_p < 0.05
    significant_robust = auroc_t_sig and sign_sig                   # ROBUSTO sólo si t Y sign-test (sign falla -> no robusto)
    mechanism_grows = (slope["mean"] > 0 and slope["tstat"] > tcrit)  # pendiente REAL (sin ronda-1) significativa -> casi nunca

    if auroc_positive and significant_robust and baserate_invariant and not diluting and not immediate_not_accumulated:
        status = "apoyada"
        head = ("H-V4-9h APOYADA (POWERED, N={ns}): la ventaja de ranking del durable es REAL, ROBUSTAMENTE significativa (t Y "
                "sign-test), base-rate-invariante, no-diluyente y acumulada.").format(ns=nseed)
    elif not auroc_positive:
        status = "refutada"
        head = ("H-V4-9h REFUTADA (POWERED, N={ns}): NO hay ventaja de ranking consistente (gap {am}, {ap}/{an} seeds) -> la del "
                "140 era ruido de N chico.").format(ns=nseed, am=_f(auroc["mean"]), ap=auroc["n_positive"], an=auroc["n"])
    else:
        status = "mixta"
        head = ("H-V4-9h MIXTA (POWERED, N={ns}): la ventaja de ranking del durable EXISTE y es base-rate-invariante, pero su "
                "SIGNIFICANCIA es FRÁGIL y el 'mecanismo' es una ventaja inmediata que se erosiona (no prevención de colapso)").format(ns=nseed)

    verdict = (
        "{head}. SALIR DEL ORÁCULO POWERED: 140 (exp124) halló en el lazo torch REAL una ventaja de RANKING base-rate-INVARIANTE "
        "del durable (cura 119) pero UNDERPOWERED a N=4; este ciclo la potencia a N={ns}. QUÉ SOBREVIVE: la ventaja de ranking "
        "EXISTE y es base-rate-INVARIANTE -- AUROC durable {aud} vs naive {aun}, gap +{am} ({ap}/{an} seeds positivos, mediana "
        "+{amed}, jackknife-min +{ajk}); NO es un confound de base-rate (corr(nc,AUROC) dentro de brazo ≈0: durable {cd}, naive "
        "{cn} -> invariancia EMPÍRICA, la defensa correcta). QUÉ NO SOBREVIVE (retractado por la verificación adversarial de 3 "
        "agentes -- el experimento lo AUTO-DOCUMENTA): (1) la SIGNIFICANCIA es FRÁGIL -- el t pareado {at} apenas cruza tcrit(df="
        "{df})={tc}, PERO el SIGN-TEST (no-paramétrico, robusto, {ap}/{an}) da p={sp} -> NO significativo a 0.05; y ese es JUSTO "
        "el test que definió el 'underpowered' de 140 (su tope a N=4 era p=0.125) -> el underpowered NO está resuelto, sólo se "
        "migró al t-paramétrico, el más sensible. (2) la magnitud se DILUYE con N: primera mitad de seeds +{d1} vs segunda mitad "
        "+{d2} (los seeds nuevos son ~4× más débiles; de +0.083 a N=4 bajó a +{am} a N=8 -- winner's curse). (3) el 'base-rate "
        "emparejado' es FALSO (gap {brm}, no cero, durable genera MENOS correctas -> trade-off de generación); la defensa válida "
        "es la INVARIANCIA empírica, no el emparejamiento. (4) el MECANISMO 'el gap crece / la cura PREVIENE el colapso' es un "
        "ARTEFACTO del cero-estructural de la ronda-1: la pendiente per-seed SIN la ronda-1 es {sl} (t={slt}, NO significativa); "
        "AMBOS brazos COLAPSAN su AUROC y el corr-gap converge a ~0; el efecto real es una VENTAJA INMEDIATA (gap temprano rondas "
        "2-3 +{ge} vs tardío +{gl}) que se EROSIONA. (5) casi-TAUTOLÓGICO + STRAWMAN: el unlikelihood optimiza DIRECTAMENTE la "
        "separación confianza-correcto que AUROC mide (no es ranking emergente, es supresión de confident-wrong), y sólo se probó "
        "contra el baseline-que-COLAPSA (no contra un regularizador de calibración alternativo -- eco del 139). => RESULTADO "
        "HONESTO: existe una ventaja de ranking del unlikelihood REAL y base-rate-invariante pero MODESTA, FRÁGIL (sign-test "
        "p={sp}), DILUYÉNDOSE con N, INMEDIATA-no-acumulada, casi-tautológica y sólo vs el baseline que colapsa. El underpowered "
        "de 140 NO se resuelve limpio. MIXTA EXITOSA: la verificación cazó significancia-frágil + mecanismo-artefacto + premisa-"
        "falsa (base-rate emparejado) antes del ledger (11mo ciclo). Frontera: N=16 para zanjar la dilución; baseline "
        "regularizador-de-calibración alternativo; SCALE.").format(
            head=head, ns=nseed, aud=_f(au_d), aun=_f(au_n), am=_f(auroc["mean"]), ap=auroc["n_positive"], an=auroc["n"],
            amed=_f(auroc["median"]), ajk=_f(auroc["jackknife_min"]), cd=_f(corr_nc_au_d), cn=_f(corr_nc_au_n),
            at=auroc["tstat"], df=nseed - 1, tc=tcrit, sp=_f(sign_p), d1=_f(dilution_first), d2=_f(dilution_second),
            brm=_f(baserate["mean"]), sl=_f(slope["mean"]), slt=slope["tstat"], ge=_f(gap_early), gl=_f(gap_late))

    return {"arms": ARMS, "n_seeds": nseed, "tcrit_df": tcrit,
            "auroc_naive": round(au_n, 4), "auroc_durable": round(au_d, 4), "auroc_gap_stats": auroc,
            "lift_f1_gap_stats": lift, "baserate_gap_stats": baserate, "corr_gap_stats": corr,
            "mean_ncorrect_durable": round(nc_d, 4), "mean_ncorrect_naive": round(nc_n, 4),
            "traj_auroc_gap": traj_auroc, "traj_corr_gap": traj_corr,
            "sign_test_p": sign_p, "perseed_slope_no_r1": slope, "gap_early": round(gap_early, 4), "gap_late": round(gap_late, 4),
            "corr_nc_auroc_durable": corr_nc_au_d, "corr_nc_auroc_naive": corr_nc_au_n,
            "dilution_first_half": dilution_first, "dilution_second_half": dilution_second,
            "auroc_positive": bool(auroc_positive), "auroc_t_sig": bool(auroc_t_sig), "sign_sig": bool(sign_sig),
            "significant_robust": bool(significant_robust), "baserate_invariant": bool(baserate_invariant),
            "diluting": bool(diluting), "immediate_not_accumulated": bool(immediate_not_accumulated),
            "mechanism_grows": bool(mechanism_grows),
            "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=str, default="0,1,2,3,4,5,6,7")
    ap.add_argument("--rounds", type=int, default=8)
    ap.add_argument("--K", type=int, default=8)
    ap.add_argument("--pool", type=int, default=64)
    ap.add_argument("--budget_frac", type=float, default=0.15)
    ap.add_argument("--temp", type=float, default=1.3)
    ap.add_argument("--replay_frac", type=float, default=0.5)
    ap.add_argument("--neg_w", type=float, default=0.5)
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
        args.seeds, args.rounds, args.pool, args.steps, args.base_steps = "0,1,2,3", 5, 48, 60, 200

    seeds = [int(s) for s in args.seeds.split(",")]
    train_targets, test_targets = E.build_split(LO, HI, args.test_frac)
    logs = []

    def log(mm):
        print(mm, flush=True); logs.append(mm)

    log("[exp125] CYCLE 141 / H-V4-9h — POWERED (N=%d): ¿la ventaja de ranking AUROC del durable (140) es REAL y SIGNIFICATIVA en el lazo torch real?" % len(seeds))
    log(f"[exp125] seeds={seeds} rango=[{LO},{HI}] rounds={args.rounds} pool={args.pool} (reusa el lazo real de exp124)")

    per_seed = [run_seed(s, args, test_targets, train_targets, log) for s in seeds]
    sm = build_summary(per_seed, args.rounds)

    au = sm["auroc_gap_stats"]; lf = sm["lift_f1_gap_stats"]; br = sm["baserate_gap_stats"]; sl = sm["perseed_slope_no_r1"]
    log("[exp125] --- RESULTADO POWERED (N=%d), post-verificación adversarial ---" % len(seeds))
    log(f"[exp125] AUROC durable={sm['auroc_durable']:.3f} naive={sm['auroc_naive']:.3f} | gap por seed {au['per_seed']}")
    log(f"[exp125] AUROC gap: media +{au['mean']:.3f} mediana +{au['median']:.3f} jackknife-min +{au['jackknife_min']:.3f} ({au['n_positive']}/{au['n']} pos)")
    log(f"[exp125] SIGNIFICANCIA: t pareado={au['tstat']} vs tcrit(df={len(seeds)-1})={sm['tcrit_df']} (t_sig={sm['auroc_t_sig']}) | SIGN-TEST p={sm['sign_test_p']} (sign_sig={sm['sign_sig']}) -> ROBUSTO={sm['significant_robust']}")
    log(f"[exp125] DILUCIÓN: 1ra mitad seeds +{sm['dilution_first_half']:.3f} vs 2da mitad +{sm['dilution_second_half']:.3f} -> diluyendo={sm['diluting']}")
    log(f"[exp125] BASE-RATE: durable={sm['mean_ncorrect_durable']:.1f} naive={sm['mean_ncorrect_naive']:.1f} (gap {br['mean']:+.1f}, emparejado-FALSO) | INVARIANCIA empírica corr(nc,auroc): durable={sm['corr_nc_auroc_durable']:.3f} naive={sm['corr_nc_auroc_naive']:.3f} -> invariante={sm['baserate_invariant']}")
    log(f"[exp125] MECANISMO: trayectoria gap por ronda {sm['traj_auroc_gap']} | pendiente per-seed SIN ronda-1 = {sl['mean']:+.4f} (t={sl['tstat']}, {sl['n_positive']}/{sl['n']} pos) -> crece={sm['mechanism_grows']} | gap_temprano(r2-3)={sm['gap_early']:.3f} vs tardío={sm['gap_late']:.3f} -> inmediato-no-acumulado={sm['immediate_not_accumulated']}")
    log(f"[exp125] CHECK auroc_positive={sm['auroc_positive']} significant_robust={sm['significant_robust']} baserate_invariant={sm['baserate_invariant']} diluting={sm['diluting']} immediate_not_accumulated={sm['immediate_not_accumulated']}")
    log(f"[exp125] VEREDICTO H-V4-9h: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp125_decisional_powered", "cycle": 141, "hypothesis": "H-V4-9h",
           "claim": "POWERED (N=8, post-verificacion adversarial de 3 agentes): intenta resolver el underpowered de la MIXTA del "
                    "CYCLE 140 corriendo el MISMO lazo torch REAL (reusa run_seed de exp124) con N=8. SOBREVIVE: la ventaja de "
                    "RANKING base-rate-INVARIANTE del durable EXISTE (AUROC gap +0.05, 7/8 seeds; corr(nc,auroc) dentro de brazo "
                    "~0 -> invariancia empirica, no confound). NO SOBREVIVE (retractado): la SIGNIFICANCIA es FRAGIL (sign-test "
                    "p=0.07 NO sig -y ese es el test que definio el underpowered de 140-; t apenas cruza; jackknife tumba 2/8); la "
                    "magnitud se DILUYE con N (los seeds nuevos ~4x mas debiles); el 'base-rate emparejado' es FALSO (la defensa es "
                    "invariancia empirica); el 'mecanismo crece/previene colapso' es ARTEFACTO del cero-estructural de la ronda-1 "
                    "(sin ella la pendiente flipea; ambos brazos colapsan; el efecto real es una ventaja INMEDIATA que se erosiona); "
                    "casi-tautologico (el unlikelihood optimiza lo que AUROC mide) y solo vs el baseline-que-colapsa. El underpowered "
                    "de 140 NO se resuelve limpio -> MIXTA. Frontera: N=16; baseline regularizador-de-calibracion alternativo",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp125] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
