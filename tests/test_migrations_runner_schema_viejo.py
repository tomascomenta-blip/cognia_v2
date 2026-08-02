"""
tests/test_migrations_runner_schema_viejo.py
============================================
Regresion del bug de _set_version (auditoria adversarial 2026-08-01):

    MigrationRunner._set_version hacia
        UPDATE schema_version SET version=?, applied_at=?
    a ciegas. En una DB con el schema viejo schema_version(version) — que es
    exactamente lo que crea cognia/database.py — la columna applied_at no
    existe todavia (la agrega la migracion 3), asi que el UPDATE reventaba con
    "no such column: applied_at" al cerrar la migracion 2, ANTES de llegar a
    la migracion 3. Consecuencia: _migration_3 era una rama muerta y el
    runner nunca pasaba de la version 1 (init_db ademas se tragaba la
    excepcion con un except Exception: pass — fallo silencioso).

Estos tests fallan sin el fix (PRAGMA table_info + escritura solo de las
columnas reales) y pasan con el.
"""

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cognia.migrations import run_migrations
from storage.db_pool import close_pool


def _schema_viejo(path: str) -> None:
    """DB como la deja cognia/database.py antes del runner: schema_version
    SOLO con la columna version, y la tabla episodic_memory base que las
    migraciones 1 y 2 esperan alterar."""
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    conn.execute("INSERT INTO schema_version (version) VALUES (1)")
    conn.execute(
        "CREATE TABLE episodic_memory (id INTEGER PRIMARY KEY, "
        "feedback_weight REAL DEFAULT 1.0)"
    )
    conn.commit()
    conn.close()


def _columnas(path: str, tabla: str) -> set:
    conn = sqlite3.connect(path)
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({tabla})").fetchall()}
    conn.close()
    return cols


def _fila_version(path: str) -> sqlite3.Row:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM schema_version").fetchone()
    conn.close()
    return row


@pytest.fixture()
def db_vieja(tmp_path):
    path = str(tmp_path / "vieja.db")
    _schema_viejo(path)
    yield path
    # El runner ahora va por el pool: drenarlo para poder borrar el archivo
    # en Windows (mismo patron que tests/test_db_pool_migration_v3.py).
    close_pool(path)


def test_llega_a_version_3_desde_schema_viejo_sin_excepcion(db_vieja):
    # Sin el fix: sqlite3.OperationalError "no such column: applied_at"
    # al cerrar la migracion 2. Con el fix: aplica 2 y 3 sin excepcion.
    applied = run_migrations(db_vieja)
    assert applied == 2, f"esperaba migraciones 2 y 3 aplicadas, aplico {applied}"
    row = _fila_version(db_vieja)
    assert row["version"] == 3


def test_migration_3_ya_no_es_rama_muerta(db_vieja):
    # La migracion 3 (la que agrega applied_at/app_version) tiene que haber
    # corrido de verdad: las columnas existen en la DB final.
    run_migrations(db_vieja)
    cols = _columnas(db_vieja, "schema_version")
    assert "applied_at" in cols
    assert "app_version" in cols


def test_metadatos_se_escriben_cuando_las_columnas_existen(db_vieja):
    # Tras la migracion 3 las columnas existen; _set_version de la version 3
    # (que corre DESPUES del ALTER de _migration_3) debe poblarlas.
    run_migrations(db_vieja)
    row = _fila_version(db_vieja)
    assert row["applied_at"] is not None
    assert row["app_version"] is not None


def test_segunda_corrida_es_noop(db_vieja):
    # Idempotencia: una vez en version 3, correr de nuevo no aplica nada.
    run_migrations(db_vieja)
    assert run_migrations(db_vieja) == 0


def test_db_totalmente_nueva_sin_fila_de_version(tmp_path):
    # Rama INSERT de _set_version: DB sin fila en schema_version (version 0)
    # con schema viejo. Deben aplicar las 3 migraciones.
    path = str(tmp_path / "cero.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    conn.execute(
        "CREATE TABLE episodic_memory (id INTEGER PRIMARY KEY)"
    )
    conn.commit()
    conn.close()
    try:
        applied = run_migrations(path)
        assert applied == 3
        row = _fila_version(path)
        assert row["version"] == 3
        cols = _columnas(path, "episodic_memory")
        assert "feedback_weight" in cols
        assert "encrypted_at" in cols
    finally:
        close_pool(path)
