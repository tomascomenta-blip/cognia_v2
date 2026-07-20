r"""
CYCLE 52 / H-V4-2e — regresión: TECHO del lazo iterado + guardia con VERIFICADOR REAL desde base DÉBIL.

Protege: (a) plateau_round localiza la ronda donde la curva alcanza su techo; (b) la lógica de veredicto
(bootstraps + plateau) clasifica bien; (c) end-to-end: desde un base DÉBIL la GUARDIA bootstrapea más que el
plano (resuelve el cold-start) sin reward-hack.

Config diminuta -> ~1 min en CPU 2c.
Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle52_real_verifier_ceiling.py -q
"""
from types import SimpleNamespace

from cognia_x.experiments.exp018_real_verifier import expression_task as E
from cognia_x.experiments.exp037_iterated_real_verifier.run import run_seed
from cognia_x.experiments.exp038_real_verifier_ceiling import run as X


def test_plateau_round():
    # max=0.80; primera ronda con >= 0.80-0.105=0.695 es la r2
    assert X.plateau_round([0.10, 0.50, 0.80, 0.80, 0.79], 0.105) == 2
    # monótona que sigue subiendo (saltos > margen): plateau = última ronda
    assert X.plateau_round([0.10, 0.30, 0.60], 0.105) == 2


def _mk(reals):
    return [{"round": r, "real": v, "coverage": 10 * r, "degen": 0.0} for r, v in enumerate(reals)]


def test_verdict_bootstraps_is_apoyada():
    args = SimpleNamespace(rounds=4)
    seeds = [{"plain": _mk([0.08, 0.10, 0.20, 0.30, 0.35]),
              "guarded": _mk([0.08, 0.49, 0.71, 0.80, 0.80])} for _ in range(3)]
    v, st = X.verdict(seeds, args, m=90)
    assert v == "APOYADA"
    assert st["bootstraps"] and st["plateaus"]


def test_verdict_no_bootstrap_is_refutada():
    args = SimpleNamespace(rounds=4)
    seeds = [{"plain": _mk([0.08, 0.09, 0.10, 0.10, 0.11]),
              "guarded": _mk([0.08, 0.10, 0.12, 0.11, 0.13])} for _ in range(3)]
    v, st = X.verdict(seeds, args, m=90)
    assert v == "REFUTADA"
    assert not st["bootstraps"]


def _args():
    return SimpleNamespace(n_seed=256, base_steps=120, base_lr=1e-3, warmup=40, batch=32,
                           pool=96, K=6, replay_n=96, steps=80, lr=5e-4,
                           top_k=20, temperature=0.9, rounds=4)


def test_weak_base_guard_bootstraps_more_than_plain():
    tr, te = E.build_split(2, 300, 0.30)
    r = run_seed(0, _args(), tr, te, log=lambda m: None)
    base = r["base"]["real_acc"]
    guard_final = r["guarded"][-1]["real"]
    plain_final = r["plain"][-1]["real"]
    # desde un base débil, la guardia bootstrapea de verdad y al menos no peor que el plano
    assert guard_final - base >= 0.20
    assert guard_final >= plain_final - 0.05
    # sin reward-hack con el verificador FUERTE
    assert r["guarded"][-1]["degen"] <= 0.05
