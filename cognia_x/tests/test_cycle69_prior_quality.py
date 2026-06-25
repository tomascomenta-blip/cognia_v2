r"""
CYCLE 69 / H-V4-3 — regresión: la calidad del prior fija la eficiencia muestral.

Protege: (a) featurize da las dimensiones correctas por prior (correcto=2, general=D+1, equivocado=k+1) y la
tarea es perm-invariante (acc del prior correcto sube con n); (b) las 3 ramas del veredicto. Rápido (numpy).

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle69_prior_quality.py -q
"""
import numpy as np

from cognia_x.experiments.exp054_prior_quality import run as X


def test_featurize_dims():
    rng = np.random.default_rng(0)
    Xb, _ = X.gen(rng, 5, D=20)
    assert X.featurize(Xb, "correcto", 20, 3).shape[1] == 2        # conteo + bias
    assert X.featurize(Xb, "general", 20, 3).shape[1] == 21        # D + bias
    assert X.featurize(Xb, "equivocado", 20, 3).shape[1] == 4      # k + bias


def test_label_is_count_based():
    rng = np.random.default_rng(1)
    Xb, y = X.gen(rng, 200, D=20)
    assert np.all(y == (Xb.sum(1) >= 10).astype(float))            # depende sólo del conteo


def _curves(cor8, gen8, wrong128, gen128):
    nts = ["4", "8", "16", "32", "64", "128"]
    return {"correcto": {n: cor8 for n in nts}, "general": {n: (gen8 if n != "128" else gen128) for n in nts},
            "equivocado": {n: wrong128 for n in nts}}


def test_verdict_apoyada():
    sm = X.build_summary(_curves(0.917, 0.569, 0.635, 0.917), [4, 8, 16, 32, 64, 128])
    assert sm["status"] == "apoyada" and sm["correct_efficient"] and sm["wrong_hurts"]


def test_verdict_refutada():
    sm = X.build_summary(_curves(0.60, 0.58, 0.60, 0.90), [4, 8, 16, 32, 64, 128])  # correcto no eficiente
    assert sm["status"] == "refutada"


def test_verdict_mixta():
    sm = X.build_summary(_curves(0.95, 0.55, 0.90, 0.91), [4, 8, 16, 32, 64, 128])  # eficiente pero equivocado no hunde
    assert sm["status"] == "mixta"
