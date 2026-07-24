# -*- coding: utf-8 -*-
"""
Regresion del lazo generar -> probar -> puntuar (cognia/program_creator/verificacion.py).

POR QUE: medido el 2026-07-23 sobre la biblioteca real, de 56 productos solo 36
arrancaban y el peor (cognia_game) tenia un main.py con `print("hello")` al lado
del juego de verdad, guardado con nota de un juez LLM. Estos tests fijan las tres
propiedades del lazo: el bueno se sella verificado, el roto NO se sella y su
pedido de correccion NOMBRA el archivo y pega el error exacto, y el stub tampoco
pasa aunque corra con exit 0.

Los productos son de mentira y viven en tmp_path: nada toca la biblioteca real.
"""
import json
from pathlib import Path

import pytest

from cognia.program_creator.verificacion import (
    NOMBRE_SELLO,
    escribir_sello,
    leer_sello,
    reflejar_en_index,
    reintentar_si_falla,
    sellar_biblioteca,
    sello_de_calidad,
    verificar_al_crear,
)

BUENO = '''"""Contador de palabras de un texto fijo."""


def contar(texto):
    palabras = [p for p in texto.split() if p.strip()]
    conteo = {}
    for p in palabras:
        conteo[p] = conteo.get(p, 0) + 1
    return conteo


def formatear(conteo):
    filas = sorted(conteo.items(), key=lambda kv: -kv[1])
    return "\\n".join(f"{p}: {n}" for p, n in filas)


def main():
    print(formatear(contar("hola mundo hola cognia")))


if __name__ == "__main__":
    main()
'''

# SyntaxError real: falta el parentesis de cierre. Rompe en 'compila'.
ROTO = '''"""Sumador."""


def sumar(a, b):
    return a + b


print(sumar(1, 2)
'''

# El caso cognia_game literal: corre, exit 0, y no es nada.
STUB = 'print("hello")\n'


def _producto(base, nombre, contenido, extra=None):
    carpeta = Path(base) / nombre
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / "main.py").write_text(contenido, encoding="utf-8")
    for nom, txt in (extra or {}).items():
        (carpeta / nom).write_text(txt, encoding="utf-8")
    return carpeta


@pytest.fixture
def biblioteca(tmp_path):
    """Tres productos de mentira: uno bueno, uno roto y uno stub."""
    _producto(tmp_path, "producto_bueno", BUENO,
              {"README.md": "Cuenta palabras de un texto y las ordena por frecuencia."})
    _producto(tmp_path, "producto_roto", ROTO)
    _producto(tmp_path, "producto_stub", STUB)
    return tmp_path


# ── El bueno ───────────────────────────────────────────────────────────────────

def test_producto_bueno_se_verifica_y_no_pide_correccion(biblioteca):
    ver = verificar_al_crear(biblioteca / "producto_bueno")
    assert ver["ok"] is True, ver["motivos"]
    assert ver["fallo_duro"] is None
    assert ver["puntaje"] >= 6.0, ver["desglose"]

    sello = sello_de_calidad(ver)
    assert sello["verificado"] is True
    assert sello["puntaje_real"] == ver["puntaje"]
    assert sello["fecha"] and sello["motivos"]

    pedido = reintentar_si_falla(biblioteca / "producto_bueno", verificacion=ver)
    assert pedido["necesita_reintento"] is False
    assert pedido["pedido"] == ""


# ── El roto ────────────────────────────────────────────────────────────────────

def test_producto_roto_no_se_verifica(biblioteca):
    ver = verificar_al_crear(biblioteca / "producto_roto")
    assert ver["ok"] is False
    assert ver["fallo_duro"] == "compila"
    sello = sello_de_calidad(ver)
    assert sello["verificado"] is False
    assert sello["fallo_duro"] == "compila"


def test_pedido_de_correccion_del_roto_es_concreto(biblioteca):
    """El pedido tiene que servirle al generador: archivo + error literal + que se espera."""
    pedido = reintentar_si_falla(biblioteca / "producto_roto")
    assert pedido["necesita_reintento"] is True

    texto = pedido["pedido"]
    # NOMBRA el archivo...
    assert pedido["archivo"] == "main.py"
    assert "main.py" in texto
    # ...pega el error EXACTO (con numero de linea) ...
    assert "SyntaxError" in texto or "invalid syntax" in texto or "'('" in texto
    assert any(ch.isdigit() for ch in pedido["error"]), pedido["error"]
    # ...y dice que se espera.
    assert "QUE SE ESPERA" in texto
    assert pedido["que_se_espera"]
    # Nada de "arreglalo": tiene que citar la fase medida.
    assert "compila" in texto


def test_pedido_respeta_el_tope_de_intentos(biblioteca):
    agotado = reintentar_si_falla(biblioteca / "producto_roto", intento=4, max_intentos=3)
    assert agotado["necesita_reintento"] is False
    assert "agotados" in agotado["error"]


# ── El stub ────────────────────────────────────────────────────────────────────

def test_producto_stub_corre_pero_no_se_verifica(biblioteca):
    """print('hello') arranca con exit 0; el lazo igual lo tiene que rechazar."""
    ver = verificar_al_crear(biblioteca / "producto_stub")
    assert ver["resultado"]["fases"]["arranca"]["ok"] is True   # SI arranca
    assert ver["ok"] is False                                    # y aun asi no vale
    assert ver["stub_duro"] is True
    assert ver["fallo_duro"] == "stubs"

    pedido = reintentar_si_falla(biblioteca / "producto_stub", verificacion=ver)
    assert pedido["necesita_reintento"] is True
    assert "main.py" in pedido["pedido"]
    assert "placeholder" in pedido["que_se_espera"] or "DE VERDAD" in pedido["que_se_espera"]


