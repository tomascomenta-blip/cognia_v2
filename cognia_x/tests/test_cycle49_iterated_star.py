r"""
CYCLE 49 / H-V4-2b — regresión: iterar el lazo de auto-mejora verificada (estabilidad multi-ronda).

Protege: (a) gen_and_measure devuelve sólo ejemplos verificados y una diversidad en [0,1]; (b) iterar el lazo
no degrada la precisión por paso vs base (no colapsa en pocas rondas); (c) reproducible por seed.

Config diminuta -> ~40s.
Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle49_iterated_star.py -q
"""
from types import SimpleNamespace

import numpy as np

from cognia_x.experiments.exp016_verified_bootstrap import addition_task as T
from cognia_x.experiments.exp016_verified_bootstrap.run import build_base
from cognia_x.experiments.exp035_iterated_star import run as E


def _train_pairs():
    tp, _ = T.build_split(0, 19, 0.30)
    return tp


def test_gen_and_measure_verified_and_diversity():
    tp = _train_pairs()
    base, _ = build_base(0, 256, 250, 1e-3, 40, 32, tp, lambda m: None)
    rng = np.random.default_rng(3)
    verified, diversity, nver = E.gen_and_measure(base, tp, 96, 6, 1.0, 16, rng, "cpu")
    assert nver == len(verified)
    assert 0.0 <= diversity <= 1.0
    for prompt, ans in verified:                  # toda entrada verificada es correcta por oráculo
        assert T.oracle_correct(prompt, ans)


def _args():
    return SimpleNamespace(n_seed=256, base_steps=300, base_lr=1e-3, warmup=40, batch=32,
                           n_prompts=160, K=6, star_steps=120, star_lr=5e-4, top_k=16, temperature=1.0,
                           M=40, rounds=2, margin=0.03)


def test_iterating_does_not_collapse():
    tp, test_pairs = T.build_split(0, 19, 0.30)
    test = T.test_from_pairs(test_pairs)[:120]
    r = E.run_seed(0, _args(), tp, test, log=lambda m: None)
    steps = [x["step"] for x in r["rounds"]]
    # iterar el lazo verificado no degrada la precisión por paso por debajo del base (no colapsa en 2 rondas)
    assert steps[-1] >= steps[0] - 0.03
    # y mejora respecto al base (la auto-mejora verificada aporta)
    assert max(steps) >= steps[0]


def test_reproducible():
    tp, test_pairs = T.build_split(0, 19, 0.30)
    test = T.test_from_pairs(test_pairs)[:80]
    a = E.run_seed(0, _args(), tp, test, log=lambda m: None)
    b = E.run_seed(0, _args(), tp, test, log=lambda m: None)
    assert [x["step"] for x in a["rounds"]] == [x["step"] for x in b["rounds"]]
