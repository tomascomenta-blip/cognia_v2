r"""
CYCLE 105 / H-V4-8j — regresión: el costo-por-valor (CYCLE 101) transfiere al lazo cerrado real (asignar por
valor-positivo/costo rinde más correctos por presupuesto de costo). El lazo usa torch (lento) -> se protege la LÓGICA del
veredicto (build_summary) + el helper de costo; el run real se verifica al correr.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle105_real_cost_alloc.py -q
"""
from cognia_x.experiments.exp089_real_cost_alloc import run as X


def test_cost_increases_with_target():
    # costo de verificación ∝ target (targets grandes cuestan más)
    assert X._cost_of(b"2=") < X._cost_of(b"150=") < X._cost_of(b"300=")


def test_alloc_under_cost_respects_budget():
    import numpy as np
    costs = np.array([1.0, 2.0, 3.0, 1.0])
    picks = X._alloc_under_cost([2, 1, 0, 3], costs, 4.0)   # orden dado; presupuesto 4
    assert sum(costs[i] for i in picks) <= 4.0 + 1e-9


def _seed(yc, yr, nvc, nvr, rc, rr, csc=0.6, ccc=0.0):
    return {"hist": {"conf_alloc": {"yield": yc, "real": [0.4] + rc, "nverified": nvc},
                     "ratio_alloc": {"yield": yr, "real": [0.4] + rr, "nverified": nvr},
                     "verify_all": {"yield": [300, 300], "real": [0.4, 0.8, 0.8]},
                     "random_alloc": {"yield": [5, 5], "real": [0.4, 0.1, 0.1], "nverified": [80, 80]}},
            "base": {"real_acc": 0.4}, "conf_strong_corr": csc, "conf_cost_corr": ccc}


def test_verdict_apoyada():
    # ratio yield > conf, downstream no peor
    per = [_seed([100, 80], [137, 131], [120, 104], [147, 146], [0.456, 0.30], [0.707, 0.404]),
           _seed([79, 119], [124, 134], [117, 127], [153, 157], [0.356, 0.448], [0.459, 0.511])]
    sm = X.build_summary(per)
    assert sm["yield_better"] and sm["real_not_worse"]
    assert sm["status"] == "apoyada"


def test_verdict_refutada():
    # ratio yield NO supera a conf -> el costo no cambia la política (o artefacto)
    per = [_seed([100, 80], [90, 70], [120, 104], [101, 94], [0.40, 0.34], [0.37, 0.32]),
           _seed([79, 119], [74, 110], [117, 127], [91, 79], [0.36, 0.45], [0.44, 0.44])]
    sm = X.build_summary(per)
    assert not sm["yield_better"]
    assert sm["status"] == "refutada"
