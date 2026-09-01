# -*- coding: utf-8 -*-
"""Espiral de depuracion y canvas quieto (2026-09-01).

A/B con 20 min: el modelo escribio debug2.js ... debug7.js persiguiendo un bug
de movimiento que la pagina nunca mostro. Dos cosas nuevas: los scripts sueltos
se cuentan por su nombre (al tercero se avisa) y el lazo corto informa si el
canvas se mueve o esta quieto entre dos muestras.
"""
from __future__ import annotations

import pytest

from cognia.agent.loop import _es_fichero_suelto
from cognia.harness import lazo_corto as lz


@pytest.mark.parametrize("ruta", [
    "debug7.js", "debug_mover.js", "tmp.py", "prueba_api.py", "scratch.js",
    "verificar_contrato.js", "check.py", "src/diag_x.py", "repro.py", "kk.sh",
])
def test_scripts_sueltos(ruta):
    assert _es_fichero_suelto(ruta)


@pytest.mark.parametrize("ruta", [
    "game.js", "servidor.py", "test_juego.js", "tests/test_api.py", "index.html",
    "README.md", "debug.md", "verificacion.txt", "checkout.js",
])
def test_producto_no_es_suelto(ruta):
    assert not _es_fichero_suelto(ruta)


def _hay_playwright():
    try:
        import playwright  # noqa: F401
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _hay_playwright(), reason="sin Playwright")
def test_canvas_quieto_y_canvas_que_se_mueve(tmp_path):
    quieto = tmp_path / "q.html"
    quieto.write_text("<canvas id='c' width='40' height='40'></canvas><script>"
                      "const g=document.getElementById('c').getContext('2d');"
                      "g.fillStyle='#f00';g.fillRect(0,0,10,10);g.fillStyle='#00f';g.fillRect(20,20,5,5);"
                      "</script>", encoding="utf-8")
    r = lz.comprobar_html(quieto, None)
    assert r["ok"] is True and r.get("canvas_animado") is False
    assert "QUIETO" in r["detalle"]
    vivo = tmp_path / "v.html"
    vivo.write_text("<canvas id='c' width='60' height='40'></canvas><script>"
                    "const c=document.getElementById('c'),g=c.getContext('2d');let x=0;"
                    "function f(){g.fillStyle='#123';g.fillRect(0,0,60,40);g.fillStyle='#0f0';"
                    "g.fillRect((x++*3)%50,10,8,8);requestAnimationFrame(f);}f();"
                    "</script>", encoding="utf-8")
    r = lz.comprobar_html(vivo, None)
    assert r["ok"] is True and r.get("canvas_animado") is True
    assert "se mueve" in r["detalle"]
