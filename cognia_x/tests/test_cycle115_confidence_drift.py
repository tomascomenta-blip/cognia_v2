r"""
CYCLE 115 / H-V4-8t — regresión: la confianza (señal de valor) se erosiona al auto-entrenarse; la guardia (replay de
verdad canónica, 94) la sostiene. El lazo usa torch (lento) -> se protege la LÓGICA del veredicto (build_summary) + el
cálculo de tendencia; el run real se verifica al correr.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle115_confidence_drift.py -q
"""
from cognia_x.experiments.exp099_confidence_drift import run as X


def test_trend_helper():
    # tendencia = media(2da mitad) - media(1ra mitad)
    assert X._trend([0.4, 0.4, 0.2, 0.2]) == -0.2
    assert abs(X._trend([0.2, 0.2, 0.4, 0.4]) - 0.2) < 1e-9
    assert X._trend([0.3]) == 0.0


def _seed(corr_plain, corr_guard, real_plain, real_guard):
    return {"hist": {"conf_plain": {"corr": corr_plain, "real": [0.3] + real_plain},
                     "conf_guard": {"corr": corr_guard, "real": [0.3] + real_guard}},
            "base": {"real_acc": 0.3}}


def test_verdict_apoyada_plain_degrades_guard_helps():
    per = [_seed([0.42, 0.40, 0.25, 0.20], [0.42, 0.40, 0.34, 0.30], [0.2, 0.15, 0.12], [0.3, 0.28, 0.24]),
           _seed([0.41, 0.38, 0.22, 0.18], [0.41, 0.39, 0.33, 0.31], [0.2, 0.14, 0.11], [0.3, 0.27, 0.23])]
    sm = X.build_summary(per)
    assert sm["plain_degrades"] and sm["guard_helps"]
    assert sm["status"] == "apoyada"


def test_verdict_refutada_plain_stable():
    # la corr NO degrada sin guardia -> lazo auto-sostenido -> refutada
    per = [_seed([0.42, 0.41, 0.42, 0.41], [0.42, 0.41, 0.42, 0.41], [0.2, 0.25, 0.3], [0.2, 0.25, 0.3]),
           _seed([0.40, 0.41, 0.40, 0.41], [0.40, 0.41, 0.40, 0.41], [0.2, 0.25, 0.3], [0.2, 0.25, 0.3])]
    sm = X.build_summary(per)
    assert not sm["plain_degrades"]
    assert sm["status"] == "refutada"
