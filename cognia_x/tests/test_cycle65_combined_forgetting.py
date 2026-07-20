r"""
CYCLE 65 / H-V4-1h — regresión: olvido COMBINADO (piso constante + sorpresa).

Protege: (a) run_agent('combined') es reproducible; (b) las 3 ramas del veredicto (APOYADA cierra el caveat /
REFUTADA no mejora recurrente / MIXTA mejora recurrente pero hunde estacionario). Rápido (numpy).

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle65_combined_forgetting.py -q
"""
import numpy as np

from cognia_x.experiments.exp051_combined_forgetting import run as X


def test_run_agent_combined_reproducible():
    a = X.run_agent(np.random.default_rng(0), [3, 7], 12, 20, 0.15, "combined", 0.7, 64)
    b = X.run_agent(np.random.default_rng(0), [3, 7], 12, 20, 0.15, "combined", 0.7, 64)
    assert len(a) == 2 and a == b


def test_verdict_apoyada():
    stat = {"committed": 1.0, "fixed": 0.61, "meta": 0.86, "combined": 0.62}
    recur = {"committed": 0.32, "fixed": 0.52, "meta": 0.41, "combined": 0.50}
    sm = X.build_summary(stat, recur, margin=0.05)
    assert sm["status"] == "apoyada" and sm["fixes_recurrent"] and sm["keeps_stationary"]


def test_verdict_refutada():
    stat = {"committed": 1.0, "fixed": 0.61, "meta": 0.866, "combined": 0.797}
    recur = {"committed": 0.315, "fixed": 0.517, "meta": 0.408, "combined": 0.404}
    sm = X.build_summary(stat, recur, margin=0.05)
    assert sm["status"] == "refutada" and not sm["fixes_recurrent"]


def test_verdict_mixta():
    stat = {"committed": 1.0, "fixed": 0.61, "meta": 0.86, "combined": 0.50}   # hunde estacionario (<fixed-margin)
    recur = {"committed": 0.32, "fixed": 0.52, "meta": 0.41, "combined": 0.50}  # mejora recurrente
    sm = X.build_summary(stat, recur, margin=0.05)
    assert sm["status"] == "mixta" and sm["fixes_recurrent"] and not sm["keeps_stationary"]
