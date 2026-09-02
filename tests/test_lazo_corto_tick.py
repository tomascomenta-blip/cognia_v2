# -*- coding: utf-8 -*-
"""Si el contrato promete tick(ms), el lazo corto lo usa (2026-09-01).

ARK con 45 min: 26 avisos informativos de "canvas QUIETO" y el modelo no actuo;
la simulacion no avanzaba (criaturas quietas, hambre que no baja). Con el tick
la evidencia deja de ser ambigua: 2.000 ms simulados sin cambiar un pixel es
una simulacion parada, no una pagina estatica legitima.
"""
from __future__ import annotations

import pytest

from cognia.harness import lazo_corto as lz


def _hay_playwright():
    try:
        import playwright  # noqa: F401
        return True
    except Exception:
        return False


IDS = {"globales": ["SIM"], "metodos": {"SIM": ["tick"]}, "dom_ids": []}


@pytest.mark.skipif(not _hay_playwright(), reason="sin Playwright")
def test_simulacion_parada_con_tick_es_fallo(tmp_path):
    f = tmp_path / "index.html"
    f.write_text("<canvas id='c' width='60' height='40'></canvas><script>"
                 "const g=document.getElementById('c').getContext('2d');"
                 "g.fillStyle='#123';g.fillRect(0,0,60,40);g.fillStyle='#0f0';g.fillRect(5,5,8,8);"
                 "window.SIM={t:0,tick(ms){this.t+=ms;}};"  # el tiempo avanza pero no se pinta
                 "</script>", encoding="utf-8")
    r = lz.comprobar_html(f, IDS)
    assert r["corrio"] is True
    assert r["ok"] is False
    assert "LA SIMULACION NO AVANZA" in r["detalle"]


@pytest.mark.skipif(not _hay_playwright(), reason="sin Playwright")
def test_simulacion_que_avanza_con_tick_pasa(tmp_path):
    f = tmp_path / "index.html"
    f.write_text("<canvas id='c' width='60' height='40'></canvas><script>"
                 "const c=document.getElementById('c'),g=c.getContext('2d');let x=0;"
                 "function pinta(){g.fillStyle='#123';g.fillRect(0,0,60,40);g.fillStyle='#0f0';"
                 "g.fillRect(x%50,5,8,8);}pinta();"
                 "window.SIM={tick(ms){x+=ms/50;pinta();}};"
                 "</script>", encoding="utf-8")
    r = lz.comprobar_html(f, IDS)
    assert r["ok"] is True, r["detalle"]
    assert "avanza con window.SIM.tick()" in r["detalle"]


@pytest.mark.skipif(not _hay_playwright(), reason="sin Playwright")
def test_sin_tick_en_el_contrato_solo_informa(tmp_path):
    f = tmp_path / "index.html"
    f.write_text("<canvas id='c' width='40' height='40'></canvas><script>"
                 "const g=document.getElementById('c').getContext('2d');"
                 "g.fillStyle='#f00';g.fillRect(0,0,10,10);g.fillStyle='#00f';g.fillRect(20,20,5,5);"
                 "</script>", encoding="utf-8")
    r = lz.comprobar_html(f, {"globales": [], "metodos": {}, "dom_ids": []})
    assert r["ok"] is True
    assert "QUIETO" in r["detalle"]
