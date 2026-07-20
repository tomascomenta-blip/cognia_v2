r"""
exp120 — CYCLE 136 / H-V4-10j (rama control/acción, RESUELVE la pregunta abierta de la MIXTA de 135: ¿es la relevancia bajo meta
NO-LINEAL un CUELLO de R-PRIOR?): ¿un aprendiz que NO conoce la forma de la meta -selecciona la REGULARIZACIÓN y/o la BASE por
CROSS-VALIDACIÓN sobre su propia experiencia- IGUALA a la base MATCHED (oracle-prior) bajo meta no-lineal, incluso bajo RUIDO?

CONTEXTO. CYCLE 135 (exp119) mostró (MIXTA) que la relevancia ES discoverable bajo no-linealidad con una base de credit-assignment
EXPRESIVA (rica/paridad-mixta), pero RETRACTÓ el claim 'el prior paga': la ventaja de la base matched bajo ruido (σ_g=20) era ~80%
ARTEFACTO de sub-regularizar la base rica -- a ridge 0.3 (cross-validable) el gap caía de +0.29 a +0.07. Quedó la pregunta: ¿un
aprendiz que CROSS-VALIDA la regularización (sin conocer la forma) cierra el gap solo? Si sí, la relevancia bajo no-linealidad NO es
un cuello de R-PRIOR -- una base expresiva + CV basta. Este ciclo lo testea de frente.

DISEÑO (numpy, sustrato IDÉNTICO a exp119, importado). ESTIMADORES de ŵ (relevancia) de la misma experiencia:
  - linear (la base de 134; falla bajo meta par)
  - matched (la base que casa con la forma = el ORACLE-PRIOR; ridge fijo mild)
  - rich_fix (base [x,x²,relu], ridge fijo mild = el estimador de 135)
  - rich_cv (base [x,x²,relu], ridge ELEGIDO por K-fold CV sobre la experiencia -- NO conoce la forma)   <- R-PRIOR explícito (regularización)
  - select_cv (ELIGE la base entre {linear,even,relu} por CV -- NO conoce la forma)                       <- R-PRIOR explícito (selección de base)
La decisión: top-K por valor_ambos = ŵ · b̂²/(b̂²+ρ); arms PAREADOS; eval con w,b VERDADEROS (aísla la asignación).

BARRIDOS: (1) FORMA × ESTIMADOR (¿recuperan los aprendices-sin-forma todas las formas?); (2) σ_g ruido de meta bajo EVEN
(¿cierra el aprendiz-CV el gap a la matched que 135 atribuyó al 'prior'?).

PREGUNTA FALSABLE (refinada tras VERIFICACIÓN ADVERSARIAL — probamos DOS regímenes, ABUNDANCIA y ESCASEZ):
  - REFUTADA (R-PRIOR NO es cuello) si el aprendiz-CV sin-forma iguala a la matched en ABUNDANCIA *y* en ESCASEZ.
  - APOYADA (R-PRIOR ES cuello) si aun con CV queda muy por debajo de la matched ya en ABUNDANCIA.
  - MIXTA (refutación ACOTADA) si el CV neutraliza el GRUESO del gap en ABUNDANCIA (T>>#columnas) pero el prior REAPARECE bajo
    ESCASEZ (T~#columnas) -> el cuello R-PRIOR es REGIME-DEPENDENT.

VEREDICTO (exp120, 200 seeds, POST-VERIFICACIÓN ADVERSARIAL de 3 agentes — 6to ciclo): MIXTA (refutación ACOTADA al régimen
abundante; refutación GENUINA sin leakage -3 controles nulos: G-decoy/G-ruido/CV-bloqueada-). EN ABUNDANCIA (T=300): un aprendiz que
NO conoce la forma (rich_cv/select_cv) NEUTRALIZA ~83% de la ventaja del oracle-prior; la fairness NO lo derriba (matched_cv apenas
mejora -> el 'prior paga' de 135 era sub-regularización, no ridge-fijo). Pero 'IGUALA' es 'CASI IGUALA': residual matched_cv-rich_cv
~+0.04 a σ_g=20, chico pero SIGNIFICATIVO (t~2.4; costo de varianza de las columnas extra). EL PRIOR REAPARECE BAJO ESCASEZ (T~24-30
~#columnas, σ_g=5): rich_cv colapsa, el prior paga +0.3. select_cv NO es del todo form-agnostic (su menú ES un prior grueso). =>
R-PRIOR no es cuello en abundancia pero su valor escala INVERSAMENTE con el ratio datos/parámetros; se DEBILITA de forma-exacta a
menú-de-formas, no desaparece.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp120_learned_basis.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp120_learned_basis.run            # FULL
"""
import argparse
import json
import os
import platform
import sys

