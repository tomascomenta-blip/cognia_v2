"""
Regresion: /crear moria con UnicodeEncodeError antes de generar nada.

Causa medida el 2026-07-19: en Windows con stdout cp1252 (tuberia o
redireccion), el primer print con emoji de run_program_hobby lanzaba
'charmap' codec can't encode character '\\U0001f3a8' y tumbaba la sesion.
El arreglo existia en cli.repl() pero no cubria las vias no interactivas
(/dormir -> maybe_run_hobby, create_program(), uso programatico).

Dos detalles de estos tests, ambos medidos, no supuestos:

  1. Escriben con sys.stdout.write() y no con print(). Es la misma ruta
     (print delega en write) pero no la intercepta la captura de pytest.
  2. El cambio de sys.stdout se hace DENTRO del test, nunca en un fixture:
     medido que un monkeypatch de sys.stdout en fase setup lo pisa el
     CaptureManager de pytest al entrar en la fase call (fixture -> utf-8,
     inline -> cp1252).
"""

import io
import sys

import pytest

from cognia.consola import forzar_utf8

EMOJI_QUE_ROMPIA = "\U0001f3a8"   # el mismo que mataba a /crear


def _poner_stdout_cp1252(monkeypatch):
    """Imita el stdout de Windows cuando la salida no es una consola UTF-8."""
    falso = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", falso)
    monkeypatch.setattr(
        sys, "stderr",
        io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict"))
    return falso


def test_cp1252_sin_fix_revienta_con_emoji(monkeypatch):
    """Sin el fix el emoji mata la escritura: esto es lo que le pasaba a /crear."""
    falso = _poner_stdout_cp1252(monkeypatch)
    assert sys.stdout is falso

    with pytest.raises(UnicodeEncodeError):
        sys.stdout.write(EMOJI_QUE_ROMPIA + " [ProgramCreator] Iniciando sesion\n")
        sys.stdout.flush()


def test_forzar_utf8_deja_pasar_emoji_y_cajas(monkeypatch):
    """Con el fix, los mismos caracteres que rompian /crear pasan sin excepcion."""
    falso = _poner_stdout_cp1252(monkeypatch)
    crudo = falso.buffer

    assert forzar_utf8() is True

    sys.stdout.write(EMOJI_QUE_ROMPIA + " [ProgramCreator] Iniciando sesion\n")
    sys.stdout.write("── Intento 1/2 ──\n")
    sys.stdout.write("✅ guardado  \U0001f5d1 descartado  ⚠ aviso\n")
    sys.stdout.flush()

    escrito = crudo.getvalue().decode("utf-8")
    assert "[ProgramCreator] Iniciando sesion" in escrito
    assert "Intento 1/2" in escrito
    assert EMOJI_QUE_ROMPIA in escrito


def test_no_toca_stdout_que_ya_es_utf8(monkeypatch):
    """Si ya es UTF-8 no reenvuelve: evita apilar wrappers en cada import."""
    ya_utf8 = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    monkeypatch.setattr(sys, "stdout", ya_utf8)
    monkeypatch.setattr(sys, "stderr", io.TextIOWrapper(io.BytesIO(), encoding="utf-8"))

    assert forzar_utf8() is False
    assert sys.stdout is ya_utf8


def test_es_idempotente(monkeypatch):
    """Segunda llamada no vuelve a envolver (el stream ya reporta utf-8)."""
    _poner_stdout_cp1252(monkeypatch)

    assert forzar_utf8() is True
    primero = sys.stdout
    assert forzar_utf8() is False
    assert sys.stdout is primero
