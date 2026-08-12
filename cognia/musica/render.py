# -*- coding: utf-8 -*-
"""Render MIDI -> WAV con fluidsynth + soundfont GM.

POR QUE fluidsynth y no el midi2audio del vendor: utils/midi2audio.py de
SymphonyGen depende de MuseScore AppImage + xvfb (Linux-only, verificado en
el codigo). En Windows el render de la casa es fluidsynth con FluidR3_GM.sf2.

Soundfont por defecto: COGNIA_SOUNDFONT o ~/.cognia/models/FluidR3_GM.sf2
(con ~/.cognia/soundfonts/ como ruta alterna aceptada si ya existe ahi).
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional


def _soundfont_default() -> Path:
    """Ruta del .sf2 en call-time (env primero; luego las dos rutas de casa)."""
    fijado = os.environ.get("COGNIA_SOUNDFONT", "").strip()
    if fijado:
        return Path(fijado)
    primaria = Path.home() / ".cognia" / "models" / "FluidR3_GM.sf2"
    alterna = Path.home() / ".cognia" / "soundfonts" / "FluidR3_GM.sf2"
    if not primaria.is_file() and alterna.is_file():
        return alterna
    return primaria


def fluidsynth_disponible() -> tuple[bool, str]:
    """(ok, motivo). Barato: binario en PATH + soundfont presente."""
    exe = shutil.which("fluidsynth")
    if not exe:
        return False, ("fluidsynth no esta en el PATH "
                       "(winget install FluidSynth.FluidSynth)")
    sf = _soundfont_default()
    if not sf.is_file():
        return False, (f"falta el soundfont {sf} "
                       "(descarga FluidR3_GM.sf2 o fija COGNIA_SOUNDFONT)")
    return True, ""


def midi_a_wav(midi: str, wav: Optional[str] = None, *,
               soundfont: Optional[str] = None, timeout: float = 300,
               seco: bool = False) -> str:
    """Renderiza un .mid a .wav 44100 Hz. Devuelve la ruta del WAV.

    seco=True apaga la reverb y el chorus que fluidsynth trae ACTIVOS por
    defecto (-R 0 -C 0): lo pide produccion para que cada stem entre limpio
    a su cadena por rol; el render directo queda con la sala default.

    POR QUE valida el tamano de salida: fluidsynth puede salir con codigo 0
    dejando un WAV vacio (soundfont corrupto) -- el fallo tipico del repo es
    el vacio silencioso, asi que aqui se convierte en RuntimeError legible.
    """
    ruta_midi = Path(midi)
    if not ruta_midi.is_file():
        raise RuntimeError(f"render: no existe el MIDI {midi}")
    sf = Path(soundfont) if soundfont else _soundfont_default()
    if not sf.is_file():
        raise RuntimeError(
            f"render: falta el soundfont {sf} (fija COGNIA_SOUNDFONT)")
    ruta_wav = Path(wav) if wav else ruta_midi.with_suffix(".wav")
    ruta_wav.parent.mkdir(parents=True, exist_ok=True)

    exe = shutil.which("fluidsynth") or "fluidsynth"
    # opciones ANTES de los posicionales: fluidsynth >=2.6 rechaza -F despues
    # de los archivos ("only -b option is allowed here"); el orden POSIX
    # funciona igual en las versiones previas
    cmd = [exe, "-ni", "-F", str(ruta_wav), "-r", "44100"]
    if seco:
        # -R 0 -C 0: sin la reverb/chorus default del synth. Un stem que
        # despues recibe su sala por rol (pedalboard) no puede traer la
        # sala del synth ya horneada: serian dos reverbs en serie y el
        # "BAJO sin reverb" de produccion seria mentira.
        cmd += ["-R", "0", "-C", "0"]
    cmd += [str(sf), str(ruta_midi)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        # subprocess.run ya mato al hijo al vencer el timeout
        raise RuntimeError(f"render: timeout tras {timeout:.0f}s con {ruta_midi.name}")
    except FileNotFoundError:
        raise RuntimeError("render: fluidsynth no esta en el PATH "
                           "(winget install FluidSynth.FluidSynth)")
    if proc.returncode != 0:
        cola = (proc.stderr or "").strip()[-400:]
        raise RuntimeError(
            f"render: fluidsynth salio con codigo {proc.returncode}: {cola or '(sin stderr)'}")
    if not ruta_wav.is_file() or ruta_wav.stat().st_size == 0:
        raise RuntimeError(f"render: fluidsynth no escribio {ruta_wav} (WAV vacio)")
    return str(ruta_wav)
