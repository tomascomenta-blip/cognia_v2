# -*- coding: utf-8 -*-
"""Especialista 7B de código duro (MoM fase 4): kill-switch, lazy, falla cacheada.

Todo con FAKES: NUNCA arranca un llama-server 7B real (el server real se prueba
con `COGNIA_HEAVY_CODE=1 python -m node.heavy_code`)."""
import pytest

import node.heavy_code as hc


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr(hc, "_HEAVY_SINGLETON", None)
    monkeypatch.setattr(hc, "_HEAVY_FAILED", False)
    monkeypatch.delenv("COGNIA_HEAVY_CODE", raising=False)
    monkeypatch.delenv("COGNIA_HEAVY_KEEPWARM", raising=False)
    yield


def test_kill_switch_0_devuelve_none():
    # Default ON tras cerrar el deploy; COGNIA_HEAVY_CODE=0 lo apaga.
    import os
    os.environ["COGNIA_HEAVY_CODE"] = "0"
    try:
        assert hc.heavy_code_backend() is None
    finally:
        os.environ.pop("COGNIA_HEAVY_CODE", None)


def test_default_on_pero_gguf_faltante_cae_al_3b(monkeypatch):
    # Default ON (sin env var) pero SIN el GGUF 7B -> None -> fallback al 3B
    # (instalaciones sin el 7B no se rompen).
    monkeypatch.delenv("COGNIA_HEAVY_CODE", raising=False)
    fake = type("P", (), {"is_file": lambda self: False})()
    import shattering.model_constants as mc
    monkeypatch.setattr(mc, "resolve_gguf_path", lambda k: fake)
    assert hc.heavy_code_backend() is None
    assert hc._HEAVY_FAILED is True


def test_on_pero_gguf_faltante_cachea_falla(monkeypatch):
    monkeypatch.setenv("COGNIA_HEAVY_CODE", "1")
    fake = type("P", (), {"is_file": lambda self: False})()
    monkeypatch.setattr(hc, "resolve_gguf_path", lambda k: fake, raising=False)
    # resolve_gguf_path se importa dentro de la función; parchear el módulo origen
    import shattering.model_constants as mc
    monkeypatch.setattr(mc, "resolve_gguf_path", lambda k: fake)
    assert hc.heavy_code_backend() is None
    assert hc._HEAVY_FAILED is True


def test_on_arranca_7b_con_puerto_y_ctx(monkeypatch, tmp_path):
    monkeypatch.setenv("COGNIA_HEAVY_CODE", "1")
    gguf = tmp_path / "Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf"
    gguf.write_bytes(b"x")
    import shattering.model_constants as mc
    monkeypatch.setattr(mc, "resolve_gguf_path", lambda k: gguf)
    cap = {}

    class _FakeBackend:
        def __init__(self, g, port=0, ctx_size=None, lora_path="unset"):
            cap.update(gguf=g, port=port, ctx_size=ctx_size, lora_path=lora_path)

    monkeypatch.setattr(hc, "_LlamaServerBackend", _FakeBackend)
    b = hc.heavy_code_backend()
    assert isinstance(b, _FakeBackend)
    assert cap["gguf"] == gguf
    assert cap["port"] == 8092
    assert cap["ctx_size"] == 4096
    assert cap["lora_path"] is None        # base 7B pura, sin fleet


def test_singleton_no_re_arranca(monkeypatch, tmp_path):
    monkeypatch.setenv("COGNIA_HEAVY_CODE", "1")
    gguf = tmp_path / "m.gguf"
    gguf.write_bytes(b"x")
    import shattering.model_constants as mc
    monkeypatch.setattr(mc, "resolve_gguf_path", lambda k: gguf)
    n = {"c": 0}

    class _FakeBackend:
        def __init__(self, *a, **k):
            n["c"] += 1

    monkeypatch.setattr(hc, "_LlamaServerBackend", _FakeBackend)
    hc.heavy_code_backend()
    hc.heavy_code_backend()
    assert n["c"] == 1                      # segunda llamada reusa el singleton


def test_falla_de_arranque_no_reintenta(monkeypatch, tmp_path):
    monkeypatch.setenv("COGNIA_HEAVY_CODE", "1")
    gguf = tmp_path / "m.gguf"
    gguf.write_bytes(b"x")
    import shattering.model_constants as mc
    monkeypatch.setattr(mc, "resolve_gguf_path", lambda k: gguf)
    n = {"c": 0}

    class _Explota:
        def __init__(self, *a, **k):
            n["c"] += 1
            raise RuntimeError("no arranca")

    monkeypatch.setattr(hc, "_LlamaServerBackend", _Explota)
    assert hc.heavy_code_backend() is None
    assert hc.heavy_code_backend() is None
    assert n["c"] == 1                      # falla cacheada: sin reintento


def test_close_libera_y_resetea(monkeypatch):
    stopped = {"c": 0}

    class _Srv:
        def stop(self):
            stopped["c"] += 1

    monkeypatch.setattr(hc, "_HEAVY_SINGLETON", _Srv())
    hc.close_heavy_code()
    assert stopped["c"] == 1
    assert hc._HEAVY_SINGLETON is None


def test_close_respeta_keepwarm(monkeypatch):
    stopped = {"c": 0}

    class _Srv:
        def stop(self):
            stopped["c"] += 1

    monkeypatch.setattr(hc, "_HEAVY_SINGLETON", _Srv())
    monkeypatch.setenv("COGNIA_HEAVY_KEEPWARM", "1")
    hc.close_heavy_code()
    assert stopped["c"] == 0                 # keepwarm: NO se cierra
    assert hc._HEAVY_SINGLETON is not None
