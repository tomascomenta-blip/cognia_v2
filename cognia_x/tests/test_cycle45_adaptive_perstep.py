r"""
CYCLE 45 / H-V4-1j — regresión: presupuesto ADAPTATIVO per-step (gastar-hasta-verificar) en cadenas largas.

Protege: (a) _first_verified para en el primer correcto y reporta el costo; (b) el adaptativo no es peor que
el uniforme a igual cómputo en cadenas largas (rescata el compounding); (c) reproducible por seed.

Config diminuta -> ~30s.
Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle45_adaptive_perstep.py -q
"""
from types import SimpleNamespace

from cognia_x.experiments.exp016_verified_bootstrap import addition_task as T
from cognia_x.experiments.exp031_adaptive_perstep import run as E


def test_first_verified_stops_early():
    # primer correcto en índice 2 -> costo 3; commitea su valor
    pool = [(5, False), (7, False), (9, True), (1, True)]
    val, cost = E._first_verified(pool)
    assert val == 9 and cost == 3


def test_first_verified_none_correct():
    pool = [(5, False), (7, False)]
    val, cost = E._first_verified(pool)
    assert val == 5 and cost == 2          # ninguno verifica -> commitea el primero, costo = len


def _args():
    return SimpleNamespace(n_seed=256, base_steps=250, base_lr=1e-3, warmup=40, batch=32,
                           temperature=1.0, top_k=16, avg=4, per_step_cap=10, M=50)


def test_adaptive_not_worse_on_long_chain():
    args = _args()
    train_pairs, _ = T.build_split(0, 19, 0.30)
    r = E.run_seed(0, args, train_pairs, Ks=[6], log=lambda m: None)
    d = r["by_K"][6]
    # a igual cómputo total, reasignar por dificultad no es peor que el uniforme en cadenas largas
    assert d["adaptive"] >= d["uniform"] - 1e-9


def test_reproducible():
    args = _args()
    train_pairs, _ = T.build_split(0, 19, 0.30)
    a = E.run_seed(0, args, train_pairs, Ks=[4], log=lambda m: None)
    b = E.run_seed(0, args, train_pairs, Ks=[4], log=lambda m: None)
    assert a["by_K"][4]["adaptive"] == b["by_K"][4]["adaptive"]
    assert a["by_K"][4]["uniform"] == b["by_K"][4]["uniform"]
