"""
Tests del interruptor local-only de la version comercial (cognia/runtime_mode.py)
y su efecto en el ruteo de inferencia (node/inference_pipeline.py).
"""
from __future__ import annotations

import importlib

from cognia import runtime_mode


def test_default_respects_coordinator(monkeypatch):
    monkeypatch.delenv("COGNIA_DISABLE_SWARM", raising=False)
    monkeypatch.setenv("COGNIA_COORDINATOR_URL", "http://host:8001")
    assert not runtime_mode.swarm_disabled()
    assert runtime_mode.coordinator_url() == "http://host:8001"


def test_hard_off_forces_local(monkeypatch):
    monkeypatch.setenv("COGNIA_COORDINATOR_URL", "http://host:8001")
    for val in ("1", "true", "YES", "on"):
        monkeypatch.setenv("COGNIA_DISABLE_SWARM", val)
        assert runtime_mode.swarm_disabled()
        assert runtime_mode.coordinator_url() == ""   # fuerza local aunque haya URL


def test_no_config_is_local(monkeypatch):
    monkeypatch.delenv("COGNIA_DISABLE_SWARM", raising=False)
    monkeypatch.delenv("COGNIA_COORDINATOR_URL", raising=False)
    monkeypatch.delenv("COORDINATOR_URL", raising=False)
    assert runtime_mode.coordinator_url() == ""       # default = local


def test_inference_pipeline_honors_hard_off(monkeypatch):
    # el modulo computa COORDINATOR_URL al importar -> reload con el flag puesto
    monkeypatch.setenv("COGNIA_COORDINATOR_URL", "http://host:8001")
    monkeypatch.setenv("COGNIA_DISABLE_SWARM", "1")
    import node.inference_pipeline as ip
    importlib.reload(ip)
    assert ip.COORDINATOR_URL == ""
    # y sin el flag, respeta la URL
    monkeypatch.delenv("COGNIA_DISABLE_SWARM", raising=False)
    importlib.reload(ip)
    assert ip.COORDINATOR_URL == "http://host:8001"
