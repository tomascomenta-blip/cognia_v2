r"""
CYCLE 85 / H-V4-7c — regresión: subir la calidad del feedback vuelve decisiva la recuperación del combinador aprendido.

Protege: (a) en la corrida real, la ventaja learned_poly2−producto bajo sustitutos crece con la calidad del feedback
(q3 > q0) y cruza el umbral decisivo (+0.03) sin feedback perfecto, sin sacrificar complementos; (b) las 3 ramas del
veredicto (apoyada moderado / mixta sólo-alto / refutada sólo-clean). Rápido (numpy).

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle85_feedback_quality.py -q
"""
from cognia_x.experiments.exp069_feedback_quality import run as X


def test_quality_lifts_recovery_real_run():
    grid = X.run(n=50, k=10, sc=0.5, m=20, n_seeds=24)
    sm = X.build_summary(grid, 50, 10)
    adv = sm["adv_subs"]
    # crece con la calidad del feedback
    assert adv["q3"] > adv["q0"]
    assert sm["improves_with_quality"]
    # cruza el umbral decisivo sin feedback perfecto
    assert sm["crossover_quality"] in ("q0", "q1", "q2", "q3")
    # no sacrifica complementos
    assert sm["comp_no_sacrifice"]
    assert sm["status"] in ("apoyada", "mixta")


def _cell(prod, poly2, emp=0.5, rel=0.5):
    return {"oracle": 1.0, "empowerment": emp, "relevance": rel, "rvalue_prod": prod,
            "learned_lin": poly2, "learned_poly2": poly2, "random": 0.2}


def _grid(subs_advs, comp_gap=0.0):
    # subs_advs: dict label -> adv (poly2-prod). prod fijo 0.92, poly2=0.92+adv. comp: poly2 = prod - comp_gap.
    g = {}
    for lab in ("q0", "q1", "q2", "q3", "clean"):
        g["subs_{}".format(lab)] = _cell(0.92, 0.92 + subs_advs[lab])
        g["comp_{}".format(lab)] = _cell(0.95, 0.95 - comp_gap, emp=0.5, rel=0.5)
    return g


def test_verdict_apoyada_moderate():
    # cruza +0.03 en feedback moderado (q1) y crece monótono
    sm = X.build_summary(_grid({"q0": 0.01, "q1": 0.04, "q2": 0.05, "q3": 0.06, "clean": 0.06}), 50, 10)
    assert sm["status"] == "apoyada"
    assert sm["crossover_quality"] == "q1"


def test_verdict_mixta_only_high():
    # sólo cruza +0.03 en q3 (feedback alto)
    sm = X.build_summary(_grid({"q0": 0.00, "q1": 0.01, "q2": 0.02, "q3": 0.04, "clean": 0.06}), 50, 10)
    assert sm["status"] == "mixta"
    assert sm["crossover_quality"] == "q3"


def test_verdict_refutada_only_clean():
    # sólo decisivo con feedback perfecto (o nunca en no-clean)
    sm = X.build_summary(_grid({"q0": 0.00, "q1": 0.01, "q2": 0.015, "q3": 0.02, "clean": 0.06}), 50, 10)
    assert sm["status"] == "refutada"
    assert sm["crossover_quality"] is None
