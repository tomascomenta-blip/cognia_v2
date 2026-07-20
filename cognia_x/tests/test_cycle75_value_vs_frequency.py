r"""
CYCLE 75 / H-V4-5e — regresión: el valor != frecuencia (task-definido = frecuencia × costo de fallar).

Protege: (a) en cost-varying value_est (por costo acumulado) supera a lfu_freq (por cuenta) y en cost-uniform
convergen; (b) las 3 ramas del veredicto con los umbrales pre-registrados. Rápido (numpy).

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle75_value_vs_frequency.py -q
"""
from cognia_x.experiments.exp059_value_vs_frequency import run as X


def test_value_beats_lfu_when_cost_varies_and_converges_when_uniform():
    uni = X.run_scenario(n=40, m=8, alpha_f=1.5, alpha_c=1.5, T=2000, n_seeds=6, cost_varying=False)
    var = X.run_scenario(n=40, m=8, alpha_f=1.5, alpha_c=1.5, T=2000, n_seeds=6, cost_varying=True)
    # cost-varying: estimar el valor (costo) vence a estimar la frecuencia
    assert var["value_est"] > var["lfu_freq"] + 0.05
    # cost-uniform: convergen (la ventaja la DRIVE la divergencia, no value_est per se)
    assert abs(uni["value_est"] - uni["lfu_freq"]) < 0.04


def _scn(oracle, lfu, value, recency, random):
    return {"oracle_value": oracle, "lfu_freq": lfu, "value_est": value, "recency": recency, "random": random}


def test_verdict_apoyada():
    uni = _scn(0.506, 0.502, 0.502, 0.370, 0.180)
    var = _scn(0.639, 0.489, 0.636, 0.351, 0.169)
    sm = X.build_summary(uni, var, n=50, m=10)
    assert sm["status"] == "apoyada"
    assert sm["value_beats_lfu"] and sm["value_recovers"] and sm["no_divergence_uniform"]


def test_verdict_refutada_when_cost_irrelevant():
    uni = _scn(0.506, 0.502, 0.502, 0.370, 0.180)
    var = _scn(0.639, 0.620, 0.625, 0.351, 0.169)   # value ~ lfu en cost-varying (costo no separa)
    sm = X.build_summary(uni, var, n=50, m=10)
    assert sm["status"] == "refutada"


def test_verdict_mixta_when_uniform_diverges():
    uni = _scn(0.506, 0.502, 0.460, 0.370, 0.180)   # value_est PEOR que lfu en uniform (|dif|=0.042 >= 0.04)
    var = _scn(0.639, 0.489, 0.636, 0.351, 0.169)   # ayuda y recupera en varying, pero uniform no converge limpio
    sm = X.build_summary(uni, var, n=50, m=10)
    assert sm["status"] == "mixta"
