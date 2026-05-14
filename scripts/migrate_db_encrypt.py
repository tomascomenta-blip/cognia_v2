"""
scripts/migrate_db_encrypt.py
=============================
One-time migration: column-level AES-256-GCM encryption for sensitive
fields in episodic_memory (observation, notes).

Uses the existing KeyManager from security/key_manager.py.
Already-encrypted rows (base64 payload starting with CGN1 magic) are skipped,
making this script fully idempotent.

Usage:
    python scripts/migrate_db_encrypt.py [--db PATH] [--dry-run]

Passphrase (required):
    Set env var COGNIA_ENCRYPT_PASSPHRASE or pass --passphrase <value>.

Warning:
    Back up your database before running. Encryption is irreversible
    without the passphrase.
"""

import argparse
import base64
import os
import sqlite3
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

_MAGIC_B64_PREFIX = base64.b64encode(b"CGN1")[:4].decode("ascii")
_DEFAULT_DB = os.path.join(_ROOT, "cognia_memory.db")
_SALT_PATH = os.path.join(_ROOT, "cognia_key.salt")


def _is_encrypted(value: str) -> bool:
    if not value:
        return False
    try:
        decoded = base64.b64decode(value[:20].encode("ascii") + b"==")
        return decoded[:4] == b"CGN1"
    except Exception:
        return False


def _encrypt_column(km, value: str | None) -> str | None:
    if not value:
        return value
    if _is_encrypted(value):
        return value
    return km.encrypt_text(value)


def run(db_path: str, passphrase: str, dry_run: bool) -> int:
    from security.key_manager import KeyManager

    km = KeyManager(salt_path=_SALT_PATH)
    km.unlock(passphrase)

    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.text_factory = str
    conn.execute("PRAGMA journal_mode=WAL")

    rows = conn.execute(
        "SELECT id, observation, notes FROM episodic_memory"
    ).fetchall()

    to_update = []
    already_done = 0

    for row_id, observation, notes in rows:
        obs_enc = _encrypt_column(km, observation)
        notes_enc = _encrypt_column(km, notes)

        obs_changed = obs_enc != observation
        notes_changed = notes_enc != notes

        if obs_changed or notes_changed:
            to_update.append((obs_enc, notes_enc, row_id))
        else:
            already_done += 1

    tag = "[DRY-RUN] " if dry_run else ""
    print(f"{tag}Rows to encrypt : {len(to_update)}")
    print(f"{tag}Already encrypted: {already_done}")
    print(f"{tag}Total rows       : {len(rows)}")

    if dry_run:
        print("[DRY-RUN] No changes written.")
        conn.close()
        km.lock()
        return 0

    if not to_update:
        print("Nothing to do.")
        conn.close()
        km.lock()
        return 0

    conn.executemany(
        "UPDATE episodic_memory SET observation=?, notes=? WHERE id=?",
        to_update,
    )
    conn.commit()
    print(f"Encrypted {len(to_update)} row(s). Done.")
    conn.close()
    km.lock()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Encrypt sensitive columns in cognia_memory.db"
    )
    parser.add_argument("--db", default=_DEFAULT_DB,
                        help="Path to SQLite database (default: cognia_memory.db)")
    parser.add_argument("--passphrase", default=None,
                        help="Encryption passphrase (or set COGNIA_ENCRYPT_PASSPHRASE)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview changes without writing")
    args = parser.parse_args()

    passphrase = args.passphrase or os.environ.get("COGNIA_ENCRYPT_PASSPHRASE", "")
    if not passphrase:
        print("[FAIL] Passphrase required. Set COGNIA_ENCRYPT_PASSPHRASE or --passphrase.")
        return 1

    if not os.path.exists(args.db):
        print(f"[FAIL] Database not found: {args.db}")
        return 1

    return run(args.db, passphrase, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
