"""Tests del bus de eventos (cognia/ux/events.py) — el contrato de la obra
2026-08-09: emitir nunca lanza, los suscriptores reciben los dataclasses, y el
sink JSONL serializa cada evento como una linea JSON con su tipo."""
import json

import pytest

from cognia.ux import events


@pytest.fixture(autouse=True)
def _bus_limpio():
    """Cada test arranca sin suscriptores heredados (el bus es modulo-global)."""
    with events._lock:
        previos = list(events._suscriptores)
        events._suscriptores.clear()
    yield
    with events._lock:
        events._suscriptores.clear()
        events._suscriptores.extend(previos)


def test_emitir_reparte_a_suscriptores():
    vistos = []
    events.suscribir(vistos.append)
    ev = events.ToolInicio(tool="leer_archivo", args="motor.py", paso=1)
    events.emitir(ev)
    assert vistos == [ev]
    assert vistos[0].tool == "leer_archivo"


def test_suscriptor_roto_no_rompe_el_turno():
    vistos = []

    def roto(_):
        raise RuntimeError("adorno roto")

    events.suscribir(roto)
    events.suscribir(vistos.append)
    events.emitir(events.Aviso(texto="hola", origen="test"))
    assert len(vistos) == 1  # el segundo suscriptor recibio a pesar del roto


def test_desuscribir():
    vistos = []
    events.suscribir(vistos.append)
    events.desuscribir(vistos.append)
    events.emitir(events.TareaFin(ok=True, resumen="listo"))
    assert vistos == []


def test_a_dict_lleva_tipo_y_campos():
    d = events.a_dict(events.Degradado(
        donde="cli.agente", motivo="sin backend",
        accion_sugerida="servir_flota.py pensar"))
    assert d["tipo"] == "Degradado"
    assert d["donde"] == "cli.agente"
    assert d["ts"] > 0


def test_sink_jsonl_escribe_una_linea_por_evento(tmp_path, monkeypatch):
    ruta = tmp_path / "eventos.jsonl"
    monkeypatch.setattr(events, "_sink_jsonl", None)
    events.activar_sink_jsonl(str(ruta))
    events.emitir(events.TareaInicio(tarea="crea hola.txt", modo="agente",
                                     modelo="gpt-oss-20b"))
    events.emitir(events.TareaFin(ok=True, resumen="hecho", pasos=2))
    lineas = ruta.read_text(encoding="utf-8").strip().split("\n")
    assert len(lineas) == 2
    primero = json.loads(lineas[0])
    assert primero["tipo"] == "TareaInicio"
    assert primero["modelo"] == "gpt-oss-20b"
