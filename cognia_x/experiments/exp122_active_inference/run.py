r"""
exp122 — CYCLE 138 / H-V4-10l (rama control/acción, PUENTE FORMAL a ACTIVE INFERENCE; versión HONESTA tras VERIFICACIÓN
ADVERSARIAL de 3 agentes): ¿EMERGE el keystone (valor = controlabilidad × relevancia, 79-137) de minimizar la ENERGÍA LIBRE
ESPERADA (EFE)? La directiva predijo que "el producto ctrl×rel caería de minimizar la energía libre esperada".

VEREDICTO: MIXTA (puente TEÓRICO válido + 'emergencia empírica' TAUTOLÓGICA/artefacto). DISTINTO de CYCLE 131 (active inference
como COLECTOR DE DATOS / probing, MIXTA): aquí es la DERIVACIÓN NORMATIVA.

QUÉ SOBREVIVE (puente teórico). DERIVACIÓN en forma cerrada: en un modelo generativo lineal-gaussiano (x~N(0,diag(v)), meta G=w·x)
con PREFERENCIA gaussiana (costo pragmático = -ln C(G) = E[G²]/2σc² = CUADRÁTICO), controlar el modo i (precisión b², costo ρ)
reduce E[G²] en w²·v·b²/(b²+ρ). El término PRAGMÁTICO de la EFE = w²·v·ctrl. El keystone del lab (w·ctrl, 129) es su LÍMITE
binary+uniforme (w∈{0,1} ⇒ w²=w; v=1). => active inference SUBSUME el keystone como caso especial -> GROUNDING NORMATIVO del
producto (la directiva acertó DERIVACIONALMENTE). El valor producto-estructurado es además LEARNABLE de un stream (leakage-free).

QUÉ NO SOBREVIVE (retractado/acotado por la verificación adversarial -- el experimento lo AUTO-DOCUMENTA):
  (1) La 'emergencia EMPÍRICA' es TAUTOLÓGICA: el scorer efe_pragmatic (w²·v·ctrl) es BYTE-IDÉNTICO a la métrica del eval
      (_true_reduction); efe=oracle=1.000 por construcción en TODO régimen/seed. 'efe bate factores' / 'efe>keystone' es álgebra.
  (2) 'Emerge bajo binary' es la identidad trivial w²=w (no un hallazgo).
  (3) El '+0.43 refinamiento' es ARTEFACTO de un canónico hand-tuned: en configs graded ALEATORIAS la mediana del gap efe-keystone
      es ~0 (el canónico es percentil-100).
  (4) El MECANISMO 'w² refina' es FALSO: la VARIANZA-PRIOR v hace ~85-100% de la corrección; el CUADRADO añade ~1.5% y es
      NEUTRO-A-DAÑINO bajo params ESTIMADOS (w·v·ctrl GANA a w²·v·ctrl en todo T finito: el cuadrado amplifica el ruido de ŵ). La
      corrección ROBUSTA y LEARNABLE sobre el keystone es incluir la varianza-prior v (w·v·ctrl), NO elevar w al cuadrado.
  (5) La unificación exploración/empowerment depende de un epistémico NO-canónico; con info-gain PURO (σ²) la exploración apenas
      paga -> CONJETURA, no establecido.
  (6) Alcance: lineal-gaussiano, modos INDEPENDIENTES (no cubre los sustratos no-lineales 135-136 ni acoplados 137).

DISEÑO. Scorers sobre la REDUCCIÓN REAL de E[G²] (params VERDADEROS en el eval; arms PAREADOS): efe_pragmatic (w²·v·ctrl, = oracle
por construcción), v_correction (w·v·ctrl, la corrección ROBUSTA), keystone_lab (w·ctrl, 129), relevancia (w²·v), control (ctrl),
prediccion (v). BARRIDOS: (1) RÉGIMEN binary_uniform vs graded_nonuniform; (2) DISTRIBUCIÓN del gap sobre N configs graded
ALEATORIAS (mediana ~0 -> refinamiento nulo típico); (3) T params ESTIMADOS: efe vs v_correction vs keystone (v_correction >= efe;
el cuadrado daña); (4) β-exploración con epistémico CANÓNICO (σ²) -> conjetura.

PREGUNTA FALSABLE:
  - APOYADA si el término pragmático bate a las factores de forma NO-tautológica Y el refinamiento (efe>keystone) es robusto a
    configs aleatorias Y la corrección sobrevive a la estimación. (FALLA: es tautológico + artefacto + el cuadrado daña.)
  - MIXTA (el resultado): el puente TEÓRICO es válido (keystone = límite binary+uniforme de la EFE pragmática) pero la 'emergencia
    empírica' es tautológica/artefacto y la corrección robusta es la varianza-prior v, no el cuadrado.
  - REFUTADA si ni el puente teórico se sostiene (el término pragmático no tiene estructura de producto).

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp122_active_inference.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp122_active_inference.run            # FULL
"""
import argparse
import json
import os
import platform
import sys

