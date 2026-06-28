r"""
CYCLE 151 / H-V4-9k — regresión: ¿el payoff de calibración del lazo real (149 durable>naive, 150 ls_lo) es una señal de
ranking GENUINA o un artefacto de la RIQUEZA DE GENERACIÓN? El desconfound: que TODOS los brazos rankeen un POOL FIJO
COMPARTIDO Y BALANCEADO (candidatos construidos con etiqueta conocida vía el verificador real) -> AUROC_fixed aísla la
calidad de ranking de la riqueza de su propia generación.

El lazo torch es LENTO (3 brazos) -> el test NO re-corre el lazo; valida la LÓGICA del desconfound de build_summary sobre
datos sintéticos (REFUTADA si ninguna ventaja FIXED sobrevive ni en signo; APOYADA si alguna sobrevive ROBUSTA -CI excluye 0 Y
t-test pareado significativo-; MIXTA si una se invierte y otra sobrevive sólo en SIGNO -no robusta-) + verifica la consistencia
interna del results.json commiteado. La compuerta dura es el t-test pareado: 'CI bootstrap excluye 0' es TAUTOLÓGICO con gaps
todos del mismo signo (no mide robustez) — verificación adversarial del 151.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle151_deconfound_calibration.py -q
"""
import json
import os

import numpy as np

from cognia_x.experiments.exp133_deconfound_calibration import run as X

RESULTS = os.path.join(os.path.dirname(X.__file__), "results", "results.json")


def _mk(seed, own, fix, rng, rounds=4, jit=0.006):
    """per_seed sintético para exp133: AUROC_own y AUROC_fixed por brazo (medias `own`/`fix` por arm + jitter)."""
    def series(mu):
        return [float(mu + jit * rng.standard_normal()) for _ in range(rounds)]
    hist = {a: {"auroc_own": series(own[a]), "auroc_fixed": series(fix[a]),
                "ncorrect": [40] * rounds, "npool": [384] * rounds} for a in X.ARMS}
    return {"seed": seed, "base": {"real_acc": 0.4}, "fixed_ncorrect": 48, "fixed_npool": 96, "hist": hist}


def _mk_exact(seed, own_gap, fix_gap, rounds=4, base_own=0.93, base_fix=0.97):
    """per_seed con gaps EXACTOS (series constantes): _auc_over_rounds da el gap pedido sin ruido -> controla t-stat por la
    dispersión entre seeds (no within). own_gap/fix_gap son dicts arm->gap respecto a naive (naive gap=0)."""
    hist = {a: {"auroc_own": [base_own + own_gap[a]] * rounds, "auroc_fixed": [base_fix + fix_gap[a]] * rounds,
                "ncorrect": [40] * rounds, "npool": [384] * rounds} for a in X.ARMS}
    return {"seed": seed, "base": {"real_acc": 0.4}, "fixed_ncorrect": 48, "fixed_npool": 96, "hist": hist}


def test_logica_refutada_cuando_no_sobrevive_ni_en_signo():
    # OWN: durable y ls_lo > naive. FIXED: durable SE DESPLOMA, ls_lo POR DEBAJO de naive (no sobrevive ni en signo) -> REFUTADA.
    rng = np.random.default_rng(1)
    own = {"naive": 0.86, "durable": 0.99, "ls_lo": 0.98}
    fix = {"naive": 0.965, "durable": 0.70, "ls_lo": 0.955}
    ps = [_mk(i, own, fix, rng) for i in range(6)]
    sm = X.build_summary(ps, n_boot=3000)
    assert sm["status"] == "refutada", (sm["status"], sm["fixed_durable_vs_naive"], sm["fixed_lslo_vs_naive"])
    assert sm["own_had_advantage"] and not sm["fixed_sign"], (sm["own_had_advantage"], sm["fixed_sign"])
    assert sm["fixed_durable_vs_naive"]["mean"] < 0, sm["fixed_durable_vs_naive"]["mean"]


