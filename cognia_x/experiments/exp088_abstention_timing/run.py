r"""
exp088 — CYCLE 104 / H-V4-8i (rama R-VALOR, dimensión NUEVA: TIMING del presupuesto / ABSTENCIÓN): todo el arco de
asignación (83-103) gastó un presupuesto FIJO por ronda (cuánto VERIFICAR/elegir DENTRO de una ronda). Un agente real con
un presupuesto GLOBAL acotado también decide CUÁNDO gastar: abstenerse en rondas POBRES (pocos ítems valiosos) y guardar
para rondas RICAS. ¿Asignar el presupuesto global por el VALOR estimado de cada ronda (gastar donde rinde, abstenerse
donde no) supera a gastar uniforme?

CONTEXTO. Es la dimensión TEMPORAL de R-VALOR: no sólo QUÉ elegir (within-round, 83-103) sino CUÁNDO gastar el
presupuesto (across-round). Conecta con la ABSTENCIÓN (CYCLE 46) y con el COSTO (101): el valor de NO actuar.

DISEÑO (numpy, online). T rondas; cada ronda tiene una RIQUEZA r_t (la masa de valor disponible esa ronda) que VARÍA:
régimen 'varied' (riquezas heterogéneas: algunas rondas ricas, otras pobres) vs 'flat' (riqueza ~uniforme, control). El
valor logrado al gastar k picks en una ronda = k·r_t (rendimiento ∝ riqueza; cap a la masa disponible). Presupuesto
GLOBAL B (total de picks sobre las T rondas). El agente ve una RIQUEZA ESTIMADA ruidosa r_est_t (no la real). Brazos:
  - uniform:   gasta B/T picks cada ronda (ignora la riqueza).
  - threshold: gasta más donde la riqueza estimada es alta; abstiene (0) donde es baja (asignación greedy del presupuesto
               global por riqueza estimada, con tope por ronda).
  - oracle:    asigna B por la riqueza REAL (gasta en las rondas más ricas) = techo.
  - random:    reparte B al azar entre rondas.
Perf = valor_real_total / valor_real_oracle.

PREGUNTA FALSABLE:
  - APOYADA si bajo riquezas VARIADAS threshold >> uniform (+>0.05; gastar-donde-rinde + abstenerse gana) Y ≈ oracle;
    bajo riqueza FLAT coinciden (cuando todas las rondas rinden igual, el timing no importa). => R-VALOR gobierna CUÁNDO
    gastar (timing/abstención), no sólo qué elegir; el valor de NO actuar es real.
  - REFUTADA si threshold ≈ uniform bajo variadas (el timing no aporta).
  - MIXTA en otro caso.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp088_abstention_timing.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp088_abstention_timing.run            # FULL
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
ARMS = ["uniform", "threshold", "oracle", "random"]
REGIMES = ["varied", "flat"]
REGIME_ID = {"varied": 0, "flat": 1}


def _alloc_by_richness(rich, B, cap):
    """Asigna B picks (enteros) por riqueza desc, con tope 'cap' por ronda (gastar-donde-rinde + abstención implícita)."""
    T = len(rich)
    k = np.zeros(T, dtype=int)
    order = np.argsort(rich)[::-1]
    rem = B
    for t in order:
        if rem <= 0:
            break
        give = min(cap, rem)
        k[t] = give; rem -= give
    return k


def _value(k, rich, mass):
    # valor logrado = picks · riqueza, cap a la masa disponible esa ronda
    return float(np.sum(np.minimum(k, mass) * rich))


def run_cell(n_rounds, B, cap, regime, noise, n_seeds):
    acc = {a: [] for a in ARMS}
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed * 617 + REGIME_ID[regime] * 29 + 5)
        if regime == "varied":
            rich = rng.random(n_rounds) ** 2          # heterogénea (muchas pobres, pocas ricas)
        else:
            rich = 0.45 + 0.1 * rng.random(n_rounds)  # ~uniforme
        mass = rng.integers(cap, cap + 5, size=n_rounds)        # masa disponible por ronda (>= cap)
        rich_est = np.clip(rich + rng.normal(0.0, noise, size=n_rounds), 0.0, None)

        k_uniform = np.full(n_rounds, max(1, B // n_rounds), dtype=int)
        k_threshold = _alloc_by_richness(rich_est, B, cap)
        k_oracle = _alloc_by_richness(rich, B, cap)
        # random: reparte B al azar
        k_random = np.zeros(n_rounds, dtype=int); rem = B
        for t in rng.permutation(n_rounds):
            if rem <= 0:
                break
            give = min(cap, rem, int(rng.integers(0, cap + 1)))
            k_random[t] = give; rem -= give

        denom = _value(k_oracle, rich, mass)
        if denom < 1e-9:
            continue
        acc["uniform"].append(_value(k_uniform, rich, mass) / denom)
        acc["threshold"].append(_value(k_threshold, rich, mass) / denom)
        acc["oracle"].append(1.0)
        acc["random"].append(_value(k_random, rich, mass) / denom)
    return {a: round(float(np.mean(acc[a])), 4) for a in ARMS}


def run(n_rounds, B, cap, noise, n_seeds):
    return {reg: run_cell(n_rounds, B, cap, reg, noise, n_seeds) for reg in REGIMES}


def _f(x):
    return "{:.3f}".format(x)


def build_summary(grid):
    var, flat = grid["varied"], grid["flat"]
    varied_gain = round(var["threshold"] - var["uniform"], 4)        # >0.05 esperado (timing gana bajo riquezas variadas)
    varied_oracle_gap = round(var["oracle"] - var["threshold"], 4)
    flat_coincide = round(abs(flat["threshold"] - flat["uniform"]), 4)  # ~0 bajo riqueza flat

    GAP_THR = 0.05
    COINC_TOL = 0.03
    NEAR_ORACLE = 0.08

    timing_wins = varied_gain > GAP_THR
    near_oracle = varied_oracle_gap <= NEAR_ORACLE
    coincide_flat = flat_coincide <= COINC_TOL

    if timing_wins and near_oracle and coincide_flat:
        status = "apoyada"
        verdict = ("H-V4-8i APOYADA: bajo riquezas VARIADAS (algunas rondas ricas, otras pobres), asignar el presupuesto "
                   "GLOBAL por el VALOR estimado de cada ronda -- gastar donde rinde, ABSTENERSE donde no -- SUPERA a "
                   "gastar uniforme: threshold={th} >> uniform={un} (+{vg}, ≈ oracle gap {og}). Bajo riqueza FLAT coinciden "
                   "(Δ {fc}: cuando todas las rondas rinden igual, el timing no importa). => R-VALOR gobierna CUÁNDO "
                   "gastar (timing/abstención), no sólo QUÉ elegir; el valor de NO actuar (abstenerse en rondas pobres "
                   "para guardar el presupuesto) es REAL. Dimensión TEMPORAL del arco de asignación (83-103).").format(
                       th=_f(var["threshold"]), un=_f(var["uniform"]), vg=_f(varied_gain), og=_f(varied_oracle_gap), fc=_f(flat_coincide))
    elif not timing_wins:
        status = "refutada"
        verdict = ("H-V4-8i REFUTADA: bajo riquezas variadas el timing NO aporta (threshold={th} ≈ uniform={un}, Δ {vg} "
                   "<= {thr}) -> gastar uniforme ya basta.").format(th=_f(var["threshold"]), un=_f(var["uniform"]),
                                                                    vg=_f(varied_gain), thr=GAP_THR)
    else:
        status = "mixta"
        verdict = ("H-V4-8i MIXTA: timing_wins={tw}(+{vg}) near_oracle={no}(gap {og}) coincide_flat={cf}(Δ {fc}).").format(
                       tw=timing_wins, vg=_f(varied_gain), no=near_oracle, og=_f(varied_oracle_gap), cf=coincide_flat, fc=_f(flat_coincide))

    return {"grid": grid, "varied_gain": varied_gain, "varied_oracle_gap": varied_oracle_gap,
            "flat_coincide": flat_coincide, "timing_wins": bool(timing_wins), "near_oracle": bool(near_oracle),
            "coincide_flat": bool(coincide_flat), "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=int, default=48)
    ap.add_argument("--rounds", type=int, default=20)
    ap.add_argument("--B", type=int, default=20)
    ap.add_argument("--cap", type=int, default=5)
    ap.add_argument("--noise", type=float, default=0.08)
    args = ap.parse_args()
    if args.smoke:
        args.seeds = 12

    logs = []

    def log(mm):
        print(mm, flush=True); logs.append(mm)

    log("[exp088] CYCLE 104 / H-V4-8i — TIMING del presupuesto / ABSTENCIÓN: ¿gastar-donde-rinde supera a gastar uniforme?")
    log(f"[exp088] rounds={args.rounds} B={args.B} cap={args.cap} noise={args.noise} seeds={args.seeds} regimes={REGIMES}")

    grid = run(args.rounds, args.B, args.cap, args.noise, args.seeds)
    sm = build_summary(grid)

    for reg in REGIMES:
        c = grid[reg]
        log(f"[exp088] richness={reg:>6}: uniform={c['uniform']:.3f} threshold={c['threshold']:.3f} "
            f"oracle={c['oracle']:.3f} random={c['random']:.3f}")
    log(f"[exp088] VARIED: threshold−uniform=+{sm['varied_gain']:.3f} oracle_gap={sm['varied_oracle_gap']:.3f} | "
        f"FLAT: coincide Δ={sm['flat_coincide']:.3f}")
    log(f"[exp088] timing_wins={sm['timing_wins']} near_oracle={sm['near_oracle']} coincide_flat={sm['coincide_flat']}")
    log(f"[exp088] VEREDICTO H-V4-8i: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp088_abstention_timing", "cycle": 104, "hypothesis": "H-V4-8i",
           "claim": "R-VALOR gobierna CUANDO gastar el presupuesto global (timing/abstencion), no solo que elegir: bajo "
                    "rondas de riqueza heterogenea, asignar el presupuesto por el valor estimado de cada ronda (gastar "
                    "donde rinde, abstenerse donde no) supera a gastar uniforme; bajo riqueza flat coinciden",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp088] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
