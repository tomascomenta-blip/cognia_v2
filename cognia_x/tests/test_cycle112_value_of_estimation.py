r"""
CYCLE 112 / H-V4-8q — regresión: el ROI de ESTIMAR el valor (decidir SI estimar es una decisión R-VALOR). Hay un régimen
(baja heterogeneidad o alto costo) donde conviene NO estimar; el cruce sube con el costo.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle112_value_of_estimation.py -q
"""
from cognia_x.experiments.exp096_value_of_estimation import run as X


def test_crossover_real_run():
    grid = X.run(n=50, k=10, sigma=0.1, n_seeds=32)
    sm = X.build_summary(grid)
    assert sm["has_crossover"], sm["verdict"]
    assert sm["status"] == "apoyada"
    # el cruce existe a costo bajo y sube (o se mantiene) con el costo
    assert sm["crossover_spread_lo_cost"] is not None


def test_prior_wins_low_heterogeneity():
    # a baja heterogeneidad, estimar (con costo) no supera al prior
    grid = X.run(n=50, k=10, sigma=0.1, n_seeds=32)
    sm = X.build_summary(grid)
    assert sm["prior_wins_low_het"]


def test_crossover_rises_with_cost():
    grid = X.run(n=50, k=10, sigma=0.1, n_seeds=32)
    sm = X.build_summary(grid)
    lo = sm["crossover_spread_lo_cost"]
    hi = sm["crossover_spread_hi_cost"]
    # umbral con costo alto >= umbral con costo bajo (None=infinito)
    lo_v = 99.0 if lo is None else lo
    hi_v = 99.0 if hi is None else hi
    assert hi_v >= lo_v
