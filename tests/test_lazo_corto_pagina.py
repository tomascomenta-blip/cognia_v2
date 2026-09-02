# -*- coding: utf-8 -*-
"""La PAGINA es la unidad de verificacion de un producto web (2026-09-01).

A/B con 20 min de reloj: el agente escribio index.html una vez y game.js doce
veces; el lazo abrio la pagina una sola vez y las otras doce solo paso
`node --check` sobre el .js, que dice "sintaxis OK" a un juego que no pinta.
"""
from __future__ import annotations

import pytest

from cognia.harness import lazo_corto as lz


def test_pagina_de_prefiere_la_que_referencia_el_script(tmp_path):
    (tmp_path / "index.html").write_text("<html><body></body></html>", encoding="utf-8")
    (tmp_path / "juego.html").write_text('<script src="game.js"></script>', encoding="utf-8")
    js = tmp_path / "game.js"
    js.write_text("var x = 1;", encoding="utf-8")
    assert lz.pagina_de(js, tmp_path).name == "juego.html"


def test_pagina_de_cae_a_index_sin_referencia(tmp_path):
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")
    js = tmp_path / "otro.js"
    js.write_text("var x = 1;", encoding="utf-8")
    assert lz.pagina_de(js, tmp_path).name == "index.html"


def test_pagina_de_none_sin_html(tmp_path):
    js = tmp_path / "util.js"
    js.write_text("var x = 1;", encoding="utf-8")
    assert lz.pagina_de(js, tmp_path) is None


def _hay_playwright():
    try:
        import playwright  # noqa: F401
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _hay_playwright(), reason="sin Playwright")
def test_escribir_el_js_abre_la_pagina_y_ve_el_contrato(tmp_path):
    import shutil
    if not shutil.which("node"):
        pytest.skip("sin node")
    (tmp_path / "index.html").write_text(
        '<canvas id="c" width="30" height="30"></canvas><script src="game.js"></script>',
        encoding="utf-8")
    js = tmp_path / "game.js"
    js.write_text("window.JUEGO = {tick(){}};", encoding="utf-8")
    ids = {"globales": ["JUEGO"], "metodos": {"JUEGO": ["guardar"]}, "dom_ids": []}
    lz._ultima.clear()
    txt = lz.tras_escritura(js, raiz=tmp_path, contrato=ids, forzar=True)
    assert txt.startswith("[LAZO CORTO FALLA] index.html (abierta tras escribir game.js)")
    assert "JUEGO.guardar" in txt
    js.write_text("window.JUEGO = {tick(){}, guardar(){}};"
                  "const g=document.getElementById('c').getContext('2d');"
                  "g.fillStyle='#0f0';g.fillRect(0,0,10,10);", encoding="utf-8")
    txt = lz.tras_escritura(js, raiz=tmp_path, contrato=ids, forzar=True)
    assert txt.startswith("[LAZO CORTO OK] index.html (abierta tras escribir game.js)")
