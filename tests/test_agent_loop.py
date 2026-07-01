"""
Tests for dynamic step budgeting (cognia/agent/loop.py).

Pins that the budget scales with the model's complexity rating, clamps to the
hard cap, and falls back to a heuristic when the model is unavailable.
"""

import re
import types

from cognia.agent.loop import (
    estimate_step_budget, wants_more_steps, AGENT_HARD_CAP, _RATING_TO_BUDGET,
    first_action_block,
)

# Mismo regex que usa el loop en cli.py para parsear la accion.
_PARSE = re.compile(r"ACCI[OÓ]N:\s*(\w+)\s*(.*)", re.IGNORECASE | re.DOTALL)


def _orch(text):
    """A fake orchestrator whose infer() returns a fixed text."""
    return types.SimpleNamespace(
        infer=lambda prompt: types.SimpleNamespace(text=text)
    )


def test_budget_scales_with_rating():
    assert estimate_step_budget("tarea", _orch("1")) == _RATING_TO_BUDGET[1]
    assert estimate_step_budget("tarea", _orch("5")) == _RATING_TO_BUDGET[5]


def test_budget_never_exceeds_hard_cap():
    assert estimate_step_budget("x", _orch("5")) <= AGENT_HARD_CAP


def test_budget_falls_back_to_heuristic_when_model_fails():
    def boom(prompt):
        raise RuntimeError("no model")
    orch = types.SimpleNamespace(infer=boom)
    # Trivial-looking task -> small heuristic budget.
    assert estimate_step_budget("hola", orch) == 2
    # Long task -> larger heuristic.
    assert estimate_step_budget("x" * 250, orch) == 8


def test_budget_is_at_least_one():
    assert estimate_step_budget("", _orch("garbage no number")) >= 1


def test_wants_more_steps_parses_number():
    assert wants_more_steps("t", "progreso", _orch("3")) == 3
    assert wants_more_steps("t", "progreso", _orch("0")) == 0


def test_wants_more_steps_zero_when_model_fails():
    def boom(prompt):
        raise RuntimeError("no model")
    assert wants_more_steps("t", "p", types.SimpleNamespace(infer=boom)) == 0


# ── first_action_block: recorte del rambling multi-ACCION ───────────────

def test_first_action_block_single_action_unchanged():
    raw = "ACCION: calcular 2 + 2"
    assert first_action_block(raw) == raw


def test_first_action_block_keeps_only_first_of_many():
    # El 3B rambléa varias ACCION en una respuesta; solo la primera es real.
    raw = ("ACCION: escribir_archivo x.txt | hola\n"
           "ACCION: anotar k | v\n"
           "ACCION: responder listo")
    assert first_action_block(raw) == "ACCION: escribir_archivo x.txt | hola"


def test_first_action_block_prevents_corrupt_args_regression():
    # Bug de produccion: el parser DOTALL metia las ACCION siguientes DENTRO de
    # los args de escribir_archivo, escribiendo un archivo con el rambling.
    raw = ("ACCION: escribir_archivo x.txt | hola\n"
           "ACCION: responder ok")
    m = _PARSE.search(first_action_block(raw))
    assert m.group(1).lower() == "escribir_archivo"
    assert m.group(2).strip() == "x.txt | hola"        # SIN la ACCION siguiente
    assert "responder" not in m.group(2)


def test_first_action_block_preserves_multiline_content():
    # Contenido legitimo multi-linea (sin lineas que arranquen con ACCION:) se
    # conserva entero -- escribir_archivo con codigo de varias lineas.
    raw = ("ACCION: escribir_archivo hola.py | def f():\n"
           "    return 1\n"
           "    # fin")
    out = first_action_block(raw)
    assert out == raw
    m = _PARSE.search(out)
    assert m.group(1).lower() == "escribir_archivo"
    assert "def f():" in m.group(2) and "return 1" in m.group(2)


def test_first_action_block_no_action_returned_unchanged():
    raw = "no hay ninguna accion aca, solo texto"
    assert first_action_block(raw) == raw


def test_first_action_block_ignores_preamble_before_action():
    raw = "Voy a calcular:\nACCION: calcular 5 * 5\nACCION: responder 25"
    assert first_action_block(raw) == "ACCION: calcular 5 * 5"
