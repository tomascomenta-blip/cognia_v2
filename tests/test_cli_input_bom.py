"""
tests/test_cli_input_bom.py
===========================
Test de regresion del bug E2E: con stdin pipeado al REPL (python -m cognia),
PowerShell antepone los bytes EF BB BF (BOM UTF-8) al stream, asi que la
PRIMERA linea llega como '<BOM>/comando'. Como ya no empieza con '/', esquiva
TODO el dispatch de slash commands y cae al chat (el LLM respondio a
'/modelo 7b' como mensaje libre).

Segun el encoding con que Python decodifica stdin, el BOM llega como:
  - U+FEFF        (stdin utf-8)
  - '\xef\xbb\xbf'  (stdin cp1252: cada byte decodificado por separado,
                     el caso REAL reproducido en Windows con python 3.12)

El fix es _strip_input_bom() aplicado en el unico punto de lectura del loop
del REPL. Estos tests fallan sin el fix (la funcion no existe / el loop no
la usa) y pasan con el.

Sin modelo ni servidor: solo se testea la sanitizacion y el cableado.
"""

import sys
import inspect
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


class TestStripInputBom(unittest.TestCase):
    """Sanitizacion de la linea leida antes del dispatch."""

    def test_bom_utf8_decodificado(self):
        # stdin utf-8: EF BB BF -> un solo U+FEFF
        from cognia.cli import _strip_input_bom
        raw = _strip_input_bom("\ufeff/ayuda")
        self.assertEqual(raw, "/ayuda")
        self.assertTrue(raw.startswith("/"))

    def test_bom_cp1252_mojibake(self):
        # stdin cp1252 (caso real en Windows): EF BB BF -> 'i dieresis',
        # 'guillemet', 'interrogacion invertida' (tres chars U+00EF U+00BB U+00BF)
        from cognia.cli import _strip_input_bom
        raw = _strip_input_bom("\xef\xbb\xbf/modelo 7b")
        self.assertEqual(raw, "/modelo 7b")
        self.assertTrue(raw.startswith("/"))

    def test_linea_limpia_no_cambia(self):
        from cognia.cli import _strip_input_bom
        self.assertEqual(_strip_input_bom("/modelo 3b"), "/modelo 3b")
        self.assertEqual(_strip_input_bom("hola cognia"), "hola cognia")

    def test_strip_de_whitespace_se_mantiene(self):
        # _get_input() ya hacia .strip(); el sanitizador no debe perderlo
        from cognia.cli import _strip_input_bom
        self.assertEqual(_strip_input_bom("  /salir  \n"), "/salir")
        self.assertEqual(_strip_input_bom("\ufeff  /salir\n"), "/salir")

    def test_texto_libre_con_bom_queda_como_chat_valido(self):
        # Texto libre con BOM tambien debe sanearse (no solo slash commands)
        from cognia.cli import _strip_input_bom
        self.assertEqual(_strip_input_bom("\ufeffhola"), "hola")


class TestReplUsaSanitizador(unittest.TestCase):
    """El loop del REPL debe pasar la linea por _strip_input_bom: si alguien
    revierte el cableado, la primera linea pipeada vuelve a esquivar el
    dispatch aunque la funcion exista."""

    def test_loop_lee_via_strip_input_bom(self):
        from cognia import cli
        src = inspect.getsource(cli.repl)
        self.assertIn("_strip_input_bom(_get_input())", src)


if __name__ == "__main__":
    unittest.main()