# ── Sello en disco ─────────────────────────────────────────────────────────────

def test_escribir_y_leer_sello(biblioteca):
    carpeta = biblioteca / "producto_bueno"
    ruta = escribir_sello(carpeta, sello_de_calidad(verificar_al_crear(carpeta)))
    assert ruta and Path(ruta).name == NOMBRE_SELLO
    guardado = leer_sello(carpeta)
    assert guardado["verificado"] is True
    assert set(("verificado", "puntaje_real", "fecha", "motivos")) <= set(guardado)


def test_sellar_biblioteca_sella_todo_y_es_idempotente(biblioteca):
    rep1 = sellar_biblioteca(base=biblioteca)
    assert rep1["total"] == 3
    assert rep1["escritos"] == 3
    assert rep1["verificados"] == 1              # solo el bueno
    assert rep1["no_verificados"] == 2
    assert rep1["errores"] == []

    veredictos = {s["id"]: s["verificado"] for s in rep1["sellos"]}
    assert veredictos == {"producto_bueno": True, "producto_roto": False,
                          "producto_stub": False}

    # Idempotente: segunda pasada, mismos veredictos y un solo archivo por producto.
    rep2 = sellar_biblioteca(base=biblioteca)
    assert {s["id"]: s["verificado"] for s in rep2["sellos"]} == veredictos
    for nombre in veredictos:
        assert len(list((biblioteca / nombre).glob("*.json"))) == 1
        assert not list((biblioteca / nombre).glob(".sello_*.tmp"))


def test_sellar_biblioteca_respeta_el_limite(biblioteca):
    rep = sellar_biblioteca(limite=1, base=biblioteca)
    assert rep["total"] == 1


def test_reflejar_en_index_agrega_sin_pisar_el_juez(biblioteca):
    """El total_score del juez LLM se queda; al lado aparece el puntaje medido."""
    index = biblioteca / "index.json"
    index.write_text(json.dumps([
        {"id": "producto_stub", "directory": "producto_stub", "title": "Stub",
         "total_score": 9.0},
    ]), encoding="utf-8")

    rep = sellar_biblioteca(base=biblioteca)
    assert rep["index_actualizado"] == 1

    entrada = json.loads(index.read_text(encoding="utf-8"))[0]
    assert entrada["total_score"] == 9.0        # lo que opino el juez: intacto
    assert entrada["verificado"] is False       # lo que se midio corriendolo
    assert entrada["puntaje_real"] < 9.0
    assert entrada["verificado_en"]


def test_pedido_de_una_pagina_no_pide_correrla_con_python(tmp_path):
    """
    21 de los 56 productos reales son paginas. La primera corrida sobre
    dashboard_de_inversiones devolvia 'que `python index.html` corra sin
    Traceback', un pedido sin sentido: a una pagina se la mide con revisar_html.
    """
    carpeta = tmp_path / "pagina_rota"
    carpeta.mkdir()
    (carpeta / "index.html").write_text(
        "<html><head><title>P</title>"
        "<script src='http://cdn.example.com/chart.js'></script></head>"
        "<body><div id='x'></div></body></html>", encoding="utf-8")

    pedido = reintentar_si_falla(carpeta)
    assert pedido["necesita_reintento"] is True
    assert pedido["archivo"] == "index.html"
    assert "python index.html" not in pedido["pedido"]
    assert "EMBEBIDOS" in pedido["que_se_espera"] or "HTML completo" in pedido["que_se_espera"]
    assert "http://" in pedido["error"] or "revisar_html" in pedido["error"]


def test_index_sellado_no_hace_desaparecer_programas(biblioteca):
    """
    Regresion medida el 2026-07-23: al reflejar el sello, storage.list_programs()
    tiraba la entrada entera (`except TypeError: continue`) por las claves nuevas.
    En la biblioteca real get_program_count() decia 53 y list_programs() 48.
    """
    from cognia.program_creator.storage import get_program_count, list_programs

    index = biblioteca / "index.json"
    index.write_text(json.dumps([
        {"id": "producto_bueno", "title": "Bueno", "category": "utility",
         "description": "cuenta palabras", "total_score": 7.0,
         "created_at": "2026-07-23T00:00:00", "directory": "producto_bueno"},
    ]), encoding="utf-8")

    assert len(list_programs(biblioteca)) == get_program_count(biblioteca) == 1
    sellar_biblioteca(base=biblioteca)
    programas = list_programs(biblioteca)
    assert len(programas) == get_program_count(biblioteca) == 1
    assert programas[0].verificado is True
    assert programas[0].total_score == 7.0        # el juez no se pisa
    assert programas[0].puntaje_real >= 6.0

    # Y una clave completamente desconocida tampoco borra la entrada.
    entradas = json.loads(index.read_text(encoding="utf-8"))
    entradas[0]["campo_del_futuro"] = 42
    index.write_text(json.dumps(entradas), encoding="utf-8")
    assert len(list_programs(biblioteca)) == 1


def test_directorio_inexistente_no_explota(tmp_path):
    ver = verificar_al_crear(tmp_path / "no_existe")
    assert ver["ok"] is False
    assert ver["fallo_duro"] == "sin_producto"
    assert reintentar_si_falla(tmp_path / "no_existe", verificacion=ver)["necesita_reintento"]