import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")
RHO = 0.5
D = 8
K = 2
TS = [10, 25, 75, 300, 1500]
T_FIXED = 300
BETAS = [0.0, 0.5, 1.0, 2.0, 5.0]
REGIMES = ["binary_uniform", "graded_nonuniform"]
SCORERS = ("efe_pragmatic", "v_correction", "keystone_lab", "relevancia", "control", "prediccion")
N_RANDCFG = 200            # configs graded ALEATORIAS para la distribución del gap

B_CAN = np.array([1.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0])
WBIN = np.array([1.0, 1.0, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0])
WGRAD = np.array([0.9, 0.7, 0.8, 0.0, 1.1, 1.1, 0.0, 0.0])
VGRAD = np.array([0.5, 2.0, 0.6, 1.0, 2.0, 2.0, 1.0, 1.0])


def _ctrl(b):
    return b ** 2 / (b ** 2 + RHO)


def _true_reduction(b, w, v):
    """Reducción REAL de E[G²] al controlar el modo i = w²·v·b²/(b²+ρ). (efe_pragmatic ES esta cantidad -> efe=oracle por construcción.)"""
    return w ** 2 * v * _ctrl(b)


def _params(rng, regime):
    perm = rng.permutation(D)
    b = B_CAN[perm].copy()
    if regime == "binary_uniform":
        w = WBIN[perm].copy(); v = np.ones(D)
    elif regime == "graded_nonuniform":
        w = WGRAD[perm].copy(); v = VGRAD[perm].copy()
    else:
        raise ValueError(regime)
    return b, w, v


def _scores(b, w, v):
    c = _ctrl(b)
    return {
        "efe_pragmatic": w ** 2 * v * c,        # término pragmático de la EFE = la reducción de error (= oracle por construcción)
        "v_correction": w * v * c,              # corrección ROBUSTA: keystone + varianza-prior v (SIN el cuadrado)
        "keystone_lab": w * c,                  # el keystone del lab (129): lineal en w, sin v
        "relevancia": w ** 2 * v,               # sólo relevancia (sin control)
        "control": c,                           # sólo control (sin relevancia)
        "prediccion": v,                        # sólo varianza-prior (predicción pasiva)
    }


def _select_benefit(score, b, w, v):
    tv = _true_reduction(b, w, v)
    oracle = float(np.sum(np.sort(tv)[-K:])) + 1e-12
    S = np.argsort(score)[-K:]
    return float(np.sum(tv[S])) / oracle


def run_cell_known(regime, n_seeds):
    accs = {s: [] for s in SCORERS}
    rank_match_keystone = []
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed * 6353 + {"binary_uniform": 1, "graded_nonuniform": 2}[regime] * 50021 + 17)
        b, w, v = _params(rng, regime)
        sc = _scores(b, w, v)
        for s in SCORERS:
            accs[s].append(_select_benefit(sc[s], b, w, v))
        Se = set(np.argsort(sc["efe_pragmatic"])[-K:].tolist())
        Sk = set(np.argsort(sc["keystone_lab"])[-K:].tolist())
        rank_match_keystone.append(1.0 if Se == Sk else 0.0)
    out = {s: round(float(np.mean(accs[s])), 4) for s in SCORERS}
    out["efe_eq_keystone"] = round(float(np.mean(rank_match_keystone)), 4)
    return out


