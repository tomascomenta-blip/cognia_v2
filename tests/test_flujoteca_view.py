# -*- coding: utf-8 -*-
"""
tests/test_flujoteca_view.py
============================
Tests del visor de flujos con historial (cognia/agent/flujoteca_view.py).

POR QUE ESTE FICHERO EXISTE (2026-08-29)
----------------------------------------
Hasta hoy `flujoteca_view.py` tenia CERO tests: 286 lineas, ~109 de ellas de
JavaScript, generando el HTML que abre `/flujoteca abrir`. Era la unica pieza
de la cadena de flujos sin red. Y es la que embebe datos del dueno dentro de
un `<script>`: si el escapado de "</" se rompe, el fallo no se ve (la pagina
"casi" funciona) y se lleva por delante la vista entera.

REGLA CRITICA, igual que en tests/test_flujoteca.py: la fixture que mueve
COGNIA_FLUJOTECA_DIR es AUTOUSE. `build_datos` LEE la biblioteca real del
dueno si no se aisla, y un test que guarde un flujo de prueba se lo dejaria
puesto en ~/.cognia/flujoteca.
"""
from __future__ import annotations

import json

import pytest

from cognia.agent import flujoteca as ft
from cognia.agent import flujoteca_view as fv


@pytest.fixture(autouse=True)
def biblioteca(tmp_path, monkeypatch):
    """La biblioteca ENTERA a tmp_path. Autouse por seguridad."""
    d = tmp_path / "flujoteca"
    monkeypatch.setenv("COGNIA_FLUJOTECA_DIR", str(d))
    return d


def flujo(nombre="Informe diario", args="tendencias IA 2026"):
    return {"nombre": nombre, "nodos": [
        {"id": "hallar", "tool": "buscar", "args": args, "wires": ["guardar"]},
        {"id": "guardar", "tool": "escribir_archivo",
         "args": "informe.md\n{{hallar}}", "wires": []}]}


# ---------------------------------------------------------------------------
# El HTML
# ---------------------------------------------------------------------------

def test_render_sin_cdn():
    """Autocontenido: ni una peticion a la red. La vista tiene que abrir en
    una maquina sin internet y sin que nadie de fuera sepa que se abrio."""
    ft.guardar(flujo(), nota="inicial")
    h = fv.render_html(fv.build_datos("Informe diario"))

    assert "<svg" not in h or True          # el SVG lo pinta el JS
    assert "buscar" in h and "escribir_archivo" in h
    assert "http://" not in h and "https://" not in h
    assert "<script src" not in h and "<link" not in h
    assert "cdn" not in h.lower()


def test_escape_de_cierre_de_script():
    """Un args con "</script>" no puede cerrar el <script> que lo contiene.

    json.dumps NO escapa "</": el navegador cierra la etiqueta aunque este
    dentro de una cadena JS. Sin escapar, un flujo con esos seis caracteres
    deja la pagina en blanco.
    """
    ft.guardar(flujo(args="</script><b>x"), nota="con veneno")
    h = fv.render_html(fv.build_datos("Informe diario"))

    assert "\\u003c/script" in h, "el cierre de etiqueta no se escapo"
    assert "</script><b>x" not in h
    # y solo queda el cierre de verdad del bloque <script> de la plantilla
    assert h.count("</script>") == 1


