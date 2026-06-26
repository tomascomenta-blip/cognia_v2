r"""
CYCLE 102 / H-V4-8g — regresión: ninguna estrategia de asignación fija domina todos los regímenes (per-costo
objeto-dependiente); un bandit la descubre del feedback con no-regret y supera a la mejor fija única. Converso de CYCLE
92. Protege la corrida real y las ramas del veredicto.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle102_meta_allocation.py -q
"""
from cognia_x.experiments.exp086_meta_allocation import run as X


def test_bandit_no_regret_real_run():
    grid = X.run(n=50, B=10.0, T=50, warmup=12, eps=0.2, noise=0.05, n_seeds=16)
    sm = X.build_summary(grid)
    assert sm["best_differs"], (sm["best_add"], sm["best_cov"])      # la mejor estrategia difiere por régimen
    assert sm["no_single_dominates"]
    assert sm["bandit_no_regret"], (sm["regret_add"], sm["regret_cov"])
    assert sm["bandit_beats"]
    assert sm["status"] == "apoyada"


def _cell(value, ratio, marginal, mpc, bandit, oracle_sel):
    return {"value": value, "ratio": ratio, "marginal": marginal, "marginal_per_cost": mpc,
            "bandit": bandit, "oracle_selector": oracle_sel}


def _grid(ah, ch):
    return {"additive_hetero": _cell(*ah), "coverage_hetero": _cell(*ch)}


def test_verdict_apoyada():
    # ADD: mejor ratio (0.948); COV: mejor value (0.978); bandit no-regret y supera a la mejor fija
    sm = X.build_summary(_grid(ah=(0.889, 0.948, 0.889, 0.948, 0.941, 0.948),
                               ch=(0.978, 0.937, 0.978, 0.937, 0.972, 0.978)))
    assert sm["status"] == "apoyada"


def test_verdict_refutada_one_dominates():
    # 'value' es la mejor (o ≈) en AMBOS regímenes -> ninguna diferencia -> selección innecesaria
    sm = X.build_summary(_grid(ah=(0.95, 0.90, 0.95, 0.90, 0.94, 0.95),
                               ch=(0.978, 0.937, 0.978, 0.937, 0.972, 0.978)))
    assert not sm["no_single_dominates"]
    assert sm["status"] == "refutada"
