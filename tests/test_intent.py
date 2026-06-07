"""
Tests for auto-routing intent detection (cognia/agent/intent.py).

Pins precision (chat must NOT be routed to the agent) and that clear actions are
detected with a sensible tool hint -- so natural language triggers tools without
a command.
"""

import pytest

from cognia.agent.intent import detect


@pytest.mark.parametrize("text,tool", [
    ("leé el archivo config.py", "leer_archivo"),
    ("que contiene el archivo main.py", "leer_archivo"),
    ("creá un archivo hola.py", "escribir_archivo"),
    ("escribí una funcion que sume", "escribir_archivo"),
    ("buscá TODO en el repo", "buscar"),
    ("listá los archivos de la carpeta", "listar"),
    ("cuánto es 25 * 13", "calcular"),
    ("resumí este texto", "resumir"),
    ("descargá de https://example.com", "http_get"),
    ("qué recordás sobre el parser", "recordar"),
])
def test_actions_route_to_agent_with_tool(text, tool):
    r = detect(text)
    assert r.needs_agent
    assert r.suggested_tool == tool


@pytest.mark.parametrize("text", [
    "hola, como estas?",
    "que es la fotosintesis",
    "explicame los embeddings",
    "por que el cielo es azul",
    "me gusta el color azul",
    "cual es la capital de Francia",
    "gracias por todo",
])
def test_chat_is_not_routed(text):
    assert not detect(text).needs_agent


def test_imperative_verb_fallback_without_specific_tool():
    r = detect("refactorizá este modulo entero")
    assert r.needs_agent
    assert r.suggested_tool == ""  # action, but let the agent pick the tool


def test_polite_filler_is_stripped():
    assert detect("por favor creá un script de prueba").needs_agent


def test_empty_is_chat():
    assert not detect("").needs_agent
    assert not detect("   ").needs_agent


def test_chat_guard_beats_a_noun_that_looks_actiony():
    # "que es" is a question, even though it contains an actiony word later.
    assert not detect("que es crear un indice invertido").needs_agent
