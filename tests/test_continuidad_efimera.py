# -*- coding: utf-8 -*-
"""Continuidad POR DIRECTORIO + modo EFIMERO (incidente MrBeast, 2026-08-25).

Lo que paso (transcript real del dueno, 11:52): la continuidad del REPL
restauraba los ultimos 20 mensajes de chat_history SIN mirar de que directorio
eran, y las pruebas e2e de la manana (REPL por stdin en worktrees/Temp,
preguntando por MrBeast) aparecieron en el chat del dueno en Desktop ("Hace
rato que no te veo, MrBeast"). Ademas, esas pruebas escribieron adapt_* y
episodios en SU memoria.

Los dos anticuerpos que este archivo protege:
  1. get_recent_turns(cwd=...) filtra por directorio y el REPL lo usa con
     _SESSION_CWD: sesiones de otro cwd NO se heredan (ni filas viejas sin cwd).
  2. COGNIA_EFIMERO=1 apaga TODA escritura (chat_history, user_profile) y la
     restauracion de continuidad, y el arranque lo dice.
Mas el ENTORNO en el prompt del chat: el chat recomendaba comandos Linux en
Windows y AFIRMABA haberlos ejecutado; ahora su prompt dice SO/shell/cwd y la
regla de que el chat no ejecuta nada (el prompt del AGENTE no cambia: A/B
2026-07-23, texto extra lo degrada de 10/10 a 3/5).
"""

import io
import os
import platform
import re
import subprocess
import sys
from pathlib import Path

import pytest

from storage.db_pool import db_connect_pooled
from cognia.memory.chat import ChatHistory, UserProfile, sesion_efimera

RAIZ = Path(__file__).resolve().parents[1]
FUENTE_CLI = io.open(RAIZ / "cognia" / "cli.py", encoding="utf-8").read()


@pytest.fixture(autouse=True)
def _sin_efimero_heredado(monkeypatch):
    """Si la suite corre bajo COGNIA_EFIMERO=1 (p.ej. desde un e2e), los tests
    del brazo 'sin efimero' escribirian 0 filas y fallarian por el motivo
    equivocado. Cada test arranca con la env limpia y activa el modo a mano."""
    monkeypatch.delenv("COGNIA_EFIMERO", raising=False)


def _db_con_esquema(tmp_path) -> str:
    """Un chat.db temporal con el MISMO esquema que cognia/database.py:215
    (columnas incluidas session_id y cwd). Via db_pool, como manda el repo."""
    db = str(tmp_path / "chat.db")
    conn = db_connect_pooled(db)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chat_history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   TEXT NOT NULL,
            role        TEXT NOT NULL,
            content     TEXT NOT NULL,
            label_used  TEXT,
            confidence  REAL DEFAULT 0.0,
            feedback    INTEGER DEFAULT 0,
            response_id TEXT,
            session_id  TEXT,
            cwd         TEXT
        )""")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_profile (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            key         TEXT NOT NULL UNIQUE,
            value       TEXT,
            updated_at  TEXT
        )""")
    conn.commit()
    conn.close()
    return db


def _cuenta(db: str) -> int:
    conn = db_connect_pooled(db)
    n = conn.execute("SELECT COUNT(*) FROM chat_history").fetchone()[0]
    conn.close()
    return n


# ── 1. Continuidad por directorio ──────────────────────────────────────────

def test_get_recent_turns_filtra_por_cwd(tmp_path):
    """Dos sesiones en dos cwd distintos: con cwd= solo vuelven los turnos del
    propio directorio; sin cwd, el comportamiento historico (todo)."""
    db = _db_con_esquema(tmp_path)
    ch = ChatHistory(db)
    ch.set_session("a" * 12, r"C:\proy\uno")
    ch.log(role="user", content="hola desde uno")
    ch.log(role="assistant", content="respuesta uno")
    ch.set_session("b" * 12, r"C:\otro\dos")
    ch.log(role="user", content="quien es MrBeast?")
    ch.log(role="assistant", content="turno del e2e")

    propios = ch.get_recent_turns(20, cwd=r"C:\proy\uno")
    assert [t["content"] for t in propios] == ["hola desde uno", "respuesta uno"]
    assert all("MrBeast" not in t["content"] for t in propios)

    # Windows: mayusculas/minusculas de la ruta no separan sesiones (NOCASE).
    assert len(ch.get_recent_turns(20, cwd=r"c:\PROY\UNO")) == 2

    # Directorio sin sesiones previas: NADA — no se hereda de otros cwd.
    assert ch.get_recent_turns(20, cwd=r"C:\virgen") == []

    # Sin cwd: el corpus entero, como siempre (callers de sintesis/RLM).
    assert len(ch.get_recent_turns(20)) == 4


