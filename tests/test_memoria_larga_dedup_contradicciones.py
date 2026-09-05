# -*- coding: utf-8 -*-
"""Dedup (tres frases equivalentes → una) y contradicciones con historial (SQLite → PostgreSQL)."""
import logging

import pytest

from cognia.memoria_larga import Memoria
from cognia.memoria_larga.almacen import Almacen
from cognia.memoria_larga.extraccion import extraer
from cognia.memoria_larga import dedup, contradicciones

K = dict(task_id="t1", session_id="s1")


@pytest.fixture
def almacen(tmp_path):
    a = Almacen(tmp_path / "ml.db")
    yield a
    a.cerrar()


def _guardar_con_dedup(almacen, m: Memoria) -> tuple[Memoria, bool]:
    """Flujo del integrador: si es duplicada se fusiona y la nueva se descarta."""
    ex = dedup.es_duplicada(almacen, m)
    if ex is not None:
        return dedup.fusionar(almacen, ex, m), True
    almacen.guardar(m)
    return m, False


def test_tres_frases_equivalentes_sobre_sqlite_fusionan_en_una(almacen):
    frases = ["Decisión: para la base de datos usamos SQLite. Motivo: el equipo ya lo conoce.",
              "Decidido: usamos SQLite para la base de datos.",
              "Decisión: para la base de datos usamos SQLite. Motivo: el equipo ya lo conoce."]   # hash exacto
    resultados = []
    for i, f in enumerate(frases):
        (m,) = extraer("user", f, paso=i, **K)
        m.referencias = [f"msg:{i}"]
        resultados.append(_guardar_con_dedup(almacen, m))
    assert [dup for _, dup in resultados] == [False, True, True]
    assert almacen.contar("t1")["total"] == 1
    unica = almacen.obtener(1)
    assert unica.referencias == ["msg:0", "msg:1", "msg:2"]
    assert unica.entidad == "base de datos" and unica.valor == "SQLite" and unica.importancia == 5
    assert abs(unica.confianza - min(1.0, 0.9 + 0.2)) < 1e-9
    assert unica.timestamp >= resultados[0][0].timestamp


def test_es_duplicada_por_hash_solo_en_la_misma_tarea(almacen):
    a = Memoria(tipo="hecho", contenido="El logger es loguru", task_id="A")
    almacen.guardar(a)
    b = Memoria(tipo="hecho", contenido="el  LOGGER es loguru", task_id="A")     # mismo hash normalizado
    assert dedup.es_duplicada(almacen, b).id == a.id
    c = Memoria(tipo="hecho", contenido="El logger es loguru", task_id="B")
    assert dedup.es_duplicada(almacen, c) is None
    almacen.actualizar(a.id, estado="superada")
    assert dedup.es_duplicada(almacen, b) is None          # solo vigentes


def test_es_duplicada_por_jaccard_y_por_vector(almacen):
    a = Memoria(tipo="solucion", contenido="arreglado el parser de fechas normalizando a utc en la entrada", task_id="t")
    almacen.guardar(a)
    casi = Memoria(tipo="solucion", contenido="arreglado el parser de fechas normalizando a utc en la entrada ya", task_id="t")
    assert dedup.es_duplicada(almacen, casi).id == a.id          # jaccard 11/12 ≥ 0.8
    lejos = Memoria(tipo="solucion", contenido="arreglado el parser de fechas con otra cosa distinta y más", task_id="t")
    assert dedup.es_duplicada(almacen, lejos) is None
    almacen.guardar_vector(a.id, [1.0, 0.0])
    assert dedup.es_duplicada(almacen, lejos, vector=[0.99, 0.01]).id == a.id
    assert dedup.es_duplicada(almacen, lejos, vector=[0.0, 1.0]) is None
    # otro tipo no se considera candidato
    otro = Memoria(tipo="nota", contenido=casi.contenido, task_id="t")
    assert dedup.es_duplicada(almacen, otro) is None


def test_fusionar_une_listas_y_sube_confianza(almacen):
    ex = Memoria(tipo="decision", contenido="x", task_id="t", tags=["a"], entidades=["e1"], referencias=["r1"],
                 confianza=0.95, importancia=3)
    almacen.guardar(ex)
    nueva = Memoria(tipo="decision", contenido="x", task_id="t", tags=["a", "b"], entidades=["e2"], referencias=["r2"],
                    importancia=5, entidad="cache", valor="Redis")
    f = dedup.fusionar(almacen, ex, nueva)
    assert f.id == ex.id and f.tags == ["a", "b"] and f.entidades == ["e1", "e2"] and f.referencias == ["r1", "r2"]
    assert f.confianza == 1.0 and f.importancia == 5 and f.entidad == "cache" and f.valor == "Redis"
    assert almacen.contar()["total"] == 1                     # la nueva no se insertó


