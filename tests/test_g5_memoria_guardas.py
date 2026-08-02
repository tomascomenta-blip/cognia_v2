# -*- coding: utf-8 -*-
"""
Guardas de memoria (revision adversarial de la fase de reparacion, 2026-08-01).

Cada test falla SIN su fix:

  1. Un typo en el env NO debe activar la purga: COGNIA_MAX_MEMORIES='abc'
     antes caia al default ACTIVO (200k/1024MB); ahora avisa por WARNING y
     DESACTIVA el eje.
  2. El patron LIKE 'conocimiento_%' usaba '_' como comodin SQL: un label del
     usuario tipo 'conocimientos_personales' entraba al barrido. Ahora va con
     ESCAPE en el seeder y en el script de limpieza.
  3. El script de limpieza: dry-run por defecto, backup antes de borrar, jamas
     toca memorias del usuario, y conserva la copia ACTIVA del hecho (no una
     olvidada de id menor).
"""

import importlib.util
import json
import logging
import os
import sys

import pytest

from cognia.database import init_db
from storage.db_pool import db_connect_pooled, close_pool
from cognia.memory import memory_budget as MB

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_VEC = json.dumps([0.1] * 8)


@pytest.fixture
def db(tmp_path):
    p = str(tmp_path / "mem.db")
    init_db(p)
    yield p
    close_pool(p)


