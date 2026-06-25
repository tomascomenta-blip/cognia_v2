r"""
CYCLE 76 / H-V4-5f — regresión: el valor task-definido sobrevive a la observación gateada por la acción.

Protege: (a) value_miss (costo sólo al fallar) ~ value_full (costo siempre visible) y >> lfu_freq bajo
estacionariedad; (b) las 3 ramas del veredicto con los umbrales pre-registrados. Rápido (numpy).

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle76_action_gated_value.py -q
"""
from cognia_x.experiments.exp060_action_gated_value import run as X


def test_value_miss_matches_full_and_beats_lfu():
    res = X.run_scenario(n=40, m=8, alpha_f=1.5, alpha_c=1.5, T=2500, n_seeds=6)
    # observar al fallar iguala a observar siempre (estacionario)
    assert abs(res["value_miss"] - res["value_full"]) < 0.05
    # y vence a la frecuencia sola
    assert res["value_miss"] > res["lfu_freq"] + 0.05


def _ba(o, vfull, vmiss, vexp, lfu, rnd):
    return {"oracle_value": o, "value_full": vfull, "value_miss": vmiss, "value_explore": vexp,
            "lfu_freq": lfu, "random": rnd}


def test_verdict_apoyada():
    sm = X.build_summary(_ba(0.639, 0.634, 0.634, 0.572, 0.490, 0.231), n=50, m=10)
    assert sm["status"] == "apoyada"
    assert sm["miss_recovers"] and sm["miss_beats_lfu"] and sm["miss_matches_full"]


def test_verdict_refutada_when_miss_collapses_to_lfu():
    sm = X.build_summary(_ba(0.639, 0.634, 0.520, 0.500, 0.490, 0.231), n=50, m=10)  # value_miss ~ lfu (+0.03<0.05)
    assert sm["status"] == "refutada"


def test_verdict_mixta_when_miss_below_full():
    sm = X.build_summary(_ba(0.639, 0.634, 0.560, 0.610, 0.490, 0.231), n=50, m=10)  # supera lfu, lejos de full
    assert sm["status"] == "mixta"
