r"""
CYCLE 126 / H-V4-9f — regresión: ρ EARNED (probe ajustado) ancla las apuestas decisionales 123-125. (A) el ρ earned crece
con la calidad del feature y el payoff bajo escasez lo trackea (ρ no es un knob); (B) un probe que aprendió un feature
ESPURIO que se invierte en deployment gana ρ<0 y es catastrófico-pero-budget-frágil bajo abundancia.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle126_earned_calibration.py -q
"""
from cognia_x.experiments.exp110_earned_calibration import run as X


def test_earned_grounding_real_run():
    grid = X.run(n_seeds=120)
    sm = X.build_summary(grid)
    assert sm["status"] == "apoyada", sm["verdict"]
    assert sm["groundingA"], sm        # ρ ganado ancla 123
    assert sm["groundingB"], sm        # espurio->anti ancla 124-125


def test_rho_is_earned_monotone_in_feature_quality():
    # ρ earned crece al MEJORAR el feature (bajar σ); el payoff bajo escasez lo trackea
    grid = X.run(n_seeds=120)
    rho = [grid["robusto"][str(s)]["escaso"]["3"]["rho"] for s in X.SIG_SWEEP]      # σ creciente
    pay = [grid["robusto"][str(s)]["escaso"]["3"]["payoff"] for s in X.SIG_SWEEP]
    assert rho[0] > rho[-1] + 0.1, rho          # mejor feature (σ menor, índice 0) -> más ρ
    assert pay[0] > pay[-1] + 0.2, pay          # ...y más payoff bajo escasez
    assert rho[0] > 0.4 and pay[0] > 0.5        # el buen estimador SÍ paga bajo escasez (123 con ρ ganado)


def test_spurious_probe_earns_anticalibration_via_shift():
    # el probe que aprende el atajo espurio gana ρ<0 y es catastrófico bajo abundancia, pero budget-frágil
    grid = X.run(n_seeds=120)
    esp_ab = grid["espurio"]["abundante"]
    assert esp_ab["3"]["rho"] < -0.1            # anti-calibrado (ganado, no impuesto)
    assert esp_ab["3"]["payoff"] < 0.5          # catastrófico a presupuesto ajustado bajo abundancia
    assert esp_ab["20"]["payoff"] - esp_ab["3"]["payoff"] > 0.3   # budget-frágil (recupera al ensanchar m)


def test_robust_probe_stays_calibrated_no_shift_collapse():
    # el probe robusto (sin atajo espurio) NO se vuelve anti-calibrado: ρ>0 en ambos regímenes con el buen feature
    grid = X.run(n_seeds=120)
    best = str(X.SIG_SWEEP[0])
    assert grid["robusto"][best]["escaso"]["3"]["rho"] > 0.0
    assert grid["robusto"][best]["abundante"]["3"]["rho"] > 0.0
