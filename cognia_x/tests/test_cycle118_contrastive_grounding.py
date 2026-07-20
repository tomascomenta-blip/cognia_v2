r"""
CYCLE 118 / H-V4-8x — regresión (REFUTADA-inestable): el contrastivo naive (ascenso de CE sobre negativos) desestabiliza el
modelo (real_acc->0); la dirección negativa es correcta, la implementación no. El lazo usa torch (lento) -> se protege la
LÓGICA del veredicto; el run real se verifica al correr.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle118_contrastive_grounding.py -q
"""
from cognia_x.experiments.exp102_contrastive_grounding import run as X


def _seed(corr_pos, corr_con, real_pos, real_con):
    return {"hist": {"pos_only": {"corr": corr_pos, "real": [0.3] + real_pos},
                     "contrastive": {"corr": corr_con, "real": [0.3] + real_con}},
            "base": {"real_acc": 0.3}}


def test_verdict_refutada_destabilized():
    # contrastive desestabiliza: real_acc->0 (Δ << -0.10) -> refutada-inestable
    per = [_seed([0.42, 0.40, 0.34, 0.33], [0.42, 0.41, 0.40, 0.39], [0.20, 0.22, 0.19], [0.0, 0.0, 0.0]),
           _seed([0.41, 0.39, 0.33, 0.32], [0.41, 0.40, 0.39, 0.38], [0.20, 0.21, 0.18], [0.0, 0.0, 0.0])]
    sm = X.build_summary(per)
    assert sm["destabilized"]
    assert sm["status"] == "refutada"


def test_verdict_apoyada_if_stable_and_better():
    # caso hipotético: contrastive preserva la señal SIN desestabilizar -> apoyada
    per = [_seed([0.42, 0.35, 0.25, 0.20], [0.42, 0.41, 0.40, 0.39], [0.20, 0.22, 0.24], [0.20, 0.23, 0.25]),
           _seed([0.41, 0.34, 0.24, 0.19], [0.41, 0.40, 0.39, 0.38], [0.20, 0.22, 0.25], [0.20, 0.24, 0.26])]
    sm = X.build_summary(per)
    assert not sm["destabilized"] and sm["signal_better"] and sm["real_ok"]
    assert sm["status"] == "apoyada"


def test_verdict_refutada_no_signal_gain():
    # estable pero no mejora la señal -> refutada
    per = [_seed([0.42, 0.40, 0.34, 0.33], [0.42, 0.40, 0.34, 0.33], [0.20, 0.22, 0.24], [0.20, 0.22, 0.24]),
           _seed([0.41, 0.39, 0.33, 0.32], [0.41, 0.39, 0.33, 0.32], [0.20, 0.21, 0.23], [0.20, 0.21, 0.23])]
    sm = X.build_summary(per)
    assert not sm["signal_better"] and not sm["destabilized"]
    assert sm["status"] == "refutada"
