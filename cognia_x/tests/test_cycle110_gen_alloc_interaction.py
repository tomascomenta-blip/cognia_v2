r"""
CYCLE 110 / H-V4-8o — regresión: diversidad del generador y calidad de asignación COMPLEMENTARIAS (interacción temp×alloc
positiva). El lazo usa torch (lento) -> se protege la LÓGICA del veredicto (build_summary); el run real se verifica al
correr.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle110_gen_alloc_interaction.py -q
"""
from cognia_x.experiments.exp094_gen_alloc_interaction import run as X


def _seed(cl, ch, rl, rh, csc=0.45):
    return {"hist": {"conf_low": {"real": [0.2] + cl, "yield": [10, 10]},
                     "conf_high": {"real": [0.2] + ch, "yield": [5, 5]},
                     "random_low": {"real": [0.2] + rl, "yield": [8, 8]},
                     "random_high": {"real": [0.2] + rh, "yield": [3, 3]}},
            "base": {"real_acc": 0.2}, "conf_strong_corr": csc}


def test_verdict_apoyada_positive_interaction():
    # subir temp ayuda (o daña menos) bajo conf, daña bajo random -> interacción positiva
    per = [_seed([0.30, 0.30], [0.34, 0.36], [0.40, 0.30], [0.20, 0.10]),
           _seed([0.36, 0.45], [0.40, 0.46], [0.45, 0.40], [0.25, 0.18])]
    sm = X.build_summary(per)
    assert sm["interaction"] > 0.02
    assert sm["status"] == "apoyada"


def test_verdict_refutada_no_interaction():
    # subir temp tiene el mismo efecto (+0.04) bajo ambas -> interacción ≈ 0
    per = [_seed([0.30, 0.34], [0.34, 0.38], [0.40, 0.44], [0.44, 0.48]),
           _seed([0.36, 0.40], [0.40, 0.44], [0.45, 0.49], [0.49, 0.53])]
    sm = X.build_summary(per)
    assert abs(sm["interaction"]) <= 0.02
    assert sm["status"] == "refutada"


def test_interaction_formula():
    # interacción = (conf_high - conf_low) - (random_high - random_low)
    per = [_seed([0.30, 0.30], [0.40, 0.40], [0.40, 0.40], [0.20, 0.20])]
    sm = X.build_summary(per)
    # conf_effect = 0.10, random_effect = -0.20 -> interacción = 0.30
    assert abs(sm["conf_temp_effect"] - 0.10) < 1e-6
    assert abs(sm["rand_temp_effect"] + 0.20) < 1e-6
    assert abs(sm["interaction"] - 0.30) < 1e-6
