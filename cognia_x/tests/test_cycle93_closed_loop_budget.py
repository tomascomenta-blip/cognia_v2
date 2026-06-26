r"""
CYCLE 93 / H-V4-7i — regresión: en el lazo CERRADO real, asignar la verificación por CONFIANZA ENDÓGENA rinde más
correctas/verificación que al azar. El lazo usa el HybridLM (torch) y es lento -> aquí se protege la LÓGICA del veredicto
(build_summary) con per_seed sintéticos (rápido); el run real se verifica al correr el experimento/ciclo. Las features
del experimento (confianza, surface) se chequean por forma.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle93_closed_loop_budget.py -q
"""
import numpy as np

from cognia_x.experiments.exp077_closed_loop_budget import run as X


def _seed(yc, yn, yva, rc, rn, rva, corr, B=20, M=100):
    # yields y reals son listas por ronda; real incluye el base en [0]
    return {"hist": {"conf_alloc": {"yield": yc, "real": [0.5] + rc},
                     "random_alloc": {"yield": yn, "real": [0.5] + rn},
                     "verify_all": {"yield": yva, "real": [0.5] + rva}},
            "conf_strong_corr": corr, "B": B, "M": M, "base": {"real_acc": 0.5}}


def test_verdict_apoyada_conf_beats_random():
    per_seed = [_seed([50, 52], [12, 10], [90, 88], [0.40, 0.42], [0.30, 0.31], [0.55, 0.56], 0.42),
                _seed([48, 49], [11, 13], [85, 86], [0.38, 0.39], [0.29, 0.30], [0.52, 0.53], 0.37)]
    sm = X.build_summary(per_seed)
    assert sm["yield_all_pos"] and sm["yield_better"]
    assert sm["real_not_worse"]
    assert sm["status"] == "apoyada"


def test_verdict_refutada_conf_no_better():
    # conf yield ≈ random -> la confianza no discrimina
    per_seed = [_seed([12, 13], [12, 11], [90, 88], [0.30, 0.31], [0.30, 0.31], [0.55, 0.56], 0.02),
                _seed([11, 12], [12, 13], [85, 86], [0.29, 0.30], [0.30, 0.31], [0.52, 0.53], -0.01)]
    sm = X.build_summary(per_seed)
    assert not sm["yield_better"]
    assert sm["status"] == "refutada"


def test_verdict_mixta_yield_up_downstream_down():
    # conf gana yield pero el downstream regresiona (narrowing) -> mixta
    per_seed = [_seed([50, 52], [12, 10], [90, 88], [0.20, 0.18], [0.30, 0.31], [0.55, 0.56], 0.42),
                _seed([48, 49], [11, 13], [85, 86], [0.19, 0.20], [0.31, 0.30], [0.52, 0.53], 0.37)]
    sm = X.build_summary(per_seed)
    assert sm["yield_better"] and not sm["real_not_worse"]
    assert sm["status"] == "mixta"


def test_confidence_feature_shape():
    # _confidence devuelve un array vacío para entrada vacía (sin torch); _surf no aplica (confianza es la señal)
    assert X._confidence(None, [], "cpu").shape == (0,)
    # _corr maneja varianza cero
    assert X._corr([1, 1, 1], [0, 1, 0]) == 0.0
    assert abs(X._corr([1, 2, 3], [1, 2, 3]) - 1.0) < 1e-9
