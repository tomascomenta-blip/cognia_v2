"""Tests de regresión del DatasetGenerator (SESSION 2)."""
import json

import networkx as nx
import pytest

from cognia_v3.training.dataset_gen import DatasetGenerator, TrainingPair


class MockKG:
    def __init__(self):
        self._g = nx.DiGraph()
        self._g.add_edge("dog", "mammal", relation="is_a")
        self._g.add_edge("rain", "flood", relation="causes")
        self._g.add_edge("hammer", "nail", relation="used_for")
        self._g.add_edge("foo", "bar", relation="predicado_desconocido")

    def _get_graph(self):
        return self._g


@pytest.fixture
def gen():
    return DatasetGenerator(MockKG())


def test_triples_to_pairs_uses_templates(gen):
    pairs = gen.kg_triples_to_pairs()
    by_prompt = {p.prompt: p for p in pairs}
    assert "What is a dog?" in by_prompt
    assert by_prompt["What is a dog?"].completion == "A dog is a type of mammal."
    assert by_prompt["What does rain cause?"].completion == "rain causes flood."


def test_unknown_predicate_falls_back_to_default(gen):
    pairs = gen.kg_triples_to_pairs()
    fallback = [p for p in pairs if "predicado_desconocido" in p.completion]
    assert len(fallback) == 1  # no se pierde el triple, usa DEFAULT_TEMPLATE


def test_short_subjects_filtered():
    kg = MockKG()
    kg._g.add_edge("a", "b", relation="is_a")  # demasiado corto -> filtrado
    pairs = DatasetGenerator(kg).kg_triples_to_pairs()
    assert all(len(p.prompt) > 5 for p in pairs)
    assert not any(p.completion == "A a is a type of b." for p in pairs)


def test_pairs_have_quality_and_source(gen):
    for p in gen.kg_triples_to_pairs():
        assert isinstance(p, TrainingPair)
        assert p.source == "kg_triple"
        assert 0.0 <= p.quality <= 1.0


def test_save_jsonl_roundtrip(gen, tmp_path):
    pairs = gen.kg_triples_to_pairs()
    out = tmp_path / "ds.jsonl"
    gen.save_jsonl(pairs, str(out))
    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == len(pairs)
    rec = json.loads(lines[0])
    assert set(rec) == {"prompt", "completion", "source"}
