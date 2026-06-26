r"""
CYCLE 111 / H-V4-8p — regresión (MIXTA): la guardia de diversidad (94) ayuda a conf-alloc pero no vence a random_low; el
valor del filtro depende de la tasa base de calidad del pool. El lazo usa torch (lento) -> se protege la LÓGICA del
veredicto (build_summary); el run real se verifica al correr.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle111_guard_diversity.py -q
"""
from cognia_x.experiments.exp095_guard_diversity import run as X


def _seed(rl, ch, cgh, csc=0.39):
    return {"hist": {"random_low": {"real": [0.3] + rl, "yield": [30, 30], "ntrain": [30, 30]},
                     "conf_high": {"real": [0.3] + ch, "yield": [9, 9], "ntrain": [9, 9]},
                     "conf_guard_high": {"real": [0.3] + cgh, "yield": [8, 8], "ntrain": [12, 12]}},
            "base": {"real_acc": 0.3}, "conf_strong_corr": csc}


def test_verdict_mixta_guard_helps_but_below_random():
    # la guardia ayuda (cgh > ch) pero cgh < random_low -> mixta
    per = [_seed([0.73, 0.74], [0.57, 0.40], [0.71, 0.55]),
           _seed([0.68, 0.82], [0.20, 0.30], [0.36, 0.45])]
    sm = X.build_summary(per)
    assert sm["guard_helps"] and not sm["matches_or_beats_random"]
    assert sm["status"] == "mixta"


def test_verdict_apoyada_guard_reaches_random():
    # la guardia ayuda Y cgh >= random_low - margen -> apoyada
    per = [_seed([0.70, 0.70], [0.40, 0.40], [0.70, 0.70]),
           _seed([0.68, 0.68], [0.35, 0.35], [0.69, 0.69])]
    sm = X.build_summary(per)
    assert sm["guard_helps"] and sm["matches_or_beats_random"]
    assert sm["status"] == "apoyada"


def test_verdict_refutada_guard_no_help():
    # la guardia NO ayuda (cgh ≈ ch) -> refutada
    per = [_seed([0.70, 0.70], [0.40, 0.40], [0.41, 0.41]),
           _seed([0.68, 0.68], [0.35, 0.35], [0.36, 0.36])]
    sm = X.build_summary(per)
    assert not sm["guard_helps"]
    assert sm["status"] == "refutada"
