r"""
CYCLE 74 / H-V4-5d — regresión: el estimador de valor auto-selecciona su tasa de olvido (selector full<->decay).

Protege: (a) el selector iguala al mejor experto en cada régimen y usa decay MÁS en no-estacionario que en
estacionario (detección de régimen); (b) las 3 ramas del veredicto con umbrales pre-registrados. Rápido (numpy).

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle74_adaptive_value_memory.py -q
"""
from cognia_x.experiments.exp058_adaptive_value_memory import run as X


def test_selector_no_regret_and_regime_detection():
    stat = X.run_scenario(n=40, m=8, alpha=1.5, K_phase=250, n_phases=5, decay=0.96, beta=0.98, n_seeds=6, nonstationary=False)
    nons = X.run_scenario(n=40, m=8, alpha=1.5, K_phase=250, n_phases=5, decay=0.96, beta=0.98, n_seeds=6, nonstationary=True)
    # iguala al mejor experto en cada regimen
    assert stat["selector"] >= stat["lfu_full"] - 0.04
    assert nons["selector"] >= nons["lfu_decay"] - 0.04
    # detecta el regimen: usa decay MUCHO mas en no-estacionario que en estacionario
    assert nons["_selector_frac_decay"] > stat["_selector_frac_decay"] + 0.3


def _scn(oracle, full, decay, selector, recency, random, frac_decay):
    return {"oracle_current": oracle, "lfu_full": full, "lfu_decay": decay, "selector": selector,
            "recency": recency, "random": random, "_selector_frac_decay": frac_decay}


def test_verdict_apoyada():
    stat = _scn(0.521, 0.511, 0.443, 0.507, 0.382, 0.208, 0.06)
    nons = _scn(0.516, 0.341, 0.430, 0.425, 0.379, 0.205, 0.88)
    sm = X.build_summary(stat, nons, n=50, m=10)
    assert sm["status"] == "apoyada" and sm["no_regret"]


def test_verdict_refutada_when_picks_wrong():
    stat = _scn(0.521, 0.511, 0.443, 0.400, 0.382, 0.208, 0.50)   # estac. selector < decay-0.02 (elige mal)
    nons = _scn(0.516, 0.341, 0.430, 0.425, 0.379, 0.205, 0.88)
    sm = X.build_summary(stat, nons, n=50, m=10)
    assert sm["status"] == "refutada"


def test_verdict_mixta_partial():
    stat = _scn(0.521, 0.511, 0.443, 0.507, 0.382, 0.208, 0.06)   # iguala full en estac.
    nons = _scn(0.516, 0.341, 0.430, 0.380, 0.379, 0.205, 0.60)   # no iguala decay (corto) pero supera a full
    sm = X.build_summary(stat, nons, n=50, m=10)
    assert sm["status"] == "mixta"
