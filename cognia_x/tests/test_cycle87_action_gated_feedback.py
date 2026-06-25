r"""
CYCLE 87 / H-V4-7e — regresión: bajo feedback action-gated la explotación greedy recupera sin explorar (no trap).

Protege: (a) en la corrida real, learned_greedy recupera bajo sustitutos (vence al producto) e iguala al buffer
insesgado, sin trampa de sesgo de selección; (b) las ramas del veredicto (refutada sin-trampa / apoyada con-trampa /
refutada exploración-no-rescata). Rápido (numpy, T/E reducidos).

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle87_action_gated_feedback.py -q
"""
from cognia_x.experiments.exp071_action_gated_feedback import run as X


def test_no_trap_real_run():
    grid = X.run(n=50, k=10, T=20, E=12, eps=0.3, sc=0.5, n_seeds=10)
    sm = X.build_summary(grid, 50, 10)
    # greedy recupera bajo sustitutos (vence al producto) e iguala al buffer insesgado
    assert sm["subs_greedy"] > sm["subs_product"] + 0.02
    assert sm["subs_greedy"] >= sm["subs_random"] - 0.03
    # no hay trampa de sesgo de selección
    assert not sm["trap"]
    assert sm["status"] == "refutada"


def _grid(prod, greedy, explore, rnd):
    cell = {"oracle": 1.0, "product": prod, "learned_greedy": greedy, "learned_explore": explore,
            "learned_random": rnd, "random": 0.2}
    comp = {"oracle": 1.0, "product": 0.97, "learned_greedy": 0.98, "learned_explore": 0.98,
            "learned_random": 0.98, "random": 0.2}
    return {"subs": cell, "comp": comp}


def test_verdict_refutada_no_trap():
    # greedy supera al producto por >0.02 sin explorar -> no hay trampa
    sm = X.build_summary(_grid(prod=0.929, greedy=0.979, explore=0.979, rnd=0.980), 50, 10)
    assert sm["status"] == "refutada"
    assert not sm["trap"]


def test_verdict_apoyada_trap_and_rescue():
    # greedy atrapado (~producto) y explore rescata hasta el techo insesgado
    sm = X.build_summary(_grid(prod=0.929, greedy=0.935, explore=0.975, rnd=0.980), 50, 10)
    assert sm["status"] == "apoyada"
    assert sm["trap"] and sm["explore_rescues"]


def test_verdict_refutada_explore_no_rescue():
    # greedy atrapado pero explore tampoco rescata (no supera a greedy por >0.03)
    sm = X.build_summary(_grid(prod=0.929, greedy=0.935, explore=0.945, rnd=0.980), 50, 10)
    assert sm["status"] == "refutada"
    assert sm["trap"] and not sm["explore_rescues"]
