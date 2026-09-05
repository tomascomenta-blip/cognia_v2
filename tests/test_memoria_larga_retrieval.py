# -*- coding: utf-8 -*-
"""Tests del retrieval de memoria_larga contra un AlmacenFalso en RAM.

El almacén real (almacen.py) lo escribe otro módulo; aquí se programa contra
la interfaz del contrato (__init__.py). Si `almacen.py` existe, al final hay
un test de integración con él (se salta si aún no está)."""
from __future__ import annotations

import importlib.util
import json
import logging
import math
import re
import time

import pytest

from cognia.memoria_larga import Memoria, PESOS_DEFECTO
from cognia.memoria_larga.retrieval import Recuperador, tokenizar, terminos_consulta
from cognia.memoria_larga import reranker

SENALES = ("semantic", "lexical", "task", "importance", "recency", "confidence",
           "graph", "redundancy", "contradiction", "obsolescence")


# ------------------------------------------------------------ dobles de prueba

class EmbebedorFalso:
    """Mapea palabras clave a dimensiones fijas: dos textos con el mismo tema
    comparten dimensión aunque no compartan palabras. Determinista."""
    TEMAS = {
        0: ("sqlite", "postgres", "postgresql", "base", "datos", "database", "db", "almacenamiento", "persistencia", "motor"),
        1: ("auth", "login", "sesion", "sesión", "jwt", "token", "contraseña"),
        2: ("frontend", "react", "css", "boton", "botón", "color"),
        3: ("test", "pytest", "cobertura", "suite"),
    }

    def __init__(self, devolver_none: bool = False):
        self.devolver_none = devolver_none
        self.llamadas = 0

    def embeber(self, textos):
        self.llamadas += 1
        if self.devolver_none:
            return None
        salida = []
        for t in textos:
            toks = set(tokenizar(t))
            v = [0.0] * 8
            for dim, palabras in self.TEMAS.items():
                v[dim] = float(len(toks & set(palabras)))
            v[7] = 0.1  # componente común para que nunca sea el vector nulo
            n = math.sqrt(sum(x * x for x in v))
            salida.append([x / n for x in v])
        return salida

    def disponible(self):
        return not self.devolver_none


class AlmacenFalso:
    """Subconjunto del contrato de `Almacen`, en dicts. BM25 aproximado por
    conteo de términos (positivo, mayor = mejor)."""

    def __init__(self, fts5: bool = True):
        self.mem: dict[int, Memoria] = {}
        self.vecs: dict[int, list] = {}
        self.rel: list[tuple[int, int, str]] = []
        self.fts5 = fts5  # mismo nombre que en almacen.py
        self.version = 0
        self.llamadas: list[str] = []

    def guardar(self, m: Memoria) -> int:
        m.id = len(self.mem) + 1
        self.mem[m.id] = m
        self.version += 1
        return m.id

    def obtener(self, mid):
        return self.mem.get(mid)

    def buscar_lexico(self, consulta, task_id=None, tipos=None, limite=50, solo_vigentes=True):
        """Como el real: texto plano -> terminos (palabras) unidos por OR."""
        self.llamadas.append("lexico")
        assert '"' not in consulta and " OR " not in consulta, "el Recuperador debe pasar texto plano"
        terms = [t.lower() for t in re.findall(r"\w+", consulta) if len(t) >= 2]
        out = []
        for m in self.mem.values():
            if solo_vigentes and m.estado != "vigente":
                continue
            toks = set(tokenizar(m.contenido)) | set(tokenizar(m.resumen))
            hits = [t for t in terms if t in toks]
            if hits:
                out.append((m, float(len(hits))))
        out.sort(key=lambda x: -x[1])
        return out[:limite]

    def buscar_vector(self, vector, task_id=None, tipos=None, limite=50, solo_vigentes=True):
        self.llamadas.append("vector")
        out = []
        for mid, v in self.vecs.items():
            m = self.mem[mid]
            if solo_vigentes and m.estado != "vigente":
                continue
            c = sum(a * b for a, b in zip(vector, v))
            out.append((m, c))
        out.sort(key=lambda x: -x[1])
        return out[:limite]

    def vector(self, mid):
        return self.vecs.get(mid)

    def guardar_vector(self, mid, vector):
        self.vecs[mid] = list(vector)

    def relacionar(self, o, d, tipo, peso=1.0):
        self.rel.append((o, d, tipo))

    def vecinos(self, mid, tipos=None, saltos=1):
        out = []
        for o, d, t in self.rel:
            if tipos and t not in tipos:
                continue
            if o == mid and d in self.mem:
                out.append((self.mem[d], t, 1))
            elif d == mid and o in self.mem:
                out.append((self.mem[o], t, 1))
        return out

    def superar(self, vieja_id, nueva_id):
        v, n = self.mem[vieja_id], self.mem[nueva_id]
        v.estado, v.valid_until, v.superseded_by = "superada", time.time(), nueva_id
        n.supersedes = vieja_id
        self.relacionar(nueva_id, vieja_id, "supersedes")
        self.version += 1

    def recientes(self, task_id, limite):
        ms = [m for m in self.mem.values() if m.task_id == task_id]
        ms.sort(key=lambda m: -m.timestamp)
        return ms[:limite]

    def por_entidad(self, entidad, task_id=None):
        e = entidad.lower()
        return [m for m in self.mem.values()
                if m.entidad.lower() == e or any(str(x).lower() == e for x in m.entidades)]