def test_fusionar_sobre_id_inexistente_avisa(almacen, caplog):
    fantasma = Memoria(tipo="nota", contenido="x", id=999)
    with caplog.at_level(logging.WARNING):
        assert dedup.fusionar(almacen, fantasma, Memoria(tipo="nota", contenido="y")) is fantasma
    assert "no existe" in caplog.text


def test_contradiccion_sqlite_a_postgresql_con_historial(almacen):
    (vieja,) = extraer("user", "Decisión: para la base de datos usamos SQLite. Motivo: el equipo ya lo conoce.", paso=1, **K)
    almacen.guardar(vieja)
    assert contradicciones.detectar(almacen, vieja) is None
    (nueva,) = extraer("user", "Cambio de decisión: la base de datos deja de ser SQLite y pasa a ser PostgreSQL, "
                               "porque no soporta transacciones anidadas. Actualizá lo que haga falta.", paso=40, **K)
    c = contradicciones.detectar(almacen, nueva)
    assert c is not None and c.id == vieja.id
    almacen.guardar(nueva)
    contradicciones.resolver(almacen, c, nueva)
    v = almacen.obtener(vieja.id)
    assert v.estado == "superada" and v.valid_until is not None and v.superseded_by == nueva.id
    assert almacen.obtener(nueva.id).supersedes == vieja.id
    h = contradicciones.historial(almacen, "base de datos", task_id="t1")
    assert [m.valor for m in h] == ["SQLite", "PostgreSQL"]
    assert [m.estado for m in h] == ["superada", "vigente"]
    # la vigente no se contradice consigo misma ni con la superada
    assert contradicciones.detectar(almacen, almacen.obtener(nueva.id)) is None


def test_historial_de_tres_versiones_y_sin_entidad(almacen):
    ids = []
    for i, v in enumerate(["JWT", "sesiones firmadas", "OAuth2"]):
        m = Memoria(tipo="decision", contenido=f"auth = {v}", task_id="t", entidad="autenticación", valor=v, timestamp=100.0 + i)
        c = contradicciones.detectar(almacen, m)
        almacen.guardar(m)
        if c is not None:
            contradicciones.resolver(almacen, c, m)
        ids.append(m.id)
    h = contradicciones.historial(almacen, "autenticación")
    assert [m.id for m in h] == ids and [m.valor for m in h] == ["JWT", "sesiones firmadas", "OAuth2"]
    assert contradicciones.historial(almacen, "no existe") == []
    assert contradicciones.historial(almacen, "autenticación", task_id="otra") == []


def test_detectar_ignora_tipos_sin_clave_y_mismo_valor(almacen):
    almacen.guardar(Memoria(tipo="decision", contenido="x", task_id="t", entidad="cache", valor="Redis"))
    assert contradicciones.detectar(almacen, Memoria(tipo="decision", contenido="y", task_id="t", entidad="cache", valor="redis")) is None
    assert contradicciones.detectar(almacen, Memoria(tipo="nota", contenido="y", task_id="t", entidad="cache", valor="diskcache")) is None
    assert contradicciones.detectar(almacen, Memoria(tipo="decision", contenido="y", task_id="t", entidad="", valor="diskcache")) is None
    assert contradicciones.detectar(almacen, Memoria(tipo="decision", contenido="y", task_id="t", entidad="cache", valor="diskcache")).valor == "Redis"
    # distinto tipo con la misma entidad no es contradicción (hecho vs decision)
    assert contradicciones.detectar(almacen, Memoria(tipo="hecho", contenido="y", task_id="t", entidad="cache", valor="diskcache")) is None


def test_resolver_sin_ids_avisa(almacen, caplog):
    with caplog.at_level(logging.WARNING):
        contradicciones.resolver(almacen, Memoria(tipo="decision", contenido="a"), Memoria(tipo="decision", contenido="b"))
    assert "ids faltantes" in caplog.text


def test_historial_con_eslabon_borrado_se_corta_avisando(almacen, caplog):
    a = Memoria(tipo="decision", contenido="a", entidad="e", valor="1", timestamp=1.0)
    b = Memoria(tipo="decision", contenido="b", entidad="e", valor="2", timestamp=2.0)
    c = Memoria(tipo="decision", contenido="c", entidad="e", valor="3", timestamp=3.0)
    for m in (a, b, c):
        almacen.guardar(m)
    almacen.superar(a.id, b.id)
    almacen.superar(b.id, c.id)
    almacen.borrar(b.id)
    with caplog.at_level(logging.WARNING):
        h = contradicciones.historial(almacen, "e")
    assert [m.valor for m in h] == ["3"] and "cadena cortada" in caplog.text
