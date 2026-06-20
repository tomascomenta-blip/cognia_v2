"""
CYCLE 31 — regresion del VERIFICADOR REAL (sandbox de ejecucion) de exp018.

- test_interpret: el interprete (sandbox) computa a+b / a*b, marca el echo como degenerado (sin operador),
  y rechaza chars fuera del allowlist o fuera de la gramatica (NUNCA usa eval()).
- test_verify_weak_vs_strong: el verificador DEBIL acepta el echo del target (reward-hack), el FUERTE lo
  bloquea (exige operador). Ambos rechazan valores incorrectos.
- test_real_expression_seed: la regla canonica '1+(n-1)' evalua al target (sembrado aprendible).
- test_no_arbitrary_eval: chars peligrosos / no-allowlist se rechazan (no se ejecuta codigo arbitrario).

Correr: .\\venv312\\Scripts\\python.exe -m pytest cognia_x/tests/test_cycle31_sandbox.py -q
"""
import numpy as np

from cognia_x.experiments.exp018_real_verifier import expression_task as E


def test_interpret():
    assert E.interpret(b"3*4") == (12, True, True)
    assert E.interpret(b"7+5") == (12, True, True)
    assert E.interpret(b"12") == (12, False, True)        # echo = degenerado (sin operador)
    assert E.interpret(b"1+2+3") == (None, False, False)  # fuera de gramatica
    assert E.interpret(b"") == (None, False, False)


def test_verify_weak_vs_strong():
    p = E.make_prompt(12)
    assert E.verify(p, b"3*4\n", strong=True) is True and E.verify(p, b"3*4\n", strong=False) is True
    # echo del target: el DEBIL lo acepta (hackeable), el FUERTE lo bloquea
    assert E.verify(p, b"12\n", strong=False) is True
    assert E.verify(p, b"12\n", strong=True) is False
    # valor incorrecto: ambos rechazan
    assert E.verify(p, b"3*3\n", strong=True) is False and E.verify(p, b"3*3\n", strong=False) is False


def test_real_expression_seed():
    rng = np.random.default_rng(0)
    for n in (4, 7, 12, 18, 33):
        e = E.real_expression(rng, n)
        val, has_op, ok = E.interpret(e)
        assert ok and has_op and val == n                 # regla canonica computa el target con operador


def test_no_arbitrary_eval():
    # cualquier char fuera de [0-9+*] -> no well-formed (no se ejecuta nada)
    for bad in (b"__import__", b"9-1", b"2/1", b"a+b", b"3 4", b"3**4"):
        val, has_op, ok = E.interpret(bad)
        assert ok is False and val is None


def test_echo_expression():
    # el echo (CYCLE 32): el target literal, degenerado (evalúa a n SIN operador = el atajo del reward-hack)
    for n in (5, 12, 99, 200):
        e = E.echo_expression(n)
        val, has_op, ok = E.interpret(e)
        assert ok and (not has_op) and val == n          # válido, sin operador, evalúa al target
        p = E.make_prompt(n)
        assert E.verify(p, e + b"\n", strong=False) is True   # weak ACEPTA el echo (hackeable)
        assert E.verify(p, e + b"\n", strong=True) is False   # strong lo RECHAZA
