r"""
CYCLE 104 / H-V4-8i — regresión: R-VALOR gobierna el TIMING/ABSTENCIÓN del presupuesto. Bajo rondas de riqueza
heterogénea, gastar-donde-rinde + abstenerse >> uniforme (≈ oracle); bajo flat coinciden. Protege la corrida real y las
ramas del veredicto.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle104_abstention_timing.py -q
"""
from cognia_x.experiments.exp088_abstention_timing import run as X


def test_timing_wins_varied_real_run():
    grid = X.run(n_rounds=20, B=20, cap=5, noise=0.08, n_seeds=16)
    sm = X.build_summary(grid)
    assert sm["timing_wins"], sm["varied_gain"]          # threshold >> uniform bajo riquezas variadas
    assert sm["near_oracle"]
    assert sm["coincide_flat"], sm["flat_coincide"]      # coinciden bajo riqueza flat
    assert sm["status"] == "apoyada"


def _cell(uniform, threshold, oracle, random_):
    return {"uniform": uniform, "threshold": threshold, "oracle": oracle, "random": random_}


def _grid(var, flat):
    return {"varied": _cell(*var), "flat": _cell(*flat)}


def test_verdict_apoyada():
    sm = X.build_summary(_grid(var=(0.418, 0.985, 1.0, 0.431), flat=(0.931, 0.954, 1.0, 0.937)))
    assert sm["status"] == "apoyada"


def test_verdict_refutada_timing_irrelevant():
    # bajo variadas threshold ≈ uniform -> el timing no aporta
    sm = X.build_summary(_grid(var=(0.93, 0.95, 1.0, 0.92), flat=(0.931, 0.954, 1.0, 0.937)))
    assert not sm["timing_wins"]
    assert sm["status"] == "refutada"


def test_verdict_mixta_flat_diverges():
    # threshold gana bajo variadas pero NO coincide bajo flat (diverge) -> mixta
    sm = X.build_summary(_grid(var=(0.418, 0.985, 1.0, 0.431), flat=(0.80, 0.95, 1.0, 0.80)))
    assert sm["timing_wins"] and not sm["coincide_flat"]
    assert sm["status"] == "mixta"
