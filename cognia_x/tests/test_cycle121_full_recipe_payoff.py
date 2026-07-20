r"""
CYCLE 121 / H-V4-9a — regresión: la receta COMPLETA (ancla + unlikelihood) supera a ancla-sola (115) en el downstream
(el selector calibrado compone via yield). El lazo usa torch (lento) -> se protege la LÓGICA del veredicto; el run real se
verifica al correr.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle121_full_recipe_payoff.py -q
"""
from cognia_x.experiments.exp105_full_recipe_payoff import run as X


def _seed(real_a, real_f, yld_a, yld_f, corr_a, corr_f):
    return {"hist": {"anchor_only": {"real": [0.3] + real_a, "yield": yld_a, "corr": corr_a},
                     "full": {"real": [0.3] + real_f, "yield": yld_f, "corr": corr_f}},
            "base": {"real_acc": 0.3}}


def test_verdict_apoyada_full_adds_value():
    per = [_seed([0.06, 0.07], [0.12, 0.13], [8, 8], [11, 12], [0.3, 0.17], [0.3, 0.46]),
           _seed([0.07, 0.08], [0.13, 0.14], [7, 8], [11, 11], [0.3, 0.18], [0.3, 0.45])]
    sm = X.build_summary(per)
    assert sm["adds_value"]
    assert sm["yield_full"] > sm["yield_anchor"]
    assert sm["status"] == "apoyada"


def test_verdict_refutada_full_no_value():
    # full ≈ anchor en downstream -> refutada (con el ancla la calibración extra no compone)
    per = [_seed([0.10, 0.12], [0.10, 0.12], [8, 8], [11, 12], [0.3, 0.17], [0.3, 0.46]),
           _seed([0.11, 0.13], [0.11, 0.13], [7, 8], [11, 11], [0.3, 0.18], [0.3, 0.45])]
    sm = X.build_summary(per)
    assert sm["no_value"]
    assert sm["status"] == "refutada"
