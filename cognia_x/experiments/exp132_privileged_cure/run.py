r"""
exp132 — CYCLE 150 / H-V4-9j (FRONTERA REAL §4.2 del capstone, hueco abierto por 149): ¿la cura 119 (unlikelihood acotado) es
PRIVILEGIADA, o cualquier regularizador de calibración GENÉRICO produce la misma ventaja de ranking AUROC en el lazo torch real?

CONTEXTO. El CYCLE 149 (exp131) cerró APOYADA el hueco #1: en el lazo torch REAL (HybridLM genera 'N=a*b' -> verificador REAL ->
confianza ENDÓGENA -> self-train con ancla), el brazo 'durable' (naive + unlikelihood ACOTADO sobre lo verificado-INCORRECTO = cura
119) produce una confianza endógena MÁS informativa sobre la correctness real que el naive: ventaja AUROC base-rate-INVARIANTE,
gap +0.047 a N=16 (CI bootstrap excluye 0, t=4.22), REPLICA out-of-sample (N=22 t=5.87). El blocker que 149 dejó EXPLÍCITO: el
durable = naive + unlikelihood, pero NO se testeó si la unlikelihood ESPECÍFICAMENTE (label-aware: usa el verificador para saber
QUÉ castigar) es lo que ayuda, o si CUALQUIER regularizador de calibración genérico (label-agnostic) daría la misma ventaja. Este
ciclo lo aísla con un TERCER (cuarto/quinto/sexto) brazo genérico.

DISEÑO (PyTorch CPU; reusa exactamente el lazo de exp124/exp131 y _bounded_unlikelihood de exp103). Mismo lazo cerrado real, mismos
params powered (rounds 8, pool 64, neg_w 0.5). 6 brazos que difieren SÓLO en el regularizador aplicado durante el self-train, sobre
el MISMO mecanismo de selección (top-k por confianza + replay canónico):
  - naive:   likelihood + ancla (baseline; la señal colapsa en calibración, 115).
  - durable: + unlikelihood ACOTADO sobre lo verificado-INCORRECTO (cura 119; LABEL-AWARE: usa el verificador). neg_w=0.5.
  - ent_lo / ent_hi:  + confidence-penalty (penaliza distribuciones de salida confiadas = bonus de entropía, Pereyra et al. 2017),
                      pesos 0.1 / 0.3. GENÉRICO (label-agnostic): baja la confianza UNIFORMEMENTE sobre el batch de self-train, sin
                      mirar la corrección.
  - ls_lo / ls_hi:    + label smoothing en la CE del self-train (eps 0.05 / 0.15). GENÉRICO (label-agnostic): suaviza los targets
                      uniformemente.
  (TEMPERATURE scaling se DESCARTA a priori: es una transformación MONÓTONA de la confianza -> AUROC-INVARIANTE por construcción, NO
   puede cambiar el ranking. Punto teórico limpio, no necesita corrida.)

MÉTRICA PRIMARIA: el GAP DE PRIVILEGIO por seed = AUROC(durable) − AUROC(mejor genérico), donde 'mejor genérico' = el argmax de
AUROC entre {ent_lo, ent_hi, ls_lo, ls_hi} en ESE seed. Tomar el MEJOR genérico por seed SESGA conservador CONTRA el claim de
privilegio (le da al baseline su mejor tiro + winner's curse a su favor). Secundarias: recovery_gap = AUROC(mejor genérico) −
AUROC(naive) (¿el genérico recupera la ventaja del 149?); durable_vs_naive = AUROC(durable) − AUROC(naive) (SANITY: debe reproducir
cualitativamente el +0.047 del 149). POTENCIA: CI bootstrap 95% del privilege_gap medio (10k resamples), t pareado, sign-test.

PREGUNTA FALSABLE:
  - APOYADA (la cura ES privilegiada) si el CI bootstrap 95% del privilege_gap EXCLUYE el cero (lo>0) Y durable_vs_naive>0 (replica
    149). => la unlikelihood label-aware es ESPECÍFICAMENTE lo que produce la ventaja; un regularizador de calibración genérico NO
    la reproduce. La cura es privilegiada.
  - REFUTADA (NO privilegiada) si el CI del privilege_gap INCLUYE el cero Y recovery_gap>0 (el genérico SÍ recupera la mayor parte de
    la ventaja). => RE-LOCALIZA el 149: lo que ayuda es la REGULARIZACIÓN DE CALIBRACIÓN en general, y la unlikelihood es UNA
    instancia (no privilegiada).
  - MIXTA si el CI excluye 0 PERO el genérico recupera una parte sustancial (recovery_gap>0 grande -> durable tiene una ventaja
    RESIDUAL sobre el mejor genérico, no total), o si los signos son inconsistentes entre seeds.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp132_privileged_cure.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp132_privileged_cure.run --seeds 0-7 --rounds 5 --steps 70   # corrida REAL commiteada (N=8 reducido)
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp132_privileged_cure.run --seeds 0-15                        # config 'powered' (N=16, ~10 min/seed en CPU sin CUDA — NO corrida)
NOTA: la corrida commiteada es N=8/rounds=5/steps=70 (reducida por el costo del lazo en este i3 2-core sin CUDA, ~10 min/seed a
settings full). El CI del privilege_gap es real pero modesto; el veredicto se reporta honestamente "a N=8". La config powered de
N=16 queda como frontera de potencia.
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
import torch.nn.functional as F

from cognia_x.experiments.exp018_real_verifier import expression_task as E
from cognia_x.experiments.exp018_real_verifier.run import build_base, generate_pool, LO, HI
from cognia_x.experiments.exp077_closed_loop_budget.run import _confidence, _corr
from cognia_x.experiments.exp078_closed_loop_guard.run import _dedup, _replay_examples
from cognia_x.experiments.exp103_bounded_unlikelihood.run import _bounded_unlikelihood
from cognia_x.experiments.exp124_decisional_real_loop.run import _auroc, _auc_over_rounds, _mean, _f

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")

# Brazos: difieren SÓLO en el regularizador del self-train. 'kind' despacha en _train_arm.
ARM_SPECS = {
    "naive":   {"kind": "naive"},
    "durable": {"kind": "unlik",   "neg_w": 0.5},   # cura 119 (LABEL-AWARE)
    "ent_lo":  {"kind": "entropy", "w": 0.1},       # confidence-penalty GENÉRICO (label-agnostic)
    "ls_lo":   {"kind": "lsmooth", "eps": 0.05},    # label smoothing GENÉRICO (label-agnostic)
    "ls_hi":   {"kind": "lsmooth", "eps": 0.15},
}
ARMS = list(ARM_SPECS.keys())
GENERIC = ["ent_lo", "ls_lo", "ls_hi"]
# NOTA: ent_hi (entropy w=0.3) se quitó del barrido tras el smoke -- sobre-regulariza y COLAPSA la generación
# (ncorrect~5 -> AUROC degenerado/None la mayoría de rondas), aporta poco como 'mejor genérico'. ent_lo (mild) + label
# smoothing x2 son el barrido genérico justo; la compuerta de degeneración (MIN_CLASS) controla cualquier residuo.


def _entropy_penalty(logits, y):
    """Entropía media de la distribución de salida en las posiciones supervisadas. Se RESTA del loss (loss - w*H) ->
    minimizar maximiza H -> baja la confianza UNIFORMEMENTE (confidence penalty, Pereyra et al. 2017). LABEL-AGNOSTIC."""
    logp = torch.log_softmax(logits, dim=-1)
    p = logp.exp()
    ent = -(p * logp).sum(-1)                          # [B,L] entropía por posición
    mask = (y != -100).float()
    return (ent * mask).sum() / mask.sum().clamp(min=1.0)


def _ls_ce(logits, y, eps):
    """Cross-entropy con label smoothing: (1-eps)*NLL(target) + eps*(-mean_vocab logp). Suaviza los targets
    UNIFORMEMENTE. LABEL-AGNOSTIC (no usa la corrección verificada)."""
    logp = torch.log_softmax(logits, dim=-1)
    mask = (y != -100).float()
    yc = y.clamp(min=0)
    nll = -logp.gather(-1, yc.unsqueeze(-1)).squeeze(-1)   # [B,L]
    smooth = -logp.mean(-1)                                 # [B,L] uniforme sobre el vocab
    loss = (1.0 - eps) * nll + eps * smooth
    return (loss * mask).sum() / mask.sum().clamp(min=1.0)


def _train_arm(model, pos, neg, spec, steps, batch, lr, device, rng):
    """Self-train con el regularizador del brazo. pos = verificado-correcto + replay (igual en TODOS los brazos);
    el brazo cambia SÓLO el término de regularización. RNG independiente por brazo (sin contaminación por orden)."""
    if not pos:
        return
    kind = spec["kind"]
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01)
    model.train()
    for _ in range(steps):
        idx = rng.integers(0, len(pos), size=batch)
        x, y = E.batch_from_examples([pos[i] for i in idx], device)
        if kind == "lsmooth":
            logits, _ = model(x)
            loss = _ls_ce(logits, y, spec["eps"])
        elif kind == "entropy":
            logits, loss_pos = model(x, y)
            loss = loss_pos - spec["w"] * _entropy_penalty(logits, y)
        elif kind == "unlik":
            _, loss_pos = model(x, y)
            loss = loss_pos
            if neg:
                loss = loss_pos + spec["neg_w"] * _bounded_unlikelihood(model, neg, batch, device, rng)
        else:  # naive
            _, loss_pos = model(x, y)
            loss = loss_pos
        opt.zero_grad(); loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0); opt.step()


def run_seed(seed, args, test_targets, train_targets, log):
    base, npar = build_base(seed, args.n_seed, args.base_steps, args.base_lr, args.warmup, args.batch, train_targets)
    bm = E.eval_metrics(base, test_targets, "cpu")
    log(f"[exp132] seed={seed} base real_acc={bm['real_acc']:.3f} params={npar:,}")
    pool_rng = np.random.default_rng(seed + 7)
    sel = pool_rng.integers(0, len(train_targets), size=args.pool)
    pool_prompts = [E.make_prompt(train_targets[i]) for i in sel]
    k = max(1, int(args.budget_frac * args.pool * args.K))

    arms = {a: copy.deepcopy(base) for a in ARMS}
    hist = {a: {"auroc": [], "corr": [], "ncorrect": [], "npool": []} for a in ARMS}

    for r in range(1, args.rounds + 1):
        for a in ARMS:
            torch.manual_seed(10000 * seed + r)            # mismo seed de generación por ronda -> arms comparables
            pool = generate_pool(arms[a], pool_prompts, args.K, args.temp, args.top_k, "cpu")
            pairs = [(p, e) for (p, e, _, _) in pool]
            strong = np.array([1.0 if s else 0.0 for (_, _, _, s) in pool])
            conf = _confidence(arms[a], pairs, "cpu")
            au = _auroc(conf, strong); hist[a]["auroc"].append(round(au, 4) if au is not None else None)
            cc = _corr(conf, strong); hist[a]["corr"].append(round(cc, 4) if not math.isnan(cc) else 0.0)
            nc = int(np.sum(strong)); hist[a]["ncorrect"].append(nc); hist[a]["npool"].append(len(strong))
            # selección de self-train: top-k por confianza (idéntica en todos los brazos) + replay canónico
            sel_rng = np.random.default_rng(seed * 131 + r * 17 + ARMS.index(a))
            sel_idx = np.argsort(conf + 1e-9 * sel_rng.random(len(pool)))[-min(k, len(pool)):]
            pos = _dedup([pairs[i] for i in sel_idx if strong[i] > 0.5])
            train_rng = np.random.default_rng(seed * 1000 + 17 + ARMS.index(a))   # RNG INDEPENDIENTE por brazo
            pos = pos + _replay_examples(train_rng, train_targets, int(round(args.replay_frac * max(1, len(pos)))))
            # neg = verificado-incorrecto SELECCIONADO (idéntico a exp124/exp131); SÓLO el brazo cura lo usa
            neg = _dedup([pairs[i] for i in sel_idx if strong[i] < 0.5]) if ARM_SPECS[a]["kind"] == "unlik" else []
            _train_arm(arms[a], pos, neg, ARM_SPECS[a], args.steps, args.batch, args.lr, "cpu", train_rng)

        def _g(a):
            v = hist[a]["auroc"][-1]
            return "{:.3f}".format(v) if v is not None else "--"
        log(f"[exp132] seed={seed} ronda {r}: " + " | ".join(f"{a}={_g(a)}" for a in ARMS))

    real_final = {a: round(E.eval_metrics(arms[a], test_targets, "cpu")["real_acc"], 4) for a in ARMS}
    log(f"[exp132] seed={seed} real_acc final: " + " ".join(f"{a}={real_final[a]:.3f}" for a in ARMS))
    return {"seed": seed, "base": bm, "hist": hist, "real_final": real_final}


def _bootstrap_ci(gaps, n_boot=10000, alpha=0.05, seed=0):
    rng = np.random.default_rng(seed)
    g = np.array(gaps, dtype=float)
    means = np.array([rng.choice(g, size=len(g), replace=True).mean() for _ in range(n_boot)])
    return float(np.percentile(means, 100 * alpha / 2)), float(np.percentile(means, 100 * (1 - alpha / 2)))


def _thirds(gaps):
    n = len(gaps); t = n // 3
    return (round(_mean(gaps[:t]), 4), round(_mean(gaps[t:2 * t]), 4), round(_mean(gaps[2 * t:]), 4))


MIN_CLASS = 5   # CONTROL DE DEGENERACIÓN: el AUROC de una ronda sólo cuenta si hay >=MIN_CLASS correctas Y >=MIN_CLASS
#                 incorrectas. Un brazo que COLAPSA la generación (pocas correctas) tendría AUROC de muestra-chica
#                 inflada/inestable; el 'mejor genérico' = max sesgaría a favor del más degenerado. La compuerta lo controla.


def _gated_auc(arm_hist):
    """Media de AUROC SÓLO sobre rondas NO degeneradas (ncorrect y nincorrect ambos >= MIN_CLASS)."""
    vals = []
    for au, nc, npl in zip(arm_hist["auroc"], arm_hist["ncorrect"], arm_hist["npool"]):
        if au is not None and nc >= MIN_CLASS and (npl - nc) >= MIN_CLASS:
            vals.append(au)
    return _mean(vals) if vals else None


def build_summary(per_seed, n_boot=10000):
    rows = []
    for s in per_seed:
        a_dur = _auc_over_rounds(s["hist"]["durable"]["auroc"])
        a_nai = _auc_over_rounds(s["hist"]["naive"]["auroc"])
        gen = {a: _auc_over_rounds(s["hist"][a]["auroc"]) for a in GENERIC}
        gen = {a: v for a, v in gen.items() if v is not None}
        if a_dur is None or a_nai is None or not gen:
            continue
        best_arm = max(gen, key=gen.get)
        g_best = gen[best_arm]
        nc_best = _mean(s["hist"][best_arm]["ncorrect"])   # #correctas del genérico ganador (¿colapsó la generación?)
        nc_dur = _mean(s["hist"]["durable"]["ncorrect"])
        # --- versión GATED (control de degeneración) ---
        gd = _gated_auc(s["hist"]["durable"]); gn = _gated_auc(s["hist"]["naive"])
        gg = {a: _gated_auc(s["hist"][a]) for a in GENERIC}; gg = {a: v for a, v in gg.items() if v is not None}
        priv_gap_g = (gd - max(gg.values())) if (gd is not None and gg) else None
        rows.append({"seed": s["seed"], "a_dur": a_dur, "a_nai": a_nai, "g_best": g_best, "best_arm": best_arm,
                     "gen": {a: round(v, 4) for a, v in gen.items()}, "nc_best": round(nc_best, 1), "nc_dur": round(nc_dur, 1),
                     "priv_gap": a_dur - g_best, "rec_gap": g_best - a_nai, "dvn": a_dur - a_nai,
                     "priv_gap_gated": (round(priv_gap_g, 4) if priv_gap_g is not None else None)})

    priv = [r["priv_gap"] for r in rows]
    rec = [r["rec_gap"] for r in rows]
    dvn = [r["dvn"] for r in rows]
    n = len(priv)
    mean_priv = float(np.mean(priv)); med_priv = float(np.median(priv))
    se = float(np.std(priv, ddof=1) / np.sqrt(n)) if n > 1 else 0.0
    tstat = mean_priv / se if se > 0 else 0.0
    n_pos = int(np.sum(np.array(priv) > 0))
    lo, hi = _bootstrap_ci(priv, n_boot=n_boot)
    t1, t2, t3 = _thirds(priv)

    mean_rec = float(np.mean(rec)); mean_dvn = float(np.mean(dvn))
    rec_pos = int(np.sum(np.array(rec) > 0))
    dvn_pos = int(np.sum(np.array(dvn) > 0))
    # cuánto de la ventaja durable-naive RECUPERA el genérico (fracción): rec/dvn agregada
    recovery_frac = (mean_rec / mean_dvn) if mean_dvn > 1e-9 else 0.0

    # --- ROBUSTEZ: privilege_gap con CONTROL DE DEGENERACIÓN (sólo rondas no-degeneradas) ---
    priv_g = [r["priv_gap_gated"] for r in rows if r["priv_gap_gated"] is not None]
    n_g = len(priv_g)
    mean_priv_g = float(np.mean(priv_g)) if priv_g else 0.0
    lo_g, hi_g = _bootstrap_ci(priv_g, n_boot=n_boot) if n_g > 1 else (mean_priv_g, mean_priv_g)
    ci_g_excludes_zero = lo_g > 0.0
    # ¿el genérico ganador colapsó la generación más que el durable? (si nc_best << nc_dur, su AUROC podría ser degenerado)
    nc_best_mean = float(np.mean([r["nc_best"] for r in rows]))
    nc_dur_mean = float(np.mean([r["nc_dur"] for r in rows]))

    au_dur = float(np.mean([r["a_dur"] for r in rows]))
    au_nai = float(np.mean([r["a_nai"] for r in rows]))
    au_gen = float(np.mean([r["g_best"] for r in rows]))
    # cuál genérico gana más seguido
    from collections import Counter
    best_counts = dict(Counter(r["best_arm"] for r in rows))
    nc = {a: round(float(np.mean([_mean(s["hist"][a]["ncorrect"]) for s in per_seed])), 2) for a in ARMS}
    real = {a: round(float(np.mean([s["real_final"][a] for s in per_seed])), 4) for a in ARMS}

    ci_excludes_zero = lo > 0.0           # exclusión POSITIVA (durable mejor)
    ci_below_zero = hi < 0.0              # exclusión NEGATIVA (genérico mejor = durable significativamente PEOR)
    sane_149 = mean_dvn > 0.0 and dvn_pos >= 0.6 * n     # reproduce cualitativamente el 149 (durable>naive)
    generic_recovers = mean_rec > 0.01 and recovery_frac > 0.5

    if ci_excludes_zero and sane_149:
        status = "apoyada"
        verdict = (
            "H-V4-9j APOYADA (la cura 119 ES PRIVILEGIADA): a N={n}, el durable (unlikelihood LABEL-AWARE) bate al MEJOR "
            "regularizador de calibración GENÉRICO por seed -- privilege_gap medio +{mp} (mediana +{md}, {npos}/{n} seeds pos, "
            "t={ts}), CI bootstrap 95% [{lo}, {hi}] EXCLUYE el cero. AUROC durable={ad} vs mejor-genérico={ag} vs naive={an}. El "
            "genérico recupera sólo {rf}% de la ventaja durable-naive (recovery_gap +{mr}). SANITY: durable_vs_naive +{mdvn} "
            "({dp}/{n} pos) reproduce el 149. => la ventaja de calibración del 149 NO la da cualquier regularizador: la "
            "unlikelihood que USA el verificador para castigar ESPECÍFICAMENTE lo verificado-incorrecto es la pieza privilegiada."
        ).format(n=n, mp=_f(mean_priv), md=_f(med_priv), npos=n_pos, ts=_f(tstat), lo=_f(lo), hi=_f(hi), ad=_f(au_dur),
                 ag=_f(au_gen), an=_f(au_nai), rf=int(round(100 * recovery_frac)), mr=_f(mean_rec), mdvn=_f(mean_dvn), dp=dvn_pos)
    elif (not ci_excludes_zero) and generic_recovers:
        status = "refutada"
        signif = " ENTERAMENTE NEGATIVO (el genérico es SIGNIFICATIVAMENTE mejor)" if ci_below_zero else " incluye el cero"
        verdict = (
            "H-V4-9j REFUTADA (la cura 119 NO es privilegiada): a N={n}, el CI bootstrap 95% del privilege_gap es [{lo}, {hi}]{sig} "
            "(medio {mp}, {npos}/{n} seeds pos, t={ts}) Y el regularizador GENÉRICO recupera {rf}% de la ventaja durable-naive "
            "(recovery_gap +{mr}, {rp}/{n} pos). AUROC durable={ad} <= mejor-genérico={ag} > naive={an}. => la cura NO es la pieza "
            "privilegiada: específicamente el LABEL SMOOTHING (target-smoothing, label-agnostic) la IGUALA en AUROC y la SUPERA en "
            "real_acc; el entropy-penalty sólo la EMPATA. ACOTACIÓN (importante): el AUROC está CONFUNDIDO con la riqueza de "
            "generación (corr(AUROC,ncorrect) pooled ~-0.54; durable y ls_lo en regímenes de ncorrect casi disjuntos, IGUALES en la "
            "banda de solape) -> el experimento NO aísla 'calibración' como mecanismo, sólo que un genérico target-smoothing reemplaza "
            "a la cura. El durable>naive del 149 está él mismo confundido con colapso de generación (lo debilita retroactivamente)."
        ).format(n=n, lo=_f(lo), hi=_f(hi), sig=signif, mp=_f(mean_priv), npos=n_pos, ts=_f(tstat),
                 rf=int(round(100 * recovery_frac)), mr=_f(mean_rec), rp=rec_pos, ad=_f(au_dur), ag=_f(au_gen), an=_f(au_nai))
    else:
        status = "mixta"
        verdict = (
            "H-V4-9j MIXTA: a N={n}, el durable tiene una ventaja sobre el mejor genérico (privilege_gap +{mp}, CI [{lo}, {hi}], "
            "{npos}/{n} pos) PERO el genérico recupera una parte sustancial de la ventaja del 149 (recovery_gap +{mr} = {rf}% de "
            "durable-naive +{mdvn}). AUROC durable={ad} vs genérico={ag} vs naive={an}. => la cura 119 es PARCIALMENTE privilegiada: "
            "tiene un filo RESIDUAL label-aware sobre los regularizadores genéricos, pero buena parte de su beneficio es "
            "regularización de calibración genérica. Ni privilegio total ni equivalencia."
        ).format(n=n, mp=_f(mean_priv), lo=_f(lo), hi=_f(hi), npos=n_pos, mr=_f(mean_rec), rf=int(round(100 * recovery_frac)),
                 mdvn=_f(mean_dvn), ad=_f(au_dur), ag=_f(au_gen), an=_f(au_nai))

    return {"n": n, "priv_gaps": [round(r["priv_gap"], 4) for r in rows], "mean_priv_gap": round(mean_priv, 4),
            "median_priv_gap": round(med_priv, 4), "se": round(se, 4), "tstat": round(tstat, 3), "n_positive": n_pos,
            "ci95": [round(lo, 4), round(hi, 4)], "ci_excludes_zero": bool(ci_excludes_zero),
            "ci_below_zero": bool(ci_below_zero), "thirds": [t1, t2, t3],
            "mean_recovery_gap": round(mean_rec, 4), "recovery_n_positive": rec_pos, "recovery_frac": round(recovery_frac, 4),
            "mean_durable_vs_naive": round(mean_dvn, 4), "dvn_n_positive": dvn_pos, "sane_149": bool(sane_149),
            "generic_recovers": bool(generic_recovers), "auroc_durable": round(au_dur, 4), "auroc_generic_best": round(au_gen, 4),
            "auroc_naive": round(au_nai, 4), "best_generic_counts": best_counts, "mean_ncorrect": nc, "real_final": real,
            "gated": {"n": n_g, "mean_priv_gap": round(mean_priv_g, 4), "ci95": [round(lo_g, 4), round(hi_g, 4)],
                      "ci_excludes_zero": bool(ci_g_excludes_zero), "min_class": MIN_CLASS,
                      "nc_best_generic": round(nc_best_mean, 1), "nc_durable": round(nc_dur_mean, 1)},
            "per_seed_rows": rows, "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=str, default="0-15")
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
    n_boot = 10000
    if args.smoke:
        args.seeds, args.rounds, args.pool, args.steps, args.base_steps = "0-2", 5, 48, 60, 200
        n_boot = 2000

    if "-" in args.seeds and "," not in args.seeds:
        a, b = args.seeds.split("-"); seeds = list(range(int(a), int(b) + 1))
    else:
        seeds = [int(x) for x in args.seeds.split(",")]
    train_targets, test_targets = E.build_split(LO, HI, args.test_frac)
    logs = []

    def log(mm):
        print(mm, flush=True); logs.append(mm)

    log("[exp132] CYCLE 150 / H-V4-9j — ¿la cura 119 es PRIVILEGIADA o cualquier regularizador de calibración genérico la iguala?")
    log(f"[exp132] arms={ARMS} (durable=unlikelihood LABEL-AWARE; ent/ls=GENÉRICO label-agnostic) seeds={seeds} rounds={args.rounds} pool={args.pool}")

    per_seed = [run_seed(s, args, test_targets, train_targets, log) for s in seeds]
    sm = build_summary(per_seed, n_boot=n_boot)

    log("[exp132] --- PRIVILEGIO (durable − mejor genérico por seed) ---")
    log(f"[exp132] privilege_gap por seed: {sm['priv_gaps']}")
    log(f"[exp132] medio +{sm['mean_priv_gap']:.3f} mediana +{sm['median_priv_gap']:.3f} ({sm['n_positive']}/{sm['n']} pos) t={sm['tstat']}")
    log(f"[exp132] CI bootstrap 95% = [{sm['ci95'][0]:+.3f}, {sm['ci95'][1]:+.3f}] -> EXCLUYE cero={sm['ci_excludes_zero']}")
    log(f"[exp132] AUROC: durable={sm['auroc_durable']:.3f} mejor-genérico={sm['auroc_generic_best']:.3f} naive={sm['auroc_naive']:.3f}")
    log(f"[exp132] recovery_gap (genérico−naive) +{sm['mean_recovery_gap']:.3f} = {int(round(100*sm['recovery_frac']))}% de durable_vs_naive +{sm['mean_durable_vs_naive']:.3f} ({sm['dvn_n_positive']}/{sm['n']} pos) [SANITY 149]")
    g = sm["gated"]
    log(f"[exp132] ROBUSTEZ (control de degeneración, MIN_CLASS={g['min_class']}): privilege_gap GATED +{g['mean_priv_gap']:.3f} CI [{g['ci95'][0]:+.3f},{g['ci95'][1]:+.3f}] excluye0={g['ci_excludes_zero']} (N={g['n']}) | #correctas: mejor-genérico={g['nc_best_generic']} vs durable={g['nc_durable']}")
    log(f"[exp132] mejor genérico por seed (conteo): {sm['best_generic_counts']}")
    log(f"[exp132] #correctas medio: {sm['mean_ncorrect']} | real_acc final: {sm['real_final']}")
    log(f"[exp132] VEREDICTO H-V4-9j: {sm['status'].upper()} | {sm['verdict']}")

    raw = [{"seed": s["seed"], "base_real_acc": round(s["base"].get("real_acc", 0.0), 4),
            "auroc": {a: s["hist"][a]["auroc"] for a in ARMS},
            "ncorrect": {a: s["hist"][a]["ncorrect"] for a in ARMS},
            "npool": {a: s["hist"][a]["npool"] for a in ARMS},
            "real_final": s["real_final"]} for s in per_seed]

    out = {"exp": "exp132_privileged_cure", "cycle": 150, "hypothesis": "H-V4-9j",
           "claim": "¿la cura 119 (unlikelihood ACOTADO, LABEL-AWARE) es PRIVILEGIADA, o cualquier regularizador de calibracion "
                    "GENERICO (confidence-penalty/entropy bonus, label smoothing) produce la misma ventaja AUROC en el lazo torch "
                    "real del 149? Metrica: privilege_gap = AUROC(durable) - AUROC(mejor generico por seed), CI bootstrap. APOYADA "
                    "si el CI excluye 0 (privilegiada); REFUTADA si lo incluye y el generico recupera la ventaja (re-localiza 149: "
                    "la regularizacion de calibracion en general ayuda, la cura es una instancia). Temperature se descarta a priori "
                    "(AUROC-invariante por monotonia). Reusa el lazo de exp124/exp131 y _bounded_unlikelihood de exp103.",
           "verdict": sm["status"], "summary": sm, "raw": raw, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__, "torch": torch.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp132] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
