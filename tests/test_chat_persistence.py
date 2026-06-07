"""
Regression tests for cross-session conversation persistence.

Gap (fixed this session):
    The interactive REPL kept conversation turns only in the in-memory _history
    list. The streaming and agent paths never wrote to chat_history, and the REPL
    started with _history = [], so reopening the CLI lost the whole thread.

Fix:
    - ChatHistory.get_recent_turns(n): full-content user/assistant turns, oldest
      first (for seeding _history at startup).
    - cli._persist_turn(ai, user, assistant): appends to _history AND logs both
      rows to chat_history (streaming + agent paths).
    - repl() seeds _history from chat_history.get_recent_turns() at startup.

These tests pin the round trip: a turn persisted in one "session" is restored,
full-content and in order, by the next.
"""

import types

import pytest

from cognia.database import init_db
from cognia.memory.chat import ChatHistory


@pytest.fixture
def chat_db(tmp_path):
    db = tmp_path / "chat.db"
    init_db(str(db))
    return str(db)


def test_get_recent_turns_roundtrip_full_content_in_order(chat_db):
    ch = ChatHistory(chat_db)
    long_answer = "B" * 300  # longer than get_recent()'s 80-char truncation
    ch.log(role="user", content="hola, me llamo Tomas")
    ch.log(role="assistant", content=long_answer)
    ch.log(role="user", content="segunda pregunta")
    ch.log(role="assistant", content="segunda respuesta")

    turns = ch.get_recent_turns(n=20)
    assert [t["role"] for t in turns] == ["user", "assistant", "user", "assistant"]
    assert turns[0]["content"] == "hola, me llamo Tomas"
    # Full content, NOT truncated.
    assert turns[1]["content"] == long_answer
    assert len(turns[1]["content"]) == 300


def test_get_recent_turns_respects_limit_keeps_latest(chat_db):
    ch = ChatHistory(chat_db)
    for i in range(10):
        ch.log(role="user", content=f"u{i}")
        ch.log(role="assistant", content=f"a{i}")
    turns = ch.get_recent_turns(n=4)
    assert len(turns) == 4
    # The latest 4 messages, still chronological (oldest-first).
    assert [t["content"] for t in turns] == ["u8", "a8", "u9", "a9"]


def test_get_recent_turns_excludes_non_dialogue_roles(chat_db):
    ch = ChatHistory(chat_db)
    ch.log(role="user", content="pregunta")
    ch.log(role="assistant", content="respuesta")
    ch.log(role="system", content="ruido interno que no es dialogo")
    turns = ch.get_recent_turns(n=20)
    assert [t["role"] for t in turns] == ["user", "assistant"]


def test_persist_turn_writes_db_and_seeds_next_session(chat_db):
    """End-to-end: _persist_turn in 'session 1' -> get_recent_turns restores it."""
    from cognia import cli

    saved = list(cli._history)
    cli._history.clear()
    try:
        ai = types.SimpleNamespace(chat_history=ChatHistory(chat_db))

        # --- Session 1: a streaming turn gets persisted ---
        cli._persist_turn(ai, "crea un html que diga hola", "<h1>hola</h1>")
        # In-memory buffer updated...
        assert cli._history[-2:] == [
            {"role": "user", "content": "crea un html que diga hola"},
            {"role": "assistant", "content": "<h1>hola</h1>"},
        ]

        # --- Session 2: fresh process -> seed from the DB (what repl() does) ---
        restored = ai.chat_history.get_recent_turns(cli._HISTORY_SEED_N)
        assert {"role": "user", "content": "crea un html que diga hola"} in restored
        assert {"role": "assistant", "content": "<h1>hola</h1>"} in restored
        # Seeding _history makes the very next prompt thread-aware.
        assert restored[-1]["content"] == "<h1>hola</h1>"
    finally:
        cli._history[:] = saved
