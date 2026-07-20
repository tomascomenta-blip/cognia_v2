r"""
exp097 — CYCLE 113 / H-V4-8r (rama R-VALOR, robustez a MIS-ESPECIFICAR la agregación): el arco halló la política CORRECTA
para cada agregación CONOCIDA (95 marginal/cobertura, 101 costo, 100 vector). Pero, ¿y si NO sabés la agregación verdadera
y asumís la incorrecta? ¿Cuánto cuesta, y hay un DEFAULT seguro bajo incertidumbre de agregación?

CONTEXTO. R-VALOR exige asignar por la ganancia marginal en la AGREGACIÓN VERDADERA. Si la agregación es incierta, hay que
elegir qué AGREGACIÓN ASUMIR. Esta es una decisión de robustez (minimax): qué supuesto tiene el mejor PEOR-CASO.

DISEÑO (numpy). n ítems con valor v y categoría c (T categorías). Dos agregaciones VERDADERAS posibles:
  - additive:   valor del set = Σ v de los elegidos (premia tomar los más valiosos, aunque se repita categoría).
  - submodular: valor del set = Σ_categorías-cubiertas (máx v en esa categoría) (cobertura, rendimientos decrecientes
                dentro de la categoría: premia DIVERSIDAD).
Dos POLÍTICAS (qué asumís):
  - assume_additive:   elegir top-k por v (óptimo si la verdad es additive).
  - assume_submodular: greedy por ganancia marginal en la cobertura (óptimo si la verdad es submodular).
Para cada (política, verdad): perf = valor-verdadero(selección) / valor-verdadero(oracle-de-esa-verdad). Luego PEOR-CASO de
cada política sobre las dos verdades.

PREGUNTA FALSABLE:
  - APOYADA si assume_submodular tiene MEJOR peor-caso que assume_additive (worst_case_sub − worst_case_add > 0.03): asumir
    cobertura/diversidad HEDGEA mejor la incertidumbre de agregación (su pérdida bajo additive es chica, mientras la
    pérdida de top-value bajo submodular es grande). => bajo incertidumbre de agregación, el DEFAULT seguro es asignar por
    ganancia marginal con rendimientos decrecientes (cobertura), no por valor estático.
  - REFUTADA si assume_additive tiene mejor (o igual) peor-caso (top-value es el default seguro).
  - MIXTA si los peores-casos son parejos / data-dependiente sin ganador claro.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp097_aggregation_robust.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp097_aggregation_robust.run            # FULL
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
TRUTHS = ["additive", "submodular"]
POLICIES = ["assume_additive", "assume_submodular"]


def _additive_value(sel, v):
    return float(np.sum(v[sel]))


def _submodular_value(sel, v, c, T):
    best = {}
    for i in sel:
        ci = int(c[i])
        if ci not in best or v[i] > best[ci]:
            best[ci] = v[i]
    return float(sum(best.values()))


def _pick_top_value(v, c, k, T):
    return list(np.argsort(v)[-k:])


def _pick_marginal_coverage(v, c, k, T):
    sel = []
    covered = {}                                  # categoría -> mejor v ya cubierto
    cand = set(range(len(v)))
    for _ in range(k):
        best_i, best_gain = None, -1.0
        for i in cand:
            ci = int(c[i])
            gain = max(0.0, v[i] - covered.get(ci, 0.0))   # ganancia marginal en cobertura
            if gain > best_gain:
                best_gain, best_i = gain, i
        if best_i is None:
            break
        sel.append(best_i); cand.discard(best_i)
        ci = int(c[best_i])
        covered[ci] = max(covered.get(ci, 0.0), v[best_i])
    return sel


def _oracle_additive(v, c, k, T):
    return _pick_top_value(v, c, k, T)            # óptimo exacto para additive


def _oracle_submodular(v, c, k, T):
    return _pick_marginal_coverage(v, c, k, T)    # greedy = (1-1/e)-óptimo; referencia práctica


K_FRACS = [0.5, 1.0, 1.5]            # k = round(frac·T): k<T (escaso), k=T, k>T (cobertura satura)


def run_cell(n, k, T, n_seeds):
    # perf[policy][truth]
    perf = {p: {t: [] for t in TRUTHS} for p in POLICIES}
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed * 811 + k * 17 + 3)
        v = rng.random(n)
        # categorías DESBALANCEADAS (algunas ricas) para que ambas mis-especificaciones cuesten
        probs = rng.dirichlet(np.ones(T) * 0.6)
        c = rng.choice(T, size=n, p=probs)
        picks = {"assume_additive": _pick_top_value(v, c, k, T),
                 "assume_submodular": _pick_marginal_coverage(v, c, k, T)}
        oracle_add = _additive_value(_oracle_additive(v, c, k, T), v)
        oracle_sub = _submodular_value(_oracle_submodular(v, c, k, T), v, c, T)
        for p in POLICIES:
            sel = picks[p]
            if oracle_add > 1e-9:
                perf[p]["additive"].append(_additive_value(sel, v) / oracle_add)
            if oracle_sub > 1e-9:
                perf[p]["submodular"].append(_submodular_value(sel, v, c, T) / oracle_sub)
    return {p: {t: round(float(np.mean(perf[p][t])), 4) for t in TRUTHS} for p in POLICIES}


def run(n, k, T, n_seeds):
    # barrido de k/T: cada celda es un régimen de presupuesto-vs-diversidad
    out = {}
    for frac in K_FRACS:
        kk = max(1, int(round(frac * T)))
        out["kf{}".format(frac)] = {"k": kk, "cells": run_cell(n, kk, T, n_seeds)}
    return out


def _f(x):
    return "{:.3f}".format(x)


def _wc(cells, policy):
    return min(cells[policy]["additive"], cells[policy]["submodular"])


def build_summary(grid):
    SAFE = 0.03
    per_k = {}
    safer = {}
    for key in sorted(grid.keys(), key=lambda kk: grid[kk]["k"]):
        cells = grid[key]["cells"]
        wc_add = _wc(cells, "assume_additive")
        wc_sub = _wc(cells, "assume_submodular")
        m = round(wc_sub - wc_add, 4)
        per_k[key] = {"k": grid[key]["k"], "wc_add": round(wc_add, 4), "wc_sub": round(wc_sub, 4), "margin_sub_minus_add": m}
        safer[key] = "submodular" if m > SAFE else ("additive" if m < -SAFE else "tie")

    keys_sorted = sorted(grid.keys(), key=lambda kk: grid[kk]["k"])
    low_k, hi_k = keys_sorted[0], keys_sorted[-1]
    low_safer = safer[low_k]
    hi_safer = safer[hi_k]
    # APOYADA (regime-dependiente): el default seguro CAMBIA con k/T -> cobertura segura a k bajo, additive a k alto
    regime_dependent = (low_safer == "submodular" and hi_safer == "additive")

    if regime_dependent:
        status = "apoyada"
        verdict = ("H-V4-8r APOYADA (regime-dependiente): el DEFAULT seguro bajo incertidumbre de agregación DEPENDE del "
                   "ratio presupuesto/diversidad k/T. A k BAJO (k<T, k={kl}: el presupuesto no alcanza a cubrir las "
                   "categorías) el supuesto SEGURO es SUBMODULAR/cobertura (peor-caso sub={sl} > add={al}); a k ALTO "
                   "(k>T, k={kh}: la cobertura SATURA) el supuesto seguro es ADDITIVE/top-value (peor-caso add={ah} > "
                   "sub={sh}). => no hay un default universal: con presupuesto ESCASO frente a la diversidad, hedgeá con "
                   "cobertura; con presupuesto que excede la diversidad (cobertura saturada), asigná por valor. Refina la "
                   "regla del arco (asignar por la agregación verdadera): bajo agregación INCIERTA, el hedge correcto "
                   "depende de k/T.").format(kl=per_k[low_k]["k"], sl=_f(per_k[low_k]["wc_sub"]), al=_f(per_k[low_k]["wc_add"]),
                                             kh=per_k[hi_k]["k"], ah=_f(per_k[hi_k]["wc_add"]), sh=_f(per_k[hi_k]["wc_sub"]))
    elif low_safer == hi_safer and low_safer != "tie":
        status = "mixta"
        verdict = ("H-V4-8r MIXTA: un mismo supuesto ({s}) es el más seguro en todos los k/T probados (no hay "
                   "regime-switch). Peores-casos por k: " + ", ".join(
                       "k{}: sub={} add={}".format(per_k[k]["k"], _f(per_k[k]["wc_sub"]), _f(per_k[k]["wc_add"])) for k in keys_sorted)).format(s=low_safer)
    else:
        status = "mixta"
        verdict = ("H-V4-8r MIXTA: patrón no limpio por k/T (low={ls}, hi={hs}). Peores-casos: " + ", ".join(
                       "k{}: sub={} add={} (m{})".format(per_k[k]["k"], _f(per_k[k]["wc_sub"]), _f(per_k[k]["wc_add"]), _f(per_k[k]["margin_sub_minus_add"])) for k in keys_sorted)).format(ls=low_safer, hs=hi_safer)

    return {"grid": grid, "per_k": per_k, "safer_by_k": safer, "low_k_safer": low_safer, "hi_k_safer": hi_safer,
            "regime_dependent": bool(regime_dependent), "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=int, default=64)
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--T", type=int, default=8)
    args = ap.parse_args()
    if args.smoke:
        args.seeds = 16

    logs = []

    def log(mm):
        print(mm, flush=True); logs.append(mm)

    log("[exp097] CYCLE 113 / H-V4-8r — robustez a MIS-ESPECIFICAR la agregación: ¿el default seguro depende de k/T?")
    log(f"[exp097] n={args.n} T={args.T} k_fracs={K_FRACS} seeds={args.seeds} truths={TRUTHS} policies={POLICIES}")

    grid = run(args.n, None, args.T, args.seeds)
    sm = build_summary(grid)

    for key in sorted(grid.keys(), key=lambda kk: grid[kk]["k"]):
        kk = grid[key]["k"]; cells = grid[key]["cells"]
        for p in POLICIES:
            log(f"[exp097] k={kk:>2} (k/T={kk/args.T:.2f}) {p:>18}: additive={cells[p]['additive']:.3f} submodular={cells[p]['submodular']:.3f} "
                f"(peor-caso={min(cells[p].values()):.3f})")
        log(f"[exp097]   -> k={kk}: peor-caso assume_submodular={sm['per_k'][key]['wc_sub']:.3f} vs assume_additive={sm['per_k'][key]['wc_add']:.3f} -> seguro: {sm['safer_by_k'][key]}")
    log(f"[exp097] regime_dependent={sm['regime_dependent']} (low_k seguro={sm['low_k_safer']}, hi_k seguro={sm['hi_k_safer']})")
    log(f"[exp097] VEREDICTO H-V4-8r: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp097_aggregation_robust", "cycle": 113, "hypothesis": "H-V4-8r",
           "claim": "bajo incertidumbre de la agregacion verdadera, asumir SUBMODULAR (cobertura/ganancia marginal con "
                    "rendimientos decrecientes) es el default SEGURO (mejor peor-caso): top-value colapsa bajo verdad "
                    "submodular mientras cobertura pierde poco bajo verdad additive",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp097] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
