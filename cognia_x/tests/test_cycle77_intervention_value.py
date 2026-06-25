r"""
CYCLE 77 / H-V4-5g — regresión: la intervención naive (slot fijo) bajo drift NO paga, aunque el problema sea real.

Protege: (a) bajo drift value_miss pierde respecto a value_full (problema real) pero en estacionario miss=full;
(b) value_explore no supera a value_miss bajo drift (mecanismo burdo); (c) las 3 ramas del veredicto. Rápido (numpy).

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle77_intervention_value.py -q
"""
from cognia_x.experiments.exp061_intervention_value import run as X


def test_problem_real_but_naive_intervention_does_not_pay():
    stat = X.run_scenario(n=40, m=8, alpha_f=1.5, alpha_c=1.5, K_phase=250, n_phases=5, n_seeds=6, drift=False)
    drift = X.run_scenario(n=40, m=8, alpha_f=1.5, alpha_c=1.5, K_phase=250, n_phases=5, n_seeds=6, drift=True)
    # sin drift, observar al fallar iguala a observar siempre (el problema NO existe)
    assert abs(stat["value_miss"] - stat["value_full"]) < 0.03
    # con drift, el problema es real: miss pierde respecto a full
    assert drift["value_miss"] < drift["value_full"] - 0.01
    # pero el mecanismo burdo (slot fijo) no recupera: explore no supera a miss
    assert drift["value_explore"] <= drift["value_miss"]


def _scn(o, full, miss, expl, lfu, rnd):
    return {"oracle_value": o, "value_full": full, "value_miss": miss, "value_explore": expl,
            "lfu_freq": lfu, "random": rnd}


def test_verdict_refutada():
    stat = _scn(0.662, 0.653, 0.653, 0.588, 0.503, 0.230)
    drift = _scn(0.660, 0.613, 0.561, 0.532, 0.503, 0.230)   # explore < miss bajo drift
    sm = X.build_summary(stat, drift, n=50, m=10)
    assert sm["status"] == "refutada"
    assert not sm["explore_helps_drift"]


def test_verdict_apoyada_if_explore_helps_and_neutral_stationary():
    stat = _scn(0.662, 0.653, 0.653, 0.650, 0.503, 0.230)    # explore ~ miss sin drift (neutral)
    drift = _scn(0.660, 0.613, 0.561, 0.640, 0.503, 0.230)   # explore >> miss con drift
    sm = X.build_summary(stat, drift, n=50, m=10)
    assert sm["status"] == "apoyada"


def test_verdict_mixta_if_explore_helps_but_stationary_not_separated():
    stat = _scn(0.662, 0.653, 0.560, 0.650, 0.503, 0.230)    # explore tambien ayuda sin drift (no separa)
    drift = _scn(0.660, 0.613, 0.561, 0.640, 0.503, 0.230)   # explore >> miss con drift
    sm = X.build_summary(stat, drift, n=50, m=10)
    assert sm["status"] == "mixta"
