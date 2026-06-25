r"""
CYCLE 80 / H-V4-6b — regresión: R-VALOR se reconstruye de dos marginales endógenas (control_est × relevancia_est).

Protege: (a) en rho=0 rvalue_est vence a ambas marginales y recupera el óptimo, y converge con muestras;
(b) las 3 ramas del veredicto. Rápido (numpy).

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle80_value_reconstruction.py -q
"""
from cognia_x.experiments.exp064_value_reconstruction import run as X


def test_product_reconstructs_value_and_converges():
    by = X.run(n=40, k=8, obs_noise=0.5, n_seeds=16)
    hi = by["rho0"][64]
    # el producto vence a cada marginal sola donde divergen
    assert hi["rvalue_est"] > hi["empowerment"] + 0.05
    assert hi["rvalue_est"] > hi["relevance"] + 0.05
    # recupera (casi) el optimo
    assert hi["rvalue_est"] >= 0.85
    # converge con mas muestras
    assert by["rho0"][64]["rvalue_est"] >= by["rho0"][1]["rvalue_est"]


def _cell(o, emp, rel, rv, rnd):
    return {"oracle_value": o, "empowerment": emp, "relevance": rel, "rvalue_est": rv, "random": rnd}


def _by(rv64, emp64, rel64, rv1):
    base = {1: _cell(1.0, 0.6, 0.6, rv1, 0.4), 4: _cell(1.0, 0.65, 0.65, (rv1 + rv64) / 2, 0.4),
            16: _cell(1.0, emp64, rel64, rv64 - 0.02, 0.4), 64: _cell(1.0, emp64, rel64, rv64, 0.4)}
    rho1 = {S: _cell(1.0, 0.98, 0.97, 0.99, 0.43) for S in (1, 4, 16, 64)}
    return {"rho0": base, "rho1": rho1}


def test_verdict_apoyada():
    sm = X.build_summary(_by(0.984, 0.709, 0.729, 0.686), n=40, k=8)
    assert sm["status"] == "apoyada"
    assert sm["beats_marginals"] and sm["recovers_oracle"] and sm["marginals_stuck"]


def test_verdict_refutada_when_product_no_better():
    sm = X.build_summary(_by(0.730, 0.720, 0.729, 0.700), n=40, k=8)  # rvalue ~ best marginal
    assert sm["status"] == "refutada"


def test_verdict_mixta_partial_reconstruction():
    sm = X.build_summary(_by(0.820, 0.709, 0.729, 0.650), n=40, k=8)  # supera marginales pero <0.85
    assert sm["status"] == "mixta"
