r"""
CYCLE 92 / H-V4-3b — regresión: el META-PRIOR (selección de base por CV held-out) es NO-REGRET pero INNECESARIO dado un
prior flexible que nesta los regímenes (MIXTA; espeja CYCLE 86). Protege: (a) en la corrida real, el selector logra
no-regret (≈ mejor base por régimen y oracle_selector) pero no supera a always-rbf -> mixta; (b) el selector elige poly2
en smooth y rbf en band; (c) las ramas del veredicto.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle92_prior_selector.py -q
"""
from cognia_x.experiments.exp076_prior_selector import run as X


def test_selector_no_regret_but_unnecessary_real_run():
    grid = X.run(n=50, k_budget=10, k_eval=10, E_rounds=12, sc=0.2, n_seeds=12)
    sm = X.build_summary(grid)
    # no-regret: el selector iguala a la mejor base por régimen y a oracle_selector
    assert sm["no_regret"], (sm["regret_smooth"], sm["regret_band"])
    # elige bien por régimen
    assert sm["best_fixed_smooth"] == "always_poly2"
    assert sm["best_fixed_band"] == "always_rbf"
    # pero NO supera a una base fija flexible (rbf) -> selección innecesaria -> mixta
    assert not sm["beats_any_fixed"], sm["selector_beats_best_fixed"]
    assert sm["status"] == "mixta"


def _cell(p2, rbf, bn, sel, osel, bayes, prod, chance):
    return {"always_poly2": p2, "always_rbf": rbf, "always_bin": bn, "selector": sel,
            "oracle_selector": osel, "bayes": bayes, "product": prod, "chance": chance}


def _grid(smooth, band):
    return {"smooth": _cell(*smooth), "band": _cell(*band)}


def test_verdict_mixta_flexible_default_dominates():
    # no-regret pero rbf casi domina -> selector ≈ rbf -> mixta
    sm = X.build_summary(_grid(smooth=(0.612, 0.600, 0.539, 0.605, 0.616, 0.621, 0.615, 0.23),
                               band=(0.490, 0.711, 0.586, 0.711, 0.711, 0.828, 0.327, 0.23)))
    assert sm["status"] == "mixta"
    assert sm["no_regret"] and not sm["beats_any_fixed"]


def test_verdict_apoyada_no_single_base_dominates():
    # cada base gana en su régimen y NINGUNA gana en ambos -> selector las supera en promedio -> apoyada
    sm = X.build_summary(_grid(smooth=(0.70, 0.40, 0.45, 0.69, 0.70, 0.80, 0.70, 0.23),
                               band=(0.40, 0.70, 0.45, 0.69, 0.70, 0.80, 0.30, 0.23)))
    assert sm["no_regret"] and sm["beats_any_fixed"]
    assert sm["status"] == "apoyada"


def test_verdict_refutada_selector_loses():
    # el selector pierde vs una base fija (mal selecciona) -> refutada
    sm = X.build_summary(_grid(smooth=(0.70, 0.68, 0.45, 0.50, 0.70, 0.80, 0.70, 0.23),
                               band=(0.40, 0.70, 0.45, 0.50, 0.70, 0.80, 0.30, 0.23)))
    assert not sm["beats_any_fixed"]
    assert sm["status"] == "refutada"
