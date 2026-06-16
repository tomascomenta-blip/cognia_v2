"""
tests/test_recap_policy.py — FASE 6 (O2 taxonomia + O3 recap automatica).
should_recap es la decision pura; _persist_turn la dispara (extractiva, sin LLM).
"""
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ── Politica should_recap (O3) ───────────────────────────────────────────────

def test_should_recap_triggers_on_turn_interval():
    from cognia.memory.recap_policy import should_recap, RECAP_TURN_INTERVAL
    do, reason = should_recap(RECAP_TURN_INTERVAL)
    assert do is True and "turnos" in reason
    assert should_recap(RECAP_TURN_INTERVAL - 1)[0] is False
    assert should_recap(0)[0] is False   # 0 turnos no dispara


def test_should_recap_triggers_on_context_size():
    from cognia.memory.recap_policy import should_recap, RECAP_MAX_CONTEXT_CHARS
    do, reason = should_recap(3, context_chars=RECAP_MAX_CONTEXT_CHARS)
    assert do is True and "contexto" in reason


def test_should_recap_triggers_on_tasks_and_goals():
    from cognia.memory.recap_policy import (
        should_recap, RECAP_MAX_ACTIVE_TASKS, RECAP_MAX_GOALS)
    assert should_recap(3, n_active_tasks=RECAP_MAX_ACTIVE_TASKS)[0] is True
    assert should_recap(3, n_goals=RECAP_MAX_GOALS)[0] is True


def test_should_recap_no_trigger_when_idle():
    from cognia.memory.recap_policy import should_recap
    assert should_recap(3, context_chars=100, n_active_tasks=1, n_goals=1) == (False, "")


def test_memory_levels_has_five_canonical_levels():
    from cognia.memory.recap_policy import MEMORY_LEVELS
    assert set(MEMORY_LEVELS) == {"inmediata", "sesion", "trabajo", "proyectos", "historica"}


# ── Integracion CLI (O3 automatico) ──────────────────────────────────────────

def test_recap_command_registered():
    import cognia.cli as cli
    assert "/recap" in cli._CMD_DESCRIPTIONS
    assert "/recap" in cli._CMD_DETAILS


def test_persist_turn_autoupdates_recap_after_interval():
    import cognia.cli as cli
    from cognia.memory.recap_policy import RECAP_TURN_INTERVAL
    cli._history.clear()
    cli._session_recap = ""
    ai = types.SimpleNamespace()  # sin chat_history -> _persist_turn salta el DB log
    try:
        for i in range(RECAP_TURN_INTERVAL):
            cli._persist_turn(ai, f"pregunta {i} sobre temas variados de prueba para recap",
                              f"respuesta {i}")
        # tras N turnos de usuario, la recap extractiva quedo auto-poblada
        assert cli._session_recap
    finally:
        cli._history.clear()
        cli._session_recap = ""
