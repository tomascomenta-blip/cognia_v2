# -*- coding: utf-8 -*-
"""Registry N-modelos del FLEET-30: manifest, kill-switch, lazy, RAM/LRU.

Todo con FAKES: NUNCA arranca un llama-server real (el server real se prueba
con `python -m node.fleet_registry <key>`)."""
import json

import pytest

import node.fleet_registry as fr


def _write_manifest(tmp_path, members):
    p = tmp_path / "fleet30.json"
    p.write_text(json.dumps({"members": members}), encoding="utf-8")
    return p


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr(fr, "_SERVERS", {})
    monkeypatch.setattr(fr, "_FAILED", set())
    monkeypatch.setattr(fr, "_LRU", [])
    monkeypatch.setattr(fr, "_MANIFEST_CACHE", None)
    monkeypatch.delenv("COGNIA_FLEET30", raising=False)
    monkeypatch.delenv("COGNIA_FLEET30_MANIFEST", raising=False)
    monkeypatch.delenv("COGNIA_FLEET_RAM_GB", raising=False)
    yield


class _FakeBackend:
    def __init__(self, gguf_path, port=0, ctx_size=None, lora_path=None):
        self.gguf = gguf_path
        self.port = port
        self.ctx_size = ctx_size
        self.lora_path = lora_path
        self.stopped = False

    def stop(self):
        self.stopped = True


def test_kill_switch_0_devuelve_none(monkeypatch, tmp_path):
    gguf = tmp_path / "a.gguf"
    gguf.write_bytes(b"x")
    mf = _write_manifest(tmp_path, [{"key": "a", "gguf": "a.gguf"}])
    monkeypatch.setenv("COGNIA_FLEET30_MANIFEST", str(mf))
    monkeypatch.setenv("COGNIA_FLEET30", "0")
    assert fr.fleet_backend("a") is None


def test_key_desconocida_cachea_falla(monkeypatch, tmp_path):
    mf = _write_manifest(tmp_path, [])
    monkeypatch.setenv("COGNIA_FLEET30_MANIFEST", str(mf))
    assert fr.fleet_backend("nope") is None
    assert "nope" in fr._FAILED


def test_gguf_faltante_cachea_falla(monkeypatch, tmp_path):
    mf = _write_manifest(tmp_path, [{"key": "a", "gguf": "no_existe.gguf"}])
    monkeypatch.setenv("COGNIA_FLEET30_MANIFEST", str(mf))
    assert fr.fleet_backend("a") is None
    assert "a" in fr._FAILED


def test_arranca_con_puerto_ctx_y_ruta_relativa(monkeypatch, tmp_path):
    gguf = tmp_path / "m.gguf"
    gguf.write_bytes(b"x")
    mf = _write_manifest(tmp_path, [
        {"key": "a", "gguf": "m.gguf", "port": 8095, "ctx": 2048,
         "ram_gb": 0.5}])
    monkeypatch.setenv("COGNIA_FLEET30_MANIFEST", str(mf))
    monkeypatch.setattr(fr, "_LlamaServerBackend", _FakeBackend)
    b = fr.fleet_backend("a")
    assert isinstance(b, _FakeBackend)
    assert b.gguf == gguf                    # relativa resuelta contra el manifest
    assert b.port == 8095
    assert b.ctx_size == 2048
    assert b.lora_path is None


def test_singleton_no_re_arranca(monkeypatch, tmp_path):
    gguf = tmp_path / "m.gguf"
    gguf.write_bytes(b"x")
    mf = _write_manifest(tmp_path, [{"key": "a", "gguf": "m.gguf"}])
    monkeypatch.setenv("COGNIA_FLEET30_MANIFEST", str(mf))
    n = {"c": 0}

    class _Contador(_FakeBackend):
        def __init__(self, *a, **k):
            n["c"] += 1
            super().__init__(*a, **k)

    monkeypatch.setattr(fr, "_LlamaServerBackend", _Contador)
    fr.fleet_backend("a")
    fr.fleet_backend("a")
    assert n["c"] == 1


def test_falla_de_arranque_no_reintenta(monkeypatch, tmp_path):
    gguf = tmp_path / "m.gguf"
    gguf.write_bytes(b"x")
    mf = _write_manifest(tmp_path, [{"key": "a", "gguf": "m.gguf"}])
    monkeypatch.setenv("COGNIA_FLEET30_MANIFEST", str(mf))
    n = {"c": 0}

    class _Explota:
        def __init__(self, *a, **k):
            n["c"] += 1
            raise RuntimeError("no arranca")

    monkeypatch.setattr(fr, "_LlamaServerBackend", _Explota)
    assert fr.fleet_backend("a") is None
    assert fr.fleet_backend("a") is None
    assert n["c"] == 1


