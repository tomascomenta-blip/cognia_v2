# -*- coding: utf-8 -*-
"""Tests del bus de eventos interno (cognia/events.py)."""
import sys
import threading
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from cognia.events import EventBus, emit, get_bus, subscribe, unsubscribe


@pytest.fixture(autouse=True)
def _bus_limpio():
    get_bus().limpiar()
    yield
    get_bus().limpiar()


def test_emit_llega_al_suscriptor():
    visto = []
    subscribe("tool.ejecutada", visto.append)
    ev = emit("tool.ejecutada", nombre="generar_codigo", ok=True)
    assert visto == [ev]
    assert ev["nombre"] == "generar_codigo" and ev["ok"] is True
    assert "ts" in ev and ev["evento"] == "tool.ejecutada"


def test_wildcard_recibe_todo():
    visto = []
    subscribe("*", visto.append)
    emit("a.uno")
    emit("b.dos")
    assert [e["evento"] for e in visto] == ["a.uno", "b.dos"]


def test_suscriptor_roto_no_rompe_al_emisor_ni_al_resto():
    visto = []

    def roto(_ev):
        raise RuntimeError("boom")

    subscribe("x", roto)
    subscribe("x", visto.append)
    ev = emit("x")           # no debe lanzar
    assert visto == [ev]


def test_unsubscribe():
    visto = []
    subscribe("x", visto.append)
    unsubscribe("x", visto.append)
    emit("x")
    assert visto == []
    unsubscribe("x", visto.append)   # idempotente, no lanza


def test_historial_filtra_y_acota():
    bus = EventBus(historial_max=3)
    for i in range(5):
        bus.emit("e", i=i)
    bus.emit("otro")
    h = bus.historial()
    assert len(h) == 3                       # acotado
    assert h[-1]["evento"] == "otro"
    assert [e["i"] for e in bus.historial("e")] == [3, 4]


def test_callback_puede_desuscribirse_durante_emision():
    """La copia de la lista evita mutación durante iteración."""
    visto = []

    def una_vez(ev):
        visto.append(ev)
        unsubscribe("x", una_vez)

    subscribe("x", una_vez)
    emit("x")
    emit("x")
    assert len(visto) == 1


def test_thread_safety_basica():
    """Emisiones concurrentes no pierden eventos ni lanzan."""
    bus = EventBus()
    visto = []
    bus.subscribe("t", lambda ev: visto.append(ev["i"]))

    def emisor(base):
        for i in range(50):
            bus.emit("t", i=base + i)

    hilos = [threading.Thread(target=emisor, args=(k * 100,))
             for k in range(4)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    assert len(visto) == 200


def test_subscribe_no_callable_lanza():
    with pytest.raises(TypeError):
        subscribe("x", "no soy callable")
