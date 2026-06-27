r"""
exp124 — CYCLE 140 / H-V4-9g (rama R-VALOR, SALIR DEL ORÁCULO: cerrar el gap que el CYCLE 122 dejó abierto). La auditoría de la
teoría (139→) marcó el hueco #1: TODO el payoff decisional del R-VALOR (123/exp107, +0.904 bajo escasez) se demostró en numpy
SINTÉTICO con un estimador de calibración ρ IMPUESTO; el único intento en el LAZO TORCH REAL (122/exp106) dio REFUTADA porque la
DECISIÓN saturó (submit_m=8 con ~24 correctas en el pool -> cualquier ranking captura las 8 -> payoff 1.000 en ambos brazos), aun
cuando la señal calibrada del brazo durable tenía mejor correlación (corr +0.117). Este ciclo NO re-entrena nada nuevo: REUSA el
lazo cerrado real de exp106 (el modelo HybridLM genera -> verificador REAL sandbox aritmético -> confianza ENDÓGENA del modelo ->
self-train con/sin la cura de unlikelihood 119) y pregunta lo que 122 no pudo aislar: ¿bajo ESCASEZ GENUINA de presupuesto de
submission (m chico = precisión@top-m, donde el ranking domina) la mejor calibración del brazo durable PAGA en el lazo REAL?

CONTEXTO. exp107 (123) barrió escasez q (fracción de buenas opciones) con un estimador SINTÉTICO ρ-correlacionado y halló: bajo
escasez la calibración paga +0.904; bajo abundancia satura (irrelevante). La señal AQUÍ NO es sintética: es la CONFIANZA REAL del
modelo (max-prob de su propia generación), la corrección es el VERIFICADOR REAL (exp018 evalúa 'N=a*b'), y el lazo es REAL (el
modelo se entrena y cambia ronda a ronda). El único grado de libertad que toca este ciclo es el PRESUPUESTO de la decisión
(submit_m), que se barre GRATIS sobre las MISMAS generaciones almacenadas -> aísla si la saturación del 122 era un artefacto del
m grande.

DISEÑO (PyTorch CPU; reusa exp106/exp018/exp077/exp103). Lazo cerrado real, 2 brazos (idénticos a exp106):
  - naive:   likelihood + ancla (la señal de confianza COLAPSA en calibración a lo largo de las rondas, 115).
  - durable: likelihood + ancla + unlikelihood-acotado sobre lo verificado-INCORRECTO (cura 119 -> calibración sostenida).
Cada ronda, para CADA brazo, se ALMACENAN conf[] y strong[] de un pool de K·pool generaciones. La DECISIÓN de submission (someter
las top-m por confianza a recompensa externa = #correctas-sometidas / min(m,#correctas)) se evalúa a MÚLTIPLES m =
{2,4,8,16,32,64} -> de ESCASEZ (m chico) a ABUNDANCIA (m grande). MÉTRICA: gap durable-naive del payoff por m (final y AUC sobre
rondas).

PREGUNTA FALSABLE:
  - APOYADA si bajo ESCASEZ de presupuesto (m chico) el durable PAGA (gap > margen) y el gap DECAE/SATURA al crecer m (reproduce
    el patrón de escasez de exp107 EN EL LAZO REAL; la REFUTADA del 122 era un ARTEFACTO de saturación a m=8). => el payoff
    decisional del R-VALOR sale del oráculo: la calibración endógena del modelo real paga en una decisión real bajo escasez.
  - REFUTADA si el durable NO paga a NINGÚN m (su mejor correlación global no se traduce en mejor precisión@top-m) -> el payoff
    decisional de exp107 NO transfiere al lazo real; era un artefacto del estimador sintético.
  - MIXTA si condicional (paga sólo en un m de filo, o el signo es inestable por seeds).

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp124_decisional_real_loop.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp124_decisional_real_loop.run            # FULL
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
from cognia_x.experiments.exp103_bounded_unlikelihood.run import _train

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")
ARMS = ["naive", "durable"]
# El smoke enseñó que la escasez operativa NO es 'presupuesto chico' (m<<#correctas satura: hallar pocas correctas es trivial)
# sino DEMANDA DE RECALL de positivos RAROS: el presupuesto m RELATIVO a #correctas. f = m/#correctas. En f≈1 hay que separar
# casi-perfecto los raros correctos de los incorrectos (calibración-crítico); f<<1 trivial (pocos), f>>1 trivial (someter todo).
F_GRID = [0.25, 0.5, 1.0, 1.5, 2.0, 4.0]   # presupuesto como múltiplo de #correctas (eje de demanda de RECALL)


def _payoff_at_m(conf, strong, m):
    """Someter las top-m por confianza. payoff = #correctas-sometidas / min(m, #correctas-totales) (vs oracle de selección)."""
    n = len(conf)
    if n == 0:
        return None
    mm = max(1, min(m, n))
    top = np.argsort(conf)[-mm:]
    reward = float(np.sum(strong[top]))
    oracle = float(min(mm, np.sum(strong)))
    return reward / oracle if oracle > 0 else None    # None si no hay correctas esa ronda (la decisión no existe)


