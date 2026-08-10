# -*- coding: utf-8 -*-
"""Tests del backend de musica (SymphonyGen + render) -- CPU puro, sin GPU.

POR QUE con subprocess mockeado: el contrato critico es el COMANDO y el ENV
que se le pasan al CLI de venv312gpu (PYTHONPATH/ASSET_DIR/WORK_DIR, flags,
python correcto) y la degradacion legible (timeout que MATA, stdout
contaminado, exit code). Nada de esto necesita torch ni la GPU.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from cognia.musica import render, symphony_backend


# ---------------------------------------------------------------- helpers

class _PopenFalso:
    """Captura cmd/env/cwd y devuelve un stdout fijado por el test."""

    ultimo = None

    salida = json.dumps({"ok": True, "midis": ["a.mid"], "seg": 1.0})
    error = ""
    codigo = 0
    lanza_timeout = False

    def __init__(self, cmd, stdout=None, stderr=None, text=None,
                 encoding=None, errors=None, env=None, cwd=None, **kw):
        _PopenFalso.ultimo = self
        self.cmd = cmd
        self.env = env
        self.cwd = cwd
        self.returncode = _PopenFalso.codigo
        self.matado = False
        self._comunicados = 0

    def communicate(self, timeout=None):
        self._comunicados += 1
        if _PopenFalso.lanza_timeout and self._comunicados == 1:
            raise subprocess.TimeoutExpired(self.cmd, timeout)
        return _PopenFalso.salida, _PopenFalso.error

    def kill(self):
        self.matado = True


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    """Vendor + pesos + python GPU falsos y completos en tmp."""
    vendor = tmp_path / "vendor"
    (vendor / "arch" / "symph").mkdir(parents=True)
    (vendor / "arch" / "symph" / "generator.py").write_text("# falso", encoding="utf-8")
    pesos = tmp_path / "pesos"
    pesos.mkdir()
    (pesos / "stage_one_pretrained.pt").write_bytes(b"pt")
    (pesos / "grpo_clamp+track_epoch_6.pt").write_bytes(b"pt")
    py = tmp_path / "venvgpu" / "Scripts" / "python.exe"
    py.parent.mkdir(parents=True)
    py.write_bytes(b"exe")

    monkeypatch.setenv("COGNIA_SYMPHONYGEN_SRC", str(vendor))
    monkeypatch.setenv("COGNIA_SYMPHONYGEN_PESOS", str(pesos))
    monkeypatch.setenv("COGNIA_SYMPHONYGEN_PY", str(py))

    # Estado limpio del Popen falso en cada test.
    _PopenFalso.ultimo = None
    _PopenFalso.salida = json.dumps({"ok": True, "midis": ["a.mid"], "seg": 1.0})
    _PopenFalso.error = ""
    _PopenFalso.codigo = 0
    _PopenFalso.lanza_timeout = False
    monkeypatch.setattr(subprocess, "Popen", _PopenFalso)
    return {"vendor": vendor, "pesos": pesos, "py": py, "tmp": tmp_path}


# ------------------------------------------------------- musica_disponible

def test_disponible_ok(entorno):
    ok, motivo = symphony_backend.musica_disponible()
    assert ok, motivo
    assert motivo == ""


def test_disponible_sin_vendor(entorno, monkeypatch, tmp_path):
    monkeypatch.setenv("COGNIA_SYMPHONYGEN_SRC", str(tmp_path / "no_existe"))
    ok, motivo = symphony_backend.musica_disponible()
    assert not ok
    assert "COGNIA_SYMPHONYGEN_SRC" in motivo


def test_disponible_sin_checkpoint(entorno):
    (entorno["pesos"] / "grpo_clamp+track_epoch_6.pt").unlink()
    ok, motivo = symphony_backend.musica_disponible()
    assert not ok
    assert "grpo_clamp+track_epoch_6.pt" in motivo


def test_disponible_sin_python_gpu(entorno, monkeypatch, tmp_path):
    monkeypatch.setenv("COGNIA_SYMPHONYGEN_PY", str(tmp_path / "nope.exe"))
    ok, motivo = symphony_backend.musica_disponible()
    assert not ok
    assert "python GPU" in motivo


def test_disponible_venv_sin_torch(entorno):
    # Con layout de venv (Lib/site-packages presente) pero sin torch -> False.
    site = entorno["py"].parent.parent / "Lib" / "site-packages"
    site.mkdir(parents=True)
    ok, motivo = symphony_backend.musica_disponible()
    assert not ok
    assert "torch" in motivo
    # y con torch presente vuelve a estar disponible
    (site / "torch").mkdir()
    (site / "torch" / "__init__.py").write_text("", encoding="utf-8")
    ok, motivo = symphony_backend.musica_disponible()
    assert ok, motivo


# ---------------------------------------------------------------- orquestar

def test_orquestar_comando_y_env(entorno, tmp_path):
    salida = tmp_path / "out"
    midis = symphony_backend.orquestar(None, str(salida), grupo=3)
    assert midis == ["a.mid"]

    p = _PopenFalso.ultimo
    assert p is not None
    # python GPU correcto (la contingencia COGNIA_SYMPHONYGEN_PY manda)
    assert p.cmd[0] == str(entorno["py"])
    assert p.cmd[1].endswith("musica_orquestar_cli.py")
    assert "--salida" in p.cmd and str(salida.resolve()) in p.cmd
    i = p.cmd.index("--grupo")
    assert p.cmd[i + 1] == "3"
    i = p.cmd.index("--checkpoint")
    assert p.cmd[i + 1] == "grpo_clamp+track_epoch_6.pt"
    assert "--midi" not in p.cmd
    # env del vendor (arch/config.py los lee al importar)
    assert p.env["PYTHONPATH"] == str(entorno["vendor"])
    assert p.env["ASSET_DIR"] == str(entorno["pesos"])
    assert p.env["WORK_DIR"].endswith("symphonygen_work")
    assert p.cwd == str(entorno["vendor"])


def test_orquestar_con_midi_condicion(entorno, tmp_path):
    midi = tmp_path / "tema.mid"
    midi.write_bytes(b"MThd")
    symphony_backend.orquestar(str(midi), str(tmp_path / "out"))
    p = _PopenFalso.ultimo
    i = p.cmd.index("--midi")
    assert p.cmd[i + 1] == str(midi.resolve())


def test_orquestar_midi_inexistente(entorno, tmp_path):
    with pytest.raises(RuntimeError, match="no existe el MIDI"):
        symphony_backend.orquestar(str(tmp_path / "nada.mid"), str(tmp_path / "out"))
    assert _PopenFalso.ultimo is None  # ni lanzo el subprocess


def test_orquestar_timeout_mata_y_reporta(entorno, tmp_path):
    _PopenFalso.lanza_timeout = True
    with pytest.raises(RuntimeError, match="timeout tras 5s"):
        symphony_backend.orquestar(None, str(tmp_path / "out"), timeout=5)
    assert _PopenFalso.ultimo.matado


def test_orquestar_stdout_contaminado(entorno, tmp_path):
    _PopenFalso.salida = "Loading model from x.pt\nSaved generated song 0\n"
    with pytest.raises(RuntimeError, match="no es JSON"):
        symphony_backend.orquestar(None, str(tmp_path / "out"))


def test_orquestar_stdout_vacio(entorno, tmp_path):
    _PopenFalso.salida = ""
    with pytest.raises(RuntimeError, match="contrato JSON"):
        symphony_backend.orquestar(None, str(tmp_path / "out"))


def test_orquestar_cli_reporta_fallo(entorno, tmp_path):
    _PopenFalso.salida = json.dumps({"ok": False, "error": "UnpicklingError: x"})
    with pytest.raises(RuntimeError, match="UnpicklingError"):
        symphony_backend.orquestar(None, str(tmp_path / "out"))


def test_orquestar_exit_no_cero(entorno, tmp_path):
    _PopenFalso.codigo = 1
    _PopenFalso.error = "Traceback...\nRuntimeError: sin CUDA"
    with pytest.raises(RuntimeError, match=r"(?s)codigo 1.*sin CUDA"):
        symphony_backend.orquestar(None, str(tmp_path / "out"))


def test_orquestar_ok_sin_midis(entorno, tmp_path):
    _PopenFalso.salida = json.dumps({"ok": True, "midis": [], "seg": 1})
    with pytest.raises(RuntimeError, match="sin MIDIs"):
        symphony_backend.orquestar(None, str(tmp_path / "out"))


def test_gpu_python_cadena_fallback(entorno, monkeypatch):
    # Sin COGNIA_SYMPHONYGEN_PY manda COGNIA_GPU_PYTHON (flag existente).
    monkeypatch.delenv("COGNIA_SYMPHONYGEN_PY")
    monkeypatch.setenv("COGNIA_GPU_PYTHON", r"C:\otro\python.exe")
    # gpu_env (agente A3) puede existir o no: si existe debe respetar el
    # mismo flag; si no, cae al fallback propio. Ambos dan lo mismo.
    assert symphony_backend._gpu_python() == r"C:\otro\python.exe"
    # y sin ningun flag: el venv312gpu del repo (mismo default que gpu_env)
    monkeypatch.delenv("COGNIA_GPU_PYTHON")
    assert symphony_backend._gpu_python().endswith(
        str(Path("venv312gpu") / "Scripts" / "python.exe"))


# ------------------------------------------------------------------- render

def test_fluidsynth_disponible_sin_binario(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda n: None)
    ok, motivo = render.fluidsynth_disponible()
    assert not ok
    assert "PATH" in motivo


def test_fluidsynth_disponible_sin_soundfont(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", lambda n: r"C:\fs\fluidsynth.exe")
    monkeypatch.setenv("COGNIA_SOUNDFONT", str(tmp_path / "no.sf2"))
    ok, motivo = render.fluidsynth_disponible()
    assert not ok
    assert "COGNIA_SOUNDFONT" in motivo


def test_fluidsynth_disponible_ok(monkeypatch, tmp_path):
    sf = tmp_path / "gm.sf2"
    sf.write_bytes(b"sf2")
    monkeypatch.setattr("shutil.which", lambda n: r"C:\fs\fluidsynth.exe")
    monkeypatch.setenv("COGNIA_SOUNDFONT", str(sf))
    ok, motivo = render.fluidsynth_disponible()
    assert ok, motivo


def test_midi_a_wav_linea_fluidsynth(monkeypatch, tmp_path):
    midi = tmp_path / "song.mid"
    midi.write_bytes(b"MThd")
    sf = tmp_path / "gm.sf2"
    sf.write_bytes(b"sf2")
    monkeypatch.setenv("COGNIA_SOUNDFONT", str(sf))
    monkeypatch.setattr("shutil.which", lambda n: "fluidsynth")

    capturado = {}

    def _run_falso(cmd, capture_output=None, text=None, encoding=None,
                   errors=None, timeout=None):
        capturado["cmd"] = cmd
        capturado["timeout"] = timeout
        Path(cmd[cmd.index("-F") + 1]).write_bytes(b"RIFF" + b"\0" * 100)

        class _R:
            returncode = 0
            stderr = ""
        return _R()

    monkeypatch.setattr(subprocess, "run", _run_falso)
    wav = render.midi_a_wav(str(midi))
    assert wav == str(midi.with_suffix(".wav"))
    assert capturado["cmd"] == [
        "fluidsynth", "-ni", str(sf), str(midi), "-F", wav, "-r", "44100"]
    assert capturado["timeout"] == 300


def test_midi_a_wav_sin_soundfont(monkeypatch, tmp_path):
    midi = tmp_path / "song.mid"
    midi.write_bytes(b"MThd")
    monkeypatch.setenv("COGNIA_SOUNDFONT", str(tmp_path / "no.sf2"))
    with pytest.raises(RuntimeError, match="COGNIA_SOUNDFONT"):
        render.midi_a_wav(str(midi))


def test_midi_a_wav_timeout(monkeypatch, tmp_path):
    midi = tmp_path / "song.mid"
    midi.write_bytes(b"MThd")
    sf = tmp_path / "gm.sf2"
    sf.write_bytes(b"sf2")
    monkeypatch.setenv("COGNIA_SOUNDFONT", str(sf))

    def _run_cuelga(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))

    monkeypatch.setattr(subprocess, "run", _run_cuelga)
    with pytest.raises(RuntimeError, match="timeout tras 7s"):
        render.midi_a_wav(str(midi), timeout=7)


def test_midi_a_wav_wav_vacio(monkeypatch, tmp_path):
    # fluidsynth con exit 0 pero WAV vacio -> error VISIBLE, no vacio silencioso.
    midi = tmp_path / "song.mid"
    midi.write_bytes(b"MThd")
    sf = tmp_path / "gm.sf2"
    sf.write_bytes(b"sf2")
    monkeypatch.setenv("COGNIA_SOUNDFONT", str(sf))

    def _run_vacio(cmd, **kw):
        Path(cmd[cmd.index("-F") + 1]).write_bytes(b"")

        class _R:
            returncode = 0
            stderr = ""
        return _R()

    monkeypatch.setattr(subprocess, "run", _run_vacio)
    with pytest.raises(RuntimeError, match="vacio"):
        render.midi_a_wav(str(midi))
