# -*- coding: utf-8 -*-
"""Contrato del guion interactivo de `renderizar` (cognia/agent/renderizador_guion,
2026-09-04): el parser (sin navegador), y con Playwright REAL una pagina con canvas
que escucha teclado, un boton que cambia texto y un input: las teclas mueven el
juego (la pantalla cambia y `window.score` sube), el clic cambia el DOM, escribir
rellena, los asserts juzgan, las capturas se guardan y el mapa de interaccion
lista los controles con selectores usables. Y el cableado real via run_tool."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from cognia.agent import renderizador_guion as RG

PAGINA = """<!doctype html><html><head><title>Juego de prueba</title></head><body>
<h1 id="titulo">Puntos: <span id="score">0</span></h1>
<canvas id="c" width="300" height="200"></canvas>
<button id="boton">Pulsar</button>
<p id="estado">sin pulsar</p>
<input id="nombre" placeholder="tu nombre">
<a href="#ayuda">Ayuda</a>
<script>
  window.score = 0; window.player = {x: 20};
  const c = document.getElementById('c'), ctx = c.getContext('2d');
  function pintar(){ ctx.fillStyle='#fff'; ctx.fillRect(0,0,300,200); ctx.fillStyle='#c00'; ctx.fillRect(window.player.x, 80, 30, 30); }
  pintar();
  document.addEventListener('keydown', e => {
    if (e.key === 'ArrowRight') { window.player.x += 40; window.score += 1; document.getElementById('score').textContent = window.score; pintar(); }
    if (e.key === 'Escape') { console.error('escape no soportado'); }
  });
  document.getElementById('boton').onclick = () => { document.getElementById('estado').textContent = 'pulsado ' + (++window.pulsos || (window.pulsos = 1)); };
