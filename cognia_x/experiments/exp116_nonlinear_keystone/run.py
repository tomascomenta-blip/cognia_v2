r"""
exp116 — CYCLE 132 / H-V4-10f (rama control/acción, ROBUSTEZ del keystone 129 a NO-LINEALIDAD; versión HONESTA tras
VERIFICACIÓN ADVERSARIAL): ¿sobrevive el keystone (el control reconstruye R-VALOR = controlabilidad × relevancia) a control
NO-LINEAL saturante? La respuesta verificada: el PRINCIPIO sobrevive, PERO la controlabilidad debe ser de ALCANCE/ESFUERZO --
la PENDIENTE LOCAL (b̂ lineal, la del keystone 129) es CIEGA a la saturación y FALLA.

HISTORIA HONESTA (registrada): una 1ra versión hardcodeaba el ancho del probe σ_p=0.4 y concluía "APOYADA: la pendiente local
basta, el keystone es robusto tal cual". Una VERIFICACIÓN ADVERSARIAL (3 agentes) la corrigió: σ_p=0.4 NO es local respecto de
τ=0.3 -- ahí b̂ YA siente la saturación (b̂_sat≈0.50 vs b̂_ctrl≈0.99), es un PROXY CRUDO DE ALCANCE, no pendiente local; esa
"reach-awareness encubierta" salvaba a valor_lin. Con un probe GENUINAMENTE local (σ_p≪τ) valor_lin COLAPSA a nivel relevancia
(y por debajo si ganancia y alcance anti-correlacionan), y 100× más datos NO lo rescata (es ceguera, no ruido). valor_eff
(alcance al esfuerzo U_max) es robustamente óptimo en TODO σ_p.

DINÁMICA NO-LINEAL. x_i' = a·x_i + b_i·τ_i·tanh(u_i/τ_i) + ruido (efecto satura en ±b_i·τ_i). Controlabilidad VERDADERA =
ALCANCE b_i·τ_i (cuán lejos podés empujar), NO la pendiente local b_i.

DISEÑO (numpy). 8 modos en cuadrantes; capacidad K=2; control ORACLE (grid-search del u óptimo no-lineal) para AISLAR la
ASIGNACIÓN. Se barre el ANCHO DEL PROBE σ_p (local σ_p≪τ -> ancho σ_p≳τ) en 3 regímenes:
  - "nosat":  sin saturación (τ grande) -> todos los criterios coinciden.
  - "sat":    saturación fuerte (τ_chico=0.3): los modos SATURANTE+REL tienen pendiente local 1 pero alcance bajo.
  - "break":  ganancia/alcance ANTI-correlacionados: los SATURANTE+REL tienen ganancia ALTA (b=2) y alcance BAJO (τ=0.2) ->
              la pendiente local los PREFIERE activamente.
Criterios: valor_lin (w·b̂²/(b̂²+ρ), b̂ de un probe de ancho σ_p), valor_eff (w·R̂²/(R̂²+ρ), R̂=alcance al esfuerzo U_max,
σ_p-INDEPENDIENTE), relevancia (w), prediccion (varianza). perf = fracción del beneficio ALCANZABLE (vs oracle por alcance).

PREGUNTA FALSABLE:
  - APOYADA si la pendiente LOCAL basta (valor_lin robusto en todo σ_p incl. local) -> keystone robusto tal cual.
  - REFUTADA si el keystone NO sobrevive de ninguna forma (ni valor_eff).
  - MIXTA (esperado/verificado): el PRINCIPIO sobrevive con controlabilidad de ALCANCE (valor_eff robusto en todo σ_p) pero la
    pendiente LOCAL es CIEGA a la saturación -- valor_lin es probe-width-contingente: con probe local colapsa a relevancia
    (régimen sat) o por debajo (régimen break). => bajo no-linealidad la controlabilidad del keystone debe ser de ALCANCE/
    ESFUERZO (generaliza la controlabilidad-descontada-por-costo de 130), NO la pendiente local.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp116_nonlinear_keystone.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp116_nonlinear_keystone.run            # FULL
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
U_MAX = 3.0
TAU_BIG = 5.0
N_PROBE = 3000        # alto para que el b̂ a probe local sea SEÑAL, no ruido (la ceguera no es de muestreo)
EVAL = 300
UGRID = np.linspace(-U_MAX, U_MAX, 41)
SIGMAS = [0.05, 0.2, 0.4, 1.5]      # ancho del probe: LOCAL (≪τ) -> ANCHO (≳τ)
REGIMES = ("nosat", "sat", "break")
ARMS = ("valor_lin", "valor_eff", "relevancia", "prediccion")


def _g(b, tau, u):
    return b * tau * np.tanh(u / tau)


def _modes(rng, regime):
    # (b ganancia/pendiente-local, tau saturación, w relevancia); 2 por tipo
    if regime == "nosat":
        sat = (1.0, TAU_BIG)           # "saturante+rel" sin saturación de verdad
    elif regime == "sat":
        sat = (1.0, 0.3)               # pendiente local 1, alcance 0.3 (bajo)
    else:  # break: ganancia ALTA, alcance BAJO -> la pendiente local los prefiere
        sat = (2.0, 0.2)               # pendiente local 2, alcance 0.4
    specs = [(1.0, TAU_BIG, 1.0), (1.0, TAU_BIG, 1.0),        # CTRL-REAL + REL (alcance alto: los que valen)
             (sat[0], sat[1], 1.0), (sat[0], sat[1], 1.0),    # SATURANTE + REL (alcance bajo)
             (1.0, TAU_BIG, 0.0), (1.0, TAU_BIG, 0.0),        # CTRL-REAL + IRREL
             (0.0, TAU_BIG, 0.0), (0.0, TAU_BIG, 0.0)]        # INCONTROLABLES (ruidosos)
    b = np.array([s[0] for s in specs]); tau = np.array([s[1] for s in specs]); w = np.array([s[2] for s in specs])
    s = np.where(b > 0, 1.0, 3.0)
    order = rng.permutation(len(specs))
    return b[order], tau[order], w[order], s[order]


def _estimate(rng, b, tau, s, sigma_p):
    """b̂ = pendiente del probe de ancho sigma_p (LOCAL si sigma_p≪τ); R̂ = alcance al esfuerzo U_max (σ_p-independiente)."""
    D = len(b); bhat = np.zeros(D); Rhat = np.zeros(D); var = np.zeros(D)
    for i in range(D):
        x = rng.normal(0, 1, N_PROBE); u = rng.normal(0, sigma_p, N_PROBE)
        xp = AA * x + _g(b[i], tau[i], u) + rng.normal(0, s[i], N_PROBE)
        coef, *_ = np.linalg.lstsq(np.stack([x, u], axis=1), xp, rcond=None)
        bhat[i] = float(coef[1]); var[i] = np.var(xp)
        xa = rng.normal(0, 1, N_PROBE); ua = rng.choice([-U_MAX, U_MAX], N_PROBE)
        xpa = AA * xa + _g(b[i], tau[i], ua) + rng.normal(0, s[i], N_PROBE)
        Rhat[i] = float(np.mean(np.abs(xpa - AA * xa)))
    return bhat, Rhat, var


def _obj(modeled, b, tau, target, x, noise):
    D = len(b); o = np.zeros(D)
    for i in range(D):
        if i in modeled:
            eff = _g(b[i], tau[i], UGRID)[None, :]
            cost = ((AA * x[:, i] - target[:, i])[:, None] + eff) ** 2 + RHO * (UGRID[None, :] ** 2)
            u = UGRID[np.argmin(cost, axis=1)]
        else:
            u = np.zeros(target.shape[0])
        xp = AA * x[:, i] + _g(b[i], tau[i], u) + noise[:, i]
        o[i] = float(np.mean((xp - target[:, i]) ** 2 + RHO * u ** 2))
    return o


def run_cell(regime, sigma_p, n_seeds):
    accs = {a: [] for a in ARMS}
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed * 8123 + int(sigma_p * 1000) * 7 + {"nosat": 1, "sat": 2, "break": 3}[regime] * 90001 + 5)
        b, tau, w, s = _modes(rng, regime)
        D = len(b)
        bhat, Rhat, var = _estimate(rng, b, tau, s, sigma_p)
        target = rng.normal(0, 1, size=(EVAL, D)); xe = rng.normal(0, 1, size=(EVAL, D)); noise = rng.normal(0, 1, size=(EVAL, D))
        obj_pass = _obj(set(), b, tau, target, xe, noise)
        R_true = np.abs(_g(b, tau, U_MAX))
        true_val = w * R_true ** 2 / (R_true ** 2 + RHO)
        obj_oracle = _obj(set(np.argsort(true_val)[-2:].tolist()), b, tau, target, xe, noise)
        den = float(np.sum(w * (obj_pass - obj_oracle))) + 1e-9
        scores = {"valor_lin": w * bhat ** 2 / (bhat ** 2 + RHO), "valor_eff": w * Rhat ** 2 / (Rhat ** 2 + RHO),
                  "relevancia": w + rng.normal(0, 1e-9, size=D), "prediccion": var}
        for arm in ARMS:
            modeled = set(np.argsort(scores[arm])[-2:].tolist())
            obj_m = _obj(modeled, b, tau, target, xe, noise)
            accs[arm].append(max(0.0, float(np.sum(w * (obj_pass - obj_m))) / den))
    return {a: round(float(np.mean(accs[a])), 4) for a in ARMS}


def run(n_seeds):
    return {rg: {str(sg): run_cell(rg, sg, n_seeds) for sg in SIGMAS} for rg in REGIMES}


def _f(x):
    return "{:.3f}".format(x)


def build_summary(grid):
    loc, wide = str(SIGMAS[0]), str(SIGMAS[-1])
    # valor_eff robusto en TODO σ_p y régimen
    eff_min = min(grid[rg][str(sg)]["valor_eff"] for rg in REGIMES for sg in SIGMAS)
    # valor_lin a probe LOCAL en saturación: colapsa hacia relevancia
    lin_loc_sat = grid["sat"][loc]["valor_lin"]; rel_sat = grid["sat"][loc]["relevancia"]
    lin_wide_sat = grid["sat"][wide]["valor_lin"]
    lin_loc_break = grid["break"][loc]["valor_lin"]; rel_break = grid["break"][loc]["relevancia"]
    eff_loc_sat = grid["sat"][loc]["valor_eff"]
    probe_contingent = round(lin_wide_sat - lin_loc_sat, 4)        # cuánto sube valor_lin al ENSANCHAR el probe

    eff_robust = eff_min > 0.85                                    # reach-aware óptimo en todo σ_p/régimen
    lin_blind_local = lin_loc_sat < rel_sat + 0.06                # a probe local valor_lin ~ relevancia (ciego)
    lin_probe_contingent = probe_contingent > 0.12               # su "robustez" depende del ancho del probe
    lin_harmful_break = lin_loc_break < rel_break - 0.04          # con anti-correlación, valor_lin PEOR que relevancia

    if eff_robust and lin_blind_local and lin_probe_contingent:
        status = "mixta"
        verdict = ("H-V4-10f MIXTA (el keystone sobrevive a la no-linealidad SÓLO con controlabilidad de ALCANCE; la pendiente "
                   "LOCAL es ciega): la controlabilidad de ALCANCE/ESFUERZO (valor_eff = alcance al esfuerzo U_max) es "
                   "robustamente óptima en TODO ancho de probe y régimen (min {em}). En cambio la PENDIENTE LOCAL del keystone "
                   "129 (valor_lin) es CIEGA a la saturación: a probe GENUINAMENTE LOCAL (σ_p={lo}) en saturación colapsa a "
                   "{ll} ≈ relevancia ({rs}); su aparente robustez es PROBE-WIDTH-CONTINGENTE (sube +{pc} al ensanchar el "
                   "probe a σ_p={wi} -- ahí b̂ deja de ser local y siente el alcance encubiertamente). Y con ganancia/alcance "
                   "ANTI-correlacionados (régimen break: pendiente alta, alcance bajo) valor_lin a probe local cae a {lb} -- "
                   "PEOR que relevancia ({rb}): la pendiente local PREFIERE activamente los modos inalcanzables. => bajo "
                   "control NO-LINEAL la controlabilidad del keystone debe ser de ALCANCE/ESFUERZO (cuán lejos podés empujar "
                   "al esfuerzo de control), NO la pendiente local; generaliza la controlabilidad-descontada-por-costo de 130 "
                   "(la saturación es la forma no-lineal del costo). El PRINCIPIO valor=ctrl×rel sobrevive; su factor de "
                   "controlabilidad NO es lineal.").format(
                       em=_f(eff_min), lo=SIGMAS[0], ll=_f(lin_loc_sat), rs=_f(rel_sat), pc=_f(probe_contingent),
                       wi=SIGMAS[-1], lb=_f(lin_loc_break), rb=_f(rel_break))
    elif not eff_robust:
        status = "refutada"
        verdict = ("H-V4-10f REFUTADA: ni la controlabilidad de alcance sobrevive (valor_eff min {em} <= 0.85) -> el keystone "
                   "no sobrevive a la no-linealidad.").format(em=_f(eff_min))
    else:
        status = "apoyada"
        verdict = ("H-V4-10f APOYADA: la pendiente LOCAL basta aun a probe local (valor_lin sat-local {ll} no colapsa a "
                   "relevancia {rs}; contingencia {pc}<=0.12) -> el keystone es robusto a la no-linealidad sin reach-aware.").format(
                       ll=_f(lin_loc_sat), rs=_f(rel_sat), pc=_f(probe_contingent))

    return {"grid": grid, "eff_min": eff_min, "lin_loc_sat": lin_loc_sat, "rel_sat": rel_sat, "lin_wide_sat": lin_wide_sat,
            "probe_contingent": probe_contingent, "lin_loc_break": lin_loc_break, "rel_break": rel_break,
            "eff_loc_sat": eff_loc_sat, "eff_robust": bool(eff_robust), "lin_blind_local": bool(lin_blind_local),
            "lin_probe_contingent": bool(lin_probe_contingent), "lin_harmful_break": bool(lin_harmful_break),
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

    log("[exp116] CYCLE 132 / H-V4-10f (honesto) — ¿sobrevive el keystone a control NO-LINEAL? controlabilidad de ALCANCE (eff) vs PENDIENTE LOCAL (lin), barriendo el ancho del probe σ_p")
    log(f"[exp116] seeds={args.seeds} a={AA} rho={RHO} U_max={U_MAX} sigmas={SIGMAS} regimes={REGIMES} n_probe={N_PROBE}")

    grid = run(args.seeds)
    sm = build_summary(grid)

    for rg in REGIMES:
        for sg in SIGMAS:
            row = grid[rg][str(sg)]
            log(f"[exp116] {rg:>6} σ_p={sg:>4}: lin={row['valor_lin']:.3f} eff={row['valor_eff']:.3f} relev={row['relevancia']:.3f} pred={row['prediccion']:.3f}")
    log(f"[exp116] valor_eff min (todo σ_p/régimen)={sm['eff_min']:.3f} | valor_lin SAT: local(σ{SIGMAS[0]})={sm['lin_loc_sat']:.3f} vs relev {sm['rel_sat']:.3f} -> ancho(σ{SIGMAS[-1]})={sm['lin_wide_sat']:.3f} (contingencia +{sm['probe_contingent']:.3f})")
    log(f"[exp116] BREAK local: valor_lin={sm['lin_loc_break']:.3f} vs relevancia {sm['rel_break']:.3f} (¿lin peor? {sm['lin_harmful_break']})")
    log(f"[exp116] eff_robust={sm['eff_robust']} lin_blind_local={sm['lin_blind_local']} lin_probe_contingent={sm['lin_probe_contingent']}")
    log(f"[exp116] VEREDICTO H-V4-10f: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp116_nonlinear_keystone", "cycle": 132, "hypothesis": "H-V4-10f",
           "claim": "el keystone (valor=controlabilidad×relevancia) SOBREVIVE a control no-lineal saturante pero SOLO con "
                    "controlabilidad de ALCANCE/ESFUERZO (valor_eff robustamente optimo en todo ancho de probe y regimen); la "
                    "PENDIENTE LOCAL del keystone 129 (valor_lin) es CIEGA a la saturacion -- a probe genuinamente local "
                    "colapsa a nivel relevancia (regimen sat) o por debajo (regimen break, ganancia/alcance anti-correlados); "
                    "su aparente robustez es probe-width-contingente -> la controlabilidad debe ser de alcance, generaliza la "
                    "controlabilidad-descontada-por-costo de 130",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp116] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