def random_config_gaps(n_cfg, seed0=900):
    """Sobre N configs graded ALEATORIAS (misma estructura de cuadrantes, w/v aleatorios): distribución de los gaps de DECISIÓN
    keystone vs v_correction vs efe -> ¿es el refinamiento robusto o un artefacto del canónico?"""
    rng = np.random.default_rng(seed0)
    gaps_efe_key = []; gaps_vcorr_key = []; gaps_efe_vcorr = []
    for _ in range(n_cfg):
        perm = rng.permutation(D)
        b = B_CAN[perm].copy()
        w = np.zeros(D); v = np.ones(D)
        # 0,1,2 = ctrl+rel con w,v aleatorios; 4,5 = rel-incontrolable con w,v aleatorios; resto 0/1
        relmask = (WGRAD[perm] > 0)
        w[relmask] = rng.uniform(0.3, 1.2, int(relmask.sum()))
        v[relmask] = rng.uniform(0.3, 2.5, int(relmask.sum()))
        sc = _scores(b, w, v)
        be = _select_benefit(sc["efe_pragmatic"], b, w, v)
        bv = _select_benefit(sc["v_correction"], b, w, v)
        bk = _select_benefit(sc["keystone_lab"], b, w, v)
        gaps_efe_key.append(be - bk); gaps_vcorr_key.append(bv - bk); gaps_efe_vcorr.append(be - bv)
    def stats(a):
        a = np.array(a)
        return {"mean": round(float(a.mean()), 4), "median": round(float(np.median(a)), 4),
                "frac_gt_05": round(float((a > 0.05).mean()), 4)}
    return {"efe_minus_keystone": stats(gaps_efe_key), "vcorr_minus_keystone": stats(gaps_vcorr_key),
            "efe_minus_vcorr": stats(gaps_efe_vcorr)}


def _estimate_params(rng, b, w, v, T):
    x = np.zeros(D)
    X = np.zeros((T, D)); Xn = np.zeros((T, D)); U = np.zeros((T, D)); G = np.zeros(T)
    a = 0.6
    for t in range(T):
        u = rng.normal(0, 1.0, D)
        xn = a * x + b * u + rng.normal(0, 1.0, D) * np.sqrt(v)
        g = float(np.dot(w, x)) + rng.normal(0, 0.5)
        X[t] = x; Xn[t] = xn; U[t] = u; G[t] = g
        x = xn
    b_hat = np.zeros(D)
    for i in range(D):
        F = np.stack([X[:, i], U[:, i]], axis=1)
        coef, *_ = np.linalg.lstsq(F, Xn[:, i], rcond=None)
        b_hat[i] = coef[1]
    w_hat, *_ = np.linalg.lstsq(X, G, rcond=None)
    v_hat = np.var(X, axis=0)
    return np.abs(b_hat), w_hat, np.maximum(v_hat, 1e-6)


def run_cell_estimated(regime, T, n_seeds):
    """Con params ESTIMADOS (el único régimen NO-tautológico): compara las FORMAS efe (w²·v·c), v_correction (w·v·c), keystone (w·c)."""
    accs = {"efe": [], "vcorr": [], "keystone": []}
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed * 7717 + int(T) * 13 + {"binary_uniform": 1, "graded_nonuniform": 2}[regime] * 50021 + 31)
        b, w, v = _params(rng, regime)
        b_h, w_h, v_h = _estimate_params(rng, b, w, v, T)
        c_h = _ctrl(b_h)
        accs["efe"].append(_select_benefit(w_h ** 2 * v_h * c_h, b, w, v))
        accs["vcorr"].append(_select_benefit(w_h * v_h * c_h, b, w, v))
        accs["keystone"].append(_select_benefit(w_h * c_h, b, w, v))
    return {k: round(float(np.mean(val)), 4) for k, val in accs.items()}