def _mem(contenido, tipo="decision", task="t1", imp=4, edad_h=0.0, tags=None, **kw):
    return Memoria(tipo=tipo, contenido=contenido, task_id=task, importancia=imp,
                   timestamp=time.time() - edad_h * 3600, tags=tags or [], **kw)


def _almacen_base(emb=None):
    a = AlmacenFalso()
    a.guardar(_mem("Decidimos usar SQLite como base de datos por simplicidad de despliegue", edad_h=72))
    a.guardar(_mem("El login usa JWT con expiración de 24 horas", tipo="hecho"))
    a.guardar(_mem("El botón principal es de color azul en React", tipo="nota", imp=2))
    a.guardar(_mem("La suite de pytest tarda 40 s con cobertura", tipo="test", imp=3))
    if emb is not None:
        for m in a.mem.values():
            a.guardar_vector(m.id, emb.embeber([m.contenido])[0])
    return a


# ------------------------------------------------------------------- tests

def test_i_decision_antigua_con_palabras_distintas_via_vectores():
    emb = EmbebedorFalso()
    a = _almacen_base(emb)
    r = Recuperador(a, pesos={}, embebedor=emb)
    res = r.buscar("qué motor de persistencia elegimos", task_id="t1", limite=3)
    assert res.via == "hibrido"
    assert res.memorias and "SQLite" in res.memorias[0].contenido
    assert res.explicaciones[res.memorias[0].id]["semantic"] > 0.5


def test_i_bis_sin_vectores_con_una_palabra_comun():
    a = _almacen_base()
    r = Recuperador(a, pesos={}, embebedor=EmbebedorFalso(devolver_none=True))
    res = r.buscar("qué base elegimos", task_id="t1", limite=3)
    assert res.via == "lexico"
    assert res.memorias and "SQLite" in res.memorias[0].contenido


def test_ii_distractor_mismo_vocabulario_queda_debajo():
    emb = EmbebedorFalso()
    a = _almacen_base(emb)
    d = _mem("nota temporal: base de datos SQLite mencionada de pasada", tipo="nota", imp=1,
             tags=["distractor"], confianza=0.3)
    a.guardar(d)
    a.guardar_vector(d.id, emb.embeber([d.contenido])[0])
    r = Recuperador(a, pesos={}, embebedor=emb)
    res = r.buscar("base de datos SQLite", task_id="t1", limite=5)
    ids = [m.id for m in res.memorias]
    assert ids.index(1) < ids.index(d.id)
    assert res.explicaciones[1]["score"] > res.explicaciones[d.id]["score"]


def test_iii_superada_solo_con_historial_y_cadena_completa():
    emb = EmbebedorFalso()
    a = _almacen_base(emb)
    nueva = _mem("Cambiamos la base de datos a PostgreSQL por concurrencia", entidad="base de datos",
                 valor="PostgreSQL")
    a.guardar(nueva)
    a.guardar_vector(nueva.id, emb.embeber([nueva.contenido])[0])
    a.superar(1, nueva.id)
    r = Recuperador(a, pesos={}, embebedor=emb)

    res = r.buscar("base de datos", task_id="t1", limite=5)
    ids = {m.id for m in res.memorias}
    assert nueva.id in ids and 1 not in ids
    assert res.explicaciones[nueva.id]["graph"] == 1.0  # vigente al final de la cadena

    res2 = r.buscar("historial de la base de datos, por qué cambió", task_id="t1", limite=5)
    ids2 = [m.id for m in res2.memorias]
    assert 1 in ids2 and nueva.id in ids2
    assert 0.0 < res2.explicaciones[1]["contradiction"] <= 1.0   # superada en cadena pedida: penalizada, no excluida
    assert res2.explicaciones[1]["obsolescence"] == 1.0
    assert res2.explicaciones[nueva.id]["contradiction"] == 0.0
    assert ids2.index(nueva.id) < ids2.index(1)  # la vigente primero por la penalización


