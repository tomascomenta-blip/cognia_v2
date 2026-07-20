r"""
exp109 — CYCLE 125 / H-V4-9e (rama R-VALOR, EJE DEL PRESUPUESTO: unifica 123+124 bajo el presupuesto m): 123 mostró que la
calibración paga bajo ESCASEZ; 124 que las apuestas son regime-direccionales (escasez->UPSIDE, abundancia->DOWNSIDE). Ambos
FIJARON el presupuesto (m=5). Este ciclo barre m y halla una ASIMETRÍA del presupuesto entre las dos caras del doble filo.

CONTEXTO. El payoff de someter las top-m depende de m relativo al supply de la MINORÍA relevante: bajo abundancia la
minoría son las opciones MALAS (pocas: n·(1−q)), bajo escasez son las BUENAS (pocas: n·q). Un selector ANTI-calibrado bajo
abundancia sólo puede hacer daño mientras quepa en el presupuesto evitando lo bueno -- una vez que m supera el nº de malas,
se ve FORZADO a incluir buenas y el daño se desvanece. Un selector BIEN-calibrado bajo escasez sigue ganando hasta que m se
acerca a n (porque lo bueno es una fracción ínfima, ensanchar el presupuesto casi no ayuda al azar a alcanzarlo).

HIPÓTESIS: el DOWNSIDE (abundancia) es BUDGET-FRÁGIL (decae apenas m supera el nº de malas), el UPSIDE (escasez) es
BUDGET-ROBUSTO (persiste casi hasta m=n). => bajo abundancia, ensanchar un poco el presupuesto es una MITIGACIÓN BARATA de
una señal posiblemente-rota; bajo escasez no hay sustituto de presupuesto para la calidad de la calibración.

DISEÑO (numpy, extensión de exp108). n ítems, fracción q buenos. Estimador con calibración ρ ∈ {−0.9 anti, 0.0 azar, 0.9
bien}: e = ρ·z_bueno + sqrt(1−ρ²)·ruido. DECISIÓN: someter las top-m por e. payoff = #buenos / min(m, #buenos). Se barre el
PRESUPUESTO m × régimen q × dirección ρ. UPSIDE(m) = payoff(ρ=0.9,m) − payoff(ρ=0,m); DOWNSIDE(m) = payoff(ρ=0,m) −
payoff(ρ=−0.9,m).

PREGUNTA FALSABLE:
  - APOYADA si: (a) a PRESUPUESTO AJUSTADO (m chico) el DOWNSIDE bajo abundancia es grande; (b) ese DOWNSIDE DECAE fuerte al
    crecer m (budget-frágil: a m moderado ya casi desapareció); (c) el UPSIDE bajo escasez SIGUE alto a ese mismo m moderado
    (budget-robusto). => el downside abundante es budget-frágil y el upside escaso es budget-robusto: una asimetría del
    presupuesto entre las dos caras del doble filo (refina 124).
  - REFUTADA si el downside abundante NO decae con m (no es budget-frágil) o el upside escaso TAMBIÉN colapsa al mismo m
    moderado (no hay asimetría) -> la unificación por presupuesto no se sostiene.
  - MIXTA en otro caso.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp109_selective_budget.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp109_selective_budget.run            # FULL
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
MS = [1, 3, 6, 10, 20, 40]
RHOS = {"anti": -0.9, "azar": 0.0, "bien": 0.9}
QS = {"escaso": 0.08, "abundante": 0.9}
MODERATE_M = 20      # presupuesto "moderado" (1/3 de n=60) donde se evalúa la asimetría


def run_cell(n, m, q, rho, n_seeds):
    payoffs = []
    for seed in range(n_seeds):
        # seed única por (seed,q,rho,m); offset +100 en ρ para no dar semilla negativa (ρ<0)
        rng = np.random.default_rng(seed * 877 + int(q * 100) * 13 + (int(rho * 100) + 100) * 7 + m * 101 + 3)
        good = (rng.random(n) < q).astype(float)
        z = good - q
        noise = rng.normal(0.0, 1.0, size=n)
        e = rho * (z / (np.std(z) + 1e-9)) + np.sqrt(max(0.0, 1.0 - rho ** 2)) * noise
        top = np.argsort(e)[-min(m, n):]
        reward = float(np.sum(good[top]))
        oracle = float(min(m, np.sum(good)))
        payoffs.append(reward / oracle if oracle > 0 else 0.0)
    return round(float(np.mean(payoffs)), 4)


def run(n, n_seeds):
    # grid[q][rho_name][m] = payoff
    grid = {}
    for qn, q in QS.items():
        grid[qn] = {}
        for rn, rho in RHOS.items():
            grid[qn][rn] = {str(m): run_cell(n, m, q, rho, n_seeds) for m in MS}
    return grid


def _f(x):
    return "{:.3f}".format(x)


def _upside(grid, qn, m):
    return round(grid[qn]["bien"][str(m)] - grid[qn]["azar"][str(m)], 4)


def _downside(grid, qn, m):
    return round(grid[qn]["azar"][str(m)] - grid[qn]["anti"][str(m)], 4)


def build_summary(grid, n):
    tight = MS[1]                 # m=3, presupuesto ajustado
    mod = MODERATE_M              # m=20, presupuesto moderado
    n_bad_abund = round(n * (1 - QS["abundante"]))   # nº esperado de MALAS bajo abundancia (la minoría relevante)

    down_abund_tight = _downside(grid, "abundante", tight)     # downside abundante a presupuesto ajustado
    down_abund_mod = _downside(grid, "abundante", mod)         # downside abundante a presupuesto moderado
    up_scarce_tight = _upside(grid, "escaso", tight)           # upside escaso a presupuesto ajustado
    up_scarce_mod = _upside(grid, "escaso", mod)               # upside escaso a presupuesto moderado

    down_decay = round(down_abund_tight - down_abund_mod, 4)   # cuánto DECAE el downside abundante (budget-fragilidad)

    BIG, SMALL = 0.40, 0.30
    downside_was_big = down_abund_tight > BIG                  # (a) el downside abundante existe a presupuesto ajustado
    downside_budget_fragile = down_abund_mod < SMALL and down_decay > BIG   # (b) decae fuerte a presupuesto moderado
    upside_budget_robust = up_scarce_mod > SMALL              # (c) el upside escaso PERSISTE a ese mismo m moderado

    if downside_was_big and downside_budget_fragile and upside_budget_robust:
        status = "apoyada"
        verdict = ("H-V4-9e APOYADA: ASIMETRÍA DEL PRESUPUESTO entre las dos caras del doble filo. El DOWNSIDE bajo "
                   "ABUNDANCIA es BUDGET-FRÁGIL: grande a presupuesto ajustado (m={mt}: +{dat}) pero DECAE a presupuesto "
                   "moderado (m={mm}: +{dam}, decae {dd}) -- una vez que m supera el nº de opciones malas (~{nb}), el "
                   "selector anti-calibrado se ve FORZADO a incluir buenas y el daño se desvanece. El UPSIDE bajo ESCASEZ es "
                   "BUDGET-ROBUSTO: sigue alto al MISMO m moderado (m={mm}: +{usm} vs m={mt}: +{ust}) -- como lo bueno es "
                   "una fracción ínfima, ensanchar el presupuesto casi no ayuda al azar a alcanzarlo. => bajo abundancia, "
                   "ensanchar un poco el presupuesto es una MITIGACIÓN BARATA de una señal posiblemente-rota; bajo escasez "
                   "no hay sustituto de presupuesto para la CALIDAD de la calibración. Refina 124 con el eje del "
                   "presupuesto.").format(mt=tight, dat=_f(down_abund_tight), mm=mod, dam=_f(down_abund_mod),
                                          dd=_f(down_decay), nb=n_bad_abund, usm=_f(up_scarce_mod), ust=_f(up_scarce_tight))
    elif not downside_budget_fragile or not upside_budget_robust:
        status = "refutada"
        verdict = ("H-V4-9e REFUTADA: no hay asimetría del presupuesto. downside abundante: ajustado +{dat} -> moderado "
                   "+{dam} (¿budget-frágil? {bf}); upside escaso moderado +{usm} (¿robusto? {br}).").format(
                       dat=_f(down_abund_tight), dam=_f(down_abund_mod), bf=downside_budget_fragile,
                       usm=_f(up_scarce_mod), br=upside_budget_robust)
    else:
        status = "mixta"
        verdict = ("H-V4-9e MIXTA: hay budget-fragilidad del downside (decae {dd}) y robustez del upside (+{usm}) pero el "
                   "patrón no cierra limpio (downside ajustado +{dat} no superó {b}).").format(
                       dd=_f(down_decay), usm=_f(up_scarce_mod), dat=_f(down_abund_tight), b=BIG)

    return {"grid": grid, "n_bad_abund": n_bad_abund, "tight_m": tight, "moderate_m": mod,
            "down_abund_tight": down_abund_tight, "down_abund_mod": down_abund_mod, "down_decay": down_decay,
            "up_scarce_tight": up_scarce_tight, "up_scarce_mod": up_scarce_mod,
            "downside_was_big": bool(downside_was_big), "downside_budget_fragile": bool(downside_budget_fragile),
            "upside_budget_robust": bool(upside_budget_robust), "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=int, default=200)
    ap.add_argument("--n", type=int, default=60)
    args = ap.parse_args()
    if args.smoke:
        args.seeds = 40

    logs = []

    def log(mm):
        print(mm, flush=True); logs.append(mm)

    log("[exp109] CYCLE 125 / H-V4-9e — eje del PRESUPUESTO: ¿downside abundante budget-frágil, upside escaso budget-robusto?")
    log(f"[exp109] n={args.n} seeds={args.seeds} ms={MS} rhos={RHOS} qs={QS} moderate_m={MODERATE_M}")

    grid = run(args.n, args.seeds)
    sm = build_summary(grid, args.n)

    for qn in QS:
        for rn in RHOS:
            row = " ".join(f"m{m}={grid[qn][rn][str(m)]:.3f}" for m in MS)
            log(f"[exp109] q={qn:>10} ρ={rn:>5}({RHOS[rn]:+.1f}): {row}")
    log(f"[exp109] DOWNSIDE abundante: ajustado(m{sm['tight_m']})=+{sm['down_abund_tight']:.3f} -> moderado(m{sm['moderate_m']})=+{sm['down_abund_mod']:.3f} (decae {sm['down_decay']:.3f}; #malas≈{sm['n_bad_abund']})")
    log(f"[exp109] UPSIDE escaso:      ajustado(m{sm['tight_m']})=+{sm['up_scarce_tight']:.3f} -> moderado(m{sm['moderate_m']})=+{sm['up_scarce_mod']:.3f}")
    log(f"[exp109] downside_budget_fragile={sm['downside_budget_fragile']} upside_budget_robust={sm['upside_budget_robust']}")
    log(f"[exp109] VEREDICTO H-V4-9e: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp109_selective_budget", "cycle": 125, "hypothesis": "H-V4-9e",
           "claim": "el doble filo de la calibracion tiene una ASIMETRIA del presupuesto: el DOWNSIDE bajo abundancia es "
                    "BUDGET-FRAGIL (decae apenas m supera el nro de opciones malas, que son pocas), el UPSIDE bajo escasez "
                    "es BUDGET-ROBUSTO (persiste casi hasta m=n). Bajo abundancia ensanchar un poco el presupuesto mitiga "
                    "barato una senal posiblemente-rota; bajo escasez no hay sustituto de presupuesto para la calibracion",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp109] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