def _two_phase(rng, b, w, v, sigma, beta, T_explore):
    """Explorar-luego-explotar con epistémico CANÓNICO (info-gain PURO ∝ σ², independiente de la preferencia)."""
    w_belief = w + rng.normal(0, 1.0, D) * sigma
    c = _ctrl(b)
    pragmatic = w_belief ** 2 * v * c
    epistemic = sigma ** 2                                  # info-gain PURO (saliencia EFE canónica, NO pesada por valor)
    efe_full = pragmatic + beta * epistemic
    explore = np.argsort(efe_full)[-K:]
    w_known = w_belief.copy()
    obs_noise = 1.0 / np.sqrt(T_explore)
    w_known[explore] = w[explore] + rng.normal(0, obs_noise, K)
    pragmatic2 = w_known ** 2 * v * c
    exploit = np.argsort(pragmatic2)[-K:]
    tv = _true_reduction(b, w, v)
    oracle = float(np.sum(np.sort(tv)[-K:])) + 1e-12
    return float(np.sum(tv[exploit])) / oracle


def run_cell_beta(beta, concentrated, n_seeds, T_explore=50):
    accs = []
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed * 8941 + int(beta * 100) * 131 + (7 if concentrated else 3) * 9973 + 41)
        b, w, v = _params(rng, "graded_nonuniform")
        sigma = np.ones(D) * 0.3
        if concentrated:
            sigma[w > 0.3] = 1.2
        accs.append(_two_phase(rng, b, w, v, sigma, beta, T_explore))
    return round(float(np.mean(accs)), 4)


def run(n_seeds):
    known = {r: run_cell_known(r, n_seeds) for r in REGIMES}
    randcfg = random_config_gaps(N_RANDCFG)
    by_T = {r: {str(T): run_cell_estimated(r, T, n_seeds) for T in TS} for r in REGIMES}
    by_beta = {"uniform": {str(bt): run_cell_beta(bt, False, n_seeds) for bt in BETAS},
               "concentrated": {str(bt): run_cell_beta(bt, True, n_seeds) for bt in BETAS}}
    return {"known": known, "randcfg": randcfg, "by_T": by_T, "by_beta": by_beta}


def _f(x):
    return "{:.3f}".format(x)