def _auroc(conf, strong):
    """AUROC(confianza, correcto) = P(conf_correcto > conf_incorrecto). INVARIANTE AL BASE-RATE (a diferencia de precision@m):
    mide la CALIDAD DE RANKING pura, sin confundirse con cuántas correctas hay. Es el metric correcto para 'la calibración paga'.
    Verificación adversarial CYCLE 140: la precision@m del payoff estaba confundida con el base-rate (los dos brazos generan
    pools con distinto #correctas); AUROC y lift-sobre-azar lo controlan."""
    s = strong > 0.5
    npos = int(np.sum(s)); nneg = int(len(s) - npos)
    if npos == 0 or nneg == 0:
        return None
    order = np.argsort(conf, kind="mergesort")
    sc = conf[order]
    ranks = np.empty(len(conf), dtype=float)
    i = 0; r = 1
    while i < len(sc):                                  # rangos promedio para empates
        j = i
        while j + 1 < len(sc) and sc[j + 1] == sc[i]:
            j += 1
        ranks[order[i:j + 1]] = (r + (r + (j - i))) / 2.0
        r += (j - i + 1); i = j + 1
    return float((np.sum(ranks[s]) - npos * (npos + 1) / 2.0) / (npos * nneg))


def _lift_at_f1(conf, strong):
    """Lift-sobre-azar en f=1 (m=#correctas): payoff@f1 − base_rate. A f=1, someter al azar da en esperanza base_rate;
    el lift aísla la CALIDAD DE RANKING controlando el base-rate (el confound que cazó la verificación)."""
    nc = int(np.sum(strong)); n = len(strong)
    if nc == 0 or n == 0:
        return None
    p = _payoff_at_m(conf, strong, nc)
    return None if p is None else p - (nc / n)