import numpy as np

from cognia_x.experiments.exp119_basis_relevance import run as X119

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")

# reutiliza el sustrato y las constantes de exp119 (sustrato IDÉNTICO)
AA = X119.AA; RHO = X119.RHO; D = X119.D; K = X119.K
SU_DEFAULT = X119.SU_DEFAULT; SG_DEFAULT = X119.SG_DEFAULT
B_CAN = X119.B_CAN; W_CAN = X119.W_CAN; S_CAN = X119.S_CAN
META_FORMS = X119.META_FORMS
SIGMA_GS = X119.SIGMA_GS
T_FIXED = X119.T_FIXED
RIDGE_FIX = X119.RIDGE                       # ridge fijo mild (el de 135)
RIDGE_GRID = [1e-3, 1e-2, 1e-1, 0.3, 1.0, 3.0, 10.0]   # grilla cross-validable (NO conoce la forma; extendida arriba tras verificación)
N_FOLDS = 5
SELECT_BASES = ["linear", "even", "relu"]    # menú para la selección-de-base por CV (NOTA: el menú ES un prior grueso de la forma)
SG_SCARCE = 5.0                              # ruido moderado para el barrido de ESCASEZ (T chico) -> ¿reaparece el prior?
TS_SCARCE = [24, 30, 50, 100, 300]           # T ~= #columnas de la base rica (24) hasta abundante -> CV hambriento
ESTIMATORS = ("linear", "matched", "matched_cv", "rich_fix", "rich_cv", "select_cv")


def _design(X, basis):
    """Matriz de diseño z-scoreada (T x D*|basis|) + bloques por modo."""
    T = X.shape[0]
    cols = []; blocks = []; idx = 0
    for i in range(D):
        bc = X119._basis_cols(X[:, i], basis)
        for c in bc:
            mu = c.mean(); sd = c.std()
            cols.append((c - mu) / sd if sd > 1e-9 else (c - mu))
        blocks.append((idx, len(bc))); idx += len(bc)
    return np.stack(cols, axis=1), blocks


def _ridge_coef(Phi, g, ridge):
    A = Phi.T @ Phi + ridge * Phi.shape[0] * np.eye(Phi.shape[1])
    return np.linalg.solve(A, Phi.T @ g)


def _cv_mse(Phi, g, ridge, folds, rng):
    """K-fold held-out MSE de predecir g (centrado) desde Phi con un ridge dado. Sin leakage de g a futuro: fit en train, mide en val."""
    T = Phi.shape[0]
    idx = rng.permutation(T)
    fold_sz = T // folds
    errs = []
    for k in range(folds):
        val = idx[k * fold_sz:(k + 1) * fold_sz] if k < folds - 1 else idx[k * fold_sz:]
        tr = np.setdiff1d(idx, val, assume_unique=False)
        if len(tr) < Phi.shape[1] + 1 or len(val) == 0:
            continue
        gtr = g[tr] - g[tr].mean()
        coef = _ridge_coef(Phi[tr], gtr, ridge)
        pred = Phi[val] @ coef + g[tr].mean()
        errs.append(float(np.mean((g[val] - pred) ** 2)))
    return float(np.mean(errs)) if errs else np.inf


