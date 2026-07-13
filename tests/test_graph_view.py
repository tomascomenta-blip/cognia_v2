# -*- coding: utf-8 -*-
"""Vista Obsidian-style del knowledge graph (graph_view.py)."""
from cognia.knowledge.graph_view import build_graph_data, render_html


class _FakeKG:
    def __init__(self, triples):
        self._t = triples

    def get_all_triples(self, limit=1000):
        return self._t[:limit]


def test_build_graph_data_nodos_y_aristas():
    kg = _FakeKG([
        ("perro", "is_a", "animal", 2.0),
        ("gato", "is_a", "animal", 1.5),
        ("perro", "capable_of", "ladrar", 1.0),
    ])
    d = build_graph_data(kg)
    ids = {n["id"] for n in d["nodes"]}
    assert ids == {"perro", "gato", "animal", "ladrar"}
    assert len(d["links"]) == 3
    # "animal" tiene grado 2 (perro, gato) -> val 2
    animal = next(n for n in d["nodes"] if n["id"] == "animal")
    assert animal["val"] == 2
    # colores por relación
    is_a = next(l for l in d["links"] if l["rel"] == "is_a")
    assert is_a["color"].startswith("#")
    # leyenda de relaciones ordenada por frecuencia
    assert d["rels"][0]["rel"] == "is_a" and d["rels"][0]["n"] == 2


def test_build_ignora_tripletas_vacias():
    kg = _FakeKG([("", "is_a", "x", 1.0), ("a", "is_a", "", 1.0),
                  ("a", "is_a", "b", 1.0)])
    d = build_graph_data(kg)
    assert len(d["links"]) == 1
    assert {n["id"] for n in d["nodes"]} == {"a", "b"}


def test_render_html_autocontenido():
    kg = _FakeKG([("perro", "is_a", "animal", 1.0)])
    data = build_graph_data(kg)
    h = render_html(data, "Prueba")
    # HTML autocontenido: sin CDN/scripts externos, datos embebidos
    assert "<canvas" in h and "requestAnimationFrame" in h
    assert "http://" not in h and "https://" not in h   # offline/privado
    assert "src=" not in h                               # sin scripts externos
    assert "perro" in h and "animal" in h                # datos embebidos
    assert "Prueba" in h


def test_render_escapa_titulo():
    h = render_html({"nodes": [], "links": [], "rels": [], "project": None},
                    "<script>x</script>")
    assert "<script>x</script>" not in h                 # escapado en el título


def test_build_grande_no_rompe():
    trip = [(f"n{i}", "related_to", f"n{i+1}", 1.0) for i in range(300)]
    d = build_graph_data(_FakeKG(trip), limit=600)
    assert len(d["nodes"]) == 301 and len(d["links"]) == 300
