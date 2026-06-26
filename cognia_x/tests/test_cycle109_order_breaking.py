r"""
CYCLE 109 / H-V4-8n — regresión (completa 108): a RMS igualado el daño a la asignación sigue order-preserving > ruido >
order-breaking-sistemático. El lever es ROMPER EL ORDEN.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle109_order_breaking.py -q
"""
from cognia_x.experiments.exp093_order_breaking import run as X


def test_order_holds_real_run():
    grid = X.run(n=50, k=10, n_seeds=24)
    sm = X.build_summary(grid)
    assert sm["order_holds_hi"], (sm["mono_vs_noisy_hi"], sm["noisy_vs_nonmono_hi"])
    assert sm["order_holds_mid"]
    assert sm["status"] == "apoyada"
    # el order-breaking sistemático (nonmono) es claramente el peor
    assert sm["noisy_vs_nonmono_hi"] > sm["mono_vs_noisy_hi"]


def _grid(*cells):
    # cells: lista de (mono, noisy, nonmono) por σ
    sig = [0.1, 0.2, 0.3, 0.4]
    return {"s{}".format(s): {"biased_mono": m, "noisy": n, "biased_nonmono": nm, "oracle": 1.0, "chance": 0.55}
            for s, (m, n, nm) in zip(sig, cells)}


def test_verdict_apoyada():
    sm = X.build_summary(_grid((0.974, 0.972, 0.982), (0.904, 0.923, 0.787), (0.889, 0.869, 0.638), (0.871, 0.826, 0.645)))
    assert sm["status"] == "apoyada"


def test_verdict_refutada_nonmono_not_worst():
    # nonmono NO es el peor (≈ noisy) -> refutada
    sm = X.build_summary(_grid((0.974, 0.972, 0.97), (0.904, 0.923, 0.92), (0.889, 0.869, 0.87), (0.871, 0.826, 0.83)))
    assert sm["status"] == "refutada"
