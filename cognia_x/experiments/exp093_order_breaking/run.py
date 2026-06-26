r"""
exp093 — CYCLE 109 / H-V4-8n (rama R-VALOR, COMPLETA el principio de CYCLE 108: lo que daña la asignación es el error que
ROMPE EL ORDEN): CYCLE 108 halló (revirtiendo la intuición) que un sesgo CONSTANTE (order-preserving) daña MENOS que el
ruido. La lección refinada: lo que daña el ranking es el error ORDER-BREAKING, no 'sesgo vs ruido'. Este ciclo lo COMPLETA
comparando TRES errores a RMS IGUALADO y prediciendo el orden de daño:
  - biased_mono:    sesgo SISTEMÁTICO order-PRESERVING (offset constante por tipo) -> el MEJOR (preserva orden intra-tipo).
  - noisy:          RUIDO aleatorio (order-breaking ALEATORIO) -> intermedio (rompe órdenes al azar, se promedia algo).
  - biased_nonmono: sesgo SISTEMÁTICO order-BREAKING (boost de la banda-media de valor -> mid sobre high) -> el PEOR
                    (rompe el orden de forma CONSISTENTE: siempre mete los mismos ítems equivocados).
HIPÓTESIS: biased_nonmono < noisy < biased_mono (a RMS igualado). => el lever es ROMPER EL ORDEN; la SISTEMATICIDAD ayuda
si es order-preserving y AGRAVA si es order-breaking.

DISEÑO (numpy). n ítems, valor REAL v~U(0,1), tipo t∈{0,1}. Tres estimadores escalados a RMS=σ:
  - biased_mono:    v + σ·(+1 si t=0, −1 si t=1)                      (RMS=σ, order-preserving intra-tipo).
  - noisy:          v + N(0,σ)                                        (RMS=σ, order-breaking aleatorio).
  - biased_nonmono: v + a·1{0.4<=v<=0.6}, a escalado para RMS=σ       (order-breaking sistemático: mid sobre high).
Asignación: top-k por v_est. perf = Σv_real(top-k)/oracle. Barre σ.

PREGUNTA FALSABLE:
  - APOYADA si biased_nonmono < noisy < biased_mono a σ moderado/alto (cada brecha > 0.02). => confirma que el daño lo
    causa ROMPER EL ORDEN (no la sistematicidad ni 'sesgo vs ruido'): el sistemático order-breaking es el PEOR, el
    sistemático order-preserving el MEJOR, el ruido en medio.
  - REFUTADA si el orden no se cumple (p.ej. nonmono no es el peor).
  - MIXTA en otro caso.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp093_order_breaking.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp093_order_breaking.run            # FULL
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
ARMS = ["biased_mono", "noisy", "biased_nonmono", "oracle", "chance"]
SIGMAS = [0.1, 0.2, 0.3, 0.4]


def _perf(picks, v, k):
    best = np.sort(v)[-k:].sum()
    got = v[list(picks)].sum()
    return float(got / best) if best > 1e-12 else 0.0


def run_cell(n, k, sigma, n_seeds):
    acc = {a: [] for a in ARMS}
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed * 619 + int(sigma * 100) * 11 + 3)
        v = rng.random(n)
        typ = rng.integers(0, 2, size=n)
        v_mono = v + sigma * np.where(typ == 0, 1.0, -1.0)              # order-preserving intra-tipo, RMS=σ
        v_noisy = v + rng.normal(0.0, sigma, size=n)                    # order-breaking aleatorio, RMS=σ
        band = ((v >= 0.4) & (v <= 0.6)).astype(float)                 # banda-media
        rms_raw = np.sqrt(np.mean(band ** 2))
        a = sigma / rms_raw if rms_raw > 1e-9 else 0.0
        v_nonmono = v + a * band                                       # order-breaking sistemático (mid sobre high), RMS≈σ
        acc["biased_mono"].append(_perf(np.argsort(v_mono)[-k:], v, k))
        acc["noisy"].append(_perf(np.argsort(v_noisy)[-k:], v, k))
        acc["biased_nonmono"].append(_perf(np.argsort(v_nonmono)[-k:], v, k))
        acc["oracle"].append(_perf(np.argsort(v)[-k:], v, k))
        acc["chance"].append(_perf(rng.choice(n, size=k, replace=False), v, k))
    return {a: round(float(np.mean(acc[a])), 4) for a in ARMS}


def run(n, k, n_seeds):
    return {"s{}".format(s): run_cell(n, k, s, n_seeds) for s in SIGMAS}


def _f(x):
    return "{:.3f}".format(x)


def build_summary(grid):
    hi = SIGMAS[-1]
    mid = SIGMAS[len(SIGMAS) // 2]
    ch = grid["s{}".format(hi)]
    cm = grid["s{}".format(mid)]
    # orden esperado a σ alto: nonmono < noisy < mono
    mono_vs_noisy = round(ch["biased_mono"] - ch["noisy"], 4)          # >0: mono mejor que ruido
    noisy_vs_nonmono = round(ch["noisy"] - ch["biased_nonmono"], 4)    # >0: ruido mejor que nonmono
    GAP = 0.02
    order_holds_hi = (mono_vs_noisy > GAP) and (noisy_vs_nonmono > GAP)
    order_holds_mid = (cm["biased_mono"] - cm["noisy"] > 0) and (cm["noisy"] - cm["biased_nonmono"] > 0)

    if order_holds_hi and order_holds_mid:
        status = "apoyada"
        verdict = ("H-V4-8n APOYADA: a RMS igualado el daño a la asignación sigue el orden ROMPER-EL-ORDEN, no "
                   "'sesgo vs ruido'. A σ={h}: biased_mono={bm} (order-PRESERVING sistemático = MEJOR) > noisy={no} (ruido "
                   "order-breaking ALEATORIO = intermedio, +{mn}) > biased_nonmono={bn} (order-BREAKING SISTEMÁTICO = "
                   "PEOR, +{nn}). => el lever del daño es ROMPER EL ORDEN; la SISTEMATICIDAD AYUDA si es order-preserving "
                   "(mono mejor que ruido) y AGRAVA si es order-breaking (nonmono peor que ruido, porque mete SIEMPRE los "
                   "mismos ítems equivocados). COMPLETA CYCLE 108: ni 'sesgo' ni 'ruido' es la categoría correcta -- es "
                   "order-preserving vs order-breaking. (Para decisiones de UMBRAL/costo, el offset constante SÍ importa, "
                   "106.)").format(h=hi, bm=_f(ch["biased_mono"]), no=_f(ch["noisy"]), mn=_f(mono_vs_noisy),
                                   bn=_f(ch["biased_nonmono"]), nn=_f(noisy_vs_nonmono))
    elif not order_holds_hi and (noisy_vs_nonmono <= GAP):
        status = "refutada"
        verdict = ("H-V4-8n REFUTADA: el sesgo NO-monótono (order-breaking sistemático) NO es el peor (noisy−nonmono={nn} "
                   "<= {g}) -> el order-breaking sistemático no daña más que el ruido.").format(nn=_f(noisy_vs_nonmono), g=GAP)
    else:
        status = "mixta"
        verdict = ("H-V4-8n MIXTA: orden parcial a σ={h} (mono−noisy={mn}, noisy−nonmono={nn}); order_holds_mid="
                   "{om}.").format(h=hi, mn=_f(mono_vs_noisy), nn=_f(noisy_vs_nonmono), om=order_holds_mid)

    return {"grid": grid, "mono_vs_noisy_hi": mono_vs_noisy, "noisy_vs_nonmono_hi": noisy_vs_nonmono,
            "order_holds_hi": bool(order_holds_hi), "order_holds_mid": bool(order_holds_mid),
            "status": status, "verdict": verdict}


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

    log("[exp093] CYCLE 109 / H-V4-8n — order-breaking es el lever: mono(preserva) > ruido > nonmono(rompe sistemático)")
    log(f"[exp093] n={args.n} k={args.k} sigmas={SIGMAS} seeds={args.seeds}")

    grid = run(args.n, args.k, args.seeds)
    sm = build_summary(grid)

    for s in SIGMAS:
        c = grid["s{}".format(s)]
        log(f"[exp093] σ={s}: biased_mono={c['biased_mono']:.3f} noisy={c['noisy']:.3f} biased_nonmono={c['biased_nonmono']:.3f} "
            f"oracle={c['oracle']:.3f} chance={c['chance']:.3f}")
    log(f"[exp093] @σ={SIGMAS[-1]}: mono−noisy=+{sm['mono_vs_noisy_hi']:.3f} | noisy−nonmono=+{sm['noisy_vs_nonmono_hi']:.3f} | "
        f"order_holds_hi={sm['order_holds_hi']} order_holds_mid={sm['order_holds_mid']}")
    log(f"[exp093] VEREDICTO H-V4-8n: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp093_order_breaking", "cycle": 109, "hypothesis": "H-V4-8n",
           "claim": "a error RMS igualado el dano a la asignacion sigue order-preserving>ruido>order-breaking-sistematico: "
                    "el lever es ROMPER EL ORDEN (no sesgo-vs-ruido); la sistematicidad ayuda si preserva el orden y "
                    "agrava si lo rompe. completa CYCLE 108",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp093] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
