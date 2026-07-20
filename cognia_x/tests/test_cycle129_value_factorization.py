r"""
CYCLE 129 / H-V4-10c — regresión: el objetivo de CONTROL reconstruye R-VALOR = controlabilidad × relevancia. Con capacidad
de modelado limitada, el criterio VALOR (w·b̂²) bate a cada factor por separado (predicción=varianza, controlabilidad-sola,
relevancia-sola) -> el producto value=ctrl×rel emerge del control; la tesis central 79-82 emerge de la raíz del control.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle129_value_factorization.py -q
"""
from cognia_x.experiments.exp113_value_factorization import run as X


def test_control_reconstructs_value_product_real_run():
    grid = X.run(n_seeds=150)
    sm = X.build_summary(grid)
    assert sm["status"] == "apoyada", sm["verdict"]
    assert sm["value_wins"], sm
    assert sm["value"] > 0.7
    assert sm["margin"] > 0.2


def test_value_beats_every_single_factor():
    grid = X.run(n_seeds=150)
    assert grid["valor"] > grid["prediccion"] + 0.4          # predicción modela el ruido -> ~0
    assert grid["valor"] > grid["controlabilidad"] + 0.2     # controlabilidad-sola: controlable-pero-irrelevante
    assert grid["valor"] > grid["relevancia"] + 0.2          # relevancia-sola: relevante-pero-incontrolable


def test_single_factors_land_near_half_optimal():
    # las bases de un solo factor capturan UNO de los dos modos necesarios -> ~mitad-óptimo
    grid = X.run(n_seeds=150)
    assert 0.25 < grid["controlabilidad"] < 0.75, grid["controlabilidad"]
    assert 0.25 < grid["relevancia"] < 0.75, grid["relevancia"]
    assert grid["prediccion"] < 0.2, grid["prediccion"]      # predicción modela los distractores ruidosos


def test_verdict_refutada_if_product_does_not_win():
    grid = {"valor": 0.5, "prediccion": 0.0, "controlabilidad": 0.48, "relevancia": 0.55}
    sm = X.build_summary(grid)
    assert not sm["value_wins"]
    assert sm["status"] == "refutada", sm["verdict"]
