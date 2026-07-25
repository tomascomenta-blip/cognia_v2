# -*- coding: utf-8 -*-
"""Regresion 2026-07-25: el VectorCache se reconstruia ENTERO en cada turno.

Cada mensaje del usuario guarda un episodio -> cambia el hash de la DB -> se
releian y re-parseaban TODOS los vectores. Medido en la maquina del dueno con
su base real: "VectorCache construido: 65290 vectores en 5737.8ms" y un
"Operacion lenta: 5978ms | episodic.retrieve_similar" en CADA mensaje. O(n)
por turno y creciendo con la memoria.

Ahora: si solo hubo altas, se anaden esas filas (misma medicion: 14.6ms). Si
cambio algo viejo (olvidos/borrados), se cae a build completo.
"""
import datetime
import json
import random
import sqlite3
import time

import pytest

from cognia.memory.episodic_fast import VectorCache

DIM = 384


@pytest.fixture()
def base(tmp_path):
    ruta = tmp_path / "memoria.db"
    con = sqlite3.connect(str(ruta))
    con.execute("""CREATE TABLE episodic_memory (
        id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,
        observation TEXT, label TEXT, vector TEXT, confidence REAL,
        importance REAL, emotion_score REAL, emotion_label TEXT,
        surprise REAL, feedback_weight REAL, forgotten INTEGER DEFAULT 0)""")
    con.commit()
    yield str(ruta), con
    con.close()


def _alta(con, obs="ep"):
    con.execute(
        "INSERT INTO episodic_memory (timestamp,observation,label,vector,"
        "confidence,importance,forgotten) VALUES (?,?,?,?,?,?,0)",
        (datetime.datetime.now().isoformat(), obs, "l",
         json.dumps([random.random() for _ in range(DIM)]), 0.5, 1.0))
    con.commit()


def _turno(cache, con, obs="nuevo"):
    """Un mensaje del usuario: se guarda un episodio y se busca."""
    _alta(con, obs)
    cache.mark_dirty()
    cache._dirty_since = time.monotonic() - 999    # saltar el debounce
    cache.search([random.random() for _ in range(DIM)], top_k=3)


def test_alta_no_reconstruye_todo(base, monkeypatch):
    ruta, con = base
    for i in range(30):
        _alta(con, f"ep{i}")
    c = VectorCache(ruta)
    c.build()
    assert len(c._meta) == 30

    builds = {"n": 0}
    original = c._build_locked

    def _contando(*a, **k):
        builds["n"] += 1
        return original(*a, **k)

    monkeypatch.setattr(c, "_build_locked", _contando)

    _turno(c, con, "el mensaje siguiente")
    assert len(c._meta) == 31, "el episodio nuevo tiene que estar en el cache"
    assert builds["n"] == 0, "un alta NO puede reconstruir la matriz entera"


def test_episodio_nuevo_es_buscable(base):
    """Incremental no puede significar 'desactualizado'."""
    ruta, con = base
    for i in range(10):
        _alta(con, f"ep{i}")
    c = VectorCache(ruta)
    c.build()
    _alta(con, "recuerdo fresquisimo")
    nuevo_id = con.execute("SELECT MAX(id) FROM episodic_memory").fetchone()[0]
    c.mark_dirty()
    c._dirty_since = time.monotonic() - 999
    c.search([random.random() for _ in range(DIM)], top_k=3)
    assert nuevo_id in {m["id"] for m in c._meta}


def test_olvido_de_uno_viejo_fuerza_build_completo(base):
    ruta, con = base
    for i in range(20):
        _alta(con, f"ep{i}")
    c = VectorCache(ruta)
    c.build()
    con.execute("UPDATE episodic_memory SET forgotten=1 WHERE id=3")
    con.commit()
    c.mark_dirty()
    c._dirty_since = time.monotonic() - 999
    c.search([random.random() for _ in range(DIM)], top_k=3)
    ids = {m["id"] for m in c._meta}
    assert 3 not in ids, "un episodio olvidado no puede seguir en el cache"
    assert len(c._meta) == 19


def test_cambio_de_importancia_reciente_se_refresca(base):
    """El ranking usa importance/confidence: un cambio reciente tiene que
    verse aunque no se reconstruya la matriz."""
    ruta, con = base
    for i in range(15):
        _alta(con, f"ep{i}")
    c = VectorCache(ruta)
    c.build()
    con.execute("UPDATE episodic_memory SET importance=9.0 WHERE id=15")
    con.commit()
    c.mark_dirty()
    c._dirty_since = time.monotonic() - 999
    c.search([random.random() for _ in range(DIM)], top_k=3)
    imp = [m["importance"] for m in c._meta if m["id"] == 15]
    assert imp == [9.0]


def test_cache_vacio_sigue_funcionando(base):
    ruta, _con = base
    c = VectorCache(ruta)
    c.build()
    assert c.search([random.random() for _ in range(DIM)], top_k=3) == []
