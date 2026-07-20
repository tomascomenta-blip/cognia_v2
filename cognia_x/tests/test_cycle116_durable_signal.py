r"""
CYCLE 116 / H-V4-8u — regresión: la auto-consistencia (acuerdo entre K generaciones) es una señal de valor más durable que
la confianza single-shot. El lazo usa torch (lento) -> se protege la LÓGICA del veredicto + el cálculo de auto-consistencia;
el run real se verifica al correr.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle116_durable_signal.py -q
"""
import numpy as np

from cognia_x.experiments.exp100_durable_signal import run as X


def test_self_consistency_helper():
    # 3 gens del prompt A: 2 dan "x", 1 da "y"; 1 gen del prompt B
    prompts = [b"1=", b"1=", b"1=", b"2="]
    exprs = [b"x", b"x", b"y", b"z"]
    sc = X._self_consistency(prompts, exprs)
    assert abs(sc[0] - 2 / 3) < 1e-9 and abs(sc[1] - 2 / 3) < 1e-9   # "x" aparece 2/3
    assert abs(sc[2] - 1 / 3) < 1e-9                                  # "y" aparece 1/3
    assert abs(sc[3] - 1.0) < 1e-9                                    # "z" único en su prompt


def _seed(corr_conf, corr_sc, real):
    return {"hist": {"corr_conf": corr_conf, "corr_sc": corr_sc, "real": [0.3] + real}, "base": {"real_acc": 0.3}}


def test_verdict_apoyada_self_consist_durable():
    per = [_seed([0.41, 0.40, 0.33, 0.30], [0.41, 0.45, 0.48, 0.50], [0.2, 0.22, 0.24]),
           _seed([0.42, 0.38, 0.30, 0.28], [0.42, 0.46, 0.49, 0.51], [0.2, 0.22, 0.25])]
    sm = X.build_summary(per)
    assert sm["more_durable"]
    assert sm["status"] == "apoyada"


def test_verdict_refutada_not_durable():
    # self_consist cae igual o peor que conf -> refutada (verdad externa inevitable)
    per = [_seed([0.41, 0.40, 0.33, 0.42], [0.41, 0.35, 0.28, 0.30], [0.2, 0.22, 0.24]),
           _seed([0.42, 0.41, 0.40, 0.43], [0.42, 0.34, 0.30, 0.29], [0.2, 0.22, 0.25])]
    sm = X.build_summary(per)
    assert sm["not_durable"]
    assert sm["status"] == "refutada"
