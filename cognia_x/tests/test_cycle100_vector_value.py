r"""
CYCLE 100 / H-V4-8e — regresión: bajo objetivo VECTOR egalitario (min) y ASIMÉTRICO, la suma naive desbalancea y falla;
la selección MARGINAL en la agregación real balancea y recupera; bajo simetría/lineal la suma basta. Protege la corrida
real y las ramas del veredicto.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle100_vector_value.py -q
"""
import numpy as np

from cognia_x.experiments.exp084_vector_value import run as X


def test_marginal_balances_min_objective():
    # 2 ítems alto-v1/bajo-v2 + 2 alto-v2/bajo-v1: sum elige por total; marginal balancea min(ΣV1,ΣV2)
    v1 = np.array([0.9, 0.85, 0.1, 0.15])
    v2 = np.array([0.1, 0.15, 0.9, 0.85])
    summ = X._marginal_greedy(v1, v2, 2, "sum")          # bajo sum: top-2 por v1+v2
    marg = X._marginal_greedy(v1, v2, 2, "min")          # bajo min: balancea
    assert X._agg(marg, v1, v2, "min") >= X._agg([0, 1], v1, v2, "min")   # marginal >= elegir los 2 alto-v1 (min=0)


def test_apoyada_real_run():
    grid = X.run(n=50, m=10, noise=0.05, anti_noise=0.15, n_seeds=16)
    sm = X.build_summary(grid)
    assert sm["asym_needs_marg"], sm["asym_marg_vs_sum"]      # bajo asimetría la suma falla, marginal recupera
    assert sm["near_oracle"]
    assert sm["sym_sum_suffices"]                            # bajo simetría la suma basta
    assert sm["lin_coincides"]                               # bajo lineal coinciden
    assert sm["status"] == "apoyada"


def _cell(o1, sg, mg, orc, rnd):
    return {"obj1_greedy": o1, "sum_greedy": sg, "marginal_greedy": mg, "oracle": orc, "random": rnd}


def _grid(asym, sym, lin):
    return {"min_asym": _cell(*asym), "min_sym": _cell(*sym), "sum_lin": _cell(*lin)}


def test_verdict_apoyada():
    sm = X.build_summary(_grid(asym=(0.23, 0.52, 0.98, 1.0, 0.59),
                               sym=(0.24, 0.96, 0.99, 1.0, 0.80),
                               lin=(0.87, 0.985, 0.985, 1.0, 0.84)))
    assert sm["status"] == "apoyada"


def test_verdict_refutada_sum_balances_even_asym():
    # ni bajo asimetría la suma falla -> refutada
    sm = X.build_summary(_grid(asym=(0.23, 0.95, 0.98, 1.0, 0.59),
                               sym=(0.24, 0.96, 0.99, 1.0, 0.80),
                               lin=(0.87, 0.985, 0.985, 1.0, 0.84)))
    assert not sm["asym_needs_marg"]
    assert sm["status"] == "refutada"


def test_verdict_mixta_oracle_gap():
    # marginal supera a la suma bajo asimetría pero NO alcanza el oracle (gap grande) -> mixta
    sm = X.build_summary(_grid(asym=(0.23, 0.52, 0.80, 1.0, 0.59),
                               sym=(0.24, 0.96, 0.99, 1.0, 0.80),
                               lin=(0.87, 0.985, 0.985, 1.0, 0.84)))
    assert sm["asym_needs_marg"] and not sm["near_oracle"]
    assert sm["status"] == "mixta"
