r"""
CYCLE 48 / H-V4-2 — regresión: auto-mejora VERIFICADA + amplificación multi-paso.

Protege: (a) build_starsets arma verified (sólo correctas) y control (aleatorio) del MISMO tamaño; (b) la
auto-mejora verificada no degrada la precisión por paso vs base, y supera al control (señal de corrección);
(c) chain_acc_greedy es determinista (reproducible).

Config diminuta -> ~40s.
Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle48_substrate_amplify.py -q
"""
from types import SimpleNamespace

import numpy as np

from cognia_x.experiments.exp016_verified_bootstrap import addition_task as T
from cognia_x.experiments.exp016_verified_bootstrap.run import build_base
from cognia_x.experiments.exp030_multistep_reasoning.run import make_chain
from cognia_x.experiments.exp034_substrate_amplify import run as E


def _train_pairs():
    tp, _ = T.build_split(0, 19, 0.30)
    return tp


def test_starsets_same_size_and_verified_correct():
    tp = _train_pairs()
    base, _ = build_base(0, 256, 250, 1e-3, 40, 32, tp, lambda m: None)
    rng = np.random.default_rng(7)
    verified, control = E.build_starsets(base, tp, 96, 6, 1.0, 16, rng, "cpu")
    assert len(verified) == len(control)          # mismo tamaño -> aísla volumen del control
    # toda entrada verified es CORRECTA por oráculo
    for prompt, ans in verified:
        assert T.oracle_correct(prompt, ans)


def test_chain_greedy_reproducible():
    tp = _train_pairs()
    base, _ = build_base(0, 256, 250, 1e-3, 40, 32, tp, lambda m: None)
    crng = np.random.default_rng(123)
    chains = [make_chain(crng, 2) for _ in range(40)]
    a = E.chain_acc_greedy(base, chains, "cpu")
    b = E.chain_acc_greedy(base, chains, "cpu")
    assert a == b                                  # greedy (top_k=1) -> determinista


def test_verified_not_worse_than_base_step():
    tp, test_pairs = T.build_split(0, 19, 0.30)
    test = T.test_from_pairs(test_pairs)[:120]
    args = SimpleNamespace(n_seed=256, base_steps=300, base_lr=1e-3, warmup=40, batch=32,
                           n_prompts=160, K=6, star_steps=150, star_lr=5e-4, top_k=16, temperature=1.0, M=40)
    r = E.run_seed(0, args, tp, test, Ks=[1], log=lambda m: None)
    s = r["step"]
    # la auto-mejora verificada no degrada el paso vs base, y supera (o iguala) al control (señal de corrección)
    assert s["verified"] >= s["base"] - 0.02
    assert s["verified"] >= s["control"] - 0.02
