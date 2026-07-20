r"""
CYCLE 60 / H-V4-2i — regresión: auto-consistencia como verificador parcial gateado por calibración.

Protege: (a) filter_self_consistency se queda con el valor mayoritario y mide calibración (valor==target);
(b) las 3 ramas del veredicto (APOYADA gating limpio / REFUTADA sin gating / MIXTA borderline). Sin modelo -> rápido.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle60_self_consistency_verifier.py -q
"""
from cognia_x.experiments.exp046_self_consistency_verifier import run as X


def test_filter_self_consistency_majority_and_calibration():
    # prompt "12=": 3 de 4 muestras computan 12 (target) -> consistente y CORRECTO
    # prompt "6=": 3 de 4 computan 5 (target-1) -> consistente pero INCORRECTO (calibración baja)
    pool = [(b"12=", b"3*4", True, True), (b"12=", b"6*2", True, True), (b"12=", b"2*6", True, True), (b"12=", b"1+8", False, False),
            (b"6=", b"1+4", True, False), (b"6=", b"2+3", True, False), (b"6=", b"4+1", True, False), (b"6=", b"2*3", True, True)]
    kept, info = X.filter_self_consistency(pool, tau=0.5)
    prompts = {bytes(p) for p, e in kept}
    assert b"12=" in prompts and b"6=" in prompts        # ambos consistentes (3/4 >= 0.5)
    assert info["n_consistent"] == 2
    assert abs(info["calibration"] - 0.5) < 1e-6         # 1 de 2 consistentes es correcto (el 12, no el 6)


def _regime(base, vf, scf, nf, calib, n=3):
    return [{"seed": i, "base": base, "sc_calib": calib,
             "hist": {"verified": [base, vf], "self_consistency": [base, scf], "naive": [base, nf]}}
            for i in range(n)]


def test_verdict_apoyada_clean_gating():
    strong = _regime(0.63, 0.80, 0.70, 0.62, 0.88)
    weak = _regime(0.18, 0.45, 0.06, 0.19, 0.26)
    sm = X.build_summary(strong, weak, None, m=90)
    assert sm["status"] == "apoyada"
    assert sm["gating"] and sm["strong_usable"] and sm["weak_collapses"]


def test_verdict_refutada_no_gating():
    strong = _regime(0.63, 0.80, 0.60, 0.62, 0.50)   # sc<=naive y calib ~ weak
    weak = _regime(0.18, 0.45, 0.20, 0.19, 0.40)
    sm = X.build_summary(strong, weak, None, m=90)
    assert sm["status"] == "refutada"


def test_verdict_mixta_borderline():
    strong = _regime(0.63, 0.80, 0.70, 0.62, 0.88)
    weak = _regime(0.18, 0.45, 0.15, 0.19, 0.26)      # no colapsa limpio (0.15 ~ naive 0.19)
    sm = X.build_summary(strong, weak, None, m=90)
    assert sm["status"] == "mixta"
    assert sm["gating"] and not sm["weak_collapses"]
