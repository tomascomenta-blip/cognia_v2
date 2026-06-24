r"""
CYCLE 43 / H-V4-1h — regresión: política ADAPTATIVA (estima fiabilidad del verificador y mezcla).

Protege: (a) el estimador test-retest da r=1 con verificador perfecto y baja con el ruido (calibración); (b)
la mezcla adaptativa no es catastróficamente peor que sus componentes; (c) reproducible por seed.

Config diminuta -> ~30s.
Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle43_adaptive_allocation.py -q
"""
from types import SimpleNamespace

from cognia_x.experiments.exp016_verified_bootstrap import addition_task as T
from cognia_x.experiments.exp029_adaptive_allocation import run as E


def test_reliability_estimator_calibrates():
    # test-retest: todos coinciden -> r=1; coinciden la mitad -> r=0
    assert E.estimate_reliability([True] * 20) == 1.0
    assert E.estimate_reliability([False] * 20) == 0.0
    half = [True] * 10 + [False] * 10
    assert E.estimate_reliability(half) == 0.0          # 2*0.5-1 = 0
    assert 0.0 < E.estimate_reliability([True] * 15 + [False] * 5) < 1.0


def _args():
    return SimpleNamespace(n_seed=256, base_steps=250, base_lr=1e-3, warmup=40, batch=32,
                           temperature=1.0, top_k=16, n_probe=3, avg=5)


def _setup(M=60):
    train_pairs, test_pairs = T.build_split(0, 19, 0.30)
    test = T.test_from_pairs(test_pairs)[:M]
    return _args(), test, train_pairs


def test_r_high_at_zero_noise_low_at_high_noise():
    args, test, train_pairs = _setup()
    r = E.run_seed(0, args, test, train_pairs, noises=[0.0, 0.3], log=lambda m: None)
    assert r["by_noise"][0.0]["r_est"] == 1.0           # verificador perfecto -> r=1
    assert r["by_noise"][0.3]["r_est"] < r["by_noise"][0.0]["r_est"]   # baja con el ruido


def test_adapt_not_catastrophic():
    args, test, train_pairs = _setup()
    r = E.run_seed(1, args, test, train_pairs, noises=[0.0], log=lambda m: None)
    d = r["by_noise"][0.0]
    # a verificador perfecto (r=1) la mezcla usa los MISMOS pesos que CONSEC_V -> no peor salvo ruido de muestreo
    assert d["adapt"] >= d["consequence_v"] - 0.05


def test_reproducible():
    args, test, train_pairs = _setup(M=40)
    a = E.run_seed(0, args, test, train_pairs, noises=[0.1], log=lambda m: None)
    b = E.run_seed(0, args, test, train_pairs, noises=[0.1], log=lambda m: None)
    assert a["by_noise"][0.1]["adapt"] == b["by_noise"][0.1]["adapt"]
    assert a["by_noise"][0.1]["r_est"] == b["by_noise"][0.1]["r_est"]
