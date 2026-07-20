# -*- coding: utf-8 -*-
"""Lienzo visual de flujos estilo n8n (flow_view.py)."""
from cognia.agent.flow_view import build_layout, render_html


FLUJO = {"nombre": "demo", "nodos": [
    {"id": "a", "tool": "listar", "args": "x/", "wires": ["b", "c"]},
    {"id": "b", "tool": "buscar", "args": "TODO", "wires": ["d"]},
    {"id": "c", "tool": "tests", "args": "correr", "wires": ["d"]},
    {"id": "d", "tool": "responder", "args": "fin", "wires": []}]}


def test_layout_niveles_y_cables():
    lay = build_layout(FLUJO)
    assert len(lay["cajas"]) == 4
    assert len(lay["cables"]) == 4          # a->b,a->c,b->d,c->d
    xs = {c["id"]: c["x"] for c in lay["cajas"]}
    assert xs["a"] < xs["b"] and xs["b"] < xs["d"]   # columnas por profundidad


def test_render_autocontenido():
    h = render_html(FLUJO, "Prueba")
    assert "<svg" in h and "listar" in h and "responder" in h
    assert "http://" not in h and "https://" not in h and "src=" not in h
    assert "Prueba" in h and "4 pasos" in h
