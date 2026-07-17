"""
tests/test_cli_semantic_debate.py
Tests for /buscar-memoria, /debate, /contexto-semantico CLI commands.
"""
import sys
import os
import io
from unittest import mock

# Ensure package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cognia.cli import (
    _slash_buscar_memoria,
    _slash_debate,
    _slash_contexto_semantico,
    COMMANDS,
)


def _capture(fn, *args):
    buf = io.StringIO()
    with mock.patch("sys.stdout", buf):
        fn(*args)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# 1. /buscar-memoria requires args
# ---------------------------------------------------------------------------
def test_buscar_memoria_requires_args():
    out = _capture(_slash_buscar_memoria, None, "")
    assert "Uso:" in out
    assert "/buscar-memoria" in out


# ---------------------------------------------------------------------------
# 2. /debate requires args
# ---------------------------------------------------------------------------
def _fake_ai(texto):
    """ai con orquestador fake: /debate genera por el backend REAL desde
    2026-07-16 (antes era una plantilla enlatada)."""
    import types

    class _Orch:
        def infer(self, prompt, max_tokens=None, temperature=None):
            return types.SimpleNamespace(text=texto, mode="local")

    return types.SimpleNamespace(_orchestrator=_Orch())


def test_debate_requires_args():
    out = _capture(_slash_debate, None, "")
    assert "Uso:" in out
    assert "/debate" in out


# ---------------------------------------------------------------------------
# 3. /debate prints pro/con sections (generadas por el modelo)
# ---------------------------------------------------------------------------
def test_debate_prints_pro_con_sections():
    ai = _fake_ai("A FAVOR:\n+ punto real\nEN CONTRA:\n- contra real\n"
                  "CONCLUSION: depende del contexto")
    out = _capture(_slash_debate, ai, "inteligencia artificial")
    assert "A FAVOR:" in out
    assert "EN CONTRA:" in out
    assert "CONCLUSION:" in out
    # At least one pro and one con line
    assert "+" in out
    assert "-" in out


# ---------------------------------------------------------------------------
# 4. /contexto-semantico requires args
# ---------------------------------------------------------------------------
def test_contexto_semantico_requires_args():
    out = _capture(_slash_contexto_semantico, None, "")
    assert "Uso:" in out
    assert "/contexto-semantico" in out


# ---------------------------------------------------------------------------
# 5. /buscar-memoria handles connection error gracefully
# ---------------------------------------------------------------------------
def test_buscar_memoria_local_fallback_when_api_down(tmp_path):
    """Sin Electron (:8765 caido), /buscar-memoria cae a SemanticMemorySearch local
    sobre ai.db (antes imprimia 'no disponible'; FASE 2a)."""
    import sqlite3
    import types
    db = str(tmp_path / "cm.db")
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE chat_history (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "timestamp TEXT, role TEXT, content TEXT, session_id TEXT)"
    )
    con.executemany(
        "INSERT INTO chat_history (timestamp, role, content, session_id) VALUES (?,?,?,?)",
        [("2026-06-16T10:00:00", "user", "hablamos de python y asyncio", "s1"),
         ("2026-06-16T10:01:00", "assistant", "asyncio es para concurrencia en python", "s1")],
    )
    con.commit()
    con.close()
    ai = types.SimpleNamespace(db=db)
    with mock.patch("requests.get", side_effect=Exception("connection refused")):
        out = _capture(_slash_buscar_memoria, ai, "python asyncio")
    assert "no disponible" not in out.lower()   # ya no es el viejo mensaje de error
    assert "Resultados semanticos" in out or "python" in out.lower()
    from storage.db_pool import close_pool
    close_pool(db)


# ---------------------------------------------------------------------------
# Bonus: commands registered in COMMANDS dict
# ---------------------------------------------------------------------------
def test_commands_registered():
    assert "/buscar-memoria" in COMMANDS
    assert "/debate" in COMMANDS
    assert "/contexto-semantico" in COMMANDS
