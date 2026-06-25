r"""
CYCLE 50 / H-V4-2c — regresión: guardia de diversidad (dedup + replay) en el lazo iterado.

Protege: (a) coverage_prompts cuenta prompts distintos; (b) seed_correct produce ejemplos CORRECTOS por
oráculo; (c) el lazo GUARDED no degrada la precisión final por debajo del PLANO (la guardia no cuesta
precisión); (d) reproducible por seed.

Config diminuta -> ~50s.
Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle50_diversity_guard.py -q
"""
from types import SimpleNamespace

import numpy as np

from cognia_x.experiments.exp016_verified_bootstrap import addition_task as T
from cognia_x.experiments.exp036_diversity_guard import run as E


def test_coverage_counts_distinct_prompts():
    verified = [(b"3+4=", b"7\n"), (b"3+4=", b"7\n"), (b"5+1=", b"6\n")]
    assert E.coverage_prompts(verified) == 2       # 2 prompts distintos


def test_seed_correct_is_correct():
    tp, _ = T.build_split(0, 19, 0.30)
    pairs = E.seed_correct(tp, 30, np.random.default_rng(0))
    assert len(pairs) == 30
    for prompt, ans in pairs:
        assert T.oracle_correct(prompt, ans)       # replay = datos de la VERDAD


def _args():
    return SimpleNamespace(n_seed=256, base_steps=250, base_lr=1e-3, warmup=40, batch=32,
                           n_prompts=128, K=6, replay_n=96, star_steps=100, star_lr=5e-4,
                           top_k=16, temperature=1.0, rounds=2, margin=0.03)


def test_guard_not_worse_than_plain_final():
    tp, test_pairs = T.build_split(0, 19, 0.30)
    test = T.test_from_pairs(test_pairs)[:120]
    r = E.run_seed(0, _args(), tp, test, log=lambda m: None)
    step_plain_final = r["plain"][-1]["step"]
    step_guard_final = r["guarded"][-1]["step"]
    # la guardia no sacrifica precisión final vs el plano (típicamente la mejora)
    assert step_guard_final >= step_plain_final - 0.05


def test_reproducible():
    tp, test_pairs = T.build_split(0, 19, 0.30)
    test = T.test_from_pairs(test_pairs)[:80]
    a = E.run_seed(0, _args(), tp, test, log=lambda m: None)
    b = E.run_seed(0, _args(), tp, test, log=lambda m: None)
    assert [x["step"] for x in a["guarded"]] == [x["step"] for x in b["guarded"]]
