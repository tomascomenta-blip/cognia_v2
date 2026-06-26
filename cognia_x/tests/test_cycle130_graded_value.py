r"""
CYCLE 130 / H-V4-10d — regresión: el producto R-VALOR = relevancia × controlabilidad-descontada-por-costo (w·b̂²/(b̂²+ρ))
generaliza el keystone 129 al régimen GRADUADO + COSTO de acción; es DOMINANTE y su ventaja sobre asignar por un solo factor
ESCALA con la DISOCIACIÓN controlabilidad-relevancia (grande bajo anti-correlación, chica bajo correlación).

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle130_graded_value.py -q
"""
from cognia_x.experiments.exp114_graded_value import run as X


def test_graded_product_real_run():
    grid = X.run(n_seeds=120)
    sm = X.build_summary(grid)
    assert sm["status"] == "apoyada", sm["verdict"]
    assert sm["dominant"], sm
    assert sm["scales_with_dissociation"], sm["margins"]


def test_value_cost_dominant_and_bounded():
    grid = X.run(n_seeds=120)
    for cn in X.CORRS:
        row = grid[cn]
        others = max(row["valor_simple"], row["prediccion"], row["controlabilidad"], row["relevancia"])
        assert row["valor_cost"] >= others - 1e-6, (cn, row)     # VALOR_COST es dominante
        assert row["valor_cost"] <= 1.0 + 1e-6, (cn, row["valor_cost"])   # nunca supera al oracle (pareo correcto)


def test_margin_scales_with_dissociation():
    grid = X.run(n_seeds=120)
    sm = X.build_summary(grid)
    m = sm["margins"]
    assert m["anti"] > m["indep"] > m["corr"], m              # margen cae al correlacionar los factores
    assert m["anti"] > 0.15, m["anti"]                        # bajo disociación el producto gana feo
    assert m["corr"] < 0.15, m["corr"]                        # bajo correlación un solo factor casi basta


def test_single_factors_strong_when_correlated():
    # cuando controlabilidad y relevancia coinciden, un solo factor captura casi todo (margen chico)
    grid = X.run(n_seeds=120)
    row = grid["corr"]
    assert max(row["controlabilidad"], row["relevancia"]) > 0.85, row
