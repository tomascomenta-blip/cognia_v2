# -*- coding: utf-8 -*-
"""Regresion de los avisos de apply_config (~/.cognia/config.env).

Gap cazado 2026-07-16: el aviso anti-var-stale solo se disparaba si la clave
EXISTIA en config.env con otro valor. Una LLAMA_LORA_PATH residual del
sistema que NO estuviera en config.env seguia matando el fleet en mudo —
el caso exacto de la auditoria 2026-07-15 que motivo el aviso original.
"""
import pytest

from cognia import first_run


@pytest.fixture
def config_env(tmp_path, monkeypatch):
    cfg = tmp_path / "config.env"
    monkeypatch.setattr(first_run, "CONFIG_FILE", cfg)
    return cfg


def test_avisa_lora_path_residual_fuera_de_config(config_env, monkeypatch, capsys):
    config_env.write_text("LLAMA_GGUF_PATH=C:/modelos/x.gguf\n", encoding="utf-8")
    monkeypatch.delenv("LLAMA_GGUF_PATH", raising=False)
    monkeypatch.setenv("LLAMA_LORA_PATH", "C:/viejo/adapter.gguf")
    first_run.apply_config()
    out = capsys.readouterr().out
    assert "LLAMA_LORA_PATH" in out
    assert "fleet" in out.lower()


def test_sin_lora_residual_no_avisa(config_env, monkeypatch, capsys):
    config_env.write_text("LLAMA_GGUF_PATH=C:/modelos/x.gguf\n", encoding="utf-8")
    monkeypatch.delenv("LLAMA_GGUF_PATH", raising=False)
    monkeypatch.delenv("LLAMA_LORA_PATH", raising=False)
    first_run.apply_config()
    assert "LLAMA_LORA_PATH" not in capsys.readouterr().out


def test_env_que_pisa_config_sigue_avisando(config_env, monkeypatch, capsys):
    """El aviso original (clave presente en config.env con otro valor) no se rompe."""
    config_env.write_text("LLAMA_GGUF_PATH=C:/modelos/nuevo.gguf\n", encoding="utf-8")
    monkeypatch.setenv("LLAMA_GGUF_PATH", "C:/modelos/viejo.gguf")
    first_run.apply_config()
    out = capsys.readouterr().out
    assert "LLAMA_GGUF_PATH" in out and "pisa" in out