def test_un_comentario_html_en_los_datos_tampoco_mata_la_pagina():
    """MEDIDO en Chromium (2026-08-29): escapar solo "</" NO basta.

    "<!--" y "<script" meten al tokenizador en 'script data escaped', y en ese
    estado el </script> de la plantilla YA NO CIERRA el bloque: se traga el
    resto del documento, el JS muere por error de sintaxis y la pagina queda
    con la barra pintada y CERO nodos -- se lee como "un flujo vacio", no como
    "una pagina rota". Y el dato que lo dispara es normal: un flujo que
    escribe una pagina HTML con escribir_archivo.
    """
    veneno = "pagina.html | <!--<script>alert(1)</script>-- fin"
    ft.guardar(flujo(args=veneno), nota="escribe una pagina")
    h = fv.render_html(fv.build_datos("Informe diario"))

    assert "<!--" not in h and "<script>alert" not in h
    assert "\\u003c!--\\u003cscript>" in h, "el '<' es el que hay que escapar"
    # el unico "<script" del documento es el de la plantilla, y cierra una vez
    assert h.count("<script>") == 1 and h.count("</script>") == 1

    # y el dato NO se altera: \u003c es el mismo caracter para JSON y para JS
    datos = json.loads(h.split("const D = ")[1].split(";\n")[0])
    args = [n["args"] for v in datos["versiones"] for n in v["flujo"]["nodos"]]
    assert veneno in args


def test_el_nombre_del_flujo_no_puede_reclamar_el_hueco_de_los_datos():
    """Los dos huecos se rellenan DE UNA PASADA. Encadenar .replace() dejaba
    que lo puesto primero (el titulo, que lleva dato del dueno) fuera
    reinterpretado despues: un flujo llamado "__DATA__" se llevaba el JSON
    entero dentro del <title>."""
    ft.guardar(flujo(nombre="__DATA__"), nota="x")
    h = fv.render_html(fv.build_datos("__DATA__"))

    titulo = h.split("<title>")[1].split("</title>")[0]
    assert titulo.endswith("__DATA__")
    assert "versiones" not in titulo and "nodos" not in titulo
    assert h.count("const D = {") == 1


def test_el_titulo_tampoco_puede_cerrar_su_etiqueta():
    """El nombre del flujo viaja al <title>: se escapa como HTML, no como JS."""
    ft.guardar(flujo(nombre="malo </title><img>"), nota="x")
    h = fv.render_html(fv.build_datos("malo </title><img>"))

    assert "</title><img>" not in h
    assert "&lt;/title&gt;" in h
    assert h.count("</title>") == 1


def test_el_pie_apunta_al_editor_visual():
    """El visor es el FALLBACK de solo lectura; quien llega aqui tiene que
    saber por donde se edita de verdad."""
    ft.guardar(flujo(), nota="x")
    h = fv.render_html(fv.build_datos("Informe diario"))

    assert "/flujoteca editor" in h


# ---------------------------------------------------------------------------
# build_datos
# ---------------------------------------------------------------------------

def test_build_datos_flujo_inexistente_no_explota():
    """Sin flujo no hay error: hay cero versiones. Un visor que lanza deja al
    dueno sin saber si el flujo no existe o si la vista esta rota."""
    datos = fv.build_datos("este flujo no existe")

    assert datos["nombre"] == "este flujo no existe"
    assert datos["versiones"] == []
    assert datos["descripcion"] == ""
    assert datos["ui"] == {"pos": {}}
    # y el HTML se puede pintar igual
    assert "<html" in fv.render_html(datos)


def test_build_datos_emite_ui_pos():
    """Las posiciones manuales salen en los datos Y mandan en el layout.

    Si el visor de solo lectura y el editor pintaran layouts distintos para
    el mismo flujo, el dueno veria su flujo "descolocado" cada vez que abre
    el fallback, y no habria forma de saber cual de las dos vistas miente.
    """
    ft.guardar(flujo(), nota="inicial")
    ft.guardar_ui("Informe diario",
                  {"pos": {"hallar": {"x": 700, "y": 320}}})

    datos = fv.build_datos("Informe diario")

    assert datos["ui"]["pos"]["hallar"] == {"x": 700, "y": 320}
    cajas = {c["id"]: c for c in datos["versiones"][0]["layout"]["cajas"]}
    assert (cajas["hallar"]["x"], cajas["hallar"]["y"]) == (700, 320)
    assert cajas["hallar"]["pos_manual"] is True
    assert cajas["guardar"]["pos_manual"] is False