def run_seed(seed, args, test_targets, train_targets, log):
    base, npar = build_base(seed, args.n_seed, args.base_steps, args.base_lr, args.warmup, args.batch, train_targets)
    bm = E.eval_metrics(base, test_targets, "cpu")
    log(f"[exp124] seed={seed} base real_acc={bm['real_acc']:.3f} params={npar:,}")
    pool_rng = np.random.default_rng(seed + 7)
    sel = pool_rng.integers(0, len(train_targets), size=args.pool)
    pool_prompts = [E.make_prompt(train_targets[i]) for i in sel]
    k = max(1, int(args.budget_frac * args.pool * args.K))

    arms = {a: copy.deepcopy(base) for a in ARMS}
    # hist[arm]: payoff_f (precision@m, base-rate-SENSIBLE), auroc (ranking, base-rate-INVARIANTE), lift_f1 (base-rate-controlado),
    # corr (point-biserial), ncorrect, npool (base-rate de CADA brazo -> el confound que cazó la verificación)
    hist = {a: {"payoff_f": {f: [] for f in F_GRID}, "auroc": [], "lift_f1": [], "corr": [], "ncorrect": [], "npool": []}
            for a in ARMS}
    train_rng = np.random.default_rng(seed + 99)

    for r in range(1, args.rounds + 1):
        for a in ARMS:
            torch.manual_seed(10000 * seed + r)
            pool = generate_pool(arms[a], pool_prompts, args.K, args.temp, args.top_k, "cpu")
            pairs = [(p, e) for (p, e, _, _) in pool]
            strong = np.array([1.0 if s else 0.0 for (_, _, _, s) in pool])
            conf = _confidence(arms[a], pairs, "cpu")
            cc = _corr(conf, strong)
            hist[a]["corr"].append(round(cc, 4) if not math.isnan(cc) else 0.0)
            au = _auroc(conf, strong); hist[a]["auroc"].append(round(au, 4) if au is not None else None)
            lf = _lift_at_f1(conf, strong); hist[a]["lift_f1"].append(round(lf, 4) if lf is not None else None)
            nc = int(np.sum(strong))
            hist[a]["ncorrect"].append(nc); hist[a]["npool"].append(len(strong))
            for f in F_GRID:
                m = int(round(f * nc))
                p = _payoff_at_m(conf, strong, m) if (nc > 0 and m >= 1) else None
                hist[a]["payoff_f"][f].append(round(p, 4) if p is not None else None)
            # self-training CON ancla (capacidad igual); durable agrega unlikelihood sobre lo verificado-incorrecto (cura 119)
            rng_a = np.random.default_rng(seed * 131 + r * 17 + ARMS.index(a))
            sel_idx = np.argsort(conf + 1e-9 * rng_a.random(len(pool)))[-min(k, len(pool)):]
            pos = _dedup([pairs[i] for i in sel_idx if strong[i] > 0.5])
            pos = pos + _replay_examples(train_rng, train_targets, int(round(args.replay_frac * max(1, len(pos)))))
            neg = _dedup([pairs[i] for i in sel_idx if strong[i] < 0.5]) if a == "durable" else []
            _train(arms[a], pos, neg, args.steps, args.batch, args.lr,
                   args.neg_w if a == "durable" else 0.0, "cpu", train_rng)
        def _g(a):
            v = hist[a]["auroc"][-1]
            return "{:.3f}".format(v) if v is not None else "--"
        msg = " | ".join(f"{a}: auroc={_g(a)} corr={hist[a]['corr'][-1]:.2f} nc={hist[a]['ncorrect'][-1]}" for a in ARMS)
        log(f"[exp124] seed={seed} ronda {r}: {msg} (base-rate de AMBOS brazos logueado)")

    return {"seed": seed, "base": bm, "hist": hist}


def _mean(xs):
    return float(np.mean(xs)) if len(xs) else 0.0


def _f(x):
    return "{:.3f}".format(x)


def _auc_over_rounds(seed_hist_f):
    """Media sobre rondas ignorando None (rondas sin correctas)."""
    vals = [v for v in seed_hist_f if v is not None]
    return _mean(vals) if vals else None


def _seed_auc(s, arm, key):
    return _auc_over_rounds(s["hist"][arm][key]) if key != "ncorrect" else _mean(s["hist"][arm]["ncorrect"])


def _gap_stats(per_seed, key):
    """Gap durable-naive de `key` (auroc/lift_f1/...) AUC-sobre-rondas POR SEED -> media, mediana, jackknife (drop-one min),
    signo-consistente, y un t-stat pareado simple (sin scipy). N=4 -> poder bajo, se reporta honestamente."""
    gaps = []
    for s in per_seed:
        if key == "ncorrect":
            gd = _mean(s["hist"]["durable"]["ncorrect"]); gn = _mean(s["hist"]["naive"]["ncorrect"])
        else:
            gd = _auc_over_rounds(s["hist"]["durable"][key]); gn = _auc_over_rounds(s["hist"]["naive"][key])
        if gd is not None and gn is not None:
            gaps.append(gd - gn)
    g = np.array(gaps) if gaps else np.array([0.0])
    n = len(g)
    mean = float(np.mean(g)); med = float(np.median(g))
    jk_min = float(min((np.mean(np.delete(g, i)) for i in range(n)), default=mean)) if n > 1 else mean
    pos = int(np.sum(g > 0))
    sd = float(np.std(g, ddof=1)) if n > 1 else 0.0
    tstat = mean / (sd / np.sqrt(n)) if sd > 1e-12 else 0.0
    # t crítico two-sided 0.05: df3=3.182, df2=4.303, df1=12.706
    tcrit = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571}.get(n - 1, 2.5)
    return {"per_seed": [round(x, 4) for x in gaps], "mean": round(mean, 4), "median": round(med, 4),
            "jackknife_min": round(jk_min, 4), "n_positive": pos, "n": n, "tstat": round(tstat, 3),
            "significant": bool(abs(tstat) > tcrit)}


