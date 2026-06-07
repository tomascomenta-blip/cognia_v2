"""
tests/test_tool_router.py
Tests for the deterministic ToolRouter in cognia/tools/tool_router.py.
"""
import pytest
from cognia.tools.tool_router import ToolRouter, ToolChoice


@pytest.fixture
def router():
    return ToolRouter()


# ── route() ───────────────────────────────────────────────────────────

def test_route_knowledge_graph(router):
    choice = router.route("qué es Python")
    assert choice == ToolChoice.KNOWLEDGE_GRAPH


def test_route_web_search(router):
    choice = router.route("últimas noticias de IA hoy")
    assert choice == ToolChoice.WEB_SEARCH


def test_route_llm_only(router):
    choice = router.route("escribe un poema")
    assert choice == ToolChoice.LLM_ONLY


def test_route_web_search_english(router):
    choice = router.route("what is the price today")
    assert choice == ToolChoice.WEB_SEARCH


def test_route_knowledge_graph_english(router):
    choice = router.route("what is machine learning")
    assert choice == ToolChoice.KNOWLEDGE_GRAPH


def test_route_llm_only_code(router):
    choice = router.route("how do I reverse a list in Python")
    assert choice == ToolChoice.LLM_ONLY


# ── route_with_confidence() ────────────────────────────────────────────

def test_route_with_confidence_returns_tuple(router):
    result = router.route_with_confidence("qué es un grafo")
    assert isinstance(result, tuple)
    assert len(result) == 2


def test_route_with_confidence_llm_only_returns_zero(router):
    choice, confidence = router.route_with_confidence("escribe un poema")
    assert choice == ToolChoice.LLM_ONLY
    assert confidence == 0.0


def test_route_with_confidence_web_search_positive(router):
    choice, confidence = router.route_with_confidence("noticias de hoy")
    assert choice == ToolChoice.WEB_SEARCH
    assert 0.0 < confidence <= 1.0


def test_route_with_confidence_kg_positive(router):
    choice, confidence = router.route_with_confidence("qué es una red neuronal")
    assert choice == ToolChoice.KNOWLEDGE_GRAPH
    assert 0.0 < confidence <= 1.0


def test_route_with_confidence_range(router):
    _, confidence = router.route_with_confidence("what is the current price")
    assert 0.0 <= confidence <= 1.0


# ── execute() ─────────────────────────────────────────────────────────

def test_execute_llm_only_returns_dict(router):
    result = router.execute("escribe un poema sobre el mar")
    assert isinstance(result, dict)
    assert "tool" in result
    assert "confidence" in result
    assert "result" in result
    assert "error" in result


def test_execute_llm_only_no_exception(router):
    # Must not raise regardless of query content
    result = router.execute("escribe un poema")
    assert result["tool"] == ToolChoice.LLM_ONLY.value


def test_execute_empty_query_no_exception(router):
    # Empty query falls through to LLM_ONLY (no hits, no exception)
    result = router.execute("")
    assert isinstance(result, dict)
    assert result["tool"] == ToolChoice.LLM_ONLY.value
    assert result["error"] is None
