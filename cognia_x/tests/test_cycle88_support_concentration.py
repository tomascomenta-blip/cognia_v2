r"""
CYCLE 88 / H-V4-7f — regresión: ni la concentración extrema del soporte (pool fijo + k_obs=1) atrapa al greedy.

Protege: (a) en la corrida real, bajo pool fijo + k_obs=1 el greedy recupera (gap random−greedy sub-umbral) y el
control comp queda OK; (b) las ramas del veredicto (refutada robusto / apoyada trap-condicional / mixta). Rápido.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle88_support_concentration.py -q
"""
from cognia_x.experiments.exp072_support_concentration import run as X


def test_no_trap_even_fixed_pool_real_run():
    grid = X.run(n=50, k_eval=10, T=30, E=12, eps=0.3, sc=0.5, n_seeds=10)
    sm = X.build_summary(grid, 50, 10)
    # ni el pool fijo a k_obs=1 atrapa (gap sub-umbral 0.05)
    assert not sm["fixed_traps_low"]
    assert sm["gap_fixed_random_minus_greedy"]["1"] <= 0.05
    # fresh tampoco (confirma CYCLE 87)
    assert sm["fresh_robust_low"]
    assert sm["comp_control_ok"]
    assert sm["status"] == "refutada"


def _cell(prod, greedy, explore, rnd):
    return {"product": prod, "learned_greedy": greedy, "learned_explore": explore, "learned_random": rnd}


def _grid(fixed1, fresh1):
    # fixed1/fresh1: (prod, greedy, explore, rnd) en k_obs=1; resto de k_obs sin gap.
    g = {}
    for pool in ("fixed", "fresh"):
        for k in (1, 2, 3, 5, 10):
            g["{}_kobs{}".format(pool, k)] = _cell(0.93, 0.98, 0.98, 0.98)
    g["fixed_kobs1"] = _cell(fixed1[0], fixed1[1], fixed1[2], fixed1[3])
    g["fresh_kobs1"] = _cell(fresh1[0], fresh1[1], fresh1[2], fresh1[3])
    g["comp_fixed_kobs1"] = _cell(0.97, 0.96, 0.96, 0.98)
    return g


def test_verdict_refutada_robust():
    # ni fixed/k_obs=1 atrapa (gap 0.037)
    sm = X.build_summary(_grid(fixed1=(0.93, 0.946, 0.95, 0.983), fresh1=(0.93, 0.95, 0.95, 0.976)), 50, 10)
    assert sm["status"] == "refutada"
    assert not sm["fixed_traps_low"]


def test_verdict_apoyada_trap_conditional():
    # fixed/k_obs=1 atrapa (gap 0.10 > 0.05) pero fresh no (gap 0.02) -> trap condicional a pool fijo
    sm = X.build_summary(_grid(fixed1=(0.93, 0.88, 0.97, 0.98), fresh1=(0.93, 0.96, 0.97, 0.98)), 50, 10)
    assert sm["status"] == "apoyada"
    assert sm["fixed_traps_low"] and sm["fresh_robust_low"]


def test_verdict_mixta_both_trap():
    # fixed Y fresh atrapan (contradiría CYCLE 87) -> mixta
    sm = X.build_summary(_grid(fixed1=(0.93, 0.88, 0.97, 0.98), fresh1=(0.93, 0.88, 0.97, 0.98)), 50, 10)
    assert sm["status"] == "mixta"
