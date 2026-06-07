"""
Tests for the self-tuning system prompt (cognia/agent/adaptive_prompt.py).

Pins that traits are learned from user messages, persist across "sessions"
(fresh UserProfile on the same DB), and shape the system prompt -- while a
brand-new user still gets the plain canonical prompt.
"""

import types

import pytest

from cognia.database import init_db
from cognia.memory.chat import UserProfile, ChatHistory
from cognia.agent.adaptive_prompt import (
    learn_user_traits, build_adaptive_system_prompt,
)
from shattering.model_constants import COGNIA_SYSTEM_PROMPT


@pytest.fixture
def ai(tmp_path):
    db = str(tmp_path / "u.db")
    init_db(db)
    return types.SimpleNamespace(
        user_profile=UserProfile(db),
        chat_history=ChatHistory(db),
        _db=db,
    )


def test_unknown_user_gets_plain_prompt(ai):
    assert build_adaptive_system_prompt(ai) == COGNIA_SYSTEM_PROMPT


def test_learns_name(ai):
    learn_user_traits(ai, "hola, me llamo Tomas")
    prompt = build_adaptive_system_prompt(ai)
    assert "Tomas" in prompt
    assert prompt != COGNIA_SYSTEM_PROMPT


def test_learns_verbosity_preference(ai):
    learn_user_traits(ai, "che, se mas breve por favor")
    assert "breves" in build_adaptive_system_prompt(ai).lower()


def test_learns_english_preference(ai):
    learn_user_traits(ai, "what is the weather and how are you my friend")
    assert "ingles" in build_adaptive_system_prompt(ai).lower()


def test_traits_persist_across_sessions(ai):
    # Session 1 learns the name.
    learn_user_traits(ai, "mi nombre es Lucia")
    # Session 2: brand-new objects on the same DB still see it.
    ai2 = types.SimpleNamespace(
        user_profile=UserProfile(ai._db),
        chat_history=ChatHistory(ai._db),
    )
    assert "Lucia" in build_adaptive_system_prompt(ai2)


def test_canonical_identity_is_preserved(ai):
    # The adaptive preamble augments, never replaces, the creator identity.
    learn_user_traits(ai, "me llamo Tomas")
    assert "Tomas Montes" in build_adaptive_system_prompt(ai)


def test_learning_never_raises_on_bad_input(ai):
    learn_user_traits(ai, "")
    learn_user_traits(ai, "x")
    learn_user_traits(types.SimpleNamespace(), "hola")  # no user_profile attr
