r"""
exp085 — CYCLE 101 / H-V4-8f (rama R-VALOR, extiende el arco de asignación con COSTO de acción HETEROGÉNEO): todo el arco
(83-100) asumió COSTO UNIFORME por pick (presupuesto = #verificaciones). Las acciones reales tienen costo HETEROGÉNEO
(verificar un candidato difícil/largo cuesta más, y a menudo lo valioso es caro). Bajo presupuesto de COSTO total, ¿la
asignación R-VALOR pasa a ser valor-POR-COSTO (eficiencia tipo knapsack), y asignar por valor solo DESPERDICIA el
presupuesto en ítems caros? ¿Y depende de la ESTRUCTURA del objetivo (aditivo vs cobertura-que-satura)?

CONTEXTO. El "salto grande" enfatizó FEEDBACK CON COSTO, pero el costo era UNIFORME (presupuesto = K picks). Este ciclo
añade la pieza realista: COSTO HETEROGÉNEO de cada acción. El principio costo-por-valor (knapsack) es de objetivo ADITIVO;
bajo cobertura que SATURA (CYCLE 95), debés cubrir los tipos sin importar el costo, así que el ratio NO necesariamente
ayuda -> caracterización objeto-dependiente HONESTA.

DISEÑO (numpy). n ítems con valor v_i y COSTO k_i. Presupuesto de COSTO total B. Celdas:
  - additive_uniform: valor ADITIVO (Σv), costo k_i=1 (control). oracle = knapsack fraccionario (cota LP).
  - additive_hetero:  valor ADITIVO, costo HETEROGÉNEO (corr. con v: lo valioso es caro). oracle = knapsack fraccionario.
  - coverage_hetero:  valor de COBERTURA submodular (CYCLE 95: tipo+calidad, satura), costo HETEROGÉNEO. oracle = la MEJOR
                      de {value_greedy, ratio_greedy} sobre valores reales (referencia heurística justa).
Brazos: value_greedy (greedy por valor/ganancia marginal, ignora costo), ratio_greedy (por valor/ganancia POR COSTO),
oracle, random. Todo bajo el presupuesto de costo B. El agente ve v,k RUIDOSOS. Perf = objetivo_real(selección)/oracle.

PREGUNTA FALSABLE (objeto-dependiente):
  - APOYADA si bajo ADITIVO + costo HETERO ratio_greedy >> value_greedy (+>0.05; value malgasta en caros) Y ≈ oracle, Y
    bajo ADITIVO + UNIFORME coinciden; Y (frontera honesta) bajo COBERTURA + hetero el ratio NO ayuda (ratio <= value+0.03,
    porque la cobertura satura -> hay que cubrir los tipos). => R-VALOR bajo costo heterogéneo es valor-POR-COSTO para
    objetivos ADITIVOS; para objetivos que SATURAN (cobertura) el costo importa menos (cubrir manda).
  - REFUTADA si bajo aditivo+hetero el ratio NO supera al valor (el costo no cambia la política aditiva).
  - MIXTA en otro caso.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp085_cost_aware_value.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp085_cost_aware_value.run            # FULL
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
ARMS = ["value_greedy", "ratio_greedy", "oracle", "random"]
CELLS = ["additive_uniform", "additive_hetero", "coverage_hetero"]
CELL_ID = {c: i for i, c in enumerate(CELLS)}
T_TYPES = 5


def _coverage(picks, q, typ, T):
    best = np.zeros(T)
    for i in picks:
        if q[i] > best[typ[i]]:
            best[typ[i]] = q[i]
    return float(best.sum())


def _additive(picks, v):
    return float(np.sum(v[list(picks)])) if len(picks) else 0.0


def _frac_knapsack(v, cost, B):
    """Cota LP (knapsack fraccionario): orden por v/cost, llena hasta B tomando fracción del último."""
    order = np.argsort(v / cost)[::-1]
    rem = B; tot = 0.0
    for i in order:
        if cost[i] <= rem:
            tot += v[i]; rem -= cost[i]
        else:
            tot += v[i] * (rem / cost[i]); rem = 0.0; break
    return tot


def _budget_greedy_additive(v, cost, B, by_ratio):
    n = len(v); chosen = np.zeros(n, dtype=bool); spent = 0.0; picks = []
    score0 = (v / cost) if by_ratio else v
    while True:
        score = np.where(chosen | (spent + cost > B + 1e-9), -1.0, score0)
        j = int(np.argmax(score))
        if score[j] <= 0.0:
            break
        picks.append(j); chosen[j] = True; spent += cost[j]
    return picks


def _budget_greedy_coverage(q, typ, T, cost, B, by_ratio):
    n = len(q); chosen = np.zeros(n, dtype=bool); best = np.zeros(T); spent = 0.0; picks = []
    while True:
        gain = np.maximum(0.0, q - best[typ])
        score = (gain / cost) if by_ratio else gain
        score = np.where(chosen | (spent + cost > B + 1e-9), -1.0, score)
        j = int(np.argmax(score))
        if score[j] <= 0.0:
            break
        picks.append(j); chosen[j] = True; spent += cost[j]
        if q[j] > best[typ[j]]:
            best[typ[j]] = q[j]
    return picks


def _random_under_budget(rng, cost, B, n):
    picks = []; spent = 0.0
    for i in rng.permutation(n):
        if spent + cost[i] <= B + 1e-9:
            picks.append(i); spent += cost[i]
    return picks


def run_cell(n, B, cell, noise, n_seeds):
    acc = {a: [] for a in ARMS}
    coverage = cell.startswith("coverage")
    hetero = cell.endswith("hetero")
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed * 733 + CELL_ID[cell] * 41 + 9)
        q = rng.random(n)
        typ = rng.integers(0, T_TYPES, size=n)
        v = q  # valor por ítem = calidad (para aditivo: Σq)
        cost = np.clip(0.3 + 2.5 * q + rng.normal(0.0, 0.2, size=n), 0.2, None) if hetero else np.ones(n)
        qe = np.clip(q + rng.normal(0.0, noise, size=n), 0.0, 1.0)
        ce = np.clip(cost + rng.normal(0.0, noise, size=n), 0.2, None)

        if coverage:
            obj = lambda p: _coverage(p, q, typ, T_TYPES)
            val_g = _budget_greedy_coverage(qe, typ, T_TYPES, ce, B, by_ratio=False)
            rat_g = _budget_greedy_coverage(qe, typ, T_TYPES, ce, B, by_ratio=True)
            # oracle = mejor de las dos heurísticas sobre valores REALES (referencia justa para cobertura-knapsack)
            o_v = _budget_greedy_coverage(q, typ, T_TYPES, cost, B, by_ratio=False)
            o_r = _budget_greedy_coverage(q, typ, T_TYPES, cost, B, by_ratio=True)
            denom = max(obj(o_v), obj(o_r))
        else:
            obj = lambda p: _additive(p, v)
            val_g = _budget_greedy_additive(qe, ce, B, by_ratio=False)
            rat_g = _budget_greedy_additive(qe, ce, B, by_ratio=True)
            denom = _frac_knapsack(v, cost, B)            # cota LP (>= cualquier solución entera)
        if denom < 1e-9:
            continue
        rnd = _random_under_budget(rng, cost, B, n)
        acc["value_greedy"].append(obj(val_g) / denom)
        acc["ratio_greedy"].append(obj(rat_g) / denom)
        acc["oracle"].append(1.0)
        acc["random"].append(obj(rnd) / denom)
    return {a: round(float(np.mean(acc[a])), 4) for a in ARMS}


def run(n, B, noise, n_seeds):
    return {cell: run_cell(n, B, cell, noise, n_seeds) for cell in CELLS}


def _f(x):
    return "{:.3f}".format(x)


def build_summary(grid):
    au, ah, ch = grid["additive_uniform"], grid["additive_hetero"], grid["coverage_hetero"]
    add_hetero_gain = round(ah["ratio_greedy"] - ah["value_greedy"], 4)        # >0.05 esperado (ratio gana, aditivo+hetero)
    add_oracle_gap = round(ah["oracle"] - ah["ratio_greedy"], 4)
    add_uniform_coincide = round(abs(au["ratio_greedy"] - au["value_greedy"]), 4)  # ~0 (uniforme)
    cov_hetero_gain = round(ch["ratio_greedy"] - ch["value_greedy"], 4)        # <=0.03 esperado (cobertura satura -> ratio no ayuda)

    GAP_THR = 0.05
    COINC_TOL = 0.03
    NEAR_ORACLE = 0.10

    ratio_wins_additive = add_hetero_gain > GAP_THR
    near_oracle_add = add_oracle_gap <= NEAR_ORACLE
    coincide_uniform = add_uniform_coincide <= COINC_TOL
    coverage_ratio_no_help = cov_hetero_gain <= COINC_TOL

    if ratio_wins_additive and near_oracle_add and coincide_uniform and coverage_ratio_no_help:
        status = "apoyada"
        verdict = ("H-V4-8f APOYADA (objeto-dependiente): bajo objetivo ADITIVO + costo HETEROGÉNEO (lo valioso es caro), "
                   "asignar por VALOR solo DESPERDICIA el presupuesto en ítems caros -- value_greedy={avg} -- mientras "
                   "valor-POR-COSTO recupera: ratio_greedy={arg} (+{ahg}, ≈ cota LP gap {aog}). Bajo costo UNIFORME "
                   "coinciden (Δ {auc}). PERO bajo COBERTURA que SATURA + costo hetero el ratio NO ayuda (ratio={crg} vs "
                   "value={cvg}, Δ {chg}<=0.03): hay que CUBRIR los tipos sin importar el costo. => R-VALOR bajo costo de "
                   "acción heterogéneo es valor-POR-COSTO para objetivos ADITIVOS (knapsack); para objetivos que SATURAN "
                   "(cobertura) el costo importa menos (cubrir manda). El costo-por-valor es OBJETO-DEPENDIENTE.").format(
                       avg=_f(ah["value_greedy"]), arg=_f(ah["ratio_greedy"]), ahg=_f(add_hetero_gain), aog=_f(add_oracle_gap),
                       auc=_f(add_uniform_coincide), crg=_f(ch["ratio_greedy"]), cvg=_f(ch["value_greedy"]), chg=_f(cov_hetero_gain))
    elif not ratio_wins_additive:
        status = "refutada"
        verdict = ("H-V4-8f REFUTADA: bajo aditivo+hetero el ratio NO supera al valor (ratio={arg} vs value={avg}, Δ {ahg} "
                   "<= {thr}) -> el costo de acción no cambia la política aditiva.").format(
                       arg=_f(ah["ratio_greedy"]), avg=_f(ah["value_greedy"]), ahg=_f(add_hetero_gain), thr=GAP_THR)
    else:
        status = "mixta"
        verdict = ("H-V4-8f MIXTA: ratio_wins_additive={rw}(+{ahg}) near_oracle={no}(gap {aog}) coincide_uniform={cu}(Δ "
                   "{auc}) coverage_ratio_no_help={cr}(Δ {chg}).").format(rw=ratio_wins_additive, ahg=_f(add_hetero_gain),
                                                                          no=near_oracle_add, aog=_f(add_oracle_gap), cu=coincide_uniform,
                                                                          auc=_f(add_uniform_coincide), cr=coverage_ratio_no_help, chg=_f(cov_hetero_gain))

    return {"grid": grid, "add_hetero_gain": add_hetero_gain, "add_oracle_gap": add_oracle_gap,
            "add_uniform_coincide": add_uniform_coincide, "cov_hetero_gain": cov_hetero_gain,
            "ratio_wins_additive": bool(ratio_wins_additive), "near_oracle_add": bool(near_oracle_add),
            "coincide_uniform": bool(coincide_uniform), "coverage_ratio_no_help": bool(coverage_ratio_no_help),
            "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=int, default=48)
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--B", type=float, default=10.0)
    ap.add_argument("--noise", type=float, default=0.05)
    args = ap.parse_args()
    if args.smoke:
        args.seeds = 12

    logs = []

    def log(mm):
        print(mm, flush=True); logs.append(mm)

    log("[exp085] CYCLE 101 / H-V4-8f — R-VALOR bajo COSTO de acción HETEROGÉNEO: valor-por-costo (objeto-dependiente)")
    log(f"[exp085] n={args.n} B={args.B} T_types={T_TYPES} noise={args.noise} seeds={args.seeds} cells={CELLS}")

    grid = run(args.n, args.B, args.noise, args.seeds)
    sm = build_summary(grid)

    for cell in CELLS:
        c = grid[cell]
        log(f"[exp085] {cell:>16}: value_greedy={c['value_greedy']:.3f} ratio_greedy={c['ratio_greedy']:.3f} "
            f"oracle={c['oracle']:.3f} random={c['random']:.3f}")
    log(f"[exp085] ADITIVO+hetero: ratio−value=+{sm['add_hetero_gain']:.3f} oracle_gap={sm['add_oracle_gap']:.3f} | "
        f"ADITIVO+uniforme: coincide Δ={sm['add_uniform_coincide']:.3f} | COBERTURA+hetero: ratio−value={sm['cov_hetero_gain']:+.3f}")
    log(f"[exp085] ratio_wins_additive={sm['ratio_wins_additive']} near_oracle={sm['near_oracle_add']} coincide_uniform={sm['coincide_uniform']} coverage_ratio_no_help={sm['coverage_ratio_no_help']}")
    log(f"[exp085] VEREDICTO H-V4-8f: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp085_cost_aware_value", "cycle": 101, "hypothesis": "H-V4-8f",
           "claim": "bajo costo de accion HETEROGENEO, R-VALOR es valor-POR-COSTO para objetivos ADITIVOS (knapsack: "
                    "asignar por valor solo malgasta en items caros); para objetivos que SATURAN (cobertura) el costo "
                    "importa menos (cubrir manda) -> el costo-por-valor es objeto-dependiente",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp085] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
