r"""
CYCLE 119 / H-V4-8y — regresión: el unlikelihood ACOTADO sobre negativos cura la calibración de la señal SIN colapsar la
capacidad (a diferencia del contrastivo naive de 118). El lazo usa torch (lento) -> se protege la LÓGICA del veredicto; el
run real se verifica al correr.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle119_bounded_unlikelihood.py -q
"""
from cognia_x.experiments.exp103_bounded_unlikelihood import run as X


def _seed(corr_pos, corr_unl, real_pos, real_unl):
    return {"hist": {"pos_only": {"corr": corr_pos, "real": [0.3] + real_pos},
                     "unlik": {"corr": corr_unl, "real": [0.3] + real_unl}},
            "base": {"real_acc": 0.3}}


def test_verdict_apoyada_cures_without_collapse():
    # unlik preserva la señal Y mantiene la capacidad (no colapsa) -> apoyada
    per = [_seed([0.42, 0.40, 0.41, 0.40], [0.42, 0.50, 0.60, 0.65], [0.15, 0.14, 0.15], [0.14, 0.13, 0.10]),
           _seed([0.41, 0.39, 0.40, 0.39], [0.41, 0.52, 0.62, 0.63], [0.16, 0.15, 0.16], [0.15, 0.14, 0.13])]
    sm = X.build_summary(per)
    assert sm["signal_better"] and sm["capacity_ok"] and not sm["destabilized"]
    assert sm["status"] == "apoyada"


def test_verdict_refutada_if_capacity_collapses():
    # unlik mejora la señal pero colapsa la capacidad (como el naive 118) -> refutada
    per = [_seed([0.42, 0.40, 0.41, 0.40], [0.42, 0.50, 0.60, 0.65], [0.20, 0.22, 0.24], [0.0, 0.0, 0.0]),
           _seed([0.41, 0.39, 0.40, 0.39], [0.41, 0.52, 0.62, 0.63], [0.20, 0.21, 0.23], [0.0, 0.0, 0.0])]
    sm = X.build_summary(per)
    assert sm["destabilized"]
    assert sm["status"] == "refutada"


def test_verdict_refutada_if_no_signal_gain():
    per = [_seed([0.42, 0.40, 0.41, 0.40], [0.42, 0.40, 0.41, 0.40], [0.15, 0.16, 0.17], [0.15, 0.16, 0.17]),
           _seed([0.41, 0.39, 0.40, 0.39], [0.41, 0.39, 0.40, 0.39], [0.16, 0.15, 0.16], [0.16, 0.15, 0.16])]
    sm = X.build_summary(per)
    assert not sm["signal_better"]
    assert sm["status"] == "refutada"
