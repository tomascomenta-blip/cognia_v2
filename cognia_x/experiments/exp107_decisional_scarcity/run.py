r"""
exp107 — CYCLE 123 / H-V4-9c (rama R-VALOR, CAPSTONE POSITIVO en abstracción controlada): 121 re-localizó el valor de
R-VALOR como DECISIONAL; 122 NO pudo demostrarlo positivamente en el toy (el submission SATURA por correctos abundantes, o
la temp alta desestabiliza) y diagnosticó que el payoff decisional necesita ESCASEZ de buenas opciones. Este ciclo LANDA el
capstone positivo en una abstracción NUMPY CONTROLADA (sin la inestabilidad del torch): demuestra que la CALIBRACIÓN del
selector PAGA en una decisión EXACTAMENTE bajo ESCASEZ, y SATURA bajo abundancia.

CONTEXTO. Cierra el arco con la demostración positiva que el toy no permitió: aísla los dos ejes (calibración ρ del
selector × escasez q de buenas opciones) que el lazo torch confundía.

DISEÑO (numpy). n ítems, fracción q "buenos" (valor 1) y 1−q "malos" (valor 0) -> q = abundancia (1−q = escasez). Estimador
de valor con CALIBRACIÓN ρ (corr con la bondad): e = ρ·z_bueno + sqrt(1−ρ²)·ruido. DECISIÓN: someter las top-m por e a
recompensa externa. payoff = #buenos sometidos / min(m, #buenos) (vs oracle). Se barre ρ (calibración) × q (abundancia).

PREGUNTA FALSABLE:
  - APOYADA si bajo ESCASEZ (q bajo) el payoff CRECE fuerte con la calibración ρ (payoff(ρ alto) − payoff(ρ=0) > margen:
    la calibración PAGA), Y bajo ABUNDANCIA (q alto) el payoff SATURA (≈1, casi independiente de ρ: la calibración no
    importa). => el payoff DECISIONAL de la calibración del selector se manifiesta exactamente bajo ESCASEZ -- demuestra
    POSITIVAMENTE la re-localización de 121 (R-VALOR es decisional) y confirma el diagnóstico de 122 (necesita escasez).
  - REFUTADA si la calibración no paga bajo escasez (o paga igual bajo abundancia) -> la re-localización no se sostiene.
  - MIXTA en otro caso.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp107_decisional_scarcity.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp107_decisional_scarcity.run            # FULL
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
RHOS = [0.0, 0.3, 0.6, 0.9]
QS = {"escaso": 0.08, "abundante": 0.9}


def run_cell(n, m, q, rho, n_seeds):
    payoffs = []
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed * 877 + int(q * 100) * 13 + int(rho * 100) * 7 + 3)
        good = (rng.random(n) < q).astype(float)               # bondad binaria (base rate q)
        z = good - q                                           # bondad centrada
        noise = rng.normal(0.0, 1.0, size=n)
        e = rho * (z / (np.std(z) + 1e-9)) + np.sqrt(max(0.0, 1.0 - rho ** 2)) * noise   # estimador con corr≈ρ
        top = np.argsort(e)[-min(m, n):]
        reward = float(np.sum(good[top]))
        oracle = float(min(m, np.sum(good)))
        payoffs.append(reward / oracle if oracle > 0 else 0.0)
    return round(float(np.mean(payoffs)), 4)


def run(n, m, n_seeds):
    grid = {}
    for qn, q in QS.items():
        grid[qn] = {str(rho): run_cell(n, m, q, rho, n_seeds) for rho in RHOS}
    return grid


def _f(x):
    return "{:.3f}".format(x)


def build_summary(grid):
    lo, hi = RHOS[0], RHOS[-1]
    scarce = grid["escaso"]
    abund = grid["abundante"]
    scarce_gain = round(scarce[str(hi)] - scarce[str(lo)], 4)        # cuánto paga la calibración bajo escasez
    abund_gain = round(abund[str(hi)] - abund[str(lo)], 4)          # cuánto paga bajo abundancia
    abund_saturates = abund[str(lo)] >= 0.9                         # bajo abundancia el payoff ya es alto sin calibración

    GAIN = 0.10
    ABUND_TOL = 0.10
    calib_pays_scarce = scarce_gain > GAIN
    calib_irrelevant_abund = (abund_gain <= ABUND_TOL) and abund_saturates

    if calib_pays_scarce and calib_irrelevant_abund:
        status = "apoyada"
        verdict = ("H-V4-9c APOYADA: el payoff DECISIONAL de la CALIBRACIÓN del selector se manifiesta EXACTAMENTE bajo "
                   "ESCASEZ. Bajo ESCASO (q={qs}): payoff sube de {sl} (ρ=0) a {sh} (ρ={hi}) -- la calibración PAGA "
                   "(+{sg}). Bajo ABUNDANTE (q={qa}): payoff {al}->{ah} (Δ {ag}) -- SATURA cerca de 1, la calibración no "
                   "importa (cualquier selector acierta). => DEMUESTRA POSITIVAMENTE la re-localización de 121 (R-VALOR es "
                   "DECISIONAL: la señal calibrada paga en la DECISIÓN de asignar un recurso escaso) y confirma el "
                   "diagnóstico de 122 (el payoff decisional necesita ESCASEZ -- por eso el toy, que el modelo domina "
                   "-correctos abundantes-, no podía aislarlo).").format(
                       qs=QS["escaso"], sl=_f(scarce[str(lo)]), sh=_f(scarce[str(hi)]), hi=hi, sg=_f(scarce_gain),
                       qa=QS["abundante"], al=_f(abund[str(lo)]), ah=_f(abund[str(hi)]), ag=_f(abund_gain))
    elif not calib_pays_scarce:
        status = "refutada"
        verdict = ("H-V4-9c REFUTADA: la calibración NO paga bajo escasez (escaso ρ=0->{hi}: +{sg} <= {g}) -> la "
                   "re-localización decisional no se sostiene.").format(hi=hi, sg=_f(scarce_gain), g=GAIN)
    else:
        status = "mixta"
        verdict = ("H-V4-9c MIXTA: la calibración paga bajo escasez (+{sg}) pero bajo abundancia no satura limpio "
                   "(abund Δ {ag}, base {al}).").format(sg=_f(scarce_gain), ag=_f(abund_gain), al=_f(abund[str(lo)]))

    return {"grid": grid, "scarce_gain": scarce_gain, "abund_gain": abund_gain, "abund_saturates": bool(abund_saturates),
            "calib_pays_scarce": bool(calib_pays_scarce), "calib_irrelevant_abund": bool(calib_irrelevant_abund),
            "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=int, default=200)
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--m", type=int, default=5)
    args = ap.parse_args()
    if args.smoke:
        args.seeds = 40

    logs = []

    def log(mm):
        print(mm, flush=True); logs.append(mm)

    log("[exp107] CYCLE 123 / H-V4-9c — la CALIBRACIÓN del selector PAGA en la DECISIÓN bajo ESCASEZ, satura bajo abundancia")
    log(f"[exp107] n={args.n} m={args.m} seeds={args.seeds} rhos={RHOS} qs={QS}")

    grid = run(args.n, args.m, args.seeds)
    sm = build_summary(grid)

    for qn in QS:
        row = " ".join(f"ρ{rho}={grid[qn][str(rho)]:.3f}" for rho in RHOS)
        log(f"[exp107] q={qn:>10} (={QS[qn]}): {row}")
    log(f"[exp107] ganancia por calibración: ESCASO +{sm['scarce_gain']:.3f} | ABUNDANTE +{sm['abund_gain']:.3f} (satura={sm['abund_saturates']})")
    log(f"[exp107] calib_pays_scarce={sm['calib_pays_scarce']} calib_irrelevant_abund={sm['calib_irrelevant_abund']}")
    log(f"[exp107] VEREDICTO H-V4-9c: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp107_decisional_scarcity", "cycle": 123, "hypothesis": "H-V4-9c",
           "claim": "el payoff DECISIONAL de la calibracion del selector se manifiesta exactamente bajo ESCASEZ de buenas "
                    "opciones (paga fuerte con rho bajo escasez; satura bajo abundancia) -> demuestra positivamente que "
                    "R-VALOR es DECISIONAL (121) y confirma que el toy de 122 no podia aislarlo por falta de escasez",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp107] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
