r"""
exp092 — CYCLE 108 / H-V4-8m (rama R-VALOR, calidad del estimador: SESGO vs RUIDO): el arco de asignación usó estimadores
de valor RUIDOSOS (error aleatorio). Pero un estimador SESGADO (error SISTEMÁTICO: sobre/sub-valora consistentemente una
región/tipo) es cualitativamente distinto: el sesgo NO promedia entre ítems -> mis-asigna de forma consistente. ¿A error
RMS IGUALADO, el SESGO degrada la asignación (ranking) MÁS que el RUIDO?

CONTEXTO. Conecta con el sesgo del verificador (CYCLE 55: el daño por pin/sesgo no es runaway pero es peor que el ruido) y
con la calibración (106). Distingue qué TIPO de error del estimador de valor importa para la asignación: ruido aleatorio
(se promedia en el ranking) vs sesgo sistemático (no se promedia).

DISEÑO (numpy). n ítems con valor REAL v~U(0,1) y un TIPO t∈{0,1} (independiente de v). Estimadores con error RMS=σ
IGUALADO:
  - noisy:  v_est = v + N(0,σ)            (error ALEATORIO por ítem).
  - biased: v_est = v + σ·(+1 si t=0, −1 si t=1)   (error SISTEMÁTICO por tipo, RMS=σ; sobre-valora t=0, sub t=1).
Se barre σ. Asignación: top-k por v_est. perf = Σv_real(top-k) / Σv_real(oracle top-k). Brazos: noisy, biased, oracle,
chance.

PREGUNTA FALSABLE:
  - APOYADA si a error RMS IGUALADO biased << noisy (perf_noisy − perf_biased > 0.05) en σ moderado/alto, y la brecha
    CRECE con σ. => el SESGO sistemático del estimador de valor degrada la asignación MÁS que el RUIDO equivalente (el
    sesgo no se promedia en el ranking; mis-asigna consistente toda una región). "Calibrado-pero-ruidoso > sesgado-pero-
    preciso": invertir en DEBIASEAR el estimador de valor, no sólo en reducir su ruido.
  - REFUTADA si biased ≈ noisy (el tipo de error no importa, sólo la magnitud).
  - MIXTA en otro caso.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp092_bias_vs_noise.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp092_bias_vs_noise.run            # FULL
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
ARMS = ["noisy", "biased", "oracle", "chance"]
SIGMAS = [0.1, 0.2, 0.3, 0.4]


def _perf(picks, v, k):
    best = np.sort(v)[-k:].sum()
    got = v[list(picks)].sum()
    return float(got / best) if best > 1e-12 else 0.0


def run_cell(n, k, sigma, n_seeds):
    acc = {a: [] for a in ARMS}
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed * 521 + int(sigma * 100) * 7 + 3)
        v = rng.random(n)
        typ = rng.integers(0, 2, size=n)
        v_noisy = v + rng.normal(0.0, sigma, size=n)                 # error aleatorio, RMS=σ
        v_biased = v + sigma * np.where(typ == 0, 1.0, -1.0)         # error sistemático por tipo, RMS=σ
        acc["noisy"].append(_perf(np.argsort(v_noisy)[-k:], v, k))
        acc["biased"].append(_perf(np.argsort(v_biased)[-k:], v, k))
        acc["oracle"].append(_perf(np.argsort(v)[-k:], v, k))
        acc["chance"].append(_perf(rng.choice(n, size=k, replace=False), v, k))
    return {a: round(float(np.mean(acc[a])), 4) for a in ARMS}


def run(n, k, n_seeds):
    return {"s{}".format(s): run_cell(n, k, s, n_seeds) for s in SIGMAS}


def _f(x):
    return "{:.3f}".format(x)


def build_summary(grid):
    gaps = {}     # noisy − biased por σ
    for s in SIGMAS:
        c = grid["s{}".format(s)]
        gaps[s] = round(c["noisy"] - c["biased"], 4)
    mid = SIGMAS[len(SIGMAS) // 2]
    hi = SIGMAS[-1]
    gap_mid = gaps[mid]
    gap_hi = gaps[hi]
    grows = gap_hi > gaps[SIGMAS[0]] + 0.01           # la brecha crece con σ

    GAP_THR = 0.05
    bias_worse = gap_mid > GAP_THR or gap_hi > GAP_THR

    if bias_worse and grows:
        status = "apoyada"
        verdict = ("H-V4-8m APOYADA: a error RMS IGUALADO, el SESGO sistemático del estimador de valor degrada la "
                   "asignación MÁS que el RUIDO equivalente. Brecha noisy−biased por σ: " +
                   ", ".join("σ{}={}".format(s, _f(gaps[s])) for s in SIGMAS) +
                   " -- crece con σ (σ{m}={gm}, σ{h}={gh}). MECANISMO: el ruido aleatorio se PROMEDIA en el ranking "
                   "(top-k aún ~correcto), pero el sesgo por tipo NO se promedia -> sobre-valora toda una región (t=0) y "
                   "la mete entera en el top-k incluyendo sus ítems de bajo valor real -> mis-asignación CONSISTENTE. => "
                   "'calibrado-pero-ruidoso > sesgado-pero-preciso': para la asignación R-VALOR importa DEBIASEAR el "
                   "estimador de valor, no sólo reducir su ruido. Conecta con el sesgo del verificador (CYCLE 55) y la "
                   "calibración (106).").format(m=mid, gm=_f(gap_mid), h=hi, gh=_f(gap_hi))
    elif not bias_worse:
        status = "refutada"
        verdict = ("H-V4-8m REFUTADA (con REVERSIÓN informativa): el SESGO NO degrada más que el ruido a RMS igualado; de "
                   "hecho a σ ALTO el sesgado es MEJOR (brechas noisy−biased por σ: " +
                   ", ".join("σ{}={}".format(s, _f(gaps[s])) for s in SIGMAS) +
                   " -> negativas a σ alto). MECANISMO: el sesgo por-tipo es un OFFSET CONSTANTE -> preserva el ORDEN "
                   "DENTRO de cada tipo (sólo desplaza tipos entre sí), así que el top-k aún toma los MEJORES de cada "
                   "tipo; el RUIDO aleatorio corrompe TODOS los órdenes -> mete ítems genuinamente bajos. => lo que daña "
                   "la asignación (ranking) es el error que ROMPE EL ORDEN (ruido, o sesgo NO-monótono), NO un offset "
                   "sistemático order-preserving. Refina la intuición 'bias peor que noise': un sesgo CONSTANTE es "
                   "benigno para rankear (cf. 106: transformaciones monótonas preservan el ranking); sólo el sesgo "
                   "que DISTORSIONA el orden dañaría. (Hipótesis original REFUTADA: el sesgo constante no es peor que el "
                   "ruido -- es mejor.)").format()
    else:
        status = "mixta"
        verdict = ("H-V4-8m MIXTA: el sesgo degrada más en algún σ (máx {g}) pero la brecha no CRECE limpio con σ "
                   "(σ{lo}={glo} -> σ{h}={gh}).").format(g=_f(max(gaps.values())), lo=SIGMAS[0], glo=_f(gaps[SIGMAS[0]]),
                                                         h=hi, gh=_f(gap_hi))

    return {"grid": grid, "gaps_noisy_minus_biased": {str(s): gaps[s] for s in SIGMAS}, "gap_mid": gap_mid,
            "gap_hi": gap_hi, "grows": bool(grows), "bias_worse": bool(bias_worse), "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=int, default=48)
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--k", type=int, default=10)
    args = ap.parse_args()
    if args.smoke:
        args.seeds = 12

    logs = []

    def log(mm):
        print(mm, flush=True); logs.append(mm)

    log("[exp092] CYCLE 108 / H-V4-8m — SESGO vs RUIDO del estimador de valor (a error RMS igualado, ¿cuál degrada más?)")
    log(f"[exp092] n={args.n} k={args.k} sigmas={SIGMAS} seeds={args.seeds}")

    grid = run(args.n, args.k, args.seeds)
    sm = build_summary(grid)

    for s in SIGMAS:
        c = grid["s{}".format(s)]
        log(f"[exp092] σ={s}: noisy={c['noisy']:.3f} biased={c['biased']:.3f} oracle={c['oracle']:.3f} chance={c['chance']:.3f} "
            f"(noisy−biased={c['noisy']-c['biased']:+.3f})")
    log(f"[exp092] brecha crece con σ={sm['grows']} | bias_worse={sm['bias_worse']}")
    log(f"[exp092] VEREDICTO H-V4-8m: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp092_bias_vs_noise", "cycle": 108, "hypothesis": "H-V4-8m",
           "claim": "a error RMS igualado, el SESGO sistematico del estimador de valor degrada la asignacion (ranking) mas "
                    "que el RUIDO aleatorio: el ruido se promedia en el ranking, el sesgo no -> mis-asignacion "
                    "consistente. calibrado-pero-ruidoso > sesgado-pero-preciso (debiasear importa mas que reducir ruido)",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp092] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
