"""
cognia/database.py
==================
Conexión SQLite, inicialización de tablas y limpieza de ruido.
"""

import sqlite3
from datetime import datetime, timedelta
from .config import DB_PATH, KG_STOPWORDS


def db_connect(path: str = None) -> sqlite3.Connection:
    """
    Wrapper para sqlite3.connect con configuración correcta para Windows.
    Fuerza UTF-8 como text_factory para evitar corrupción de acentos.
    """
    if path is None:
        path = DB_PATH
    conn = sqlite3.connect(path)
    conn.text_factory = str
    return conn


def init_db(path: str = DB_PATH):
    """
    Inicializa o migra la base de datos.
    Completamente retrocompatible con v2 — solo agrega tablas nuevas.
    """
    conn = db_connect(path)
    c = conn.cursor()

    # ── Tablas heredadas de v2 ─────────────────────────────────────────
    c.execute("""
    CREATE TABLE IF NOT EXISTS episodic_memory (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp     TEXT NOT NULL,
        observation   TEXT NOT NULL,
        label         TEXT,
        vector        TEXT NOT NULL,
        confidence    REAL DEFAULT 0.5,
        access_count  INTEGER DEFAULT 0,
        last_access   TEXT,
        importance    REAL DEFAULT 1.0,
        forgotten     INTEGER DEFAULT 0,
        compressed    INTEGER DEFAULT 0,
        emotion_score REAL DEFAULT 0.0,
        emotion_label TEXT DEFAULT 'neutral',
        surprise      REAL DEFAULT 0.0,
        review_count  INTEGER DEFAULT 0,
        next_review   TEXT,
        context_tags  TEXT DEFAULT '[]',
        notes         TEXT
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
        response_id TEXT
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

    conn.commit()
    conn.close()


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