def test_iv_presupuesto_tokens_corta():
    a = AlmacenFalso()
    for i in range(6):
        a.guardar(_mem(f"decisión {i} sobre la base de datos " + ("x" * 300), tokens=100))
    r = Recuperador(a, pesos={}, embebedor=EmbebedorFalso(devolver_none=True))
    res = r.buscar("base de datos", task_id="t1", limite=12, presupuesto_tokens=250)
    assert res.seleccionados == 2 and res.tokens == 200
    res_sin = r.buscar("base de datos", task_id="t1", limite=12)
    assert res_sin.seleccionados == 6
    # sin m.tokens se estima len/3.7
    b = AlmacenFalso()
    b.guardar(_mem("a" * 370))
    res_est = Recuperador(b, pesos={}, embebedor=EmbebedorFalso(True)).buscar("aaaa", limite=3)
    assert res_est.tokens == 0 or res_est.tokens == 100


def test_v_mmr_casi_identicas_no_entran_las_dos():
    a = AlmacenFalso()
    a.guardar(_mem("Decidimos usar SQLite como base de datos por simplicidad de despliegue"))
    a.guardar(_mem("Decidimos usar SQLite como base de datos por simplicidad de despliegue."))
    a.guardar(_mem("La base de datos se respalda cada noche a las 3", tipo="hecho", imp=3))
    a.guardar(_mem("Los tests de la base de datos usan un fichero temporal", tipo="test", imp=3))
    r = Recuperador(a, pesos={}, embebedor=EmbebedorFalso(True))
    res = r.buscar("base de datos", task_id="t1", limite=2)
    ids = {m.id for m in res.memorias}
    assert not ({1, 2} <= ids), "las dos casi idénticas entraron juntas"
    dup = 2 if 1 in ids else 1
    res3 = r.buscar("base de datos", task_id="t1", limite=4)
    assert res3.explicaciones[dup]["redundancy"] > 0.9
    assert res3.memorias[-1].id == dup  # la duplicada, la última


def test_vi_explicaciones_traen_10_senales_y_score():
    emb = EmbebedorFalso()
    a = _almacen_base(emb)
    r = Recuperador(a, pesos={}, embebedor=emb)
    res = r.buscar("base de datos", task_id="t1", limite=4, explicar=True)
    assert res.seleccionados >= 1
    for m in res.memorias:
        e = res.explicaciones[m.id]
        for s in SENALES:
            assert s in e and 0.0 <= e[s] <= 1.0, (s, e)
        assert "score" in e and isinstance(e["motivo"], str) and e["motivo"]
    sin = r.buscar("base de datos", task_id="t1", limite=4)
    assert "motivo" not in sin.explicaciones[sin.memorias[0].id]


def test_vii_embebedor_none_via_lexico_con_memorias():
    a = _almacen_base()
    emb = EmbebedorFalso(devolver_none=True)
    r = Recuperador(a, pesos={}, embebedor=emb)
    res = r.buscar("login JWT", task_id="t1", limite=3)
    assert res.via == "lexico" and res.memorias
    assert res.memorias[0].id == 2
    assert all(res.explicaciones[m.id]["semantic"] == 0.0 for m in res.memorias)
    assert "vector" not in a.llamadas


def test_viii_normalizar_y_cargar_pesos(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger="cognia.memoria_larga.reranker"):
        p = reranker.normalizar_pesos({"semantic": 0.9, "inventada": 3, "task": "no"})
    assert p["semantic"] == 0.9 and p["task"] == PESOS_DEFECTO["task"] and "inventada" not in p
    assert set(p) == set(PESOS_DEFECTO)
    assert "inventada" in caplog.text and "no numérico" in caplog.text

    roto = tmp_path / "pesos.json"
    roto.write_text("{ esto no es json", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="cognia.memoria_larga.reranker"):
        assert reranker.cargar_pesos(roto) == PESOS_DEFECTO
    assert "ilegible" in caplog.text
    assert reranker.cargar_pesos(tmp_path / "no_existe.json") == PESOS_DEFECTO
    bueno = tmp_path / "ok.json"
    bueno.write_text(json.dumps({"lexical": 0.5}), encoding="utf-8")
    assert reranker.cargar_pesos(bueno)["lexical"] == 0.5
    # puntuar es lineal en los pesos vigentes (los defaults se re-miden con el banco)
    assert reranker.puntuar({"semantic": 1.0, "redundancy": 1.0}, PESOS_DEFECTO) == pytest.approx(
        PESOS_DEFECTO["semantic"] + PESOS_DEFECTO["redundancy"])


# --- extras: sanitizado FTS, degradación, caché, grafo, ficheros

def test_terminos_consulta_sanitiza_fts():
    t = terminos_consulta('¿por qué "SQLite" (base:datos) -postgres* y el?')
    assert t == ["sqlite", "base", "datos", "postgres"]
    assert terminos_consulta("de la") == ["de", "la"]  # todo vacías → se usan igual