def test_ram_evicta_lru(monkeypatch, tmp_path):
    for name in ("a", "b", "c"):
        (tmp_path / f"{name}.gguf").write_bytes(b"x")
    mf = _write_manifest(tmp_path, [
        {"key": "a", "gguf": "a.gguf", "ram_gb": 1.5, "port": 8093},
        {"key": "b", "gguf": "b.gguf", "ram_gb": 1.5, "port": 8094},
        {"key": "c", "gguf": "c.gguf", "ram_gb": 1.5, "port": 8095}])
    monkeypatch.setenv("COGNIA_FLEET30_MANIFEST", str(mf))
    monkeypatch.setenv("COGNIA_FLEET_RAM_GB", "3.0")
    monkeypatch.setattr(fr, "_LlamaServerBackend", _FakeBackend)
    ba = fr.fleet_backend("a")
    bb = fr.fleet_backend("b")
    bc = fr.fleet_backend("c")              # 3×1.5 > 3.0 -> evicta "a" (LRU)
    assert ba.stopped is True
    assert bb.stopped is False and bc.stopped is False
    assert "a" not in fr._SERVERS and {"b", "c"} <= set(fr._SERVERS)


def test_ram_lru_respeta_uso_reciente(monkeypatch, tmp_path):
    for name in ("a", "b", "c"):
        (tmp_path / f"{name}.gguf").write_bytes(b"x")
    mf = _write_manifest(tmp_path, [
        {"key": "a", "gguf": "a.gguf", "ram_gb": 1.5, "port": 8093},
        {"key": "b", "gguf": "b.gguf", "ram_gb": 1.5, "port": 8094},
        {"key": "c", "gguf": "c.gguf", "ram_gb": 1.5, "port": 8095}])
    monkeypatch.setenv("COGNIA_FLEET30_MANIFEST", str(mf))
    monkeypatch.setenv("COGNIA_FLEET_RAM_GB", "3.0")
    monkeypatch.setattr(fr, "_LlamaServerBackend", _FakeBackend)
    ba = fr.fleet_backend("a")
    bb = fr.fleet_backend("b")
    fr.fleet_backend("a")                    # re-uso: "a" pasa a ser reciente
    fr.fleet_backend("c")                    # ahora el LRU es "b"
    assert bb.stopped is True
    assert ba.stopped is False


def test_modelo_mas_grande_que_presupuesto_no_arranca(monkeypatch, tmp_path):
    (tmp_path / "g.gguf").write_bytes(b"x")
    mf = _write_manifest(tmp_path, [
        {"key": "g", "gguf": "g.gguf", "ram_gb": 9.9}])
    monkeypatch.setenv("COGNIA_FLEET30_MANIFEST", str(mf))
    monkeypatch.setenv("COGNIA_FLEET_RAM_GB", "3.0")
    monkeypatch.setattr(fr, "_LlamaServerBackend", _FakeBackend)
    assert fr.fleet_backend("g") is None
    assert "g" in fr._FAILED


def test_format_prompt_por_template(monkeypatch, tmp_path):
    (tmp_path / "m.gguf").write_bytes(b"x")
    mf = _write_manifest(tmp_path, [
        {"key": "q", "gguf": "m.gguf", "template": "chatml"},
        {"key": "g", "gguf": "m.gguf", "template": "gemma"}])
    monkeypatch.setenv("COGNIA_FLEET30_MANIFEST", str(mf))
    q = fr.format_prompt("q", "S", "U")
    g = fr.format_prompt("g", "S", "U")
    assert "<|im_start|>user\nU<|im_end|>" in q
    assert "<start_of_turn>user" in g and "S\n\nU" in g
    # key desconocida cae a chatml (no explota)
    assert "<|im_start|>" in fr.format_prompt("zzz", "S", "U")


def test_lora_relativa_se_resuelve_contra_el_manifest(monkeypatch, tmp_path):
    (tmp_path / "m.gguf").write_bytes(b"x")
    (tmp_path / "cognia_id_f16.gguf").write_bytes(b"x")
    mf = _write_manifest(tmp_path, [
        {"key": "a", "gguf": "m.gguf", "lora": "cognia_id_f16.gguf"}])
    monkeypatch.setenv("COGNIA_FLEET30_MANIFEST", str(mf))
    monkeypatch.setattr(fr, "_LlamaServerBackend", _FakeBackend)
    b = fr.fleet_backend("a")
    assert b.lora_path == tmp_path / "cognia_id_f16.gguf"


def test_close_fleet30_para_todo(monkeypatch, tmp_path):
    for name in ("a", "b"):
        (tmp_path / f"{name}.gguf").write_bytes(b"x")
    mf = _write_manifest(tmp_path, [
        {"key": "a", "gguf": "a.gguf", "port": 8093},
        {"key": "b", "gguf": "b.gguf", "port": 8094}])
    monkeypatch.setenv("COGNIA_FLEET30_MANIFEST", str(mf))
    monkeypatch.setattr(fr, "_LlamaServerBackend", _FakeBackend)
    ba = fr.fleet_backend("a")
    bb = fr.fleet_backend("b")
    fr.close_fleet30()
    assert ba.stopped and bb.stopped
    assert fr._SERVERS == {} and fr._LRU == []


def test_reset_failures_permite_reintento(monkeypatch, tmp_path):
    mf = _write_manifest(tmp_path, [{"key": "a", "gguf": "no.gguf"}])
    monkeypatch.setenv("COGNIA_FLEET30_MANIFEST", str(mf))
    assert fr.fleet_backend("a") is None
    (tmp_path / "no.gguf").write_bytes(b"x")
    monkeypatch.setattr(fr, "_LlamaServerBackend", _FakeBackend)
    fr.reset_failures()
    fr.load_manifest(force=True)
    assert fr.fleet_backend("a") is not None
