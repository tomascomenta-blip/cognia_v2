r"""
exp079 — CYCLE 95 / H-V4-8a (rama R-VALOR, gap #4: objetivo NO-aditivo): todo el arco 83-94 asignó "top-k por valor
estimado", asumiendo un objetivo ADITIVO (perf = suma de valores independientes de los ítems). El caso REAL es a menudo
SUBMODULAR (cobertura / rendimientos decrecientes: no sirve elegir 10 copias de lo mismo). ¿La asignación por valor
ABSOLUTO (top-k, la política implícita de 83-94) FALLA bajo submodularidad, y el valor MARGINAL (greedy por ganancia
respecto del conjunto ya elegido) la recupera? => R-VALOR debe ser MARGINAL (contextual al conjunto), no absoluto.

CONTEXTO. El arco 83-94 (incl. el lazo cerrado real 93-94) midió perf_of = (suma de valores de los top-k) / (mejor
alcanzable), un objetivo ADITIVO. La diversidad apareció como un MATIZ empírico (narrowing, 49-50/94). Este ciclo lo
formaliza: un objetivo SUBMODULAR (cobertura por tipo con calidad) es la estructura donde la diversidad ES el valor, y
expone que la regla "top-k por valor" no basta.

DISEÑO (numpy). n ítems; cada uno con TIPO t∈{0..T-1} y CALIDAD q∈[0,1]. Objetivo:
  - submodular (cobertura): value(S) = Σ_t max_{i∈S, t_i=t} q_i  (sólo cuenta el mejor por tipo -> ítems redundantes del
    mismo tipo no aportan; monótona y submodular).
  - additive (control): value(S) = Σ_{i∈S} q_i  (la suposición de 83-94).
El agente ve calidad RUIDOSA q_est y los tipos. Presupuesto k picks (k>T -> la cobertura importa). Brazos:
  - additive_greedy: top-k por q_est (ignora tipos -> elige redundantes del mismo tipo). La política implícita de 83-94.
  - marginal_greedy: greedy por GANANCIA MARGINAL respecto del conjunto (R-VALOR marginal) usando q_est + tipos.
  - oracle: óptimo con q REAL (para additive: top-k; para submodular: mejores type-max). Techo.
  - random.
Perf = value_real(picks) / value_real(oracle).

PREGUNTA FALSABLE:
  - APOYADA si bajo SUBMODULAR marginal_greedy >> additive_greedy (gap > 0.05; el absoluto desperdicia picks en
    redundantes) Y bajo ADDITIVE marginal ≈ additive (gap ~0; sin redundancia, top-k = óptimo) Y marginal ≈ oracle.
    => el valor debe ser MARGINAL bajo objetivos no-aditivos; "top-k por valor" es específico de la aditividad.
  - REFUTADA si additive ≈ marginal aun bajo submodular (la aditividad es inocua).
  - MIXTA en otro caso.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp079_submodular_value.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp079_submodular_value.run            # FULL
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
ARMS = ["additive_greedy", "marginal_greedy", "oracle", "random"]
OBJECTIVES = ["submodular", "additive"]
OBJ_ID = {"submodular": 0, "additive": 1}


def _submod_value(picks, q, typ, T):
    best = np.zeros(T)
    for i in picks:
        if q[i] > best[typ[i]]:
            best[typ[i]] = q[i]
    return float(best.sum())


def _add_value(picks, q):
    return float(np.sum(q[list(picks)])) if len(picks) else 0.0


def _value(picks, q, typ, T, obj):
    return _submod_value(picks, q, typ, T) if obj == "submodular" else _add_value(picks, q)


def _marginal_greedy(q_est, typ, T, k, obj):
    """Greedy por ganancia marginal sobre q_est (R-VALOR marginal): en cada paso, el ítem que MÁS sube el valor del
    conjunto actual. Para submodular cubre tipos; para additive = top-k (la ganancia marginal = q)."""
    n = len(q_est)
    picks = []
    if obj == "additive":
        return list(np.argsort(q_est)[::-1][:k])
    cur_best = np.zeros(T)
    chosen = np.zeros(n, dtype=bool)
    for _ in range(min(k, n)):
        gain = np.maximum(0.0, q_est - cur_best[typ])     # ganancia de añadir i = max(0, q_i - mejor actual de su tipo)
        gain[chosen] = -1.0
        j = int(np.argmax(gain))
        picks.append(j); chosen[j] = True
        if q_est[j] > cur_best[typ[j]]:
            cur_best[typ[j]] = q_est[j]
    return picks


def _oracle(q, typ, T, k, obj):
    if obj == "additive":
        return list(np.argsort(q)[::-1][:k])
    # submodular óptimo: mejor ítem por tipo (type-max real); tomar los top-min(k,T) type-max
    type_max = np.zeros(T); type_arg = -np.ones(T, dtype=int)
    for i in range(len(q)):
        if q[i] > type_max[typ[i]]:
            type_max[typ[i]] = q[i]; type_arg[typ[i]] = i
    order = np.argsort(type_max)[::-1]
    picks = [int(type_arg[t]) for t in order[:min(k, T)] if type_arg[t] >= 0]
    return picks


def run_cell(n, T, k, obj, noise, n_seeds):
    acc = {a: [] for a in ARMS}
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed * 911 + OBJ_ID[obj] * 31 + 7)
        q = rng.random(n)
        typ = rng.integers(0, T, size=n)
        q_est = np.clip(q + rng.normal(0.0, noise, size=n), 0.0, 1.0)
        oracle_picks = _oracle(q, typ, T, k, obj)
        denom = _value(oracle_picks, q, typ, T, obj)
        if denom < 1e-12:
            continue
        add_picks = list(np.argsort(q_est)[::-1][:k])
        marg_picks = _marginal_greedy(q_est, typ, T, k, obj)
        rand_picks = list(rng.choice(n, size=min(k, n), replace=False))
        acc["additive_greedy"].append(_value(add_picks, q, typ, T, obj) / denom)
        acc["marginal_greedy"].append(_value(marg_picks, q, typ, T, obj) / denom)
        acc["oracle"].append(_value(oracle_picks, q, typ, T, obj) / denom)
        acc["random"].append(_value(rand_picks, q, typ, T, obj) / denom)
    return {a: round(float(np.mean(acc[a])), 4) for a in ARMS}


def run(n, T, k, noise, n_seeds):
    return {obj: run_cell(n, T, k, obj, noise, n_seeds) for obj in OBJECTIVES}


def _f(x):
    return "{:.3f}".format(x)


def build_summary(grid):
    sub, add = grid["submodular"], grid["additive"]
    gap_sub = round(sub["marginal_greedy"] - sub["additive_greedy"], 4)        # >0 esperado (marginal cubre, additive redundante)
    gap_add = round(add["marginal_greedy"] - add["additive_greedy"], 4)        # ~0 esperado (top-k = óptimo aditivo)
    marg_oracle_gap_sub = round(sub["oracle"] - sub["marginal_greedy"], 4)     # chico esperado (marginal ≈ oracle)
    add_loss_sub = round(sub["oracle"] - sub["additive_greedy"], 4)            # grande esperado (additive pierde)

    GAP_THR = 0.05
    ADD_TOL = 0.03
    NEAR_ORACLE = 0.05

    marginal_wins_sub = gap_sub > GAP_THR
    coincide_add = abs(gap_add) <= ADD_TOL
    marg_near_oracle = marg_oracle_gap_sub <= NEAR_ORACLE

    if marginal_wins_sub and coincide_add and marg_near_oracle:
        status = "apoyada"
        verdict = ("H-V4-8a APOYADA: bajo objetivo SUBMODULAR (cobertura), la asignación por valor ABSOLUTO (top-k, la "
                   "política implícita de 83-94) DESPERDICIA picks en ítems redundantes del mismo tipo -- additive_greedy="
                   "{ag} -- mientras el valor MARGINAL (greedy por ganancia respecto del conjunto) CUBRE los tipos: "
                   "marginal_greedy={mg} (+{gs}, ≈ oracle, gap {mo}). Bajo objetivo ADDITIVE coinciden (gap {ga}, top-k = "
                   "óptimo). El additive pierde {al} vs oracle bajo submodular. => R-VALOR debe ser MARGINAL (contextual "
                   "al conjunto) bajo objetivos no-aditivos; 'top-k por valor' es específico de la aditividad. Formaliza "
                   "el tema de diversidad (49-50/94): la diversidad ES el valor cuando el objetivo es de "
                   "cobertura.").format(ag=_f(sub["additive_greedy"]), mg=_f(sub["marginal_greedy"]), gs=_f(gap_sub),
                                        mo=_f(marg_oracle_gap_sub), ga=_f(gap_add), al=_f(add_loss_sub))
    elif not marginal_wins_sub:
        status = "refutada"
        verdict = ("H-V4-8a REFUTADA: bajo submodular el valor marginal NO supera al absoluto (gap {gs} <= {thr}) -> la "
                   "suposición de aditividad es inocua aquí.").format(gs=_f(gap_sub), thr=GAP_THR)
    else:
        status = "mixta"
        verdict = ("H-V4-8a MIXTA: marginal_wins_sub={mw} (gap {gs}) coincide_add={ca} (gap {ga}) marg_near_oracle={mn} "
                   "(gap {mo}).").format(mw=marginal_wins_sub, gs=_f(gap_sub), ca=coincide_add, ga=_f(gap_add),
                                         mn=marg_near_oracle, mo=_f(marg_oracle_gap_sub))

    return {"grid": grid, "gap_submodular": gap_sub, "gap_additive": gap_add,
            "marginal_oracle_gap_sub": marg_oracle_gap_sub, "additive_loss_sub": add_loss_sub,
            "marginal_wins_sub": bool(marginal_wins_sub), "coincide_add": bool(coincide_add),
            "marg_near_oracle": bool(marg_near_oracle), "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=int, default=48)
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--T", type=int, default=5)
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--noise", type=float, default=0.05)
    args = ap.parse_args()
    if args.smoke:
        args.seeds = 12

    logs = []

    def log(mm):
        print(mm, flush=True); logs.append(mm)

    log("[exp079] CYCLE 95 / H-V4-8a — gap #4 (objetivo NO-aditivo): R-VALOR marginal vs absoluto bajo submodularidad")
    log(f"[exp079] n={args.n} T={args.T} k={args.k} noise={args.noise} seeds={args.seeds} objetivos={OBJECTIVES} (k>T -> cobertura importa)")

    grid = run(args.n, args.T, args.k, args.noise, args.seeds)
    sm = build_summary(grid)

    for obj in OBJECTIVES:
        c = grid[obj]
        log(f"[exp079] {obj:>10}: additive_greedy={c['additive_greedy']:.3f} marginal_greedy={c['marginal_greedy']:.3f} "
            f"oracle={c['oracle']:.3f} random={c['random']:.3f}")
    log(f"[exp079] gap_submodular(marg−add)=+{sm['gap_submodular']:.3f} | gap_additive={sm['gap_additive']:+.3f} | "
        f"marg_oracle_gap_sub={sm['marginal_oracle_gap_sub']:.3f} | additive_loss_sub={sm['additive_loss_sub']:.3f}")
    log(f"[exp079] marginal_wins_sub={sm['marginal_wins_sub']} coincide_add={sm['coincide_add']} marg_near_oracle={sm['marg_near_oracle']}")
    log(f"[exp079] VEREDICTO H-V4-8a: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp079_submodular_value", "cycle": 95, "hypothesis": "H-V4-8a",
           "claim": "bajo un objetivo NO-aditivo (submodular/cobertura) la asignacion por valor ABSOLUTO (top-k, la "
                    "politica implicita de 83-94) desperdicia picks en redundantes; el valor MARGINAL (greedy por "
                    "ganancia respecto del conjunto) cubre los tipos y recupera el optimo -> R-VALOR debe ser marginal",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp079] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
