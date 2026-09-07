# -*- coding: utf-8 -*-
"""Contrato de la familia `pagina_*` (cognia/agent/pagina_tools, 2026-09-07):
una sesion PERSISTENTE de Chromium (Playwright real; se salta sin el) sobre una
pagina de prueba con canvas animado, boton, input, imagen rota, enlace roto,
desbordamiento a 360px e imagen sin alt. Las tools se llaman por su `fn` del
registro real (decorador @tool de cognia.agent.tools) desde el hilo del test —
la sesion vive en su propio worker, asi que el hilo del llamador da igual."""
from __future__ import annotations

import urllib.request
from pathlib import Path

import pytest

from cognia.agent import pagina_tools as PT
from cognia.agent import pruebas_comun as PC

PAGINA = """<!doctype html><html><head><meta charset="utf-8"><title>Pagina de prueba</title>
<style>body{background:#fff;color:#111;font-family:sans-serif} #ancho{width:900px;height:20px;background:#eee}
#gris{color:#bbb}</style></head><body>
<h1 id="titulo">Contador: <span id="n">0</span></h1>
<canvas id="c" width="300" height="150"></canvas>
<button id="boton">Sumar</button>
<p id="estado">quieto</p>
<input id="nombre" placeholder="tu nombre">
<img id="rota" src="no_existe_123.png" width="40" height="40">
<a id="enlace" href="fichero_que_no_existe.html">enlace roto</a>
<div id="ancho">desborda a 360</div>
<p id="gris">texto de bajo contraste</p>
<script>
  window.contador = 0;
  const c = document.getElementById('c'), ctx = c.getContext('2d');
  let x = 0;
  function pintar(){ ctx.fillStyle = '#fff'; ctx.fillRect(0,0,300,150); ctx.fillStyle = '#c00';
    ctx.fillRect(x, 50, 40, 40); x = (x + 7) % 260; requestAnimationFrame(pintar); }
  pintar();
  document.getElementById('boton').onclick = () => {
    window.contador++; document.getElementById('n').textContent = window.contador;
    document.getElementById('estado').textContent = 'pulsado ' + window.contador; };
  document.addEventListener('keydown', e => { if (e.key === 'ArrowRight') { window.contador += 10;
    document.getElementById('n').textContent = window.contador; } });
  console.log('hola desde la pagina');
</script></body></html>"""


def _playwright():
    try:
        import playwright.sync_api  # noqa: F401
        return True
    except Exception:
        return False


def _tools():
    from cognia.agent.tools import TOOLS, tool
    if "pagina_abrir" not in TOOLS:
        PT.register(tool)
    return TOOLS


def _fn(nombre):
    return _tools()[nombre]["fn"]


# ── sin navegador ────────────────────────────────────────────────────────────

def test_parser_de_args_y_selector_o_punto():
    obj, o = PC.partir_args("index.html | ancho=800 | espera=100", ["ancho", "alto", "espera"])
    assert obj == "index.html" and o == {"ancho": "800", "espera": "100"}
    obj, o = PC.partir_args("index.html ancho=800 espera=100", ["ancho", "alto", "espera"])
    assert obj == "index.html" and o["ancho"] == "800" and o["espera"] == "100"
    assert PT._selector_o_punto("10, 20") == (10, 20)
    assert PT._selector_o_punto("#boton") == "#boton"
    assert PT._tecla("derecha") == "ArrowRight"


def test_registro_completo_de_la_familia():
    T = _tools()
    esperadas = {"pagina_abrir", "pagina_js", "pagina_texto", "pagina_atributos", "pagina_clic",
                 "pagina_escribir", "pagina_tecla", "pagina_scroll", "pagina_esperar", "pagina_captura",
                 "pagina_consola", "pagina_red", "pagina_enlaces", "pagina_responsive",
                 "pagina_fotogramas", "pagina_accesibilidad", "pagina_servir", "pagina_cerrar",
                 "pagina_estado"}
    assert esperadas <= set(T)
    for n in esperadas:
        assert T[n]["doc"].startswith(n), n
        assert T[n]["desc"], n


def test_sin_pagina_abierta_dice_como_abrir():
    PT.cerrar_todo()
    out = _fn("pagina_js")("1+1", {})
    assert "ERROR" in out and "pagina_abrir" in out
    assert "sin sesion" in _fn("pagina_estado")("", {})


# ── con Playwright real ──────────────────────────────────────────────────────

