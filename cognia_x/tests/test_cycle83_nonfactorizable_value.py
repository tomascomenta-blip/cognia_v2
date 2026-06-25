r"""
CYCLE 83 / H-V4-7a — regresión: la reconstrucción-PRODUCTO de R-VALOR es un prior de complementariedad.

Protege: (a) en la corrida real, el producto vence a cada marginal en TODO λ bajo complementos (crossover=None) y se
rompe bajo sustitutos puros (crossover finito, breaks_extreme); (b) las filas 'clean' (estimadores perfectos)
reproducen la asimetría -> es la factorización, no el ruido; (c) las 4 ramas del veredicto. Rápido (numpy).

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle83_nonfactorizable_value.py -q
"""
from cognia_x.experiments.exp067_nonfactorizable_value import run as X


def test_asymmetry_real_run():
    grid = X.run(n=50, k=10, S=8, sc=0.5, sr=0.1, n_seeds=16)
    sm = X.build_summary(grid, 50, 10)
    # complementos: producto robusto en TODO λ (nunca cruza)
    assert sm["comp_robust_all"]
    assert sm["crossover_comp"] is None
    # sustitutos: se rompe en el extremo (crossover finito <= 1.0)
    assert sm["subs_breaks_extreme"]
    assert sm["crossover_subs"] is not None and sm["crossover_subs"] <= 1.0
    assert sm["status"] == "apoyada"


def test_clean_rows_isolate_factorization():
    grid = X.run(n=50, k=10, S=8, sc=0.5, sr=0.1, n_seeds=16)
    # bajo sustitutos puros con estimadores PERFECTOS, una marginal alcanza/supera al producto (no es el ruido)
    c = grid["subs_l1.0_clean"]
    assert max(c["empowerment"], c["relevance"]) >= c["rvalue_prod"] - 1e-6
    # bajo complementos puros con estimadores perfectos, el producto domina a ambas marginales
    c2 = grid["comp_l1.0_clean"]
    assert c2["rvalue_prod"] > max(c2["empowerment"], c2["relevance"]) + 0.05


def _cell(prod, emp, rel):
    return {"oracle": 1.0, "empowerment": emp, "relevance": rel,
            "rvalue_prod": prod, "rvalue_add": prod, "random": 0.2}


def _grid(comp_advs, subs_advs):
    g = {}
    for fam, advs in (("comp", comp_advs), ("subs", subs_advs)):
        for lam in X.LAMS:
            prod = 0.5 + advs[lam]
            for noise in ("noisy", "clean"):
                g["{}_l{}_{}".format(fam, lam, noise)] = _cell(prod, 0.5, 0.5)
    return g


_ROBUST = {0.0: 0.20, 0.25: 0.20, 0.5: 0.20, 0.75: 0.20, 1.0: 0.20}
_DECAY = {0.0: 0.20, 0.25: 0.12, 0.5: 0.06, 0.75: 0.03, 1.0: -0.03}
_HASZERO = {0.0: 0.20, 0.25: 0.20, 0.5: 0.04, 0.75: 0.20, 1.0: 0.20}


def test_verdict_apoyada():
    sm = X.build_summary(_grid(_ROBUST, _DECAY), 50, 10)
    assert sm["status"] == "apoyada"
    assert sm["comp_robust_all"] and sm["subs_breaks_extreme"]


def test_verdict_refutada_universal():
    sm = X.build_summary(_grid(_ROBUST, _ROBUST), 50, 10)  # producto vence en ambas familias en todo λ
    assert sm["status"] == "refutada"


def test_verdict_refutada_fragile():
    sm = X.build_summary(_grid(_HASZERO, _DECAY), 50, 10)  # no robusto bajo complementos + se rompe en sustitutos
    assert sm["status"] == "refutada"


def test_verdict_mixta():
    sm = X.build_summary(_grid(_HASZERO, _ROBUST), 50, 10)  # incoherente: frágil en comp, universal en subs
    assert sm["status"] == "mixta"
