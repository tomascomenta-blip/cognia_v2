r"""
CYCLE 113 / H-V4-8r — regresión: el default de agregación seguro depende de k/T (cobertura si k<T, valor si k>T). Refina
la regla 'asigná por la agregación verdadera' para el caso incierto.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle113_aggregation_robust.py -q
"""
from cognia_x.experiments.exp097_aggregation_robust import run as X


def test_regime_dependent_real_run():
    grid = X.run(n=60, k=None, T=8, n_seeds=32)
    sm = X.build_summary(grid)
    assert sm["regime_dependent"], sm["verdict"]
    assert sm["low_k_safer"] == "submodular"   # k<T -> cobertura segura
    assert sm["hi_k_safer"] == "additive"      # k>T -> valor seguro
    assert sm["status"] == "apoyada"


def test_coverage_oracle_optimal_for_submodular():
    # la cobertura-greedy es la referencia submodular -> rinde 1.0 bajo verdad submodular
    cells = X.run_cell(n=60, k=6, T=8, n_seeds=16)
    assert cells["assume_submodular"]["submodular"] >= 0.99


def test_top_value_optimal_for_additive():
    # top-value es óptimo exacto para additive -> 1.0 bajo verdad additive
    cells = X.run_cell(n=60, k=6, T=8, n_seeds=16)
    assert cells["assume_additive"]["additive"] >= 0.99
