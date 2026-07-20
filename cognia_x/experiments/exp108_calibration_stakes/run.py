r"""
exp108 — CYCLE 124 / H-V4-9d (rama R-VALOR, ESTRÉS ADVERSARIAL del capstone 123): 123 (exp107) demostró que la
CALIBRACIÓN del selector PAGA en la decisión EXACTAMENTE bajo ESCASEZ y SATURA (es irrelevante) bajo ABUNDANCIA -- pero
sólo barrió ρ≥0 (de azar a buena calibración). Este ciclo extiende el barrido a ρ<0: un estimador ACTIVAMENTE MAL-CALIBRADO
("confiadamente equivocado" -- el peligro que halló el sub-arco de fragilidad 115-119, donde la señal endógena se vuelve
sobreconfiada-incorrecta). La pregunta: ¿las APUESTAS de la calibración son simétricas, o el régimen decide qué DIRECCIÓN
importa?

CONTEXTO. 123 cerró "bajo abundancia la calibración es irrelevante". Esa frase es verdadera SÓLO para el UPSIDE (cualquier
selector positivo satura cerca de 1). Pero un selector ANTI-calibrado bajo abundancia elige justamente las raras opciones
MALAS (hay pocas, pero las encuentra fiablemente) -> catástrofe. Bajo escasez, en cambio, casi todo es malo, así que el
suelo aleatorio ya es bajo y un selector anti-calibrado no puede empeorarlo mucho. Predicción: las apuestas son
REGIME-DIRECCIONALES (anti-diagonal): escasez -> importa el UPSIDE; abundancia -> importa el DOWNSIDE.

DISEÑO (numpy, extensión directa de exp107). n ítems, fracción q "buenos" (valor 1), 1−q "malos" (valor 0). Estimador con
calibración ρ ∈ [−0.9, +0.9]: e = ρ·z_bueno + sqrt(1−ρ²)·ruido (ρ<0 => e ANTI-correlacionado con la bondad => el top-m
elige los MENOS buenos). DECISIÓN: someter las top-m por e. payoff = #buenos sometidos / min(m, #buenos) (vs oracle). Se
barre ρ (incl. negativos) × q (escaso/abundante). UPSIDE = payoff(ρ=+0.9) − payoff(ρ=0); DOWNSIDE = payoff(ρ=0) −
payoff(ρ=−0.9).

PREGUNTA FALSABLE:
  - APOYADA si el patrón es ANTI-DIAGONAL: bajo ESCASEZ el UPSIDE es grande y el DOWNSIDE chico; bajo ABUNDANCIA el UPSIDE
    es chico (satura) y el DOWNSIDE es GRANDE. => las apuestas de la calibración son regime-DIRECCIONALES; una señal de
    valor endógena es de DOBLE FILO y su fiabilidad importa en AMBOS regímenes pero por razones OPUESTAS (escasez: capturar
    las gemas raras; abundancia: NO pisar las raras minas). Refina 123: "irrelevante bajo abundancia" vale sólo para el
    upside.
  - REFUTADA si el DOWNSIDE bajo abundancia NO es grande (la mal-calibración no hace daño bajo abundancia) o el UPSIDE bajo
    escasez no paga -> la tesis del doble filo regime-direccional no se sostiene (volvería a "la calibración sólo importa
    bajo escasez, en ambas direcciones").
  - MIXTA en otro caso.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp108_calibration_stakes.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp108_calibration_stakes.run            # FULL
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
RHOS = [-0.9, -0.6, -0.3, 0.0, 0.3, 0.6, 0.9]
QS = {"escaso": 0.08, "abundante": 0.9}


def run_cell(n, m, q, rho, n_seeds):
    payoffs = []
    for seed in range(n_seeds):
        # esquema de siembra estilo exp107, con offset +100 en el término de ρ para que ρ<0 no dé semilla negativa
        # (sigue determinista y único por (seed, q, ρ); ρ∈[-0.9,0.9] -> int(ρ*100)+100 ∈ [10,190])
        rng = np.random.default_rng(seed * 877 + int(q * 100) * 13 + (int(rho * 100) + 100) * 7 + 3)
        good = (rng.random(n) < q).astype(float)               # bondad binaria (base rate q)
        z = good - q                                           # bondad centrada
        noise = rng.normal(0.0, 1.0, size=n)
        e = rho * (z / (np.std(z) + 1e-9)) + np.sqrt(max(0.0, 1.0 - rho ** 2)) * noise   # estimador con corr≈ρ (ρ<0 => anti)
        top = np.argsort(e)[-min(m, n):]                       # top-m por estimador (ρ<0 => elige los MENOS buenos)
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
    rnd = "0.0"      # ρ=0 = azar (suelo neutral)
    hi = "0.9"       # ρ=+0.9 = bien calibrado
    lo = "-0.9"      # ρ=−0.9 = anti-calibrado (confiadamente equivocado)
    sc, ab = grid["escaso"], grid["abundante"]

    upside_scarce = round(sc[hi] - sc[rnd], 4)        # cuánto AÑADE la buena calibración sobre el azar, bajo escasez
    downside_scarce = round(sc[rnd] - sc[lo], 4)      # cuánto QUITA la anti-calibración bajo el azar, bajo escasez
    upside_abund = round(ab[hi] - ab[rnd], 4)         # idem upside, bajo abundancia
    downside_abund = round(ab[rnd] - ab[lo], 4)       # idem downside, bajo abundancia

    BIG, SMALL = 0.30, 0.20
    anti_diagonal = (upside_scarce > BIG and downside_scarce < SMALL
                     and upside_abund < SMALL and downside_abund > BIG)
    abund_downside_real = downside_abund > BIG
    scarce_upside_real = upside_scarce > BIG

    if anti_diagonal:
        status = "apoyada"
        verdict = ("H-V4-9d APOYADA (anti-diagonal): las apuestas de la calibración son REGIME-DIRECCIONALES. ESCASEZ "
                   "(q={qs}): UPSIDE +{us} (azar {sr}->bien {sh}), DOWNSIDE +{ds} (azar->anti {sl}) -> importa el UPSIDE "
                   "(capturar gemas raras), el suelo ya es bajo. ABUNDANCIA (q={qa}): UPSIDE +{ua} (satura, azar {ar}->bien "
                   "{ah}: irrelevante), DOWNSIDE +{da} (azar->anti {al}) -> importa el DOWNSIDE (un selector anti-calibrado "
                   "encuentra fiablemente las raras MINAS -> catástrofe). => una señal de valor endógena es de DOBLE FILO; "
                   "su fiabilidad importa en AMBOS regímenes pero por razones OPUESTAS. REFINA 123: 'irrelevante bajo "
                   "abundancia' vale SÓLO para el upside; una señal MALA es más peligrosa justo donde te sentís seguro.").format(
                       qs=QS["escaso"], us=_f(upside_scarce), sr=_f(sc[rnd]), sh=_f(sc[hi]), ds=_f(downside_scarce),
                       sl=_f(sc[lo]), qa=QS["abundante"], ua=_f(upside_abund), ar=_f(ab[rnd]), ah=_f(ab[hi]),
                       da=_f(downside_abund), al=_f(ab[lo]))
    elif not abund_downside_real or not scarce_upside_real:
        status = "refutada"
        verdict = ("H-V4-9d REFUTADA: no hay doble-filo regime-direccional. UPSIDE escaso +{us} (>{b}? {su}), DOWNSIDE "
                   "abundante +{da} (>{b}? {ad}). Si el downside bajo abundancia no es grande, la mal-calibración no hace "
                   "daño donde 123 dice 'irrelevante' y la tesis cae.").format(
                       us=_f(upside_scarce), da=_f(downside_abund), b=BIG, su=scarce_upside_real, ad=abund_downside_real)
    else:
        status = "mixta"
        verdict = ("H-V4-9d MIXTA: hay señal de doble-filo (upside escaso +{us}, downside abundante +{da}) pero el patrón "
                   "anti-diagonal no es limpio (downside escaso +{ds}, upside abundante +{ua} no caen bajo {s}).").format(
                       us=_f(upside_scarce), da=_f(downside_abund), ds=_f(downside_scarce), ua=_f(upside_abund), s=SMALL)

    return {"grid": grid, "upside_scarce": upside_scarce, "downside_scarce": downside_scarce,
            "upside_abund": upside_abund, "downside_abund": downside_abund,
            "anti_diagonal": bool(anti_diagonal), "abund_downside_real": bool(abund_downside_real),
            "scarce_upside_real": bool(scarce_upside_real), "status": status, "verdict": verdict}


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

    log("[exp108] CYCLE 124 / H-V4-9d — apuestas de la calibración: ¿escasez->UPSIDE, abundancia->DOWNSIDE? (ρ incl. anti)")
    log(f"[exp108] n={args.n} m={args.m} seeds={args.seeds} rhos={RHOS} qs={QS}")

    grid = run(args.n, args.m, args.seeds)
    sm = build_summary(grid)

    for qn in QS:
        row = " ".join(f"ρ{rho:+.1f}={grid[qn][str(rho)]:.3f}" for rho in RHOS)
        log(f"[exp108] q={qn:>10} (={QS[qn]}): {row}")
    log(f"[exp108] ESCASEZ:   upside(0->+.9)=+{sm['upside_scarce']:.3f}  downside(0->-.9)=+{sm['downside_scarce']:.3f}")
    log(f"[exp108] ABUNDANCIA: upside(0->+.9)=+{sm['upside_abund']:.3f}  downside(0->-.9)=+{sm['downside_abund']:.3f}")
    log(f"[exp108] anti_diagonal={sm['anti_diagonal']} (escasez->UPSIDE, abundancia->DOWNSIDE)")
    log(f"[exp108] VEREDICTO H-V4-9d: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp108_calibration_stakes", "cycle": 124, "hypothesis": "H-V4-9d",
           "claim": "las apuestas de la calibracion del selector son REGIME-DIRECCIONALES: bajo escasez importa el UPSIDE "
                    "de la buena calibracion (gemas raras), bajo abundancia importa el DOWNSIDE de la anti-calibracion "
                    "(encuentra fiablemente las raras minas) -> una senal de valor endogena es de doble filo; refina 123 "
                    "('irrelevante bajo abundancia' solo vale para el upside)",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp108] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