def build_summary(grid):
    kn = grid["known"]; rc = grid["randcfg"]; bt = grid["by_beta"]
    bu = kn["binary_uniform"]; gn = kn["graded_nonuniform"]
    gnT = grid["by_T"]["graded_nonuniform"]

    # (PUENTE TEÓRICO, sobrevive) keystone = límite binary+uniforme de la EFE pragmática (identidad algebraica w²=w, v=1)
    bridge_binary = abs(bu["efe_pragmatic"] - bu["keystone_lab"]) < 0.02 and bu["efe_pragmatic"] > 0.95
    # estructura de PRODUCTO: el término pragmático (=oracle) bate a las factores simples (esto SÍ es no-trivial: las factores fallan)
    factors_fail = all(gn["efe_pragmatic"] - gn[f] > 0.10 for f in ("relevancia", "control", "prediccion"))

    # (TAUTOLOGÍA, retractado) efe_pragmatic ES la métrica -> efe=oracle por construcción; el '+gap' es álgebra, no empírico
    efe_is_oracle = gn["efe_pragmatic"] > 0.999 and bu["efe_pragmatic"] > 0.999
    # (ARTEFACTO, retractado) en configs ALEATORIAS el refinamiento efe-keystone es ~nulo (mediana ~0)
    refine_median = rc["efe_minus_keystone"]["median"]
    refine_is_artifact = refine_median < 0.02
    # (MECANISMO CORRECTO) la varianza-prior v hace el grueso; el cuadrado añade poco; v_correction recupera casi todo el gap
    vcorr_median = rc["vcorr_minus_keystone"]["median"]
    square_median = rc["efe_minus_vcorr"]["median"]
    v_does_the_work = vcorr_median > square_median             # la corrección por v supera a la del cuadrado (típico)
    # bajo params ESTIMADOS el cuadrado es NEUTRO-A-DAÑINO: v_correction >= efe en T finito
    est_mid = gnT[str(TS[2])]                                  # T=75
    square_harmful_estimated = est_mid["vcorr"] >= est_mid["efe"] - 0.005
    # DISCOVERY leakage-free converge desde abajo (la pata empírica limpia)
    converges_below = gnT[str(TS[0])]["vcorr"] < 0.9 and gnT[str(TS[-1])]["vcorr"] > 0.9

    # (CONJETURA, acotado) con epistémico CANÓNICO (σ² puro) la exploración apenas paga
    unif = bt["uniform"]; conc = bt["concentrated"]
    gain_uniform = round(max(unif[str(b)] for b in BETAS) - unif[str(BETAS[0])], 4)
    gain_concentrated = round(max(conc[str(b)] for b in BETAS) - conc[str(BETAS[0])], 4)
    explore_pays_canonical = gain_uniform > 0.04 and gain_concentrated > 0.04

    bridge_holds = bridge_binary and factors_fail and converges_below

    if bridge_holds and (efe_is_oracle and refine_is_artifact):
        status = "mixta"
        verdict = (
            "H-V4-10l MIXTA (puente TEÓRICO válido + 'emergencia empírica' TAUTOLÓGICA/artefacto; post-verificación adversarial de "
            "3 agentes, 8vo ciclo): la directiva acertó DERIVACIONALMENTE pero NO empíricamente. SOBREVIVE (puente teórico): en un "
            "modelo lineal-gaussiano con preferencia gaussiana (costo = E[G²], CUADRÁTICO), el término PRAGMÁTICO de la EFE = "
            "w²·v·ctrl; el keystone del lab (w·ctrl, 129) es su LÍMITE binary+uniforme (efe {bue}=keystone {buk}, w²=w, v=1) -> "
            "active inference SUBSUME el keystone como caso especial (GROUNDING NORMATIVO del producto). El producto-estructurado es "
            "LEARNABLE de un stream (converge desde abajo: T={t0} {d0} -> T={tN} {dN}, leakage-free). Las FACTORES simples FALLAN "
            "(graded relev {grel}/ctrl {gctl}/pred {gpred}) -> la composición es necesaria. NO SOBREVIVE (retractado por la "
            "verificación): (1) la 'emergencia EMPÍRICA' es TAUTOLÓGICA -- efe_pragmatic (w²·v·ctrl) es BYTE-IDÉNTICO a la métrica "
            "del eval, así que efe=oracle ({gue}) por construcción y 'efe>keystone' es álgebra, no un hallazgo. (2) 'emerge bajo "
            "binary' es la identidad trivial w²=w. (3) el refinamiento efe-keystone es un ARTEFACTO del canónico hand-tuned: en "
            "{nc} configs graded ALEATORIAS la MEDIANA del gap es {rm} (~nulo; el canónico era percentil-100). (4) el MECANISMO "
            "'w² refina' es FALSO: la VARIANZA-PRIOR v hace el grueso (v_correction-keystone mediana {vm} >> cuadrado {sm}), y bajo "
            "params ESTIMADOS el cuadrado es NEUTRO-A-DAÑINO (T=75 v_correction {ev} >= efe {ee}: el cuadrado amplifica el ruido de "
            "ŵ) -> la corrección ROBUSTA y LEARNABLE sobre el keystone es incluir la varianza-prior v (w·v·ctrl), NO elevar w al "
            "cuadrado. (5) la unificación exploración/empowerment es CONJETURA: con epistémico CANÓNICO (info-gain σ² puro) la "
            "exploración apenas paga (gan_unif +{gu}, gan_conc +{gc}). (6) ALCANCE: lineal-gaussiano, modos INDEPENDIENTES (no "
            "cubre los sustratos no-lineales 135-136 ni acoplados 137). => RESULTADO HONESTO: el keystone ctrl×rel es el LÍMITE "
            "binary+uniforme de la EFE pragmática (puente normativo real, confirma la directiva en lo TEÓRICO); la corrección "
            "empírica robusta es la varianza-prior v, no el cuadrado; la exploración como término EFE queda como conjetura."
        ).format(bue=_f(bu["efe_pragmatic"]), buk=_f(bu["keystone_lab"]), t0=TS[0], d0=_f(gnT[str(TS[0])]["vcorr"]),
                 tN=TS[-1], dN=_f(gnT[str(TS[-1])]["vcorr"]), grel=_f(gn["relevancia"]), gctl=_f(gn["control"]),
                 gpred=_f(gn["prediccion"]), gue=_f(gn["efe_pragmatic"]), nc=N_RANDCFG, rm=_f(refine_median),
                 vm=_f(vcorr_median), sm=_f(square_median), ev=_f(est_mid["vcorr"]), ee=_f(est_mid["efe"]),
                 gu=_f(gain_uniform), gc=_f(gain_concentrated))
    elif bridge_holds and not efe_is_oracle:
        status = "apoyada"
        verdict = ("H-V4-10l APOYADA: el término pragmático bate a las factores de forma NO-tautológica y el refinamiento es "
                   "robusto (mediana {rm}).").format(rm=_f(refine_median))
    elif not bridge_holds:
        status = "refutada"
        verdict = ("H-V4-10l REFUTADA: ni el puente teórico se sostiene -- bridge_binary={bb} factors_fail={ff} converges_below="
                   "{cb}.").format(bb=bridge_binary, ff=factors_fail, cb=converges_below)
    else:
        status = "mixta"
        verdict = ("H-V4-10l MIXTA: parcial -- bridge={br} efe_is_oracle={eo} refine_artifact={ra} v_does_work={vw}.").format(
            br=bridge_holds, eo=efe_is_oracle, ra=refine_is_artifact, vw=v_does_the_work)

    return {"known": kn, "randcfg": rc, "by_T": grid["by_T"], "by_beta": bt,
            "bu_efe": bu["efe_pragmatic"], "bu_keystone": bu["keystone_lab"], "bu_efe_eq_keystone": bu["efe_eq_keystone"],
            "gn_efe": gn["efe_pragmatic"], "gn_keystone": gn["keystone_lab"], "gn_vcorr": gn["v_correction"],
            "gn_relevancia": gn["relevancia"], "gn_control": gn["control"], "gn_prediccion": gn["prediccion"],
            "refine_median": refine_median, "vcorr_median": vcorr_median, "square_median": square_median,
            "est_mid_efe": est_mid["efe"], "est_mid_vcorr": est_mid["vcorr"], "est_mid_keystone": est_mid["keystone"],
            "discovery_vcorr_T0": gnT[str(TS[0])]["vcorr"], "discovery_vcorr_TN": gnT[str(TS[-1])]["vcorr"],
            "gain_uniform": gain_uniform, "gain_concentrated": gain_concentrated,
            "bridge_binary": bool(bridge_binary), "factors_fail": bool(factors_fail), "efe_is_oracle": bool(efe_is_oracle),
            "refine_is_artifact": bool(refine_is_artifact), "v_does_the_work": bool(v_does_the_work),
            "square_harmful_estimated": bool(square_harmful_estimated), "converges_below": bool(converges_below),
            "explore_pays_canonical": bool(explore_pays_canonical), "bridge_holds": bool(bridge_holds),
            "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=int, default=400)
    args = ap.parse_args()
    if args.smoke:
        args.seeds = 80

    logs = []

    def log(mm):
        print(mm, flush=True); logs.append(mm)

    log("[exp122] CYCLE 138 / H-V4-10l (HONESTO post-verificación) — ¿EMERGE el keystone de minimizar la EFE? Puente TEÓRICO válido vs 'emergencia empírica' tautológica")
    log(f"[exp122] seeds={args.seeds} D={D} K={K} rho={RHO} Ts={TS} betas={BETAS} regimes={REGIMES} n_randcfg={N_RANDCFG}")

    grid = run(args.seeds)
    sm = build_summary(grid)

    log("[exp122] --- (1) PARAMS CONOCIDOS: efe(=oracle por construcción) / v_correction(w·v·c) / keystone(w·c) / factores ---")
    for r in REGIMES:
        c = grid["known"][r]
        log(f"[exp122] {r:>16}: efe={c['efe_pragmatic']:.3f}(=oracle) v_corr={c['v_correction']:.3f} keystone={c['keystone_lab']:.3f} | relev={c['relevancia']:.3f} ctrl={c['control']:.3f} pred={c['prediccion']:.3f}")
    rc = grid["randcfg"]
    log("[exp122] --- (2) DISTRIBUCIÓN del gap sobre %d configs graded ALEATORIAS (¿refinamiento robusto o artefacto?) ---" % N_RANDCFG)
    log(f"[exp122] efe-keystone: mediana={rc['efe_minus_keystone']['median']:.3f} media={rc['efe_minus_keystone']['mean']:.3f} frac>0.05={rc['efe_minus_keystone']['frac_gt_05']:.2f} (canónico era +0.43)")
    log(f"[exp122] vcorr-keystone: mediana={rc['vcorr_minus_keystone']['median']:.3f} | efe-vcorr (lo que añade el CUADRADO): mediana={rc['efe_minus_vcorr']['median']:.3f}")
    log("[exp122] --- (3) PARAMS ESTIMADOS (no-tautológico): efe(w²vc) vs v_correction(wvc) vs keystone(wc) -- ¿daña el cuadrado? ---")
    for T in TS:
        r = grid["by_T"]["graded_nonuniform"][str(T)]
        log(f"[exp122] T={T:>5}: efe={r['efe']:.3f} v_corr={r['vcorr']:.3f} keystone={r['keystone']:.3f} | efe-vcorr={r['efe']-r['vcorr']:+.3f}")
    log("[exp122] --- (4) β-EXPLORACIÓN con epistémico CANÓNICO (σ² puro) — ¿paga explorar? ---")
    for cond in ("uniform", "concentrated"):
        row = " ".join(f"β={b}:{grid['by_beta'][cond][str(b)]:.3f}" for b in BETAS)
        log(f"[exp122] σ-{cond:>12}: {row}")
    log(f"[exp122] CHECK bridge_binary={sm['bridge_binary']} factors_fail={sm['factors_fail']} converges_below={sm['converges_below']} | efe_is_oracle(TAUTOL)={sm['efe_is_oracle']} refine_is_artifact={sm['refine_is_artifact']} (mediana {sm['refine_median']:.3f}) v_does_the_work={sm['v_does_the_work']} square_harmful_estimated={sm['square_harmful_estimated']} | explore_pays_canonical={sm['explore_pays_canonical']} (gan_unif +{sm['gain_uniform']:.3f} gan_conc +{sm['gain_concentrated']:.3f})")
    log(f"[exp122] VEREDICTO H-V4-10l: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp122_active_inference", "cycle": 138, "hypothesis": "H-V4-10l",
           "claim": "MIXTA (post-verificacion adversarial de 3 agentes). PUENTE TEORICO VALIDO: en un modelo lineal-gaussiano con "
                    "preferencia gaussiana, el termino PRAGMATICO de la EFE = w^2*v*ctrl; el keystone del lab (w*ctrl, 129) es su "
                    "LIMITE binary+uniforme -> active inference SUBSUME el keystone como caso especial (grounding normativo del "
                    "producto; la directiva acerto DERIVACIONALMENTE). El producto-estructurado es LEARNABLE leakage-free. PERO la "
                    "'emergencia EMPIRICA' es TAUTOLOGICA (efe_pragmatic ES byte-identico a la metrica del eval -> efe=oracle por "
                    "construccion); 'emerge bajo binary' es la identidad trivial w^2=w; el '+0.43 refinamiento' es artefacto de un "
                    "canonico hand-tuned (mediana ~0 en configs aleatorias); el MECANISMO 'w^2 refina' es FALSO -- la varianza-prior "
                    "v hace el grueso y el cuadrado es neutro-a-daino bajo estimacion (w*v*ctrl > w^2*v*ctrl en todo T finito), asi "
                    "que la correccion ROBUSTA es incluir v, NO el cuadrado; la unificacion exploracion/empowerment es conjetura "
                    "(con epistemico canonico sigma^2 apenas paga). Alcance: lineal-gaussiano, modos independientes",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp122] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
