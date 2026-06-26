r"""
CYCLE 117 / H-V4-8w — regresión (REFUTADA): dirigir el replay canónico a los fallos NO restaura la señal mejor que el
replay aleatorio. El lazo usa torch (lento) -> se protege la LÓGICA del veredicto; el run real se verifica al correr.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle117_targeted_grounding.py -q
"""
from cognia_x.experiments.exp101_targeted_grounding import run as X


def _seed(corr_rand, corr_targ, real_rand, real_targ):
    return {"hist": {"guard_random": {"corr": corr_rand, "real": [0.3] + real_rand},
                     "guard_targeted": {"corr": corr_targ, "real": [0.3] + real_targ}},
            "base": {"real_acc": 0.3}}


def test_verdict_refutada_targeting_no_help():
    # targeted ≈ o peor que random en la señal -> refutada
    per = [_seed([0.42, 0.40, 0.34, 0.32], [0.42, 0.38, 0.28, 0.23], [0.25, 0.28, 0.29], [0.24, 0.26, 0.19]),
           _seed([0.41, 0.39, 0.33, 0.31], [0.41, 0.37, 0.27, 0.24], [0.25, 0.27, 0.30], [0.24, 0.25, 0.20])]
    sm = X.build_summary(per)
    assert not sm["signal_better"]
    assert sm["status"] == "refutada"


def test_verdict_apoyada_if_targeting_helped():
    # caso hipotético: targeted preserva mejor la señal -> apoyada
    per = [_seed([0.42, 0.35, 0.25, 0.20], [0.42, 0.41, 0.40, 0.39], [0.25, 0.26, 0.27], [0.25, 0.27, 0.29]),
           _seed([0.41, 0.34, 0.24, 0.19], [0.41, 0.40, 0.39, 0.38], [0.25, 0.26, 0.28], [0.25, 0.27, 0.30])]
    sm = X.build_summary(per)
    assert sm["signal_better"] and sm["real_not_worse"]
    assert sm["status"] == "apoyada"


def test_verdict_mixta_signal_better_downstream_worse():
    per = [_seed([0.42, 0.35, 0.25, 0.20], [0.42, 0.41, 0.40, 0.39], [0.40, 0.42, 0.45], [0.25, 0.22, 0.20]),
           _seed([0.41, 0.34, 0.24, 0.19], [0.41, 0.40, 0.39, 0.38], [0.40, 0.43, 0.46], [0.25, 0.23, 0.21])]
    sm = X.build_summary(per)
    assert sm["signal_better"] and not sm["real_not_worse"]
    assert sm["status"] == "mixta"
