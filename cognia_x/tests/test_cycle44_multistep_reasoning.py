r"""
CYCLE 44 / H-V4-1i — regresión: razonamiento MULTI-PASO (verif intermedia vs sólo-final).

Protege: (a) make_chain produce trazas consistentes con la suma mod 20; (b) parse_value parsea respuestas;
(c) la verificación por-paso (step-wise) no es peor que la sólo-final (end-to-end) cuando los errores se
componen (K>1); (d) reproducible por seed.

Config diminuta -> ~30s.
Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle44_multistep_reasoning.py -q
"""
from types import SimpleNamespace

import numpy as np

from cognia_x.experiments.exp016_verified_bootstrap import addition_task as T
from cognia_x.experiments.exp030_multistep_reasoning import run as E


def test_make_chain_consistent():
    rng = np.random.default_rng(0)
    r0, a, ref = E.make_chain(rng, 4)
    assert len(a) == 4 and len(ref) == 4
    r = r0
    for ai, ri in zip(a, ref):
        r = (r + ai) % E.MOD
        assert r == ri
        assert 0 <= ri < E.MOD


def test_parse_value():
    assert E.parse_value(b"28\n") == 28
    assert E.parse_value(b"5\n") == 5
    assert E.parse_value(b"x\n") is None
    assert E.parse_value(b"\n") is None


def _args():
    return SimpleNamespace(n_seed=256, base_steps=250, base_lr=1e-3, warmup=40, batch=32,
                           temperature=1.0, top_k=16, k=4, M=50)


def test_stepwise_not_worse_when_compounding():
    args = _args()
    train_pairs, _ = T.build_split(0, 19, 0.30)
    r = E.run_seed(0, args, train_pairs, Ks=[4], log=lambda m: None)
    d = r["by_K"][4]
    # con K=4 la verificación por-paso corta el compounding -> no peor que la sólo-final
    assert d["step_wise"] >= d["end_to_end"] - 1e-9


def test_reproducible():
    args = _args()
    train_pairs, _ = T.build_split(0, 19, 0.30)
    a = E.run_seed(0, args, train_pairs, Ks=[2], log=lambda m: None)
    b = E.run_seed(0, args, train_pairs, Ks=[2], log=lambda m: None)
    assert a["by_K"][2]["step_wise"] == b["by_K"][2]["step_wise"]
    assert a["by_K"][2]["end_to_end"] == b["by_K"][2]["end_to_end"]
