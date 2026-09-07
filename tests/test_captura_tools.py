# -*- coding: utf-8 -*-
"""Familia captura_* (cognia/agent/captura_tools, 2026-09-07): con PIL REAL e
imagenes sinteticas: inspeccionar distingue uniforme de contenido y cuenta
fotogramas de un GIF; diff mide el % y la caja; recortar+zoom da el tamano
pedido; mosaico y cuadricula existen; comparar_color acierta y falla; describir
sin VLM lo dice; texto sin tesseract dice como instalarlo. Todo via el
decorador real (TOOLS[nombre]["fn"])."""
from __future__ import annotations

import pytest
from PIL import Image, ImageDraw

from cognia.agent import captura_tools as CT
from cognia.agent.tools import TOOLS, tool

CT.register(tool)


def _ctx(tmp_path):
    return {"_scratchpad": str(tmp_path)}


def _fn(nombre):
    return TOOLS[nombre]["fn"]


@pytest.fixture
def imgs(tmp_path):
    uni = tmp_path / "uniforme.png"
    Image.new("RGB", (200, 120), (255, 255, 255)).save(uni)
    con = tmp_path / "contenido.png"
    im = Image.new("RGB", (200, 120), (255, 255, 255))
    ImageDraw.Draw(im).rectangle((40, 30, 99, 79), fill=(255, 0, 0))
    im.save(con)
    gif = tmp_path / "anim.gif"
    frames = []
    for i in range(3):
        f = Image.new("RGB", (60, 40), (i * 80, 0, 0))
        frames.append(f)
    frames[0].save(gif, save_all=True, append_images=frames[1:], duration=100, loop=0)
    return {"uni": uni, "con": con, "gif": gif}


def test_registra_las_ocho():
    for n in CT.NOMBRES:
        assert n in TOOLS, n
        assert TOOLS[n]["doc"].startswith(n)


def test_inspeccionar_uniforme_vs_contenido(imgs, tmp_path):
    out = _fn("captura_inspeccionar")(str(imgs["uni"]), _ctx(tmp_path))
    assert out.startswith("RESULTADO captura_inspeccionar:")
    assert "UN solo color" in out
    out2 = _fn("captura_inspeccionar")(str(imgs["con"]), _ctx(tmp_path))
    assert "tiene contenido" in out2
    assert "#ff0000" in out2 and "200x120" in out2


def test_inspeccionar_gif_animado(imgs, tmp_path):
    out = _fn("captura_inspeccionar")(str(imgs["gif"]), _ctx(tmp_path))
    assert "animada: 3 fotogramas" in out
    assert "300 ms" in out


def test_inspeccionar_no_existe(tmp_path):
    out = _fn("captura_inspeccionar")("nada.png", _ctx(tmp_path))
    assert "ERROR" in out and "no existe" in out


def test_diff_mide_pct_y_caja(imgs, tmp_path):
    out = _fn("captura_diff")("%s | %s | salida=d.png" % (imgs["uni"], imgs["con"]), _ctx(tmp_path))
    assert "RESULTADO captura_diff:" in out
    # rectangulo 60x50 sobre 200x120 = 12,5%
    assert "12.50%" in out
    assert "cambio GRANDE" in out
    assert "x=40..100 y=30..80" in out
    assert (tmp_path / "d.png").exists()
    igual = _fn("captura_diff")("%s | %s" % (imgs["uni"], imgs["uni"]), _ctx(tmp_path))
    assert "IDENTICAS" in igual


def test_diff_tamanos_distintos(imgs, tmp_path):
    otra = tmp_path / "chica.png"
    Image.new("RGB", (100, 60), (255, 255, 255)).save(otra)
    out = _fn("captura_diff")("%s | %s" % (imgs["uni"], otra), _ctx(tmp_path))
    assert "TAMANOS DISTINTOS" in out


