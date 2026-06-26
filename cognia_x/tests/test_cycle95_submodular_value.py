r"""
CYCLE 95 / H-V4-8a — regresión: bajo objetivo NO-aditivo (submodular/cobertura) el valor debe ser MARGINAL (greedy por
ganancia), no absoluto (top-k); bajo aditivo coinciden. Protege: (a) corrida real (marginal >> additive bajo submodular,
coinciden bajo additive); (b) el greedy marginal cubre tipos; (c) ramas del veredicto.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle95_submodular_value.py -q
"""
import numpy as np

from cognia_x.experiments.exp079_submodular_value import run as X


def test_marginal_greedy_covers_types():
    # 3 ítems tipo 0 (alta q) + 1 ítem tipo 1: top-2 absoluto toma 2 del tipo 0 (redundante); marginal cubre ambos tipos
    q = np.array([0.9, 0.85, 0.8, 0.5])
    typ = np.array([0, 0, 0, 1])
    add = list(np.argsort(q)[::-1][:2])             # [0,1] ambos tipo 0
    marg = X._marginal_greedy(q, typ, T=2, k=2, obj="submodular")
    assert set(typ[add]) == {0}                      # absoluto: redundante (sólo tipo 0)
    assert set(typ[marg]) == {0, 1}                  # marginal: cubre ambos tipos
    assert X._submod_value(marg, q, typ, 2) > X._submod_value(add, q, typ, 2)


def test_apoyada_real_run():
    grid = X.run(n=50, T=5, k=10, noise=0.05, n_seeds=16)
    sm = X.build_summary(grid)
    assert sm["marginal_wins_sub"], sm["gap_submodular"]      # marginal > additive bajo submodular
    assert sm["coincide_add"], sm["gap_additive"]            # coinciden bajo additive
    assert sm["marg_near_oracle"]
    assert sm["status"] == "apoyada"


def _cell(ag, mg, orc, rnd):
    return {"additive_greedy": ag, "marginal_greedy": mg, "oracle": orc, "random": rnd}


def _grid(sub, add):
    return {"submodular": _cell(*sub), "additive": _cell(*add)}


def test_verdict_apoyada():
    sm = X.build_summary(_grid(sub=(0.915, 0.991, 1.0, 0.659), add=(0.993, 0.993, 1.0, 0.543)))
    assert sm["status"] == "apoyada"


def test_verdict_refutada_additivity_harmless():
    # additive ≈ marginal aun bajo submodular -> la aditividad es inocua
    sm = X.build_summary(_grid(sub=(0.985, 0.991, 1.0, 0.659), add=(0.993, 0.993, 1.0, 0.543)))
    assert not sm["marginal_wins_sub"]
    assert sm["status"] == "refutada"


def test_verdict_mixta():
    # marginal gana bajo submodular pero NO coincide bajo additive (gap aditivo grande) -> mixta
    sm = X.build_summary(_grid(sub=(0.85, 0.99, 1.0, 0.66), add=(0.80, 0.95, 1.0, 0.54)))
    assert sm["marginal_wins_sub"] and not sm["coincide_add"]
    assert sm["status"] == "mixta"
