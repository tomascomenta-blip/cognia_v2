# -*- coding: utf-8 -*-
"""GBNF auto-generada del registry de tools (harness #3)."""
from cognia.agent.tools_grammar import build_action_grammar, grammar_para


def test_build_grammar_basico():
    g = build_action_grammar(["leer_archivo", "responder", "tests"])
    assert 'root ::= "ACCION: " tool rest' in g
    assert '"leer_archivo"' in g and '"responder"' in g and '"tests"' in g
    assert "rest ::=" in g


def test_build_grammar_vacio():
    assert build_action_grammar([]) == ""
    assert build_action_grammar([None, ""]) == ""


def test_build_grammar_dedup():
    g = build_action_grammar(["a", "a", "b"])
    assert g.count('"a"') == 1


def test_grammar_para_opt_in(monkeypatch):
    monkeypatch.delenv("COGNIA_TOOL_GRAMMAR", raising=False)
    assert grammar_para() is None                 # OFF por default
    monkeypatch.setenv("COGNIA_TOOL_GRAMMAR", "1")
    g = grammar_para()
    assert g is not None and "ACCION: " in g and "generar_codigo" in g


def test_grammar_para_acota_por_rol(monkeypatch):
    monkeypatch.setenv("COGNIA_TOOL_GRAMMAR", "1")
    g = grammar_para(allowed={"leer_archivo", "responder"})
    assert '"leer_archivo"' in g and '"responder"' in g
    assert '"escribir_archivo"' not in g          # fuera del rol
