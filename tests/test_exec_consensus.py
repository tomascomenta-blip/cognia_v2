# -*- coding: utf-8 -*-
"""Consenso por ejecución (exec_consensus.py, ataque A del techo): el LLM
propone inputs, el sandbox decide por moda de comportamiento. Ejecución
REAL en subprocess; gen_fns no aplican (los inputs se pasan directos)."""
from cognia.agent.exec_consensus import (behavior_signature, consensus_pick,
                                         extract_input_calls)

ENTRY = "doble"
BUENO = "def doble(n):\n    return n * 2"
BUENO2 = "def doble(n):\n    return n + n"          # correcto, otra forma
MALO_A = "def doble(n):\n    return n + 1"          # bug 1
MALO_B = "def doble(n):\n    return n * 3"          # bug 2 (distinto)
INPUTS = ["doble(2)", "doble(-3)", "doble(0)", "doble(100)"]


def test_extract_input_calls_filtra():
    txt = ("doble(2)\nassert doble(3) == 6\n>>> doble(-1)\nprosa\n"
           "otra_funcion(5)\n`doble(0)`")
    calls = extract_input_calls(txt, ENTRY)
    assert "doble(2)" in calls
    assert "doble(-1)" in calls          # tolera prefijo >>>
    assert "doble(0)" in calls           # tolera fence
    assert all("assert" not in c for c in calls)
    assert "otra_funcion(5)" not in calls


def test_behavior_signature_distingue():
    sb = behavior_signature(BUENO, ENTRY, INPUTS)
    sb2 = behavior_signature(BUENO2, ENTRY, INPUTS)
    sa = behavior_signature(MALO_A, ENTRY, INPUTS)
    assert sb == sb2                     # dos correctos = misma firma
    assert sb != sa                      # correcto != buggy


def test_behavior_signature_none_si_no_hay_funcion():
    assert behavior_signature("print('nada')", ENTRY, INPUTS) is None


def test_behavior_signature_captura_excepcion():
    code = "def doble(n):\n    return n / 0"
    sig = behavior_signature(code, ENTRY, ["doble(2)"])
    assert sig == ("ERR:ZeroDivisionError",)


def test_consenso_elige_la_moda_correcta():
    # 2 correctos (misma firma) + 2 buggy (firmas distintas) -> gana el
    # cluster de los correctos por mayoria de comportamiento.
    codes = [MALO_A, BUENO, BUENO2, MALO_B]
    idx, info = consensus_pick(codes, INPUTS, ENTRY)
    assert idx in (1, 2)                  # uno de los correctos
    assert info["winner_size"] == 2
    assert info["n_clusters"] == 3        # {correcto, malo_a, malo_b}


def test_consenso_desempata_por_idx_menor():
    # dos correctos en el cluster ganador -> idx menor (reproducible)
    codes = [BUENO, BUENO2, MALO_A]
    idx, info = consensus_pick(codes, INPUTS, ENTRY)
    assert idx == 0


def test_consenso_sin_señal_devuelve_none():
    # todos distintos (sin mayoria) -> None (no inventa ganador)
    codes = [BUENO, MALO_A, MALO_B]
    idx, info = consensus_pick(codes, INPUTS, ENTRY)
    assert idx is None
    assert info["winner_size"] == 1


def test_consenso_sin_inputs_none():
    idx, info = consensus_pick([BUENO, MALO_A], [], ENTRY)
    assert idx is None


def test_consenso_solo_sobre_tied():
    # tied_idxs acota a un subconjunto (los que empataron en visibles)
    codes = [MALO_A, BUENO, BUENO2, MALO_B]
    idx, info = consensus_pick(codes, INPUTS, ENTRY, tied_idxs=[1, 2, 3])
    assert idx in (1, 2)
    assert info["n_considered"] == 3


def test_consensus_tiebreak_usa_gen_fn_y_elige():
    # gen_fn devuelve inputs; entre 3 empatados (2 correctos + 1 buggy)
    # gana el cluster correcto.
    def gen_fn(prompt, temperature=0.0, seed=None):
        assert "doble(" in prompt          # el prompt pide llamadas a doble
        return "doble(2)\ndoble(-3)\ndoble(0)\ndoble(100)"
    from cognia.agent.exec_consensus import consensus_tiebreak
    codes = [MALO_A, BUENO, BUENO2, MALO_B]
    idx, info = consensus_tiebreak(codes, [1, 2, 3], gen_fn, "haz doble", ENTRY)
    assert idx in (1, 2)


def test_consensus_tiebreak_sin_empate_none():
    from cognia.agent.exec_consensus import consensus_tiebreak
    called = {"n": 0}
    def gen_fn(prompt, temperature=0.0, seed=None):
        called["n"] += 1
        return ""
    idx, info = consensus_tiebreak([BUENO], [0], gen_fn, "t", ENTRY)
    assert idx is None
    assert called["n"] == 0                # ni llama al modelo si no hay empate


def test_consensus_tiebreak_gen_fn_falla_none():
    from cognia.agent.exec_consensus import consensus_tiebreak
    def gen_fn(prompt, temperature=0.0, seed=None):
        raise RuntimeError("server caido")
    idx, info = consensus_tiebreak([BUENO, MALO_A], [0, 1], gen_fn, "t", ENTRY)
    assert idx is None                     # fallback seguro
