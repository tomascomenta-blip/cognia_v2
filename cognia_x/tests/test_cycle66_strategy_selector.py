r"""
CYCLE 66 / H-V4-1i — regresión: selector de ESTRATEGIA de memoria.

Protege: (a) run_agent('selector') reproducible; (b) las 3 ramas del veredicto (APOYADA óptimo en ambos /
REFUTADA en ninguno / MIXTA en uno). Rápido (numpy).

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle66_strategy_selector.py -q
"""
import numpy as np

from cognia_x.experiments.exp052_strategy_selector import run as X


def test_run_agent_selector_reproducible():
    a = X.run_agent(np.random.default_rng(0), [3, 7], 12, 20, 0.15, "selector", 0.85, 64)
    b = X.run_agent(np.random.default_rng(0), [3, 7], 12, 20, 0.15, "selector", 0.85, 64)
    assert len(a) == 2 and a == b


def test_verdict_apoyada_optimo_ambos():
    stat = {"committed": 1.0, "fixed": 0.60, "selector": 1.0}
    recur = {"committed": 0.29, "fixed": 0.45, "selector": 0.51}
    sm = X.build_summary(stat, recur, margin=0.10)
    assert sm["status"] == "apoyada" and sm["sel_optimal_stat"] and sm["sel_optimal_recur"]


def test_verdict_refutada_ninguno():
    stat = {"committed": 1.0, "fixed": 0.60, "selector": 0.62}   # ~ fixed (no committea)
    recur = {"committed": 0.29, "fixed": 0.45, "selector": 0.30}  # ~ committed (no olvida)
    sm = X.build_summary(stat, recur, margin=0.10)
    assert sm["status"] == "refutada"


def test_verdict_mixta_uno():
    stat = {"committed": 1.0, "fixed": 0.60, "selector": 1.0}     # óptimo estacionario
    recur = {"committed": 0.29, "fixed": 0.45, "selector": 0.30}  # NO óptimo recurrente
    sm = X.build_summary(stat, recur, margin=0.10)
    assert sm["status"] == "mixta" and sm["sel_optimal_stat"] and not sm["sel_optimal_recur"]
