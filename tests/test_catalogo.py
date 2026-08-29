# -*- coding: utf-8 -*-
"""Tests del catalogo unificado de artefactos (cognia/memory/catalogo.py).

El test que importa es `test_bytes_de_no_recorre_el_repo_con_ruta_vacia`: es
la regresion del bug que hacia el catalogo inservible. `_leer_skills` leia
`spec.path` (campo que SkillSpec no tiene) con default "", `Path("")` resuelve
al cwd, y `_bytes_de` se ponia a rglob el repositorio entero una vez por
skill. Medido antes del fix: 44,9 s de los 46 s totales. Despues: 0,17 s.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from cognia.memory import catalogo as C


# --------------------------------------------------------------- _iso

def test_iso_normaliza_los_tres_formatos_del_repo():
    """ISO, epoch float y epoch int conviven en las fuentes; el catalogo los
    unifica o el dashboard ordena por fecha al azar."""
    assert C._iso("2026-08-28T10:11:12") == "2026-08-28T10:11:12"
    assert C._iso("2026-08-28T10:11:12.987654").startswith("2026-08-28T10:11:12")
    epoch = C._iso(1756000000)
    assert epoch.startswith("20") and "T" in epoch
    # epoch en MILISEGUNDOS: se detecta por magnitud y da la misma fecha
    assert C._iso(1756000000000)[:10] == epoch[:10]
    assert C._iso(None) == ""
    assert C._iso("") == ""
    assert C._iso(0) == ""


def test_iso_no_lanza_con_basura():
    for basura in ("no es una fecha", -1, 9.9e18, [], {}):
        assert isinstance(C._iso(basura), str)


# ------------------------------------------------------------- _bytes_de

def test_bytes_de_no_recorre_el_repo_con_ruta_vacia(tmp_path, monkeypatch):
    """REGRESION. Con ruta vacia, `Path("")` es el cwd: sin la guarda esto
    recorria el repositorio entero (44,9 s medidos). Se comprueba por
    CONTRATO (devuelve 0) y por TIEMPO (no toca el disco)."""
    hondo = tmp_path / "a" / "b" / "c"
    hondo.mkdir(parents=True)
    for i in range(50):
        (hondo / f"f{i}.txt").write_text("x" * 100, encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    inicio = time.monotonic()
    assert C._bytes_de("") == 0
    assert C._bytes_de(None) == 0
    assert C._bytes_de(".") == 0
    assert C._bytes_de("..") == 0
    # Sin la guarda estas cuatro llamadas habrian sumado 5.000 bytes reales
    # recorriendo el arbol; con ella ni lo miran.
    assert time.monotonic() - inicio < 1.0


def test_bytes_de_fichero_y_directorio(tmp_path):
    f = tmp_path / "uno.txt"
    f.write_text("x" * 123, encoding="utf-8")
    assert C._bytes_de(f) == 123
    d = tmp_path / "carpeta"
    d.mkdir()
    (d / "a.txt").write_text("y" * 10, encoding="utf-8")
    (d / "b.txt").write_text("z" * 20, encoding="utf-8")
    assert C._bytes_de(d) == 30
    assert C._bytes_de(tmp_path / "no_existe") == 0


def test_bytes_de_acota_el_recorrido(tmp_path, monkeypatch):
    """El tope existe para que una ruta inesperada no congele el REPL: se
    devuelve un numero aproximado, nunca un cuelgue."""
    monkeypatch.setattr(C, "_TOPE_ENTRADAS_DIR", 5)
    d = tmp_path / "muchos"
    d.mkdir()
    for i in range(40):
        (d / f"f{i}.txt").write_text("x" * 100, encoding="utf-8")
    total = C._bytes_de(d)
    assert 0 < total <= 5 * 100      # corto en el tope, no sumo los 4.000


# --------------------------------------------------------------- construir

def test_construir_nunca_lanza_y_reporta_la_familia_rota(monkeypatch):
    """Una familia que revienta NO puede verse igual que una familia vacia.
    Es la regla dura del repo: 'no lo cablearon' y 'se rompio' distintos."""
    def _explota(avisos):
        raise RuntimeError("indice corrupto")

    monkeypatch.setitem(C._LECTORES, "programa", _explota)
    cat = C.construir(familias=["programa", "documento"])
    assert "programa" in cat.familias_fallidas
    assert "programa" not in cat.familias_ok
    assert any("programa" in a and "indice corrupto" in a for a in cat.avisos)
    # y el resto del catalogo sigue construyendose
    assert "documento" in cat.familias_ok


def test_construir_familia_vacia_no_es_familia_rota(monkeypatch):
    monkeypatch.setitem(C._LECTORES, "programa", lambda avisos: [])
    cat = C.construir(familias=["programa"])
    assert cat.familias_ok == ["programa"]
    assert cat.familias_fallidas == []
    assert cat.avisos == []


def test_construir_respeta_el_limite_por_familia(monkeypatch):
    filas = [C.Fila(id=str(i), familia="programa", titulo=f"p{i}")
             for i in range(20)]
    monkeypatch.setitem(C._LECTORES, "programa", lambda avisos: list(filas))
    cat = C.construir(familias=["programa"], limite_por_familia=3)
    assert len(cat.filas) == 3


def test_construir_ignora_familias_desconocidas():
    cat = C.construir(familias=["no_existe_esta_familia"])
    assert cat.filas == []
    assert cat.familias_ok == []


def test_familias_disponibles_tienen_lector():
    for fam in C.familias_disponibles():
        assert fam in C._LECTORES
        assert fam in C.FAMILIAS


# ----------------------------------------------------------------- buscar

def _cat_de_prueba():
    cat = C.Catalogo()
    cat.filas = [
        C.Fila(id="1", familia="programa", titulo="Hola en 3 Palabras",
               resumen="imprime un saludo corto", modificado="2026-08-17T23:51:11"),
        C.Fila(id="2", familia="skill", titulo="formatea-red-terminal",
               resumen="colorea la red en la terminal",
               modificado="2026-08-20T10:00:00"),
        C.Fila(id="3", familia="flujo", titulo="crea fichero texto",
               resumen="crea un fichero y escribe dentro",
               modificado="2026-08-01T10:00:00"),
    ]
    return cat


def test_buscar_encuentra_por_titulo_y_resumen():
    cat = _cat_de_prueba()
    r = C.buscar(cat, "saludo corto palabras", minimo=1)
    assert r and r[0].id == "1"


def test_buscar_minimo_filtra_el_ruido():
    """minimo=2 es lo que usa el mejorador: con una sola palabra comun
    entraria cualquier cosa y el contexto se llenaria de basura, que es
    exactamente lo que la mision prohibe."""
    cat = _cat_de_prueba()
    assert C.buscar(cat, "fichero", minimo=2) == []
    assert len(C.buscar(cat, "crea fichero texto", minimo=2)) == 1


def test_buscar_sin_palabras_utiles_devuelve_vacio():
    cat = _cat_de_prueba()
    assert C.buscar(cat, "de la que el en y a") == []
    assert C.buscar(cat, "") == []


def test_buscar_filtra_por_familia():
    cat = _cat_de_prueba()
    r = C.buscar(cat, "terminal red colorea", familias=["programa"], minimo=1)
    assert r == []
    r = C.buscar(cat, "terminal red colorea", familias=["skill"], minimo=1)
    assert len(r) == 1


def test_buscar_respeta_el_tope():
    cat = _cat_de_prueba()
    assert len(C.buscar(cat, "crea un fichero texto saludo corto palabras "
                             "terminal red", tope=2, minimo=1)) <= 2


# ------------------------------------------------------- forma de la fila

def test_fila_a_dict_no_comparte_listas():
    """a_dict() copia las listas: el dashboard serializa el dict y no puede
    quedarse con referencias vivas a la fila."""
    f = C.Fila(id="1", familia="skill", titulo="t", etiquetas=["a"])
    d = f.a_dict()
    d["etiquetas"].append("b")
    assert f.etiquetas == ["a"]


def test_catalogo_a_dict_es_serializable():
    cat = _cat_de_prueba()
    texto = json.dumps(cat.a_dict(), ensure_ascii=False)
    vuelto = json.loads(texto)
    assert vuelto["conteo"] == {"programa": 1, "skill": 1, "flujo": 1}


# --------------------------------------------------- humo contra el disco real

def test_catalogo_real_es_rapido_y_no_falla():
    """Humo de punta a punta contra las fuentes REALES de la maquina.

    El tope de 10 s no es cosmetico: esto lo llama el mejorador de prompts
    entre el Enter del usuario y el envio al modelo. Si vuelve a aparecer un
    recorrido no acotado, este test lo caza aunque el bug este en otra
    familia. (Medido tras el fix: 0,17 s.)
    """
    inicio = time.monotonic()
    cat = C.construir()
    tardo = time.monotonic() - inicio
    assert tardo < 10.0, f"el catalogo tardo {tardo:.1f}s: hay un recorrido sin acotar"
    assert cat.familias_ok, "ninguna familia se pudo leer"
    for fila in cat.filas:
        assert fila.familia in C.FAMILIAS
        assert isinstance(fila.id, str) and fila.id
        assert isinstance(fila.titulo, str)
