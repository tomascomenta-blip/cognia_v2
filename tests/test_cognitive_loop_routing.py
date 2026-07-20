"""Tests de regresión del CognitiveLoop (SESSION 1).

Sin LLM real: usa un callable dummy para verificar clasificación de modos,
inyección de contexto y el adapter _call_llm. Falla sin cognitive_loop.py,
pasa con él.
"""
import pytest

from cognia_v3.interfaces.cognitive_loop import CognitiveLoop, CogniaResponse


class FakeKG:
    """KG mínimo con la misma forma que cognia_v3.core.cognia_v3.KnowledgeGraph."""

    def __init__(self):
        import networkx as nx
        self._g = nx.DiGraph()
        self._g.add_edge("perro", "mamifero")

    def _get_graph(self):
        return self._g

    def get_facts(self, concept, predicate=None):
        if concept == "perro":
            return [{"subject": "perro", "predicate": "is_a", "object": "mamifero", "weight": 1.0}]
        return []


def echo_llm(prompt: str) -> str:
    return f"ECHO: {prompt}"


@pytest.fixture
def loop():
    return CognitiveLoop(kg=FakeKG(), language_engine=echo_llm)


@pytest.mark.parametrize("query,expected", [
    ("Hello, how are you today?", "FAST"),
    ("What did I say last time about music?", "RECALL"),
    ("Explain why rain causes floods step by step.", "DELIBERATE"),
    ("Write a Python function to sort a list.", "ACT"),
    ("¿Por qué el cielo es azul?", "DELIBERATE"),
    ("Crea un programa que sume dos números.", "ACT"),
    ("Recuerda qué te dije ayer.", "RECALL"),
])
def test_classify_modes(loop, query, expected):
    assert loop.classify(query) == expected


def test_kg_concept_triggers_recall(loop):
    # "perro" existe en el KG → la query sin keywords va a RECALL, no FAST
    assert loop.classify("el perro de mi casa") == "RECALL"


def test_recall_injects_kg_context(loop):
    resp = loop.process("el perro de mi casa")
    assert resp.mode_used == "RECALL"
    assert any("perro is_a mamifero" in c for c in resp.context_used)
    assert "Context" in resp.answer  # el prompt aumentado llegó al LLM


def test_fast_passthrough(loop):
    resp = loop.process("Hola!")
    assert resp.mode_used == "FAST"
    assert resp.answer == "ECHO: Hola!"


def test_act_two_phase(loop):
    resp = loop.process("Write a haiku generator")
    assert resp.mode_used == "ACT"
    assert len(resp.reasoning_steps) == 1
    assert "Break into 3 numbered steps" in resp.reasoning_steps[0]


def test_call_llm_respond_signature():
    """Adapter para el LanguageEngine del repo: respond(cognia, q) -> .response"""

    class FakeEngineResult:
        response = "ok"

    class FakeLanguageEngine:
        def respond(self, cognia_instance, question, pre_built_context=""):
            return FakeEngineResult()

    loop = CognitiveLoop(kg=FakeKG(), language_engine=FakeLanguageEngine())
    assert loop._call_llm("test") == "ok"


def test_returns_cognia_response_dataclass(loop):
    resp = loop.process("Hello, how are you today?")
    assert isinstance(resp, CogniaResponse)
    assert 0.0 <= resp.confidence <= 1.0
