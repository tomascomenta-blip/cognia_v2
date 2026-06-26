r"""
CYCLE 108 / H-V4-8m — regresión (REFUTADA con reversión): a error RMS igualado, un sesgo por-tipo (offset constante,
order-preserving) NO degrada el ranking más que el ruido; a σ alto es MEJOR. Lo que daña es el error que ROMPE el orden.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle108_bias_vs_noise.py -q
"""
import numpy as np

from cognia_x.experiments.exp092_bias_vs_noise import run as X


def test_constant_offset_preserves_intragroup_order():
    # un offset constante por tipo NO cambia el orden DENTRO de cada tipo
    v = np.array([0.2, 0.8, 0.5, 0.9])
    typ = np.array([0, 0, 1, 1])
    v_off = v + 0.3 * np.where(typ == 0, 1.0, -1.0)
    # dentro de tipo 0 (idx 0,1): orden 0<1 preservado; dentro de tipo 1 (idx 2,3): 2<3 preservado
    assert (v_off[0] < v_off[1]) == (v[0] < v[1])
    assert (v_off[2] < v_off[3]) == (v[2] < v[3])


def test_refutada_real_run():
    grid = X.run(n=50, k=10, n_seeds=24)
    sm = X.build_summary(grid)
    # la hipótesis 'bias peor que noise' queda refutada: a σ alto el sesgado NO es peor (gap noisy-biased <= ~0)
    assert not sm["bias_worse"]
    assert sm["status"] == "refutada"
    # de hecho a σ alto el sesgado es mejor (gap negativo)
    assert sm["gap_hi"] < 0.0


def _grid(g01, g02, g03, g04):
    def cell(gap):
        return {"noisy": 0.9, "biased": round(0.9 - gap, 4), "oracle": 1.0, "chance": 0.57}
    return {"s0.1": cell(g01), "s0.2": cell(g02), "s0.3": cell(g03), "s0.4": cell(g04)}


def test_verdict_refutada():
    sm = X.build_summary(_grid(0.001, 0.010, -0.025, -0.041))
    assert sm["status"] == "refutada"


def test_verdict_apoyada_if_bias_were_worse():
    # caso hipotético: el sesgo SÍ degrada más (brecha positiva creciente) -> apoyada
    sm = X.build_summary(_grid(0.02, 0.06, 0.10, 0.15))
    assert sm["bias_worse"] and sm["grows"]
    assert sm["status"] == "apoyada"
