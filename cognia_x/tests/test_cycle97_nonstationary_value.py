r"""
CYCLE 97 / H-V4-8c — regresión: bajo no-estacionariedad el combinador R-VALOR de asignación debe OLVIDAR (decay); el
full-history se vuelve stale (crossover, cf. CYCLE 73). Protege: (a) corrida real (decay>>full bajo drift, coinciden bajo
estacionario); (b) ramas del veredicto.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle97_nonstationary_value.py -q
"""
from cognia_x.experiments.exp081_nonstationary_value import run as X


def test_decay_tracks_drift_real_run():
    grid = X.run(n=50, T=32, D=8, warmup=4, k_obs=10, k_eval=10, decay=0.8, n_seeds=12)
    sm = X.build_summary(grid)
    assert sm["decay_wins_drift"], sm["drift_gain"]       # decay >> full bajo drift
    assert sm["full_ok_stat"], sm["stat_cost"]           # coinciden bajo estacionario
    assert sm["full_degrades"] > 0.1                     # el full se degrada con drift
    assert sm["status"] == "apoyada"


def _cell(full, decay, oracle, chance):
    return {"full_history": full, "decay": decay, "oracle": oracle, "chance": chance}


def _grid(stat, drift):
    return {"stationary": _cell(*stat), "drift": _cell(*drift)}


def test_verdict_apoyada():
    sm = X.build_summary(_grid(stat=(0.968, 0.966, 1.0, 0.35), drift=(0.569, 0.841, 1.0, 0.35)))
    assert sm["status"] == "apoyada"


def test_verdict_refutada_forgetting_no_help():
    # bajo drift decay ≈ full -> olvidar no aporta
    sm = X.build_summary(_grid(stat=(0.968, 0.966, 1.0, 0.35), drift=(0.83, 0.84, 1.0, 0.35)))
    assert not sm["decay_wins_drift"]
    assert sm["status"] == "refutada"


def test_verdict_mixta_decay_beats_full_even_stationary():
    # decay gana bajo drift PERO también supera a full en estacionario (stat_cost<−0.03) -> full no es el mejor estable -> mixta
    sm = X.build_summary(_grid(stat=(0.90, 0.95, 1.0, 0.35), drift=(0.55, 0.84, 1.0, 0.35)))
    assert sm["decay_wins_drift"] and not sm["full_ok_stat"]
    assert sm["status"] == "mixta"
