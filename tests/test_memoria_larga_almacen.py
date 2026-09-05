# -*- coding: utf-8 -*-
"""Almacén de memoria_larga: SQLite propio con FTS5, vectores, grafo y checkpoints. Sin modelo."""
import logging
import math
import os

import pytest

from cognia.memoria_larga import Memoria
from cognia.memoria_larga.almacen import Almacen, ruta_por_defecto


@pytest.fixture
def almacen(tmp_path):
    a = Almacen(tmp_path / "ml.db")
    yield a
    a.cerrar()


def _m(contenido, tipo="hecho", task_id="t1", **kw):
    return Memoria(tipo=tipo, contenido=contenido, task_id=task_id, **kw)


def test_ruta_por_defecto_respeta_cognia_home(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIA_HOME", str(tmp_path / "hogar"))
    assert ruta_por_defecto() == tmp_path / "hogar" / "memoria_larga.db"
    a = Almacen()
    try:
        assert a.ruta == tmp_path / "hogar" / "memoria_larga.db"
        assert (tmp_path / "hogar" / "memoria_larga.db").exists()
        assert a.fts5 is True
    finally:
        a.cerrar()


def test_crear_guardar_obtener(almacen):
    m = _m("Decisión: para la base de datos usamos SQLite.", tipo="decision", entidad="base de datos",
           valor="SQLite", tags=["decision"], entidades=["base de datos"], referencias=["msg:3"], importancia=5)
    i = almacen.guardar(m)
    assert i == 1 and m.id == 1
    g = almacen.obtener(1)
    assert g.tipo == "decision" and g.entidad == "base de datos" and g.valor == "SQLite"
    assert g.tags == ["decision"] and g.referencias == ["msg:3"] and g.entidades == ["base de datos"]
    assert g.hash and g.tokens > 0      # el almacén los completa si vienen vacíos
    assert almacen.obtener(999) is None


def test_guardar_lote_ids_consecutivos(almacen):
    ids = almacen.guardar_lote([_m(f"fila {i}") for i in range(5)])
    assert ids == [1, 2, 3, 4, 5]
    assert almacen.contar()["total"] == 5
    assert almacen.guardar_lote([]) == []


def test_tipo_desconocido_degrada_a_nota_avisando(almacen, caplog):
    with caplog.at_level(logging.WARNING):
        almacen.guardar(_m("x", tipo="inventado"))
    assert almacen.obtener(1).tipo == "nota"
    assert "tipo desconocido" in caplog.text


def test_fts_bm25_matchea_solo_palabras_del_texto(almacen):
    almacen.guardar(_m("El planificador usa APScheduler para las tareas nocturnas.", tipo="decision"))
    almacen.guardar(_m("Los tests de facturas pasan en 1.2 segundos.", tipo="test"))
    res = almacen.buscar_lexico("planificador APScheduler")
    assert [m.contenido[:15] for m, _ in res] == ["El planificador"]
    assert res[0][1] > 0                       # score positivo = -bm25
    assert almacen.buscar_lexico("kafka rabbitmq zookeeper") == []
    # la tilde no importa (remove_diacritics) y la puntuación no rompe el MATCH
    assert len(almacen.buscar_lexico("¿planificador: APScheduler?")) == 1
    assert almacen.buscar_lexico("") == []


def test_buscar_lexico_filtros(almacen):
    almacen.guardar(_m("cache con Redis", tipo="decision", task_id="A"))
    almacen.guardar(_m("cache con Redis", tipo="hecho", task_id="B"))
    almacen.guardar(_m("cache con Redis", tipo="hecho", task_id="B", estado="superada"))
    assert len(almacen.buscar_lexico("redis")) == 2                       # solo vigentes
    assert len(almacen.buscar_lexico("redis", solo_vigentes=False)) == 3
    assert [m.task_id for m, _ in almacen.buscar_lexico("redis", task_id="A")] == ["A"]
    assert [m.tipo for m, _ in almacen.buscar_lexico("redis", tipos=["hecho"])] == ["hecho"]
    assert len(almacen.buscar_lexico("redis", limite=1)) == 1


def test_fts_se_mantiene_tras_actualizar_y_borrar(almacen):
    i = almacen.guardar(_m("usamos httpx como cliente"))
    almacen.actualizar(i, contenido="usamos requests como cliente")
    assert almacen.buscar_lexico("httpx") == []
    assert len(almacen.buscar_lexico("requests")) == 1
    almacen.borrar(i)
    assert almacen.buscar_lexico("requests") == []


def test_vectores_guardar_leer_buscar_coseno(almacen):
    ids = almacen.guardar_lote([_m("a", task_id="t1"), _m("b", task_id="t1"), _m("c", task_id="t2")])
    almacen.guardar_vector(ids[0], [1.0, 0.0, 0.0])
    almacen.guardar_vector(ids[1], [0.0, 1.0, 0.0])
    almacen.guardar_vector(ids[2], [0.9, 0.1, 0.0])
    v = almacen.vector(ids[0])
    assert v == [1.0, 0.0, 0.0] and almacen.vector(999) is None
    res = almacen.buscar_vector([1.0, 0.0, 0.0], solo_vigentes=False)
    assert [m.id for m, _ in res] == [ids[0], ids[2], ids[1]]
    assert math.isclose(res[0][1], 1.0, abs_tol=1e-6) and math.isclose(res[2][1], 0.0, abs_tol=1e-6)
    # con task_id solo se cargan los candidatos de esa tarea
    res = almacen.buscar_vector([1.0, 0.0, 0.0], task_id="t2")
    assert [m.id for m, _ in res] == [ids[2]]
    assert almacen.buscar_vector([0.0, 0.0, 0.0]) == []
    assert almacen.ids_con_vector(ids + [999]) == set(ids)


def test_vector_dim_distinta_se_ignora_avisando(almacen, caplog):
    i = almacen.guardar(_m("a"))
    almacen.guardar_vector(i, [1.0, 0.0])
    with caplog.at_level(logging.WARNING):
        assert almacen.buscar_vector([1.0, 0.0, 0.0]) == []
    assert "dim distinta" in caplog.text


def test_relaciones_y_vecinos_dos_saltos(almacen):
    a, b, c, d = almacen.guardar_lote([_m("a"), _m("b"), _m("c"), _m("d")])
    almacen.relacionar(a, b, "caused_by")
    almacen.relacionar(c, b, "solves")          # dirección inversa: b es destino
    almacen.relacionar(c, d, "modifies")
    v1 = almacen.vecinos(a, saltos=1)
    assert [(m.id, t, dist) for m, t, dist in v1] == [(b, "caused_by", 1)]
    v2 = {m.id: (t, dist) for m, t, dist in almacen.vecinos(a, saltos=2)}
    assert v2 == {b: ("caused_by", 1), c: ("solves", 2)}
    v3 = {m.id: dist for m, _, dist in almacen.vecinos(a, saltos=3)}
    assert v3 == {b: 1, c: 2, d: 3}
    assert [m.id for m, _, _ in almacen.vecinos(a, tipos=["modifies"], saltos=3)] == []
    assert almacen.vecinos(999) == []


def test_relacion_tipo_desconocido_avisa(almacen, caplog):
    a, b = almacen.guardar_lote([_m("a"), _m("b")])
    with caplog.at_level(logging.WARNING):
        almacen.relacionar(a, b, "inventada")
    assert "tipo desconocido" in caplog.text


def test_superar_e_historial_de_tres_versiones(almacen):
    va = almacen.guardar(_m("bd = SQLite", tipo="decision", entidad="base de datos", valor="SQLite"))
    vb = almacen.guardar(_m("bd = PostgreSQL", tipo="decision", entidad="base de datos", valor="PostgreSQL"))
    almacen.superar(va, vb)
    vc = almacen.guardar(_m("bd = MySQL", tipo="decision", entidad="base de datos", valor="MySQL"))
    almacen.superar(vb, vc)
    A, B, C = almacen.obtener(va), almacen.obtener(vb), almacen.obtener(vc)
    assert A.estado == "superada" and A.valid_until is not None and A.superseded_by == vb
    assert B.estado == "superada" and B.valid_until is not None and B.supersedes == va and B.superseded_by == vc
    assert C.estado == "vigente" and C.valid_until is None and C.supersedes == vb
    # por_entidad: vigentes primero
    assert [m.valor for m in almacen.por_entidad("Base De Datos")] == ["MySQL", "PostgreSQL", "SQLite"]
    assert [m.valor for m in almacen.por_entidad("base de datos", solo_vigentes=True)] == ["MySQL"]
    # y la relación 'supersedes' queda en el grafo
    assert [(m.id, t) for m, t, _ in almacen.vecinos(vc, tipos=["supersedes"])] == [(vb, "supersedes")]


def test_por_entidad_encuentra_la_clave_normalizada_con_tilde_y_articulo(almacen):
    # extracción guarda 'autenticacion' (sin tilde ni artículo); el que pregunta escribe como habla
    almacen.guardar(_m("auth = JWT", tipo="decision", entidad="autenticacion", valor="JWT"))
    assert [m.valor for m in almacen.por_entidad("autenticación")] == ["JWT"]
    assert [m.valor for m in almacen.por_entidad("la Autenticación")] == ["JWT"]
    assert almacen.por_entidad("autorización") == []


def test_actualizar_campos_y_desconocidos(almacen, caplog):
    i = almacen.guardar(_m("x", tags=["a"]))
    with caplog.at_level(logging.WARNING):
        assert almacen.actualizar(i, tags=["a", "b"], confianza=0.9, inventado=1) is True
    m = almacen.obtener(i)
    assert m.tags == ["a", "b"] and m.confianza == 0.9
    assert "desconocidos" in caplog.text
    assert almacen.actualizar(999, confianza=0.1) is False
    assert almacen.actualizar(i) is False


def test_checkpoints_guardar_y_ultimo_por_cwd(almacen):
    i1 = almacen.checkpoint_guardar({"task_id": "t1", "session_id": "s", "cwd": "/a", "paso": 3, "next_action": "x",
                                     "timestamp": 100.0})
    i2 = almacen.checkpoint_guardar({"task_id": "t1", "session_id": "s", "cwd": "/a", "paso": 7, "next_action": "y",
                                     "timestamp": 200.0})
    almacen.checkpoint_guardar({"task_id": "t2", "cwd": "/b", "paso": 1, "timestamp": 300.0})
    u = almacen.checkpoint_ultimo(cwd="/a")
    assert u["id"] == i2 and u["paso"] == 7 and u["next_action"] == "y" and u["timestamp"] == 200.0
    assert almacen.checkpoint_ultimo(task_id="t2")["cwd"] == "/b"
    assert almacen.checkpoint_ultimo()["task_id"] == "t2"           # el más reciente de todos
    assert almacen.checkpoint_ultimo(cwd="/zzz") is None
    assert [c["id"] for c in almacen.checkpoints("t1")] == [i2, i1]
    assert almacen.checkpoint_borrar_viejos("t1", conservar=1) == 1
    assert [c["id"] for c in almacen.checkpoints("t1")] == [i2]


def test_recientes_contar_estadisticas(almacen):
    almacen.guardar_lote([_m("a", tipo="decision", task_id="t1", timestamp=1.0, nivel=2),
                          _m("b", tipo="error", task_id="t1", timestamp=2.0, nivel=2),
                          _m("c", tipo="error", task_id="t2", timestamp=3.0, nivel=1, estado="superada")])
    almacen.guardar_vector(1, [1.0, 2.0])
    almacen.checkpoint_guardar({"task_id": "t1"})
    assert [m.contenido for m in almacen.recientes("t1", limite=5)] == ["b", "a"]
    c = almacen.contar("t1")
    assert c == {"total": 2, "por_tipo": {"decision": 1, "error": 1}, "por_estado": {"vigente": 2}}
    e = almacen.estadisticas()
    assert e["total"] == 3 and e["por_tipo"] == {"decision": 1, "error": 2}
    assert e["por_estado"] == {"vigente": 2, "superada": 1} and e["por_nivel"] == {1: 1, 2: 2}
    assert e["vectores"] == 1 and e["checkpoints"] == 1 and e["tareas"] == 2
    assert e["bytes"] > 0 and e["fts5"] is True and e["en_ram"] is False


def test_podar_borra_descartadas_y_las_de_importancia_1_mas_viejas(almacen):
    almacen.guardar_lote([_m("desc", estado="descartada"),
                          _m("vieja1", importancia=1, timestamp=1.0),
                          _m("vieja2", importancia=1, timestamp=2.0),
                          _m("imp5", importancia=5, timestamp=0.5)])
    almacen.guardar_vector(2, [1.0])
    assert almacen.podar(max_filas=2) == 2
    assert sorted(m.contenido for m in almacen.recientes(None, limite=10)) == ["imp5", "vieja2"]
    assert almacen.estadisticas()["vectores"] == 0      # huérfano limpiado


def test_persistencia_entre_dos_instancias(tmp_path):
    ruta = tmp_path / "p.db"
    a = Almacen(ruta)
    i = a.guardar(_m("persistente con Jinja2", tipo="decision"))
    a.guardar_vector(i, [0.5, 0.5])
    a.checkpoint_guardar({"task_id": "t1", "paso": 2})
    a.cerrar()
    b = Almacen(ruta)
    try:
        assert b.obtener(i).contenido == "persistente con Jinja2"
        assert [m.id for m, _ in b.buscar_lexico("jinja2")] == [i]
        assert b.vector(i) == [0.5, 0.5]
        assert b.checkpoint_ultimo(task_id="t1")["paso"] == 2
        assert b._con.execute("PRAGMA user_version").fetchone()[0] >= 1
    finally:
        b.cerrar()


def test_sin_disco_cae_a_ram_avisando(tmp_path, caplog):
    # un directorio como ruta de DB no se puede abrir → RAM de la sesión
    with caplog.at_level(logging.WARNING):
        a = Almacen(tmp_path)
    try:
        assert a.en_ram is True and "RAM" in caplog.text
        assert a.guardar(_m("en ram")) == 1
        assert a.estadisticas()["bytes"] == 0
    finally:
        a.cerrar()


def test_fallback_like_sin_fts5(almacen, caplog):
    almacen.fts5 = False       # simula SQLite sin FTS5 compilado
    almacen.guardar(_m("cache con memcached", tipo="decision"))
    almacen.guardar(_m("logger con loguru"))
    with caplog.at_level(logging.WARNING):
        res = almacen.buscar_lexico("memcached cache")
        almacen.buscar_lexico("memcached")
    assert [(m.contenido, s) for m, s in res] == [("cache con memcached", 2.0)]
    assert almacen.buscar_lexico("kafka") == []
    assert caplog.text.count("LIKE") == 1          # se avisa UNA vez por instancia
