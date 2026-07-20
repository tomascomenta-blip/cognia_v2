"""
cognia/database.py
==================
Conexión SQLite, inicialización de tablas y limpieza de ruido.
"""

import logging as _log
import os as _os
import sqlite3
from datetime import datetime, timedelta
from .config import DB_PATH, KG_STOPWORDS

_encrypt_warned = False


def db_connect(path: str = None) -> sqlite3.Connection:
    """
    Wrapper para sqlite3.connect con configuración optimizada.
    - WAL mode: mejor concurrencia multi-hilo (sin database is locked)
    - cache_size: reduce I/O repetitivo
    - text_factory: evita corrupción de acentos en Windows

    NOTA deuda (2026-07-16): este wrapper aplica los MISMOS pragmas que
    storage/db_pool pero devuelve conexiones propias (no pooleadas). La
    migración al pool va módulo a módulo (patrón user_facts/goal_tracker;
    los call-sites por-operación ya migraron) porque varios callers retienen
    la conexión de por vida y poolearlos a ciegas agota el pool (stalls de
    10s en acquire). No agregar call-sites nuevos de este wrapper: usar
    storage.db_pool.db_connect_pooled.
    """
    if path is None:
        path = DB_PATH
    conn = sqlite3.connect(path, check_same_thread=False, timeout=30)
    conn.text_factory = str
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=10000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _run_migrations(conn: sqlite3.Connection):
    """
    Aplica migraciones de schema en orden ascendente.
    Cada migración es idempotente: usa PRAGMA table_info antes de ALTER.
    """
    conn.execute("""
    CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER NOT NULL
    )""")
    row = conn.execute("SELECT version FROM schema_version").fetchone()
    current = row[0] if row else 0

    # Migration 1: add feedback_weight to episodic_memory
    if current < 1:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(episodic_memory)").fetchall()}
        with conn:
            if "feedback_weight" not in cols:
                conn.execute(
                    "ALTER TABLE episodic_memory ADD COLUMN feedback_weight REAL DEFAULT 1.0"
                )
            if row:
                conn.execute("UPDATE schema_version SET version = 1")
            else:
                conn.execute("INSERT INTO schema_version (version) VALUES (1)")

    # chat_history: ensure session_id + cwd exist (per-session /resume).
    # Deliberately version-AGNOSTIC and idempotent rather than gated on
    # schema_version: a second migration runner (cognia/migrations/runner.py)
    # shares this same schema_version table and may have advanced the counter
    # past any gate we'd pick, which would silently skip the ALTER and break
    # /resume with "no such column". A bare PRAGMA + conditional ALTER is cheap
    # and safe to run every startup. We do NOT touch schema_version here (the
    # other runner owns it; writing it could downgrade its value).
    has_chat = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='chat_history'"
    ).fetchone() is not None
    if has_chat:
        cols = {r[1] for r in conn.execute(
            "PRAGMA table_info(chat_history)").fetchall()}
        with conn:
            if "session_id" not in cols:
                conn.execute("ALTER TABLE chat_history ADD COLUMN session_id TEXT")
            if "cwd" not in cols:
                conn.execute("ALTER TABLE chat_history ADD COLUMN cwd TEXT")

    conn.commit()


