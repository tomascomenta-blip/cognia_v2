r"""
CYCLE 82 / H-V4-6d — regresión: R-VALOR totalmente endógeno (control_est × verificador) supera a cada marginal.

Protege: (a) en el punto realista rvalue_full vence a ambas marginales y recupera el óptimo, y vence en todo el grid;
(b) las 3 ramas del veredicto. Rápido (numpy).

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle82_endogenous_rvalue.py -q
"""
from cognia_x.experiments.exp066_endogenous_rvalue import run as X


def test_combined_beats_each_marginal_across_grid():
    grid = X.run(n=50, k=10, p_rel=0.3, ctrl_noise=0.5, n_seeds=16)
    rep = grid["S8_e0.1"]
    # combinar vence a cada marginal sola en el punto realista
    assert rep["rvalue_full"] > rep["empowerment"] + 0.05
    assert rep["rvalue_full"] > rep["verifier"] + 0.05
    # y vence a ambas en TODAS las celdas
    assert all(c["rvalue_full"] > max(c["empowerment"], c["verifier"]) for c in grid.values())


def _cell(o, emp, ver, rv, rnd):
    return {"oracle_value": o, "empowerment": emp, "verifier": ver, "rvalue_full": rv, "random": rnd}


def _grid(rep_rv, rep_emp, rep_ver):
    g = {k: _cell(1.0, 0.35, 0.4, 0.6, 0.2) for k in
         ("S2_e0.1", "S32_e0.1", "S2_e0.3", "S8_e0.3", "S32_e0.3")}
    g["S8_e0.1"] = _cell(1.0, rep_emp, rep_ver, rep_rv, 0.2)
    return g


def test_verdict_apoyada():
    sm = X.build_summary(_grid(0.822, 0.400, 0.637), n=50, k=10)
    assert sm["status"] == "apoyada"
    assert sm["beats_both"] and sm["recovers"]


def test_verdict_refutada_when_no_gain():
    sm = X.build_summary(_grid(0.640, 0.400, 0.637), n=50, k=10)  # rvalue ~ verifier
    assert sm["status"] == "refutada"


def test_verdict_mixta_partial():
    sm = X.build_summary(_grid(0.730, 0.400, 0.637), n=50, k=10)  # vence marginales pero <0.80
    assert sm["status"] == "mixta"
