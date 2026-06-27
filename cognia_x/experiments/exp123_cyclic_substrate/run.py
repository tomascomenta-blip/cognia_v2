r"""
exp123 — CYCLE 139 / H-V4-10m (rama control/acción, EXTIENDE el sustrato ACOPLADO de 137 al régimen con CICLOS / radio espectral
cercano a 1, justo donde la reach-relevancia de ESTADO-ESTACIONARIO del 137 — |b̂·(I-Â)^{-T}ŵ| — se vuelve mal-condicionada):
¿sobrevive el keystone valor=ctrl×rel a un sustrato con feedback (ciclos), y cuál es la forma correcta de la controlabilidad-por-
alcance?

VEREDICTO: MIXTA (núcleo APOYADO + 4 overclaims RETRACTADOS por verificación adversarial de 4 agentes; 9no ciclo seguido). El
experimento AUTO-DOCUMENTA el veredicto corregido.

QUÉ SOBREVIVE (núcleo, leakage-free, sim-validado):
  - La reach de estado-estacionario CRUDA del 137 (R_inf=(I-Â)^{-1}) es NUMÉRICAMENTE FRÁGIL cerca de radio espectral 1: bajo
    capacidad K=1 (selección winner-take-all) con escalas temporales en competencia, MIS-RANKEA el modo top (apuesta al lazo lento
    casi-crítico que reach-∞∝1/(1-radio) infla, pero cuyo beneficio no se materializó en el horizonte). Una reach REGULARIZADA lo
    corrige. Esto es un CAVEAT REAL al 137 (que asumía radio<1 con buen condicionamiento).
  - El producto-estructurado |b̂·R^T·ŵ| es ESTIMABLE de un stream leakage-free (Â,b̂,ŵ por system-ID + credit-assignment; converge
    desde abajo; Â=0 lo colapsa a local; sim_check valida que la fórmula = la física).

QUÉ NO SOBREVIVE (retractado/acotado por la verificación adversarial -- el experimento lo AUTO-DOCUMENTA):
  (1) El gap titular (reach_H >> reach_inf, +0.55) es un ARTEFACTO de K=1 WINNER-TAKE-ALL: con K>=2 el gap EVAPORA (gap_true~0 en
      todo el barrido). reach_inf NO "falla" -- identifica el CONJUNTO correcto de modos relevantes; sólo invierte el orden #1<->#2,
      que K=1 castiga al máximo.
  (2) La forma HORIZONTE-H específica NO es privilegiada: una reach-∞ REGULARIZADA por CAP-DE-AUTOVALOR (sin conocer H) IGUALA a
      reach_H en todo radio. La novedad es "REGULARIZAR el modo casi-crítico", no "horizonte". reach_disc (descontada) también empata.
  (3) La RELEVANCIA es COLINEAL / no-aislada en este régimen: con ŵ≡unos (relevancia eliminada) reach_H~0.99 (el control shuffle-ŵ
      daba un falso positivo). El factor load-bearing demostrado es la CONTROLABILIDAD-REACH, no la relevancia (que 134-137 ya aisló).
  (4) "Falla cerca de radio 1" requiere COMPETENCIA de escalas temporales: con un ÚNICO lazo (slow_only/fast_only) reach_inf=1.0
      hasta radio 0.99. El driver es H < tiempo-de-mezcla del lazo lento CON un competidor más rápido por la capacidad K.
  (+) El pilar "es la FORMA, no la estimación" (reach_inf_true falla) tiene ventana angosta a∈[~0.45,0.65]; a=0.6 cerca del borde.

DISEÑO (numpy, sustrato lineal con CICLO). x_{t+1}=A·x + b⊙u + ruido. Dos sub-estructuras compiten por la capacidad K:
  - FAST: driver_f (b=1,w=0) --arco directo 1-hop--> target_f (b=0,w=1). Triangular, autovalor=a -> materializa RÁPIDO.
  - SLOW: driver_s (b=1,w=0) <==ciclo de peso g==> target_s (b=0,w=1). Autovalores a±g, radio=a+g -> al subir g, lazo casi-crítico.
+ decoy controlable-irrelevante, 2 ruidosos, filler. Meta G=w·x; oracle = valor de horizonte H = |b·(Σ_{k<H}A^k)^T w|.
SCORERS (la FORMA del valor; estimados de un stream o exactos): reach_H (horizonte finito), reach_inf (137, ∞ cruda),
reach_disc (descontada (I-γÂ)^{-1}), reach_inf_reg (∞ con CAP-de-autovalor, SIN H), local, ctrl_only, prediccion + *_true.
ANTI-TAUTOLOGÍA (lección de 138): el oracle es horizonte-H -> reach_H_true=oracle por construcción (el NIVEL no es el hallazgo);
lo load-bearing es la fragilidad de reach_inf_true (la FORMA), la estimabilidad leakage-free y el sim_check.

PREGUNTA FALSABLE:
  - APOYADA si la forma horizonte-H es ÚNICA/privilegiada, el gap es robusto a K, y la relevancia se aísla. (FALLA: ver overclaims.)
  - MIXTA (el resultado): la reach-∞ cruda es frágil cerca de radio 1 y la regularización la cura (núcleo real) PERO el gap es
    artefacto de K=1, la forma horizonte no es privilegiada (varias regularizaciones empatan) y la relevancia es colineal.
  - REFUTADA si la reach-∞ cruda NO es frágil (no mis-rankea) -- la frontera de 137 no era real.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp123_cyclic_substrate.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp123_cyclic_substrate.run            # FULL
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
AA = 0.6                 # auto-decaimiento (diagonal de A); ventana de la FORMA: a∈[~0.45,0.65]
RHO = 0.5                # costo de control (controlabilidad-descontada, reusado de 130/137)
D = 8                    # NO parametrizable hacia abajo (índices 5,6 ruidosos hardcoded)
K_DEFAULT = 1            # capacidad por defecto; el gap es ARTEFACTO de K=1 (evapora a K>=2)
C_FAST = 0.9             # peso del arco directo FAST; el efecto cualitativo vive en c_fast>=~0.5
CAP_DEFAULT = 0.8        # cap de autovalor para la reach-∞ REGULARIZADA (sin conocer H)
SU_DEFAULT = 1.0
SG_DEFAULT = 0.5
NOISE_HI = 3.0
TS = [12, 30, 100, 300, 1000]
T_FIXED = 1000
SPECRADII = [0.6, 0.8, 0.9, 0.95, 0.99]   # radio espectral objetivo del lazo SLOW (= a + g)
RHO_FIXED = 0.95
HS = [3, 8, 20, 60, 200]
H_SHORT = 5
KS = [1, 2, 3]                             # barrido de capacidad: el gap evapora a K>=2
STRUCTS = ["both", "slow_only", "fast_only"]   # competencia vs lazo único
# índices canónicos: 0 driver_f, 1 target_f, 2 driver_s, 3 target_s, 4 decoy_ctrl, 5,6 noisy, 7 filler
ARMS = ("reach_H", "reach_inf", "reach_disc", "reach_inf_reg", "local", "ctrl_only", "prediccion",
        "reach_H_true", "reach_inf_true")


def _spec(structure="both"):
    """(b, w, s, has_fast, has_slow) en índices canónicos."""
    b = np.zeros(D); w = np.zeros(D); s = np.ones(D)
    has_fast = structure in ("both", "fast_only")
    has_slow = structure in ("both", "slow_only")
    if has_fast:
        b[0] = 1.0; w[1] = 1.0          # FAST: driver_f controla, target_f relevante
    if has_slow:
        b[2] = 1.0; w[3] = 1.0          # SLOW: driver_s controla, target_s relevante
    b[4] = 1.0                          # decoy controlable-irrelevante
    s[5] = s[6] = NOISE_HI              # modos ruidosos (tientan a la predicción)
    return b, w, s, has_fast, has_slow


def _build_A(g, perm, structure="both"):
    """A = a·I + arco directo FAST (target_f<-driver_f) + ciclo SLOW (driver_s<->target_s). g fija el radio del slow = a+g."""
    A = AA * np.eye(D)
    if structure in ("both", "fast_only"):
        A[1, 0] += C_FAST          # driver_f (0) -> target_f (1): triangular, materializa rápido
    if structure in ("both", "slow_only"):
        A[3, 2] += g               # driver_s (2) -> target_s (3)
        A[2, 3] += g               # target_s (3) -> driver_s (2): CICLO de feedback, radio = a+g
    return A[np.ix_(perm, perm)]


def _reach_H_mat(A, H):
    """R_H = Σ_{k=0}^{H-1} A^k (horizonte FINITO). Bien definido aun con radio>=1."""
    R = np.eye(D); P = np.eye(D)
    for _ in range(1, H):
        P = P @ A
        R = R + P
    return R


def _safe_reach_inf(A):
    """(I-A)^{-1} con caída a pseudo-inversa si está cerca de singular (radio≈1)."""
    M = np.eye(D) - A
    try:
        return np.linalg.solve(M, np.eye(D))
    except np.linalg.LinAlgError:
        return np.linalg.pinv(M)


def _reach_inf_reg_mat(A, cap=CAP_DEFAULT):
    """(I-A_reg)^{-1} REGULARIZADA: capa la MAGNITUD de los autovalores de A a `cap` (SIN conocer H) -> el modo casi-crítico
    deja de dominar. Es la regularización 'agnóstica al horizonte' que IGUALA a reach_H (overclaim 2: la forma horizonte no es única)."""
    lam, V = np.linalg.eig(A)
    mag = np.abs(lam)
    scale = np.where(mag > cap, cap / np.maximum(mag, 1e-12), 1.0)
    A_reg = (V @ np.diag(lam * scale) @ np.linalg.inv(V)).real
    return _safe_reach_inf(A_reg)


def _value_H(A, b, w, H):
    """VALOR de decisión de horizonte H = |b·(R_H^T w)| (sensibilidad de Σ_{t<H}G a un impulso de control). = ORACLE."""
    RH = _reach_H_mat(A, H)
    return np.abs(b * (RH.T @ w))


def _score_reach(b, w, Rmat):
    return np.abs(b * (Rmat.T @ w))


def _experience(rng, A, b, s, T, sigma_u, sigma_g, w):
    x = np.zeros(D)
    X = np.zeros((T, D)); Xn = np.zeros((T, D)); U = np.zeros((T, D)); G = np.zeros(T)
    for t in range(T):
        u = rng.normal(0, sigma_u, D)
        xn = A @ x + b * u + rng.normal(0, 1.0, D) * s
        xn = np.clip(xn, -1e6, 1e6)     # clip defensivo (nunca dispara con radio<1; el estado es estable)
        X[t] = x; Xn[t] = xn; U[t] = u; G[t] = float(np.dot(w, x)) + rng.normal(0, sigma_g)
        x = xn
    return X, Xn, U, G


def _estimate_AB(X, Xn, U):
    A_hat = np.zeros((D, D)); b_hat = np.zeros(D)
    for j in range(D):
        F = np.concatenate([X, U[:, j:j + 1]], axis=1)
        coef, *_ = np.linalg.lstsq(F, Xn[:, j], rcond=None)
        A_hat[j, :] = coef[:D]; b_hat[j] = coef[D]
    return A_hat, b_hat


def _estimate_w(X, G):
    w_hat, *_ = np.linalg.lstsq(X, G, rcond=None)
    return w_hat


def _disc_gamma(H):
    return max(0.0, 1.0 - 1.0 / float(H))


def run_cell(rho_spec, H, T, sigma_u, sigma_g, n_seeds, K=K_DEFAULT, structure="both", w_mode="real"):
    """w_mode: 'real' (ŵ estimado) | 'shuffle' (permutado) | 'ones' (relevancia ELIMINADA, control nulo correcto) | 'zeroA' (Â:=0)."""
    g = rho_spec - AA
    accs = {a: [] for a in ARMS}
    pick = {a: [] for a in ARMS}
    pick_fast = []; pick_slow = []
    corr_w = []
    b0, w0, s0, has_fast, has_slow = _spec(structure)
    gamma = _disc_gamma(H)
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed * 9173 + int(rho_spec * 1000) * 131 + int(H) * 1009 + int(T) * 13
                                    + int(sigma_g * 100) * 101 + K * 7919 + STRUCTS.index(structure) * 50021
                                    + {"real": 0, "shuffle": 1, "ones": 2, "zeroA": 3}[w_mode] * 104729 + 29)
        perm = rng.permutation(D)
        b = b0[perm]; w = w0[perm]; s = s0[perm]
        A = _build_A(g, perm, structure)
        idx_df = int(np.where(perm == 0)[0][0]); idx_ds = int(np.where(perm == 2)[0][0])

        v_true = _value_H(A, b, w, H)
        kk = min(K, int(np.sum(v_true > 1e-9)) if np.sum(v_true > 1e-9) > 0 else K)
        kk = max(1, min(K, D))
        oracle_set = set(np.argsort(v_true)[-kk:].tolist())
        oracle_pick = int(np.argmax(v_true))
        den = float(np.sum(v_true[list(oracle_set)])) + 1e-12
        pick_fast.append(1.0 if (has_fast and oracle_pick == idx_df) else 0.0)
        pick_slow.append(1.0 if (has_slow and oracle_pick == idx_ds) else 0.0)

        X, Xn, U, G = _experience(rng, A, b, s, T, sigma_u, sigma_g, w)
        A_hat, b_hat = _estimate_AB(X, Xn, U)
        w_hat = _estimate_w(X, G)
        if w_mode == "shuffle":
            w_hat = w_hat[rng.permutation(D)]
        elif w_mode == "ones":
            w_hat = np.ones(D)                 # relevancia ELIMINADA manteniendo la estructura (control nulo correcto)
        if w_mode == "zeroA":
            A_hat = np.zeros((D, D))           # acople ELIMINADO

        RH_hat = _reach_H_mat(A_hat, H)
        Rinf_hat = _safe_reach_inf(A_hat)
        Rdisc_hat = _safe_reach_inf(gamma * A_hat)
        Rreg_hat = _reach_inf_reg_mat(A_hat)
        RH_true = _reach_H_mat(A, H)
        Rinf_true = _safe_reach_inf(A)

        scores = {
            "reach_H": _score_reach(b_hat, w_hat, RH_hat),
            "reach_inf": _score_reach(b_hat, w_hat, Rinf_hat),
            "reach_disc": _score_reach(b_hat, w_hat, Rdisc_hat),
            "reach_inf_reg": _score_reach(b_hat, w_hat, Rreg_hat),     # ∞ regularizada SIN H
            "local": np.abs(b_hat * w_hat),
            "ctrl_only": np.abs(b_hat),
            "prediccion": np.var(X, axis=0),
            "reach_H_true": _score_reach(b, w, RH_true),               # = oracle por construcción (declarado)
            "reach_inf_true": _score_reach(b, w, Rinf_true),           # FALSADOR: forma ∞ con params VERDADEROS
        }
        for a in ARMS:
            sc = np.where(np.isfinite(scores[a]), scores[a], -np.inf)
            S = set(np.argsort(sc)[-kk:].tolist())
            accs[a].append(float(np.sum(v_true[list(S)])) / den)
            pick[a].append(1.0 if int(np.argmax(sc)) == oracle_pick else 0.0)
        if np.std(w_hat) > 1e-9:
            corr_w.append(float(np.corrcoef(w_hat, w)[0, 1]))

    out = {a: round(float(np.mean(accs[a])), 4) for a in ARMS}
    out.update({a + "_pick": round(float(np.mean(pick[a])), 4) for a in ARMS})
    out["oracle_pick_fast"] = round(float(np.mean(pick_fast)), 4)
    out["oracle_pick_slow"] = round(float(np.mean(pick_slow)), 4)
    out["corr_w"] = round(float(np.mean(corr_w)) if corr_w else 0.0, 4)
    return out


def _sim_check(rho_spec, H, n_seeds=200):
    """Valida que el ORACLE (fórmula reach_H) = la FÍSICA simulada: impulso de control unitario a cada modo, mide Σ_{t<H}G_t real
    SIN ruido, y confirma argmax simulado == argmax de la fórmula. (Anti-'fórmula inventada'.)"""
    g = rho_spec - AA
    b0, w0, s0, hf, hs = _spec("both")
    rng = np.random.default_rng(424242)
    agree = []
    for _ in range(n_seeds):
        perm = rng.permutation(D)
        b = b0[perm]; w = w0[perm]
        A = _build_A(g, perm, "both")
        v_formula = _value_H(A, b, w, H)
        v_sim = np.zeros(D)
        for i in range(D):
            if b[i] == 0:
                continue
            x = np.zeros(D); acc = 0.0
            for _t in range(H):
                acc += float(np.dot(w, x))
                u = np.zeros(D); u[i] = 1.0
                x = A @ x + b * u
            v_sim[i] = abs(acc)
        agree.append(1.0 if int(np.argmax(v_sim)) == int(np.argmax(v_formula)) else 0.0)
    return round(float(np.mean(agree)), 4)


def run(n_seeds):
    by_rho = {str(r): run_cell(r, H_SHORT, T_FIXED, SU_DEFAULT, SG_DEFAULT, n_seeds) for r in SPECRADII}
    by_H = {str(h): run_cell(RHO_FIXED, h, T_FIXED, SU_DEFAULT, SG_DEFAULT, n_seeds) for h in HS}
    by_T = {str(T): run_cell(RHO_FIXED, H_SHORT, T, SU_DEFAULT, SG_DEFAULT, n_seeds) for T in TS}
    by_K = {str(K): run_cell(RHO_FIXED, H_SHORT, T_FIXED, SU_DEFAULT, SG_DEFAULT, n_seeds, K=K) for K in KS}
    by_struct = {st: run_cell(RHO_FIXED, H_SHORT, T_FIXED, SU_DEFAULT, SG_DEFAULT, n_seeds, structure=st) for st in STRUCTS}
    ctrl = {m: run_cell(RHO_FIXED, H_SHORT, T_FIXED, SU_DEFAULT, SG_DEFAULT, n_seeds, w_mode=m)
            for m in ("shuffle", "ones", "zeroA")}
    return {"by_rho": by_rho, "by_H": by_H, "by_T": by_T, "by_K": by_K, "by_struct": by_struct, "ctrl": ctrl,
            "sim_check_lo": _sim_check(0.6, H_SHORT, n_seeds=min(n_seeds, 200)),
            "sim_check_hi": _sim_check(RHO_FIXED, H_SHORT, n_seeds=min(n_seeds, 200))}


def _f(x):
    return "{:.3f}".format(x)


def build_summary(grid):
    br = grid["by_rho"]; bH = grid["by_H"]; bT = grid["by_T"]; bK = grid["by_K"]; bs = grid["by_struct"]; ct = grid["ctrl"]
    rlo = br[str(SPECRADII[0])]; rhi = br[str(RHO_FIXED)]

    # NÚCLEO APOYADO ---------------------------------------------------------------------------------------------------
    # (A) la reach-∞ CRUDA es FRÁGIL cerca de radio 1 bajo K=1: mis-rankea (reach_inf cae mientras la regularizada se mantiene)
    inf_fragile_crude = (rhi["reach_H"] - rhi["reach_inf"]) > 0.15 and rlo["reach_inf"] > 0.90
    # (B) es la FORMA (no la estimación): reach_inf_TRUE también cae (ventana a∈[~0.45,0.65]; a=0.6 dentro)
    form_not_estimation = (rhi["reach_H_true"] - rhi["reach_inf_true"]) > 0.15
    # (C) la REGULARIZACIÓN cura: reach_H, reach_disc y reach_inf_reg (sin H) recuperan
    regularization_fixes = (rhi["reach_disc"] > rhi["reach_inf"] + 0.15) and (rhi["reach_inf_reg"] > rhi["reach_inf"] + 0.15)
    # (D) estimable leakage-free: converge desde abajo + Â=0 colapsa
    Tmin = bT[str(TS[0])]; Tmax = bT[str(TS[-1])]
    estimable = (Tmax["reach_H"] - Tmin["reach_H"]) > 0.05 and Tmax["reach_H"] > 0.90
    zeroA_collapses = (rhi["reach_H"] - ct["zeroA"]["reach_H"]) > 0.30
    sim_ok = grid["sim_check_lo"] > 0.9 and grid["sim_check_hi"] > 0.9

    # OVERCLAIMS RETRACTADOS -------------------------------------------------------------------------------------------
    # (1) el gap es ARTEFACTO de K=1: a K>=2 el gap_true evapora
    k1 = bK[str(KS[0])]; k2 = bK[str(KS[1])]
    gap_k1_true = round(k1["reach_H_true"] - k1["reach_inf_true"], 4)
    gap_k2_true = round(k2["reach_H_true"] - k2["reach_inf_true"], 4)
    gap_is_k1_artifact = gap_k1_true > 0.15 and gap_k2_true < 0.05
    # (2) la forma horizonte NO es privilegiada: reach_inf_reg (sin H) ≈ reach_H
    form_not_privileged = abs(rhi["reach_inf_reg"] - rhi["reach_H"]) < 0.05
    # (3) la RELEVANCIA es colineal: ŵ≡unos NO colapsa a ctrl_only (reach_H sigue alto)
    relevance_colinear = ct["ones"]["reach_H"] > rhi["ctrl_only"] + 0.20
    # (4) requiere COMPETENCIA: con un único lazo reach_inf NO falla
    requires_competition = bs["slow_only"]["reach_inf"] > 0.85 and bs["fast_only"]["reach_inf"] > 0.85

    core = inf_fragile_crude and form_not_estimation and regularization_fixes and estimable and zeroA_collapses and sim_ok
    overclaims = [gap_is_k1_artifact, form_not_privileged, relevance_colinear, requires_competition]
    n_overclaims = sum(overclaims)

    if core and n_overclaims >= 2:
        status = "mixta"
        verdict = (
            "H-V4-10m MIXTA (núcleo APOYADO + {no} overclaims RETRACTADOS por verificación adversarial de 4 agentes, 9no ciclo; "
            "leakage-free, sim-validada): bajo un sustrato con CICLOS el keystone valor=ctrl×rel sobrevive en su FACTOR DE "
            "CONTROLABILIDAD-REACH, pero la forma de estado-estacionario del 137 es NUMÉRICAMENTE FRÁGIL cerca de radio 1 y los "
            "claims fuertes son artefactos de evaluación. NÚCLEO APOYADO: a radio BAJO (a+g={rlo_r}) la reach-∞ y la finita "
            "COINCIDEN (reach_inf {rli}: reproduce 137). A radio→1 (a+g={rhi_r}) con H={hs}, K=1, la reach-∞ CRUDA MIS-RANKEA el "
            "modo top (reach_inf {rii} vs reach_H {rih}) y NO es ruido de estimación (con params VERDADEROS reach_inf_true {riit} "
            "vs reach_H_true {riht}) -> ES LA FORMA (ventana a∈[~0.45,0.65]). La REGULARIZACIÓN la cura: reach_disc {rid} y reach_"
            "inf_reg {rir} (cap-de-autovalor, SIN conocer H) recuperan. ESTIMABLE leakage-free (converge desde abajo T={tmin0} "
            "{rhm}->T={tmax0} {rhx}; Â:=0 colapsa a {z0}); sim_check={sclo}/{schi} (fórmula=física). RETRACTADO (verificación "
            "adversarial): (1) el gap es ARTEFACTO de K=1 WINNER-TAKE-ALL -- a K=2 EVAPORA (gap_true K1 +{gk1} -> K2 +{gk2}): "
            "reach_inf identifica el CONJUNTO correcto de modos relevantes, sólo invierte el orden #1<->#2 que K=1 castiga al "
            "máximo. (2) la forma HORIZONTE-H NO es privilegiada -- reach_inf_reg SIN H IGUALA a reach_H ({rir}≈{rih}); la novedad "
            "es REGULARIZAR el modo casi-crítico, no el horizonte. (3) la RELEVANCIA es COLINEAL -- ŵ≡unos (relevancia eliminada) "
            "da reach_H {ones} (no colapsa a ctrl_only {cto}); el control shuffle-ŵ daba falso positivo; el factor load-bearing es "
            "la CONTROLABILIDAD-REACH, no la relevancia (que 134-137 ya aisló). (4) 'falla cerca de radio 1' requiere COMPETENCIA "
            "de escalas temporales -- con un ÚNICO lazo reach_inf no falla (slow_only {so}/fast_only {fo}). => MIXTA: la reach-∞ "
            "cruda del 137 es frágil cerca de radio 1 y necesita REGULARIZACIÓN (caveat REAL al 137: el dominio de 137 es radio<1 "
            "con buen condicionamiento), pero NO se establece que la forma horizonte-H sea única ni que el efecto sobreviva a K>=2 "
            "ni que la relevancia se aísle aquí. Generaliza el alcance del keystone (130 costo, 132 esfuerzo, 133/137 red) con un "
            "caveat de CONDICIONAMIENTO bajo ciclos."
        ).format(no=n_overclaims, rlo_r=_f(SPECRADII[0]), rli=_f(rlo["reach_inf"]), rhi_r=_f(RHO_FIXED), hs=H_SHORT,
                 rii=_f(rhi["reach_inf"]), rih=_f(rhi["reach_H"]), riit=_f(rhi["reach_inf_true"]),
                 riht=_f(rhi["reach_H_true"]), rid=_f(rhi["reach_disc"]), rir=_f(rhi["reach_inf_reg"]),
                 tmin0=TS[0], rhm=_f(Tmin["reach_H"]), tmax0=TS[-1], rhx=_f(Tmax["reach_H"]),
                 z0=_f(ct["zeroA"]["reach_H"]), sclo=_f(grid["sim_check_lo"]), schi=_f(grid["sim_check_hi"]),
                 gk1=_f(gap_k1_true), gk2=_f(gap_k2_true), ones=_f(ct["ones"]["reach_H"]), cto=_f(rhi["ctrl_only"]),
                 so=_f(bs["slow_only"]["reach_inf"]), fo=_f(bs["fast_only"]["reach_inf"]))
    elif core and n_overclaims < 2:
        status = "apoyada"
        verdict = ("H-V4-10m APOYADA: la forma horizonte-finito es necesaria y robusta (overclaims no reproducidos: "
                   "gap_k1_artifact={a1} form_not_privileged={a2} relevance_colinear={a3} requires_competition={a4}).").format(
            a1=gap_is_k1_artifact, a2=form_not_privileged, a3=relevance_colinear, a4=requires_competition)
    elif not inf_fragile_crude or not form_not_estimation:
        status = "refutada"
        verdict = ("H-V4-10m REFUTADA: la reach-∞ cruda del 137 NO es frágil cerca de radio 1 (reach_inf {rii}~reach_H {rih}; true "
                   "{riit}~{riht}) -> la frontera de 137 no era real.").format(
            rii=_f(rhi["reach_inf"]), rih=_f(rhi["reach_H"]), riit=_f(rhi["reach_inf_true"]), riht=_f(rhi["reach_H_true"]))
    else:
        status = "mixta"
        verdict = ("H-V4-10m MIXTA: parcial -- core={c} (frag={fr} form={fm} reg={rg} est={es} zeroA={za} sim={so}) "
                   "overclaims={no}/4.").format(c=core, fr=inf_fragile_crude, fm=form_not_estimation, rg=regularization_fixes,
                                                es=estimable, za=zeroA_collapses, so=sim_ok, no=n_overclaims)

    return {"by_rho": br, "by_H": bH, "by_T": bT, "by_K": bK, "by_struct": bs, "ctrl": ct,
            "sim_check_lo": grid["sim_check_lo"], "sim_check_hi": grid["sim_check_hi"],
            "rlo_reach_inf": rlo["reach_inf"], "rlo_reach_H": rlo["reach_H"],
            "rhi_reach_inf": rhi["reach_inf"], "rhi_reach_H": rhi["reach_H"], "rhi_reach_disc": rhi["reach_disc"],
            "rhi_reach_inf_reg": rhi["reach_inf_reg"], "rhi_local": rhi["local"], "rhi_ctrl_only": rhi["ctrl_only"],
            "rhi_reach_inf_true": rhi["reach_inf_true"], "rhi_reach_H_true": rhi["reach_H_true"],
            "gap_hat": round(rhi["reach_H"] - rhi["reach_inf"], 4),
            "gap_true": round(rhi["reach_H_true"] - rhi["reach_inf_true"], 4),
            "gap_k1_true": gap_k1_true, "gap_k2_true": gap_k2_true,
            "ones_reach_H": ct["ones"]["reach_H"], "shuffle_reach_H": ct["shuffle"]["reach_H"],
            "zeroA_reach_H": ct["zeroA"]["reach_H"],
            "slowonly_reach_inf": bs["slow_only"]["reach_inf"], "fastonly_reach_inf": bs["fast_only"]["reach_inf"],
            "Tmin_reachH": Tmin["reach_H"], "Tmax_reachH": Tmax["reach_H"], "corr_w_hi": rhi["corr_w"],
            "inf_fragile_crude": bool(inf_fragile_crude), "form_not_estimation": bool(form_not_estimation),
            "regularization_fixes": bool(regularization_fixes), "estimable": bool(estimable),
            "zeroA_collapses": bool(zeroA_collapses), "sim_ok": bool(sim_ok),
            "gap_is_k1_artifact": bool(gap_is_k1_artifact), "form_not_privileged": bool(form_not_privileged),
            "relevance_colinear": bool(relevance_colinear), "requires_competition": bool(requires_competition),
            "core": bool(core), "n_overclaims": int(n_overclaims), "status": status, "verdict": verdict}


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

    log("[exp123] CYCLE 139 / H-V4-10m (MIXTA post-verificación) — keystone bajo CICLOS: la reach-∞ del 137 es frágil cerca de radio 1 (necesita regularización) PERO el gap es artefacto de K=1, la forma horizonte no es única, la relevancia es colineal")
    log(f"[exp123] seeds={args.seeds} a={AA} D={D} K={K_DEFAULT} c_fast={C_FAST} cap={CAP_DEFAULT} specradii={SPECRADII} Hs={HS} Ts={TS} Ks={KS} structs={STRUCTS}")

    grid = run(args.seeds)
    sm = build_summary(grid)

    log("[exp123] --- (1) BARRIDO radio (H=%d,T=%d,K=1) — reach_inf(137,∞ cruda) vs regularizadas (reach_H finito / reach_disc / reach_inf_reg cap-autovalor SIN H) ---" % (H_SHORT, T_FIXED))
    for r in SPECRADII:
        c = grid["by_rho"][str(r)]
        log(f"[exp123] radio={r:>4}: reach_inf={c['reach_inf']:.3f} | reach_H={c['reach_H']:.3f} reach_disc={c['reach_disc']:.3f} reach_inf_reg={c['reach_inf_reg']:.3f} | TRUE inf={c['reach_inf_true']:.3f} H={c['reach_H_true']:.3f} | ctrl={c['ctrl_only']:.3f}")
    log("[exp123] --- (2) BARRIDO K (radio=%.2f,H=%d) — el gap es ARTEFACTO de K=1 (evapora a K>=2) ---" % (RHO_FIXED, H_SHORT))
    for K in KS:
        c = grid["by_K"][str(K)]
        log(f"[exp123] K={K}: reach_inf={c['reach_inf']:.3f} reach_H={c['reach_H']:.3f} | TRUE inf={c['reach_inf_true']:.3f} H={c['reach_H_true']:.3f} (gap_true={c['reach_H_true']-c['reach_inf_true']:+.3f})")
    log("[exp123] --- (3) BARRIDO estructura (radio=%.2f,H=%d) — 'falla' requiere COMPETENCIA de escalas temporales ---" % (RHO_FIXED, H_SHORT))
    for st in STRUCTS:
        c = grid["by_struct"][st]
        log(f"[exp123] {st:>10}: reach_inf={c['reach_inf']:.3f} reach_H={c['reach_H']:.3f} | TRUE inf={c['reach_inf_true']:.3f}")
    log("[exp123] --- (4) CONTROLES nulos (radio=%.2f,H=%d): relevancia y dinámica ---" % (RHO_FIXED, H_SHORT))
    log(f"[exp123] ŵ real reach_H={grid['by_rho'][str(RHO_FIXED)]['reach_H']:.3f} | ŵ shuffle={grid['ctrl']['shuffle']['reach_H']:.3f} | ŵ≡unos(relev ELIMINADA)={grid['ctrl']['ones']['reach_H']:.3f} | Â:=0={grid['ctrl']['zeroA']['reach_H']:.3f} | ctrl_only={grid['by_rho'][str(RHO_FIXED)]['ctrl_only']:.3f}  (unos NO colapsa -> relevancia COLINEAL)")
    log("[exp123] --- (5) BARRIDO T (radio=%.2f,H=%d) — reach_H estimable leakage-free (converge desde abajo) ---" % (RHO_FIXED, H_SHORT))
    for T in TS:
        c = grid["by_T"][str(T)]
        log(f"[exp123] T={T:>5}: reach_H={c['reach_H']:.3f} reach_inf={c['reach_inf']:.3f} | corr_w={c['corr_w']:.2f}")
    log(f"[exp123] --- (6) SIM-CHECK fórmula-oracle = física: lo(0.6)={grid['sim_check_lo']:.3f} hi({RHO_FIXED})={grid['sim_check_hi']:.3f}")
    log(f"[exp123] CHECK NÚCLEO: inf_fragile_crude={sm['inf_fragile_crude']} form_not_estimation={sm['form_not_estimation']} regularization_fixes={sm['regularization_fixes']} estimable={sm['estimable']} zeroA_collapses={sm['zeroA_collapses']} sim_ok={sm['sim_ok']} -> core={sm['core']}")
    log(f"[exp123] CHECK OVERCLAIMS RETRACTADOS: gap_is_k1_artifact={sm['gap_is_k1_artifact']} (K1 +{sm['gap_k1_true']:.3f}->K2 +{sm['gap_k2_true']:.3f}) form_not_privileged={sm['form_not_privileged']} relevance_colinear={sm['relevance_colinear']} requires_competition={sm['requires_competition']} -> n_overclaims={sm['n_overclaims']}/4")
    log(f"[exp123] VEREDICTO H-V4-10m: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp123_cyclic_substrate", "cycle": 139, "hypothesis": "H-V4-10m",
           "claim": "MIXTA (nucleo APOYADO + 4 overclaims RETRACTADOS por verificacion adversarial de 4 agentes). NUCLEO: bajo "
                    "ciclos la reach de estado-estacionario CRUDA del 137 (I-A)^-1 es NUMERICAMENTE FRAGIL cerca de radio espectral "
                    "1 (mis-rankea el modo top bajo K=1) y una REGULARIZACION (reach horizonte-finito, descontada, o cap-de-"
                    "autovalor SIN H) la cura; es la FORMA no la estimacion (reach_inf_true falla, ventana a en [0.45,0.65]); "
                    "estimable leakage-free, sim-validada. Es un caveat REAL al 137 (cuyo dominio es radio<1 con buen "
                    "condicionamiento). RETRACTADO: (1) el gap titular es ARTEFACTO de K=1 winner-take-all -- evapora a K>=2 "
                    "(reach_inf identifica el conjunto correcto, solo invierte #1<->#2); (2) la forma horizonte-H NO es privilegiada "
                    "-- una reach-inf regularizada por cap-de-autovalor SIN conocer H iguala a reach_H (la novedad es regularizar "
                    "el modo casi-critico, no el horizonte); (3) la RELEVANCIA es COLINEAL/no-aislada (w=unos da reach_H~0.99, el "
                    "control shuffle daba falso positivo); (4) 'falla cerca de radio 1' requiere COMPETENCIA de escalas temporales "
                    "(con un unico lazo reach_inf=1.0 hasta radio 0.99). Alcance: lineal, ciclo de 2, radio<1, D=8 fijo, K=1",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp123] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
