r"""
CYCLE 51 / H-V4-2d — regresión: lazo ITERADO + guardia (dedup+replay) con VERIFICADOR REAL (sandbox exp018).

Protege: (a) coverage_prompts cuenta prompts distintos del set verificado; (b) seed_correct produce ejemplos
que el VERIFICADOR REAL FUERTE acepta (computación real, no echo); (c) el lazo GUARDED no degrada la real_acc
final por debajo del PLANO; (d) degenerate (echo) no aparece con el verificador FUERTE; (e) reproducible.

Config diminuta -> ~1-2 min en CPU 2c.
Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle51_iterated_real_verifier.py -q
"""
from types import SimpleNamespace

import numpy as np

from cognia_x.experiments.exp018_real_verifier import expression_task as E
from cognia_x.experiments.exp037_iterated_real_verifier import run as X


def test_coverage_counts_distinct_prompts():
    verified = [(b"12=", b"3*4"), (b"12=", b"3*4"), (b"6=", b"2*3")]
    assert X.coverage_prompts(verified) == 2       # 2 prompts distintos


def test_seed_correct_is_strong_verified():
    tr, _ = E.build_split(2, 300, 0.30)
    pairs = X.seed_correct(tr, 40, np.random.default_rng(0))
    assert len(pairs) == 40
    for prompt, expr in pairs:
        # replay = datos de la VERDAD: el verificador REAL FUERTE los acepta (computa el target con operador)
        assert E.verify(prompt, expr, strong=True)


def _args():
    return SimpleNamespace(n_seed=256, base_steps=150, base_lr=1e-3, warmup=40, batch=32,
                           pool=64, K=4, replay_n=64, steps=50, lr=5e-4,
                           top_k=20, temperature=0.9, rounds=2)


def test_guard_not_worse_and_no_echo():
    tr, te = E.build_split(2, 300, 0.30)
    r = X.run_seed(0, _args(), tr, te, log=lambda m: None)
    real_plain_final = r["plain"][-1]["real"]
    real_guard_final = r["guarded"][-1]["real"]
    # la guardia no sacrifica real_acc final vs el plano
    assert real_guard_final >= real_plain_final - 0.10
    # el verificador FUERTE no se hackea por echo: degenerate ~0 en ambos brazos
    assert r["guarded"][-1]["degen"] <= 0.05
    assert r["plain"][-1]["degen"] <= 0.05


def test_reproducible():
    tr, te = E.build_split(2, 300, 0.30)
    a = X.run_seed(1, _args(), tr, te, log=lambda m: None)
    b = X.run_seed(1, _args(), tr, te, log=lambda m: None)
    assert [x["real"] for x in a["guarded"]] == [x["real"] for x in b["guarded"]]
