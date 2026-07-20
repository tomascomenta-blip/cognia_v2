r"""
CYCLE 153 / H-V4-9m — regresión: el diseño CORRECTO del downstream (152 saturó/no-escaso). Pool fijo COMPARTIDO ESCASO
(base-rate ~0.125) + precision@top-m POR f=m/#correct, barriendo el régimen DISCRIMINANTE f≈1 (recall de las pocas correctas).
¿El residuo genérico (ls_lo) PAGA bajo escasez GENUINA?

El lazo torch es LENTO -> el test NO re-corre; valida la LÓGICA del gate (saturación-en-disc / informative / robusto / borderline
en el régimen f≈1) + consistencia del results.json commiteado.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle153_scarce_downstream.py -q
"""
import json
import os

import numpy as np

from cognia_x.experiments.exp135_scarce_downstream import run as X

RESULTS = os.path.join(os.path.dirname(X.__file__), "results", "results.json")


def _mk(seed, naive_pay, lslo_gap, dur_gap, rng, rounds=4, jit=0.003):
    """per_seed sintético: payoff por arm/pool/f = naive_pay[pool] + gap (0 naive). AUROC dummy. base-rate escaso (20/160)."""
    def series(mu):
        return [float(np.clip(mu + jit * rng.standard_normal(), 0.0, 1.0)) for _ in range(rounds)]
    hist = {}
    for a in X.ARMS:
        hist[a] = {}
        for p in X.POOLS:
            g = lslo_gap[p] if a == "ls_lo" else (dur_gap[p] if a == "durable" else 0.0)
            hist[a][p] = {"auroc": series(0.90 if a != "naive" else 0.88),
                          "payoff": {f: series(naive_pay[p] + g) for f in X.F_GRID}}
    return {"seed": seed, "base": {"real_acc": 0.4}, "fixed_ncorrect": {p: 20 for p in X.POOLS},
            "fixed_npool": {p: 160 for p in X.POOLS}, "hist": hist}


def test_logica_refutada_pool_informativo_sin_pago():
    # pools informativos (naive 0.8/0.62) y ls_lo por DEBAJO de naive (sin señal positiva ni tendencia) -> REFUTADA.
    rng = np.random.default_rng(1)
    ps = [_mk(i, {"indist": 0.80, "heldout": 0.62}, {"indist": -0.02, "heldout": -0.02}, {"indist": -0.15, "heldout": -0.15}, rng) for i in range(6)]
    sm = X.build_summary(ps, n_boot=2000)
    assert sm["status"] == "refutada", (sm["status"], sm["saturated_disc"], sm["informative_pools"], sm["lslo_robust_f1"])
    assert sm["informative_pools"], sm["saturated_disc"]


def test_logica_apoyada_residuo_paga_robusto_en_f1_preregistrado():
    # el residuo ls_lo paga ROBUSTO en el f PRE-REGISTRADO (1.0) en un pool informativo -> APOYADA (la brújula decisional 123 vale).
    rng = np.random.default_rng(2)
    ps = [_mk(i, {"indist": 0.80, "heldout": 0.62}, {"indist": 0.08, "heldout": 0.07}, {"indist": -0.1, "heldout": -0.1}, rng) for i in range(6)]
    sm = X.build_summary(ps, n_boot=2000)
    assert sm["status"] == "apoyada", (sm["status"], sm["lslo_robust_f1"])
    assert any(sm["lslo_robust_f1"][p] for p in sm["informative_pools"]), sm["lslo_robust_f1"]


def test_compuerta_anti_cherrypick_f_preregistrado():
    # APOYADA debe descansar en el f PRE-REGISTRADO (1.0), no en el max-t: un pico positivo aislado fuera de f=1.0 NO basta.
    rng = np.random.default_rng(7)
    # ls_lo ~0 en todos los f salvo un único pico estrecho lejos de f=1.0 no se construye aquí; verificamos que el campo
    # cherry-pick se reporta separado del veredicto.
    ps = [_mk(i, {"indist": 0.80, "heldout": 0.62}, {"indist": 0.0, "heldout": 0.0}, {"indist": -0.1, "heldout": -0.1}, rng) for i in range(6)]
    sm = X.build_summary(ps, n_boot=2000)
    assert "lslo_robust_anyf_cherrypick" in sm and "lslo_robust_f1" in sm, list(sm)
    assert sm["status"] in ("refutada", "mixta"), sm["status"]   # ls_lo~0 -> sin robustez en f=1.0


def test_logica_mixta_cuando_disc_satura():
    # AMBOS pools saturan el régimen discriminante (naive ~1.0 en f≈1) -> ningún informativo -> MIXTA (inconcluso).
    rng = np.random.default_rng(3)
    ps = [_mk(i, {"indist": 1.0, "heldout": 1.0}, {"indist": 0.0, "heldout": 0.0}, {"indist": 0.0, "heldout": 0.0}, rng) for i in range(6)]
    sm = X.build_summary(ps, n_boot=2000)
    assert sm["status"] == "mixta", (sm["status"], sm["saturated_disc"], sm["informative_pools"])
    assert all(sm["saturated_disc"].values()) and sm["informative_pools"] == [], (sm["saturated_disc"], sm["informative_pools"])


def test_results_committeado_consistente():
    if not os.path.exists(RESULTS):
        import pytest
        pytest.skip("results.json aún no generado (corre exp135 primero)")
    with open(RESULTS, encoding="utf-8") as f:
        d = json.load(f)
    s = d["summary"]
    assert d["cycle"] == 153 and d["hypothesis"] == "H-V4-9m", (d.get("cycle"), d.get("hypothesis"))
    assert d["verdict"] in ("apoyada", "refutada", "mixta") and d["verdict"] == s["status"], (d["verdict"], s["status"])
    if s["status"] == "apoyada":
        assert any(s["lslo_robust_f1"][p] for p in s["informative_pools"]), s["lslo_robust_f1"]
    # pool ESCASO por construcción (base-rate baja, ~0.125), NO el 50/50 del 152
    for p in X.POOLS:
        assert 0.05 <= s["base_rate"][p] <= 0.30, (p, s["base_rate"][p])
    for r in d["raw"]:
        for p in X.POOLS:
            frac = r["fixed_ncorrect"][p] / max(1, r["fixed_npool"][p])
            assert 0.05 <= frac <= 0.30, (r["seed"], p, frac)
