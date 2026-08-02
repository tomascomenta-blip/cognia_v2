"""
tests/test_cli_confirmar_accion.py
==================================
Regresion del gate central de permisos del REPL (cognia/cli.py::_confirmar_accion).

Contexto: _confirmar_accion se inyecta como ctx['confirm'] del loop del agente,
y ahi lo leen sentinel.evaluar_shell (nivel CONFIRM) y las pantalla_*
destructivas. La version previa devolvia True ante CUALQUIER excepcion del
clasificador (cognia.console.permissions), asi que un import roto o un error de
runtime en ese modulo convertia el default-deny del sentinel en "proceder sin
preguntar" — un debilitamiento de seguridad silencioso. El contrato correcto es
DENY (False) y dejar rastro por logging.warning.

Los tests parchean cognia.console.permissions.needs_confirmation (el nombre que
_confirmar_accion importa dentro de la funcion) para simular el fallo.
"""
from __future__ import annotations

import builtins
import logging
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

import cognia.cli as cli_mod  # noqa: E402
import cognia.console.permissions as permissions_mod  # noqa: E402


class TestConfirmarAccionDenyOnException(unittest.TestCase):

    def test_excepcion_del_clasificador_deniega(self):
        """needs_confirmation que lanza => False (deny), no True."""
        def _boom(kind, detalle):
            raise RuntimeError("clasificador roto")

        with patch.object(permissions_mod, "needs_confirmation", _boom):
            # input() no debe ni llegar a llamarse: el deny es inmediato.
            with patch.object(builtins, "input",
                              lambda *a, **k: self.fail("no debe preguntar")):
                self.assertFalse(
                    cli_mod._confirmar_accion("shell_exec", "rm -rf /"))

    def test_import_roto_del_modulo_de_permisos_deniega(self):
        """Si cognia.console.permissions ni siquiera importa => deny."""
        real_import = builtins.__import__

        def _import_falla(name, *args, **kwargs):
            if name == "cognia.console.permissions":
                raise ImportError("modulo de permisos ausente")
            return real_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", _import_falla):
            with patch.object(builtins, "input",
                              lambda *a, **k: self.fail("no debe preguntar")):
                self.assertFalse(
                    cli_mod._confirmar_accion("shell_exec", "format C:"))

    def test_el_fallo_queda_logueado_como_warning(self):
        """El deny no es silencioso: se loguea con nivel WARNING."""
        def _boom(kind, detalle):
            raise RuntimeError("clasificador roto")

        with patch.object(permissions_mod, "needs_confirmation", _boom):
            with self.assertLogs(cli_mod.__name__, level=logging.WARNING) as cm:
                self.assertFalse(
                    cli_mod._confirmar_accion("shell_exec", "shutdown /s"))
        self.assertTrue(any("permisos" in linea.lower() for linea in cm.output),
                        f"el warning no menciona el clasificador: {cm.output}")

    def test_accion_no_peligrosa_sigue_pasando_sin_preguntar(self):
        """El deny-on-exception no debe romper el camino feliz: si el
        clasificador dice que NO hace falta confirmar, devuelve True."""
        with patch.object(permissions_mod, "needs_confirmation",
                          lambda kind, detalle: False):
            with patch.object(builtins, "input",
                              lambda *a, **k: self.fail("no debe preguntar")):
                self.assertTrue(
                    cli_mod._confirmar_accion("shell_exec", "dir"))

    def test_accion_peligrosa_pregunta_y_respeta_la_respuesta(self):
        """Camino normal con confirmacion: 's' procede, 'n' cancela."""
        with patch.object(permissions_mod, "needs_confirmation",
                          lambda kind, detalle: True):
            with patch.object(builtins, "input", lambda *a, **k: "s"):
                self.assertTrue(
                    cli_mod._confirmar_accion("shell_exec", "rm -rf x"))
            with patch.object(builtins, "input", lambda *a, **k: "n"):
                self.assertFalse(
                    cli_mod._confirmar_accion("shell_exec", "rm -rf x"))


if __name__ == "__main__":
    unittest.main()