def test_filas_viejas_sin_cwd_quedan_fuera(tmp_path):
    """Las filas de antes de la era session_id/cwd (cwd NULL) no se restauran
    cuando se filtra: no hay forma de saber de donde eran."""
    db = _db_con_esquema(tmp_path)
    ch = ChatHistory(db)          # sin set_session: cwd queda NULL
    ch.log(role="user", content="fila antigua")
    assert ch.get_recent_turns(20, cwd=r"C:\proy\uno") == []
    assert len(ch.get_recent_turns(20)) == 1


def test_el_repl_pasa_su_cwd_y_lo_dice():
    """Anti-regresion sobre la fuente del CLI: la semilla de continuidad tiene
    que ir con cwd= (el bug era exactamente llamarla sin filtro) y el mensaje
    tiene que decir el directorio conservando el prefijo 'Continuidad: N
    mensajes' que el remoto clasifica (cognia/remoto/sesiones.py)."""
    assert re.search(r"get_recent_turns\(\s*_HISTORY_SEED_N,\s*cwd=", FUENTE_CLI)
    assert "previas en {_dir_cont} restaurados" in FUENTE_CLI
    # El corpus profundo del RLM respeta la misma frontera.
    assert re.search(r"get_recent_turns\(\s*_RLM_VIVO_SEED_N,\s*cwd=", FUENTE_CLI)


# ── 2. Modo efimero ────────────────────────────────────────────────────────

def test_sesion_efimera_lee_la_env_por_llamada(monkeypatch):
    assert sesion_efimera() is False
    monkeypatch.setenv("COGNIA_EFIMERO", "1")
    assert sesion_efimera() is True
    monkeypatch.setenv("COGNIA_EFIMERO", "0")
    assert sesion_efimera() is False


def test_efimero_no_escribe_chat_history(tmp_path, monkeypatch):
    db = _db_con_esquema(tmp_path)
    ch = ChatHistory(db)
    ch.set_session("c" * 12, str(tmp_path))
    assert ch.log(role="user", content="persistente") is not None
    assert _cuenta(db) == 1

    monkeypatch.setenv("COGNIA_EFIMERO", "1")
    assert ch.log(role="user", content="soy MrBeast") is None
    assert ch.log(role="assistant", content="turno de prueba") is None
    assert _cuenta(db) == 1                      # ni una fila mas

    monkeypatch.delenv("COGNIA_EFIMERO")
    ch.log(role="user", content="vuelve a persistir")
    assert _cuenta(db) == 2


def test_efimero_no_escribe_user_profile(tmp_path, monkeypatch):
    """El perfil adapt_* (nombre/idioma/verbosidad) es lo que 'soy Tomas' pisa
    en cada mensaje libre: en efimero, set() es un no-op."""
    db = _db_con_esquema(tmp_path)
    prof = UserProfile(db)
    monkeypatch.setenv("COGNIA_EFIMERO", "1")
    prof.set("adapt_nombre", "MrBeast")
    assert prof.get("adapt_nombre") is None

    monkeypatch.delenv("COGNIA_EFIMERO")
    prof.set("adapt_nombre", "Tomas")
    assert prof.get("adapt_nombre") == "Tomas"


def test_repl_efimero_avisa_y_no_restaura_ni_persiste(tmp_path):
    """El REPL REAL por stdin con COGNIA_EFIMERO=1 y un COGNIA_DB_PATH
    temporal: avisa 'Sesion efimera', NO imprime linea de Continuidad y no
    deja ni una fila en chat_history. Es la verificacion tecleada del modo."""
    dbdir = tmp_path / "dbdir"
    env = dict(os.environ, PYTHONUTF8="1", COGNIA_SPINNER="0",
               COGNIA_ANIMACION="0", NO_COLOR="1",
               COGNIA_EFIMERO="1", COGNIA_DB_PATH=str(dbdir))
    p = subprocess.run([sys.executable, "-m", "cognia"],
                       input="/salir\n", capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env,
                       cwd=str(RAIZ), timeout=240)
    salida = (p.stdout or "") + (p.stderr or "")
    assert "Sesion efimera" in salida, salida[-2000:]
    assert "Continuidad:" not in salida
    db = dbdir / "cognia_memory.db"
    if db.exists():                 # Cognia() crea el esquema; 0 filas de chat
        assert _cuenta(str(db)) == 0


