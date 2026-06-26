r"""
CYCLE 125 / H-V4-9e — regresión: asimetría del PRESUPUESTO en el doble filo de la calibración. El DOWNSIDE bajo abundancia
es BUDGET-FRÁGIL (decae apenas m supera el nº de opciones malas); el UPSIDE bajo escasez es BUDGET-ROBUSTO (persiste).
Presupuesto y calibración: sustitutos bajo abundancia (evitar minas), complementos bajo escasez (capturar gemas).

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle125_selective_budget.py -q
"""
from cognia_x.experiments.exp109_selective_budget import run as X


def test_budget_asymmetry_real_run():
    grid = X.run(n=60, n_seeds=120)
    sm = X.build_summary(grid, n=60)
    assert sm["status"] == "apoyada", sm["verdict"]
    assert sm["downside_was_big"], sm["down_abund_tight"]            # downside abundante grande a presupuesto ajustado
    assert sm["downside_budget_fragile"], sm                         # ...y decae a presupuesto moderado
    assert sm["upside_budget_robust"], sm["up_scarce_mod"]           # upside escaso persiste a ese mismo m


def test_abundance_downside_decays_past_n_bad():
    # la curva anti bajo abundancia se RECUPERA una vez que m supera el nº de malas (~6 de 60)
    grid = X.run(n=60, n_seeds=120)
    anti = grid["abundante"]["anti"]
    assert anti["3"] <= 0.2          # m<=#malas: el anti-calibrado se va a las malas (payoff ~0)
    assert anti["40"] >= 0.6         # m>>#malas: forzado a incluir buenas -> el daño se desvanece
    assert anti["40"] > anti["6"] + 0.4


def test_scarcity_upside_robust_to_budget():
    # bajo escasez la buena calibración sigue dominando al azar incluso a presupuesto moderado
    grid = X.run(n=60, n_seeds=120)
    sm = X.build_summary(grid, n=60)
    # el downside abundante decae MUCHO más con el presupuesto que el upside escaso
    down_decay = sm["down_abund_tight"] - sm["down_abund_mod"]
    up_decay = sm["up_scarce_tight"] - sm["up_scarce_mod"]
    assert down_decay > up_decay + 0.2, (down_decay, up_decay)


def _grid(esc_anti, esc_azar, esc_bien, ab_anti, ab_azar, ab_bien):
    ms = ["1", "3", "6", "10", "20", "40"]
    return {"escaso": {"anti": dict(zip(ms, esc_anti)), "azar": dict(zip(ms, esc_azar)), "bien": dict(zip(ms, esc_bien))},
            "abundante": {"anti": dict(zip(ms, ab_anti)), "azar": dict(zip(ms, ab_azar)), "bien": dict(zip(ms, ab_bien))}}


def test_verdict_refutada_if_downside_not_fragile():
    # si el downside abundante NO decae con m (no budget-frágil) -> refutada
    g = _grid(
        esc_anti=[0, 0, 0, 0, 0, 0], esc_azar=[0.06, 0.1, 0.11, 0.14, 0.33, 0.64], esc_bien=[1, 1, 1, 1, 1, 1],
        ab_anti=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0],     # downside abundante GRANDE a todo m (no decae)
        ab_azar=[0.9, 0.9, 0.9, 0.9, 0.9, 0.9], ab_bien=[1, 1, 1, 1, 1, 1])
    sm = X.build_summary(g, n=60)
    assert not sm["downside_budget_fragile"]
    assert sm["status"] == "refutada", sm["verdict"]
