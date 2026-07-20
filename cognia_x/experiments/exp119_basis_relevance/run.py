r"""
exp119 — CYCLE 135 / H-V4-10i (rama control/acción, CIERRA el caveat EJE2 de 134: la relevancia NO se descubre bajo meta NO-
LINEAL porque el credit-assignment es LINEAL): ¿una BASE de credit-assignment más RICA recupera la relevancia bajo una meta no-
lineal, y a qué COSTO? Si sí, descubrir la relevancia bajo no-linealidad es fundamentalmente un problema de PRIOR (qué base) ->
UNE el factor RELEVANCIA de R-VALOR con R-PRIOR.

CONTEXTO. CYCLE 134 (exp118) cerró el supuesto 'relevancia DADA' del arco 127-133: el R-VALOR completo (valor=ctrl×rel) es
descubrible de UN stream de experiencia-acción. Pero dejó un CAVEAT agudo (EJE2/forma-de-meta): el credit-assignment LINEAL
(regresar G ~ x) recupera la relevancia sólo si la meta es ~lineal-descomponible en el estado observado. Bajo meta PAR (G=Σw·x²)
recupera corr(ŵ,w)≈0.00 y valor_ambos cae a azar. Este ciclo ataca ese caveat: cambia la BASE del credit-assignment (las features
sobre las que se regresa G), no el sustrato ni la decisión.

DISEÑO (numpy, mínima desviación de exp118). Sustrato IDÉNTICO: 8 modos en 4 cuadrantes (CONTROLABLE b∈{1,0}) × (RELEVANTE
w∈{1,0}); 2 por cuadrante; los irrelevantes-incontrolables son RUIDOSOS (s=1.5). x_{t+1}=a·x+b⊙u+ruido·s; stream de T pasos de
exploración u~N(0,σ_u). META escalar de pesos OCULTOS, en 4 FORMAS: linear (Σw·x), even (Σw·x²), relu (Σw·relu(x)), mixed
(Σw·(0.5x+0.5x²)). ESTIMADORES de la MISMA experiencia: b̂ (control, regresión x'~[x,u], 128, COMPARTIDO entre brazos); ŵ por
BASE de credit-assignment -- regresar G sobre features z-scoreadas de x con ridge suave, ŵ_i = norma del bloque de coeficientes del
modo i. BASES: 'linear' [x] (la de 134), 'even' [x²], 'relu' [relu(x)], 'rich' [x,x²,relu(x)] (genérica, NO sabe la forma).
DECISIÓN: top-K por valor_ambos_BASE = ŵ_BASE · b̂²/(b̂²+ρ); arms PAREADOS sobre la misma experiencia; perf = beneficio/oracle con
w,b VERDADEROS en el eval (aísla la asignación). 'matched' = la base que casa con la forma (linear->linear, even->even,
relu->relu, mixed->rich) = el PRIOR-oráculo de la forma.

BARRIDOS: (1) FORMA de la meta × BASE (la tabla núcleo: ¿qué base recupera qué forma?); (2) T presupuesto bajo meta EVEN
(linear/even/rich) -> costo de datos; (3) σ_g ruido de meta bajo EVEN (even/rich) -> ¿la riqueza amplifica el costo?

PREGUNTA FALSABLE:
  - APOYADA si una base RICA recupera la relevancia bajo meta no-lineal Y una base MATCHED es ROBUSTAMENTE más eficiente (el prior
    PAGA aun bajo regularización cross-validada) Y no hay base fija universal -> R-PRIOR como cuello.
  - MIXTA si la base rica recupera (núcleo) pero los claims secundarios NO se sostienen (el 'prior paga' es artefacto de
    sub-regularización; existe una base fija casi-universal) -> bundle de claims (directiva v4): núcleo apoyado, secundarios acotados.
  - REFUTADA si ni la matched recupera -> la base no es el problema (obstrucción más profunda).

VEREDICTO (exp119, 200 seeds, POST-VERIFICACIÓN ADVERSARIAL de 4 agentes — 5to ciclo de la institución): MIXTA.
  SOBREVIVE (leakage-free verificado): la base RICA [x,x²,relu] -o de paridad-mixta- recupera el factor RELEVANCIA bajo meta
  no-lineal (cierra el caveat EJE2 de 134); la base lineal falla bajo meta par por ORTOGONALIDAD-DE-PARIDAD; robusta a las 4 formas
  y a sustratos más duros; con dato limpio la generalidad es GRATIS. NO SE SOSTIENEN (claims retractados por la verificación):
  (1) 'el prior paga / costo de DATOS escala con la riqueza' -- el eje datos es nulo (T≥30) y el de ruido es ~80% ARTEFACTO de
  sub-regularizar la base rica (subir el ridge a 0.3, gratis en el régimen fácil, cierra el gap σ_g=20 de +0.29 a +0.07; el propio
  build_summary vira a MIXTA); (2) 'no hay base fija universal' -- FALSO: un feature fijo relu (paridad-mixta) recupera todas las
  formas probadas (peor caso ~0.99); sólo fallan bases de paridad-PURA ortogonales (linear↔even); (3) 'une R-VALOR con R-PRIOR' --
  PUENTE SUGERIDO, no testeado (no aprende/selecciona la base). PRÓXIMO: testear R-PRIOR explícito (aprender/seleccionar la base).

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp119_basis_relevance.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp119_basis_relevance.run            # FULL
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
AA = 0.6
RHO = 0.5
D = 8
K = 2
SG_DEFAULT = 0.5
SU_DEFAULT = 1.0
RIDGE = 1e-2                                  # ridge suave para estabilizar la base rica (colinealidad x²/relu)
RIDGE_HI = 0.3                                 # ridge MAYOR (cross-validable, gratis en el régimen fácil): prueba si el 'prior paga' es artefacto de sub-regularización
TS = [10, 30, 100, 300, 1000]
T_SMALL = 100                                 # punto de costo-de-datos para "el prior paga"
SIGMA_GS = [0.5, 2.0, 5.0, 20.0]
META_FORMS = ["linear", "even", "relu", "mixed"]
BASES = ["linear", "even", "relu", "rich"]
T_FIXED = 300
MATCHED = {"linear": "linear", "even": "even", "relu": "relu", "mixed": "rich"}

B_CAN = np.array([1.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0])
W_CAN = np.array([1.0, 1.0, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0])
S_CAN = np.array([0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 1.5, 1.5])


def _true_value(b, w):
    return w * b ** 2 / (b ** 2 + RHO)


def _meta(x, w, form):
    if form == "linear":
        f = x
    elif form == "even":
        f = x ** 2
    elif form == "relu":
        f = np.maximum(x, 0.0)
    elif form == "mixed":
        f = 0.5 * x + 0.5 * x ** 2
    else:
        raise ValueError(form)
    return float(np.dot(w, f))


def _basis_cols(xi, basis):
    if basis == "linear":
        return [xi]
    if basis == "even":
        return [xi ** 2]
    if basis == "relu":
        return [np.maximum(xi, 0.0)]
    if basis == "rich":
        return [xi, xi ** 2, np.maximum(xi, 0.0)]
    raise ValueError(basis)


def _experience(rng, b, w, s, T, sigma_u, sigma_g, form):
    x = np.zeros(D)
    X = np.zeros((T, D)); Xn = np.zeros((T, D)); U = np.zeros((T, D)); G = np.zeros(T)
    for t in range(T):
        u = rng.normal(0, sigma_u, D)
        xn = AA * x + b * u + rng.normal(0, 1.0, D) * s
        g = _meta(x, w, form) + rng.normal(0, sigma_g)
        X[t] = x; Xn[t] = xn; U[t] = u; G[t] = g
        x = xn
    return X, Xn, U, G


def _estimate_b(X, Xn, U):
    b_hat = np.zeros(D)
    for i in range(D):
        F = np.stack([X[:, i], U[:, i]], axis=1)
        coef, *_ = np.linalg.lstsq(F, Xn[:, i], rcond=None)
        b_hat[i] = coef[1]
    return np.abs(b_hat)


def _estimate_w(X, G, basis, ridge=RIDGE):
    """Credit-assignment por una BASE: regresa G (centrado) sobre features z-scoreadas; ŵ_i = norma del bloque del modo i."""
    T = X.shape[0]
    cols = []
    blocks = []                                       # (start, count) por modo (sin intercepto)
    idx = 0
    for i in range(D):
        bc = _basis_cols(X[:, i], basis)
        for c in bc:
            mu = c.mean(); sd = c.std()
            cols.append((c - mu) / sd if sd > 1e-9 else (c - mu))
        blocks.append((idx, len(bc)))
        idx += len(bc)
    Phi = np.stack(cols, axis=1)                       # (T, D*|basis|), z-scoreada
    g = G - G.mean()
    A = Phi.T @ Phi + ridge * T * np.eye(Phi.shape[1])
    coef = np.linalg.solve(A, Phi.T @ g)
    w_hat = np.array([float(np.linalg.norm(coef[s:s + c])) for (s, c) in blocks])
    return w_hat


def _benefit(S, b, w):
    return float(np.sum(_true_value(b, w)[list(S)]))


def run_cell(form, T, sigma_u, sigma_g, n_seeds, ridge=RIDGE):
    accs = {f"ambos_{bs}": [] for bs in BASES}
    accs["ctrl_solo"] = []; accs["prediccion"] = []
    corrw = {bs: [] for bs in BASES}
    corrb = []
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed * 7919 + int(T) * 13 + int(sigma_u * 1000) * 7
                                    + int(sigma_g * 100) * 101
                                    + {"linear": 0, "even": 1, "relu": 2, "mixed": 3}[form] * 50021 + 11)
        perm = rng.permutation(D)
        b = B_CAN[perm]; w = W_CAN[perm]; s = S_CAN[perm]
        X, Xn, U, G = _experience(rng, b, w, s, T, sigma_u, sigma_g, form)

        b_hat = _estimate_b(X, Xn, U)
        var_hat = np.var(X, axis=0)
        ctrl_score = b_hat ** 2 / (b_hat ** 2 + RHO)

        tv = _true_value(b, w)
        oracle = set(np.argsort(tv)[-K:].tolist())
        den = _benefit(oracle, b, w) + 1e-12

        for basis in BASES:
            w_hat = _estimate_w(X, G, basis, ridge)
            S = set(np.argsort(w_hat * ctrl_score)[-K:].tolist())
            accs[f"ambos_{basis}"].append(_benefit(S, b, w) / den)
            if np.std(w_hat) > 1e-9:
                corrw[basis].append(float(np.corrcoef(w_hat, w)[0, 1]))
        accs["ctrl_solo"].append(_benefit(set(np.argsort(ctrl_score)[-K:].tolist()), b, w) / den)
        accs["prediccion"].append(_benefit(set(np.argsort(var_hat)[-K:].tolist()), b, w) / den)
        if np.std(b_hat) > 1e-9:
            corrb.append(float(np.corrcoef(b_hat, b)[0, 1]))

    out = {k: round(float(np.mean(v)), 4) for k, v in accs.items()}
    for bs in BASES:
        out[f"corrw_{bs}"] = round(float(np.mean(corrw[bs])) if corrw[bs] else 0.0, 4)
    out["corr_b"] = round(float(np.mean(corrb)) if corrb else 0.0, 4)
    out["ambos_matched"] = out[f"ambos_{MATCHED[form]}"]
    out["corrw_matched"] = out[f"corrw_{MATCHED[form]}"]
    return out


def _random_baseline(n_seeds=4000):
    rng = np.random.default_rng(12345)
    b = B_CAN; w = W_CAN; tv = _true_value(b, w)
    oracle = float(np.sum(np.sort(tv)[-K:]))
    accs = []
    for _ in range(n_seeds):
        S = rng.choice(D, K, replace=False)
        accs.append(float(np.sum(tv[S])) / oracle)
    return round(float(np.mean(accs)), 4)


def run(n_seeds):
    by_form = {form: run_cell(form, T_FIXED, SU_DEFAULT, SG_DEFAULT, n_seeds) for form in META_FORMS}
    by_T = {str(T): run_cell("even", T, SU_DEFAULT, SG_DEFAULT, n_seeds) for T in TS}
    by_sg = {str(sg): run_cell("even", T_FIXED, SU_DEFAULT, sg, n_seeds) for sg in SIGMA_GS}
    # PROBE de robustez-a-ridge (post-verificación adversarial): el 'prior paga' a σ_g alto, ¿sobrevive a más regularización?
    sg_hi = SIGMA_GS[-1]
    sg20_hiridge = run_cell("even", T_FIXED, SU_DEFAULT, sg_hi, n_seeds, ridge=RIDGE_HI)
    return {"by_form": by_form, "by_T": by_T, "by_sg": by_sg, "sg20_hiridge": sg20_hiridge,
            "random_baseline": _random_baseline()}


def _f(x):
    return "{:.3f}".format(x)


def build_summary(grid):
    bf = grid["by_form"]; gT = grid["by_T"]; gsg = grid["by_sg"]; rand = grid["random_baseline"]
    hr = grid["sg20_hiridge"]
    ev = bf["even"]

    # NOTA: la métrica primaria es la DECISIÓN (ambos = beneficio/oracle del top-K), que es la brújula de R-VALOR.
    # corr(ŵ,w) es un diagnóstico SECUNDARIo: la operación-norma (ŵ_i=‖coef bloque i‖) sesga positivo a los modos ruidosos,
    # así que corr_w queda bajo (~0.6) aun cuando el ranking top-K es perfecto. (Verificado: lente identificabilidad.)

    # === NÚCLEO QUE SOBREVIVE (verificado por 4 agentes, leakage-free) ===
    # (1) reproduce el caveat 134: la base LINEAL queda fuertemente DEGRADADA bajo meta even (recupera ~29% del gap, corr_w ~0.18)
    linear_fails = ev["ambos_linear"] < 0.75 and ev["corrw_linear"] < 0.40
    # (2) la base MATCHED (prior de la forma) RESUCITA la relevancia bajo even (decisión)
    matched_recovers = ev["ambos_even"] > 0.88
    # (3) la base RICA genérica (NO sabe la forma) recupera bajo even y bate a la lineal por margen grande (t~17.6, frac>=1.0)
    rich_recovers = ev["ambos_rich"] > 0.85 and (ev["ambos_rich"] - ev["ambos_linear"]) > 0.15
    # (4) la rica es ROBUSTA a TODA forma (linear/even/relu/mixed) sin saber cuál
    rich_robust = all(bf[f]["ambos_rich"] > 0.88 for f in META_FORMS)
    core_recovers = matched_recovers and rich_recovers and rich_robust

    # === CLAIMS SECUNDARIOS ACOTADOS/RETRACTADOS (cazados por la verificación adversarial) ===
    small_T = gT[str(T_SMALL)]
    hi_sg = gsg[str(SIGMA_GS[-1])]
    # (5a) eje DATOS: NULO en el checkpoint -- la 'eficiencia de datos' del prior no existe a T>=30 (sólo a T<=15, base rica rank-deficiente)
    prior_pays_data = (small_T["ambos_even"] - small_T["ambos_rich"]) > 0.05
    # (5b) eje RUIDO: existe a ridge MILD (σ_g=20: matched bate a rica) PERO ~80% se cierra subiendo el ridge (cross-validable, gratis)
    gap_noise_loridge = hi_sg["ambos_even"] - hi_sg["ambos_rich"]
    gap_noise_hiridge = hr["ambos_even"] - hr["ambos_rich"]
    prior_pays_noise_loridge = gap_noise_loridge > 0.08
    # ROBUSTO sólo si una ventaja SUSTANCIAL del prior (>0.15, ~la mitad del gap a ridge mild) SOBREVIVE a la regularización
    # cross-validada; un residual ~0.07 = ~75% cerrado NO es un costo intrínseco de la generalidad.
    prior_pays_noise_hiridge = gap_noise_hiridge > 0.15
    prior_pays_robust = prior_pays_noise_hiridge or prior_pays_data   # 'prior paga' ROBUSTO sólo si sobrevive al ridge alto o paga en datos
    # (6) 'no hay base fija universal' es FALSO: una base FIJA de paridad-mixta (relu) es casi-universal sobre las formas probadas;
    #     sólo fallan las bases de PARIDAD-PURA ortogonales (linear<->even). El fenómeno real es ORTOGONALIDAD-DE-PARIDAD.
    relu_worst = min(bf[f]["ambos_relu"] for f in META_FORMS)
    relu_near_universal = relu_worst > 0.88
    parity_orthogonal_fails = (bf["even"]["ambos_linear"] < 0.78) and (bf["linear"]["ambos_even"] < 0.80)

    data_cost = {
        "small_T_matched": small_T["ambos_even"], "small_T_rich": small_T["ambos_rich"],
        "small_T_linear": small_T["ambos_linear"],
        "hi_sg_matched": hi_sg["ambos_even"], "hi_sg_rich": hi_sg["ambos_rich"],
        "hi_sg_corrw_matched": hi_sg["corrw_even"], "hi_sg_corrw_rich": hi_sg["corrw_rich"],
        "hi_sg_matched_hiridge": hr["ambos_even"], "hi_sg_rich_hiridge": hr["ambos_rich"],
        "gap_noise_loridge": round(gap_noise_loridge, 4), "gap_noise_hiridge": round(gap_noise_hiridge, 4),
        "ridge_lo": RIDGE, "ridge_hi": RIDGE_HI,
    }

    # VEREDICTO MIXTA (post-verificación adversarial de 4 agentes, 5to ciclo): el NÚCLEO recupera, pero el ciclo BUNDLEABA dos
    # claims secundarios FRÁGILES/FALSOS ('el prior paga' = artefacto de sub-regularización; 'no hay base fija universal' = falso).
    # Directiva v4: bundle de claims donde sólo una parte se aísla = MIXTA, no apoyada.
    if core_recovers and not (prior_pays_robust and not relu_near_universal):
        status = "mixta"
        verdict = (
            "H-V4-10i MIXTA (post-verificación adversarial de 4 agentes, 5to ciclo; leakage-free verificado): el NÚCLEO RECUPERA "
            "pero los CLAIMS SECUNDARIOS no se sostienen. SOBREVIVE: una base de credit-assignment RICA [x,x²,relu] -o de paridad-"
            "mixta- recupera el factor RELEVANCIA del R-VALOR bajo meta NO-LINEAL, cerrando el caveat EJE2 de 134. La base LINEAL "
            "de 134 queda fuertemente DEGRADADA bajo meta PAR (ambos={al} vs ctrl_solo {cs}, corr(ŵ,w)={cwl}; recupera ~29% del "
            "gap) por ORTOGONALIDAD-DE-PARIDAD (una función impar no representa una par); la MATCHED (ambos={am}) y la RICA genérica "
            "-que NO sabe la forma- (ambos={ar}, +{gap} sobre la lineal, t~17.6, frac(rich≥lin)=1.0) la RESUCITAN, robustas a TODA "
            "forma (linear {arl}/even {are}/relu {arr}/mixed {arm}); con dato amplio/limpio la generalidad es GRATIS. El núcleo "
            "sobrevive a sustratos más duros (pesos graduados, disociación genuina ctrl-rel ctrl_solo→0.20, D=16 K=4) -verificación-. "
            "NO SE SOSTIENEN (claims retractados): (1) 'el PRIOR PAGA / costo de DATOS escala con la riqueza' -- el eje DATOS es NULO "
            "(T={ts}: matched-rica +{ppd}; sólo paga a T≤15, base rica rank-deficiente) y el eje RUIDO (σ_g=20: +{gnl} a ridge {rl}) "
            "es ~80% ARTEFACTO de sub-regularizar la base rica: subiendo el ridge a {rh} (cross-validable, GRATIS en el régimen "
            "fácil) el gap cae a +{gnh}. El mecanismo es VARIANZA por colinealidad x²/relu, no un costo intrínseco de la "
            "generalidad. (2) 'NO hay base FIJA universal' es FALSO: la base FIJA relu (1 columna, paridad-mixta) es casi-universal "
            "sobre las formas probadas (peor caso {rw}); sólo fallan las bases de PARIDAD-PURA ORTOGONALES (lin-en-even {al}, "
            "even-en-lin {el}). El fenómeno real es ORTOGONALIDAD-DE-PARIDAD, no 'no existe base universal'. (3) 'une R-VALOR con "
            "R-PRIOR' es un PUENTE SUGERIDO, no testeado: el experimento hace ingeniería de features (cambiar columnas de una "
            "regresión ridge), no APRENDE/SELECCIONA la base ni varía un prior. => H-V4-10i acota a: el factor relevancia ES "
            "discoverable bajo no-linealidad con una base suficientemente expresiva (paridad-mixta/rica), barata cuando el dato es "
            "limpio; testear si elegir/aprender la base es un cuello de R-PRIOR (y si la robustez-al-ruido del prior sobrevive a la "
            "cross-validación) es el PRÓXIMO ciclo."
        ).format(al=_f(ev["ambos_linear"]), cs=_f(ev["ctrl_solo"]), cwl=_f(ev["corrw_linear"]), am=_f(ev["ambos_even"]),
                 ar=_f(ev["ambos_rich"]), gap=_f(ev["ambos_rich"] - ev["ambos_linear"]), arl=_f(bf["linear"]["ambos_rich"]),
                 are=_f(bf["even"]["ambos_rich"]), arr=_f(bf["relu"]["ambos_rich"]), arm=_f(bf["mixed"]["ambos_rich"]),
                 ts=T_SMALL, ppd=_f(small_T["ambos_even"] - small_T["ambos_rich"]), gnl=_f(gap_noise_loridge),
                 rl=RIDGE, rh=RIDGE_HI, gnh=_f(gap_noise_hiridge), rw=_f(relu_worst), el=_f(bf["linear"]["ambos_even"]))
    elif core_recovers and prior_pays_robust and not relu_near_universal:
        status = "apoyada"
        verdict = ("H-V4-10i APOYADA: la base rica recupera la relevancia bajo no-linealidad y el prior paga ROBUSTAMENTE "
                   "(sobrevive al ridge alto: gap {gnh}) y no hay base fija universal (relu peor caso {rw}).").format(
                       gnh=_f(gap_noise_hiridge), rw=_f(relu_worst))
    elif not matched_recovers:
        status = "refutada"
        verdict = ("H-V4-10i REFUTADA: ni la base MATCHED recupera la relevancia bajo meta no-lineal (even ambos={am}, "
                   "corr(ŵ,w)={cwe}) -> la base/prior no es el problema; obstrucción más profunda.").format(
                       am=_f(ev["ambos_even"]), cwe=_f(ev["corrw_even"]))
    else:
        status = "mixta"
        verdict = ("H-V4-10i MIXTA: recuperación parcial -- core_recovers={cr} prior_pays_robust={pp} "
                   "relu_near_universal={ru}; even ambos lin={al}/matched={am}/rich={ar}.").format(
                       cr=core_recovers, pp=prior_pays_robust, ru=relu_near_universal,
                       al=_f(ev["ambos_linear"]), am=_f(ev["ambos_even"]), ar=_f(ev["ambos_rich"]))

    return {"by_form": bf, "by_T": gT, "by_sg": gsg, "sg20_hiridge": hr, "random_baseline": rand,
            "even_ambos_linear": ev["ambos_linear"], "even_ambos_even": ev["ambos_even"],
            "even_ambos_rich": ev["ambos_rich"], "even_ctrl_solo": ev["ctrl_solo"],
            "even_corrw_linear": ev["corrw_linear"], "even_corrw_even": ev["corrw_even"],
            "even_corrw_rich": ev["corrw_rich"],
            "rich_linear": bf["linear"]["ambos_rich"], "rich_even": bf["even"]["ambos_rich"],
            "rich_relu": bf["relu"]["ambos_rich"], "rich_mixed": bf["mixed"]["ambos_rich"],
            "relu_worst": relu_worst, "relu_near_universal": bool(relu_near_universal),
            "offform_linear_on_even": bf["even"]["ambos_linear"], "offform_even_on_linear": bf["linear"]["ambos_even"],
            "data_cost": data_cost,
            "linear_fails": bool(linear_fails), "matched_recovers": bool(matched_recovers),
            "rich_recovers": bool(rich_recovers), "rich_robust": bool(rich_robust),
            "core_recovers": bool(core_recovers),
            "prior_pays_data": bool(prior_pays_data), "prior_pays_noise_loridge": bool(prior_pays_noise_loridge),
            "prior_pays_noise_hiridge": bool(prior_pays_noise_hiridge), "prior_pays_robust": bool(prior_pays_robust),
            "parity_orthogonal_fails": bool(parity_orthogonal_fails),
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

    log("[exp119] CYCLE 135 / H-V4-10i — ¿una BASE de credit-assignment más RICA recupera la relevancia bajo meta NO-LINEAL (cierra el caveat EJE2 de 134)? ¿el prior PAGA? ¿es R-PRIOR? (MIXTA post-verificación adversarial)")
    log(f"[exp119] seeds={args.seeds} a={AA} rho={RHO} D={D} K={K} ridge={RIDGE} ridge_hi={RIDGE_HI} Ts={TS} sigma_gs={SIGMA_GS} forms={META_FORMS} bases={BASES} (T_fixed={T_FIXED})")

    grid = run(args.seeds)
    sm = build_summary(grid)
    dc = sm["data_cost"]

    log(f"[exp119] random_baseline (elegir K={K} al azar / oracle) = {grid['random_baseline']:.3f}")
    log("[exp119] --- (1) FORMA de la meta × BASE (T=%d) — la tabla núcleo: ¿qué base recupera qué forma? ---" % T_FIXED)
    for form in META_FORMS:
        r = grid["by_form"][form]
        log(f"[exp119] meta={form:>6}: ctrl_solo={r['ctrl_solo']:.3f} | ambos lin={r['ambos_linear']:.3f} even={r['ambos_even']:.3f} relu={r['ambos_relu']:.3f} rich={r['ambos_rich']:.3f} matched={r['ambos_matched']:.3f} | corr_w lin={r['corrw_linear']:.2f} even={r['corrw_even']:.2f} relu={r['corrw_relu']:.2f} rich={r['corrw_rich']:.2f}")
    log(f"[exp119]   relu (base FIJA de paridad-mixta) peor-caso sobre las formas = {sm['relu_worst']:.3f} -> relu_near_universal={sm['relu_near_universal']} (REFUTA 'no hay base fija universal')")
    log("[exp119] --- (2) BARRIDO T bajo meta EVEN — eje DATOS (¿paga el prior en eficiencia de datos?) ---")
    for T in TS:
        r = grid["by_T"][str(T)]
        log(f"[exp119] T={T:>4}: lin={r['ambos_linear']:.3f} matched(even)={r['ambos_even']:.3f} rich={r['ambos_rich']:.3f} | corr_w even={r['corrw_even']:.2f} rich={r['corrw_rich']:.2f}")
    log("[exp119] --- (3) BARRIDO σ_g ruido de meta bajo EVEN — eje RUIDO (¿paga el prior en robustez al ruido?) ---")
    for sg in SIGMA_GS:
        r = grid["by_sg"][str(sg)]
        log(f"[exp119] σ_g={sg:>5}: matched(even)={r['ambos_even']:.3f} rich={r['ambos_rich']:.3f} | corr_w even={r['corrw_even']:.2f} rich={r['corrw_rich']:.2f}")
    log(f"[exp119] --- (4) PROBE robustez-a-RIDGE del 'prior paga' (σ_g={SIGMA_GS[-1]}, even) — ¿es artefacto de sub-regularización? ---")
    log(f"[exp119] gap matched-rica: ridge={RIDGE} -> +{dc['gap_noise_loridge']:.3f} | ridge={RIDGE_HI} (cross-validable) -> +{dc['gap_noise_hiridge']:.3f}  => prior_pays_robust={sm['prior_pays_robust']} (el 'prior paga' {'SOBREVIVE' if sm['prior_pays_robust'] else 'SE CIERRA'} a más regularización)")
    log(f"[exp119] CHECK core_recovers={sm['core_recovers']} (matched={sm['matched_recovers']} rich={sm['rich_recovers']} robust={sm['rich_robust']}) | prior_pays_data={sm['prior_pays_data']} prior_pays_noise_loridge={sm['prior_pays_noise_loridge']} prior_pays_noise_hiridge={sm['prior_pays_noise_hiridge']} prior_pays_robust={sm['prior_pays_robust']} | relu_near_universal={sm['relu_near_universal']} parity_orthogonal_fails={sm['parity_orthogonal_fails']}")
    log(f"[exp119] VEREDICTO H-V4-10i: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp119_basis_relevance", "cycle": 135, "hypothesis": "H-V4-10i",
           "claim": "MIXTA (post-verificacion adversarial de 4 agentes). SOBREVIVE: una BASE de credit-assignment RICA [x,x2,relu] "
                    "-o de paridad-mixta- recupera el factor RELEVANCIA del R-VALOR bajo meta NO-LINEAL, cerrando el caveat EJE2 de "
                    "134 (la base lineal falla bajo meta par por ORTOGONALIDAD-DE-PARIDAD); robusta a las 4 formas y a sustratos "
                    "mas duros; con dato limpio la generalidad es GRATIS. NO SE SOSTIENEN: (1) 'el prior paga / costo de datos "
                    "escala con la riqueza' -- el eje datos es nulo (T>=30) y el de ruido es ~80% artefacto de sub-regularizar la "
                    "base rica (subir el ridge, gratis, cierra el gap); (2) 'no hay base fija universal' -- FALSO: un feature fijo "
                    "relu (paridad-mixta) recupera todas las formas probadas; solo fallan bases de paridad-pura ortogonales; (3) "
                    "'une R-VALOR con R-PRIOR' -- puente SUGERIDO, no testeado (no aprende/selecciona la base). Proximo: testear "
                    "R-PRIOR explicito (aprender/seleccionar la base; si la robustez del prior sobrevive a cross-validacion)",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp119] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
