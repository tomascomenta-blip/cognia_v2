"""Regresión del CoT dirigido (cognia/agent/stepwise.py) contra la batería REAL del bench.

Falla sin el módulo y protege el contrato medido: los 16 items de razonamiento ACTIVAN el
empujón (donde CoT dio +50 pts) y los 4 de formato NO (donde CoT rompía compliance 0.75->0.25).

Correr: .\\venv312\\Scripts\\python.exe -m pytest tests/test_stepwise.py -q
"""
from cognia.agent.stepwise import augment_stepwise, needs_stepwise, wants_exact_format
from cognia_v3.eval.bench_reasoning import FORMAT_ITEMS, ITEMS


def test_items_razonamiento_activan():
    for iid, q, _ans in ITEMS:
        assert needs_stepwise(q), f"{iid} debería activar el empujón CoT"


def test_items_formato_no_activan():
    for fid, q, _kind, _exp in FORMAT_ITEMS:
        assert wants_exact_format(q), f"{fid} debería detectarse como pedido de formato"
        assert not needs_stepwise(q), f"{fid} NO debe activar CoT (rompe compliance, medido)"


def test_social_no_activa():
    for s in ("hola", "cómo estás?", "gracias!", "contame un chiste", "qué es un agujero negro?"):
        assert not needs_stepwise(s), s


def test_augment():
    assert augment_stepwise("hola") == "hola"
    q = ITEMS[0][1]
    out = augment_stepwise(q)
    assert out.startswith(q) and "paso a paso" in out
