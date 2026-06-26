r"""
CYCLE 122 / H-V4-9b — regresión (REFUTADA-null): el payoff decisional de la señal calibrada no se aísla en el toy (la
submission satura por correctos abundantes). El lazo usa torch (lento) -> se protege la LÓGICA del veredicto; el run real
se verifica al correr.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle122_decisional_payoff.py -q
"""
from cognia_x.experiments.exp106_decisional_payoff import run as X


def _seed(payoff_n, payoff_d, corr_n, corr_d):
    return {"hist": {"naive": {"payoff": payoff_n, "corr": corr_n},
                     "durable": {"payoff": payoff_d, "corr": corr_d}}, "base": {"real_acc": 0.3}}


def test_verdict_refutada_saturated():
    # payoff satura (≈1.0 ambos) -> refutada-null
    per = [_seed([1.0, 1.0, 1.0], [0.95, 1.0, 0.94], [0.3, 0.26], [0.3, 0.38]),
           _seed([1.0, 1.0, 1.0], [1.0, 0.94, 1.0], [0.3, 0.27], [0.3, 0.39])]
    sm = X.build_summary(per)
    assert sm["no_pay"]
    assert sm["status"] == "refutada"


def test_submission_payoff_helper():
    import numpy as np
    conf = np.array([0.9, 0.8, 0.1, 0.2])
    strong = np.array([1.0, 1.0, 0.0, 0.0])   # las 2 de mayor conf son correctas
    # top-2 por conf = idx 0,1 -> ambas correctas; oracle = min(2, 2)=2 -> payoff 1.0
    assert abs(X._submission_payoff(conf, strong, 2) - 1.0) < 1e-9
    # selector invertido (conf negada) -> top-2 = idx 2,3 (incorrectas) -> payoff 0
    assert abs(X._submission_payoff(-conf, strong, 2) - 0.0) < 1e-9


def test_verdict_apoyada_if_separates():
    # caso hipotético: el payoff separa los brazos (escasez) -> apoyada
    per = [_seed([0.40, 0.45, 0.50], [0.60, 0.70, 0.80], [0.3, 0.15], [0.3, 0.50]),
           _seed([0.42, 0.44, 0.48], [0.62, 0.72, 0.78], [0.3, 0.16], [0.3, 0.49])]
    sm = X.build_summary(per)
    assert sm["pays"]
    assert sm["status"] == "apoyada"
