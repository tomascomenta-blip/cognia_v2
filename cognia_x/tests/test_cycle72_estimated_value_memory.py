r"""
CYCLE 72 / H-V4-5b — regresión: memoria por valor ESTIMADO online (frecuencia/LFU) vs oráculo / recency / random.

Protege: (a) simulate -- oracle (memoria fija top-m por valor verdadero) ~ masa de valor de top-m; estimated
converge por encima de random; anti_value por debajo; (b) las 3 ramas del veredicto (APOYADA/REFUTADA/MIXTA) con
los umbrales pre-registrados (recovers>=70%, +>0.15 vs random, +>0.03 vs recency). Rápido (numpy).

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle72_estimated_value_memory.py -q
"""
import numpy as np

from cognia_x.experiments.exp056_estimated_value_memory import run as X


def test_oracle_matches_top_m_value_mass():
    # bajo IID, el hit-rate del oráculo (memoria fija top-m) converge a la masa de valor de top-m.
    rng = np.random.default_rng(0)
    p = X.gen_values(rng, n=50, alpha=1.5)
    top_mass = float(np.sort(p)[-10:].sum())
    fw, _ = X.simulate(np.random.default_rng(1), p, m=10, T=4000, arm="oracle")
    assert abs(fw - top_mass) < 0.05


def test_estimated_beats_random_and_anti_below():
    rng = np.random.default_rng(3)
    p = X.gen_values(rng, n=50, alpha=1.5)
    est, _ = X.simulate(np.random.default_rng(10), p, m=10, T=4000, arm="estimated")
    rnd, _ = X.simulate(np.random.default_rng(11), p, m=10, T=4000, arm="random")
    anti, _ = X.simulate(np.random.default_rng(12), p, m=10, T=4000, arm="anti_value")
    assert est > rnd + 0.10          # estimar el valor por frecuencia gana a azar
    assert anti < rnd                # la direccion del valor estimado importa


def _ba(oracle, est, rec, rnd, anti):
    return {"oracle": oracle, "estimated": est, "recency": rec, "random": rnd, "anti_value": anti}


def test_verdict_apoyada():
    sm = X.build_summary(_ba(0.508, 0.506, 0.370, 0.219, 0.088), n=50, m=10, T=3000)
    assert sm["status"] == "apoyada"
    assert sm["recovers_most"] and sm["est_beats_random"] and sm["beats_recency"]


def test_verdict_refutada_when_not_beats_recency():
    sm = X.build_summary(_ba(0.508, 0.360, 0.370, 0.219, 0.088), n=50, m=10, T=3000)  # est <= recency
    assert sm["status"] == "refutada"


def test_verdict_mixta_partial_recovery():
    sm = X.build_summary(_ba(0.508, 0.400, 0.350, 0.219, 0.088), n=50, m=10, T=3000)  # gana a ambos, recupera ~63%
    assert sm["status"] == "mixta"
