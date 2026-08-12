# -*- coding: utf-8 -*-
"""Backend de transcripcion audio -> MIDI por subprocess (venv symphonygen312).

POR QUE subprocess y no import: misma regla que symphony_backend -- cognia/
no importa torch, y Demucs/Basic Pitch viven en el venv dedicado de musica.
El CLI pesado es scripts/musica_transcribir_cli.py (contrato: UNA linea JSON
por stdout, progreso por stderr).

POR QUE el mismo venv que SymphonyGen: torch cu128 ya esta ahi y los dos
son "musica en GPU"; COGNIA_TRANSCRIBIR_PY permite separarlos si algun dia
sus dependencias chocan.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _python_transcriptor() -> str:
    """Python que corre el CLI pesado (env en CALL-time, leccion _root_actual)."""
    propio = os.environ.get("COGNIA_TRANSCRIBIR_PY", "").strip()
    if propio:
        return propio
    heredado = os.environ.get("COGNIA_SYMPHONYGEN_PY", "").strip()
    if heredado:
        return heredado
    return str(Path.home() / ".cognia" / "venvs" / "symphonygen312"
               / "Scripts" / "python.exe")


def transcribir_disponible() -> tuple[bool, str]:
    """(ok, motivo). Chequeo BARATO: python + demucs/basic_pitch presentes."""
    py = Path(_python_transcriptor())
    if not py.is_file():
        return False, (f"no existe el python de transcripcion {py} "
                       "(fija COGNIA_TRANSCRIBIR_PY o COGNIA_SYMPHONYGEN_PY)")
    site = py.parent.parent / "Lib" / "site-packages"
    if site.is_dir():
        for mod in ("demucs", "basic_pitch"):
            if not (site / mod / "__init__.py").is_file():
                return False, (f"el venv {py.parent.parent.name} no tiene {mod} "
                               "(pip install demucs basic-pitch)")
    return True, ""


def transcribir(audio: str, salida_dir: str, *, sin_stems: bool = False,
                sin_drums: bool = False, timeout: float = 900) -> str:
    """Transcribe un audio a MIDI multi-pista. Devuelve la ruta .mid.

    Con sin_stems=True salta Demucs (audio mono-instrumental o ya separado).
    Levanta RuntimeError con motivo legible; jamas cuelga (kill al timeout).
    """
    audio_p = Path(audio).resolve()
    if not audio_p.is_file():
        raise RuntimeError(f"transcribir: no existe el audio {audio_p}")
    salida = Path(salida_dir).resolve()
    salida.mkdir(parents=True, exist_ok=True)

    repo = Path(__file__).resolve().parents[2]
    cmd = [_python_transcriptor(),
           str(repo / "scripts" / "musica_transcribir_cli.py"),
           "--audio", str(audio_p), "--salida", str(salida)]
    if sin_stems:
        cmd.append("--sin-stems")
    if sin_drums:
        cmd.append("--sin-drums")

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace")
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.communicate(timeout=10)
        except Exception:
            pass
        raise RuntimeError(f"transcribir: timeout tras {timeout:.0f}s con {audio_p.name}")

    if proc.returncode != 0:
        cola = (err or "").strip()[-800:]
        raise RuntimeError(
            f"transcribir: el CLI salio con codigo {proc.returncode}: {cola or '(sin stderr)'}")

    lineas = [l for l in (out or "").splitlines() if l.strip()]
    if not lineas:
        raise RuntimeError("transcribir: el CLI no imprimio nada por stdout")
    try:
        datos = json.loads(lineas[-1])
    except (json.JSONDecodeError, ValueError):
        raise RuntimeError("transcribir: stdout contaminado: "
                           f"{lineas[-1][:200]!r}")
    if not datos.get("ok"):
        raise RuntimeError(f"transcribir: el CLI reporto fallo: "
                           f"{datos.get('error', '(sin detalle)')}")
    midi = datos.get("midi", "")
    if not midi or not Path(midi).is_file():
        raise RuntimeError("transcribir: el CLI dijo ok pero el MIDI no existe")
    return midi
