# -*- coding: utf-8 -*-
"""apendar_archivo: el modelo envuelve el texto en comillas y escapa el salto.

Regresion medida el 2026-07-24 reproduciendo la tarea 'apendar' del gate del
camino feliz: el 7B emitia `apendar_archivo bitacora.txt | "tercera\\n"` y el
archivo quedaba con la linea literal `"tercera\\n"` — comillas y barra incluidas.
"""
from cognia.agent.tools import _texto_literal, run_tool


def test_quita_comillas_envolventes():
    assert _texto_literal("'tercera'") == "tercera"
    assert _texto_literal('"tercera"') == "tercera"


def test_traduce_el_salto_escapado():
    assert _texto_literal('"tercera\\n"') == "tercera\n"
    assert _texto_literal("'a\\tb'") == "a\tb"


def test_respeta_comillas_internas():
    """Un texto con comillas EN EL MEDIO es legitimo: no se toca."""
    assert _texto_literal('dijo "hola" y se fue') == 'dijo "hola" y se fue'
    assert _texto_literal('"dijo "hola""') == '"dijo "hola""'


def test_texto_normal_intacto():
    assert _texto_literal("tercera") == "tercera"
    assert _texto_literal("") == ""
    assert _texto_literal("no cierra'") == "no cierra'"


def test_apendar_deja_la_linea_limpia(tmp_path, monkeypatch):
    """El caso completo del gate: la ultima linea debe ser exactamente 'tercera'."""
    import cognia.agents.workers.dev_tools as dev_tools
    monkeypatch.setattr(dev_tools, "AGENT_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("COGNIA_AGENT_WORKSPACE", str(tmp_path))
    (tmp_path / "bitacora.txt").write_text("primera\nsegunda\n", encoding="utf-8")

    r = run_tool("apendar_archivo", 'bitacora.txt | "tercera\\n"', {})
    assert "OK" in r
    lineas = (tmp_path / "bitacora.txt").read_text(encoding="utf-8").strip().splitlines()
    assert lineas == ["primera", "segunda", "tercera"]


# NOTA: se probo extender la limpieza de envoltorio a escribir_archivo para
# texto plano; el A/B del gate no mostro mejora (3/6 vs 4/6) y se revirtio.
# Por eso aca solo se cubre apendar_archivo.
