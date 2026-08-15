# -*- coding: utf-8 -*-
"""Regresion: doctor/status/modo diagnostican el backend REAL (GGUF) primero.

Deuda tecnica cazada 2026-07-16: cognia doctor / cognia status / cognia modo
local solo miraban los sistemas viejos (Ollama y shards NPZ). En el install
recomendado (cognia install-model = GGUF sin NPZ):
- doctor terminaba sin verificar inferencia real y el hint decia 'Cognia usa
  los shards locales sin Ollama' (falso hoy);
- status decia 'modo standalone / Ollama: no disponible' en una instalacion
  perfectamente sana;
- modo local respondia 'Faltan los pesos locales' y mandaba a bajar ~1.2GB
  de shards numpy que produccion ya no usa.
"""
import io
import contextlib
from pathlib import Path

import cognia.doctor as doctor
import cognia.__main__ as cmain


def _capture(fn):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn()
    return buf.getvalue()


def test_check_gguf_ok_con_stack_instalado(monkeypatch, tmp_path):
    fake = tmp_path / "modelo.gguf"
    fake.write_bytes(b"gguf")
    import node.llama_backend as lb
    monkeypatch.setattr(lb, "_find_gguf", lambda: fake)
    monkeypatch.delenv("LLAMA_SERVER_PATH", raising=False)
    out = _capture(doctor.check_gguf)
    assert "modelo.gguf" in out and "[OK]" in out


def test_check_gguf_sin_stack_recomienda_install_model(monkeypatch):
    import node.llama_backend as lb
    monkeypatch.setattr(lb, "_find_gguf", lambda: None)
    out = _capture(doctor.check_gguf)
    assert "install-model" in out


def test_hint_ollama_ya_no_miente():
    """El hint viejo decia 'Cognia usa los shards locales sin Ollama'."""
    import inspect
    src = inspect.getsource(doctor.check_ollama)
    assert "shards locales" not in src
    assert "GGUF" in src


def test_doctor_incluye_check_gguf():
    import inspect
    src = inspect.getsource(doctor.run_all)
    assert "check_gguf" in src


def test_status_reporta_backend_gguf(monkeypatch, tmp_path):
    fake = tmp_path / "modelo.gguf"
    fake.write_bytes(b"gguf")
    import node.llama_backend as lb
    monkeypatch.setattr(lb, "_find_gguf", lambda: fake)
    monkeypatch.delenv("COGNIA_COORDINATOR_URL", raising=False)
    monkeypatch.delenv("COORDINATOR_URL", raising=False)
    out = _capture(cmain._cmd_status)
    # "configurado" y no "instalado" (2026-08-15): la palabra distingue lo que
    # dice config.env de lo que el server SIRVE, que puede ser otro modelo.
    assert "Backend local (GGUF): configurado" in out
    # el swarm sigue reportandose, pero como opcional apagado, no como el estado
    assert "modo local" in out


def test_status_dice_el_modelo_SERVIDO_no_el_configurado(monkeypatch, tmp_path):
    """El fallo del e2e del 2026-08-15: con Nemotron servido en :8080,
    `cognia status` imprimia el Qwythos de config.env. Un diagnostico que
    informa del modelo equivocado es peor que no informar."""
    fake = tmp_path / "configurado.gguf"
    fake.write_bytes(b"gguf")
    import node.llama_backend as lb
    monkeypatch.setattr(lb, "_find_gguf", lambda: fake)
    monkeypatch.delenv("COGNIA_COORDINATOR_URL", raising=False)
    monkeypatch.delenv("COORDINATOR_URL", raising=False)
    monkeypatch.setattr(cmain.urllib.request, "urlopen",
                        lambda *a, **k: _Health())
    import cognia.backend_activo as BA
    monkeypatch.setattr(BA, "props",
                        lambda url, forzar=False: {
                            "modelo": "otro-modelo-servido.gguf",
                            "n_ctx": 1048576})
    out = _capture(cmain._cmd_status)
    assert "SIRVIENDO   : otro-modelo-servido.gguf" in out
    assert "1,048,576" in out or "1048576" in out
    assert "OJO" in out          # la discrepancia se declara, no se traga


class _Health:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return b"{}"


def test_status_sin_gguf_recomienda_install_model(monkeypatch):
    import node.llama_backend as lb
    monkeypatch.setattr(lb, "_find_gguf", lambda: None)
    monkeypatch.delenv("COGNIA_COORDINATOR_URL", raising=False)
    monkeypatch.delenv("COORDINATOR_URL", raising=False)
    out = _capture(cmain._cmd_status)
    assert "install-model" in out
