"""
CYCLE 29 — regresion de la tarea VERIFICABLE de suma + oraculo + particion disjunta (exp016).

Falla SIN la implementacion correcta y pasa CON ella:
- test_oracle: el oraculo acepta correctos, rechaza incorrectos/malformados, corta en el primer '\\n'.
- test_mask: la mascara supervisa SOLO la respuesta (digitos de C + '\\n'); prompt y PAD -> -100.
- test_split_disjoint: train_pairs y test_pairs son DISJUNTOS (anti-leakage) y cubren el espacio.
- test_emitted_answer: normaliza la salida emitida (con/sin '\\n').

Correr: .\\venv312\\Scripts\\python.exe -m pytest cognia_x/tests/test_cycle29_addition.py -q
"""
import numpy as np

from cognia_x.experiments.exp016_verified_bootstrap import addition_task as T


def test_oracle():
    assert T.oracle_correct(T.make_prompt(47, 8), b"55\n") is True
    assert T.oracle_correct(T.make_prompt(47, 8), b"54\n") is False
    assert T.oracle_correct(T.make_prompt(2, 3), b"5\n") is True
    assert T.oracle_correct(T.make_prompt(2, 3), b"5") is False        # sin terminador
    assert T.oracle_correct(T.make_prompt(2, 3), b"x\n") is False      # no-digito
    assert T.oracle_correct(T.make_prompt(99, 99), b"198\n") is True
    assert T.oracle_correct(T.make_prompt(10, 5), b"15\nXYZ") is True  # corta en primer \n


def test_mask():
    seq, tgt = T.example_to_seq_target(T.make_prompt(47, 8), b"55\n")
    assert len(seq) == T.L and len(tgt) == T.L
    sup = [(i, tgt[i]) for i in range(T.L) if tgt[i] != -100]
    # solo 3 posiciones supervisadas, prediciendo los bytes de "55\n" = [53,53,10]
    assert [t for _, t in sup] == [53, 53, 10]
    assert len(sup) == 3


def test_emitted_answer():
    assert T.emitted_answer(b"55\n") == b"55\n"
    assert T.emitted_answer(b"55") == b"55\n"           # añade terminador si falta
    assert T.emitted_answer(b"5\nXX") == b"5\n"          # corta en primer \n (incluido)


def test_split_disjoint():
    train, test = T.build_split(0, 19, 0.30)
    strain, stest = set(train), set(test)
    assert strain.isdisjoint(stest)                      # anti-leakage
    assert len(strain) + len(stest) == 20 * 20           # cubren TODO el espacio (0..19)^2
    assert abs(len(test) - round(400 * 0.30)) <= 1       # ~30% al test
    # reproducible (mismo split_seed -> misma particion)
    train2, test2 = T.build_split(0, 19, 0.30)
    assert set(test2) == stest


def test_split_deterministic_across_calls():
    _, t1 = T.build_split(0, 12, 0.25)
    _, t2 = T.build_split(0, 12, 0.25)
    assert t1 == t2
