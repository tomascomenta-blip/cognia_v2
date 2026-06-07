"""
Tests for /resume: per-directory / per-id session resume.

Covers the ChatHistory session API (set_session, list_sessions,
latest_session_for_dir, resolve_session_prefix, get_session_turns) and the
cli._slash_resume command end to end -- resuming by directory, by id prefix, and
the list mode -- including the schema migration that adds session_id + cwd.
"""

import io
import contextlib
import types

import pytest

from cognia.database import init_db
from cognia.memory.chat import ChatHistory


@pytest.fixture
def ch(tmp_path):
    db = tmp_path / "sessions.db"
    init_db(str(db))
    return ChatHistory(str(db))


def _seed_two_sessions(ch):
    """Session A in /proj/alpha, then session B in /proj/beta."""
    ch.set_session("aaaa1111aaaa", "/proj/alpha")
    ch.log(role="user", content="en alpha: arregla el bug X")
    ch.log(role="assistant", content="bug X resuelto en alpha")
    ch.set_session("bbbb2222bbbb", "/proj/beta")
    ch.log(role="user", content="en beta: escribe el README")
    ch.log(role="assistant", content="README escrito en beta")


def test_log_tags_rows_with_session_and_cwd(ch):
    _seed_two_sessions(ch)
    sessions = ch.list_sessions(limit=10)
    ids = {s["session_id"] for s in sessions}
    assert ids == {"aaaa1111aaaa", "bbbb2222bbbb"}
    by_id = {s["session_id"]: s for s in sessions}
    assert by_id["aaaa1111aaaa"]["cwd"] == "/proj/alpha"
    assert by_id["aaaa1111aaaa"]["count"] == 2


def test_list_sessions_newest_first(ch):
    _seed_two_sessions(ch)
    sessions = ch.list_sessions(limit=10)
    # Session B was logged last -> appears first.
    assert sessions[0]["session_id"] == "bbbb2222bbbb"


def test_list_sessions_filtered_by_dir(ch):
    _seed_two_sessions(ch)
    only_alpha = ch.list_sessions(cwd="/proj/alpha")
    assert [s["session_id"] for s in only_alpha] == ["aaaa1111aaaa"]


def test_latest_session_for_dir(ch):
    _seed_two_sessions(ch)
    # A second, newer session in alpha must win.
    ch.set_session("cccc3333cccc", "/proj/alpha")
    ch.log(role="user", content="alpha de nuevo")
    ch.log(role="assistant", content="ok")
    assert ch.latest_session_for_dir("/proj/alpha") == "cccc3333cccc"
    assert ch.latest_session_for_dir("/proj/beta") == "bbbb2222bbbb"
    assert ch.latest_session_for_dir("/nope") is None


def test_resolve_session_prefix(ch):
    _seed_two_sessions(ch)
    assert ch.resolve_session_prefix("aaaa1111") == "aaaa1111aaaa"
    assert ch.resolve_session_prefix("zzzz") is None


def test_get_session_turns_full_content_in_order(ch):
    _seed_two_sessions(ch)
    turns = ch.get_session_turns("aaaa1111aaaa")
    assert turns == [
        {"role": "user", "content": "en alpha: arregla el bug X"},
        {"role": "assistant", "content": "bug X resuelto en alpha"},
    ]


def test_cwd_match_is_case_insensitive(ch):
    ch.set_session("dddd4444dddd", "C:/Users/Tomas/Proj")
    ch.log(role="user", content="hola")
    ch.log(role="assistant", content="hola!")
    # Windows: same path, different case must still match.
    assert ch.latest_session_for_dir("c:/users/tomas/proj") == "dddd4444dddd"


def test_slash_resume_by_directory_loads_history(ch, tmp_path):
    """End-to-end: /resume <dir> loads that directory's last session into _history.

    Uses REAL directories so the abspath/normpath the command applies to the arg
    round-trips to the same string stored as cwd (the startup path is normalized
    the same way).
    """
    import os
    from cognia import cli

    beta_dir = str(tmp_path / "beta")
    os.makedirs(beta_dir, exist_ok=True)
    beta_norm = os.path.normpath(os.path.abspath(beta_dir))

    ch.set_session("bbbb2222bbbb", beta_norm)
    ch.log(role="user", content="en beta: escribe el README")
    ch.log(role="assistant", content="README escrito en beta")

    saved_hist = list(cli._history)
    saved_sid, saved_cwd = cli._SESSION_ID, cli._SESSION_CWD
    cli._history.clear()
    try:
        ai = types.SimpleNamespace(chat_history=ch)
        cli._SESSION_ID = "current-session"
        cli._SESSION_CWD = str(tmp_path / "elsewhere")

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli._slash_resume(beta_dir, ai)

        assert cli._history == [
            {"role": "user", "content": "en beta: escribe el README"},
            {"role": "assistant", "content": "README escrito en beta"},
        ]
    finally:
        cli._history[:] = saved_hist
        cli._SESSION_ID, cli._SESSION_CWD = saved_sid, saved_cwd


def test_slash_resume_by_id_prefix(ch):
    from cognia import cli

    _seed_two_sessions(ch)
    saved_hist = list(cli._history)
    saved_sid, saved_cwd = cli._SESSION_ID, cli._SESSION_CWD
    cli._history.clear()
    try:
        ai = types.SimpleNamespace(chat_history=ch)
        cli._SESSION_ID = "current-session"
        cli._SESSION_CWD = "/proj/somewhere-else"

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli._slash_resume("aaaa1111", ai)  # alpha's id prefix

        assert cli._history[0]["content"] == "en alpha: arregla el bug X"
    finally:
        cli._history[:] = saved_hist
        cli._SESSION_ID, cli._SESSION_CWD = saved_sid, saved_cwd
