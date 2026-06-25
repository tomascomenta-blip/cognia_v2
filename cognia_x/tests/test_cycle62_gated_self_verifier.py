r"""
CYCLE 62 / H-V4-2j — regresión: gating explícito por calibración estimada.

Protege: (a) filter_gated elige ENDÓGENO cuando los consistentes son correctos (calib alta) y EXTERNO cuando son
incorrectos (calib baja); (b) las 3 ramas del veredicto (APOYADA robusto / MIXTA evita colapso sin igualar /
REFUTADA no evita colapso). Sin entrenar modelo -> rápido.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle62_gated_self_verifier.py -q
"""
import numpy as np

from cognia_x.experiments.exp047_gated_self_verifier import run as X


def _pool(targets, expr_fn, s_flag, K=4):
    pool = []
    for n in targets:
        p = "{}=".format(n).encode()
        e = expr_fn(n)
        for _ in range(K):
            pool.append((p, e, s_flag, s_flag))
    return pool


def test_filter_gated_endogenous_when_calibrated():
    # consistentes y CORRECTOS (valor == target) -> calib_est alta -> elige ENDÓGENO
    pool = _pool(range(10, 30), lambda n: "1+{}".format(n - 1).encode(), True)
    kept, info = X.filter_gated(pool, tau=0.5, calib_threshold=0.65, probe_frac=0.5,
                                probe_rng=np.random.default_rng(0))
    assert info["mode"] == "endogenous" and info["calib_est"] >= 0.65
    assert len(kept) > 0


def test_filter_gated_external_when_miscalibrated():
    # consistentes pero INCORRECTOS (valor == target-1) -> calib_est baja -> elige EXTERNO
    pool = _pool(range(10, 30), lambda n: "1+{}".format(n - 2).encode(), False)
    kept, info = X.filter_gated(pool, tau=0.5, calib_threshold=0.65, probe_frac=0.5,
                                probe_rng=np.random.default_rng(0))
    assert info["mode"] == "external" and info["calib_est"] < 0.65


def _regime(base, vf, scf, gf, nf, frac_endo, oracle_frac, n=3):
    return [{"seed": i, "base": base, "frac_endo": frac_endo, "oracle_frac": oracle_frac,
             "hist": {"verified": [base, vf], "self_consistency": [base, scf], "gated": [base, gf],
                      "naive": [base, nf]}} for i in range(n)]


def test_verdict_apoyada_robust():
    strong = _regime(0.63, 0.80, 0.61, 0.74, 0.68, frac_endo=0.9, oracle_frac=0.2)
    weak = _regime(0.18, 0.46, 0.06, 0.42, 0.19, frac_endo=0.1, oracle_frac=0.9)
    sm = X.build_summary(strong, weak, m=90)
    assert sm["status"] == "apoyada"
    assert sm["strong_chooses_endo"] and sm["weak_chooses_ext"] and sm["weak_avoids_collapse"] and sm["weak_matches_verified"]


def test_verdict_mixta_avoids_collapse_no_match():
    strong = _regime(0.63, 0.80, 0.61, 0.74, 0.68, frac_endo=0.9, oracle_frac=0.2)
    weak = _regime(0.18, 0.46, 0.06, 0.20, 0.19, frac_endo=0.3, oracle_frac=0.7)
    sm = X.build_summary(strong, weak, m=90)
    assert sm["status"] == "mixta"
    assert sm["weak_avoids_collapse"] and not sm["weak_matches_verified"]


def test_verdict_refutada_collapses():
    strong = _regime(0.63, 0.80, 0.61, 0.74, 0.68, frac_endo=0.9, oracle_frac=0.2)
    weak = _regime(0.18, 0.46, 0.06, 0.08, 0.19, frac_endo=0.5, oracle_frac=0.6)
    sm = X.build_summary(strong, weak, m=90)
    assert sm["status"] == "refutada"
    assert not sm["weak_avoids_collapse"]
