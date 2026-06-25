r"""
CYCLE 68 / H-V4-1j — regresión: selector de 3 estrategias de memoria.

Protege: (a) run_agent('selector3') reproducible con fases asimétricas; (b) las 3 ramas del veredicto (APOYADA
3/3 / MIXTA 2/3 / REFUTADA <=1/3). Rápido (numpy).

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle68_strategy_selector3.py -q
"""
import numpy as np

from cognia_x.experiments.exp053_strategy_selector3 import run as X


def test_run_agent_selector3_reproducible():
    a = X.run_agent(np.random.default_rng(0), [3, 7], [20, 10], 20, 0.15, "selector3", 0.6, 64)
    b = X.run_agent(np.random.default_rng(0), [3, 7], [20, 10], 20, 0.15, "selector3", 0.6, 64)
    assert len(a) == 2 and a == b


def _bg(est_sel, ais_sel, rec_sel):
    return {"estacionario": {"committed": 1.0, "fixed": 0.60, "surprise_gate": 0.85, "selector3": est_sel},
            "aislado": {"committed": 0.0, "fixed": 0.41, "surprise_gate": 0.59, "selector3": ais_sel},
            "recurrente": {"committed": 0.29, "fixed": 0.45, "surprise_gate": 0.58, "selector3": rec_sel}}


def test_verdict_apoyada_3de3():
    sm = X.build_summary(_bg(0.95, 0.55, 0.45), margin=0.10)
    assert sm["status"] == "apoyada" and sm["n_optimal"] == 3


def test_verdict_mixta_2de3():
    sm = X.build_summary(_bg(0.903, 0.44, 0.51), margin=0.10)   # aislado falla (0.44 < 0.59-0.10)
    assert sm["status"] == "mixta" and sm["n_optimal"] == 2
    assert not sm["near_optimal"]["aislado"]


def test_verdict_refutada_1de3():
    sm = X.build_summary(_bg(0.95, 0.10, 0.30), margin=0.10)     # aislado y recurrente fallan
    assert sm["status"] == "refutada" and sm["n_optimal"] <= 1
