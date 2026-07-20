r"""
CYCLE 132 / H-V4-10f — regresión (versión HONESTA tras verificación adversarial): el keystone (valor=ctrl×rel) sobrevive a
control NO-LINEAL saturante PERO sólo con controlabilidad de ALCANCE/ESFUERZO (valor_eff robusto en todo ancho de probe); la
PENDIENTE LOCAL (valor_lin, la del keystone 129) es CIEGA a la saturación -- a probe local colapsa a relevancia (sat) o por
debajo (break). Generaliza la controlabilidad-descontada-por-costo de 130.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle132_nonlinear_keystone.py -q
"""
from cognia_x.experiments.exp116_nonlinear_keystone import run as X


def test_mixta_reach_aware_real_run():
    grid = X.run(n_seeds=60)
    sm = X.build_summary(grid)
    assert sm["status"] == "mixta", sm["verdict"]
    assert sm["eff_robust"], sm["eff_min"]                  # controlabilidad de ALCANCE robusta en todo σ_p/régimen
    assert sm["lin_blind_local"], (sm["lin_loc_sat"], sm["rel_sat"])   # pendiente local ciega a probe local
    assert sm["lin_probe_contingent"], sm["probe_contingent"]          # su robustez depende del ancho del probe


def test_reach_aware_robust_local_slope_blind():
    grid = X.run(n_seeds=60)
    sm = X.build_summary(grid)
    assert sm["eff_min"] > 0.85, sm["eff_min"]                         # valor_eff óptimo en todo σ_p
    # a probe genuinamente local en saturación, valor_lin colapsa a nivel relevancia
    assert sm["lin_loc_sat"] < sm["rel_sat"] + 0.08, (sm["lin_loc_sat"], sm["rel_sat"])
    # y se recupera sólo al ensanchar el probe (reach-awareness encubierta)
    assert sm["lin_wide_sat"] - sm["lin_loc_sat"] > 0.12, sm["probe_contingent"]


def test_local_slope_harmful_under_anticorrelated_gain_reach():
    # régimen break: ganancia alta + alcance bajo -> la pendiente local PREFIERE los modos inalcanzables (peor que relevancia)
    grid = X.run(n_seeds=60)
    sm = X.build_summary(grid)
    assert sm["lin_loc_break"] < sm["rel_break"] - 0.04, (sm["lin_loc_break"], sm["rel_break"])


def test_nosat_all_criteria_agree():
    # sin saturación, la pendiente local y el alcance coinciden (el keystone lineal vale cuando no hay no-linealidad)
    grid = X.run(n_seeds=60)
    for sg in X.SIGMAS:
        row = grid["nosat"][str(sg)]
        assert row["valor_lin"] > 0.85 and row["valor_eff"] > 0.85, (sg, row)