def test_bonus_and_todos_los_terminos():
    a = AlmacenFalso()
    a.guardar(_mem("la base de datos es SQLite", imp=3))
    a.guardar(_mem("una base sólida para el proyecto", imp=3))
    res = Recuperador(a, pesos={}, embebedor=EmbebedorFalso(True)).buscar("base datos", task_id="t1")
    assert res.memorias[0].id == 1
    assert res.explicaciones[1]["lexical"] == 1.0 and res.explicaciones[2]["lexical"] < 0.8


def test_degradacion_buscar_vector_lanza_y_todo_lanza(caplog):
    emb = EmbebedorFalso()
    a = _almacen_base(emb)

    def rompe(*a_, **k_):
        raise RuntimeError("tabla vectores ausente")
    a.buscar_vector = rompe
    r = Recuperador(a, pesos={}, embebedor=emb)
    with caplog.at_level(logging.WARNING):
        res = r.buscar("base de datos", task_id="t1")
    assert res.via == "lexico" and res.memorias
    assert "buscar_vector" in caplog.text

    class Roto:
        fts5 = True

        def __getattr__(self, n):
            raise RuntimeError("db cerrada")
    with caplog.at_level(logging.WARNING):
        res2 = Recuperador(Roto(), pesos={}, embebedor=EmbebedorFalso(True)).buscar("base")
    assert res2.via == "error" and res2.memorias == [] and res2.latencia_ms >= 0


def test_via_like_sin_fts():
    a = _almacen_base()
    a.fts5 = False
    res = Recuperador(a, pesos={}, embebedor=EmbebedorFalso(True)).buscar("base datos", task_id="t1")
    assert res.via == "like" and res.memorias


def test_cache_por_version_del_almacen():
    a = _almacen_base()
    r = Recuperador(a, pesos={}, embebedor=EmbebedorFalso(True))
    r1 = r.buscar("base de datos", task_id="t1")
    assert r.buscar("base de datos", task_id="t1") is r1
    a.guardar(_mem("otra base de datos nueva"))
    assert r.buscar("base de datos", task_id="t1") is not r1


def test_vectores_faltantes_se_calculan_y_guardan_una_vez():
    emb = EmbebedorFalso()
    a = _almacen_base()  # sin vectores
    r = Recuperador(a, pesos={}, embebedor=emb)
    res = r.buscar("motor de persistencia", task_id="t1")
    assert res.via == "hibrido" and len(a.vecs) == 4
    n = emb.llamadas
    r.invalidar_cache()
    r.buscar("motor de persistencia", task_id="t1")
    assert emb.llamadas == n + 1  # solo la consulta, no las memorias


def test_grafo_y_ficheros_abiertos():
    a = _almacen_base()
    err = _mem("Error: sqlite3.OperationalError database is locked", tipo="error")
    a.guardar(err)
    sol = _mem("Solución: activar WAL en la conexión", tipo="solucion", entidades=["cognia/almacen.py"])
    a.guardar(sol)
    a.relacionar(sol.id, err.id, "solves")
    r = Recuperador(a, pesos={}, embebedor=EmbebedorFalso(True))
    res = r.buscar("database is locked", task_id="t1", limite=5)
    ids = [m.id for m in res.memorias]
    assert err.id in ids and sol.id in ids
    assert res.explicaciones[sol.id]["graph"] == 1.0
    res2 = r.buscar("otra cosa sin relacion", task_id="t1", ficheros_abiertos=("cognia/almacen.py",))
    assert any(m.id == sol.id for m in res2.memorias)


# --- integración con el almacén real, si ya existe

@pytest.mark.skipif(importlib.util.find_spec("cognia.memoria_larga.almacen") is None,
                    reason="almacen.py aún no está escrito")
def test_integracion_almacen_real(tmp_path):
    from cognia.memoria_larga.almacen import Almacen
    a = Almacen(ruta_db=str(tmp_path / "m.db"))
    try:
        ids = [a.guardar(_mem("Decidimos usar SQLite como base de datos", edad_h=48)),
               a.guardar(_mem("El login usa JWT", tipo="hecho")),
               a.guardar(_mem("El botón es azul", tipo="nota", imp=2))]
        emb = EmbebedorFalso()
        r = Recuperador(a, pesos={}, embebedor=emb)
        res = r.buscar("qué motor de persistencia elegimos", task_id="t1", limite=3)
        assert res.via in ("hibrido", "lexico", "like"), res.via
        assert res.memorias and res.memorias[0].id == ids[0]
        for s in SENALES:
            assert s in res.explicaciones[ids[0]]
        res2 = Recuperador(a, pesos={}, embebedor=EmbebedorFalso(True)).buscar("login JWT", limite=2)
        assert res2.memorias and res2.memorias[0].id == ids[1]
    finally:
        a.cerrar()
