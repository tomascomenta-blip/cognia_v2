# -*- coding: utf-8 -*-
"""Cognia organiza el flujo desde NL (flows.organizar_flujo + tool crear_flujo).
0-LLM: plan_task es simbolico/determinista."""
from cognia.agent.flows import organizar_flujo, validar


def test_organizar_flujo_produce_dag():
    flujo = organizar_flujo("leer el archivo x.py y resumirlo")
    assert flujo["nodos"]                       # tiene pasos
    orden = validar(flujo)                       # es un DAG valido
    assert len(orden) == len(flujo["nodos"])
    # cada nodo tiene una tool y esta encadenado
    assert all(n.get("tool") for n in flujo["nodos"])


def test_tool_crear_flujo(tmp_path, monkeypatch):
    import cognia.agents.workers.dev_tools as dev
    monkeypatch.setattr(dev, "AGENT_WORKSPACE_ROOT", str(tmp_path))
    from cognia.agent.tools import TOOLS
    r = TOOLS["crear_flujo"]["fn"]("analizar el proyecto y escribir un informe", {})
    assert "RESULTADO crear_flujo:" in r
    assert "pasos" in r
    assert (tmp_path / ".flujo.json").exists()   # se guardo


def test_tool_crear_flujo_vacio():
    from cognia.agent.tools import TOOLS
    r = TOOLS["crear_flujo"]["fn"]("", {})
    assert "ERROR" in r