@pytest.mark.skipif(not _playwright(), reason="Playwright no instalado")
def test_sesion_persistente_de_punta_a_punta(tmp_path):
    p = tmp_path / "prueba.html"
    p.write_text(PAGINA, encoding="utf-8")
    ctx = {"_scratchpad": str(tmp_path)}
    fn = _fn
    try:
        out = fn("pagina_abrir")(f"{p} | espera=300", ctx)
        assert out.startswith("RESULTADO pagina_abrir:"), out
        assert "titulo: Pagina de prueba" in out and "Contador: 0" in out and "sesion abierta" in out

        out = fn("pagina_estado")("", ctx)
        assert "sesion abierta" in out and "Pagina de prueba" in out

        out = fn("pagina_texto")("#estado", ctx)
        assert out.endswith("quieto"), out
        out = fn("pagina_texto")("p | todos=1", ctx)
        assert "coincidencia(s)" in out and "[0] quieto" in out

        out = fn("pagina_js")("window.contador", ctx)
        assert "RESULTADO pagina_js: 0" in out
        out = fn("pagina_js")("document.querySelectorAll('p').length", ctx)
        assert "RESULTADO pagina_js: 2" in out
        out = fn("pagina_js")("noExiste.foo", ctx)
        assert "ERROR" in out

        out = fn("pagina_clic")("#boton", ctx)
        assert "RESULTADO pagina_clic:" in out and "cambio" in out
        assert fn("pagina_texto")("#estado", ctx).endswith("pulsado 1")
        assert "RESULTADO pagina_js: 1" in fn("pagina_js")("window.contador", ctx)

        out = fn("pagina_tecla")("derecha*2", ctx)
        assert "ArrowRight x2" in out
        assert "RESULTADO pagina_js: 21" in fn("pagina_js")("window.contador", ctx)

        out = fn("pagina_escribir")('#nombre "ana maria"', ctx)
        assert "escrito" in out
        assert "RESULTADO pagina_js: \"ana maria\"" in fn("pagina_js")("document.getElementById('nombre').value", ctx)

        out = fn("pagina_atributos")("#boton", ctx)
        assert "<button#boton>" in out and "VISIBLE" in out and "display=inline-block" in out
        assert "ERROR" in fn("pagina_atributos")("#no_existe", ctx)

        out = fn("pagina_scroll")("100", ctx)
        assert "scroll 100" in out
        out = fn("pagina_esperar")('"pulsado 1"', ctx)
        assert "aparecio el texto" in out
        out = fn("pagina_esperar")("120", ctx)
        assert "esperados 120 ms" in out

        out = fn("pagina_captura")("", ctx)
        assert "captura en" in out and "1100x720" in out
        ruta = out.split("captura en ")[1].split(" ·")[0]
        assert Path(ruta).is_file()
        out = fn("pagina_captura")("#c | salida=canvas.png", ctx)
        assert (tmp_path / "canvas.png").is_file() and "300x15" in out   # 300x150 o 300x151 (redondeo)

        out = fn("pagina_consola")("", ctx)
        assert "hola desde la pagina" in out and "mensaje(s)" in out

        out = fn("pagina_red")("| fallos=1", ctx)
        assert "fallida(s)" in out and "no_existe_123.png" in out

        out = fn("pagina_enlaces")("", ctx)
        assert "roto(s)" in out and "fichero_que_no_existe.html" in out
        assert "imagenes que no cargaron" in out and "no_existe_123.png" in out
        assert "sin alt" in out

        out = fn("pagina_responsive")("| anchos=360,1280", ctx)
        assert "360px: DESBORDA" in out and "1280px: sin desbordamiento" in out
        mosaico = out.split("mosaico en ")[1].split(" ·")[0]
        assert Path(mosaico).is_file()

        out = fn("pagina_fotogramas")("| n=4 | cada=120", ctx)
        assert "ANIMA" in out or "A RATOS" in out, out
        assert Path(out.split("mosaico en ")[1].strip()).is_file()

        out = fn("pagina_accesibilidad")("", ctx)
        assert "img_sin_alt x1" in out and "#rota" in out
        assert "input_sin_label" not in out          # tiene placeholder
        assert "contraste_bajo" in out and "#gris" in out
        assert "sin atributo lang" in out

        out = fn("pagina_servir")(f"{tmp_path}", ctx)
        assert "sirviendo" in out
        url = out.split(" en ")[1].split(" ·")[0]
        with urllib.request.urlopen(url + "prueba.html", timeout=5) as r:
            assert r.status == 200 and b"Pagina de prueba" in r.read()
        out = fn("pagina_abrir")(url + "prueba.html", ctx)
        assert "titulo: Pagina de prueba" in out
        out = fn("pagina_red")("", ctx)
        assert "GET http://127.0.0.1" in out

        assert "servidor" in fn("pagina_estado")("", ctx)
    finally:
        out = fn("pagina_cerrar")("", ctx)
    assert "cerrado navegador" in out and "servidor" in out
    assert "no habia nada abierto" in fn("pagina_cerrar")("", ctx)
    assert PT.disponibilidad()["sesion"] is False


@pytest.mark.skipif(not _playwright(), reason="Playwright no instalado")
def test_url_no_alcanzable_es_accionable(tmp_path):
    import socket
    s = socket.socket(); s.bind(("127.0.0.1", 0)); puerto = s.getsockname()[1]; s.close()
    try:
        out = _fn("pagina_abrir")(f"http://127.0.0.1:{puerto}/nada", {"_scratchpad": str(tmp_path)})
        assert "ERROR" in out and "ejecutar_fondo" in out, out
    finally:
        PT.cerrar_todo()


@pytest.mark.skipif(not _playwright(), reason="Playwright no instalado")
def test_run_tool_cablea_la_familia(tmp_path):
    from cognia.agent.tools import run_tool
    p = tmp_path / "min.html"
    p.write_text("<title>Min</title><p id='t'>hola</p>", encoding="utf-8")
    _tools()
    try:
        out = run_tool("pagina_abrir", str(p), {"_scratchpad": str(tmp_path)})
        assert "titulo: Min" in out
        assert run_tool("pagina_texto", "#t", {}).endswith("hola")
    finally:
        PT.cerrar_todo()
