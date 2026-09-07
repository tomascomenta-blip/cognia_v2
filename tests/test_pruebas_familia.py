# -*- coding: utf-8 -*-
"""
tests/test_pruebas_familia.py
=============================
La FAMILIA DE PRUEBAS (2026-09-07, cognia/agent/pruebas_tools.py): cableado en
el registro, la puerta `probar` (despacho por tipo), `probar ayuda`, el
catalogo/familias/ayuda del CLI y las regresiones del helper pruebas_comun
cazadas en los e2e de esta entrega:

  - partir_args dejaba una comilla colgando en `python "C:\\ruta con espacios\\x.py"`
  - resumen_imagen llamaba "casi blanca" a una pagina con texto
  - resolver_ruta no miraba el scratchpad de la tarea
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from cognia.agent import pruebas_comun as PC
from cognia.agent import pruebas_tools as PT
from cognia.agent import tools as T


def _ctx(tmp_path):
    return {"_scratchpad": str(tmp_path), "workspace": str(tmp_path),
            "confirm": lambda *a, **k: True}


# ── cableado ─────────────────────────────────────────────────────────────────

def test_familia_encendida_por_defecto_y_probar_en_el_core():
    assert os.environ.get("COGNIA_PRUEBAS") == "1"
    assert "probar" in T.CORE_TOOLS
    assert "probar" in T.TOOLS and "pruebas_estado" in T.TOOLS
    assert T.flag_de_optin("probar") == "COGNIA_PRUEBAS"
    assert T.flag_de_optin("pagina_abrir") == "COGNIA_PRUEBAS"
    assert T.flag_de_optin("app_probar") == "COGNIA_PRUEBAS"
    # py_ NO es prefijo de la familia: py_validar es del core y no lleva flag
    assert T.flag_de_optin("py_validar") == ""
    assert T.flag_de_optin("py_lint") == "COGNIA_PRUEBAS"


def test_las_cinco_subfamilias_cargaron():
    est = PT.estado()["carga"]
    assert len(est) == len(PT.SUBFAMILIAS)
    for ruta, fila in est.items():
        assert fila["ok"], "%s no cargo: %s" % (ruta, fila["error"])
        assert fila["tools"], ruta
    fam = sorted(n for n in T.TOOLS if T.flag_de_optin(n) == "COGNIA_PRUEBAS")
    assert len(fam) >= 60, fam


def test_roles_ven_la_familia():
    assert "probar" in T.ROLE_TOOLS["implementador"]
    assert "probar" in T.ROLE_TOOLS["investigador"]
    assert "app_probar" in T.ROLE_TOOLS["implementador"]
    # lanzar apps no es de investigador
    assert "app_probar" not in T.ROLE_TOOLS["investigador"]
    assert "captura_inspeccionar" in T.ROLE_TOOLS["investigador"]


def test_catalogo_familias_y_ayuda_conocen_la_familia():
    from cognia.agent import catalogo_nodos as cn
    from cognia.harness import ayuda, familias
    assert cn.categoria_de("probar") == "pruebas"
    assert cn.categoria_de("pagina_abrir") == "pruebas"
    assert cn.categoria_de("py_lint") == "pruebas"
    assert cn.categoria_de("py_validar") != "pruebas"
    assert "pruebas" in familias.FAMILIAS
    filas = {f["familia"]: f for f in familias.estado()}
    assert filas["pruebas"]["encendida"] and filas["pruebas"]["n_tools"] >= 60
    import cognia.cli as cli
    for cmd in ("/probar", "/pruebas", "/escritorio"):
        assert cmd in cli._CMD_DESCRIPTIONS
        assert ayuda.clasificar(cmd, cli._CMD_DESCRIPTIONS[cmd]) == "Consola y arnes"
    assert ayuda.desbordes(cli._CMD_DESCRIPTIONS, ayuda.TOPE_CATEGORIA) == []


def test_apagada_responde_deshabilitada(monkeypatch):
    monkeypatch.setenv("COGNIA_PRUEBAS", "0")
    from cognia.simple_mode import visible_tools
    vis = visible_tools(T.TOOLS.keys(), override="sencillo")
    assert "probar" not in vis and "captura_diff" not in vis
    monkeypatch.setenv("COGNIA_PRUEBAS", "1")
    vis = visible_tools(T.TOOLS.keys(), override="sencillo")
    assert "probar" in vis and "captura_diff" in vis


# ── probar: despacho por tipo ────────────────────────────────────────────────

def test_probar_sin_objetivo_y_ayuda():
    out = T.run_tool("probar", "", {})
    assert "ERROR" in out and "probar ayuda" in out
    out = T.run_tool("probar", "ayuda", {})
    assert "imagenes:" in out and "captura_inspeccionar" in out and "apps graficas" in out
    out = T.run_tool("probar", "ayuda imagen", {})
    assert "captura_diff" in out and "pagina_" not in out
    out = T.run_tool("probar", "ayuda nada", {})
    assert "ERROR" in out
    out = T.run_tool("probar", "estado", {})
    assert "pruebas_estado" in out and "imagenes:" in out


def test_probar_json_roto_y_bueno(tmp_path):
    (tmp_path / "roto.json").write_text('{"a": [1,}', encoding="utf-8")
    (tmp_path / "ok.json").write_text('{"a": [1]}', encoding="utf-8")
    out = T.run_tool("probar", "roto.json", _ctx(tmp_path))
    assert out.startswith("RESULTADO probar (formato_validar)") and "problema" in out
    out = T.run_tool("probar", "ok.json", _ctx(tmp_path))
    assert "OK" in out


def test_probar_png_inspecciona(tmp_path):
    from PIL import Image
    im = Image.new("RGB", (60, 40), (255, 255, 255))
    im.save(tmp_path / "vacia.png")
    out = T.run_tool("probar", "vacia.png", _ctx(tmp_path))
    assert "captura_inspeccionar" in out and "UN solo color" in out


def test_probar_py_simple_valida_lintea_y_ejecuta(tmp_path):
    (tmp_path / "s.py").write_text("import os\nprint('hola', 2+2)\n", encoding="utf-8")
    out = T.run_tool("probar", "s.py", _ctx(tmp_path))
    assert "sintaxis OK" in out
    assert "'os' imported but unused" in out
    assert "hola 4" in out, out


def test_probar_py_con_input_usa_ejecutar_guion(tmp_path):
    (tmp_path / "m.py").write_text(
        "op = input('op> ')\nprint('elegiste', op)\n", encoding="utf-8")
    out = T.run_tool("probar", "m.py | entradas=7", _ctx(tmp_path))
    assert "ejecutar_guion" in out and "elegiste 7" in out, out


def test_probar_py_gui_va_a_app_probar_sin_lanzar_nada(tmp_path, monkeypatch):
    """Un .py que importa pygame/tkinter se despacha a app_probar. No se lanza
    de verdad: se intercepta run_tool para comprobar el despacho."""
    (tmp_path / "g.py").write_text("import tkinter\n", encoding="utf-8")
    llamadas = []
    real = PT._run

    def falso(nombre, args, ctx):
        if nombre == "app_probar":
            llamadas.append(args)
            return "RESULTADO app_probar (falso)"
        return real(nombre, args, ctx)
    monkeypatch.setattr(PT, "_run", falso)
    out = T.run_tool("probar", "g.py | pasos=tecla a", _ctx(tmp_path))
    assert llamadas and "g.py" in llamadas[0] and "pasos=tecla a" in llamadas[0]
    assert "app_probar (falso)" in out


def test_probar_carpeta_inventaria(tmp_path):
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")
    (tmp_path / "a.png").write_bytes(b"")
    (tmp_path / "x.py").write_text("print(1)\n", encoding="utf-8")
    out = T.run_tool("probar", str(tmp_path), _ctx(tmp_path))
    assert ".html x1" in out and ".png x1" in out and ".py x1" in out
    assert "index.html" in out


def test_probar_html_renderiza_y_valida(tmp_path):
    (tmp_path / "p.html").write_text("<html><head><title>T</title></head><body><h1>Hola</h1><div></body></html>",
                                     encoding="utf-8")
    from cognia.agent import renderizador as rz
    if not (rz.playwright_disponible() or rz.navegador_sistema()[0]):
        pytest.skip("sin navegador headless")
    out = T.run_tool("probar", "p.html", _ctx(tmp_path))
    assert out.startswith("RESULTADO probar (renderizar)") and "captura en" in out
    assert "formato_validar" in out and "<div>" in out


def test_probar_comando_sin_ventana_explica(tmp_path):
    out = T.run_tool("probar", 'python -c "print(1)"', _ctx(tmp_path))
    assert "sin abrir ventana" in out and "ejecutar_guion" in out


# ── regresiones del helper ───────────────────────────────────────────────────

def test_partir_args_no_deja_comillas_colgando():
    obj, o = PC.partir_args('python "C:\\ruta con espacios\\x.py" | pasos=tecla a', ("pasos",))
    assert obj == 'python "C:\\ruta con espacios\\x.py"'
    assert o == {"pasos": "tecla a"}
    obj, o = PC.partir_args('"C:\\ruta\\x.py"', ("pasos",))
    assert obj == "C:\\ruta\\x.py"
    obj, o = PC.partir_args("f.html ancho=800 alto=600", ("ancho", "alto"))
    assert obj == "f.html" and o == {"ancho": "800", "alto": "600"}


def test_resumen_imagen_pagina_con_texto_es_contenido(tmp_path):
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (400, 300), (255, 255, 255))
    d = ImageDraw.Draw(im)
    for i in range(12):
        d.text((10, 10 + i * 20), "linea de texto %d con cosas" % i, fill=(20 + i * 5, 20, 20))
    im.save(tmp_path / "t.png")
    info = PC.resumen_imagen(tmp_path / "t.png")
    assert info["veredicto"].startswith("tiene contenido"), info
    Image.new("RGB", (400, 300), (255, 255, 255)).save(tmp_path / "b.png")
    assert "UN solo color" in PC.resumen_imagen(tmp_path / "b.png")["veredicto"]


def test_resolver_ruta_mira_primero_el_scratchpad(tmp_path):
    sc = tmp_path / "scratch"
    sc.mkdir()
    (sc / "prueba.wav").write_bytes(b"x")
    assert PC.resolver_ruta("prueba.wav", ctx={"_scratchpad": str(sc)}) == (sc / "prueba.wav").resolve()
    with pytest.raises(ValueError):
        PC.resolver_ruta("prueba.wav", ctx={"_scratchpad": str(tmp_path)})


def test_ruta_salida_no_anida_el_scratchpad(tmp_path, monkeypatch):
    """`salida=.cognia_scratch/<id>/x.png` (relativa al workspace) no se pega
    al scratchpad otra vez (anidaba .cognia_scratch/<id>/.cognia_scratch/...)."""
    ws = tmp_path
    sc = ws / ".cognia_scratch" / "abc"
    sc.mkdir(parents=True)
    monkeypatch.setattr(PC, "bases_relativas", lambda: [ws])
    ctx = {"_scratchpad": str(sc)}
    assert PC.ruta_salida(ctx, "x", ".png", ".cognia_scratch/abc/anim.png") == sc / "anim.png"
    assert PC.ruta_salida(ctx, "x", ".png", "anim.png") == sc / "anim.png"
