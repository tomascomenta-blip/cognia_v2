import os
import secrets
import sqlite3
import time

DATA_DIR = os.environ.get("DATA_DIR", "/data")
_DB_PATH = os.path.join(DATA_DIR, "keys.db")


def _connect() -> sqlite3.Connection:
    os.makedirs(DATA_DIR, exist_ok=True)
    return sqlite3.connect(_DB_PATH)


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS api_keys (
                key TEXT PRIMARY KEY,
                created_at REAL NOT NULL,
                last_used REAL,
                request_count INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.commit()


def generate_key() -> str:
    return "cogn-" + secrets.token_hex(8)


def create_key() -> str:
    key = generate_key()
    now = time.time()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO api_keys (key, created_at, last_used, request_count) VALUES (?, ?, NULL, 0)",
            (key, now),
        )
        conn.commit()
    return key


def validate_key(key: str) -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT key FROM api_keys WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return False
        conn.execute(
            "UPDATE api_keys SET last_used = ?, request_count = request_count + 1 WHERE key = ?",
            (time.time(), key),
        )
        conn.commit()
    return True


def list_keys() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT key, created_at, last_used, request_count FROM api_keys ORDER BY created_at DESC"
        ).fetchall()
    return [
        {"key": r[0], "created_at": r[1], "last_used": r[2], "request_count": r[3]}
        for r in rows
    ]
