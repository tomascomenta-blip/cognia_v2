"""
CYCLE 30 — regresion del verificador RUIDOSO (exp017): el modelo de ruido de falso-positivo.

- test_noisy_accept_eps0: eps=0 (oraculo perfecto) -> acepta SOLO las correctas.
- test_noisy_accept_eps1: eps=1 -> acepta TODAS (correctas + incorrectas).
- test_noisy_accept_monotone: el nº aceptado crece (no decrece) con eps.

Correr: .\\venv312\\Scripts\\python.exe -m pytest cognia_x/tests/test_cycle30_noisy.py -q
"""
import numpy as np

from cognia_x.experiments.exp017_noisy_verifier.run import noisy_accept


def _pool():
    # (prompt, emit, is_correct): 3 correctas, 4 incorrectas
    return [("a", "x", True), ("b", "y", True), ("c", "z", True),
            ("d", "w", False), ("e", "v", False), ("f", "u", False), ("g", "t", False)]


def test_noisy_accept_eps0():
    acc = noisy_accept(_pool(), 0.0, np.random.default_rng(0))
    assert len(acc) == 3                       # solo las 3 correctas
    assert all(p in ("a", "b", "c") for p, _ in acc)


def test_noisy_accept_eps1():
    acc = noisy_accept(_pool(), 1.0, np.random.default_rng(0))
    assert len(acc) == 7                       # todas (correctas + incorrectas)


def test_noisy_accept_monotone():
    pool = _pool()
    counts = [len(noisy_accept(pool, e, np.random.default_rng(0))) for e in (0.0, 0.3, 0.6, 1.0)]
    assert counts[0] == 3 and counts[-1] == 7
    assert all(counts[i] <= counts[i + 1] for i in range(len(counts) - 1))  # no decrece con eps
