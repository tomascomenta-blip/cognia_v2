# -*- coding: utf-8 -*-
"""Fleet de expertos LoRA en llama_backend: manifiesto, args, hot-swap, dirty-flag.

Todo con fakes: NUNCA levanta ni toca un llama-server real.
"""
import json

import pytest

from node.llama_backend import (
    LlamaBackend, _LlamaServerBackend, _fleet_manifest, _lora_args,
)


# ---------------------------------------------------------------- manifiesto
def _mk_model_dir(tmp_path, manifest=None, adapter_files=()):
    gguf = tmp_path / "base-Q4_K_M.gguf"
    gguf.write_bytes(b"x")
    for f in adapter_files:
        (tmp_path / f).write_bytes(b"x")
    if manifest is not None:
        (tmp_path / "adapters.json").write_text(json.dumps(manifest), encoding="utf-8")
    return gguf


def test_manifest_ausente_devuelve_vacio(tmp_path):
    gguf = _mk_model_dir(tmp_path)
    assert _fleet_manifest(gguf) == []
    assert _fleet_manifest(None) == []


def test_manifest_parsea_y_saltea_inexistentes(tmp_path):
    gguf = _mk_model_dir(
        tmp_path,
        manifest={"adapters": [{"name": "accion", "file": "a.gguf"},
                               {"name": "roto", "file": "no_existe.gguf"}]},
        adapter_files=["a.gguf"],
    )
    fleet = _fleet_manifest(gguf)
    assert [a["name"] for a in fleet] == ["accion"]
    assert fleet[0]["path"] == tmp_path / "a.gguf"


def test_manifest_corrupto_fleet_off(tmp_path):
    gguf = _mk_model_dir(tmp_path)
    (tmp_path / "adapters.json").write_text("{no json", encoding="utf-8")
    assert _fleet_manifest(gguf) == []


# ---------------------------------------------------------------- _lora_args
def test_lora_path_estatico_tiene_precedencia(tmp_path, monkeypatch):
    gguf = _mk_model_dir(
        tmp_path,
        manifest={"adapters": [{"name": "accion", "file": "a.gguf"}]},
        adapter_files=["a.gguf"],
    )
    static = tmp_path / "viejo.gguf"
    static.write_bytes(b"x")
    monkeypatch.setenv("LLAMA_LORA_PATH", str(static))
    args, names = _lora_args(gguf)
    assert args == ["--lora", str(static)]
    assert names == []


def test_fleet_args_init_without_apply(tmp_path, monkeypatch):
    monkeypatch.delenv("LLAMA_LORA_PATH", raising=False)
    gguf = _mk_model_dir(
        tmp_path,
        manifest={"adapters": [{"name": "accion", "file": "a.gguf"},
                               {"name": "razonamiento", "file": "b.gguf"}]},
        adapter_files=["a.gguf", "b.gguf"],
    )
    args, names = _lora_args(gguf)
    assert args[0] == "--lora-init-without-apply"
    assert args.count("--lora") == 2
    assert names == ["accion", "razonamiento"]


def test_sin_nada_args_vacios(tmp_path, monkeypatch):
    monkeypatch.delenv("LLAMA_LORA_PATH", raising=False)
    gguf = _mk_model_dir(tmp_path)
    assert _lora_args(gguf) == ([], [])


# ---------------------------------------------------------------- hot-swap
class _FakeResp:
    def read(self):
        return b"{}"

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeUrlReq:
    def __init__(self):
        self.posts = []

    def Request(self, url, data=None, headers=None):
        return ("REQ", url, data)

    def urlopen(self, req, timeout=0):
        if isinstance(req, tuple):
            self.posts.append(json.loads(req[2]))
        return _FakeResp()


def _mk_server_backend(fleet_names):
    b = object.__new__(_LlamaServerBackend)
    b._base = "http://fake"
    b._json = json
    b._urlreq = _FakeUrlReq()
    b._fleet_names = list(fleet_names)
    b._active_expert = None
    b._lora_dirty = False
    return b


def test_activate_expert_postea_scales_y_marca_dirty():
    b = _mk_server_backend(["accion", "razonamiento"])
    assert b.activate_expert("accion") is True
    assert b._urlreq.posts == [[{"id": 0, "scale": 1.0}, {"id": 1, "scale": 0.0}]]
    assert b._active_expert == "accion"
    assert b._lora_dirty is True


def test_activate_expert_idempotente_no_repostea():
    b = _mk_server_backend(["accion"])
    b.activate_expert("accion")
    b._lora_dirty = False
    assert b.activate_expert("accion") is True
    assert len(b._urlreq.posts) == 1      # no hubo segundo POST
    assert b._lora_dirty is False         # sin swap, sin invalidar cache


def test_activate_none_vuelve_a_base():
    b = _mk_server_backend(["accion"])
    b.activate_expert("accion")
    assert b.activate_expert(None) is True
    assert b._urlreq.posts[-1] == [{"id": 0, "scale": 0.0}]
    assert b._active_expert is None


def test_experto_desconocido_falla_sin_post():
    b = _mk_server_backend(["accion"])
    assert b.activate_expert("nope") is False
    assert b._urlreq.posts == []


