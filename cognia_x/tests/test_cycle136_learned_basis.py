r"""
CYCLE 136 / H-V4-10j — regresión (MIXTA / refutación ACOTADA, post-verificación adversarial). El cuello R-PRIOR de la relevancia
bajo no-linealidad es REGIME-DEPENDENT: EN ABUNDANCIA (T>>#columnas) un aprendiz que NO conoce la forma -cross-validando la
regularización (rich_cv) y/o seleccionando la base (select_cv)- neutraliza el grueso de la ventaja del oracle-prior (el 'prior
paga' de 135 era sub-regularización; residual chico pero significativo); EN ESCASEZ (T~#columnas) el prior REAPARECE.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle136_learned_basis.py -q
"""
from cognia_x.experiments.exp120_learned_basis import run as X


def test_mixta_refutacion_acotada():
    grid = X.run(n_seeds=80)
    sm = X.build_summary(grid)
    assert sm["status"] == "mixta", sm["verdict"]
    assert sm["abundant_neutralizes"], (sm["gap_richcv"],)        # el CV neutraliza el grueso en abundancia
    assert sm["scarce_prior_pays"], sm["gap_scarce"]              # pero el prior reaparece en escasez


def test_abundancia_cv_neutraliza_el_grueso_del_prior():
    # en abundancia (σ_g=20) el aprendiz-CV cierra la mayor parte del gap de 135
    grid = X.run(n_seeds=80)
    sm = X.build_summary(grid)
    assert sm["gap_richfix"] > 0.15, sm["gap_richfix"]            # el gap de 135 (ridge fijo) es grande
    assert sm["gap_richcv"] < 0.08, sm["gap_richcv"]              # el CV lo cierra
    assert sm["closed_frac"] > 0.6, sm["closed_frac"]            # cierra >60% del gap
    # FAIRNESS: dar a la matched el mismo CV-ridge NO la separa mucho de rich_cv (no era ridge-fijo)
    assert sm["gap_matchedcv_richcv"] < 0.10, sm["gap_matchedcv_richcv"]


def test_escasez_el_prior_reaparece():
    # bajo escasez (T~#columnas, ruido moderado) rich_cv (genuinamente sin-forma) colapsa y el prior paga fuerte
    grid = X.run(n_seeds=80)
    sm = X.build_summary(grid)
    assert sm["gap_scarce"] > 0.15, sm["gap_scarce"]
    assert sm["scarce_rich_cv"] < sm["scarce_matched_cv"] - 0.15, (sm["scarce_rich_cv"], sm["scarce_matched_cv"])


def test_aprendices_sin_forma_recuperan_todas_las_formas_en_abundancia():
    grid = X.run(n_seeds=80)
    bf = grid["by_form"]
    for form in X.META_FORMS:
        assert bf[form]["rich_cv"] > 0.88, (form, bf[form]["rich_cv"])
        assert bf[form]["select_cv"] > 0.88, (form, bf[form]["select_cv"])


def test_descubrimiento_real_no_colapsa_a_control():
    grid = X.run(n_seeds=80)
    ev = grid["by_form"]["even"]
    assert ev["rich_cv"] - ev["ctrl_solo"] > 0.4, (ev["rich_cv"], ev["ctrl_solo"])
