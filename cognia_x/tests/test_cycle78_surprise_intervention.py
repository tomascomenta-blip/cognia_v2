r"""
CYCLE 78 / H-V4-5h — regresión: la intervención barata sorpresa-gateada vence al slot fijo pero no al baseline pasivo.

Protege: (a) value_surprise > value_explore (barata < burda en costo) pero value_surprise <= value_miss bajo drift
(no paga); (b) las 3 ramas del veredicto. Rápido (numpy).

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle78_surprise_intervention.py -q
"""
from cognia_x.experiments.exp062_surprise_intervention import run as X


def test_surprise_beats_explore_but_not_passive_baseline():
    drift = X.run_scenario(n=40, m=8, alpha_f=1.5, alpha_c=1.5, K_phase=250, n_phases=5, n_seeds=6, drift=True,
                           probe_len=40, surp_margin=0.04)
    # la barata es menos derrochadora que el slot fijo
    assert drift["value_surprise"] > drift["value_explore"]
    # pero no supera al baseline pasivo (no intervenir)
    assert drift["value_surprise"] <= drift["value_miss"] + 0.02


def _scn(o, full, miss, expl, surp, lfu, rnd):
    return {"oracle_value": o, "value_full": full, "value_miss": miss, "value_explore": expl,
            "value_surprise": surp, "lfu_freq": lfu, "random": rnd}


def test_verdict_refutada():
    stat = _scn(0.662, 0.653, 0.653, 0.588, 0.618, 0.502, 0.230)
    drift = _scn(0.660, 0.613, 0.561, 0.532, 0.545, 0.503, 0.230)   # surprise < miss bajo drift
    sm = X.build_summary(stat, drift, n=50, m=10)
    assert sm["status"] == "refutada"
    assert not sm["surprise_helps_drift"]


def test_verdict_apoyada_if_cheap_intervention_pays():
    stat = _scn(0.662, 0.653, 0.653, 0.588, 0.650, 0.502, 0.230)    # surprise ~ miss sin drift (no falsos positivos)
    drift = _scn(0.660, 0.613, 0.561, 0.532, 0.600, 0.503, 0.230)   # surprise >> miss y > explore con drift
    sm = X.build_summary(stat, drift, n=50, m=10)
    assert sm["status"] == "apoyada"


def test_verdict_mixta_if_helps_but_stationary_false_positives():
    stat = _scn(0.662, 0.653, 0.653, 0.588, 0.600, 0.502, 0.230)    # surprise < miss sin drift (falsos positivos)
    drift = _scn(0.660, 0.613, 0.561, 0.532, 0.600, 0.503, 0.230)   # surprise >> miss con drift
    sm = X.build_summary(stat, drift, n=50, m=10)
    assert sm["status"] == "mixta"
