# -*- coding: utf-8 -*-
"""Regresión: el 7B de código (MoM fase 4) llega al PRODUCTO INSTALADO.

Antes el escalado 3B→7B solo resolvía el GGUF vía resolve_gguf_path("7b"), que
apunta a <repo|site-packages>/model_shards/ — nunca poblado en un pip install.
Resultado: en instalaciones de usuario el 7B NUNCA se activaba (caía al 3B) y
el +20pp de código duro no llegaba al producto.

Fix: (a) heavy_code._resolve_heavy_gguf() resuelve override -> config instalada
(HEAVY_CODE_GGUF_PATH, que cognia install-model --with-heavy-code persiste en
~/.cognia/config.env) -> registry del repo; (b) install_model gana with_heavy_code
(opt-in, ~4.7 GB) e install_heavy_code() baja el 7B y persiste la ruta.
"""
import inspect
from pathlib import Path


def test_resolve_prefiere_override_explicito(tmp_path, monkeypatch):
    from node import heavy_code
    real = tmp_path / "override.gguf"
    real.write_bytes(b"x")
    monkeypatch.setenv("COGNIA_HEAVY_CODE_GGUF", str(real))
    monkeypatch.setenv("HEAVY_CODE_GGUF_PATH", str(tmp_path / "no_existe.gguf"))
    assert heavy_code._resolve_heavy_gguf() == real


def test_resolve_usa_config_instalada(tmp_path, monkeypatch):
    from node import heavy_code
    monkeypatch.delenv("COGNIA_HEAVY_CODE_GGUF", raising=False)
    inst = tmp_path / "instalado.gguf"
    inst.write_bytes(b"x")
    monkeypatch.setenv("HEAVY_CODE_GGUF_PATH", str(inst))
    assert heavy_code._resolve_heavy_gguf() == inst


def test_resolve_none_si_nada_existe(tmp_path, monkeypatch):
    # sin env vars válidas y con el registry apuntando a un archivo inexistente
    from node import heavy_code
    monkeypatch.delenv("COGNIA_HEAVY_CODE_GGUF", raising=False)
    monkeypatch.setenv("HEAVY_CODE_GGUF_PATH", str(tmp_path / "no_existe.gguf"))
    import shattering.model_constants as mc
    monkeypatch.setattr(mc, "resolve_gguf_path",
                        lambda k: tmp_path / "tampoco.gguf")
    assert heavy_code._resolve_heavy_gguf() is None


def test_resolve_cae_al_registry_del_repo(tmp_path, monkeypatch):
    # sin env vars, con el registry apuntando a un archivo que SÍ existe (modo dev)
    from node import heavy_code
    monkeypatch.delenv("COGNIA_HEAVY_CODE_GGUF", raising=False)
    monkeypatch.delenv("HEAVY_CODE_GGUF_PATH", raising=False)
    repo_gguf = tmp_path / "repo_7b.gguf"
    repo_gguf.write_bytes(b"x")
    import shattering.model_constants as mc
    monkeypatch.setattr(mc, "resolve_gguf_path", lambda k: repo_gguf)
    assert heavy_code._resolve_heavy_gguf() == repo_gguf


def test_install_model_tiene_with_heavy_code_opt_in():
    from cognia import model_install
    sig = inspect.signature(model_install.install_model)
    assert "with_heavy_code" in sig.parameters, "install_model no expone with_heavy_code"
    assert sig.parameters["with_heavy_code"].default is False, \
        "with_heavy_code debe ser OPT-IN (default False; el 7B son ~4.7 GB)"


def test_main_parsea_with_heavy_code(monkeypatch):
    from cognia import model_install
    capturado = {}

    def _fake_install_model(**kw):
        capturado.update(kw)
        return {}

    monkeypatch.setattr(model_install, "install_model", _fake_install_model)
    model_install.main([])
    assert capturado["with_heavy_code"] is False, "sin flag debe ser False"
    capturado.clear()
    model_install.main(["--with-heavy-code"])
    assert capturado["with_heavy_code"] is True, "--with-heavy-code debe activar el 7B"


def test_install_heavy_code_descarga_persiste_ruta(tmp_path, monkeypatch):
    # rama de descarga: baja el 7B (mock) y persiste HEAVY_CODE_GGUF_PATH para que
    # apply_config lo exponga como env var y heavy_code lo resuelva en instalado.
    from cognia import model_install
    import huggingface_hub
    fake_path = tmp_path / model_install.HEAVY_GGUF_FILE
    fake_path.write_bytes(b"x")   # 1 byte -> NO dispara el early-return de >3GB
    monkeypatch.setattr(huggingface_hub, "hf_hub_download",
                        lambda **kw: str(fake_path))
    guardado = {}
    monkeypatch.setattr(model_install, "set_config_value",
                        lambda k, v: guardado.__setitem__(k, v))
    out = model_install.install_heavy_code(dest_dir=tmp_path)
    assert out == fake_path
    assert guardado.get("HEAVY_CODE_GGUF_PATH") == str(fake_path), \
        "install_heavy_code no persistió la ruta del 7B en config"


def test_install_heavy_code_falla_limpio_sin_red(tmp_path, monkeypatch):
    # sin red / repo inexistente -> None y NO persiste (el CLI corre solo con el 3B)
    from cognia import model_install
    import huggingface_hub

    def _boom(**kw):
        raise RuntimeError("sin red")

    monkeypatch.setattr(huggingface_hub, "hf_hub_download", _boom)
    guardado = {}
    monkeypatch.setattr(model_install, "set_config_value",
                        lambda k, v: guardado.__setitem__(k, v))
    out = model_install.install_heavy_code(dest_dir=tmp_path)
    assert out is None
    assert "HEAVY_CODE_GGUF_PATH" not in guardado
