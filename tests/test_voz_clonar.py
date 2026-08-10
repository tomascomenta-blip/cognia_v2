# -*- coding: utf-8 -*-
"""Tests del backend de clonacion (cognia/voz/clonar.py) — subprocess mockeado.

POR QUE se mockea Popen y no se corre el CLI: el CLI real carga torch y
OpenVoice en venv312gpu (prohibido en tests: hay una medicion GPU en curso
y la regla de la ola es CPU con mocks). Lo que SI se verifica aqui es el
contrato completo del lado consumidor: comando construido, timeout que
mata, exit code con detalle, stdout contaminado con error legible (el modo
de fallo tipico de vendors ruidosos) y el 'ok' que no se cree sin el WAV
en disco.
"""
from __future__ import annotations

import py_compile
import subprocess
import sys
from pathlib import Path

import pytest

from cognia.voz import clonar

_REPO = Path(__file__).resolve().parents[1]


class FakeProc:
    """Doble de Popen: entrega (out, err) o revienta con TimeoutExpired."""

    def __init__(self, out="", err="", rc=0, expira=False):
        self.out, self.err, self.returncode = out, err, rc
        self.expira = expira
        self.matado = False
        self._llamadas = 0

    def communicate(self, timeout=None):
        self._llamadas += 1
        if self.expira and self._llamadas == 1:
            raise subprocess.TimeoutExpired(cmd="voz_clonar_cli", timeout=timeout)
        return self.out, self.err

    def kill(self):
        self.matado = True


def _preparar(monkeypatch, tmp_path, proc):
    """Crea la referencia, fija el python GPU y captura el comando lanzado."""
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"RIFF")
    monkeypatch.setenv("COGNIA_GPU_PYTHON", sys.executable)
    capturado = {}

    def fake_popen(cmd, **kwargs):
        capturado["cmd"] = cmd
        return proc
    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    return ref, capturado


# ── camino feliz: comando y JSON ─────────────────────────────────────────

def test_clonar_voz_comando_y_wav(monkeypatch, tmp_path):
    salida = tmp_path / "clon.wav"
    salida.write_bytes(b"RIFF")     # el contrato exige que el WAV EXISTA
    proc = FakeProc(out='{"ok": true, "wav": "%s", "seg": 3.2}'
                    % str(salida).replace("\\", "\\\\"))
    ref, capturado = _preparar(monkeypatch, tmp_path, proc)

    wav = clonar.clonar_voz(str(ref), "hola mundo", str(salida),
                            idioma="es", device="cpu", timeout=60)
    assert wav == str(salida)
    cmd = capturado["cmd"]
    assert cmd[0] == sys.executable                  # COGNIA_GPU_PYTHON manda
    assert cmd[1].endswith("voz_clonar_cli.py")
    assert cmd[cmd.index("--referencia") + 1] == str(ref)
    assert cmd[cmd.index("--texto") + 1] == "hola mundo"
    assert cmd[cmd.index("--device") + 1] == "cpu"
    assert cmd[cmd.index("--idioma") + 1] == "es"


def test_clonar_voz_stdout_con_progreso_toma_ultima_linea(monkeypatch, tmp_path):
    """Si algo se escapo del redirect, la ULTIMA linea JSON sigue valiendo."""
    salida = tmp_path / "clon.wav"
    salida.write_bytes(b"RIFF")
    js = '{"ok": true, "wav": "%s", "seg": 1}' % str(salida).replace("\\", "\\\\")
    proc = FakeProc(out="Loading model...\n" + js)
    ref, _ = _preparar(monkeypatch, tmp_path, proc)
    assert clonar.clonar_voz(str(ref), "hola", str(salida)) == str(salida)


# ── degradaciones VISIBLES ───────────────────────────────────────────────

def test_stdout_contaminado_error_legible(monkeypatch, tmp_path):
    proc = FakeProc(out="Loading checkpoint...\nEpoch 1/1 done", rc=0)
    ref, _ = _preparar(monkeypatch, tmp_path, proc)
    with pytest.raises(RuntimeError, match="stdout contaminado"):
        clonar.clonar_voz(str(ref), "hola", str(tmp_path / "c.wav"))


def test_stdout_vacio_error_legible(monkeypatch, tmp_path):
    proc = FakeProc(out="", rc=0)
    ref, _ = _preparar(monkeypatch, tmp_path, proc)
    with pytest.raises(RuntimeError, match="no imprimio nada"):
        clonar.clonar_voz(str(ref), "hola", str(tmp_path / "c.wav"))


