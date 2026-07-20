"""
tests/test_cli_modelo.py
========================
Tests de regresion del comando /modelo (conmutacion en caliente del GGUF):

  (a) el registry MODEL_GGUF_REGISTRY contiene 3b y 7b con rutas relativas
      .gguf y resolve_gguf_path() resuelve a absoluta contra el root del repo;
  (b) /modelo sin args no revienta sin servidor ni orquestador;
  (c) /modelo con clave invalida da error claro sin tocar el backend ni el env;
  (d) /modelo con clave valida pero GGUF ausente en disco avisa y no toca el env;
  (e) contrato de _LlamaServerBackend.stop(): False si el server fue adoptado
      (proceso externo) y sigue vivo, True si el puerto quedo libre.

Sin mocks del modelo real: los tests solo simulan la AUSENCIA del server.
"""

import io
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


def _capture(fn, *args, **kwargs):
    """Llama fn(*args) y devuelve todo lo impreso a stdout como string."""
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        fn(*args, **kwargs)
    finally:
        sys.stdout = old
    return buf.getvalue()


def _ai_sin_orquestador():
    """ai minimo sin orquestador cacheado (NO MagicMock: getattr debe dar None)."""
    return types.SimpleNamespace(_orchestrator=None)


class TestModelRegistry(unittest.TestCase):
    """(a) registry y resolucion de rutas en model_constants."""

    def test_registry_contiene_3b_y_7b_gguf(self):
        from shattering.model_constants import MODEL_GGUF_REGISTRY
        self.assertIn("3b", MODEL_GGUF_REGISTRY)
        self.assertIn("7b", MODEL_GGUF_REGISTRY)
        for key, rel in MODEL_GGUF_REGISTRY.items():
            self.assertTrue(rel.endswith(".gguf"),
                            f"registry[{key}] no termina en .gguf: {rel}")
            # Rutas RELATIVAS al repo (el repo puede moverse de disco)
            self.assertFalse(Path(rel).is_absolute(),
                             f"registry[{key}] debe ser relativa: {rel}")

    def test_default_es_clave_del_registry(self):
        from shattering.model_constants import (
            MODEL_GGUF_DEFAULT, MODEL_GGUF_REGISTRY,
        )
        self.assertIn(MODEL_GGUF_DEFAULT, MODEL_GGUF_REGISTRY)

    def test_resolve_gguf_path_absoluta_bajo_repo(self):
        import shattering.model_constants as mc
        repo_root = Path(mc.__file__).resolve().parent.parent
        for key in mc.MODEL_GGUF_REGISTRY:
            p = mc.resolve_gguf_path(key)
            self.assertIsNotNone(p)
            self.assertTrue(p.is_absolute())
            self.assertIn(repo_root, p.parents,
                          f"resolve_gguf_path({key}) no cuelga del repo: {p}")

    def test_resolve_gguf_path_clave_invalida_none(self):
        from shattering.model_constants import resolve_gguf_path
        self.assertIsNone(resolve_gguf_path("13b"))


class TestSlashModelo(unittest.TestCase):
    """(b)-(d) comportamiento del comando sin servidor."""

    def test_sin_args_no_revienta_sin_servidor(self):
        import cognia.cli as cli_mod
        with patch.dict(os.environ):
            os.environ.pop("LLAMA_GGUF_PATH", None)
            out = _capture(cli_mod._slash_modelo, _ai_sin_orquestador(), "")
        self.assertIn("Modelo activo", out)
        self.assertIn("3b", out)
        self.assertIn("7b", out)
        # Marcadores ASCII de existencia en disco
        self.assertTrue("[OK]" in out or "[NO]" in out)

    def test_clave_invalida_error_claro_sin_tocar_env(self):
        import cognia.cli as cli_mod
        with patch.dict(os.environ):
            os.environ.pop("LLAMA_GGUF_PATH", None)
            out = _capture(cli_mod._slash_modelo, _ai_sin_orquestador(), "13b")
            self.assertIsNone(os.environ.get("LLAMA_GGUF_PATH"),
                              "clave invalida no debe setear LLAMA_GGUF_PATH")
        self.assertIn("desconocida", out)
        self.assertIn("13b", out)

    def test_gguf_ausente_en_disco_no_toca_env(self):
        import cognia.cli as cli_mod
        import shattering.model_constants as mc
        with patch.dict(mc.MODEL_GGUF_REGISTRY,
                        {"fake": "model_shards/no_existe/fake.gguf"}):
            with patch.dict(os.environ):
                os.environ.pop("LLAMA_GGUF_PATH", None)
                out = _capture(cli_mod._slash_modelo, _ai_sin_orquestador(), "fake")
                self.assertIsNone(os.environ.get("LLAMA_GGUF_PATH"),
                                  "GGUF ausente no debe setear LLAMA_GGUF_PATH")
        self.assertIn("no encontrado", out)

    def test_registrado_en_help_y_dispatch(self):
        import cognia.cli as cli_mod
        self.assertIn("/modelo", cli_mod._CMD_DESCRIPTIONS)
        self.assertIn("/modelo", cli_mod._CMD_DETAILS)
        self.assertTrue(callable(getattr(cli_mod, "_slash_modelo", None)))


class TestLlamaServerStopContract(unittest.TestCase):
    """(e) stop() reporta si el puerto quedo libre (server adoptado vs propio)."""

    def _backend_sin_init(self, ping_alive):
        # __new__ evita el __init__ (que arrancaria/adoptaria un server real);
        # solo se setean los attrs que stop() usa. Simula AUSENCIA/presencia
        # del server, no al modelo.
        from node.llama_backend import _LlamaServerBackend
        b = _LlamaServerBackend.__new__(_LlamaServerBackend)
        b._proc = None              # server adoptado: no es nuestro proceso
        b._port = 9999
        b._ping = lambda: ping_alive
        return b

    def test_stop_adoptado_vivo_devuelve_false(self):
        b = self._backend_sin_init(ping_alive=True)
        self.assertFalse(b.stop())

    def test_stop_puerto_libre_devuelve_true(self):
        b = self._backend_sin_init(ping_alive=False)
        self.assertTrue(b.stop())

    def test_facade_sin_stop_devuelve_true(self):
        # Impl in-process (sin stop()): el facade devuelve True (nada que parar)
        from node.llama_backend import LlamaBackend
        backend = LlamaBackend(types.SimpleNamespace())
        self.assertTrue(backend.stop())


if __name__ == "__main__":
    unittest.main()
