r"""
CYCLE 84 / H-V4-7b — regresión: un combinador APRENDIDO recupera parcial/noise-gated bajo sustitutos.

Protege: (a) en la corrida real, learned_poly2 es el mejor brazo no-oráculo bajo sustitutos (vence a producto y
marginal) y recupera PLENO con estimadores clean, sin sacrificar complementos; (b) las 4 ramas del veredicto
(apoyada/mixta-parcial/mixta-sacrifica/refutada). Rápido (numpy).

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle84_learned_combiner.py -q
"""
from cognia_x.experiments.exp068_learned_combiner import run as X


def test_partial_recovery_real_run():
    grid = X.run(n=50, k=10, S=8, sc=0.5, sr=0.1, n_seeds=24)
    sm = X.build_summary(grid, 50, 10)
    # learned_poly2 es el mejor brazo no-oráculo bajo sustitutos (vence a producto y a la marginal)
    assert sm["partial_recover"]
    assert sm["subs_learned_poly2"] > sm["subs_prod"]
    assert sm["subs_learned_poly2"] >= sm["subs_best_marginal"]
    # recupera PLENO con estimadores limpios (aísla: es la forma aprendida, no el ruido)
    assert sm["clean_recover"]
    # no sacrifica complementos
    assert sm["no_sacrifice_comp"]
    assert sm["status"] in ("apoyada", "mixta")


def test_budget_helps():
    # más presupuesto de observaciones -> learned_poly2 no peor (convergencia con m)
    grid = X.run(n=50, k=10, S=8, sc=0.5, sr=0.1, n_seeds=24)
    sm = X.build_summary(grid, 50, 10)
    curve = sm["budget_curve_subs_l1"]
    assert curve["20"] >= curve["5"]


def _cell(prod, emp, rel, lin, poly2):
    return {"oracle": 1.0, "empowerment": emp, "relevance": rel, "rvalue_prod": prod,
            "learned_lin": lin, "learned_poly2": poly2, "random": 0.2}


def _grid(subs_noisy, subs_clean, comp_noisy):
    # subs_*/comp_*: dict con prod, bm (best marginal), poly2. Construye sólo las celdas que build_summary lee (m=20).
    g = {}
    for fam in ("comp", "subs"):
        for lam in (0.5, 1.0):
            for m in (5, 10, 20, 40):
                for noise in ("noisy", "clean"):
                    g["{}_l{}_m{}_{}".format(fam, lam, m, noise)] = _cell(0.9, 0.5, 0.5, 0.9, 0.9)
    sn, sc, cn = subs_noisy, subs_clean, comp_noisy
    g["subs_l1.0_m20_noisy"] = _cell(sn["prod"], sn["bm"], 0.0, sn["prod"], sn["poly2"])
    g["subs_l1.0_m20_clean"] = _cell(sc["prod"], 0.5, 0.0, sc["prod"], sc["poly2"])
    g["comp_l1.0_m20_noisy"] = _cell(cn["prod"], 0.5, 0.5, cn["prod"], cn["poly2"])
    return g


def test_verdict_apoyada():
    sm = X.build_summary(_grid(
        subs_noisy={"prod": 0.90, "bm": 0.92, "poly2": 0.96},   # +0.06 decisivo, >= marginal
        subs_clean={"prod": 0.93, "poly2": 0.99},
        comp_noisy={"prod": 0.92, "poly2": 0.93}), 50, 10)
    assert sm["status"] == "apoyada"


def test_verdict_mixta_partial():
    sm = X.build_summary(_grid(
        subs_noisy={"prod": 0.926, "bm": 0.939, "poly2": 0.953},  # +0.027 no decisivo, pero mejor no-oráculo
        subs_clean={"prod": 0.93, "poly2": 0.99},
        comp_noisy={"prod": 0.927, "poly2": 0.933}), 50, 10)
    assert sm["status"] == "mixta"
    assert sm["partial_recover"] and not sm["decisive_recover"]


def test_verdict_mixta_sacrifices_comp():
    sm = X.build_summary(_grid(
        subs_noisy={"prod": 0.90, "bm": 0.92, "poly2": 0.96},   # decisivo bajo sustitutos
        subs_clean={"prod": 0.93, "poly2": 0.99},
        comp_noisy={"prod": 0.95, "poly2": 0.85}), 50, 10)   # pero sacrifica complementos (gap 0.10>0.05)
    assert sm["status"] == "mixta"


def test_verdict_refutada():
    sm = X.build_summary(_grid(
        subs_noisy={"prod": 0.94, "bm": 0.95, "poly2": 0.93},   # poly2 NO supera ni a producto ni a marginal
        subs_clean={"prod": 0.93, "poly2": 0.94},
        comp_noisy={"prod": 0.92, "poly2": 0.93}), 50, 10)
    assert sm["status"] == "refutada"
