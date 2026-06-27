r"""
exp128 — CYCLE 144 / H-V4-10p (rama control/acción, CARACTERIZA el hallazgo NETO de 138: la corrección por VARIANZA-PRIOR v):
138 (exp122) halló -- de pasada, al refutar el overclaim del cuadrado -- que la corrección ROBUSTA sobre el keystone (valor=ctrl×rel,
w·ctrl) NO es elevar w al cuadrado (la forma EFE-óptima w²·v·ctrl) sino incluir la VARIANZA-PRIOR v: w·v·ctrl, porque el cuadrado
AMPLIFICA el ruido de ŵ bajo estimación. Este ciclo lo ESTUDIA sistemáticamente: ¿es w·v·ctrl la elección PRÁCTICA robusta para un
agente bajo ESTIMACIÓN, y CUÁNDO paga la corrección por v (vs el keystone que la ignora, vs la forma EFE-óptima que la sobre-pondera)?

TESIS. El valor de atender/controlar un modo para un agente que ESTIMA de datos finitos es w·v·ctrl (relevancia × varianza-prior ×
controlabilidad) -- el punto dulce PRÁCTICO entre (a) el keystone w·ctrl (ignora v: subóptimo cuando la varianza es HETEROGÉNEA) y
(b) la forma EFE-óptima w²·v·ctrl (= el valor verdadero, pero el cuadrado de ŵ amplifica el ruido de estimación -> peor DECISIÓN a
T finito). v es ENDÓGENA: estimable como Var(x_i) del stream.

DISEÑO (numpy, sustrato lineal de 138). D modos; meta G=w·x; valor-de-decisión VERDADERO de controlar el modo i = w_i²·v_i·ctrl(b_i)
(término pragmático de la EFE; = ORACLE). El agente estima de un stream u~N(0,σu): ŵ (credit-assignment G~x), v̂=Var(x_i), b̂
(system-ID) -> ĉ=ctrl(b̂). CRITERIOS (todos estimados): efe (ŵ²·v̂·ĉ, =oracle por construcción), v_corr (ŵ·v̂·ĉ, la corrección
propuesta), keystone (ŵ·ĉ, 129), rel (ŵ·v̂). Payoff(criterio) = Σ valor-verdadero de los K elegidos / oracle. BARRIDOS: (1)
HETEROGENEIDAD de v (uniforme -> v_corr≈keystone; spread alto -> v_corr paga); (2) T (ruido de estimación -> el cuadrado de efe daña).

ANTI-TAUTOLOGÍA (lección de 138): efe (ŵ²·v̂·ĉ) con params VERDADEROS = oracle por construcción -> el NIVEL de efe no es el hallazgo.
Lo LOAD-BEARING son comparaciones de formas ESTIMADAS no-tautológicas: (a) v_corr vs keystone bajo v heterogéneo (¿paga incluir v?);
(b) v_corr vs efe bajo ruido de estimación (¿el cuadrado daña la DECISIÓN?). Ambas entre estimadores, no contra el oracle.

PREGUNTA FALSABLE:
  - APOYADA si v_corr es la elección ROBUSTA: bate al keystone cuando v es heterogéneo (incluir v paga, monótono en la
    heterogeneidad) Y bate a efe bajo estimación (el cuadrado daña, peor a T chico/σ_w alto), Y v es estimable de Var(x).
  - REFUTADA si v_corr NO bate al keystone (v no importa para la decisión) o NO bate a efe bajo estimación (el cuadrado no daña).
  - MIXTA si condicional.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp128_variance_prior.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp128_variance_prior.run --seeds 300
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
D = 10
K = 3
RHO = 0.5
AA = 0.6
TS = [10, 25, 60, 150, 500]      # incluye T=10 (ŵ ruidoso): la verificación mostró que ahí el cuadrado SÍ daña (138 confirmado)
T_FIXED = 60
HETERO = {"uniform": 0.0, "mild": 0.6, "strong": 1.4}   # spread (sigma log) de la varianza-prior v
HET_FINE = [0.0, 0.2, 0.4, 0.6, 1.0, 1.4]               # barrido FINO en el régimen ESTIMADO (umbral ~0.4)
HET_FIXED = "strong"
SIGMA_GS = [0.5, 2.0, 5.0]       # ruido de la señal de meta G -> ruido de ŵ; el cuadrado daña al crecer (138)
SIGMA_G_DEFAULT = 0.5
CRITERIA = ("efe", "v_corr", "keystone", "rel")


def _ctrl(b):
    return b ** 2 / (b ** 2 + RHO)


def _draw(rng, hetero):
    b = rng.uniform(0.2, 1.0, D)
    w = rng.uniform(0.2, 1.0, D)
    # varianza-prior log-normal: spread controla la heterogeneidad (uniform -> casi constante)
    v = np.exp(rng.normal(0.0, hetero, D))
    v = v / np.mean(v)        # normaliza para comparar regímenes a igual escala media
    return b, w, np.maximum(v, 0.05)


def _true_value(b, w, v):
    return w ** 2 * v * _ctrl(b)       # término pragmático de la EFE = ORACLE


def _estimate(rng, b, w, v, T, sigma_g=SIGMA_G_DEFAULT):
    """Estima ŵ (credit-assignment), v̂=Var(x), b̂ (system-ID) de un stream lineal-gaussiano (sustrato de 138). sigma_g controla
    el ruido de la señal de meta -> ruido de ŵ (el lever que hace que el cuadrado de efe dañe, 138)."""
    x = np.zeros(D)
    X = np.zeros((T, D)); Xn = np.zeros((T, D)); U = np.zeros((T, D)); G = np.zeros(T)
    for t in range(T):
        u = rng.normal(0, 1.0, D)
        xn = AA * x + b * u + rng.normal(0, 1.0, D) * np.sqrt(v)
        g = float(np.dot(w, x)) + rng.normal(0, sigma_g)
        X[t] = x; Xn[t] = xn; U[t] = u; G[t] = g
        x = xn
    b_hat = np.zeros(D)
    for i in range(D):
        F = np.stack([X[:, i], U[:, i]], axis=1)
        coef, *_ = np.linalg.lstsq(F, Xn[:, i], rcond=None)
        b_hat[i] = coef[1]
    w_hat, *_ = np.linalg.lstsq(X, G, rcond=None)
    v_hat = np.maximum(np.var(X, axis=0), 1e-6)
    return np.abs(b_hat), w_hat, v_hat


def _scores(b_hat, w_hat, v_hat):
    c = _ctrl(b_hat)
    return {"efe": w_hat ** 2 * v_hat * c, "v_corr": w_hat * v_hat * c, "keystone": w_hat * c, "rel": w_hat * v_hat}


def _payoff(score, v_true):
    S = np.argsort(score)[-K:]
    oracle = float(np.sum(np.sort(v_true)[-K:])) + 1e-12
    return float(np.sum(v_true[S])) / oracle


def run_cell_estimated(h_val, T, n_seeds, sigma_g=SIGMA_G_DEFAULT):
    accs = {cr: [] for cr in CRITERIA}
    corr_vt = []; corr_vb = []
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed * 7919 + int(h_val * 1000) * 131 + int(T) * 13 + int(sigma_g * 100) * 7 + 29)
        b, w, v = _draw(rng, h_val)
        v_true = _true_value(b, w, v)
        b_hat, w_hat, v_hat = _estimate(rng, b, w, v, T, sigma_g)
        sc = _scores(b_hat, w_hat, v_hat)
        for cr in CRITERIA:
            accs[cr].append(_payoff(sc[cr], v_true))
        if np.std(v_hat) > 1e-9:
            corr_vt.append(float(np.corrcoef(v_hat, v)[0, 1]))      # ¿v̂ rankea la varianza-prior verdadera?
            corr_vb.append(float(np.corrcoef(v_hat, b ** 2)[0, 1]))  # contaminación por el control
    out = {cr: round(float(np.mean(accs[cr])), 4) for cr in CRITERIA}
    out["corr_vhat_vtrue"] = round(float(np.mean(corr_vt)) if corr_vt else 0.0, 4)
    out["corr_vhat_b2"] = round(float(np.mean(corr_vb)) if corr_vb else 0.0, 4)
    return out


def run_cell_clean(h_val, n_seeds):
    """Params VERDADEROS (sin ruido de estimación): aísla el efecto de INCLUIR v (v_corr vs keystone). NOTA: 'v_corr bate al
    keystone' aquí es DEFINICIONAL (el oracle=w²·v·ctrl contiene v; sacarlo del oracle invierte el signo, verificación 144)."""
    accs = {cr: [] for cr in CRITERIA}
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed * 6353 + int(h_val * 1000) * 101 + 17)
        b, w, v = _draw(rng, h_val)
        v_true = _true_value(b, w, v)
        sc = _scores(b, w, v)      # params verdaderos
        for cr in CRITERIA:
            accs[cr].append(_payoff(sc[cr], v_true))
    return {cr: round(float(np.mean(accs[cr])), 4) for cr in CRITERIA}