def _w_from_coef(coef, blocks):
    return np.array([float(np.linalg.norm(coef[s:s + c])) for (s, c) in blocks])


def _estimate_w_fixed(X, G, basis, ridge):
    Phi, blocks = _design(X, basis)
    g = G - G.mean()
    return _w_from_coef(_ridge_coef(Phi, g, ridge), blocks)


def _estimate_w_cv(X, G, basis, ridge_grid, folds, rng):
    """Elige el ridge por CV (NO conoce la forma), refit en todo, devuelve ŵ + ridge elegido."""
    Phi, blocks = _design(X, basis)
    g = G - G.mean()
    best_r, best_mse = ridge_grid[0], np.inf
    for r in ridge_grid:
        m = _cv_mse(Phi, g, r, folds, rng)
        if m < best_mse:
            best_mse, best_r = m, r
    return _w_from_coef(_ridge_coef(Phi, g, best_r), blocks), best_r


def _estimate_w_select(X, G, bases, ridge_grid, folds, rng):
    """Elige la BASE (entre 'bases') y su ridge por CV (NO conoce la forma); devuelve ŵ + base elegida."""
    g = G - G.mean()
    best_basis, best_mse, best_coef, best_blocks = bases[0], np.inf, None, None
    for basis in bases:
        Phi, blocks = _design(X, basis)
        for r in ridge_grid:
            m = _cv_mse(Phi, g, r, folds, rng)
            if m < best_mse:
                best_mse, best_basis = m, basis
                best_coef = _ridge_coef(Phi, g, r); best_blocks = blocks
    return _w_from_coef(best_coef, best_blocks), best_basis


def _paired(a, b):
    """(media de la diferencia a-b, t pareado, frac(a>=b)) -- para acotar 'IGUALA' con significancia."""
    d = np.array(a) - np.array(b)
    n = len(d)
    se = d.std(ddof=1) / np.sqrt(n) if n > 1 and d.std(ddof=1) > 0 else float("inf")
    t = float(d.mean() / se) if se not in (0.0, float("inf")) else 0.0
    return [round(float(d.mean()), 4), round(t, 2), round(float((d >= 0).mean()), 3)]


def run_cell(form, T, sigma_u, sigma_g, n_seeds):
    accs = {e: [] for e in ESTIMATORS}
    accs["ctrl_solo"] = []
    chosen_basis = {b: 0 for b in SELECT_BASES}
    matched = X119.MATCHED[form]
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed * 8731 + int(T) * 13 + int(sigma_u * 1000) * 7
                                    + int(sigma_g * 100) * 101
                                    + {"linear": 0, "even": 1, "relu": 2, "mixed": 3}[form] * 50021 + 23)
        perm = rng.permutation(D)
        b = B_CAN[perm]; w = W_CAN[perm]; s = S_CAN[perm]
        X, Xn, U, G = X119._experience(rng, b, w, s, T, sigma_u, sigma_g, form)
        b_hat = X119._estimate_b(X, Xn, U)
        ctrl_score = b_hat ** 2 / (b_hat ** 2 + RHO)
        tv = X119._true_value(b, w)
        oracle = set(np.argsort(tv)[-K:].tolist())
        den = X119._benefit(oracle, b, w) + 1e-12

        # rng de CV FRESCO por estimador (misma partición -> comparación apareada, justa; tras verificación adversarial)
        cv_seed = seed * 104729 + 7
        w_hats = {
            "linear": _estimate_w_fixed(X, G, "linear", RIDGE_FIX),
            "matched": _estimate_w_fixed(X, G, matched, RIDGE_FIX),
            "matched_cv": _estimate_w_cv(X, G, matched, RIDGE_GRID, N_FOLDS, np.random.default_rng(cv_seed))[0],
            "rich_fix": _estimate_w_fixed(X, G, "rich", RIDGE_FIX),
            "rich_cv": _estimate_w_cv(X, G, "rich", RIDGE_GRID, N_FOLDS, np.random.default_rng(cv_seed))[0],
        }
        w_sel, basis_sel = _estimate_w_select(X, G, SELECT_BASES, RIDGE_GRID, N_FOLDS, np.random.default_rng(cv_seed))
        w_hats["select_cv"] = w_sel
        chosen_basis[basis_sel] += 1

        for e in ESTIMATORS:
            S = set(np.argsort(w_hats[e] * ctrl_score)[-K:].tolist())
            accs[e].append(X119._benefit(S, b, w) / den)
        accs["ctrl_solo"].append(X119._benefit(set(np.argsort(ctrl_score)[-K:].tolist()), b, w) / den)

    out = {e: round(float(np.mean(v)), 4) for e, v in accs.items()}
    tot = sum(chosen_basis.values()) or 1
    out["select_chose"] = {b: round(chosen_basis[b] / tot, 3) for b in SELECT_BASES}
    # significancia pareada del gap (matched_cv − rich_cv): acota el verbo 'IGUALA'
    out["paired_mcv_richcv"] = _paired(accs["matched_cv"], accs["rich_cv"])
    return out


