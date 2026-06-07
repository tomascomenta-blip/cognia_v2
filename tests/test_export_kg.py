"""
tests/test_export_kg.py
Tests for scripts/export_kg_html.py — build_graph_data and generate_html.
"""
import sys
from pathlib import Path

# Allow importing scripts/ directly
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from export_kg_html import build_graph_data, generate_html


class TestBuildGraphData:
    def test_empty_triples_returns_empty_nodes_and_links(self):
        result = build_graph_data([], 500)
        assert result == {"nodes": [], "links": []}

    def test_single_triple_two_nodes_one_link(self):
        triples = [("A", "is_a", "B", 1.0)]
        result = build_graph_data(triples, 500)
        assert len(result["nodes"]) == 2
        assert len(result["links"]) == 1
        ids = {n["id"] for n in result["nodes"]}
        assert ids == {"A", "B"}

    def test_link_fields_correct(self):
        triples = [("cat", "is_a", "animal", 0.9)]
        result = build_graph_data(triples, 500)
        link = result["links"][0]
        assert link["source"] == "cat"
        assert link["target"] == "animal"
        assert link["label"] == "is_a"
        assert abs(link["value"] - 0.9) < 1e-9

    def test_limit_respected(self):
        triples = [(f"s{i}", "rel", f"o{i}", 1.0) for i in range(20)]
        result = build_graph_data(triples, limit=5)
        # limit 5 triples -> 10 unique nodes, 5 links
        assert len(result["links"]) == 5

    def test_nodes_have_id_and_group(self):
        triples = [("X", "has_property", "Y", 1.5)]
        result = build_graph_data(triples, 500)
        for node in result["nodes"]:
            assert "id" in node
            assert "group" in node
            assert 1 <= node["group"] <= 4

    def test_duplicate_entity_across_triples_single_node(self):
        triples = [
            ("hub", "is_a", "concept", 1.0),
            ("hub", "related_to", "thing", 0.5),
        ]
        result = build_graph_data(triples, 500)
        ids = [n["id"] for n in result["nodes"]]
        # "hub" appears in both triples as subject — should be a single node
        assert ids.count("hub") == 1

    def test_weight_as_float(self):
        triples = [("A", "causes", "B", 2)]
        result = build_graph_data(triples, 500)
        assert isinstance(result["links"][0]["value"], float)


class TestGenerateHtml:
    def test_returns_string_starting_with_html_tag(self):
        html = generate_html({"nodes": [], "links": []}, 0)
        assert isinstance(html, str)
        assert "<html" in html

    def test_contains_d3_cdn(self):
        html = generate_html({"nodes": [], "links": []}, 0)
        assert "d3js.org" in html

    def test_stats_embedded_in_html(self):
        data = {"nodes": [{"id": "A", "group": 1}], "links": []}
        html = generate_html(data, triple_count=3)
        assert "Triples totales" in html
        assert "3" in html

    def test_graph_json_embedded(self):
        data = {"nodes": [{"id": "Foo", "group": 2}], "links": []}
        html = generate_html(data, triple_count=1)
        assert "Foo" in html

    def test_empty_graph_shows_no_data_message(self):
        html = generate_html({"nodes": [], "links": []}, 0)
        assert "no-data" in html or "no tiene datos" in html

    def test_non_empty_graph_no_no_data_div(self):
        data = build_graph_data([("A", "is_a", "B", 1.0)], 500)
        html = generate_html(data, triple_count=1)
        assert "no tiene datos todavia" not in html
