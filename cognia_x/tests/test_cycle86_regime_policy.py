r"""
CYCLE 86 / H-V4-7d — regresión: el combinador aprendido domina; la detección de régimen es innecesaria (capstone gap #2).

Protege: (a) en la corrida real, always_learned domina al producto sobre una compuerta (>= en comp, > en subs) y ni el
oracle_selector ni el selector superan a always_learned por >0.02; (b) las 3 ramas del veredicto. Rápido (numpy).

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle86_regime_policy.py -q
"""
from cognia_x.experiments.exp070_regime_policy import run as X


def test_domination_detection_unnecessary_real_run():
    grid = X.run(n=50, k=10, sc=0.5, m=20, n_seeds=24)
    sm = X.build_summary(grid, 50, 10)
    assert sm["dominates"]
    assert sm["gate_quality"] in ("q0", "q1", "q2")
    # a q_ref: learned iguala en comp y vence en subs
    assert sm["dom_comp_qref"] >= -0.01
    assert sm["dom_subs_qref"] > 0.02
    # detección innecesaria: ni el detector perfecto ni el real superan a always_learned por >0.02
    assert sm["detection_unnecessary"]
    assert sm["oracle_selector_minus_always_learned"] <= 0.02
    assert sm["status"] == "apoyada"


def _cell(prod, learned, selector, oracle_sel):
    return {"oracle": 1.0, "always_product": prod, "always_learned": learned, "selector": selector,
            "oracle_selector": oracle_sel, "random": 0.2, "_frac_chose_learned": 0.5}


def _grid(comp, subs):
    # comp/subs: dict por nivel q -> (prod, learned, selector, oracle_sel). Construye las celdas que build_summary lee.
    g = {}
    for fam, spec in (("comp", comp), ("subs", subs)):
        for q in ("q0", "q1", "q2", "clean"):
            p, l, s, o = spec[q]
            g["{}_{}".format(fam, q)] = _cell(p, l, s, o)
    return g


_COMP_DOM = {"q0": (0.85, 0.85, 0.85, 0.86), "q1": (0.92, 0.92, 0.92, 0.93),
             "q2": (0.97, 0.975, 0.975, 0.976), "clean": (0.98, 0.99, 0.99, 0.99)}
_SUBS_DOM = {"q0": (0.89, 0.90, 0.89, 0.91), "q1": (0.91, 0.95, 0.95, 0.955),
             "q2": (0.94, 0.99, 0.99, 0.99), "clean": (0.93, 0.99, 0.99, 0.99)}


def test_verdict_apoyada():
    sm = X.build_summary(_grid(_COMP_DOM, _SUBS_DOM), 50, 10)
    assert sm["status"] == "apoyada"


def test_verdict_refutada_domination_fails():
    # en NINGÚN nivel no-clean el learned domina al producto en subs -> gate=None, dominación falla
    subs_nodom = {"q0": (0.89, 0.89, 0.89, 0.90), "q1": (0.91, 0.91, 0.91, 0.92),
                  "q2": (0.97, 0.97, 0.97, 0.975), "clean": (0.93, 0.99, 0.99, 0.99)}
    sm = X.build_summary(_grid(_COMP_DOM, subs_nodom), 50, 10)
    assert sm["gate_quality"] is None
    assert sm["status"] == "refutada"


def test_verdict_refutada_detection_helps():
    # el selector supera a always_learned por >0.02 a q2 -> detección SÍ aporta
    subs_sel = dict(_SUBS_DOM)
    subs_sel["q2"] = (0.94, 0.96, 0.99, 0.99)   # selector 0.99 >> learned 0.96
    comp_sel = dict(_COMP_DOM)
    comp_sel["q2"] = (0.97, 0.975, 0.99, 0.99)  # selector 0.99 > learned 0.975
    sm = X.build_summary(_grid(comp_sel, subs_sel), 50, 10)
    assert sm["status"] == "refutada"
