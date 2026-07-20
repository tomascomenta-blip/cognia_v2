r"""
CYCLE 56 / H-V4-1b — regresión: aislar el valor de info-gain con post_on_cause (instrumento fiel).

Protege: (a) regime_stats computa post_BminusC y sign_BgtC; (b) las 3 ramas del veredicto (APOYADA aislamiento
robusto / REFUTADA sin valor / MIXTA modesto). Sin correr el experimento bayesiano -> instantáneo.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle56_value_isolation_post.py -q
"""
from cognia_x.experiments.exp042_value_isolation_post import run as X


def _cell(postB, postC, accB, accC):
    return {"A_pasivo": {"post_on_cause": 0.2, "interv": 0.6, "iid": 0.9},
            "B_infogain": {"post_on_cause": postB, "interv": accB, "iid": 0.9},
            "C_aleatorio": {"post_on_cause": postC, "interv": accC, "iid": 0.9}}


def _regime(budgets, perK, n=6):
    """perK[K] = (postB, postC, accB, accC); n seeds idénticas."""
    return [{"by_budget": {str(K): _cell(*perK[K]) for K in budgets}} for _ in range(n)]


def test_regime_stats_computes_gap_and_sign():
    budgets = [8, 24]
    r = _regime(budgets, {8: (0.21, 0.21, 0.69, 0.72), 24: (0.85, 0.54, 0.95, 0.81)})
    st = X.regime_stats(r, budgets, 6)
    assert abs(st["24"]["post_BminusC"] - 0.31) < 1e-6
    assert st["24"]["sign_BgtC"] == 1.0          # todas las seeds B>C
    assert abs(st["24"]["acc_BminusC"] - 0.14) < 1e-6


def _summary(perK_hard):
    budgets = [8, 24]
    easy = _regime(budgets, {8: (0.55, 0.40, 0.95, 0.93), 24: (0.99, 0.98, 1.0, 1.0)})
    hard = _regime(budgets, perK_hard)
    return X.build_summary(easy, hard, budgets, 6)


def test_verdict_apoyada_isolation():
    sm = _summary({8: (0.21, 0.21, 0.69, 0.72), 24: (0.85, 0.54, 0.95, 0.81)})
    assert sm["status"] == "apoyada"
    assert sm["post_iso_hard_Kmax"] > 0.15 and sm["grows_with_K"] and sm["acc_masks_value"]


def test_verdict_refutada_no_value():
    sm = _summary({8: (0.30, 0.32, 0.70, 0.71), 24: (0.50, 0.55, 0.90, 0.92)})
    assert sm["status"] == "refutada"           # B-C post <= 0 a Kmax


def test_verdict_mixta_modest():
    sm = _summary({8: (0.30, 0.30, 0.70, 0.70), 24: (0.55, 0.48, 0.90, 0.88)})
    assert sm["status"] == "mixta"              # +0.07 < umbral fuerte 0.15
