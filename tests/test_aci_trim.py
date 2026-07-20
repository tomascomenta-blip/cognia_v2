# -*- coding: utf-8 -*-
"""ACI: compactacion de tool-outputs (mejora de harness)."""
import cognia.agent.tools as tools


def test_output_corto_intacto():
    s = "RESULTADO listar: a.py b.py c.py"
    assert tools.aci_trim(s, "listar") == s


def test_output_largo_recortado(tmp_path, monkeypatch):
    import cognia.agents.workers.dev_tools as dev
    monkeypatch.setattr(dev, "AGENT_WORKSPACE_ROOT", str(tmp_path))
    largo = "RESULTADO leer_archivo: " + ("X" * 5000)
    out = tools.aci_trim(largo, "leer_archivo")
    assert len(out) < len(largo)
    assert out.startswith("RESULTADO leer_archivo: XXX")   # cabeza preservada
    assert "chars omitidos" in out
    assert out.endswith("X" * 50)                          # cola preservada
    # el completo se guardo
    over = list((tmp_path / ".aci_overflow").glob("*.txt"))
    assert over and over[0].read_text(encoding="utf-8") == largo


def test_run_tool_aplica_trim(tmp_path, monkeypatch):
    import cognia.agents.workers.dev_tools as dev
    monkeypatch.setattr(dev, "AGENT_WORKSPACE_ROOT", str(tmp_path))
    tools.TOOLS["_falsa_larga"] = {
        "fn": lambda a, c: "RESULTADO _falsa_larga: " + ("Y" * 4000),
        "doc": "x", "danger": False}
    try:
        r = tools.run_tool("_falsa_larga", "", {})
        assert "chars omitidos" in r and len(r) < 2500
    finally:
        del tools.TOOLS["_falsa_larga"]
