r"""
CYCLE 47 / H-V4-1l — regresión: backtracking/RETRY del paso fallido vs abstención.

Protege: (a) _commit_cost para en el primer noisy-aceptado y reporta el costo (gastar-hasta-verificar); (b)
con verificador perfecto el RETRY no reduce la cobertura vs ABSTAIN (sólo rescata pasos fallidos); (c)
reproducible por seed.

Config diminuta -> ~30s.
Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle47_backtrack_retry.py -q
"""
from types import SimpleNamespace

import numpy as np

from cognia_x.experiments.exp016_verified_bootstrap import addition_task as T
from cognia_x.experiments.exp033_backtrack_retry import run as E


def test_commit_cost_stops_at_first_accept():
    nrng = np.random.default_rng(0)
    # vnoise=0: acepta los true_correct; primer aceptado en índice 2 -> costo 3
    pool = [(5, False), (7, False), (9, True), (1, True)]
    val, accepted, cost = E._commit_cost(pool, 0.0, nrng)
    assert val == 9 and accepted is True and cost == 3


def test_commit_cost_none_accepted():
    nrng = np.random.default_rng(0)
    pool = [(5, False), (7, False)]
    val, accepted, cost = E._commit_cost(pool, 0.0, nrng)
    assert accepted is False and cost == 2 and val == 5


def _args():
    return SimpleNamespace(n_seed=256, base_steps=250, base_lr=1e-3, warmup=40, batch=32,
                           temperature=1.0, top_k=16, avg=4, per_step_cap=8, retry_extra=8, M=60)


def test_retry_not_below_abstain_perfect_verifier():
    args = _args()
    train_pairs, _ = T.build_split(0, 19, 0.30)
    r = E.run_seed(0, args, train_pairs, Ks=[4], noises=[0.0], log=lambda m: None)
    d = r["by"]["4|0.0"]
    # con verificador perfecto el retry sólo rescata pasos fallidos -> cobertura >= abstención (tol muestreo)
    assert d["retry_cov"] >= d["abstain_cov"] - 0.05
    # y la precisión con verificador perfecto sigue 1.0 (lo respondido es correcto)
    if d["retry_cov"] > 0:
        assert d["retry_prec"] == 1.0


def test_reproducible():
    args = _args()
    train_pairs, _ = T.build_split(0, 19, 0.30)
    a = E.run_seed(0, args, train_pairs, Ks=[4], noises=[0.1], log=lambda m: None)
    b = E.run_seed(0, args, train_pairs, Ks=[4], noises=[0.1], log=lambda m: None)
    assert a["by"]["4|0.1"]["retry_cov"] == b["by"]["4|0.1"]["retry_cov"]
    assert a["by"]["4|0.1"]["abstain_prec"] == b["by"]["4|0.1"]["abstain_prec"]
