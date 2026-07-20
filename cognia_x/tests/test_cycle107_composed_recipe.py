r"""
CYCLE 107 / H-V4-8l — regresión: la receta compuesta de asignación (confianza+costo+cobertura) compone en el lazo cerrado
real (cobertura domina el downstream). El lazo usa torch (lento) -> se protege la LÓGICA del veredicto (build_summary); el
run real se verifica al correr.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle107_composed_recipe.py -q
"""
from cognia_x.experiments.exp091_composed_recipe import run as X


def _seed(rc, rr, rrc, rva, csc=0.45):
    return {"hist": {"conf": {"yield": [40, 40], "real": [0.4] + rc},
                     "ratio": {"yield": [45, 45], "real": [0.4] + rr},
                     "ratio_coverage": {"yield": [40, 40], "real": [0.4] + rrc},
                     "verify_all": {"yield": [300, 300], "real": [0.4] + rva}},
            "base": {"real_acc": 0.4}, "conf_strong_corr": csc}


def test_verdict_apoyada_composes():
    # compuesto > conf; costo dentro de tolerancia; cobertura aporta -> apoyada
    per = [_seed([0.33, 0.34], [0.31, 0.30], [0.57, 0.41], [0.59, 0.37]),
           _seed([0.36, 0.45], [0.34, 0.43], [0.50, 0.55], [0.67, 0.81])]
    sm = X.build_summary(per)
    assert sm["composes"]
    assert sm["status"] == "apoyada"


def test_verdict_refutada_no_gain():
    # compuesto NO supera a confianza -> refutada
    per = [_seed([0.40, 0.41], [0.39, 0.40], [0.41, 0.42], [0.59, 0.60]),
           _seed([0.36, 0.45], [0.35, 0.44], [0.37, 0.46], [0.67, 0.70])]
    sm = X.build_summary(per)
    assert sm["composed_vs_conf"] <= 0.03
    assert sm["status"] == "refutada"


def test_verdict_mixta_cost_regresses():
    # compuesto > conf PERO el paso costo regresiona claramente (< -0.03) -> composición parcial -> mixta
    per = [_seed([0.40, 0.41], [0.30, 0.31], [0.55, 0.56], [0.70, 0.71]),
           _seed([0.42, 0.43], [0.31, 0.32], [0.54, 0.55], [0.70, 0.72])]
    sm = X.build_summary(per)
    assert sm["composed_vs_conf"] > 0.03 and sm["cost_step"] < -0.03
    assert sm["status"] == "mixta"
