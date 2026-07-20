r"""
CYCLE 91 / H-V4-3a — regresión: la FORMA/CALIDAD del prior fija la eficiencia muestral (R-PRIOR/H-V4-3). Protege: (a) en
la corrida real, el prior MATCHEADO (rbf local) es sample-efficient (rbf_low >= bin_high) y supera a poly2 -> apoyada;
(b) el rbf encode el TIPO de estructura, no las bandas exactas; (c) las ramas del veredicto.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle91_matched_prior.py -q
"""
from cognia_x.experiments.exp075_matched_prior import run as X


def test_rbf_encodes_structure_not_exact_bands():
    # el prior matcheado = bumps locales en c × lineal en r (18 features), centros equiespaciados (no en las bandas)
    import numpy as np
    feats = X._rbf_feats(np.array([0.3, 0.7]), np.array([0.5, 0.9]))
    assert feats.shape == (2, 2 * len(X.RBF_C))
    assert len(X.RBF_C) >= 5 and abs(X.RBF_C[0] - 0.0) < 1e-9 and abs(X.RBF_C[-1] - 1.0) < 1e-9


def test_matched_prior_sample_efficient_real_run():
    grid = X.run(n=50, k_budget=10, k_eval=10, E_rounds=12, sc=0.2, n_seeds=12)
    sm = X.build_summary(grid)
    # rbf a presupuesto BAJO iguala/supera a bin a presupuesto ALTO (a fracción del costo)
    assert sm["fraction_of_cost"], sm["rbf_fraction_cost_vs_bin_high"]
    # rbf gana a bin a igual bajo presupuesto, y supera a la base equivocada poly2
    assert sm["sample_efficient"], sm["rbf_sample_eff_vs_bin_low"]
    assert sm["beats_poly2"], sm["rbf_vs_poly2"]
    # rbf satura más rápido que bin (no data-hungry)
    assert sm["rbf_saturates"] <= sm["bin_data_hungry"] + 0.02
    assert sm["status"] == "apoyada"


def _cell(prod, p2, bn, rbf, bayes, oracle, chance):
    return {"product": prod, "learned_poly2": p2, "learned_bin": bn, "learned_rbf": rbf,
            "bayes": bayes, "oracle": oracle, "chance": chance}


def _grid(low, high):
    return {"low": _cell(*low), "high": _cell(*high)}


def test_verdict_apoyada():
    # rbf_low (0.687) >= bin_high (0.620); rbf_low > bin_low (0.540); rbf >> poly2
    sm = X.build_summary(_grid(low=(0.33, 0.46, 0.540, 0.687, 0.825, 1.0, 0.23),
                               high=(0.33, 0.499, 0.620, 0.720, 0.833, 1.0, 0.22)))
    assert sm["status"] == "apoyada"
    assert sm["sample_efficient"] and sm["fraction_of_cost"] and sm["beats_poly2"]


def test_verdict_refutada_form_no_help():
    # rbf ≈ bin/poly2: la forma del prior no aporta
    sm = X.build_summary(_grid(low=(0.33, 0.50, 0.51, 0.51, 0.825, 1.0, 0.23),
                               high=(0.33, 0.52, 0.53, 0.53, 0.833, 1.0, 0.22)))
    assert not sm["beats_poly2"]
    assert sm["status"] == "refutada"


def test_verdict_mixta_partial():
    # rbf gana a bin_low y a poly2 pero NO alcanza bin_high (no a fracción del costo)
    sm = X.build_summary(_grid(low=(0.33, 0.46, 0.540, 0.60, 0.825, 1.0, 0.23),
                               high=(0.33, 0.499, 0.660, 0.70, 0.833, 1.0, 0.22)))
    assert not sm["fraction_of_cost"]
    assert sm["sample_efficient"] and sm["beats_poly2"]
    assert sm["status"] == "mixta"
