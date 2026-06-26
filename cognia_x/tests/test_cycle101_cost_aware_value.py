r"""
CYCLE 101 / H-V4-8f — regresión: bajo costo de acción HETEROGÉNEO, R-VALOR es valor-POR-COSTO para objetivos ADITIVOS
(knapsack); para objetivos que SATURAN (cobertura) el costo importa menos. Objeto-dependiente. Protege la corrida real y
las ramas del veredicto.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle101_cost_aware_value.py -q
"""
import numpy as np

from cognia_x.experiments.exp085_cost_aware_value import run as X


def test_ratio_beats_value_additive_hetero_real_run():
    grid = X.run(n=50, B=10.0, noise=0.05, n_seeds=32)
    sm = X.build_summary(grid)
    assert sm["ratio_wins_additive"], sm["add_hetero_gain"]       # ratio > value bajo aditivo+hetero
    assert sm["coincide_uniform"], sm["add_uniform_coincide"]     # coinciden bajo uniforme
    assert sm["coverage_ratio_no_help"], sm["cov_hetero_gain"]    # bajo cobertura que satura el ratio no ayuda
    assert sm["status"] == "apoyada"


def test_frac_knapsack_is_upper_bound():
    # la cota LP fraccionaria >= cualquier selección entera bajo presupuesto
    v = np.array([0.9, 0.8, 0.7, 0.2]); cost = np.array([3.0, 2.0, 2.0, 1.0])
    lp = X._frac_knapsack(v, cost, 4.0)
    picks = X._budget_greedy_additive(v, cost, 4.0, by_ratio=True)
    assert lp >= X._additive(picks, v) - 1e-9


def _cell(vg, rg, orc, rnd):
    return {"value_greedy": vg, "ratio_greedy": rg, "oracle": orc, "random": rnd}


def _grid(au, ah, ch):
    return {"additive_uniform": _cell(*au), "additive_hetero": _cell(*ah), "coverage_hetero": _cell(*ch)}


def test_verdict_apoyada():
    sm = X.build_summary(_grid(au=(0.95, 0.973, 1.0, 0.56),
                               ah=(0.885, 0.945, 1.0, 0.77),
                               ch=(0.977, 0.940, 1.0, 0.62)))
    assert sm["status"] == "apoyada"


def test_verdict_refutada_cost_irrelevant():
    # bajo aditivo+hetero el ratio no supera al valor -> el costo no cambia la política
    sm = X.build_summary(_grid(au=(0.95, 0.96, 1.0, 0.56),
                               ah=(0.94, 0.95, 1.0, 0.77),
                               ch=(0.977, 0.940, 1.0, 0.62)))
    assert not sm["ratio_wins_additive"]
    assert sm["status"] == "refutada"


def test_verdict_mixta_coverage_ratio_helps():
    # aditivo+hetero ok PERO bajo cobertura el ratio TAMBIÉN ayuda mucho (no se cumple el patrón objeto-dependiente)
    sm = X.build_summary(_grid(au=(0.95, 0.973, 1.0, 0.56),
                               ah=(0.885, 0.945, 1.0, 0.77),
                               ch=(0.85, 0.95, 1.0, 0.62)))
    assert sm["ratio_wins_additive"] and not sm["coverage_ratio_no_help"]
    assert sm["status"] == "mixta"
