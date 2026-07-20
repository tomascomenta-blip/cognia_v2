"""Potencia estadística del test de McNemar exacto para los gates de COGNIA 3B.

Los gates de calidad de TEORIA_COGNIA3B.md (cognia_v3/training/cognia3b/) comparan
base vs adapter sobre ítems PAREADOS con McNemar exacto (binomial sobre discordantes).
Este script hace reproducibles los umbrales de potencia citados en la teoría:
con qué probabilidad un efecto verdadero de +X pp pasa el gate a N ítems.

Modelo de simulación (mismo supuesto que la teoría, Parte 3):
  - p10 = P(base acierta, adapter falla) fija (churn regresivo).
  - p01 = p10 + delta  → el delta neto es la mejora verdadera.
  - Cada ítem es discordante-01 con prob p01, discordante-10 con prob p10,
    concordante si no. McNemar exacto ignora los concordantes.

Correr:  .\\venv312\\Scripts\\python.exe cognia_v3\\eval\\mcnemar_power.py
Salida:  cognia_v3/eval/mcnemar_power_results.json (committeada como artefacto).
"""
import json
import math
import os
import random

ALPHA = 0.05
REPS = 20_000
SEED = 20260706


def mcnemar_exact_p(n01: int, n10: int) -> float:
    """p-value bilateral del McNemar exacto (binomial p=0.5 sobre discordantes)."""
    n = n01 + n10
    if n == 0:
        return 1.0
    b = min(n01, n10)
    # 2 * P(X <= b) con X ~ Binom(n, 0.5), capado a 1.
    tail = sum(math.comb(n, k) for k in range(b + 1)) / 2.0 ** n
    return min(1.0, 2.0 * tail)


def min_wins_significant(n_discordant: int) -> int | None:
    """Mínimo n01 (con n10 = n_discordant - n01) que da p < ALPHA, o None."""
    for n01 in range(n_discordant, n_discordant // 2, -1):
        if mcnemar_exact_p(n01, n_discordant - n01) < ALPHA:
            continue
        return n01 + 1 if n01 < n_discordant else None
    return None


def power(n_items: int, delta_pp: float, p10: float, rng: random.Random,
          reps: int = REPS) -> float:
    """Fracción de simulaciones donde el efecto verdadero pasa p < ALPHA."""
    p01 = p10 + delta_pp / 100.0
    hits = 0
    for _ in range(reps):
        n01 = n10 = 0
        for _ in range(n_items):
            u = rng.random()
            if u < p01:
                n01 += 1
            elif u < p01 + p10:
                n10 += 1
        if mcnemar_exact_p(n01, n10) < ALPHA:
            hits += 1
    return hits / reps


def main():
    rng = random.Random(SEED)
    # Casos citados por la teoría (Parte 3) + sensibilidad al churn en el umbral
    # real del gate de ganancia (+10 pp).
    cases = []
    for n_items, delta_pp, p10 in [
        (50, 8, 0.02), (50, 12, 0.02), (50, 18, 0.02),
        (100, 8, 0.02), (100, 10, 0.02), (100, 12, 0.02), (100, 18, 0.02),
        (100, 10, 0.06), (100, 10, 0.12),   # churn medio/alto en el umbral del gate
        (200, 10, 0.02),
        (10, 30, 0.02),                      # por qué el baseline N=10 NO es gate
        (16, 20, 0.02),                      # por qué bench_reasoning N=16 es señal, no gate
    ]:
        pw = power(n_items, delta_pp, p10, rng)
        cases.append({"n_items": n_items, "delta_pp": delta_pp, "p10": p10,
                      "power": round(pw, 3)})
        print(f"N={n_items:4d}  delta=+{delta_pp}pp  p10={p10:.2f}  ->  potencia {pw:.1%}")

    # Umbrales exactos de significancia por número de discordantes.
    thresholds = {n: min_wins_significant(n) for n in (10, 15, 20, 30, 50)}
    for n, w in thresholds.items():
        print(f"discordantes={n}: se necesita n01 >= {w} para p < {ALPHA}")

    out = {"alpha": ALPHA, "reps": REPS, "seed": SEED, "cases": cases,
           "min_wins_by_discordants": thresholds,
           "modelo": "p01 = p10 + delta; McNemar exacto bilateral sobre discordantes"}
    path = os.path.join(os.path.dirname(__file__), "mcnemar_power_results.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    print(f"\nGuardado: {path}")


if __name__ == "__main__":
    main()