</script></body></html>"""


def _pagina(tmp_path) -> Path:
    p = tmp_path / "juego.html"
    p.write_text(PAGINA, encoding="utf-8")
    return p


# ── parser (sin navegador) ───────────────────────────────────────────────────

def test_parsear_guion_cubre_las_ops():
    pasos = RG.parsear_guion("tecla derecha*3; teclas a,b; mantener espacio 200; clic #btn; clic 10,20; "
                             "dobleclic #x; escribir #nombre \"ana maria\"; tipear \"hola\"; raton 5,6; "
                             "arrastrar 1,2 3,4; scroll 100; espera 50; esperar #ok; esperar \"listo\"; "
                             "captura tras; var window.score; js window.score=5; assert window.score==5; recargar")
    ops = [p.op for p in pasos]
    assert ops == ["tecla", "teclas", "mantener", "clic", "clic", "dobleclic", "escribir", "tipear", "raton",
                   "arrastrar", "scroll", "espera", "esperar", "esperar", "captura", "var", "js", "assert", "recargar"]
    assert pasos[0].args == ["ArrowRight", 3]
    assert pasos[1].args == ["a", "b"]
    assert pasos[2].args == ["Space", 200]
    assert pasos[4].args == [10, 20]
    assert pasos[6].args == ["#nombre", "ana maria"]
    assert pasos[9].args == [1, 2, 3, 4]


def test_parsear_guion_rechaza_lo_desconocido_y_lo_malformado():
    with pytest.raises(ValueError, match="paso desconocido"):
        RG.parsear_guion("volar alto")
    with pytest.raises(ValueError, match="espera"):
        RG.parsear_guion("espera mucho")
    with pytest.raises(ValueError, match="mantener"):
        RG.parsear_guion("mantener espacio")
    assert RG.parsear_guion("# comentario\n\n;;") == []


def test_parsear_guion_alias_de_teclas():
    assert RG._tecla("izquierda") == "ArrowLeft"
    assert RG._tecla("Enter") == "Enter"
    assert RG._tecla("f5") == "F5"
    assert RG._tecla("q") == "q"
    assert RG._tecla("arrowdown") == "ArrowDown"


# ── Playwright real ──────────────────────────────────────────────────────────

pytestmark_pw = pytest.mark.skipif(not __import__("importlib").util.find_spec("playwright"),
                                   reason="sin Playwright")


@pytestmark_pw
def test_guion_real_teclas_clic_escribir_vars_asserts_y_mapa(tmp_path):
    p = _pagina(tmp_path)
    r = RG.correr_guion(p.resolve().as_uri(),
                        "var window.player.x; tecla ArrowRight*3; assert window.score == 3; assert canvas cambia; "
                        "captura tras3; clic #boton; assert texto contiene \"pulsado 1\"; "
                        "escribir #nombre \"ana\"; assert document.querySelector('#nombre').value === 'ana'; "
                        "tecla Escape; assert sin errores",
                        vars_iniciales=["window.score"], salida_base=tmp_path / "caps", prefijo="t")
    assert not r.get("error"), r
    pasos = {x["n"]: x for x in r["pasos"]}
    # las 3 flechas movieron el jugador y subieron el score: vars antes -> despues
    p2 = pasos[2]
    assert p2["vars_cambiadas"]["window.score"] == ("0", "3")
    assert p2["vars_cambiadas"]["window.player.x"] == ("20", "140")
    assert p2["cambio"] is not None and p2["cambio"] >= RG.UMBRAL_CAMBIO
    assert pasos[3]["assert_ok"] is True and pasos[4]["assert_ok"] is True
    assert pasos[5]["captura"] and Path(pasos[5]["captura"]).is_file()
    assert pasos[7]["assert_ok"] is True            # texto contiene "pulsado 1"
    assert pasos[9]["assert_ok"] is True            # el input tiene 'ana'
    # Escape provoco un console.error: el assert 'sin errores' FALLA y lo dice
    assert pasos[10]["errores_nuevos"] == 1
    assert pasos[11]["assert_ok"] is False
    assert r["asserts"]["total"] == 5 and len(r["asserts"]["fallidos"]) == 1
    assert r["vars_final"]["window.score"] == "3"
    # mapa de interaccion: boton, input y enlace con selectores usables
    sels = {c["selector"] for c in r["mapa"]["controles"]}
    assert "#boton" in sels and "#nombre" in sels
    assert r["mapa"]["canvas"] is True
    assert r.get("captura_final") and Path(r["captura_final"]).is_file()
    texto = RG.texto_guion(r)
    assert "window.score: 0 -> 3" in texto and "pantalla CAMBIO" in texto and "asserts: 4/5 OK" in texto
    assert "mapa de interaccion" in texto and "#boton" in texto


@pytestmark_pw
def test_guion_real_una_tecla_que_no_hace_nada_se_ve(tmp_path):
    p = _pagina(tmp_path)
    r = RG.correr_guion(p.resolve().as_uri(), "tecla ArrowLeft*2", vars_iniciales=["window.score"],
                        salida_base=tmp_path / "caps", captura_final=False)
    paso = r["pasos"][0]
    assert paso["vars_cambiadas"] == {}
    assert paso["cambio"] is not None and paso["cambio"] < RG.UMBRAL_CAMBIO
    assert "pantalla igual" in RG.texto_guion(r) and "vars sin cambio" in RG.texto_guion(r)


@pytestmark_pw
def test_guion_invalido_o_pagina_inexistente_no_lanzan(tmp_path):
    p = _pagina(tmp_path)
    assert "guion invalido" in RG.correr_guion(p.resolve().as_uri(), "volar")["error"]
    r = RG.correr_guion("http://127.0.0.1:1/nada", "tecla a")
    assert "no se pudo abrir" in r["error"]


@pytestmark_pw
def test_cableado_en_la_tool_renderizar(tmp_path, monkeypatch):
    from cognia.agent.tools import run_tool
    p = _pagina(tmp_path)
    monkeypatch.chdir(tmp_path)
    out = run_tool("renderizar", f"{p} | vars=window.score | guion=tecla derecha*2; captura dos; assert window.score == 2",
                   {"_scratchpad": str(tmp_path / "scratch"), "workspace": str(tmp_path)})
    assert out.startswith("RESULTADO renderizar"), out
    assert "GUION INTERACTIVO" in out and "window.score: 0 -> 2" in out and "asserts: 1/1 OK" in out
    assert "playwright-guion" in out
    # las capturas quedaron en el scratchpad de la tarea
    assert any((tmp_path / "scratch").glob("*dos*.png"))


def test_partir_args_con_guion_y_vars():
    from cognia.agent.renderizador import partir_args
    fuente, o = partir_args("juego.html | espera=500 | vars=window.score,player.x | guion=tecla a; clic #b; assert x==1")
    assert fuente == "juego.html"
    assert o["espera"] == "500" and o["vars"] == "window.score,player.x"
    assert o["guion"] == "tecla a; clic #b; assert x==1"
