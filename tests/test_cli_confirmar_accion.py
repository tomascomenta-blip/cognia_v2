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


class TestPermisoDesdeElHiloDeUnaToolConDeadline(unittest.TestCase):
    """Revision adversarial 2026-08-24: con el timeout por tool
    (harness/timeout_tool) TODA tool corre en un hilo worker, y
    _confirmar_accion desde un hilo sin carril de fondo y con tty DENEGABA
    con 'cli.permiso.hilo_sin_carril': en el despacho inline (COGNIA_SIN_FONDO
    =1, /lazo, bucle legacy) el dueno jamas veia la pregunta y todo comando
    CONFIRM se rechazaba. Ahora la pregunta SUBE al hilo que espera la tool."""

    def _arnes(self):
        import threading
        import cognia.ux.selector as selector
        from cognia.harness import timeout_tool as tt
        llamadas, avisos = [], []
        parches = [
            patch.object(cli_mod, "_preguntar_en_consola",
                         lambda k, d: (llamadas.append(
                             threading.current_thread().name), True)[1]),
            patch.object(selector, "hay_tty", lambda: True),
            patch.object(cli_mod, "_CORRIDA", None),
            patch.object(cli_mod, "_aviso_degradado",
                         lambda o, m: avisos.append(o)),
            patch.object(permissions_mod, "needs_confirmation",
                         lambda k, d: True),
        ]
        return tt, parches, llamadas, avisos

    def test_desde_el_worker_pregunta_en_el_principal(self):
        import threading
        tt, parches, llamadas, avisos = self._arnes()
        res = {}

        def _tool(a, ctx):
            res["hilo"] = threading.current_thread().name
            return cli_mod._confirmar_accion("shell", "git push origin main")

        with patch.multiple(cli_mod) if False else _apilar(parches):
            out, agotada, _ = tt.correr_con_deadline(_tool, "probe", "", {}, 5)
        self.assertTrue(out)
        self.assertFalse(agotada)
        self.assertEqual(llamadas, [threading.main_thread().name])
        self.assertNotEqual(res["hilo"], threading.main_thread().name)
        self.assertEqual(avisos, [])

    def test_la_espera_del_permiso_no_consume_el_deadline(self):
        """Carril de fondo simulado: _preguntar_desde_hilo tarda 1,2 s (el
        dueno pensando) con un deadline de 0,6 s. La tool NO se agota."""
        tt, parches, llamadas, avisos = self._arnes()
        import time

        def _lento(k, d):
            time.sleep(1.2)
            return True

        parches.append(patch.object(cli_mod, "_preguntar_desde_hilo", _lento))
        with _apilar(parches):
            with patch.dict("os.environ", {tt.ENV_GRACIA: "0"}):
                out, agotada, _ = tt.correr_con_deadline(
                    lambda a, c: cli_mod._confirmar_accion("shell", "x"),
                    "probe", "", {}, 0.6)
        self.assertTrue(out)
        self.assertFalse(agotada)
        self.assertEqual(avisos, [])


def _apilar(parches):
    import contextlib
    pila = contextlib.ExitStack()
    for p in parches:
        pila.enter_context(p)
    return pila
