"""
cognia/memory/chat.py
=====================
Historial de conversación y perfil de usuario.
"""

import os

from datetime import datetime
from storage.db_pool import db_connect_pooled as db_connect
from ..config import DB_PATH


def sesion_efimera() -> bool:
    """True si esta corrida NO debe dejar rastro en la memoria del dueno.

    POR QUE (incidente 2026-08-25): las pruebas e2e de la manana (REPL por
    stdin desde worktrees/Temp preguntando por MrBeast, Acua Boy, ...) se
    guardaron en el chat_history REAL, y a las 11:52 la continuidad le
    restauro esos 20 mensajes al dueno ("Hace rato que no te veo, MrBeast").
    El anticuerpo es un modo efimero OPT-IN por env: COGNIA_EFIMERO=1 apaga
    la escritura en chat_history y user_profile (los gates viven en las
    clases de este modulo, asi cubren TODAS las vias: streaming, agente y
    articulada, que loguea por su cuenta en respuestas_articuladas.py).
    Se lee en CADA llamada, no en el import: los tests lo activan con
    monkeypatch.setenv despues de importar, y un valor congelado al import
    los dejaria escribiendo igual.
    """
    return os.environ.get("COGNIA_EFIMERO", "").strip() == "1"


class ChatHistory:
    """
    Historial de conversación separado de episodic_memory.
    Las preguntas del chat NO contaminan la memoria episódica real.
    """
    def __init__(self, db_path: str = DB_PATH):
        self.db = db_path
        # Current session context. Set once at REPL startup via set_session();
        # log() then stamps every row (streaming, agent AND articulated paths,
        # since they all go through this same instance) so /resume can later
        # bring back a session by id or by the directory it ran in.
        self._session_id = None
        self._cwd = None

    def set_session(self, session_id: str, cwd: str):
        """Bind this instance to a session so all subsequent log() rows carry it."""
        self._session_id = session_id
        self._cwd = cwd

    def log(self, role: str, content: str, label_used: str = None,
            confidence: float = 0.0, response_id: str = None,
            session_id: str = None, cwd: str = None):
        """Inserta el mensaje y devuelve su id (rowid de chat_history).

        Devolver el id permite que el caller cree punteros 'msg' en el context
        map (context_engine.record_conversation con user_msg_id/assistant_msg_id)
        sin duplicar el texto. Retrocompatible: los callers que ignoran el
        retorno siguen funcionando igual.

        En sesion EFIMERA (COGNIA_EFIMERO=1) devuelve None SIN insertar: es el
        gate central contra la contaminacion del historial del dueno por
        pruebas e2e/agentes (ver sesion_efimera()). Devolver None es seguro:
        el unico consumidor del rowid (record_conversation del context map)
        va detras de /contexto-auto, que en una sesion efimera no tiene
        sentido encender."""
        if sesion_efimera():
            return None
        conn = db_connect(self.db)
        try:
            c = conn.cursor()
            c.execute("""
                INSERT INTO chat_history
                    (timestamp, role, content, label_used, confidence, response_id,
                     session_id, cwd)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (datetime.now().isoformat(), role, content, label_used, confidence,
                  response_id, session_id or self._session_id, cwd or self._cwd))
            conn.commit()
            return c.lastrowid
        finally:
            conn.close()

    def add_feedback(self, response_id: str, feedback: int):
        """feedback: 1=correcto, -1=incorrecto, 0=neutro"""
        conn = db_connect(self.db)
        try:
            c = conn.cursor()
            c.execute("UPDATE chat_history SET feedback=? WHERE response_id=?", (feedback, response_id))
            conn.commit()
        finally:
            conn.close()

    def get_recent(self, n: int = 10) -> list:
        conn = db_connect(self.db)
        try:
            c = conn.cursor()
            c.execute("""
                SELECT role, content, label_used, confidence, feedback, timestamp
                FROM chat_history ORDER BY timestamp DESC LIMIT ?
            """, (n,))
            rows = [{"role": r[0], "content": r[1][:80], "label": r[2],
                     "confidence": r[3], "feedback": r[4], "ts": r[5]}
                    for r in c.fetchall()]
        finally:
            conn.close()
        return list(reversed(rows))

    def get_recent_turns(self, n: int = 20, cwd: str = None) -> list:
        """
        Full-content user/assistant turns for restoring conversation continuity
        across restarts (seeds the REPL's in-memory _history buffer).

        Unlike get_recent(), content is NOT truncated and only user/assistant
        roles are returned, in chronological (oldest-first) order. Ordered by id
        (monotonic autoincrement) rather than the textual timestamp so ties and
        clock quirks can't scramble turn order.

        cwd: si viene, SOLO turnos de sesiones que corrieron en ese directorio
        (COLLATE NOCASE: en Windows C:\\proy y c:\\proy son el mismo). POR QUE
        (incidente 2026-08-25): la continuidad restauraba los ultimos 20
        mensajes de CUALQUIER directorio, y al dueno en Desktop le aparecieron
        los turnos de unas pruebas e2e corridas en worktrees/Temp ("Hace rato
        que no te veo, MrBeast"). Las filas viejas sin cwd (NULL, anteriores a
        la era session_id/cwd) quedan FUERA cuando se filtra: no hay forma de
        saber de donde eran, y restaurarlas repetiria el bug con otro disfraz.
        Sin cwd, el comportamiento historico (todo) se conserva para los
        callers que quieren el corpus entero.
        """
        conn = db_connect(self.db)
        c = conn.cursor()
        if cwd:
            c.execute("""
                SELECT role, content FROM chat_history
                WHERE role IN ('user', 'assistant')
                  AND cwd = ? COLLATE NOCASE
                ORDER BY id DESC LIMIT ?
            """, (cwd, n))
        else:
            c.execute("""
                SELECT role, content FROM chat_history
                WHERE role IN ('user', 'assistant')
                ORDER BY id DESC LIMIT ?
            """, (n,))
        rows = [{"role": r[0], "content": r[1]} for r in c.fetchall()]
        conn.close()
        return list(reversed(rows))

    def list_sessions(self, limit: int = 10, cwd: str = None) -> list:
        """
        Recent sessions (those with a session_id), newest activity first.
        If cwd is given, only sessions that ran in that directory (case-insensitive
        so Windows paths match). Each entry: session_id, cwd, count, first_ts,
        last_ts.
        """
        conn = db_connect(self.db)
        c = conn.cursor()
        if cwd:
            c.execute("""
                SELECT session_id, cwd, COUNT(*),
                       MIN(timestamp), MAX(timestamp)
                FROM chat_history
                WHERE session_id IS NOT NULL AND cwd = ? COLLATE NOCASE
                GROUP BY session_id
                ORDER BY MAX(id) DESC LIMIT ?
            """, (cwd, limit))
        else:
            c.execute("""
                SELECT session_id, cwd, COUNT(*),
                       MIN(timestamp), MAX(timestamp)
                FROM chat_history
                WHERE session_id IS NOT NULL
                GROUP BY session_id
                ORDER BY MAX(id) DESC LIMIT ?
            """, (limit,))
        rows = [{"session_id": r[0], "cwd": r[1], "count": r[2],
                 "first_ts": r[3], "last_ts": r[4]} for r in c.fetchall()]
        conn.close()
        return rows

    def latest_session_for_dir(self, cwd: str) -> str:
        """session_id of the most recent session that ran in cwd, or None."""
        rows = self.list_sessions(limit=1, cwd=cwd)
        return rows[0]["session_id"] if rows else None

    def resolve_session_prefix(self, prefix: str) -> str:
        """Most recent session_id whose id starts with prefix, or None."""
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("""
            SELECT session_id FROM chat_history
            WHERE session_id LIKE ?
            GROUP BY session_id ORDER BY MAX(id) DESC LIMIT 1
        """, (prefix + "%",))
        row = c.fetchone()
        conn.close()
        return row[0] if row else None

    def get_session_turns(self, session_id: str, limit: int = 40) -> list:
        """
        The most recent user/assistant turns of one session, full content,
        chronological (oldest-first) -- for seeding _history on /resume.
        """
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("""
            SELECT role, content FROM chat_history
            WHERE session_id = ? AND role IN ('user', 'assistant')
            ORDER BY id DESC LIMIT ?
        """, (session_id, limit))
        rows = [{"role": r[0], "content": r[1]} for r in c.fetchall()]
        conn.close()
        return list(reversed(rows))

    def get_frequent_topics(self, top_k: int = 5) -> list:
        conn = db_connect(self.db)
        try:
            c = conn.cursor()
            c.execute("""
                SELECT label_used, COUNT(*) as freq
                FROM chat_history
                WHERE role='user' AND label_used IS NOT NULL
                GROUP BY label_used ORDER BY freq DESC LIMIT ?
            """, (top_k,))
            rows = [{"label": r[0], "freq": r[1]} for r in c.fetchall()]
        finally:
            conn.close()
        return rows

    def count(self) -> int:
        conn = db_connect(self.db)
        try:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM chat_history")
            n = c.fetchone()[0]
        finally:
            conn.close()
        return n


class UserProfile:
    """Perfil simple del usuario: nombre, idioma, estadísticas."""
    def __init__(self, db_path: str = DB_PATH):
        self.db = db_path

    def set(self, key: str, value: str):
        """Upsert de un rasgo del perfil.

        En sesion EFIMERA (COGNIA_EFIMERO=1) NO escribe: los rasgos adapt_*
        (nombre, idioma, verbosidad) los aprende learn_user_traits de CADA
        mensaje libre, asi que una prueba e2e que teclea "soy MrBeast"
        pisaria el adapt_nombre REAL del dueno (paso el 2026-08-25)."""
        if sesion_efimera():
            return
        conn = db_connect(self.db)
        try:
            c = conn.cursor()
            c.execute("""
                INSERT INTO user_profile (key, value, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
            """, (key, value, datetime.now().isoformat()))
            conn.commit()
        finally:
            conn.close()

    def get(self, key: str, default: str = None) -> str:
        conn = db_connect(self.db)
        try:
            c = conn.cursor()
            c.execute("SELECT value FROM user_profile WHERE key=?", (key,))
            row = c.fetchone()
        finally:
            conn.close()
        return row[0] if row else default

    def get_all(self) -> dict:
        conn = db_connect(self.db)
        try:
            c = conn.cursor()
            c.execute("SELECT key, value FROM user_profile")
            result = dict(c.fetchall())
        finally:
            conn.close()
        return result
