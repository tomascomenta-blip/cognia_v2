"""
tests/test_conversation_templates.py
=====================================
Tests for ConversationTemplateManager and BUILTIN_TEMPLATES.
"""

import pytest
import tempfile
import os

from cognia.templates.conversation_templates import (
    ConversationTemplateManager,
    BUILTIN_TEMPLATES,
)


@pytest.fixture
def mgr(tmp_path):
    """Manager backed by a temp SQLite DB."""
    db = str(tmp_path / "test_templates.db")
    return ConversationTemplateManager(db_path=db)


@pytest.fixture
def mgr_no_db():
    """Manager with no DB (builtin-only access)."""
    return ConversationTemplateManager(db_path=None)


# ── Builtin template tests ────────────────────────────────────────────


def test_list_templates_returns_at_least_five(mgr):
    templates = mgr.list_templates()
    assert len(templates) >= 5


def test_list_templates_builtin_ids_present(mgr):
    ids = {t["id"] for t in mgr.list_templates()}
    for builtin_id in BUILTIN_TEMPLATES:
        assert builtin_id in ids


def test_get_template_code_review_has_guide_questions(mgr):
    tpl = mgr.get_template("code_review")
    assert tpl is not None
    assert "guide_questions" in tpl
    assert isinstance(tpl["guide_questions"], list)
    assert len(tpl["guide_questions"]) > 0


def test_get_template_nonexistent_returns_none(mgr):
    result = mgr.get_template("nonexistent_template_xyz")
    assert result is None


def test_list_templates_filter_by_tag(mgr):
    filtered = mgr.list_templates(tag="codigo")
    assert len(filtered) >= 1
    for t in filtered:
        assert "codigo" in t["tags"]


def test_list_templates_filter_unknown_tag_returns_empty(mgr):
    filtered = mgr.list_templates(tag="tag_that_does_not_exist_xyz")
    assert filtered == []


# ── Custom template tests ─────────────────────────────────────────────


_VALID_CUSTOM = {
    "name": "My Custom Template",
    "description": "A custom test template",
    "initial_prompt": "Let's start this custom session.",
    "guide_questions": ["What is the goal?", "What are the constraints?"],
    "tags": ["test", "custom"],
    "estimated_turns": 4,
}


def test_create_custom_returns_dict_with_id(mgr):
    result = mgr.create_custom(_VALID_CUSTOM.copy())
    assert isinstance(result, dict)
    assert "id" in result
    assert result["id"]  # non-empty


def test_create_custom_persisted_in_list(mgr):
    mgr.create_custom(_VALID_CUSTOM.copy())
    templates = mgr.list_templates()
    names = [t["name"] for t in templates]
    assert "My Custom Template" in names


def test_create_custom_missing_required_fields_raises_value_error(mgr):
    with pytest.raises(ValueError):
        mgr.create_custom({"name": "Incomplete"})  # missing description, initial_prompt, guide_questions


def test_create_custom_missing_guide_questions_raises_value_error(mgr):
    with pytest.raises(ValueError):
        mgr.create_custom({
            "name": "X",
            "description": "Y",
            "initial_prompt": "Z",
            # guide_questions missing
        })


def test_create_custom_guide_questions_not_list_raises_value_error(mgr):
    with pytest.raises(ValueError):
        mgr.create_custom({
            "name": "X",
            "description": "Y",
            "initial_prompt": "Z",
            "guide_questions": "not a list",
        })


# ── Delete custom tests ───────────────────────────────────────────────


def test_delete_custom_builtin_returns_false(mgr):
    result = mgr.delete_custom("code_review")
    assert result is False


def test_delete_custom_nonexistent_returns_false(mgr):
    result = mgr.delete_custom("does_not_exist")
    assert result is False


def test_delete_custom_removes_template(mgr):
    created = mgr.create_custom(_VALID_CUSTOM.copy())
    tid = created["id"]
    deleted = mgr.delete_custom(tid)
    assert deleted is True
    assert mgr.get_template(tid) is None


# ── start_session tests ───────────────────────────────────────────────


def test_start_session_returns_initial_prompt(mgr):
    result = mgr.start_session("code_review")
    assert "initial_prompt" in result
    assert result["initial_prompt"]


def test_start_session_returns_guide_questions(mgr):
    result = mgr.start_session("code_review")
    assert "guide_questions" in result
    assert isinstance(result["guide_questions"], list)


def test_start_session_returns_session_id(mgr):
    result = mgr.start_session("brainstorming")
    assert "session_id" in result
    assert result["session_id"]


def test_start_session_uses_provided_session_id(mgr):
    result = mgr.start_session("planning", session_id="my_session_abc")
    assert result["session_id"] == "my_session_abc"


def test_start_session_nonexistent_raises_key_error(mgr):
    with pytest.raises(KeyError):
        mgr.start_session("nonexistent_xyz")


def test_start_session_returns_estimated_turns(mgr):
    result = mgr.start_session("debugging")
    assert "estimated_turns" in result
    assert isinstance(result["estimated_turns"], int)
