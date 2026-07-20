r"""
CYCLE 106 / H-V4-8k — regresión: la calibración (escala) del valor importa para abstención/umbral, no para ranking.
Protege la corrida real y las ramas del veredicto.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle106_calibration_decisions.py -q
"""
from cognia_x.experiments.exp090_calibration_decisions import run as X


def test_calibration_matters_for_threshold_real_run():
    grid = X.run(n=50, k=10, c=0.5, noise=0.05, n_seeds=16)
    sm = X.build_summary(grid)
    assert sm["rank_indiff"], sm["rank_gap"]                # ranking: calibración irrelevante
    assert sm["abstain_needs_calib"], sm["abstain_gain"]    # abstención: calibración necesaria
    assert sm["status"] == "apoyada"


def _cell(cal, mis, orc, ch):
    return {"calibrated": cal, "miscalibrated": mis, "oracle": orc, "chance": ch}


def _grid(rk, ab):
    return {"rank": _cell(*rk), "abstain": _cell(*ab)}


def test_verdict_apoyada():
    sm = X.build_summary(_grid(rk=(0.992, 0.997, 1.0, 0.58), ab=(0.989, 0.821, 1.0, -0.09)))
    assert sm["status"] == "apoyada"


def test_verdict_refutada_calibration_irrelevant_everywhere():
    # calibración tampoco importa para abstención -> refutada
    sm = X.build_summary(_grid(rk=(0.99, 0.99, 1.0, 0.58), ab=(0.95, 0.94, 1.0, -0.09)))
    assert not sm["abstain_needs_calib"]
    assert sm["status"] == "refutada"


def test_verdict_mixta_rank_also_differs():
    # calibración importa para abstención PERO también separa el ranking (no es limpio) -> mixta
    sm = X.build_summary(_grid(rk=(0.99, 0.90, 1.0, 0.58), ab=(0.989, 0.821, 1.0, -0.09)))
    assert sm["abstain_needs_calib"] and not sm["rank_indiff"]
    assert sm["status"] == "mixta"