def test_recortar_zoom_da_el_tamano(imgs, tmp_path):
    out = _fn("captura_recortar")("%s | 40,30,60,50 | zoom=3 | salida=rec.png" % imgs["con"], _ctx(tmp_path))
    assert "RESULTADO captura_recortar:" in out
    im = Image.open(tmp_path / "rec.png")
    assert im.size == (180, 150)
    assert "#ff0000" in out or "UN solo color" in out     # la region es toda roja
    out2 = _fn("captura_recortar")("%s | region=centro" % imgs["con"], _ctx(tmp_path))
    assert "100x60" in out2
    mal = _fn("captura_recortar")("%s | 999,999,10,10" % imgs["con"], _ctx(tmp_path))
    assert "ERROR" in mal


def test_mosaico_con_lista_y_directorio(imgs, tmp_path):
    out = _fn("captura_mosaico")("%s,%s,%s | etiquetas=a,b,c | salida=m.png" % (imgs["uni"], imgs["con"], imgs["gif"]),
                                 _ctx(tmp_path))
    assert "mosaico de 3 imagenes" in out
    assert (tmp_path / "m.png").exists()
    out2 = _fn("captura_mosaico")("%s | salida=m2.png" % tmp_path, _ctx(tmp_path))
    assert "mosaico de" in out2 and (tmp_path / "m2.png").exists()


def test_cuadricula_existe_y_cambia(imgs, tmp_path):
    out = _fn("captura_cuadricula")("%s | paso=50 | salida=g.png" % imgs["con"], _ctx(tmp_path))
    assert "cuadricula cada 50 px" in out
    assert (tmp_path / "g.png").exists()
    d = _fn("captura_diff")("%s | g.png" % imgs["con"], _ctx(tmp_path))     # g.png relativo al scratchpad
    assert "IDENTICAS" not in d


def test_comparar_color_acierta_y_falla(imgs, tmp_path):
    ok = _fn("captura_comparar_color")("%s | 60,50 | #ff0000" % imgs["con"], _ctx(tmp_path))
    assert "COINCIDE" in ok and "NO coincide" not in ok
    mal = _fn("captura_comparar_color")("%s | 5,5 | #ff0000" % imgs["con"], _ctx(tmp_path))
    assert "NO coincide" in mal
    fuera = _fn("captura_comparar_color")("%s | 500,5 | #ff0000" % imgs["con"], _ctx(tmp_path))
    assert "ERROR" in fuera


def test_describir_sin_vlm_lo_dice(imgs, tmp_path, monkeypatch):
    monkeypatch.delenv("COGNIA_VLM_TOOLS", raising=False)
    out = _fn("captura_describir")("%s | pregunta=que hay" % imgs["con"], _ctx(tmp_path))
    assert "sin VLM" in out and "tiene contenido" in out


def test_describir_con_vlm_delega(imgs, tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIA_VLM_TOOLS", "1")
    llamadas = []

    def _falso(args, ctx):
        llamadas.append(args)
        return "RESULTADO vlm_mirar: un cuadrado rojo"
    monkeypatch.setitem(TOOLS, "vlm_mirar", {"fn": _falso, "doc": "vlm_mirar", "danger": False,
                                             "desc": "", "params": [], "timeout_s": None,
                                             "timeout_interno": None})
    out = _fn("captura_describir")("%s | pregunta=que hay" % imgs["con"], _ctx(tmp_path))
    assert "un cuadrado rojo" in out and "TECNICO" in out
    assert len(llamadas) == 1 and "que hay" in llamadas[0]


def test_texto_sin_tesseract_dice_como_instalar(imgs, tmp_path, monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "pytesseract", None)   # import falla
    out = _fn("captura_texto")(str(imgs["con"]), _ctx(tmp_path))
    assert "ERROR" in out and "winget install UB-Mannheim.TesseractOCR" in out


def test_ultimo_refleja_la_operacion(imgs, tmp_path):
    _fn("captura_inspeccionar")(str(imgs["uni"]), _ctx(tmp_path))
    u = CT.ultimo()
    assert u["tool"] == "captura_inspeccionar" and "UN solo color" in u["detalle"]
