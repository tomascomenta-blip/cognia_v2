r"""
CYCLE 152 / H-V4-9l — regresión: ¿el residuo de calibración GENÉRICO (ls_lo, único superviviente del 151) PAGA DOWNSTREAM en una
decisión real bajo escasez (precision@top-m)? + ¿sobre candidatos HELD-OUT (forma novel)?

ACOTACIÓN load-bearing (verificación adversarial del 152): precision@top-m sobre un pool BALANCEADO 50/50 está TOPADA en 1.0 ->
si el naive ya rankea near-perfecto (AUROC alto) la métrica SATURA y el gap es CERO ESTRUCTURAL (no evidencia). build_summary
detecta saturación (naive precision@top-m de escasez ~1.0 -> pool NO informativo) y basa el veredicto SÓLO en pools informativos.
El lazo torch es LENTO -> el test NO re-corre; valida la LÓGICA del gate (saturación/informative/robusto/borderline) + consistencia
del results.json commiteado.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle152_downstream_payoff.py -q
"""
import json
import os

import numpy as np

from cognia_x.experiments.exp134_downstream_payoff import run as X

RESULTS = os.path.join(os.path.dirname(X.__file__), "results", "results.json")


def _mk(seed, naive_pay, lslo_gap, dur_gap, rng, rounds=4, jit=0.003):
    """per_seed sintético: payoff por arm/pool/m = naive_pay[pool] + gap (gap 0 naive, lslo_gap/dur_gap por pool). AUROC dummy."""
    def series(mu):
        return [float(np.clip(mu + jit * rng.standard_normal(), 0.0, 1.0)) for _ in range(rounds)]
    hist = {}
    for a in X.ARMS:
        hist[a] = {}
        for p in X.POOLS:
            g = lslo_gap[p] if a == "ls_lo" else (dur_gap[p] if a == "durable" else 0.0)
            hist[a][p] = {"auroc": series(0.90 if a != "naive" else 0.88),
                          "payoff": {m: series(naive_pay[p] + g) for m in X.M_GRID}}
    return {"seed": seed, "base": {"real_acc": 0.4}, "fixed_ncorrect": {p: 48 for p in X.POOLS},
            "fixed_npool": {p: 96 for p in X.POOLS}, "hist": hist}


def test_logica_refutada_pool_informativo_sin_pago():
    # pools INFORMATIVOS (naive 0.8/0.62, no saturados) y ls_lo NO paga (gap 0) -> REFUTADA.
    rng = np.random.default_rng(1)
    ps = [_mk(i, {"indist": 0.80, "heldout": 0.62}, {"indist": 0.0, "heldout": 0.0}, {"indist": -0.15, "heldout": -0.15}, rng) for i in range(6)]
    sm = X.build_summary(ps, n_boot=2000)
    assert sm["status"] == "refutada", (sm["status"], sm["saturated"], sm["informative_pools"], sm["lslo_robust"])
    assert sm["informative_pools"] and not any(sm["saturated"].values()), (sm["informative_pools"], sm["saturated"])


def test_logica_apoyada_residuo_paga_robusto_en_informativo():
    # pool informativo + ls_lo paga ROBUSTO -> APOYADA.
    rng = np.random.default_rng(2)
    ps = [_mk(i, {"indist": 0.80, "heldout": 0.62}, {"indist": 0.08, "heldout": 0.07}, {"indist": -0.1, "heldout": -0.1}, rng) for i in range(6)]
    sm = X.build_summary(ps, n_boot=2000)
    assert sm["status"] == "apoyada", (sm["status"], sm["lslo_robust"])
    assert any(sm["lslo_robust"][p] for p in sm["informative_pools"]), sm["lslo_robust"]


def test_logica_mixta_cuando_todos_los_pools_saturan():
    # AMBOS pools SATURADOS (naive precision@top-m ~1.0) -> ningún pool informativo -> INCONCLUSO = MIXTA
    # (no se puede refutar lo que la métrica saturada no pudo testear) — el corazón de la acotación del 152.
    rng = np.random.default_rng(3)
    ps = [_mk(i, {"indist": 1.0, "heldout": 1.0}, {"indist": 0.0, "heldout": 0.0}, {"indist": 0.0, "heldout": 0.0}, rng) for i in range(6)]
    sm = X.build_summary(ps, n_boot=2000)
    assert sm["status"] == "mixta", (sm["status"], sm["saturated"], sm["informative_pools"])
    assert all(sm["saturated"].values()) and sm["informative_pools"] == [], (sm["saturated"], sm["informative_pools"])


def test_results_committeado_consistente():
    if not os.path.exists(RESULTS):
        import pytest
        pytest.skip("results.json aún no generado (corre exp134 primero)")
    with open(RESULTS, encoding="utf-8") as f:
        d = json.load(f)
    s = d["summary"]
    assert d["cycle"] == 152 and d["hypothesis"] == "H-V4-9l", (d.get("cycle"), d.get("hypothesis"))
    assert d["verdict"] in ("apoyada", "refutada", "mixta") and d["verdict"] == s["status"], (d["verdict"], s["status"])
    # la corrida real: INDIST saturado (no informativo), HELDOUT informativo, ls_lo NO robusto en ninguno -> MIXTA-acotada
    assert s["saturated"]["indist"] is True, ("INDIST debería saturar (near-ceiling)", s["naive_scarce_payoff"])
    assert "heldout" in s["informative_pools"], s["informative_pools"]
    assert not any(s["lslo_robust"].values()), s["lslo_robust"]
    if s["status"] == "apoyada":
        assert any(s["lslo_robust"][p] for p in s["informative_pools"]), s["lslo_robust"]
    # pools balanceados por construcción
    for r in d["raw"]:
        for p in X.POOLS:
            frac = r["fixed_ncorrect"][p] / max(1, r["fixed_npool"][p])
            assert 0.25 < frac < 0.75, (r["seed"], p, frac)
