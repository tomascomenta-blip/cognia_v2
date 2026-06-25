r"""
CYCLE 73 / H-V4-5c — regresión: el estimador de valor debe OLVIDAR (decay) bajo no-estacionariedad.

Protege: (a) bajo no-estacionariedad lfu_decay supera a lfu_full y lfu_full degrada (cae hacia random); (b) en
estacionario lfu_full >= lfu_decay (olvidar cuesta); (c) las 3 ramas del veredicto con los umbrales pre-registrados.
Rápido (numpy).

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle73_nonstationary_value_memory.py -q
"""
from cognia_x.experiments.exp057_nonstationary_value_memory import run as X


def test_decay_beats_full_under_nonstationarity_and_full_best_when_stationary():
    stat = X.run_scenario(n=40, m=8, alpha=1.5, K_phase=250, n_phases=5, decay=0.96, n_seeds=6, nonstationary=False)
    nons = X.run_scenario(n=40, m=8, alpha=1.5, K_phase=250, n_phases=5, decay=0.96, n_seeds=6, nonstationary=True)
    # no-estacionario: olvidar ayuda
    assert nons["lfu_decay"] > nons["lfu_full"]
    # no-estacionario: full degrada respecto a su propio valor estacionario
    assert nons["lfu_full"] < stat["lfu_full"]
    # estacionario: no-olvidar (full) es al menos tan bueno como olvidar (decay) -> olvidar cuesta
    assert stat["lfu_full"] >= stat["lfu_decay"] - 0.02


def _scn(oracle, full, decay, recency, random):
    return {"oracle_current": oracle, "lfu_full": full, "lfu_decay": decay, "recency": recency, "random": random}


def test_verdict_apoyada():
    stat = _scn(0.521, 0.511, 0.443, 0.382, 0.207)
    nons = _scn(0.516, 0.341, 0.430, 0.379, 0.191)
    sm = X.build_summary(stat, nons, n=50, m=10)
    assert sm["status"] == "apoyada"
    assert sm["decay_beats_full_ns"] and sm["decay_recovers_ns"] and sm["decay_beats_recency_ns"]
    assert sm["tradeoff_real_stationary"]


def test_verdict_refutada_when_decay_not_beats_full():
    stat = _scn(0.521, 0.511, 0.443, 0.382, 0.207)
    nons = _scn(0.516, 0.430, 0.440, 0.379, 0.191)   # decay ~ full (no supera por +0.05)
    sm = X.build_summary(stat, nons, n=50, m=10)
    assert sm["status"] == "refutada"


def test_verdict_mixta_partial_recovery():
    stat = _scn(0.521, 0.511, 0.443, 0.382, 0.207)
    nons = _scn(0.516, 0.300, 0.360, 0.320, 0.191)   # supera a full y recency pero recupera ~52% (<55%)
    sm = X.build_summary(stat, nons, n=50, m=10)
    assert sm["status"] == "mixta"