def _ins(db_path, observation, label, forgotten=0):
    conn = db_connect_pooled(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO episodic_memory (timestamp, observation, label, vector, "
            "confidence, importance, feedback_weight, access_count, forgotten) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            ("2026-01-01", observation, label, _VEC, 0.8, 1.0, 1.0, 1, forgotten),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _rows(db_path):
    conn = db_connect_pooled(db_path)
    try:
        return conn.execute(
            "SELECT id, observation, label, forgotten FROM episodic_memory ORDER BY id"
        ).fetchall()
    finally:
        conn.close()


# ── 1. env no parseable: avisa y DESACTIVA ────────────────────────────


def test_env_no_parseable_desactiva_el_eje(monkeypatch, caplog):
    monkeypatch.setenv("COGNIA_MAX_MEMORIES", "abc")
    monkeypatch.delenv("COGNIA_MAX_DB_MB", raising=False)
    with caplog.at_level(logging.WARNING, logger=MB.__name__):
        limites = MB.get_limits()
    assert limites == (None, MB._DEFAULT_MAX_DB_MB)  # antes: (200000, 1024)
    assert any("abc" in r.getMessage() and r.levelno == logging.WARNING
               for r in caplog.records), caplog.text


@pytest.mark.parametrize("valor", ["abc", "200k", "1_000 memorias", "??"])
def test_env_basura_nunca_activa_una_purga(db, monkeypatch, valor):
    # 60 filas y un default DE PRUEBA de 10: si el typo cayera al default,
    # enforce borraria 50 memorias reales. Con el fix no toca ninguna.
    for i in range(60):
        _ins(db, f"memoria {i}", "usuario")
    monkeypatch.setattr(MB, "_DEFAULT_MAX_MEMORIES", 10)
    monkeypatch.setenv("COGNIA_MAX_MEMORIES", valor)
    monkeypatch.setenv("COGNIA_MAX_DB_MB", "0")  # eje de disco fuera del test

    rep = MB.enforce_memory_budget(db)
    assert rep["soft_deleted"] == 0 and rep["hard_deleted"] == 0
    assert MB.current_usage(db)["active"] == 60


def test_env_valido_sigue_funcionando(db, monkeypatch):
    # El fix no debe romper el camino bueno: un numero valido SI purga.
    for i in range(60):
        _ins(db, f"memoria {i}", "usuario")
    monkeypatch.setenv("COGNIA_MAX_MEMORIES", "10")
    monkeypatch.setenv("COGNIA_MAX_DB_MB", "0")
    rep = MB.enforce_memory_budget(db)
    assert rep["soft_deleted"] == 50
    assert MB.current_usage(db)["active"] == 10


# ── 2. LIKE con ESCAPE en el seeder ───────────────────────────────────


def test_seeder_no_confunde_label_del_usuario(db):
    from cognia.knowledge.knowledge_seeder import KnowledgeSeeder, seed_observations

    texto = sorted(seed_observations())[0]
    # Memoria del usuario con un label que el comodin '_' hacia casar.
    _ins(db, texto, "conocimientos_personales")

    class _Mem:
        pass
    mem = _Mem()
    mem.db = db

    vistos = KnowledgeSeeder._existing_seed_observations(mem)
    # Sin ESCAPE, 'conocimientos_personales' casaba y el hecho no se sembraba.
    assert texto not in vistos


# ── 3. script de limpieza ─────────────────────────────────────────────


def _cargar_script():
    ruta = os.path.join(_REPO, "scripts", "limpiar_seed_duplicado.py")
    spec = importlib.util.spec_from_file_location("limpiar_seed_duplicado_test", ruta)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _poblar(db_path):
    """Devuelve (textos_seed, ids_usuario). Siembra duplicados de 2 hechos."""
    from cognia.knowledge.knowledge_seeder import seed_observations
    textos = sorted(seed_observations())[:2]
    for t in textos:
        for _ in range(3):
            _ins(db_path, t, "conocimiento_python")
    ids_usuario = [
        # label que el comodin '_' hacia entrar al DELETE, con el MISMO texto
        # que un hecho del seed: el peor caso posible.
        _ins(db_path, textos[0], "conocimientos_personales"),
        _ins(db_path, textos[0], "conocimientos_personales"),
        # memoria normal
        _ins(db_path, "mi clave del wifi es 1234", "usuario"),
        # label de seed pero texto que NO esta en la whitelist
        _ins(db_path, "nota mia que no es del seed", "conocimiento_python"),
        _ins(db_path, "nota mia que no es del seed", "conocimiento_python"),
    ]
    return textos, ids_usuario


def test_script_dry_run_por_defecto_no_borra(db, monkeypatch, capsys):
    _poblar(db)
    antes = _rows(db)
    mod = _cargar_script()
    monkeypatch.setattr(mod, "DB_PATH", db)
    monkeypatch.setattr(sys, "argv", ["limpiar_seed_duplicado.py"])

    assert mod.main() == 0
    salida = capsys.readouterr().out
    assert "DRY-RUN" in salida
    assert "DUPLICADOS A BORRAR: 4" in salida, salida
    assert _rows(db) == antes  # ni una fila movida


def test_script_no_toca_memorias_del_usuario(db, monkeypatch):
    textos, ids_usuario = _poblar(db)
    mod = _cargar_script()
    monkeypatch.setattr(mod, "DB_PATH", db)
    monkeypatch.setattr(sys, "argv", ["limpiar_seed_duplicado.py", "--aplicar"])

    assert mod.main() == 0
    ids = {r[0] for r in _rows(db)}
    # Sin ESCAPE + whitelist, las 'conocimientos_personales' y las notas con
    # label de seed pero texto ajeno se iban en el barrido.
    for i in ids_usuario:
        assert i in ids, f"el script borro una memoria del usuario (id {i})"
    # y de cada hecho del seed queda EXACTAMENTE una fila
    for t in textos:
        n = sum(1 for r in _rows(db) if r[1] == t and r[2] == "conocimiento_python")
        assert n == 1, f"quedaron {n} copias de {t!r}"


def test_script_conserva_la_copia_ACTIVA(db, monkeypatch):
    from cognia.knowledge.knowledge_seeder import seed_observations
    texto = sorted(seed_observations())[0]
    id_olvidada = _ins(db, texto, "conocimiento_python", forgotten=1)  # id MENOR
    id_activa = _ins(db, texto, "conocimiento_python", forgotten=0)
    assert id_olvidada < id_activa

    mod = _cargar_script()
    monkeypatch.setattr(mod, "DB_PATH", db)
    monkeypatch.setattr(sys, "argv", ["limpiar_seed_duplicado.py", "--aplicar"])
    assert mod.main() == 0

    ids = {r[0] for r in _rows(db)}
    # Con MIN(id) a secas sobrevivia la olvidada y se perdia la unica copia viva.
    assert id_activa in ids and id_olvidada not in ids


def test_script_hace_backup_restaurable_antes_de_borrar(db, monkeypatch, tmp_path):
    _poblar(db)
    antes = len(_rows(db))
    mod = _cargar_script()
    monkeypatch.setattr(mod, "DB_PATH", db)
    monkeypatch.setattr(sys, "argv", ["limpiar_seed_duplicado.py", "--aplicar"])
    assert mod.main() == 0

    baks = [f for f in os.listdir(str(tmp_path))
            if ".bak-" in f and not f.endswith(("-wal", "-shm"))]
    assert baks, os.listdir(str(tmp_path))
    # El backup no es un archivo decorativo: se abre y tiene TODAS las filas
    # previas al borrado.
    bak = str(tmp_path / baks[0])
    assert mod._contar_filas(bak) == antes
    close_pool(bak)
    assert len(_rows(db)) < antes  # y el borrado si ocurrio


def test_script_aborta_si_el_backup_falla(db, monkeypatch):
    _poblar(db)
    antes = _rows(db)
    mod = _cargar_script()
    monkeypatch.setattr(mod, "DB_PATH", db)
    monkeypatch.setattr(sys, "argv", ["limpiar_seed_duplicado.py", "--aplicar"])
    monkeypatch.setattr(mod, "_backup", lambda p: (_ for _ in ()).throw(OSError("disco lleno")))

    assert mod.main() == 1
    assert _rows(db) == antes  # sin backup NO se borra nada