def test_lanzadores_de_prueba_llevan_efimero():
    """Una leccion en prosa no impide nada: los lanzadores que arrancan el
    REPL/agente real por subprocess tienen que exportar COGNIA_EFIMERO. Si
    alguien agrega uno nuevo sin el gate, este test no lo ve — pero si alguien
    se lo QUITA a los existentes (el vector del incidente), revienta aca."""
    lanzadores = [
        RAIZ / "scripts" / "e2e_happy_path.py",
        RAIZ / "scripts" / "e2e_goal_hibrido.py",
        RAIZ / "scripts" / "dsh_probar_tareas.py",
        RAIZ / "scripts" / "estilo_editor_gate_conpty.py",
        RAIZ / "scripts" / "prompt_gate_conpty.py",
        RAIZ / "tests" / "test_cli_cableado.py",
        RAIZ / "tests" / "test_cli_mejorar_prompt.py",
        RAIZ / "tests" / "test_repl_piped.py",
        RAIZ / "tests" / "test_cli_remoto_paridad.py",
        RAIZ / "tests" / "test_remoto_paridad.py",
    ]
    sin_gate = [str(p) for p in lanzadores
                if "COGNIA_EFIMERO" not in p.read_text(encoding="utf-8")]
    assert not sin_gate, f"lanzadores sin COGNIA_EFIMERO: {sin_gate}"


# ── 3. Entorno (SO/shell/cwd) en el prompt del chat ───────────────────────

def test_prompt_del_chat_trae_el_entorno(monkeypatch):
    monkeypatch.delenv("COGNIA_ENTORNO_PROMPT", raising=False)
    from cognia.system_prompt import build_system_prompt, entorno_usuario
    ent = entorno_usuario()
    # Verdadero en ESTA maquina, sin hardcodear el SO del CI.
    assert platform.system() in ent
    assert os.getcwd() in ent
    cerebro = build_system_prompt(rol="cerebro")
    assert "ENTORNO DEL USUARIO" in cerebro
    # La regla anti-invencion del incidente: el chat no ejecuta y deriva.
    assert "NO ejecutas nada" in cerebro and "/hacer" in cerebro
    assert "JAMAS afirmes haber ejecutado" in cerebro


def test_el_agente_no_recibe_el_BLOQUE_del_chat(monkeypatch):
    """A/B 2026-07-23: PROSA extra degrada el gate del agente de 10/10 a 1/4.

    Enmendado el 2026-08-25 (misma jornada, corrida posterior): el agente SI
    recibe una linea de datos con su SO/shell/cwd, porque sin ella ejecuto
    `uname -s`, `find` y `ls -R` en Windows, gasto 6 pasos y cerro "sin
    progreso verificado". Lo que sigue prohibido es el BLOQUE de prosa del
    chat; el tope de <=120 chars y el kill-switch los fija
    tests/test_agente_sabe_el_so.py."""
    from cognia.system_prompt import (TOPE_ENTORNO_AGENTE, build_system_prompt,
                                      entorno_agente)
    for perfil in ("minimo", "compacto", "completo"):
        monkeypatch.delenv("COGNIA_ENTORNO_PROMPT", raising=False)
        con = build_system_prompt(rol="agente", perfil=perfil)
        monkeypatch.setenv("COGNIA_ENTORNO_PROMPT", "0")
        sin = build_system_prompt(rol="agente", perfil=perfil)
        assert 0 < len(con) - len(sin) <= TOPE_ENTORNO_AGENTE
        monkeypatch.delenv("COGNIA_ENTORNO_PROMPT", raising=False)
        assert con == sin + "\n\n" + entorno_agente()
        assert "ENTORNO DEL USUARIO" not in con      # el bloque del chat, no
        assert "NO ejecutas nada" not in con         # (el agente SI ejecuta)


def test_kill_switch_del_entorno(monkeypatch):
    from cognia.system_prompt import entorno_usuario
    monkeypatch.setenv("COGNIA_ENTORNO_PROMPT", "0")
    assert entorno_usuario() == ""