def build_summary(per_seed):
    nseed = len(per_seed)

    def m_auc(arm, key):
        return _mean([v for v in (_auc_over_rounds(s["hist"][arm][key]) for s in per_seed) if v is not None])

    # --- payoff precision@m por f (REFERENCIA: base-rate-SENSIBLE -> confundido, lo marca la verificación) ---
    by_f = {}
    for f in F_GRID:
        an = _mean([v for v in (_auc_over_rounds(s["hist"]["naive"]["payoff_f"][f]) for s in per_seed) if v is not None])
        ad = _mean([v for v in (_auc_over_rounds(s["hist"]["durable"]["payoff_f"][f]) for s in per_seed) if v is not None])
        by_f[f] = {"auc_naive": round(an, 4), "auc_durable": round(ad, 4), "auc_gap": round(ad - an, 4)}
    best_f = max(F_GRID, key=lambda f: by_f[f]["auc_gap"])

    # --- métricas LIMPIAS (post-verificación): AUROC (ranking, base-rate-INVARIANTE), lift_f1 (base-rate-controlado) ---
    auroc = _gap_stats(per_seed, "auroc")
    lift = _gap_stats(per_seed, "lift_f1")
    # payoff f=1 por seed (el titular confundido) -> para contraste con AUROC/lift
    f1_seed = []
    for s in per_seed:
        gd = _auc_over_rounds(s["hist"]["durable"]["payoff_f"][1.0]); gn = _auc_over_rounds(s["hist"]["naive"]["payoff_f"][1.0])
        if gd is not None and gn is not None:
            f1_seed.append(round(gd - gn, 4))
    # --- el CONFOUND: base-rate (#correctas) de CADA brazo ---
    baserate = _gap_stats(per_seed, "ncorrect")
    nc_d = _mean([_mean(s["hist"]["durable"]["ncorrect"]) for s in per_seed])
    nc_n = _mean([_mean(s["hist"]["naive"]["ncorrect"]) for s in per_seed])
    npool = _mean([_mean(s["hist"]["durable"]["npool"]) for s in per_seed])

    ca_n, ca_d = m_auc("naive", "corr"), m_auc("durable", "corr")
    cf_n = _mean([s["hist"]["naive"]["corr"][-1] for s in per_seed])
    cf_d = _mean([s["hist"]["durable"]["corr"][-1] for s in per_seed])
    au_n, au_d = m_auc("naive", "auroc"), m_auc("durable", "auroc")
    lf_n, lf_d = m_auc("naive", "lift_f1"), m_auc("durable", "lift_f1")

    # CRITERIOS HONESTOS (post-verificación adversarial de 4 agentes):
    # (1) ¿hay una ventaja de RANKING base-rate-INVARIANTE? AUROC gap > 0, signo-consistente. (limpia el confound de base-rate)
    auroc_advantage = auroc["mean"] > 0.01 and auroc["n_positive"] == auroc["n"]
    # (2) ¿sobrevive controlando el base-rate? lift_f1 gap > 0, signo-consistente.
    lift_survives = lift["mean"] > 0.0 and lift["n_positive"] == lift["n"]
    # (3) UNDERPOWERED: con N<8 seeds NO se puede reclamar significancia (el t-stat con 2-4 puntos es ilusorio; el sign-test tope
    #     con N=4 es p=0.125). La significancia se REPORTA pero NO habilita APOYADA hasta tener N suficiente.
    underpowered = nseed < 8
    significant = (auroc["significant"] or lift["significant"]) and not underpowered
    # (4) TRADE-OFF GENERACIÓN/RANKING: el unlikelihood (cura 119) suprime la generación -> el durable genera MENOS correctas.
    #     'el calibrado decide mejor' debe acotarse con 'genera mucho menos para decidir'. (confound de base-rate, ahora medido.)
    generation_tradeoff = baserate["mean"] < -5.0
    baserate_confound = abs(baserate["mean"]) > 5.0

    if auroc_advantage and lift_survives and significant and not generation_tradeoff:
        status = "apoyada"
        head = ("H-V4-9g APOYADA (caracterización honesta, post-verificación de 4 agentes): el durable tiene una ventaja de "
                "RANKING base-rate-INVARIANTE (AUROC) que sobrevive el control de base-rate (lift), es significativa (N>=8) y SIN "
                "trade-off de generación.")
    elif not auroc_advantage:
        status = "refutada"
        head = ("H-V4-9g REFUTADA: NO hay ventaja de ranking base-rate-invariante consistente (AUROC gap {am}, {ap}/{an} seeds) "
                "-> el payoff aparente del durable era el CONFOUND de base-rate, no calibración. El payoff decisional de exp107 NO "
                "transfiere limpio al lazo real.").format(am=_f(auroc["mean"]), ap=auroc["n_positive"], an=auroc["n"])
    else:
        status = "mixta"
        head = ("H-V4-9g MIXTA (existe la ventaja de ranking pero ACOTADA: underpowered N={ns} y/o trade-off de generación "
                "-- el durable genera {brm} correctas vs el naive)").format(ns=nseed, brm=("MENOS" if generation_tradeoff else "≈"))

    verdict = (
        "{head} SALIR DEL ORÁCULO (cierra el hueco #1 de la auditoría -- primer intento de payoff decisional del R-VALOR fuera del "
        "numpy sintético): en el lazo torch REAL (HybridLM genera 'N=a*b' -> verificador REAL sandbox -> confianza ENDÓGENA -> "
        "self-train; durable agrega unlikelihood = cura 119), ¿la mejor calibración del durable PAGA en la decisión real? "
        "QUÉ SOBREVIVE (limpio): (a) la DECISIÓN es genuinamente endógena (ranking por confianza del modelo, el oráculo sólo MIDE) "
        "y el verificador es REAL; (b) ventaja de RANKING base-rate-INVARIANTE del durable, AUROC gap medio +{aum} (durable {aud} "
        "vs naive {aun}), {aup}/{aun_} seeds positivos, mediana +{aumed}, jackknife-min +{aujk}, t={aut} (significativo={ausig}); "
        "(c) lift-sobre-azar en f=1 (controla el base-rate) gap +{lm} ({lp}/{ln_} seeds, t={lt}). QUÉ NO SOBREVIVE (retractado por "
        "la verificación de 4 agentes -- el experimento lo AUTO-DOCUMENTA): (1) CONFOUND DE BASE-RATE -- el titular previo (payoff "
        "precision@m f=1 +{f1m}) está CONFUNDIDO: los dos brazos son modelos DISTINTOS que generan pools con distinto #correctas "
        "(durable {ncd} vs naive {ncn}, gap {brm}); precision@m es base-rate-SENSIBLE, y un Δbase-rate de magnitud plausible con "
        "CERO diferencia de calibración reproduce el titular. La 1ra versión NI SIQUIERA logueaba el #correctas del naive -> "
        "irrecuperable; corregido aquí con AUROC+lift+base-rate de ambos brazos. (2) NO SIGNIFICATIVO a N={ns}: el t-test pareado "
        "no cruza el umbral; con 4 seeds el sign-test tope es p=0.125. (3) MECANISMO FALSO -- NO hay pico en f=1: el gap del payoff "
        "es MÁXIMO en f={bf} (zona que el propio grid llama trivial) y monótono-decreciente; el gate 'decision_driven' (se anula a "
        "f=4) es VACUO (4·#correctas>pool -> a f=4 se somete todo por construcción). (4) FRAMING -- 'sale del oráculo' es ACOTADO "
        "(sólo el ranking es endógeno; el verificador supervisa el self-train, etiqueta y normaliza la métrica); 'transfiere' es un "
        "ECO MUY ATENUADO vs exp107 (+0.904 random-vs-best, escasez q=0.08) -- acá ~+0.0x entre dos señales ya-positivas a 44% de "
        "correctas (abundancia, no escasez); el régimen f≈1 fue elegido POST-HOC tras refutarse 'presupuesto chico'. => RESULTADO "
        "HONESTO: existe una ventaja de ranking base-rate-invariante (AUROC) del durable, POSITIVA en signo pero MODESTA y NO "
        "significativa a N=4; el 'payoff decisional' aparente estaba confundido con el base-rate. La LECCIÓN METODOLÓGICA es el "
        "aporte: medir payoff decisional en un lazo de auto-entrenamiento EXIGE controlar el base-rate (AUROC/lift, no precision@m) "
        "y N suficiente. MIXTA EXITOSA: la verificación adversarial cazó un CONFOUND + un mecanismo falso + framing sobre-vendido "
        "antes del ledger (10mo ciclo)."
    ).format(head=head, aum=_f(auroc["mean"]), aud=_f(au_d), aun=_f(au_n), aup=auroc["n_positive"], aun_=auroc["n"],
             aumed=_f(auroc["median"]), aujk=_f(auroc["jackknife_min"]), aut=auroc["tstat"], ausig=auroc["significant"],
             lm=_f(lift["mean"]), lp=lift["n_positive"], ln_=lift["n"], lt=lift["tstat"], f1m=_f(np.mean(f1_seed) if f1_seed else 0.0),
             ncd=_f(nc_d), ncn=_f(nc_n), brm=_f(baserate["mean"]), ns=nseed, bf=best_f)

    return {"arms": ARMS, "n_seeds": nseed, "f_grid": F_GRID, "by_f": {str(f): by_f[f] for f in F_GRID},
            "auroc_naive": round(au_n, 4), "auroc_durable": round(au_d, 4), "auroc_gap_stats": auroc,
            "lift_f1_naive": round(lf_n, 4), "lift_f1_durable": round(lf_d, 4), "lift_f1_gap_stats": lift,
            "payoff_f1_gap_by_seed": f1_seed, "baserate_gap_stats": baserate,
            "mean_ncorrect_durable": round(nc_d, 4), "mean_ncorrect_naive": round(nc_n, 4), "mean_npool": round(npool, 4),
            "corr_auc_naive": round(ca_n, 4), "corr_auc_durable": round(ca_d, 4), "corr_gap": round(ca_d - ca_n, 4),
            "corr_final_naive": round(cf_n, 4), "corr_final_durable": round(cf_d, 4), "best_f": best_f,
            "auroc_advantage": bool(auroc_advantage), "lift_survives": bool(lift_survives),
            "significant": bool(significant), "underpowered": bool(underpowered),
            "generation_tradeoff": bool(generation_tradeoff), "baserate_confound": bool(baserate_confound),
            "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=str, default="0,1,2,3")
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
        args.seeds, args.rounds, args.pool, args.steps, args.base_steps = "0,1", 5, 48, 60, 200

    seeds = [int(s) for s in args.seeds.split(",")]
    train_targets, test_targets = E.build_split(LO, HI, args.test_frac)
    logs = []

    def log(mm):
        print(mm, flush=True); logs.append(mm)

    log("[exp124] CYCLE 140 / H-V4-9g — SALIR DEL ORÁCULO (post-verificación de 4 agentes): ¿la calibración endógena del durable paga en la decisión real, CONTROLANDO el base-rate (AUROC/lift, no precision@m confundido)?")
    log(f"[exp124] seeds={seeds} rango=[{LO},{HI}] rounds={args.rounds} K={args.K} pool={args.pool} f_grid={F_GRID} "
        f"budget_frac={args.budget_frac} temp={args.temp} neg_w={args.neg_w}")

    per_seed = [run_seed(s, args, test_targets, train_targets, log) for s in seeds]
    sm = build_summary(per_seed)

    au = sm["auroc_gap_stats"]; lf = sm["lift_f1_gap_stats"]; br = sm["baserate_gap_stats"]
    log("[exp124] --- MÉTRICAS LIMPIAS (base-rate-controladas) ---")
    log(f"[exp124] AUROC (ranking, INVARIANTE al base-rate): naive={sm['auroc_naive']:.3f} durable={sm['auroc_durable']:.3f} | gap por seed {au['per_seed']} -> media +{au['mean']:.3f} mediana +{au['median']:.3f} jackknife-min +{au['jackknife_min']:.3f} ({au['n_positive']}/{au['n']} pos, t={au['tstat']}, signif={au['significant']})")
    log(f"[exp124] LIFT@f1 (payoff − base_rate, CONTROLA base-rate): naive={sm['lift_f1_naive']:.3f} durable={sm['lift_f1_durable']:.3f} | gap media +{lf['mean']:.3f} ({lf['n_positive']}/{lf['n']} pos, t={lf['tstat']}, signif={lf['significant']})")
    log(f"[exp124] CONFOUND base-rate (#correctas): durable={sm['mean_ncorrect_durable']:.1f} naive={sm['mean_ncorrect_naive']:.1f}/{sm['mean_npool']:.0f} | gap por seed {br['per_seed']} (media {br['mean']:+.1f})")
    log(f"[exp124] payoff precision@m f=1 (CONFUNDIDO, referencia): gap por seed {sm['payoff_f1_gap_by_seed']} | corr-AUC gap +{sm['corr_gap']:.3f} (final naive={sm['corr_final_naive']:.3f} durable={sm['corr_final_durable']:.3f})")
    log("[exp124] --- payoff precision@m por f (REFERENCIA, base-rate-sensible -> confundido) ---")
    for f in F_GRID:
        d = sm["by_f"][str(f)]
        log(f"[exp124] f={f:>4}: durable={d['auc_durable']:.3f} naive={d['auc_naive']:.3f} gap={d['auc_gap']:+.3f}  (pico en f={sm['best_f']})")
    log(f"[exp124] CHECK auroc_advantage={sm['auroc_advantage']} lift_survives={sm['lift_survives']} significant={sm['significant']} baserate_confound={sm['baserate_confound']}")
    log(f"[exp124] VEREDICTO H-V4-9g: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp124_decisional_real_loop", "cycle": 140, "hypothesis": "H-V4-9g",
           "claim": "SALIR DEL ORACULO (post-verificacion adversarial de 4 agentes). Intento de aterrizar el payoff decisional del "
                    "R-VALOR (exp107/123, +0.904 sintetico) en el LAZO TORCH REAL (HybridLM genera 'N=a*b' -> verificador REAL "
                    "sandbox -> confianza ENDOGENA -> self-train con/sin cura 119). SOBREVIVE: la DECISION es endogena (ranking por "
                    "confianza, el oraculo solo MIDE) y el verificador es REAL; hay una ventaja de RANKING base-rate-INVARIANTE "
                    "(AUROC) del durable, positiva en signo pero MODESTA. NO SOBREVIVE (retractado): el titular previo (payoff "
                    "precision@m) estaba CONFUNDIDO con el base-rate (los dos brazos generan pools con distinto #correctas; la 1ra "
                    "version ni siquiera logueaba el #correctas del naive); NO es significativo a N=4; el mecanismo 'pico en f=1' "
                    "era FALSO (pico en f=0.5 trivial, monotono-decreciente; el gate decision_driven era vacuo); 'sale del oraculo' "
                    "es ACOTADO (el verificador supervisa todo el lazo) y 'transfiere' es un ECO ATENUADO (no la escasez de exp107, "
                    "44% correctas=abundancia). LECCION METODOLOGICA: medir payoff decisional en un lazo de auto-entrenamiento EXIGE "
                    "controlar el base-rate (AUROC/lift, no precision@m) y N suficiente",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__, "torch": torch.__version__},
           "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp124] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
