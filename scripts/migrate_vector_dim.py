"""
scripts/migrate_vector_dim.py
=============================
One-time migration: re-embed episodic_memory vectors to a single, consistent
dimension (384) so the VectorCache fast-path never hits a dim mismatch.

Why this exists
---------------
`VECTOR_DIM` used to be `384 if sentence_transformers installed else 64`.
Uninstalling sentence-transformers silently flipped NEW vectors (and every
query) to dim 64 while the DB still held 384-dim rows from before. The
VectorCache builds its matrix on the dominant dim (384), so a 64-dim query hits
`(N,384) @ (64,)` -> matmul crash -> ~6s Python slow-path on every search.

config.py now pins VECTOR_DIM = 384 unconditionally, so no new 64-dim rows are
created. This script fixes the rows already on disk: it re-embeds every vector
whose stored dimension != 384 (or all rows, with --all) from its preserved
`observation` text, using the app's own embedder. The observation text -- the
actual memory -- is never touched; only the derived vector index is regenerated,
so the operation is safe and repeatable.

Idempotent: re-running it is a no-op once every row is 384-dim (unless --all).

Usage
-----
    python scripts/migrate_vector_dim.py            # dry-run report only
    python scripts/migrate_vector_dim.py --apply    # re-embed dim != 384 rows
    python scripts/migrate_vector_dim.py --apply --all   # re-embed EVERY row
    python scripts/migrate_vector_dim.py --apply --db PATH

A timestamped backup copy of the DB is written before any change unless
--no-backup is passed.
"""

import argparse
import json
import os
import shutil
import sys
import time
from collections import Counter

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

TARGET_DIM = 384


def _distribution(conn) -> Counter:
    c = Counter()
    for (vec_str,) in conn.execute(
        "SELECT vector FROM episodic_memory WHERE forgotten = 0"
    ).fetchall():
        try:
            c[len(json.loads(vec_str))] += 1
        except Exception:
            c["unparseable"] += 1
    return c


def _looks_encrypted(text: str) -> bool:
    # Encrypted observation columns are base64 of a CGN1-magic payload.
    if not text:
        return False
    try:
        import base64
        return base64.b64decode(text[:20].encode("ascii") + b"==")[:4] == b"CGN1"
    except Exception:
        return False


def run(db_path: str, apply: bool, do_all: bool, do_backup: bool) -> int:
    from storage.db_pool import db_connect_pooled
    from cognia.cognia_embedding import _ngram_vector, text_to_vector_fast

    if not os.path.exists(db_path):
        print(f"[ERROR] DB no encontrada: {db_path}")
        return 1

    conn = db_connect_pooled(db_path)
    try:
        before = _distribution(conn)
        print(f"DB: {db_path}")
        print(f"Distribucion ANTES: {dict(before.most_common())}")

        rows = conn.execute(
            "SELECT id, observation, vector FROM episodic_memory"
        ).fetchall()

        to_fix = []          # (id, observation)
        skipped_encrypted = 0
        skipped_no_text = 0
        for ep_id, obs, vec_str in rows:
            try:
                cur_dim = len(json.loads(vec_str))
            except Exception:
                cur_dim = -1
            needs = do_all or cur_dim != TARGET_DIM
            if not needs:
                continue
            if not obs:
                skipped_no_text += 1
                continue
            if _looks_encrypted(obs):
                skipped_encrypted += 1
                continue
            to_fix.append((ep_id, obs))

        print(f"Filas a reembeber: {len(to_fix)}"
              + (f"  (--all)" if do_all else "  (dim != 384)"))
        if skipped_no_text:
            print(f"  Omitidas sin observation: {skipped_no_text}")
        if skipped_encrypted:
            print(f"  Omitidas cifradas (re-ejecuta con passphrase): {skipped_encrypted}")

        if not apply:
            print("\n[DRY-RUN] Nada escrito. Re-ejecuta con --apply para aplicar.")
            return 0

        if not to_fix:
            print("Nada que hacer. La DB ya es consistente a 384.")
            return 0

        if do_backup:
            stamp = time.strftime("%Y%m%d-%H%M%S")
            backup = f"{db_path}.bak-{stamp}"
            shutil.copy2(db_path, backup)
            print(f"Backup creado: {backup}")

        # Re-embed via the app's own embedder so migrated vectors live in the
        # SAME space future queries use (n-gram@384 when ST absent, ST@384 if
        # present). Fall back to a direct n-gram if the embedder errors.
        updated = 0
        t0 = time.time()
        for ep_id, obs in to_fix:
            try:
                vec = text_to_vector_fast(obs, dim=TARGET_DIM)
                if not vec or len(vec) != TARGET_DIM:
                    vec = _ngram_vector(obs, TARGET_DIM)
            except Exception:
                vec = _ngram_vector(obs, TARGET_DIM)
            conn.execute(
                "UPDATE episodic_memory SET vector = ? WHERE id = ?",
                (json.dumps(vec), ep_id),
            )
            updated += 1
            if updated % 2000 == 0:
                print(f"  ... {updated}/{len(to_fix)}")
        conn.commit()
        elapsed = time.time() - t0

        after = _distribution(conn)
        print(f"\nReembebidos: {updated} en {elapsed:.1f}s")
        print(f"Distribucion DESPUES: {dict(after.most_common())}")
        non_target = sum(n for d, n in after.items() if d != TARGET_DIM)
        if non_target == 0:
            print("OK: todos los vectores activos estan en dim 384. Cache fast-path consistente.")
        else:
            print(f"AVISO: quedan {non_target} vectores fuera de 384 "
                  "(probablemente cifrados o sin texto).")
        return 0
    finally:
        conn.close()  # commit + release al pool


def main() -> None:
    ap = argparse.ArgumentParser(description="Re-embed episodic vectors to dim 384.")
    ap.add_argument("--db", default=None,
                    help="Ruta a la DB (default: cognia.config.DB_PATH).")
    ap.add_argument("--apply", action="store_true",
                    help="Aplicar cambios (sin esto es dry-run).")
    ap.add_argument("--all", dest="do_all", action="store_true",
                    help="Reembeber TODAS las filas, no solo las de dim != 384.")
    ap.add_argument("--no-backup", dest="backup", action="store_false",
                    help="No crear copia de seguridad antes de aplicar.")
    args = ap.parse_args()

    db_path = args.db
    if db_path is None:
        from cognia.config import DB_PATH
        db_path = DB_PATH

    sys.exit(run(db_path, apply=args.apply, do_all=args.do_all, do_backup=args.backup))


if __name__ == "__main__":
    main()
