r"""
exp110 — CYCLE 126 / H-V4-9f (rama R-VALOR, GROUNDING del sub-arco 123-125: ρ EARNED, no impuesto): 123-125 caracterizaron
las apuestas decisionales de R-VALOR en 3 ejes (régimen × dirección × presupuesto) PERO con la calibración ρ IMPUESTA
(estimador sintético con corr-ρ). La crítica más fuerte: "ρ es exógeno". Este ciclo lo ANCLA: el estimador es un PROBE
LINEAL AJUSTADO (mínimos cuadrados sobre features), así que ρ EMERGE de la calidad/integridad del estimador, no se impone.

DOS GROUNDINGS:
  (A) ρ ES GANADO Y MONÓTONO EN LA CALIDAD DEL FEATURE. Se barre el ruido σ_sig del feature genuino: a MENOR ruido, MAYOR ρ
      earned y MAYOR payoff bajo escasez. Esto demuestra que ρ no es un knob -- es una consecuencia de la calidad del
      estimador, y el payoff-bajo-escasez de 123 TRACKEA el ρ ganado. (Anti-Goodhart: no se elige un σ; se muestra la curva.)
  (B) LA ANTI-CALIBRACIÓN PELIGROSA SE GANA DE UNA CORRELACIÓN ESPURIA + SHIFT. Un probe que aprende un feature limpio en
      train que se INVIERTE en deployment (distribution shift -- núcleo de R-INTERVENCIÓN y de la fragilidad 115-118
      "confiadamente equivocado") gana ρ<0 (anti-calibrado) y es CATASTRÓFICO bajo abundancia, pero BUDGET-FRÁGIL (125).

CONTEXTO. Une tres hilos: apuestas decisionales (123-125) + fragilidad "confiadamente equivocado" (115-119) + R-INTERVENCIÓN
(la señal espuria sólo se delata bajo cambio de distribución). El probe se entrena BALANCEADO (q_train=0.5) y se DESPLIEGA
bajo regímenes de test escaso/abundante.

DISEÑO (numpy, probe por mínimos cuadrados exacto). goodness g~Bernoulli(q). Features:
  - GENUINO   x_sig = g + N(0, σ_sig)                          (predice g en train Y en test; σ_sig = calidad)
  - ESPURIO   x_dec = g + N(0, σ_dec) en TRAIN; (1−g) + N(0, σ_dec) en TEST   (predice en train, se INVIERTE en test)
(A) probe ROBUSTO: fit sobre [x_sig] variando σ_sig. (B) probe ESPURIO: fit sobre [x_sig, x_dec] con x_dec más limpio en
train (σ_dec<σ_sig_fijo) -> el fit se apoya en el espurio -> el shift lo vuelve ANTI-calibrado. ρ EARNED = corr(e_test,
g_test). DECISIÓN: someter top-m por e_test. payoff = #buenos / min(m, #buenos).

PREGUNTA FALSABLE:
  - APOYADA si: (A) el ρ EARNED del probe robusto CRECE al bajar σ_sig Y el payoff bajo escasez TRACKEA ese ρ (mejor feature
    -> más ρ -> paga más bajo escasez: reproduce 123 con ρ ganado); (B) el probe ESPURIO gana ρ<0 (anti-calibrado) por el
    shift y es CATASTRÓFICO bajo abundancia pero BUDGET-FRÁGIL (reproduce 124-125 con ρ ganado). => las apuestas decisionales
    NO son artefacto del ρ impuesto: ρ se gana de la calidad/integridad del estimador, y la anti-calibración peligrosa surge
    de correlación espuria + shift.
  - REFUTADA si el ρ earned no crece con la calidad / el payoff no lo trackea, o el espurio NO se vuelve anti-calibrado.
  - MIXTA en otro caso.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp110_earned_calibration.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp110_earned_calibration.run            # FULL
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
SIG_SWEEP = [0.4, 1.0, 2.0]        # calidad del feature genuino: bajo ruido (bueno) -> alto ruido (malo)
MS = [3, 20]                       # presupuesto ajustado vs moderado (reusa la lección de 125)
QS = {"escaso": 0.08, "abundante": 0.9}
SIG_SIG_ESP = 1.2                  # ruido del genuino en el arm espurio (fijo; peor que el espurio en train)
SIG_DEC = 0.4                      # ruido del espurio en TRAIN (limpio: el fit se apoya en él)
N_TRAIN = 400
N_TEST = 60


def _fit_probe(X, y):
    """probe lineal por mínimos cuadrados: y ≈ [1|X] w. Cierre exacto, determinista."""
    A = np.concatenate([np.ones((X.shape[0], 1)), X], axis=1)
    w, *_ = np.linalg.lstsq(A, y, rcond=None)
    return w


def _apply(w, X):
    A = np.concatenate([np.ones((X.shape[0], 1)), X], axis=1)
    return A @ w


def _corr(a, b):
    if np.std(a) < 1e-9 or np.std(b) < 1e-9:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def _decide(e_te, g_te, m):
    top = np.argsort(e_te)[-min(m, len(e_te)):]
    reward = float(np.sum(g_te[top]))
    oracle = float(min(m, np.sum(g_te)))
    return reward / oracle if oracle > 0 else 0.0


def run_robust(sig_sig, q_test, m, n_seeds):
    """probe robusto: feature genuino con ruido sig_sig. Devuelve (payoff, ρ_earned)."""
    payoffs, rhos = [], []
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed * 7919 + int(sig_sig * 100) * 17 + int(q_test * 100) * 31 + m * 101 + 7)
        g_tr = (rng.random(N_TRAIN) < 0.5).astype(float)
        x_tr = (g_tr + rng.normal(0.0, sig_sig, size=N_TRAIN)).reshape(-1, 1)
        g_te = (rng.random(N_TEST) < q_test).astype(float)
        x_te = (g_te + rng.normal(0.0, sig_sig, size=N_TEST)).reshape(-1, 1)
        w = _fit_probe(x_tr, g_tr)
        e_te = _apply(w, x_te)
        rhos.append(_corr(e_te, g_te))
        payoffs.append(_decide(e_te, g_te, m))
    return round(float(np.mean(payoffs)), 4), round(float(np.mean(rhos)), 4)


def run_spurious(q_test, m, n_seeds):
    """probe espurio: genuino (ruidoso) + espurio (limpio en train, INVERTIDO en test). Devuelve (payoff, ρ_earned)."""
    payoffs, rhos = [], []
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed * 7919 + int(q_test * 100) * 31 + m * 101 + 50003 + 7)
        g_tr = (rng.random(N_TRAIN) < 0.5).astype(float)
        x_sig_tr = g_tr + rng.normal(0.0, SIG_SIG_ESP, size=N_TRAIN)
        x_dec_tr = g_tr + rng.normal(0.0, SIG_DEC, size=N_TRAIN)               # espurio limpio en train
        X_tr = np.stack([x_sig_tr, x_dec_tr], axis=1)
        g_te = (rng.random(N_TEST) < q_test).astype(float)
        x_sig_te = g_te + rng.normal(0.0, SIG_SIG_ESP, size=N_TEST)
        x_dec_te = (1.0 - g_te) + rng.normal(0.0, SIG_DEC, size=N_TEST)        # espurio INVERTIDO en deployment
        X_te = np.stack([x_sig_te, x_dec_te], axis=1)
        w = _fit_probe(X_tr, g_tr)
        e_te = _apply(w, X_te)
        rhos.append(_corr(e_te, g_te))
        payoffs.append(_decide(e_te, g_te, m))
    return round(float(np.mean(payoffs)), 4), round(float(np.mean(rhos)), 4)


def run(n_seeds):
    grid = {"robusto": {}, "espurio": {}}
    for sig in SIG_SWEEP:
        grid["robusto"][str(sig)] = {}
        for qn, q in QS.items():
            grid["robusto"][str(sig)][qn] = {}
            for m in MS:
                p, r = run_robust(sig, q, m, n_seeds)
                grid["robusto"][str(sig)][qn][str(m)] = {"payoff": p, "rho": r}
    for qn, q in QS.items():
        grid["espurio"][qn] = {}
        for m in MS:
            p, r = run_spurious(q, m, n_seeds)
            grid["espurio"][qn][str(m)] = {"payoff": p, "rho": r}
    return grid


def _f(x):
    return "{:.3f}".format(x)


def build_summary(grid):
    tight, mod = str(MS[0]), str(MS[1])
    sig_best, sig_worst = str(SIG_SWEEP[0]), str(SIG_SWEEP[-1])

    # (A) ρ earned y payoff-escaso crecen al mejorar el feature (bajar σ)
    rho_best = grid["robusto"][sig_best]["escaso"][tight]["rho"]
    rho_worst = grid["robusto"][sig_worst]["escaso"][tight]["rho"]
    pay_best = grid["robusto"][sig_best]["escaso"][tight]["payoff"]
    pay_worst = grid["robusto"][sig_worst]["escaso"][tight]["payoff"]
    rho_monotone = rho_best > rho_worst + 0.10                        # mejor feature -> más ρ earned
    payoff_tracks_rho = pay_best > pay_worst + 0.20                   # ...y más payoff bajo escasez
    best_pays_scarce = (rho_best > 0.4) and (pay_best > 0.5)          # el buen estimador SÍ paga bajo escasez (123)

    # (B) el espurio gana ρ<0 y es catastrófico-pero-budget-frágil bajo abundancia (124-125)
    esp_rho = grid["espurio"]["abundante"][tight]["rho"]
    esp_pay_tight = grid["espurio"]["abundante"][tight]["payoff"]
    esp_pay_mod = grid["espurio"]["abundante"][mod]["payoff"]
    espurio_anticalibrated = esp_rho < -0.1
    espurio_catastrophic = esp_pay_tight < 0.5
    espurio_budget_fragile = (esp_pay_mod - esp_pay_tight) > 0.3

    groundingA = rho_monotone and payoff_tracks_rho and best_pays_scarce
    groundingB = espurio_anticalibrated and espurio_catastrophic and espurio_budget_fragile

    if groundingA and groundingB:
        status = "apoyada"
        verdict = ("H-V4-9f APOYADA (ρ EARNED ancla 123-125): (A) el ρ EARNED del probe robusto CRECE con la calidad del "
                   "feature (σ={sb}: ρ={rb}, paga-escasez={pb}) vs (σ={sw}: ρ={rw}, paga={pw}) -- el payoff bajo escasez "
                   "TRACKEA el ρ ganado (reproduce 123: mejor estimador -> más ρ -> paga más bajo escasez; ρ NO es un knob). "
                   "(B) el probe ESPURIO -- que aprendió un feature limpio en train que se INVIERTE en deployment -- GANA ρ="
                   "{er}<0 (anti-calibrado) y es CATASTRÓFICO bajo abundancia (payoff m{tm}={ept}) pero BUDGET-FRÁGIL "
                   "(m{mm}={epm}) (reproduce 124-125 con ρ ganado). => las apuestas decisionales 123-125 NO son artefacto del "
                   "ρ impuesto: ρ se gana de la calidad/integridad del estimador, y la anti-calibración peligrosa surge "
                   "NATURALMENTE de correlación ESPURIA + cambio de distribución (R-INTERVENCIÓN + fragilidad 115-118).").format(
                       sb=sig_best, rb=_f(rho_best), pb=_f(pay_best), sw=sig_worst, rw=_f(rho_worst), pw=_f(pay_worst),
                       er=_f(esp_rho), tm=tight, ept=_f(esp_pay_tight), mm=mod, epm=_f(esp_pay_mod))
    elif not groundingB or not best_pays_scarce:
        status = "refutada"
        verdict = ("H-V4-9f REFUTADA: el ρ earned no ancla el ρ impuesto. (A) robusto: ρ {rw}->{rb}, paga-escasez={bps}; "
                   "(B) espurio ρ={er} (anti? {ea}). Si el espurio no gana ρ<0 o el buen feature no paga bajo escasez, el "
                   "grounding falla.").format(rw=_f(rho_worst), rb=_f(rho_best), bps=best_pays_scarce, er=_f(esp_rho),
                                              ea=espurio_anticalibrated)
    else:
        status = "mixta"
        verdict = ("H-V4-9f MIXTA: grounding parcial -- A(monótono={mo}, trackea={tr}, paga={bp}) B(anti={an}, catastróf={ca}"
                   ", frágil={fr}).").format(mo=rho_monotone, tr=payoff_tracks_rho, bp=best_pays_scarce,
                                             an=espurio_anticalibrated, ca=espurio_catastrophic, fr=espurio_budget_fragile)

    return {"grid": grid, "rho_best": rho_best, "rho_worst": rho_worst, "pay_best": pay_best, "pay_worst": pay_worst,
            "esp_rho_abund": esp_rho, "esp_pay_abund_tight": esp_pay_tight, "esp_pay_abund_mod": esp_pay_mod,
            "rho_monotone": bool(rho_monotone), "payoff_tracks_rho": bool(payoff_tracks_rho),
            "best_pays_scarce": bool(best_pays_scarce), "espurio_anticalibrated": bool(espurio_anticalibrated),
            "espurio_catastrophic": bool(espurio_catastrophic), "espurio_budget_fragile": bool(espurio_budget_fragile),
            "groundingA": bool(groundingA), "groundingB": bool(groundingB), "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=int, default=200)
    args = ap.parse_args()
    if args.smoke:
        args.seeds = 50

    logs = []

    def log(mm):
        print(mm, flush=True); logs.append(mm)

    log("[exp110] CYCLE 126 / H-V4-9f — ρ EARNED (probe ajustado): ¿ancla 123-125? (A) ρ monótono en calidad (B) espurio->anti-calibrado por shift")
    log(f"[exp110] seeds={args.seeds} sig_sweep={SIG_SWEEP} ms={MS} qs={QS} sig_sig_esp={SIG_SIG_ESP} sig_dec={SIG_DEC} n_train={N_TRAIN} n_test={N_TEST}")

    grid = run(args.seeds)
    sm = build_summary(grid)

    log("[exp110] (A) probe ROBUSTO (ρ earned crece al bajar σ; payoff bajo escasez trackea ρ):")
    for sig in SIG_SWEEP:
        for qn in QS:
            row = " ".join(f"m{m}:pay={grid['robusto'][str(sig)][qn][str(m)]['payoff']:.3f},ρ={grid['robusto'][str(sig)][qn][str(m)]['rho']:+.3f}" for m in MS)
            log(f"[exp110]    σ={sig:>4} q={qn:>10}: {row}")
    log("[exp110] (B) probe ESPURIO (gana ρ<0 por shift; catastrófico bajo abundancia pero budget-frágil):")
    for qn in QS:
        row = " ".join(f"m{m}:pay={grid['espurio'][qn][str(m)]['payoff']:.3f},ρ={grid['espurio'][qn][str(m)]['rho']:+.3f}" for m in MS)
        log(f"[exp110]    q={qn:>10}: {row}")
    log(f"[exp110] groundingA(ρ ganado ancla 123)={sm['groundingA']} groundingB(espurio->anti ancla 124-125)={sm['groundingB']}")
    log(f"[exp110] VEREDICTO H-V4-9f: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp110_earned_calibration", "cycle": 126, "hypothesis": "H-V4-9f",
           "claim": "con un estimador APRENDIDO (probe lineal ajustado, rho EARNED no impuesto) se anclan las apuestas "
                    "decisionales 123-125: (A) el rho earned crece con la calidad del feature y el payoff bajo escasez lo "
                    "trackea (rho no es un knob; reproduce 123); (B) un probe que aprendio un feature ESPURIO que se invierte "
                    "en deployment gana rho<0 (anti-calibrado) y es catastrofico-pero-budget-fragil bajo abundancia "
                    "(reproduce 124-125) -> la anti-calibracion peligrosa surge de correlacion espuria + shift "
                    "(R-INTERVENCION + fragilidad 115-118)",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp110] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
