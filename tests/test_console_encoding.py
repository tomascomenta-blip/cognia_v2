"""
Robustez de encoding en la consola de Windows (cp1252).

Regresion: la Curiosidad Pasiva imprimia emojis (U+2728 U+23ED U+274C) que
LANZABAN UnicodeEncodeError en cp1252 y, como el except del hilo tambien imprimia
un emoji, re-lanzaban -> el error se tragaba y el hilo moria. Ademas se endurece
stdout/stderr al arranque para que ningun print con simbolos fuera de cp1252 pueda
tumbar un comando.
"""

import inspect
import io

import cognia_v3.core.curiosidad_pasiva as cp
from cognia.__main__ import _harden_console_encoding


def test_harden_console_encoding_never_raises():
    # Idempotente y a prueba de streams que no soportan reconfigure.
    _harden_console_encoding()
    _harden_console_encoding()


def test_reconfigured_cp1252_stream_tolerates_emoji():
    # El mecanismo: errors='replace' hace que un stream cp1252 NO crashee al
    # escribir un emoji (pasa a '?'), en vez de lanzar UnicodeEncodeError.
    wrapper = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    wrapper.reconfigure(errors="replace")
    wrapper.write("hola ✨ salte ⏭ error ❌")  # no debe lanzar
    wrapper.flush()


def test_curiosidad_pasiva_loop_prints_are_ascii():
    # El cuerpo del loop (donde estaban los print con emoji) debe ser ASCII puro
    # en sus lineas de print, para no depender del encoding de la consola.
    src = inspect.getsource(cp.CuriosidadPasiva._loop)
    for ln in src.splitlines():
        if "print(" in ln:
            non_ascii = [c for c in ln if ord(c) > 127]
            assert not non_ascii, f"print no-ASCII en el loop: {ln.strip()!r} -> {non_ascii}"
