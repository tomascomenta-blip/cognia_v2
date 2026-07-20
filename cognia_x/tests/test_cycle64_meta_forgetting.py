r"""
CYCLE 64 / H-V4-1g — regresión: olvido META-ADAPTATIVO (estima la tasa de cambio y elige el olvido).

Protege: (a) run_agent('meta') es reproducible y devuelve un post por fase; (b) las 3 ramas del veredicto
(APOYADA iguala el óptimo / MIXTA adapta en dirección / REFUTADA no adapta). Rápido (numpy).

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle64_meta_forgetting.py -q
"""
import numpy as np

from cognia_x.experiments.exp050_meta_forgetting import run as X


def test_run_agent_meta_reproducible():
    a = X.run_agent(np.random.default_rng(0), [3, 7], 12, 20, 0.15, "meta", 0.7, 64)
    b = X.run_agent(np.random.default_rng(0), [3, 7], 12, 20, 0.15, "meta", 0.7, 64)
    assert len(a) == 2 and a == b


def test_metric_for_regime():
    assert X.metric_for_regime([0.9], 1) == 0.9                       # estacionario: final
    assert abs(X.metric_for_regime([0.8, 0.4, 0.6], 3) - 0.5) < 1e-9  # recurrente: media post-cambio


def test_verdict_apoyada_matches_optimum():
    stat = {"committed": 1.0, "fixed": 0.61, "meta": 0.93}
    recur = {"committed": 0.32, "fixed": 0.52, "meta": 0.45}
    sm = X.build_summary(stat, recur, margin=0.10)
    assert sm["status"] == "apoyada"
    assert sm["matches_stat"] and sm["matches_recur"]


def test_verdict_mixta_directional():
    stat = {"committed": 1.0, "fixed": 0.61, "meta": 0.866}
    recur = {"committed": 0.315, "fixed": 0.517, "meta": 0.408}
    sm = X.build_summary(stat, recur, margin=0.10)
    assert sm["status"] == "mixta"
    assert sm["adapts_dir_stat"] and sm["adapts_dir_recur"]
    assert not (sm["matches_stat"] and sm["matches_recur"])


def test_verdict_refutada_no_adaptation():
    stat = {"committed": 1.0, "fixed": 0.61, "meta": 0.60}    # se comporta como el fixed
    recur = {"committed": 0.315, "fixed": 0.517, "meta": 0.32}
    sm = X.build_summary(stat, recur, margin=0.10)
    assert sm["status"] == "refutada"