def test_sin_fleet_base_ok_experto_no():
    b = _mk_server_backend([])
    assert b.activate_expert(None) is True
    assert b.activate_expert("accion") is False


def test_dirty_fuerza_cache_prompt_false_una_vez():
    b = _mk_server_backend(["accion"])
    b._lora_dirty = True
    assert b._consume_lora_dirty(True) is False   # 1ra request post-swap
    assert b._consume_lora_dirty(True) is True    # la siguiente vuelve al default


def test_force_base_scales_postea_ceros_al_arrancar():
    # Medido: --lora-init-without-apply deja scale 1.0 -> el arranque debe
    # forzar base con un POST real aunque _active_expert arranque en None.
    b = _mk_server_backend(["accion"])
    b._force_base_scales()
    assert b._urlreq.posts == [[{"id": 0, "scale": 0.0}]]
    assert b._active_expert is None


def test_force_base_scales_sin_fleet_no_hace_nada():
    b = _mk_server_backend([])
    b._force_base_scales()
    assert b._urlreq.posts == []


# ------------------------------------------------- LoRA estatica (portero)
class _FakePopen:
    def __init__(self, cmd, stdout=None, stderr=None):
        self.cmd = cmd
        self.pid = 123

    def poll(self):
        return None

    def terminate(self):
        pass

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass


def _portero_files(tmp_path):
    gguf = tmp_path / "qwen05b.gguf"
    lora = tmp_path / "portero_f16.gguf"
    gguf.write_bytes(b"x")
    lora.write_bytes(b"x")
    return gguf, lora


def test_lora_estatica_por_parametro_en_cmd(tmp_path, monkeypatch):
    # lora_path/ctx_size POR INSTANCIA (no LLAMA_LORA_PATH global, que
    # envenenaria el server del 3B): --lora aplicada, sin fleet hot-swap.
    import node.llama_backend as lb
    gguf, lora = _portero_files(tmp_path)
    monkeypatch.delenv("LLAMA_SERVER_PATH", raising=False)
    monkeypatch.delenv("LLAMA_LORA_PATH", raising=False)
    monkeypatch.setattr(lb.shutil, "which", lambda name: "llama-server-fake")
    capturado = {}

    def fake_popen(cmd, stdout=None, stderr=None):
        capturado["cmd"] = cmd
        return _FakePopen(cmd)

    monkeypatch.setattr(lb.subprocess, "Popen", fake_popen)
    pings = iter([False])   # 1ra: no hay server que adoptar; luego: arriba
    monkeypatch.setattr(lb._LlamaServerBackend, "_ping",
                        lambda self: next(pings, True))
    b = lb._LlamaServerBackend(gguf, port=9999, lora_path=lora, ctx_size=4096)
    cmd = capturado["cmd"]
    assert "--lora" in cmd and str(lora) in cmd
    assert "--lora-init-without-apply" not in cmd     # aplicada, no hot-swap
    assert cmd[cmd.index("--ctx-size") + 1] == "4096"
    assert b._fleet_names == []


def test_adoptado_sin_lora_estatica_rechaza(tmp_path, monkeypatch):
    # server ya vivo en el puerto SIN la LoRA pedida -> RuntimeError (el caller
    # cae al 3B; nunca servir la base pelada como si fuera el experto).
    import node.llama_backend as lb
    gguf, lora = _portero_files(tmp_path)
    monkeypatch.setattr(lb._LlamaServerBackend, "_ping", lambda self: True)
    monkeypatch.setattr(lb._LlamaServerBackend, "_check_adopted_server",
                        lambda self: None)
    monkeypatch.setattr(lb._LlamaServerBackend, "lora_adapters", lambda self: [])
    with pytest.raises(RuntimeError, match="sin la LoRA"):
        lb._LlamaServerBackend(gguf, port=9999, lora_path=lora)


def test_adoptado_con_lora_estatica_aplicada_ok(tmp_path, monkeypatch):
    import node.llama_backend as lb
    gguf, lora = _portero_files(tmp_path)
    monkeypatch.setattr(lb._LlamaServerBackend, "_ping", lambda self: True)
    monkeypatch.setattr(lb._LlamaServerBackend, "_check_adopted_server",
                        lambda self: None)
    monkeypatch.setattr(lb._LlamaServerBackend, "lora_adapters",
                        lambda self: [{"id": 0, "path": str(lora), "scale": 1.0}])
    b = lb._LlamaServerBackend(gguf, port=9999, lora_path=lora)
    assert b._fleet_names == []


# ---------------------------------------------------------------- fachada
def test_facade_sin_soporte_fleet():
    class _Impl:            # impl viejo/in-process sin activate_expert
        pass
    fb = LlamaBackend(_Impl())
    assert fb.fleet_experts == []
    assert fb.active_expert is None
    assert fb.activate_expert(None) is True
    assert fb.activate_expert("accion") is False


def test_facade_delega_al_impl():
    b = _mk_server_backend(["accion"])
    fb = LlamaBackend(b)
    assert fb.fleet_experts == ["accion"]
    assert fb.activate_expert("accion") is True
    assert fb.active_expert == "accion"