def init_db(path: str = DB_PATH):
    """
    Inicializa o migra la base de datos.
    Completamente retrocompatible con v2 — solo agrega tablas nuevas.
    """
    global _encrypt_warned
    if not _os.getenv("COGNIA_ENCRYPT_PASSPHRASE") and not _encrypt_warned:
        _log.getLogger("cognia.db").warning(
            "COGNIA_ENCRYPT_PASSPHRASE not set — episodic memory is stored unencrypted. "
            "Run: python scripts/migrate_db_encrypt.py"
        )
        _encrypt_warned = True
    conn = db_connect(path)
    c = conn.cursor()

    # ── Tablas heredadas de v2 ─────────────────────────────────────────
    c.execute("""
    CREATE TABLE IF NOT EXISTS episodic_memory (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp       TEXT NOT NULL,
        observation     TEXT NOT NULL,
        label           TEXT,
        vector          TEXT NOT NULL,
        confidence      REAL DEFAULT 0.5,
        access_count    INTEGER DEFAULT 0,
        last_access     TEXT,
        importance      REAL DEFAULT 1.0,
        forgotten       INTEGER DEFAULT 0,
        compressed      INTEGER DEFAULT 0,
        emotion_score   REAL DEFAULT 0.0,
        emotion_label   TEXT DEFAULT 'neutral',
        surprise        REAL DEFAULT 0.0,
        review_count    INTEGER DEFAULT 0,
        next_review     TEXT,
        context_tags    TEXT DEFAULT '[]',
        notes           TEXT,
        feedback_weight REAL DEFAULT 1.0
    )""")

    c.execute("""
    CREATE TABLE IF NOT EXISTS semantic_memory (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        concept       TEXT NOT NULL UNIQUE,
        description   TEXT,
        vector        TEXT NOT NULL,
        confidence    REAL DEFAULT 0.5,
        support       INTEGER DEFAULT 1,
        last_updated  TEXT,
        parent_concept TEXT,
        emotion_avg   REAL DEFAULT 0.0,
        associations  TEXT DEFAULT '{}'
    )""")

    c.execute("""
    CREATE TABLE IF NOT EXISTS hypotheses (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        hypothesis  TEXT NOT NULL,
        confidence  REAL DEFAULT 0.3,
        created_at  TEXT,
        validated   INTEGER DEFAULT 0,
        contradicts TEXT
    )""")

    c.execute("""
    CREATE TABLE IF NOT EXISTS world_model (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        entity_a    TEXT NOT NULL,
        relation    TEXT NOT NULL,
        entity_b    TEXT NOT NULL,
        strength    REAL DEFAULT 0.5,
        source      TEXT
    )""")

    c.execute("""
    CREATE TABLE IF NOT EXISTS decision_log (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp   TEXT,
        action      TEXT,
        prediction  TEXT,
        outcome     TEXT,
        was_error   INTEGER DEFAULT 0,
        learned     TEXT
    )""")

    c.execute("""
    CREATE TABLE IF NOT EXISTS contradictions (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp   TEXT,
        concept     TEXT,
        claim_a     TEXT,
        claim_b     TEXT,
        resolved    INTEGER DEFAULT 0,
        resolution  TEXT
    )""")

    c.execute("""
    CREATE TABLE IF NOT EXISTS sleep_log (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp     TEXT,
        episodes_in   INTEGER,
        concepts_out  INTEGER,
        duration_ms   INTEGER
    )""")

    c.execute("""
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

    c.execute("""
    CREATE TABLE IF NOT EXISTS user_profile (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        key         TEXT NOT NULL UNIQUE,
        value       TEXT,
        updated_at  TEXT
    )""")

    # ── Tablas nuevas v3 ───────────────────────────────────────────────
    c.execute("""
    CREATE TABLE IF NOT EXISTS knowledge_graph (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        subject     TEXT NOT NULL,
        predicate   TEXT NOT NULL,
        object      TEXT NOT NULL,
        weight      REAL DEFAULT 1.0,
        source      TEXT DEFAULT 'learned',
        timestamp   TEXT,
        verified    INTEGER DEFAULT 0,
        UNIQUE(subject, predicate, object)
    )""")

    c.execute("""
    CREATE TABLE IF NOT EXISTS temporal_sequences (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        from_concept TEXT NOT NULL,
        to_concept   TEXT NOT NULL,
        count        INTEGER DEFAULT 1,
        last_seen    TEXT,
        avg_gap_sec  REAL DEFAULT 0.0
    )""")

    c.execute("""
    CREATE TABLE IF NOT EXISTS goal_system (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        goal_type   TEXT NOT NULL,
        description TEXT,
        priority    REAL DEFAULT 0.5,
        status      TEXT DEFAULT 'pending',
        created_at  TEXT,
        resolved_at TEXT,
        metadata    TEXT DEFAULT '{}'
    )""")

    c.execute("""
    CREATE TABLE IF NOT EXISTS inference_rules (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        premise_a   TEXT NOT NULL,
        predicate_a TEXT NOT NULL,
        premise_b   TEXT NOT NULL,
        predicate_b TEXT NOT NULL,
        conclusion  TEXT NOT NULL,
        confidence  REAL DEFAULT 0.7,
        use_count   INTEGER DEFAULT 0,
        created_at  TEXT
    )""")

    # Índices
    c.execute("CREATE INDEX IF NOT EXISTS idx_episodic_label ON episodic_memory(label, forgotten)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_episodic_timestamp ON episodic_memory(timestamp DESC) WHERE forgotten=0")
    c.execute("CREATE INDEX IF NOT EXISTS idx_semantic_concept ON semantic_memory(concept, confidence DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_kg_subject ON knowledge_graph(subject, weight DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_kg_object ON knowledge_graph(object, weight DESC)")

    _run_migrations(conn)
    conn.commit()
    conn.close()

    try:
        from cognia.migrations import run_migrations
        run_migrations(path)
    except Exception:
        pass


def limpiar_episodios_ruido(path: str = DB_PATH) -> dict:
    """
    Limpieza de memoria episódica durante el ciclo de sueño:
      1. Marca como olvidados episodios sin label + importancia baja + >7 días
      2. Elimina triples KG con stopwords o tokens muy cortos
    """
    conn = db_connect(path)
    c = conn.cursor()
    cutoff = (datetime.now() - timedelta(days=7)).isoformat()
    c.execute("""
        UPDATE episodic_memory SET forgotten=1
        WHERE label IS NULL AND importance < 0.35
          AND timestamp < ? AND context_tags LIKE '%chat%' AND forgotten=0
    """, (cutoff,))
    episodios = c.rowcount

    kg_elim = 0
    for sw in list(KG_STOPWORDS)[:30]:
        c.execute("DELETE FROM knowledge_graph WHERE (subject=? OR object=?) AND weight < 1.0", (sw, sw))
        kg_elim += c.rowcount
    c.execute("DELETE FROM knowledge_graph WHERE length(subject) < 3 OR length(object) < 3")
    kg_elim += c.rowcount

    conn.commit()
    conn.close()
    return {"episodios_limpiados": episodios, "kg_triples_eliminados": kg_elim}
