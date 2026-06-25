r"""
CYCLE 81 / H-V4-6c — regresión: el verificador como marginal-de-relevancia de R-VALOR (robusto al ruido ε).

Protege: (a) en ε=0 rvalue_verifier reconstruye y vence a empowerment; con ruido alto degrada al control;
(b) las 3 ramas del veredicto. Rápido (numpy).

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle81_verifier_relevance.py -q
"""
from cognia_x.experiments.exp065_verifier_relevance import run as X


def test_reconstructs_at_zero_and_tolerates_then_degrades():
    by = X.run(n=50, k=10, p_rel=0.3, n_seeds=16)
    # eps=0: reconstruye y vence al control
    assert by[0.0]["rvalue_verifier"] >= 0.85
    assert by[0.0]["rvalue_verifier"] > by[0.0]["empowerment"] + 0.05
    # eps alto: el verificador deja de agregar (cae hacia el control)
    assert by[0.5]["rvalue_verifier"] < by[0.0]["rvalue_verifier"] - 0.2


def _cell(o, emp, vo, rv, rnd):
    return {"oracle_value": o, "empowerment": emp, "verifier_only": vo, "rvalue_verifier": rv, "random": rnd}


def _by(rv0, rv1, rv2, rv3, rv5, emp=0.39):
    return {0.0: _cell(1.0, emp, 0.81, rv0, 0.2), 0.1: _cell(1.0, emp, 0.66, rv1, 0.27),
            0.2: _cell(1.0, emp, 0.52, rv2, 0.24), 0.3: _cell(1.0, emp, 0.37, rv3, 0.22),
            0.5: _cell(1.0, emp, 0.22, rv5, 0.24)}


def test_verdict_apoyada():
    sm = X.build_summary(_by(1.000, 0.882, 0.695, 0.590, 0.356), n=50, k=10)
    assert sm["status"] == "apoyada"
    assert sm["recovers_at_zero"] and sm["tolerant"] and sm["eps_star"] >= 0.2


def test_verdict_refutada_when_no_gain_at_zero():
    sm = X.build_summary(_by(0.40, 0.40, 0.40, 0.40, 0.40), n=50, k=10)  # rvalue ~ empowerment en eps=0
    assert sm["status"] == "refutada"


def test_verdict_mixta_fragile():
    sm = X.build_summary(_by(0.95, 0.55, 0.42, 0.41, 0.40), n=50, k=10)  # reconstruye en 0 pero eps*<0.2
    assert sm["status"] == "mixta"
