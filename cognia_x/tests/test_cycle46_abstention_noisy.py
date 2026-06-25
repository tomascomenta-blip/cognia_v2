r"""
CYCLE 46 / H-V4-1k — regresión: abstención calibrada + verificador ruidoso per-step.

Protege: (a) _step_commit acepta el primer noisy-aceptado y marca accepted; (b) con verificador PERFECTO la
abstención da precisión 1.0 sobre las cadenas respondidas (answered = todos los pasos verificados = correctas);
(c) reproducible por seed.

Config diminuta -> ~30s.
Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle46_abstention_noisy.py -q
"""
from types import SimpleNamespace

import numpy as np

from cognia_x.experiments.exp016_verified_bootstrap import addition_task as T
from cognia_x.experiments.exp032_abstention_noisy import run as E


def test_step_commit_perfect_verifier():
    # vnoise=0: acepta exactamente los true_correct; toma el primer correcto
    nrng = np.random.default_rng(0)
    pool = [(5, False), (8, True), (3, True)]
    val, accepted = E._step_commit(pool, 0.0, nrng)
    assert val == 8 and accepted is True


def test_step_commit_none_correct_perfect():
    nrng = np.random.default_rng(0)
    pool = [(5, False), (8, False)]
    val, accepted = E._step_commit(pool, 0.0, nrng)
    assert accepted is False and val == 5      # ninguno verdadero -> no aceptado -> commitea el primero


def _args():
    return SimpleNamespace(n_seed=256, base_steps=250, base_lr=1e-3, warmup=40, batch=32,
                           temperature=1.0, top_k=16, avg=4, per_step_cap=10, M=60)


def test_abstain_precision_perfect_verifier():
    args = _args()
    train_pairs, _ = T.build_split(0, 19, 0.30)
    r = E.run_seed(0, args, train_pairs, Ks=[2], noises=[0.0], log=lambda m: None)
    d = r["by"]["2|0.0"]
    if d["coverage"] > 0:                       # si respondió algo, con verificador perfecto debe ser correcto
        assert d["precision"] == 1.0
    # y la precisión-sobre-respondidas no es peor que commitear-siempre
    assert d["precision"] >= d["commit_always"] - 1e-9


def test_reproducible():
    args = _args()
    train_pairs, _ = T.build_split(0, 19, 0.30)
    a = E.run_seed(0, args, train_pairs, Ks=[2], noises=[0.1], log=lambda m: None)
    b = E.run_seed(0, args, train_pairs, Ks=[2], noises=[0.1], log=lambda m: None)
    assert a["by"]["2|0.1"]["precision"] == b["by"]["2|0.1"]["precision"]
    assert a["by"]["2|0.1"]["commit_always"] == b["by"]["2|0.1"]["commit_always"]
