# -*- coding: utf-8 -*-
"""Familias audio_* / video_* (cognia/agent/medios_tools, 2026-09-07) con
soundfile/numpy/ffmpeg REALES (skip explicito si ffmpeg falta): un tono
generado mide ~1 s, pico -6 dBFS y 0% de silencio; un wav de silencio da
'SILENCIO'; el espectrograma existe; un mp4 creado desde 5 PNG dura 5/fps s y
sus fotogramas cambian; gif tambien; medios_estado no explota."""
from __future__ import annotations

import numpy as np
import pytest
import soundfile as sf
from PIL import Image

from cognia.agent import medios_tools as MT
from cognia.agent import pruebas_comun as PC
from cognia.agent.tools import TOOLS, tool

MT.register(tool)


def _hay_ffmpeg() -> bool:
    try:
        PC.binario("ffmpeg")
        PC.binario("ffprobe")
        return True
    except ValueError:
        return False


necesita_ffmpeg = pytest.mark.skipif(not _hay_ffmpeg(), reason="ffmpeg/ffprobe no instalados")


def _ctx(tmp_path):
    return {"_scratchpad": str(tmp_path)}


def _fn(nombre):
    return TOOLS[nombre]["fn"]


def test_registra_las_siete():
    for n in MT.NOMBRES:
        assert n in TOOLS, n
        assert TOOLS[n]["doc"].startswith(n)


def test_tono_generado_se_mide(tmp_path):
    # ruta RELATIVA: tiene que caer en el scratchpad, no en el cwd
    out = _fn("audio_generar_prueba")("tono.wav | hz=440 | segundos=1 | amplitud=0.5", _ctx(tmp_path))
    assert "RESULTADO audio_generar_prueba:" in out and (tmp_path / "tono.wav").exists()
    ins = _fn("audio_inspeccionar")("tono.wav", _ctx(tmp_path))     # relativo al scratchpad
    assert "RESULTADO audio_inspeccionar:" in ins
    assert "duracion medida 1.000 s" in ins
    assert "pico -6.0 dBFS" in ins
    assert "silencio 0.0%" in ins
    assert "OK" in ins


def test_silencio_da_veredicto(tmp_path):
    p = tmp_path / "mudo.wav"
    sf.write(str(p), np.zeros(44100, dtype="float32"), 44100)
    out = _fn("audio_inspeccionar")(str(p), _ctx(tmp_path))
    assert "SILENCIO total" in out


def test_clipping_y_silencio_en_los_bordes(tmp_path):
    sr = 44100
    x = np.zeros(sr, dtype="float32")
    t = np.arange(sr // 2) / float(sr)
    x[sr // 4: sr // 4 + sr // 2] = np.clip(1.5 * np.sin(2 * np.pi * 440 * t), -1, 1)
    p = tmp_path / "clip.wav"
    sf.write(str(p), x, sr)
    out = _fn("audio_inspeccionar")(str(p), _ctx(tmp_path))
    assert "CLIPPING" in out
    assert "silencio al inicio 250 ms, al final 250 ms" in out


def test_espectrograma_existe(tmp_path):
    p = tmp_path / "t.wav"
    t = np.arange(22050) / 22050.0
    sf.write(str(p), (0.3 * np.sin(2 * np.pi * 1000 * t)).astype("float32"), 22050)
    out = _fn("audio_espectrograma")("%s | salida=esp.png" % p, _ctx(tmp_path))
    assert "RESULTADO audio_espectrograma:" in out
    assert (tmp_path / "esp.png").exists()
    assert "tiene contenido" in out


def test_audio_no_existe(tmp_path):
    out = _fn("audio_inspeccionar")("nada.wav", _ctx(tmp_path))
    assert "ERROR" in out and "no existe" in out


def _frames(tmp_path, n=5):
    d = tmp_path / "frames"
    d.mkdir()
    for i in range(n):
        im = Image.new("RGB", (64, 48), (255, 255, 255))
        im.paste((255, 0, 0), (i * 10, 10, i * 10 + 10, 30))
        im.save(d / ("f%02d.png" % i))
    return d


@necesita_ffmpeg
def test_video_crear_mp4_e_inspeccionar(tmp_path):
    d = _frames(tmp_path)
    out = _fn("video_crear")("%s | %s | fps=5" % (d, tmp_path / "v.mp4"), _ctx(tmp_path))
    assert "RESULTADO video_crear:" in out, out
    assert (tmp_path / "v.mp4").exists()
    assert "h264" in out and "64x48" in out and "OK" in out
    ins = _fn("video_inspeccionar")(str(tmp_path / "v.mp4"), _ctx(tmp_path))
    dur = float(ins.split(", ")[1].split(" s")[0])
    assert 0.8 <= dur <= 1.2        # 5 fotogramas a 5 fps = 1 s


@necesita_ffmpeg
def test_video_fotogramas_detecta_movimiento(tmp_path):
    d = _frames(tmp_path)
    _fn("video_crear")("%s | %s | fps=5" % (d, tmp_path / "v.mp4"), _ctx(tmp_path))
    out = _fn("video_fotogramas")("%s | n=4 | salida=fot.png" % (tmp_path / "v.mp4"), _ctx(tmp_path))
    assert "RESULTADO video_fotogramas:" in out, out
    assert (tmp_path / "fot.png").exists()
    assert "se mueve" in out


@necesita_ffmpeg
def test_video_congelado(tmp_path):
    d = tmp_path / "quietos"
    d.mkdir()
    for i in range(4):
        Image.new("RGB", (64, 48), (0, 0, 200)).save(d / ("q%d.png" % i))
    _fn("video_crear")("%s | %s | fps=4" % (d, tmp_path / "q.mp4"), _ctx(tmp_path))
    out = _fn("video_fotogramas")("%s | n=3" % (tmp_path / "q.mp4"), _ctx(tmp_path))
    assert "CONGELADO" in out


@necesita_ffmpeg
def test_video_crear_gif(tmp_path):
    d = _frames(tmp_path)
    out = _fn("video_crear")("%s | %s | fps=5" % (d, tmp_path / "v.gif"), _ctx(tmp_path))
    assert "RESULTADO video_crear:" in out, out
    assert (tmp_path / "v.gif").exists()
    assert "gif" in out


@necesita_ffmpeg
def test_video_inspeccionar_no_video(tmp_path):
    p = tmp_path / "t.wav"
    sf.write(str(p), np.zeros(4410, dtype="float32"), 44100)
    out = _fn("video_inspeccionar")(str(p), _ctx(tmp_path))
    assert "SIN stream de video" in out


def test_video_crear_salida_mala(tmp_path):
    d = _frames(tmp_path)
    out = _fn("video_crear")("%s | %s" % (d, tmp_path / "v.avi"), _ctx(tmp_path))
    assert "ERROR" in out


def test_medios_estado_no_explota(tmp_path):
    out = _fn("medios_estado")("", _ctx(tmp_path))
    assert "ffmpeg" in out and "soundfile" in out
