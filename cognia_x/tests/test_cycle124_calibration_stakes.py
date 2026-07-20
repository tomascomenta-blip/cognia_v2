r"""
CYCLE 124 / H-V4-9d — regresión: las apuestas de la calibración del selector son REGIME-DIRECCIONALES (anti-diagonal).
Bajo ESCASEZ pesa el UPSIDE de la buena calibración (gemas raras); bajo ABUNDANCIA pesa el DOWNSIDE de la anti-calibración
(encuentra fiablemente las raras minas -> catástrofe). Refina 123 ('irrelevante bajo abundancia' sólo vale para el upside).

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle124_calibration_stakes.py -q
"""
from cognia_x.experiments.exp108_calibration_stakes import run as X


def test_anti_diagonal_real_run():
    grid = X.run(n=60, m=5, n_seeds=120)
    sm = X.build_summary(grid)
    assert sm["status"] == "apoyada", sm["verdict"]
    assert sm["anti_diagonal"], sm
    # escasez: UPSIDE grande, DOWNSIDE chico
    assert sm["upside_scarce"] > 0.30, sm["upside_scarce"]
    assert sm["downside_scarce"] < 0.20, sm["downside_scarce"]
    # abundancia: UPSIDE chico (satura), DOWNSIDE grande (catástrofe)
    assert sm["upside_abund"] < 0.20, sm["upside_abund"]
    assert sm["downside_abund"] > 0.30, sm["downside_abund"]


def test_anticalibration_catastrophic_under_abundance():
    # el corazón del refinamiento de 123: bajo abundancia, anti-calibración (ρ=-0.9) << azar (ρ=0)
    grid = X.run(n=60, m=5, n_seeds=120)
    assert grid["abundante"]["0.0"] >= 0.8                      # azar bajo abundancia: casi todo es bueno
    assert grid["abundante"]["-0.9"] <= 0.3                     # anti-calibrado: se va derecho a las raras malas
    # y el daño de la anti-calibración es MUCHO mayor bajo abundancia que bajo escasez
    sm = X.build_summary(grid)
    assert sm["downside_abund"] > sm["downside_scarce"] + 0.3, sm


def test_good_calibration_pays_only_scarce_upside():
    # el upside paga bajo escasez y satura bajo abundancia (consistente con 123)
    grid = X.run(n=60, m=5, n_seeds=120)
    sm = X.build_summary(grid)
    assert sm["upside_scarce"] > sm["upside_abund"] + 0.3, sm   # el upside vive bajo escasez


def _grid(sc, ab):
    rhos = ["-0.9", "-0.6", "-0.3", "0.0", "0.3", "0.6", "0.9"]
    return {"escaso": dict(zip(rhos, sc)), "abundante": dict(zip(rhos, ab))}


def test_verdict_refutada_if_no_abund_downside():
    # si la mal-calibración NO daña bajo abundancia, la tesis del doble-filo cae -> refutada
    sc = [0.00, 0.00, 0.05, 0.08, 0.50, 0.90, 1.00]            # escasez ok (upside grande, downside chico)
    ab = [0.85, 0.88, 0.90, 0.90, 0.95, 1.00, 1.00]            # abundancia SIN downside (anti ~ azar)
    sm = X.build_summary(_grid(sc, ab))
    assert not sm["abund_downside_real"]
    assert sm["status"] == "refutada", sm["verdict"]
