r"""
CYCLE 57 / H-V4-1c — regresión: señal de valor ENDÓGENA (confianza calibrada).

Protege: (a) agg_regime computa calibración y confidently_wrong; (b) las 3 ramas del veredicto (APOYADA señal
endógena calibrada / REFUTADA miscalibrada / MIXTA imperfecta). Sin correr el bayesiano -> instantáneo.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle57_endogenous_signal.py -q
"""
from cognia_x.experiments.exp043_endogenous_signal import run as X


def _rows(spec, K=24, n=10):
    """spec = {agent: (conf, n_correct)}; n seeds, conf fijo, primeros n_correct con correct=1."""
    rows = []
    for agent, (conf, n_corr) in spec.items():
        for s in range(n):
            rows.append({"seed": s, "K": K, "agent": agent, "conf": conf,
                         "correct": 1 if s < n_corr else 0, "entropy": 1.0, "post_on_cause": conf})
    return rows


def test_agg_regime_calibration_and_confidently_wrong():
    rows = _rows({"A_pasivo": (0.10, 0), "B_infogain": (0.88, 9), "C_aleatorio": (0.70, 7)})
    a = X.agg_regime(rows, [24], tau=0.5)["24"]
    assert abs(a["B_infogain"]["calibration_P_correct_given_confident"] - 0.9) < 1e-6
    assert abs(a["B_infogain"]["confidently_wrong"] - 0.1) < 1e-6
    assert abs(a["C_aleatorio"]["confidently_wrong"] - 0.3) < 1e-6   # 3/10 confiado-equivocado
    assert a["A_pasivo"]["frac_confident"] == 0.0                    # 0.10 < tau -> nunca confiado


def _summary(spec):
    rows = _rows(spec)
    return X.build_summary(rows, rows, [24], 10, tau=0.5)


def test_verdict_apoyada_calibrated_signal():
    sm = _summary({"A_pasivo": (0.10, 0), "B_infogain": (0.88, 9), "C_aleatorio": (0.70, 7)})
    assert sm["status"] == "apoyada"
    assert sm["endo_ranks_BgtC"] and sm["well_calibrated"]


def test_verdict_refutada_miscalibrated():
    # B confiado pero a menudo equivocado -> calib baja, confidently_wrong alto
    sm = _summary({"A_pasivo": (0.10, 0), "B_infogain": (0.88, 4), "C_aleatorio": (0.70, 7)})
    assert sm["status"] == "refutada"


def test_verdict_mixta_imperfect():
    # B rankea y calib 0.80 pero confidently_wrong 0.20 (>=0.15) -> no del todo confiable
    sm = _summary({"A_pasivo": (0.10, 0), "B_infogain": (0.88, 8), "C_aleatorio": (0.70, 7)})
    assert sm["status"] == "mixta"
