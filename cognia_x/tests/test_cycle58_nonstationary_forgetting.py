r"""
CYCLE 58 / H-V4-1d — regresión: olvido dirigido por valor en mundo NO-estacionario.

Protege: (a) discounted_update descuenta la evidencia vieja (decay<1 achica el gap de log-evidencia); (b) las
3 ramas del veredicto (APOYADA committed-atascado+olvido-adapta / REFUTADA committed-adapta / MIXTA parcial).
Sin correr el bayesiano completo -> instantáneo.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle58_nonstationary_forgetting.py -q
"""
import numpy as np

from cognia_x.experiments.exp044_nonstationary_forgetting import run as X


def test_discounted_update_forgets_old_evidence():
    # prior fuerte a favor del índice 0; una observación que NO confirma a 0 (x todo 0, y=1)
    base = np.array([10.0, 0.0, 0.0, 0.0])
    x = np.zeros(4, dtype=int)
    committed = X.discounted_update(base.copy(), x, 1, p_obs=0.1, decay=1.0)
    forget = X.discounted_update(base.copy(), x, 1, p_obs=0.1, decay=0.5)
    # el gap de log-evidencia entre el índice 0 y el 1 se escala por decay (la evidencia vieja se desvanece)
    assert abs((committed[0] - committed[1]) - 10.0) < 1e-6
    assert abs((forget[0] - forget[1]) - 5.0) < 1e-6     # decay=0.5 -> mitad del gap


def _by_decay(committed_new, best_new, committed_mid=1.0, best_mid=0.9):
    return {"1.0": {"post_c_new_final": committed_new, "post_c_old_final": 1.0 - committed_new,
                    "post_c_old_midpoint": committed_mid},
            "0.9": {"post_c_new_final": best_new, "post_c_old_final": 0.04, "post_c_old_midpoint": best_mid},
            "0.8": {"post_c_new_final": best_new * 0.7, "post_c_old_final": 0.04, "post_c_old_midpoint": 0.6},
            "0.7": {"post_c_new_final": best_new * 0.5, "post_c_old_final": 0.04, "post_c_old_midpoint": 0.4}}


def _sm(bd):
    return X.build_summary(bd, [{}] * 24)


def test_verdict_apoyada():
    sm = _sm(_by_decay(committed_new=0.00, best_new=0.70))
    assert sm["status"] == "apoyada"
    assert sm["committed_stuck"] and sm["forgetting_adapts"] and sm["phase1_ok"]


def test_verdict_refutada_committed_adapts():
    sm = _sm(_by_decay(committed_new=0.65, best_new=0.70))
    assert sm["status"] == "refutada"
    assert not sm["committed_stuck"]


def test_verdict_mixta_partial():
    # committed atascado (0.0) pero el mejor olvido sólo llega a 0.553 (< umbral 0.60) -> adaptación parcial
    sm = _sm(_by_decay(committed_new=0.00, best_new=0.553))
    assert sm["status"] == "mixta"
    assert sm["committed_stuck"] and not sm["forgetting_adapts"]