def test_build_datos_emite_el_flujo_crudo_por_version():
    """El editor no puede reconstruir el flujo desde el layout: el layout no
    dibuja saltar_si, reintentos ni timeout_s, y guardar manda el DAG entero.
    """
    f = flujo()
    f["nodos"][1]["saltar_si"] = "ERROR"
    f["nodos"][1]["reintentos"] = 2
    ft.guardar(f, nota="con opcionales")

    v = fv.build_datos("Informe diario")["versiones"][0]

    assert v["flujo"]["nombre"] == "Informe diario"
    # el nodo de ENTRADA va delante: desde el PEDIDO 3 (2026-08-29)
    # `flujoteca.guardar` llama a `flows.asegurar_prompt`, asi que todo flujo
    # de la biblioteca sale con su `prompt` al inicio, cableado a las raices
    assert [n["id"] for n in v["flujo"]["nodos"]] == [
        "prompt", "hallar", "guardar"]
    assert v["flujo"]["nodos"][0]["tool"] == "prompt"
    assert v["flujo"]["nodos"][0]["wires"] == ["hallar"]
    guardar = v["flujo"]["nodos"][-1]
    assert guardar["saltar_si"] == "ERROR"
    assert guardar["reintentos"] == 2


def test_build_datos_sin_catalogo_por_defecto():
    """El visor se abre por file:// y no habla con nadie: embeber 133 tools
    solo engordaria el HTML."""
    ft.guardar(flujo(), nota="x")
    datos = fv.build_datos("Informe diario")

    assert "catalogo" not in datos


def test_build_datos_con_catalogo_roto_degrada_con_motivo(monkeypatch):
    """Si el catalogo de nodos falla (o aun no esta implementado), la vista
    sigue abriendo y el motivo se DICE. Un catalogo vacio sin explicacion es
    el modo de fallo silencioso de la casa."""
    from cognia.agent import catalogo_nodos as cn

    def _explota(allowed=None):
        raise NotImplementedError("todavia no")

    monkeypatch.setattr(cn, "catalogo", _explota)
    ft.guardar(flujo(), nota="x")

    datos = fv.build_datos("Informe diario", con_catalogo=True)

    assert datos["catalogo"] == []
    assert "NotImplementedError" in datos["catalogo_motivo"]
    assert datos["versiones"], "el flujo se sigue viendo sin catalogo"


def test_build_datos_con_catalogo_lo_incluye(monkeypatch):
    from cognia.agent import catalogo_nodos as cn

    monkeypatch.setattr(cn, "catalogo",
                        lambda allowed=None: [{"nombre": "buscar",
                                               "categoria": "lectura"}])
    ft.guardar(flujo(), nota="x")

    datos = fv.build_datos("Informe diario", con_catalogo=True)

    assert datos["catalogo"] == [{"nombre": "buscar", "categoria": "lectura"}]
    assert "catalogo_motivo" not in datos


def test_los_datos_son_json_serializables():
    """Lo que no se pueda volcar a JSON no llega al navegador: mejor que lo
    diga un test que un HTML a medio escribir."""
    ft.guardar(flujo(), nota="x")
    crudo = json.dumps(fv.build_datos("Informe diario"), ensure_ascii=False)

    assert "Informe diario" in crudo


# ---------------------------------------------------------------------------
# export()
# ---------------------------------------------------------------------------

def test_export_respeta_open_browser(tmp_path, monkeypatch):
    import webbrowser

    abiertos = []
    monkeypatch.setattr(webbrowser, "open", lambda u: abiertos.append(u))
    ft.guardar(flujo(), nota="x")
    destino = tmp_path / "vista.html"

    ruta = fv.export("Informe diario", str(destino), open_browser=False)

    assert ruta == str(destino)
    assert destino.read_text(encoding="utf-8").startswith("<!doctype html>")
    assert abiertos == []
