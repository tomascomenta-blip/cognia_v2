r"""
CYCLE 59 / H-V4-1e — regresión: olvido ADAPTATIVO dirigido por sorpresa.

Protege: (a) run_agent es reproducible (mismo seed -> mismo resultado, sin hash() randomizado); (b) las 3 ramas
del veredicto (APOYADA trade-off endógeno / REFUTADA no adapta / MIXTA estabilidad no domina). Rápido.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle59_adaptive_forgetting.py -q
"""
import numpy as np

from cognia_x.experiments.exp045_adaptive_forgetting import run as X


def test_run_agent_reproducible():
    a = X.run_agent(np.random.default_rng(0), 10, 4, 8, 1, 2, 0.15, 64, "adaptive", 0.6)
    b = X.run_agent(np.random.default_rng(0), 10, 4, 8, 1, 2, 0.15, 64, "adaptive", 0.6)
    assert abs(a[0][2] - b[0][2]) < 1e-12      # mismo posterior sobre c_new (reproducible)


def _by_arm(com_new, mild_new, agg_new, agg_mid, ada_new, ada_mid, com_mid=1.0, mild_mid=0.99):
    return {"committed": {"post_c_new_final": com_new, "post_c_old_final": 1 - com_new, "post_c_old_midpoint": com_mid, "n_forget_steps": 0.0},
            "fixed_mild": {"post_c_new_final": mild_new, "post_c_old_final": 0.04, "post_c_old_midpoint": mild_mid, "n_forget_steps": 0.0},
            "fixed_aggressive": {"post_c_new_final": agg_new, "post_c_old_final": 0.04, "post_c_old_midpoint": agg_mid, "n_forget_steps": 0.0},
            "adaptive": {"post_c_new_final": ada_new, "post_c_old_final": 0.04, "post_c_old_midpoint": ada_mid, "n_forget_steps": 25.0}}


def _sm(by_arm):
    return X.build_summary(by_arm, [{}] * 24, K2=12)


def test_verdict_apoyada_endogenous_tradeoff():
    sm = _sm(_by_arm(com_new=0.00, mild_new=0.45, agg_new=0.20, agg_mid=0.20, ada_new=0.45, ada_mid=0.84))
    assert sm["status"] == "apoyada"
    assert sm["adapts"] and sm["stable_phase1"] and sm["beats_aggressive_stability"]


def test_verdict_refutada_no_adapt():
    sm = _sm(_by_arm(com_new=0.00, mild_new=0.45, agg_new=0.20, agg_mid=0.20, ada_new=0.05, ada_mid=0.84))
    assert sm["status"] == "refutada"
    assert not sm["adapts"]


def test_verdict_mixta_stability_not_dominant():
    # adapta pero su estabilidad no domina al aggressive (mid 0.84 no supera a 0.82+0.05)
    sm = _sm(_by_arm(com_new=0.00, mild_new=0.45, agg_new=0.20, agg_mid=0.82, ada_new=0.45, ada_mid=0.84))
    assert sm["status"] == "mixta"
    assert sm["adapts"] and not sm["beats_aggressive_stability"]
