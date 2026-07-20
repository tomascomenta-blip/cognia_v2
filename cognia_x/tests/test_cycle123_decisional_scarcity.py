r"""
CYCLE 123 / H-V4-9c — regresión: la calibración del selector PAGA en la decisión bajo ESCASEZ (de azar a casi-óptimo) y
SATURA bajo abundancia. Capstone positivo: R-VALOR es una brújula decisional.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle123_decisional_scarcity.py -q
"""
from cognia_x.experiments.exp107_decisional_scarcity import run as X


def test_calibration_pays_under_scarcity_real_run():
    grid = X.run(n=60, m=5, n_seeds=100)
    sm = X.build_summary(grid)
    assert sm["calib_pays_scarce"], sm["scarce_gain"]          # bajo escasez la calibración paga
    assert sm["calib_irrelevant_abund"], sm["abund_gain"]      # bajo abundancia satura
    assert sm["status"] == "apoyada"
    assert sm["scarce_gain"] > sm["abund_gain"]                # paga MÁS bajo escasez


def test_perfect_calibration_near_optimal_scarce():
    # ρ=0.9 bajo escasez debe estar cerca de 1.0 (casi-óptimo)
    grid = X.run(n=60, m=5, n_seeds=100)
    assert grid["escaso"]["0.9"] >= 0.85


def test_random_selector_scarce_near_baserate():
    # ρ=0 bajo escasez (q=0.08) debe estar cerca del azar (bajo)
    grid = X.run(n=60, m=5, n_seeds=100)
    assert grid["escaso"]["0.0"] <= 0.3


def _grid(sc, ab):
    rhos = ["0.0", "0.3", "0.6", "0.9"]
    return {"escaso": dict(zip(rhos, sc)), "abundante": dict(zip(rhos, ab))}


def test_verdict_refutada_if_no_pay_scarce():
    # la calibración no paga bajo escasez -> refutada
    sm = X.build_summary(_grid([0.5, 0.5, 0.5, 0.52], [0.9, 0.95, 0.98, 1.0]))
    assert not sm["calib_pays_scarce"]
    assert sm["status"] == "refutada"
