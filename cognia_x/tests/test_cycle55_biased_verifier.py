r"""
CYCLE 55 / H-V4-2h — regresión: verificador con SESGO SISTEMÁTICO (off-by-one) + guardia como defensa.

Protege: (a) offbyone_expression computa target-1 con operador; (b) buggy_accept acepta target y target-1 (con
operador) y rechaza target-2 / sin-operador; (c) las 3 ramas del veredicto (APOYADA deriva / MIXTA pin / REFUTADA
sin daño). El (c) sin modelo -> instantáneo.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle55_biased_verifier.py -q
"""
from types import SimpleNamespace

from cognia_x.experiments.exp018_real_verifier import expression_task as E
from cognia_x.experiments.exp041_biased_verifier import run as X


def test_offbyone_expression_is_target_minus_one():
    val, has_op, ok = E.interpret(X.offbyone_expression(12))      # 1+10 = 11 = 12-1
    assert ok and has_op and val == 11


def test_buggy_accept_takes_target_and_offbyone():
    # (prompt, emitted_expr, weak_ok, strong_ok) — buggy acepta valor target O target-1 con operador
    pool = [
        (b"12=", b"3*4", True, True),     # 12 = target -> aceptar
        (b"12=", b"1+10", True, False),   # 11 = target-1 -> aceptar (el BUG)
        (b"12=", b"1+8", False, False),   # 9 = target-3 -> rechazar
        (b"12=", b"12", True, False),     # echo, sin operador -> rechazar
    ]
    acc = X.buggy_accept(pool)
    assert (b"12=", b"3*4") in acc and (b"12=", b"1+10") in acc
    assert (b"12=", b"1+8") not in acc and (b"12=", b"12") not in acc
    assert len(acc) == 2


def _seeds(real_p, obo_p, real_g, obo_g):
    def arm(real, obo):
        return [{"round": r, "real": a, "offbyone": b} for r, (a, b) in enumerate(zip(real, obo))]
    return [{"plain": arm(real_p, obo_p), "guarded": arm(real_g, obo_g)} for _ in range(3)]


def test_verdict_apoyada_drift():
    s = _seeds([0.40, 0.35, 0.30, 0.28], [0.18, 0.30, 0.40, 0.45],
               [0.40, 0.60, 0.73, 0.75], [0.18, 0.10, 0.08, 0.08])
    v, st = X.verdict(s, SimpleNamespace(rounds=3), m=90)
    assert v == "APOYADA" and st["plain_drifts"] and st["guard_defends"]


def test_verdict_mixta_pin():
    s = _seeds([0.40, 0.41, 0.42, 0.45], [0.18, 0.25, 0.28, 0.25],
               [0.40, 0.60, 0.73, 0.73], [0.18, 0.10, 0.08, 0.10])
    v, st = X.verdict(s, SimpleNamespace(rounds=3), m=90)
    assert v == "MIXTA" and st["plain_pinned"] and st["plain_harmed"] and st["guard_defends"]
    assert not st["plain_drifts"]


def test_verdict_refutada_no_damage():
    s = _seeds([0.40, 0.60, 0.75, 0.80], [0.18, 0.10, 0.06, 0.05],
               [0.40, 0.62, 0.76, 0.81], [0.18, 0.09, 0.05, 0.05])
    v, st = X.verdict(s, SimpleNamespace(rounds=3), m=90)
    assert v == "REFUTADA" and not st["plain_harmed"]
