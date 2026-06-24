r"""
CYCLE 36 / H-V4-1b — regresión del aislamiento del valor (exp023).

Falla SIN la implementación correcta y pasa CON ella. El hallazgo HONESTO que protege:
- el VALOR info-gain NO está robustamente aislado del azar-activo (margen medio ~0),
- pero ACTUAR (cualquier política activa) >> observar (pasivo plano) sí es robusto.
Si alguien "arreglara" el experimento para inflar el margen del valor, este test lo atrapa.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle36_value_isolation.py -q
"""
from cognia_x.experiments.exp023_value_isolation import run as E


def _fast():
    return E.run(budgets=[8, 32, 128], n_seeds=10, D=24, cluster=6, p_obs=0.25, n_test=800, cand_pool=96)


def test_active_beats_passive_robust():
    _, s = _fast()
    bb = s["by_budget"]
    A128 = bb["128"]["A_pasivo"]["interv_mean"]
    B128 = bb["128"]["B_infogain"]["interv_mean"]
    C128 = bb["128"]["C_aleatorio"]["interv_mean"]
    A8 = bb["8"]["A_pasivo"]["interv_mean"]
    # actuar (info-gain Y azar) >> observar
    assert (B128 - A128) > 0.20
    assert (C128 - A128) > 0.20
    # pasivo plano en presupuesto (muro informacional)
    assert abs(A128 - A8) < 0.12


def test_value_not_robustly_isolated():
    _, s = _fast()
    bb = s["by_budget"]
    value_margin = abs(s["value_isolation"]["mean_margin"])          # efecto del VALOR (info-gain vs azar)
    active_margin = bb["128"]["C_aleatorio"]["interv_mean"] - bb["128"]["A_pasivo"]["interv_mean"]  # efecto de ACTUAR
    # el hallazgo robusto: el VALOR es un efecto MENOR frente a la ACCIÓN (no el lever dominante)
    assert value_margin < 0.10                       # margen del valor chico en términos absolutos
    assert value_margin < 0.5 * active_margin        # y chico RELATIVO a la acción (lo que de verdad importa)
    assert s["verdict"] in ("mixta", "refutada")


def test_cheap_on_cpu():
    _, s = _fast()
    # baratísimo: aprender un modelo causal completo cuesta milisegundos en CPU
    assert s["cost"]["mean_secs_per_agent_run"] < 0.5


def test_reproducible():
    a = E.run(budgets=[8, 32], n_seeds=4, D=24, cluster=6, p_obs=0.25, n_test=500, cand_pool=64)[1]
    b = E.run(budgets=[8, 32], n_seeds=4, D=24, cluster=6, p_obs=0.25, n_test=500, cand_pool=64)[1]
    assert a["verdict"] == b["verdict"]
    assert a["by_budget"]["32"]["B_infogain"]["interv_mean"] == b["by_budget"]["32"]["B_infogain"]["interv_mean"]
