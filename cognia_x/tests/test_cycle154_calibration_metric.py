r"""
CYCLE 154 / H-V4-9n — regresión: ¿la CALIBRACIÓN del residuo (ls_lo) paga SEPARADA del ranking? El 153 halló un payoff RANK-ONLY
(precision@top-m re-expresa el AUROC del 151). exp136 mide métricas SENSIBLES A MAGNITUDES (Brier, ECE=calibración pura, NET
umbral-abstención) vs AUROC rank-only. APOYADA si ls_lo tiene ventaja robusta en calibración; REFUTADA si la ventaja vive en AUROC
pero se desvanece en ECE/Brier/NET (ranking re-expresado); MIXTA si parcial.

El lazo torch es LENTO -> el test NO re-corre; valida la LÓGICA del gate (robust_cal / rank_only / sign_cal) + consistencia del
results.json commiteado.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle154_calibration_metric.py -q
"""
import json
import os

import numpy as np

from cognia_x.experiments.exp136_calibration_metric import run as X

RESULTS = os.path.join(os.path.dirname(X.__file__), "results", "results.json")


def _mk(seed, auroc_d, ece_imp, brier_imp, net_imp, rng, rounds=4, jit=0.004):
    """per_seed sintético. ls_lo: AUROC +auroc_d, ECE −ece_imp (mejor), Brier −brier_imp, NET +net_imp vs naive. durable peor."""
    def series(mu):
        return [float(np.clip(mu + jit * rng.standard_normal(), 0.0, 1.0)) for _ in range(rounds)]
    base = {"auroc": 0.88, "brier": 0.20, "ece": 0.15, "net": {1: 0.3, 3: 0.2, 7: 0.1}}
    hist = {}
    for a in X.ARMS:
        if a == "naive":
            au, br, ec, nt = base["auroc"], base["brier"], base["ece"], dict(base["net"])
        elif a == "ls_lo":
            au, br, ec = base["auroc"] + auroc_d, base["brier"] - brier_imp, base["ece"] - ece_imp
            nt = {lam: base["net"][lam] + net_imp for lam in X.LAMBDAS}
        else:  # durable peor en todo
            au, br, ec = 0.72, 0.30, 0.25
            nt = {lam: base["net"][lam] - 0.1 for lam in X.LAMBDAS}
        hist[a] = {}
        for p in X.POOLS:
            hist[a][p] = {"auroc": series(au), "brier": series(br), "ece": series(ec),
                          "net": {lam: series(nt[lam]) for lam in X.LAMBDAS}}
    return {"seed": seed, "base": {"real_acc": 0.4}, "fixed_ncorrect": {p: 20 for p in X.POOLS},
            "fixed_npool": {p: 160 for p in X.POOLS}, "hist": hist}


def test_logica_apoyada_calibracion_robusta():
    # ls_lo claramente MEJOR CALIBRADO (ECE −0.05) y consistente -> robust_cal -> APOYADA.
    rng = np.random.default_rng(2)
    ps = [_mk(i, auroc_d=0.03, ece_imp=0.05, brier_imp=0.04, net_imp=0.08, rng=rng) for i in range(6)]
    sm = X.build_summary(ps, n_boot=2000)
    assert sm["status"] == "apoyada", (sm["status"], sm["robust_ece"], sm["neg_ece_gap"]["indist"]["ls_lo"])
    assert sm["robust_ece"], sm["robust_ece"]   # APOYADA exige reliability PURA (ECE) robusta, no Brier/NET (resolution)


def test_logica_refutada_rank_only():
    # ls_lo MEJOR en AUROC (ranking) pero IGUAL en calibración (ECE/Brier/NET ~0) -> rank_only -> REFUTADA-calibración.
    rng = np.random.default_rng(1)
    ps = [_mk(i, auroc_d=0.05, ece_imp=0.0, brier_imp=0.0, net_imp=0.0, rng=rng) for i in range(6)]
    sm = X.build_summary(ps, n_boot=2000)
    assert sm["status"] == "refutada", (sm["status"], sm["rank_only"], sm["sign_cal"], sm["auroc_pos"], sm["ece_vanishes"])
    assert sm["rank_only"] and not sm["robust_cal"], (sm["rank_only"], sm["robust_cal"])


def test_logica_mixta_sin_ventaja_concluyente():
    # SIN ventaja de ranking (AUROC no-positivo) ni de calibración robusta -> ni rank_only ni robust_cal -> MIXTA (inconcluso).
    rng = np.random.default_rng(5)
    ps = [_mk(i, auroc_d=-0.02, ece_imp=0.0, brier_imp=0.0, net_imp=0.0, rng=rng, jit=0.01) for i in range(6)]
    sm = X.build_summary(ps, n_boot=2000)
    assert sm["status"] == "mixta", (sm["status"], sm["robust_ece"], sm["rank_only"], sm["auroc_pos"])
    assert not sm["robust_ece"] and not sm["rank_only"], (sm["robust_ece"], sm["rank_only"])


def test_results_committeado_consistente():
    if not os.path.exists(RESULTS):
        import pytest
        pytest.skip("results.json aún no generado (corre exp136 primero)")
    with open(RESULTS, encoding="utf-8") as f:
        d = json.load(f)
    s = d["summary"]
    assert d["cycle"] == 154 and d["hypothesis"] == "H-V4-9n", (d.get("cycle"), d.get("hypothesis"))
    assert d["verdict"] in ("apoyada", "refutada", "mixta") and d["verdict"] == s["status"], (d["verdict"], s["status"])
    if s["status"] == "apoyada":
        assert s["robust_ece"], s["robust_ece"]
    if s["status"] == "refutada":
        assert s["rank_only"] and not s["sign_cal"], (s["rank_only"], s["sign_cal"])
        # la corrida real: ECE (reliability pura) no paga + NET heldout degenerado (no-evidencia)
        assert not s["robust_ece"], s["robust_ece"]
        assert s["net_degenerate"]["heldout"] is True, s["net_degenerate"]
    for p in X.POOLS:
        assert 0.05 <= s["base_rate"][p] <= 0.30, (p, s["base_rate"][p])
