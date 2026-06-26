r"""
CYCLE 90 / H-V4-7h — regresión: el poly2 default del gap #2 NO es universal — falla cuando la media condicional del
verificador REAL no es nesteable (dos bandas interiores); una base rica recupera PARCIALMENTE (MIXTA). Protege: (a) en
la corrida real, poly2 se queda corto del techo bayes y la base rica recupera sólo parcial -> mixta; (b) las dos bandas
interiores derrotan al monótono (product) y a la parábola (poly2); (c) las ramas del veredicto.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle90_nonnested_value.py -q
"""
from cognia_x.experiments.exp074_nonnested_value import run as X


def test_two_interior_bands_defeat_monotone_and_parabola():
    # dos bandas interiores: acepta [0.2,0.4)U[0.6,0.8), rechaza extremos y centro
    assert X._well_formed_band(0.30) and X._well_formed_band(0.70)
    assert not X._well_formed_band(0.10)   # extremo bajo
    assert not X._well_formed_band(0.50)   # centro
    assert not X._well_formed_band(0.95)   # extremo alto (derrota al prior monótono)


def test_poly2_not_universal_real_run():
    grid = X.run(n=50, k_budget=10, k_eval=10, E_rounds=12, sc=0.2, n_seeds=12)
    sm = X.build_summary(grid)
    # poly2 se queda corto del techo bayes (no captura la estructura no-nesteable)
    assert sm["poly2_failed"], sm["poly2_short_vs_bayes"]
    # la base rica recupera ALGO sobre poly2 pero NO alcanza bayes -> mixta
    assert sm["bin_recovers_vs_poly2"] > 0.0
    assert not sm["bin_recovered"], sm["bin_short_vs_bayes"]
    assert sm["status"] == "mixta"


def _cell(prod, p2, p4, bn, bayes, oracle, chance):
    return {"product": prod, "learned_poly2": p2, "learned_poly4": p4, "learned_bin": bn,
            "bayes": bayes, "oracle": oracle, "chance": chance}


def _grid(low, high):
    return {"low": _cell(*low), "high": _cell(*high)}


def test_verdict_mixta_partial_recovery():
    # poly2 short de bayes (0.49 vs 0.82); bin recupera +0.12 pero short de bayes (0.21); bin data-hungry
    sm = X.build_summary(_grid(low=(0.33, 0.47, 0.48, 0.53, 0.83, 1.0, 0.23),
                               high=(0.33, 0.49, 0.52, 0.61, 0.82, 1.0, 0.23)))
    assert sm["status"] == "mixta"
    assert sm["poly2_failed"] and not sm["bin_recovered"]


def test_verdict_apoyada_full_recovery():
    # bin recupera y ALCANZA bayes (short <= 0.05) -> apoyada
    sm = X.build_summary(_grid(low=(0.33, 0.49, 0.55, 0.70, 0.82, 1.0, 0.23),
                               high=(0.33, 0.49, 0.60, 0.80, 0.82, 1.0, 0.23)))
    assert sm["poly2_failed"] and sm["bin_recovered"]
    assert sm["status"] == "apoyada"


def test_verdict_refutada_poly2_reaches_bayes():
    # poly2 alcanza bayes (short <= 0.08) -> la estructura era nesteable -> refutada
    sm = X.build_summary(_grid(low=(0.50, 0.79, 0.80, 0.80, 0.82, 1.0, 0.23),
                               high=(0.50, 0.80, 0.81, 0.81, 0.82, 1.0, 0.23)))
    assert not sm["poly2_failed"]
    assert sm["status"] == "refutada"