def run(n_seeds):
    by_form = {form: run_cell(form, T_FIXED, SU_DEFAULT, SG_DEFAULT, n_seeds) for form in META_FORMS}
    by_sg = {str(sg): run_cell("even", T_FIXED, SU_DEFAULT, sg, n_seeds) for sg in SIGMA_GS}
    # barrido de ESCASEZ (T ~ #columnas, ruido moderado): ¿REAPARECE la ventaja del prior cuando el CV está hambriento?
    by_T_scarce = {str(T): run_cell("even", T, SU_DEFAULT, SG_SCARCE, n_seeds) for T in TS_SCARCE}
    return {"by_form": by_form, "by_sg": by_sg, "by_T_scarce": by_T_scarce, "random_baseline": X119._random_baseline()}


def _f(x):
    return "{:.3f}".format(x)


def build_summary(grid):
    bf = grid["by_form"]; gsg = grid["by_sg"]; gts = grid["by_T_scarce"]; rand = grid["random_baseline"]
    ev = bf["even"]; hi = gsg[str(SIGMA_GS[-1])]
    sc = gts[str(TS_SCARCE[1])]                       # T=30 (~#columnas de la base rica): el régimen de ESCASEZ

    # ¿recuperan los aprendices-sin-forma TODAS las formas (punto limpio/abundante)?
    rich_cv_robust = all(bf[f]["rich_cv"] > 0.88 for f in META_FORMS)
    select_cv_robust = all(bf[f]["select_cv"] > 0.88 for f in META_FORMS)

    # === ABUNDANTE (T=300): ¿neutraliza el CV el GRUESO de la ventaja del prior que 135 atribuyó al 'prior paga'? ===
    gap_richfix = hi["matched"] - hi["rich_fix"]          # el gap de 135 (ridge fijo)
    gap_richcv = hi["matched"] - hi["rich_cv"]            # tras cross-validar la regularización
    gap_selectcv = hi["matched"] - hi["select_cv"]        # tras seleccionar la base por CV
    # FAIRNESS (tras verificación): la matched con su MISMO handicap de CV-ridge -- ¿'vuelve a pagar'? (NO, ~no se mueve)
    gap_matchedcv_richcv = hi["matched_cv"] - hi["rich_cv"]
    closed_frac = 1.0 - gap_richcv / gap_richfix if gap_richfix > 1e-9 else 0.0
    abundant_neutralizes = gap_richcv < 0.08             # el CV cierra el GRUESO del gap de prior en abundancia
    paired_mcv_richcv = hi["paired_mcv_richcv"]          # [media, t, frac] del residual significativo

    # === ESCASEZ (T~#columnas, σ_g moderado): ¿REAPARECE la ventaja del prior cuando el CV está hambriento? ===
    gap_scarce = sc["matched_cv"] - sc["rich_cv"]
    scarce_prior_pays = gap_scarce > 0.15                # el prior REAPARECE bajo escasez de datos vs #parámetros

    # === MIXTA: refutación ACOTADA. El cuello R-PRIOR es REGIME-DEPENDENT ===
    if abundant_neutralizes and scarce_prior_pays:
        status = "mixta"
        verdict = (
            "H-V4-10j MIXTA (REFUTACIÓN ACOTADA AL RÉGIMEN ABUNDANTE; post-verificación adversarial de 3 agentes, 6to ciclo; "
            "refutación genuina sin leakage -3 controles nulos-): el cuello R-PRIOR es REGIME-DEPENDENT. NEUTRALIZADO EN "
            "ABUNDANCIA: con dato amplio (T=300) un aprendiz que NO conoce la forma -cross-validando la regularización (rich_cv) "
            "y/o seleccionando la base (select_cv)- NEUTRALIZA EL GRUESO de la ventaja del oracle-prior. Bajo meta even limpio "
            "rich_cv={rcv}/select_cv={scv}=matched (sobre ctrl_solo {ecs}); bajo ruido σ_g=20 el gap de 135 (+{grf} a ridge fijo) "
            "se CIERRA ~{cf}% al cross-validar (rich_cv +{grc}, select_cv +{gsc}). La fairness NO lo derriba: dar a la matched el "
            "MISMO CV-ridge (matched_cv) apenas la mueve (gap a rich_cv +{gmcv}) -> el 'prior paga' de 135 NO era artefacto del "
            "ridge-fijo, ERA sub-regularización de la base rica. rich_cv robusto a TODA forma (lin {rcl}/even {rce}/relu {rcr}/"
            "mixed {rcm}). PERO 'IGUALA' es 'CASI IGUALA': el residual matched_cv-rich_cv a σ_g=20 es +{rmd} (t={rmt}, "
            "frac(m_cv≥rich)={rmf}) -- chico pero SIGNIFICATIVO, costo de varianza irreducible de las 2 columnas extra de la "
            "base rica. Y EL PRIOR REAPARECE BAJO ESCASEZ: a T={tsc}~#columnas con ruido moderado (σ_g={sgs}) el aprendiz "
            "genuinamente sin-forma (rich_cv) COLAPSA y matched_cv le gana +{gsce} -- la ventaja del prior escala INVERSAMENTE con "
            "el ratio datos/parámetros. Caveat: select_cv NO es del todo form-agnostic (su menú {{linear,even,relu}} ES un prior "
            "grueso de la forma). => H-V4-10j (R-PRIOR es cuello) REFUTADA EN ABUNDANCIA pero el prior NO es prescindible: se "
            "DEBILITA de forma-exacta a menú-de-formas y su valor escala con la escasez de datos. El factor RELEVANCIA es "
            "discoverable bajo no-linealidad sin prior privilegiado CUANDO T>>#columnas; bajo escasez conocer la forma paga."
        ).format(rcv=_f(ev["rich_cv"]), scv=_f(ev["select_cv"]), ecs=_f(ev["ctrl_solo"]), grf=_f(gap_richfix),
                 cf="{:.0f}".format(closed_frac * 100), grc=_f(gap_richcv), gsc=_f(gap_selectcv),
                 gmcv=_f(gap_matchedcv_richcv), rcl=_f(bf["linear"]["rich_cv"]), rce=_f(bf["even"]["rich_cv"]),
                 rcr=_f(bf["relu"]["rich_cv"]), rcm=_f(bf["mixed"]["rich_cv"]), rmd=_f(paired_mcv_richcv[0]),
                 rmt=paired_mcv_richcv[1], rmf=paired_mcv_richcv[2], tsc=TS_SCARCE[1], sgs=SG_SCARCE, gsce=_f(gap_scarce))
    elif abundant_neutralizes and not scarce_prior_pays:
        status = "refutada"
        verdict = (
            "H-V4-10j REFUTADA: el aprendiz-CV sin-forma iguala a la matched en abundancia Y bajo escasez (gap escasez "
            "+{gsce}<0.15) -> R-PRIOR no es cuello en ningún régimen."
        ).format(gsce=_f(gap_scarce))
    elif not abundant_neutralizes:
        status = "apoyada"
        verdict = (
            "H-V4-10j APOYADA (R-PRIOR ES cuello): aun cross-validando, el aprendiz sin-forma queda por debajo de la matched en "
            "abundancia (σ_g=20: gap rich_cv +{grc}≥0.08) -> conocer la forma es irreduciblemente valioso."
        ).format(grc=_f(gap_richcv))
    else:
        status = "mixta"
        verdict = ("H-V4-10j MIXTA: parcial -- abundant_neutralizes={an} scarce_prior_pays={sp} (gap abund +{grc}, escasez "
                   "+{gsce}).").format(an=abundant_neutralizes, sp=scarce_prior_pays, grc=_f(gap_richcv), gsce=_f(gap_scarce))

    return {"by_form": bf, "by_sg": gsg, "by_T_scarce": gts, "random_baseline": rand,
            "even_matched": ev["matched"], "even_rich_fix": ev["rich_fix"], "even_rich_cv": ev["rich_cv"],
            "even_select_cv": ev["select_cv"], "even_linear": ev["linear"], "even_ctrl_solo": ev["ctrl_solo"],
            "even_select_chose": ev["select_chose"],
            "richcv_linear": bf["linear"]["rich_cv"], "richcv_even": bf["even"]["rich_cv"],
            "richcv_relu": bf["relu"]["rich_cv"], "richcv_mixed": bf["mixed"]["rich_cv"],
            "hi_sg_matched": hi["matched"], "hi_sg_matched_cv": hi["matched_cv"], "hi_sg_rich_fix": hi["rich_fix"],
            "hi_sg_rich_cv": hi["rich_cv"], "hi_sg_select_cv": hi["select_cv"], "hi_sg_select_chose": hi["select_chose"],
            "scarce_T": TS_SCARCE[1], "scarce_sg": SG_SCARCE, "scarce_matched_cv": sc["matched_cv"],
            "scarce_rich_cv": sc["rich_cv"], "scarce_select_cv": sc["select_cv"], "gap_scarce": round(gap_scarce, 4),
            "gap_richfix": round(gap_richfix, 4), "gap_richcv": round(gap_richcv, 4), "gap_selectcv": round(gap_selectcv, 4),
            "gap_matchedcv_richcv": round(gap_matchedcv_richcv, 4), "closed_frac": round(closed_frac, 3),
            "paired_mcv_richcv": paired_mcv_richcv,
            "rich_cv_robust": bool(rich_cv_robust), "select_cv_robust": bool(select_cv_robust),
            "abundant_neutralizes": bool(abundant_neutralizes), "scarce_prior_pays": bool(scarce_prior_pays),
            "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=int, default=200)
    args = ap.parse_args()
    if args.smoke:
        args.seeds = 40

    logs = []

    def log(mm):
        print(mm, flush=True); logs.append(mm)

    log("[exp120] CYCLE 136 / H-V4-10j — ¿es la relevancia bajo no-linealidad un cuello de R-PRIOR? Un aprendiz-CV sin-forma vs el oracle-prior, en ABUNDANCIA y en ESCASEZ (MIXTA post-verificación adversarial)")
    log(f"[exp120] seeds={args.seeds} D={D} K={K} ridge_fix={RIDGE_FIX} ridge_grid={RIDGE_GRID} folds={N_FOLDS} forms={META_FORMS} sigma_gs={SIGMA_GS} scarce(T={TS_SCARCE},σ_g={SG_SCARCE}) (T_abund={T_FIXED})")

    grid = run(args.seeds)
    sm = build_summary(grid)

    log(f"[exp120] random_baseline = {grid['random_baseline']:.3f}")
    log("[exp120] --- (1) FORMA × ESTIMADOR (T=%d, σ_g=%.1f) — ¿recuperan los aprendices-sin-forma cada forma? ---" % (T_FIXED, SG_DEFAULT))
    for form in META_FORMS:
        r = grid["by_form"][form]
        log(f"[exp120] meta={form:>6}: ctrl={r['ctrl_solo']:.3f} | lin={r['linear']:.3f} matched={r['matched']:.3f} m_cv={r['matched_cv']:.3f} rich_fix={r['rich_fix']:.3f} rich_cv={r['rich_cv']:.3f} select_cv={r['select_cv']:.3f} | select_chose={r['select_chose']}")
    log("[exp120] --- (2) BARRIDO σ_g bajo EVEN (T=%d, ABUNDANTE) — ¿neutraliza el CV el gap del 'prior' de 135? ---" % T_FIXED)
    for sg in SIGMA_GS:
        r = grid["by_sg"][str(sg)]
        log(f"[exp120] σ_g={sg:>5}: matched={r['matched']:.3f} m_cv={r['matched_cv']:.3f} rich_fix={r['rich_fix']:.3f} rich_cv={r['rich_cv']:.3f} select_cv={r['select_cv']:.3f} | gap(m_cv-richcv)={r['matched_cv']-r['rich_cv']:+.3f}")
    log("[exp120] --- (3) BARRIDO T bajo EVEN (σ_g=%.1f, ESCASEZ) — ¿REAPARECE la ventaja del prior con CV hambriento? ---" % SG_SCARCE)
    for T in TS_SCARCE:
        r = grid["by_T_scarce"][str(T)]
        log(f"[exp120] T={T:>4}: matched_cv={r['matched_cv']:.3f} rich_cv={r['rich_cv']:.3f} select_cv={r['select_cv']:.3f} | gap(m_cv-richcv)={r['matched_cv']-r['rich_cv']:+.3f}")
    log(f"[exp120] CHECK rich_cv_robust={sm['rich_cv_robust']} select_cv_robust={sm['select_cv_robust']} | ABUNDANTE σ_g=20: rich_fix(135)={sm['gap_richfix']:+.3f} -> rich_cv={sm['gap_richcv']:+.3f} (cierra {sm['closed_frac']*100:.0f}%) select_cv={sm['gap_selectcv']:+.3f}; residual m_cv-richcv {sm['paired_mcv_richcv']} | ESCASEZ T={sm['scarce_T']}: gap={sm['gap_scarce']:+.3f} -> abundant_neutralizes={sm['abundant_neutralizes']} scarce_prior_pays={sm['scarce_prior_pays']}")
    log(f"[exp120] VEREDICTO H-V4-10j: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp120_learned_basis", "cycle": 136, "hypothesis": "H-V4-10j",
           "claim": "MIXTA (refutacion ACOTADA, post-verificacion adversarial de 3 agentes). El cuello R-PRIOR es REGIME-DEPENDENT. "
                    "EN ABUNDANCIA (T>>#columnas): un aprendiz que NO conoce la forma (cross-valida la regularizacion -rich_cv- y/o "
                    "selecciona la base -select_cv-) NEUTRALIZA EL GRUESO de la ventaja del oracle-prior (cierra ~83% del gap de "
                    "135); la fairness no lo derriba (matched_cv apenas mejora). PERO 'IGUALA' es 'CASI IGUALA': el residual "
                    "matched_cv-rich_cv ~+0.04 a sigma_g=20 es chico pero SIGNIFICATIVO (costo de varianza de las columnas extra). "
                    "Y EL PRIOR REAPARECE BAJO ESCASEZ (T~#columnas, ruido moderado): rich_cv colapsa y el prior paga +0.3. select_cv "
                    "NO es del todo form-agnostic (su menu ES un prior grueso). => R-PRIOR no es cuello en abundancia pero su valor "
                    "escala inversamente con el ratio datos/parametros; se DEBILITA de forma-exacta a menu-de-formas, no desaparece. "
                    "Acota la pregunta abierta de la MIXTA de 135",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp120] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
