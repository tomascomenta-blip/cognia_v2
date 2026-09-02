# -*- coding: utf-8 -*-
"""El LAZO CORTO (2026-09-01): lo que el agente escribe se corre en el acto.

Antes, la unica ejecucion del producto vivia en el cierre del turno, y en una
tarea larga el cierre no llega (reloj o presupuesto la matan antes). Medido con
el banco: un tablero kanban de 30 KB con README impecable y `window.KANBAN` sin
definir, porque el agente nunca abrio la pagina.

Estos tests fijan tres cosas:
  1. el lazo distingue un fichero sano de uno roto, en las tres familias;
  2. comprueba el CONTRATO que el encargo declara (window.X, X.metodo(), ...);
  3. no revienta nunca y calla cuando el fichero no es arrancable.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cognia.harness import contrato_tarea as ct
from cognia.harness import lazo_corto as lz

REPO = Path(__file__).resolve().parent.parent


def _prompt(nombre):
    p = REPO / "banco_largo" / "tareas" / nombre
    if not p.exists():
        pytest.skip("sin el banco de tareas largas")
    return json.loads(p.read_text(encoding="utf-8"))["prompt"]


# -- identificadores del encargo ----------------------------------------------

def test_identificadores_sacan_la_interfaz_declarada():
    ids = ct.identificadores(_prompt("juego_tower_defense.json"))
    assert ids["globales"] == ["JUEGO"]
    assert "iniciarOleada" in ids["metodos"]["JUEGO"]
    assert "tick" in ids["metodos"]["JUEGO"]


def test_identificadores_vacios_sin_interfaz():
    ids = ct.identificadores("Crea saluda.py que imprima hola y ejecutalo.")
    assert ids == {"globales": [], "metodos": {}, "dom_ids": [], "funciones": []}


def test_identificadores_dom_y_funciones():
    ids = ct.identificadores(
        'Un boton con id="enviar" y un div id="salida". Expon `calcular(` y '
        'la funcion validar(email).')
    assert ids["dom_ids"] == ["enviar", "salida"]
    assert "calcular" in ids["funciones"]
    assert "validar" in ids["funciones"]


# -- que es arrancable ----------------------------------------------------------

@pytest.mark.parametrize("ruta,esperado", [
    ("index.html", "html"), ("juego.htm", "html"), ("app.py", "py"),
    ("main.js", "js"), ("mod.mjs", "js"), ("README.md", ""), ("datos.json", ""),
    ("test_app.py", ""), ("conftest.py", ""), ("app_test.py", ""),
])
def test_es_arrancable(ruta, esperado):
    assert lz.es_arrancable(ruta) == esperado


# -- Python ----------------------------------------------------------------------

def test_py_roto_al_importar_se_reporta_con_la_linea(tmp_path):
    f = tmp_path / "mod.py"
    f.write_text("import os\nx = nombre_inexistente + 1\n", encoding="utf-8")
    r = lz.comprobar_py(f, tmp_path)
    assert r["corrio"] is True and r["ok"] is False
    assert "NameError" in r["detalle"]
    assert "line 2" in r["detalle"]


def test_py_que_no_compila(tmp_path):
    f = tmp_path / "mod.py"
    f.write_text("def f(:\n    pass\n", encoding="utf-8")
    r = lz.comprobar_py(f, tmp_path)
    assert r["ok"] is False and "NO compila" in r["detalle"]


def test_py_sano_con_guarda_main_no_se_ejecuta(tmp_path):
    marca = tmp_path / "corrio.txt"
    f = tmp_path / "app.py"
    f.write_text("def suma(a, b):\n    return a + b\n\nif __name__ == '__main__':\n"
                 "    open(%r, 'w').write('x')\n" % str(marca), encoding="utf-8")
    r = lz.comprobar_py(f, tmp_path)
    assert r["ok"] is True
    assert not marca.exists(), "el lazo corto importa, no ejecuta el main"


def test_py_que_bloquea_no_cuelga_el_lazo(tmp_path, monkeypatch):
    monkeypatch.setattr(lz, "TIMEOUT_IMPORT_S", 1.5)
    f = tmp_path / "servidor.py"
    f.write_text("import time\nwhile True:\n    time.sleep(0.2)\n", encoding="utf-8")
    r = lz.comprobar_py(f, tmp_path)
    assert r["corrio"] is False
    assert "tardo mas" in r["detalle"]


# -- JS ------------------------------------------------------------------------

def test_js_sintaxis(tmp_path):
    import shutil
    if not shutil.which("node"):
        pytest.skip("sin node")
    roto = tmp_path / "a.js"
    roto.write_text("function f( {", encoding="utf-8")
    sano = tmp_path / "b.js"
    sano.write_text("function f() { return 1; }", encoding="utf-8")
    assert lz.comprobar_js(roto)["ok"] is False
    assert lz.comprobar_js(sano)["ok"] is True


# -- HTML: navegador real ----------------------------------------------------------

def _hay_playwright():
    try:
        import playwright  # noqa: F401
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _hay_playwright(), reason="sin Playwright")
def test_html_roto_y_contrato_ausente(tmp_path):
    f = tmp_path / "index.html"
    f.write_text("<canvas id='c'></canvas><script>window.JUEGO={oro:1};noExiste();</script>",
                 encoding="utf-8")
    ids = {"globales": ["JUEGO"], "metodos": {"JUEGO": ["tick", "guardar"]}, "dom_ids": ["hud"]}
    r = lz.comprobar_html(f, ids)
    assert r["corrio"] is True and r["ok"] is False
    assert any("noExiste" in e for e in r["errores"])
    assert "JUEGO.tick" in r["faltan"] and "JUEGO.guardar" in r["faltan"]
    assert "#hud" in r["faltan"]


@pytest.mark.skipif(not _hay_playwright(), reason="sin Playwright")
def test_html_sano_con_contrato_expuesto(tmp_path):
    f = tmp_path / "index.html"
    f.write_text("<canvas id='c' width='40' height='40'></canvas><div id='hud'></div>"
                 "<script>const g=document.getElementById('c').getContext('2d');"
                 "g.fillStyle='#f00';g.fillRect(0,0,10,10);"
                 "window.JUEGO={tick(){},guardar(){}};</script>", encoding="utf-8")
    # sin 'tick' en el contrato: este test mide que la interfaz este expuesta,
    # no que la simulacion avance (eso lo mide test_lazo_corto_tick.py)
    ids = {"globales": ["JUEGO"], "metodos": {"JUEGO": ["guardar"]}, "dom_ids": ["hud"]}
    r = lz.comprobar_html(f, ids)
    assert r["corrio"] is True and r["ok"] is True, r
    assert "contrato" in r["detalle"]


# -- punto de entrada --------------------------------------------------------------

def test_tras_escritura_calla_con_prosa_y_nunca_lanza(tmp_path):
    md = tmp_path / "README.md"
    md.write_text("# hola", encoding="utf-8")
    assert lz.tras_escritura(md, forzar=True) is None
    assert lz.tras_escritura(tmp_path / "no_existe.py", forzar=True) is None
    assert lz.tras_escritura(None, forzar=True) is None


def test_tras_escritura_respeta_el_intervalo(tmp_path, monkeypatch):
    f = tmp_path / "a.py"
    f.write_text("x = 1\n", encoding="utf-8")
    lz._ultima.clear()
    assert lz.tras_escritura(f, raiz=tmp_path) is not None
    # la segunda comprobacion inmediata del MISMO fichero se salta
    assert lz.tras_escritura(f, raiz=tmp_path) is None
    assert lz.tras_escritura(f, raiz=tmp_path, forzar=True) is not None


def test_apagado_por_entorno(tmp_path, monkeypatch):
    monkeypatch.setenv(lz.ENV, "0")
    f = tmp_path / "a.py"
    f.write_text("x = nombre_inexistente\n", encoding="utf-8")
    assert lz.tras_escritura(f, raiz=tmp_path, forzar=True) is None
