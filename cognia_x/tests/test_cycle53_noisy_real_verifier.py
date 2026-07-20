r"""
CYCLE 53 / H-V4-2f — regresión: dosis-respuesta al RUIDO del VERIFICADOR REAL (plano vs guardia).

Protege: (a) noisy_accept_real implementa el falso-positivo ε (ε=0 -> solo strong-correctas; ε=1 -> todas);
(b) la lógica de veredicto (decae con ε + ε* + guard_raises) clasifica bien. Sin modelo -> instantáneo.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle53_noisy_real_verifier.py -q
"""
import numpy as np

from cognia_x.experiments.exp039_noisy_real_verifier import run as X


def test_noisy_accept_eps0_only_strong():
    pool = [(b"12=", b"3*4", True, True), (b"6=", b"6", True, False), (b"9=", b"xx", False, False)]
    acc = X.noisy_accept_real(pool, 0.0, np.random.default_rng(0))
    assert acc == [(b"12=", b"3*4")]              # ε=0: solo la STRONG-correcta


def test_noisy_accept_eps1_accepts_all():
    pool = [(b"12=", b"3*4", True, True), (b"6=", b"6", True, False), (b"9=", b"xx", False, False)]
    acc = X.noisy_accept_real(pool, 1.0, np.random.default_rng(0))
    assert len(acc) == 3                          # ε=1: acepta todas (FP siempre)


def _seed(base, guarded_finals, plain_finals):
    """hist[arm][str(eps)] = [base, final, final] (2 rondas en la meseta)."""
    def arm(finals):
        return {str(e): [base, f, f] for e, f in zip(X.EPS_SWEEP, finals)}
    return {"base_acc": base, "hist": {"guarded": arm(guarded_finals), "plain": arm(plain_finals)}}


def test_verdict_apoyada_decays_and_guard_raises():
    # guarded decae suave (sobrevive a todos los ε); plano cae bajo cero pasado ε=0.15
    per_seed = [_seed(0.30, [0.80, 0.75, 0.60, 0.45], [0.80, 0.60, 0.28, 0.20]) for _ in range(3)]
    sm = X.build_summary(per_seed, m=90)
    assert sm["status"] == "apoyada"
    assert sm["decays"] and sm["clean_improves"]
    assert sm["eps_star"]["guarded"] == 0.50      # guarded sobrevive a todo el barrido
    assert sm["eps_star"]["plain"] == 0.15        # plano sólo hasta 0.15
    assert sm["guard_raises_eps_star"] is True


def test_verdict_refutada_flat():
    # net no decae con ε (plano en ε) -> REFUTADA (el ruido no importa)
    per_seed = [_seed(0.30, [0.80, 0.80, 0.80, 0.80], [0.80, 0.80, 0.80, 0.80]) for _ in range(3)]
    sm = X.build_summary(per_seed, m=90)
    assert sm["status"] == "refutada"
    assert not sm["decays"]