def test_logica_apoyada_cuando_la_ventaja_fixed_es_robusta():
    # FIXED: ls_lo claramente arriba del naive y consistente -> CI excluye 0 Y t-test significativo -> ROBUSTA -> APOYADA.
    rng = np.random.default_rng(2)
    own = {"naive": 0.86, "durable": 0.99, "ls_lo": 0.98}
    fix = {"naive": 0.95, "durable": 0.70, "ls_lo": 0.985}
    ps = [_mk(i, own, fix, rng) for i in range(6)]
    sm = X.build_summary(ps, n_boot=3000)
    assert sm["status"] == "apoyada", (sm["status"], sm["fixed_lslo_vs_naive"])
    assert sm["fixed_robust"] and sm["fixed_survives"], sm["fixed_lslo_vs_naive"]
    assert abs(sm["fixed_lslo_vs_naive"]["tstat"]) >= sm["t_crit_one_tail_05"], (sm["fixed_lslo_vs_naive"]["tstat"], sm["t_crit_one_tail_05"])


def test_logica_mixta_cuando_durable_invierte_y_lslo_solo_en_signo():
    # Reproduce el caso REAL del 151: durable se INVIERTE; ls_lo todos los gaps positivos PERO t-test sub-significativo (no robusto).
    lslo_gaps = [0.036, 0.008, 0.053, 0.003, 0.0001, 0.006]   # los gaps FIXED ls_lo−naive reales (N=6) -> media ~0.0175, t<2.015
    ps = [_mk_exact(i, own_gap={"naive": 0.0, "durable": 0.057, "ls_lo": 0.052},
                    fix_gap={"naive": 0.0, "durable": -0.21, "ls_lo": g}) for i, g in enumerate(lslo_gaps)]
    sm = X.build_summary(ps, n_boot=3000)
    assert sm["status"] == "mixta", (sm["status"], sm["fixed_lslo_vs_naive"]["tstat"], sm["t_crit_one_tail_05"])
    assert sm["durable_inverts"], sm["fixed_durable_vs_naive"]
    assert sm["fixed_sign"] and not sm["fixed_robust"], (sm["fixed_sign"], sm["fixed_robust"])
    # la firma del 151: ls_lo todos positivos pero t-test por DEBAJO del crítico (CI-excluye-0 sería tautológico)
    assert sm["fixed_lslo_vs_naive"]["n_positive"] == sm["fixed_lslo_vs_naive"]["n"], sm["fixed_lslo_vs_naive"]
    assert abs(sm["fixed_lslo_vs_naive"]["tstat"]) < sm["t_crit_one_tail_05"], (sm["fixed_lslo_vs_naive"]["tstat"], sm["t_crit_one_tail_05"])


def test_results_committeado_consistente():
    if not os.path.exists(RESULTS):
        import pytest
        pytest.skip("results.json aún no generado (corre exp133 primero)")
    with open(RESULTS, encoding="utf-8") as f:
        d = json.load(f)
    s = d["summary"]
    assert d["cycle"] == 151 and d["hypothesis"] == "H-V4-9k", (d.get("cycle"), d.get("hypothesis"))
    assert d["verdict"] in ("apoyada", "refutada", "mixta"), d["verdict"]
    assert d["verdict"] == s["status"], (d["verdict"], s["status"])
    # consistencia interna de la compuerta del desconfound (robusta, no el CI tautológico)
    if s["status"] == "refutada":
        assert s["own_had_advantage"] and not s["fixed_sign"], (s["own_had_advantage"], s["fixed_sign"])
    if s["status"] == "apoyada":
        assert s["fixed_robust"], s["fixed_robust"]
    if s["status"] == "mixta":
        # el caso real: durable se invierte y/o sólo sobrevive el signo sin robustez por t-test
        assert s["durable_inverts"] or (s["fixed_sign"] and not s["fixed_robust"]), (s["durable_inverts"], s["fixed_sign"], s["fixed_robust"])
    # el pool fijo debe estar BALANCEADO por construcción (no el 7%-positivo del diseño viejo generado-desde-base)
    for r in d["raw"]:
        frac = r["fixed_ncorrect"] / max(1, r["fixed_npool"])
        assert 0.25 < frac < 0.75, (r["seed"], r["fixed_ncorrect"], r["fixed_npool"], frac)
