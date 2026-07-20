r"""
CYCLE 131 / H-V4-10e — regresión (versión HONESTA tras verificación adversarial): el sondeo dirigido por valor (active
inference) compra eficiencia muestral MODERADA sólo cuando la controlabilidad debe DESCUBRIRSE y a presupuesto MEDIO
(U-invertida robusta); con relevancia conocida el efecto es chico. La afirmación original 'paga en escasez' quedó REFUTADA.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle131_active_probing.py -q
"""
from cognia_x.experiments.exp115_active_probing import run as X


def test_mixta_inverted_u_real_run():
    grid = X.run(n_seeds=120)
    sm = X.build_summary(grid)
    assert sm["status"] == "mixta", sm["verdict"]            # fenómeno real pero MODERADO
    assert sm["shape_inverted_u"], sm["gaps_descubrir"]
    assert sm["dominates_descubrir"], sm["gaps_descubrir"]
    assert sm["known_small"], (sm["peak_conocida"], sm["peak_descubrir"])
    assert sm["moderate"], sm["peak_descubrir"]


def test_inverted_u_shape_peak_interior_above_edges():
    grid = X.run(n_seeds=120)
    sm = X.build_summary(grid)
    g = sm["gaps_descubrir"]
    peak_idx = g.index(max(g))
    assert 0 < peak_idx < len(g) - 1, (peak_idx, g)          # el pico está en un presupuesto INTERIOR (medio)
    assert sm["peak_descubrir"] > sm["edge_descubrir"] + 0.05, sm   # el pico SUPERA claramente a los bordes
    assert sm["peak_descubrir"] > 0.10, sm["peak_descubrir"]


def test_discover_regime_beats_known_regime():
    # el efecto vive cuando hay que DESCUBRIR la controlabilidad, no cuando la relevancia es dada
    grid = X.run(n_seeds=120)
    sm = X.build_summary(grid)
    assert sm["peak_descubrir"] > sm["peak_conocida"] + 0.04, (sm["peak_descubrir"], sm["peak_conocida"])


def test_active_does_not_lose_in_discover():
    # la activa robusta no PIERDE significativamente en ningún presupuesto fiteable (pareado)
    grid = X.run(n_seeds=120)
    assert min(grid["descubrir"][str(B)]["gap"] for B in X.BUDGETS) > -0.03


def _g(desc, con):
    return {"descubrir": {str(B): {"activa": 0, "pasiva": 0, "gap": desc[i]} for i, B in enumerate(X.BUDGETS)},
            "conocida": {str(B): {"activa": 0, "pasiva": 0, "gap": con[i]} for i, B in enumerate(X.BUDGETS)}}


def test_verdict_refutada_if_no_inverted_u():
    # gaps planos/monótonos (sin pico interior sobre los bordes) -> refutada
    sm = X.build_summary(_g(desc=[0.02, 0.03, 0.04, 0.05, 0.06], con=[0.0, 0.0, 0.0, 0.0, 0.0]))
    assert not sm["shape_inverted_u"]
    assert sm["status"] == "refutada", sm["verdict"]