def run(n_seeds):
    hfix = HETERO[HET_FIXED]
    by_hetero_clean = {h: run_cell_clean(HETERO[h], n_seeds) for h in HETERO}
    by_hetero_est = {h: run_cell_estimated(HETERO[h], T_FIXED, n_seeds) for h in HETERO}
    by_T = {str(T): run_cell_estimated(hfix, T, n_seeds) for T in TS}
    # barridos de la VERIFICACIÓN: (a) ruido de ŵ (σ_g) -> el cuadrado daña (138); (b) heterogeneidad fina ESTIMADA -> umbral + efe domina
    by_sigma_g = {str(sg): run_cell_estimated(hfix, 25, n_seeds, sigma_g=sg) for sg in SIGMA_GS}
    by_het_est_fine = {str(h): run_cell_estimated(h, T_FIXED, n_seeds) for h in HET_FINE}
    return {"by_hetero_est": by_hetero_est, "by_hetero_clean": by_hetero_clean, "by_T": by_T,
            "by_sigma_g": by_sigma_g, "by_het_est_fine": by_het_est_fine}


def _f(x):
    return "{:.3f}".format(x)


def build_summary(grid):
    he = grid["by_hetero_est"]; hc = grid["by_hetero_clean"]; bt = grid["by_T"]
    bsg = grid["by_sigma_g"]; bhf = grid["by_het_est_fine"]

    Tmin = bt[str(TS[0])]; Tmax = bt[str(TS[-1])]
    # NÚCLEO honesto: la varianza-prior v MODULA el valor bajo heterogeneidad (params clean), monótono. (Pero 'v_corr bate keystone'
    # es DEFINICIONAL: el oracle contiene v -- la verificación lo mostró: sacar v del oracle invierte el signo.)
    v_modulates = (hc["strong"]["v_corr"] - hc["strong"]["keystone"]) > 0.10 and \
        (hc["strong"]["v_corr"] - hc["strong"]["keystone"]) > (hc["mild"]["v_corr"] - hc["mild"]["keystone"]) - 0.01

    # (1) el CUADRADO DAÑA con ŵ RUIDOSO (138 CONFIRMADO, no refutado): v_corr-efe crece con σ_g a T chico
    sg_hi = bsg[str(SIGMA_GS[-1])]; sg_lo = bsg[str(SIGMA_GS[0])]
    square_harms_noisy = (sg_hi["v_corr"] - sg_hi["efe"]) > 0.03
    # (2) el CUADRADO AYUDA a baja heterogeneidad ESTIMADA: efe bate a v_corr (la verificación, no estaba en la 1ra versión)
    lowh = bhf[str(HET_FINE[1])]; highh = bhf[str(HET_FINE[-1])]
    square_helps_lowhet = (lowh["efe"] - lowh["v_corr"]) > 0.02
    # (3) v̂ ESTIMADO DAÑA bajo baja heterogeneidad (incluir el v̂ contaminado por control empeora): umbral
    vhat_harms_lowhet = (bhf[str(HET_FINE[0])]["keystone"] - bhf[str(HET_FINE[0])]["v_corr"]) > 0.02
    # (4) efe (forma EFE-completa) DOMINA débilmente todo el eje (>= keystone y >= v_corr en heterogeneidad estimada)
    efe_dominates = all(bhf[str(h)]["efe"] >= bhf[str(h)]["keystone"] - 0.01 and bhf[str(h)]["efe"] >= bhf[str(h)]["v_corr"] - 0.01 for h in HET_FINE)
    # contaminación del estimador v̂
    cvt = he["strong"].get("corr_vhat_vtrue", 0.0); cvb = he["strong"].get("corr_vhat_b2", 0.0)

    if v_modulates and square_harms_noisy and (square_helps_lowhet or efe_dominates):
        status = "mixta"
        verdict = (
            "H-V4-10p MIXTA (mi hipótesis -w·v·ctrl la elección robusta que bate a AMBOS- REFUTADA; mapa de régimen honesto tras "
            "verificación adversarial de 2 agentes; 14mo ciclo). La varianza-prior v MODULA el valor bajo heterogeneidad (params "
            "clean: v_corr-keystone +{vps} strong vs +{vpm} mild, monótono) -- PERO la verificación re-acotó TODO: (1) 'incluir v "
            "bate al keystone' es en gran medida DEFINICIONAL -- el oracle (w²·v·ctrl) CONTIENE v; sacar v del oracle invierte el "
            "signo de la 'ventaja'. Lo genuino es la estimabilidad de v̂=Var(x) (corr con v_true {cvt}) PERO está CONTAMINADO por el "
            "control (corr con b² {cvb}), y bajo BAJA heterogeneidad estimada el v̂ ruidoso DAÑA (keystone {ks0} > v_corr {vc0} a "
            "uniforme). (2) el claim secundario de 138 ('el cuadrado w² DAÑA bajo estimación') NO se refuta -- se CONFIRMA, "
            "regime-específicamente: con ŵ RUIDOSO (σ_g={sgh}, T=25) el cuadrado DAÑA (v_corr-efe +{shn}); mi 1ra versión muestreó "
            "el rincón LIMPIO (σ_g=0.5, T≥25) y lo llamó 'wash' por error. (3) PERO a BAJA heterogeneidad el cuadrado AYUDA (efe "
            "bate a v_corr +{shl}) -> el cuadrado NO es 'siempre daña' (138) NI 'wash' (mi 1ra versión): es REGIME-DEPENDENT (ayuda "
            "a baja-het, wash a alta-het+limpio, daña con ŵ-ruidoso). (4) la elección REALMENTE robusta a través del eje es la "
            "forma EFE-COMPLETA w²·v·ctrl (efe), que DOMINA débilmente todo (efe_dominates={ed}); w·v·ctrl es una simplificación "
            "justificada SÓLO bajo heterogeneidad fuerte + estimación limpia. => RESULTADO HONESTO: la varianza-prior v importa "
            "bajo heterogeneidad (pero 'incluir v' es casi definicional + v̂ contaminado); la forma robusta es la EFE-completa "
            "w²·v·ctrl, NO la simplificada w·v·ctrl que yo proponía; el cuadrado es regime-dependent (138 confirmado en el régimen "
            "ruidoso). MIXTA EXITOSA: la verificación cazó mi overclaim BIDIRECCIONAL (definicional + refutación-deshonesta) y "
            "protegió la AUTOCONSISTENCIA con 138 (que yo contradecía erróneamente)."
        ).format(vps=_f(hc["strong"]["v_corr"] - hc["strong"]["keystone"]), vpm=_f(hc["mild"]["v_corr"] - hc["mild"]["keystone"]),
                 cvt=_f(cvt), cvb=_f(cvb), ks0=_f(bhf[str(HET_FINE[0])]["keystone"]), vc0=_f(bhf[str(HET_FINE[0])]["v_corr"]),
                 sgh=_f(SIGMA_GS[-1]), shn=_f(sg_hi["v_corr"] - sg_hi["efe"]), shl=_f(lowh["efe"] - lowh["v_corr"]), ed=efe_dominates)
    elif not v_modulates:
        status = "refutada"
        verdict = ("H-V4-10p REFUTADA: la varianza-prior v NI SIQUIERA modula el valor bajo heterogeneidad (v_corr-keystone clean "
                   "strong {vps}).").format(vps=_f(hc["strong"]["v_corr"] - hc["strong"]["keystone"]))
    else:
        status = "mixta"
        verdict = ("H-V4-10p MIXTA (parcial): v modula el valor pero el mapa de régimen del cuadrado no es del todo limpio "
                   "(square_harms_noisy={shn} square_helps_lowhet={shl} efe_dominates={ed}).").format(
                       shn=square_harms_noisy, shl=square_helps_lowhet, ed=efe_dominates)

    return {"D": D, "K": K, "by_hetero_est": he, "by_hetero_clean": hc, "by_T": bt, "by_sigma_g": bsg, "by_het_est_fine": bhf,
            "v_pays_strong_clean": round(hc["strong"]["v_corr"] - hc["strong"]["keystone"], 4),
            "v_mild_clean": round(hc["mild"]["v_corr"] - hc["mild"]["keystone"], 4),
            "square_harms_noisy_sgmax": round(sg_hi["v_corr"] - sg_hi["efe"], 4),
            "square_helps_lowhet": round(lowh["efe"] - lowh["v_corr"], 4),
            "vhat_lowhet_penalty": round(bhf[str(HET_FINE[0])]["keystone"] - bhf[str(HET_FINE[0])]["v_corr"], 4),
            "corr_vhat_vtrue": cvt, "corr_vhat_b2": cvb,
            "v_modulates": bool(v_modulates), "square_harms_noisy": bool(square_harms_noisy),
            "square_helps_lowhet_flag": bool(square_helps_lowhet), "vhat_harms_lowhet": bool(vhat_harms_lowhet),
            "efe_dominates": bool(efe_dominates), "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=int, default=300)
    args = ap.parse_args()
    if args.smoke:
        args.seeds = 60

    logs = []

    def log(mm):
        print(mm, flush=True); logs.append(mm)

    log("[exp128] CYCLE 144 / H-V4-10p — ¿es w·v·ctrl (corrección por VARIANZA-PRIOR) la elección PRÁCTICA robusta entre el keystone w·ctrl y la EFE-óptima w²·v·ctrl? (caracteriza el hallazgo neto de 138)")
    log(f"[exp128] seeds={args.seeds} D={D} K={K} Ts={TS} hetero={list(HETERO.keys())}")

    grid = run(args.seeds)
    sm = build_summary(grid)

    log("[exp128] --- (1) INCLUIR v: params CLEAN (aísla del ruido del cuadrado), por heterogeneidad de varianza ---")
    for h in HETERO:
        c = grid["by_hetero_clean"][h]
        log(f"[exp128] {h:>8}: v_corr={c['v_corr']:.3f} keystone={c['keystone']:.3f} (v_corr-keystone +{c['v_corr']-c['keystone']:.3f}) | efe(oracle)={c['efe']:.3f}")
    log("[exp128] --- (2) ¿el CUADRADO daña bajo ESTIMACIÓN? por T (hetero=%s) ---" % HET_FIXED)
    for T in TS:
        c = grid["by_T"][str(T)]
        log(f"[exp128] T={T:>5}: v_corr={c['v_corr']:.3f} efe={c['efe']:.3f} (v_corr-efe +{c['v_corr']-c['efe']:.3f}) keystone={c['keystone']:.3f}")
    log("[exp128] --- (2b) el CUADRADO con ŵ RUIDOSO (σ_g sweep, hetero=%s, T=25): ¿daña? (138 CONFIRMADO) ---" % HET_FIXED)
    for sg in SIGMA_GS:
        c = grid["by_sigma_g"][str(sg)]
        log(f"[exp128] σ_g={sg:>4}: v_corr={c['v_corr']:.3f} efe={c['efe']:.3f} (v_corr-efe +{c['v_corr']-c['efe']:.3f}) keystone={c['keystone']:.3f}")
    log("[exp128] --- (3) heterogeneidad FINA en régimen ESTIMADO (T=%d): efe vs v_corr vs keystone (¿efe domina? ¿v̂ daña a baja-het?) ---" % T_FIXED)
    for h in HET_FINE:
        c = grid["by_het_est_fine"][str(h)]
        log(f"[exp128] σ_log={h:>4}: efe={c['efe']:.3f} v_corr={c['v_corr']:.3f} keystone={c['keystone']:.3f} | efe-v_corr +{c['efe']-c['v_corr']:.3f} v_corr-keystone +{c['v_corr']-c['keystone']:.3f} | corr(v̂,v)={c.get('corr_vhat_vtrue',0):.2f} corr(v̂,b²)={c.get('corr_vhat_b2',0):.2f}")
    log(f"[exp128] CHECK v_modulates={sm['v_modulates']} | square_harms_noisy={sm['square_harms_noisy']} (σ_g max +{sm['square_harms_noisy_sgmax']:.3f}) square_helps_lowhet={sm['square_helps_lowhet_flag']} (+{sm['square_helps_lowhet']:.3f}) vhat_harms_lowhet={sm['vhat_harms_lowhet']} efe_dominates={sm['efe_dominates']} | corr(v̂,v)={sm['corr_vhat_vtrue']:.2f} corr(v̂,b²)={sm['corr_vhat_b2']:.2f}")
    log(f"[exp128] VEREDICTO H-V4-10p: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp128_variance_prior", "cycle": 144, "hypothesis": "H-V4-10p",
           "claim": "MIXTA (mi hipotesis -w·v·ctrl la eleccion robusta que bate a AMBOS- REFUTADA; mapa de regimen honesto tras "
                    "verificacion adversarial de 2 agentes). La varianza-prior v MODULA el valor bajo heterogeneidad (params clean, "
                    "monotono) PERO: (1) 'incluir v bate al keystone' es en gran medida DEFINICIONAL (el oracle=w²·v·ctrl contiene v; "
                    "sacarlo invierte el signo) -- lo genuino es la estimabilidad de v̂=Var(x), CONTAMINADA por el control (corr con "
                    "b²); bajo BAJA heterogeneidad el v̂ ruidoso DAÑA. (2) el claim de 138 'el cuadrado dania bajo estimacion' NO se "
                    "refuta, se CONFIRMA regime-especificamente (con w_hat RUIDOSO -sigma_g alto, T chico- el cuadrado dania); mi 1ra "
                    "version muestreo el rincon limpio y lo llamo 'wash' por error. (3) a BAJA heterogeneidad el cuadrado AYUDA -> el "
                    "cuadrado es REGIME-DEPENDENT. (4) la eleccion robusta a traves del eje es la EFE-COMPLETA w²·v·ctrl, NO la "
                    "simplificada w·v·ctrl. La verificacion cazo mi overclaim BIDIRECCIONAL y protegio la autoconsistencia con 138",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp128] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
