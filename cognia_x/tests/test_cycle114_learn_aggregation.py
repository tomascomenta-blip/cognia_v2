r"""
CYCLE 114 / H-V4-8s — regresión: aprender la agregación del feedback (bandit) logra no-regret y vence al hedge fijo
(promediado sobre ambas verdades). Cierra 113.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle114_learn_aggregation.py -q
"""
from cognia_x.experiments.exp098_learn_aggregation import run as X


def test_learn_beats_hedge_real_run():
    grid = X.run(n=60, k=6, T=8, rounds=40, eps=0.1, n_seeds=24)
    sm = X.build_summary(grid)
    assert sm["no_regret"], sm["no_regret_gap"]
    assert sm["beats_hedge"], sm["learn_vs_hedge"]
    assert sm["status"] == "apoyada"


def test_learn_adapts_to_each_truth():
    # el learner casi alcanza al best_fixed en CADA verdad por separado
    grid = X.run(n=60, k=6, T=8, rounds=40, eps=0.1, n_seeds=24)
    pt = grid["per_truth"]
    assert pt["additive"]["learn"] >= pt["additive"]["best_fixed"] - 0.08
    assert pt["submodular"]["learn"] >= pt["submodular"]["best_fixed"] - 0.08


def _grid(learn, hedge, best):
    return {"avg": {"learn": learn, "hedge": hedge, "best_fixed": best, "always_add": 0.82, "always_sub": hedge},
            "per_truth": {"additive": {"learn": learn, "hedge": 0.89, "best_fixed": 1.0, "always_add": 1.0, "always_sub": 0.89},
                          "submodular": {"learn": learn, "hedge": 1.0, "best_fixed": 1.0, "always_add": 0.65, "always_sub": 1.0}}}


def test_verdict_refutada_no_gain_over_hedge():
    sm = X.build_summary(_grid(learn=0.95, hedge=0.95, best=1.0))
    assert not sm["beats_hedge"]
    assert sm["status"] == "refutada"