def test_exit_no_cero_trae_stderr(monkeypatch, tmp_path):
    proc = FakeProc(out="", err="Traceback ...\nRuntimeError: boom melo", rc=1)
    ref, _ = _preparar(monkeypatch, tmp_path, proc)
    with pytest.raises(RuntimeError, match=r"(?s)codigo 1.*boom melo"):
        clonar.clonar_voz(str(ref), "hola", str(tmp_path / "c.wav"))


def test_exit_no_cero_prefiere_el_json_de_fallo(monkeypatch, tmp_path):
    proc = FakeProc(out='{"ok": false, "error": "faltan pesos X-9"}',
                    err="mucho ruido", rc=1)
    ref, _ = _preparar(monkeypatch, tmp_path, proc)
    with pytest.raises(RuntimeError, match="faltan pesos X-9"):
        clonar.clonar_voz(str(ref), "hola", str(tmp_path / "c.wav"))


def test_ok_false_con_rc_cero(monkeypatch, tmp_path):
    proc = FakeProc(out='{"ok": false, "error": "melo revento"}', rc=0)
    ref, _ = _preparar(monkeypatch, tmp_path, proc)
    with pytest.raises(RuntimeError, match="melo revento"):
        clonar.clonar_voz(str(ref), "hola", str(tmp_path / "c.wav"))


def test_ok_sin_wav_en_disco_es_contrato_roto(monkeypatch, tmp_path):
    fantasma = tmp_path / "no_escrito.wav"
    proc = FakeProc(out='{"ok": true, "wav": "%s", "seg": 1}'
                    % str(fantasma).replace("\\", "\\\\"))
    ref, _ = _preparar(monkeypatch, tmp_path, proc)
    with pytest.raises(RuntimeError, match="no existe"):
        clonar.clonar_voz(str(ref), "hola", str(tmp_path / "c.wav"))


def test_timeout_mata_y_reporta(monkeypatch, tmp_path):
    proc = FakeProc(expira=True)
    ref, _ = _preparar(monkeypatch, tmp_path, proc)
    with pytest.raises(RuntimeError, match="timeout tras 5s"):
        clonar.clonar_voz(str(ref), "hola", str(tmp_path / "c.wav"), timeout=5)
    assert proc.matado is True


def test_entradas_invalidas(monkeypatch, tmp_path):
    monkeypatch.setenv("COGNIA_GPU_PYTHON", sys.executable)
    with pytest.raises(RuntimeError, match="no existe el WAV de referencia"):
        clonar.clonar_voz(str(tmp_path / "nope.wav"), "hola",
                          str(tmp_path / "c.wav"))
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"RIFF")
    with pytest.raises(RuntimeError, match="texto vacio"):
        clonar.clonar_voz(str(ref), "   ", str(tmp_path / "c.wav"))


# ── clonar_disponible: chequeo barato, sin cargar pesos ──────────────────

def test_clonar_disponible_sin_pesos(monkeypatch, tmp_path):
    monkeypatch.setenv("COGNIA_OPENVOICE_DIR", str(tmp_path))
    ok, motivo = clonar.clonar_disponible()
    assert ok is False
    assert "checkpoint.pth" in motivo and str(tmp_path) in motivo


def test_clonar_disponible_ok(monkeypatch, tmp_path):
    conv = tmp_path / "converter"
    conv.mkdir()
    (conv / "checkpoint.pth").write_bytes(b"x")
    (conv / "config.json").write_text("{}")
    monkeypatch.setenv("COGNIA_OPENVOICE_DIR", str(tmp_path))
    monkeypatch.setenv("COGNIA_GPU_PYTHON", sys.executable)
    assert clonar.clonar_disponible() == (True, "")


def test_clonar_disponible_sin_python_gpu(monkeypatch, tmp_path):
    conv = tmp_path / "converter"
    conv.mkdir()
    (conv / "checkpoint.pth").write_bytes(b"x")
    (conv / "config.json").write_text("{}")
    monkeypatch.setenv("COGNIA_OPENVOICE_DIR", str(tmp_path))
    monkeypatch.setenv("COGNIA_GPU_PYTHON", str(tmp_path / "no_python.exe"))
    ok, motivo = clonar.clonar_disponible()
    assert ok is False and "python GPU" in motivo


# ── el CLI por lo menos compila (sin importar torch) ─────────────────────

def test_cli_compila():
    py_compile.compile(str(_REPO / "scripts" / "voz_clonar_cli.py"),
                       doraise=True)
