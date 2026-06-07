"""
tests/test_persona_manager.py
Tests for cognia.persona.persona_manager.PersonaManager
"""

import os
import sys
import tempfile
import pytest

# Ensure repo root is on path
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


@pytest.fixture
def pm(tmp_path):
    """PersonaManager instance backed by a temporary SQLite DB."""
    db_path = str(tmp_path / "test_personas.db")
    from cognia.persona.persona_manager import PersonaManager
    # Close any existing pool for this path (test isolation)
    try:
        from storage.db_pool import close_pool
        close_pool(db_path)
    except Exception:
        pass
    manager = PersonaManager(db_path=db_path)
    yield manager
    try:
        from storage.db_pool import close_pool
        close_pool(db_path)
    except Exception:
        pass


def test_set_persona_formal_returns_true(pm):
    assert pm.set_persona("local", "formal") is True


def test_get_persona_instruction_non_empty_after_set(pm):
    pm.set_persona("local", "formal")
    instr = pm.get_persona_instruction("local")
    assert instr != ""
    assert "formal" in instr.lower() or "profesional" in instr.lower()


def test_get_persona_instruction_unknown_user_returns_empty(pm):
    assert pm.get_persona_instruction("nonexistent_user_xyz") == ""


def test_set_persona_invalid_and_empty_custom_returns_false(pm):
    # persona not in PERSONAS, and no custom_instruction
    result = pm.set_persona("local", "nonexistent_persona", "")
    assert result is False


def test_set_persona_with_custom_instruction_and_empty_persona_returns_true(pm):
    # custom_instruction provided — persona blank is OK (defaults to "default")
    result = pm.set_persona("local", "", "Habla siempre en verso.")
    assert result is True


def test_custom_instruction_takes_precedence(pm):
    pm.set_persona("local", "formal", "Siempre responde en haiku.")
    instr = pm.get_persona_instruction("local")
    assert instr == "Siempre responde en haiku."


def test_reset_persona_clears_instruction(pm):
    pm.set_persona("local", "tecnico")
    pm.reset_persona("local")
    assert pm.get_persona_instruction("local") == ""


def test_list_personas_includes_expected(pm):
    personas = pm.list_personas()
    for expected in ("formal", "tecnico", "casual", "conciso", "detallado"):
        assert expected in personas


def test_list_personas_excludes_default(pm):
    assert "default" not in pm.list_personas()


def test_get_persona_returns_dict(pm):
    pm.set_persona("u1", "casual")
    data = pm.get_persona("u1")
    assert data["persona"] == "casual"
    assert "custom_instruction" in data


def test_get_persona_unknown_returns_default(pm):
    data = pm.get_persona("no_such_user")
    assert data["persona"] == "default"
    assert data["custom_instruction"] == ""


def test_upsert_overwrites_previous(pm):
    pm.set_persona("u2", "formal")
    pm.set_persona("u2", "casual")
    data = pm.get_persona("u2")
    assert data["persona"] == "casual"
