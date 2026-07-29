"""COGNIA_SIN_TROCEO quita el bloque REQUIRED del prompt web (fase 3 de la
sonda del ladrón, PREREG_ABLACION_TEXTO_20260729: la ablación apareada midió
+6 netas al quitarlo). El default queda intacto."""

import importlib

import pytest

IDEA = ("Un carrito con STOCK. OBLIGATORIO: 3 productos, data-precio 100, "
        "data-stock 2, un boton que suma y el total se recalcula siempre")


@pytest.fixture()
def build(monkeypatch):
    from cognia.program_creator import generator
    return generator._build_prompt_web


def test_default_trocea(build, monkeypatch):
    monkeypatch.delenv("COGNIA_SIN_TROCEO", raising=False)
    p = build(IDEA, "extra")
    assert "- REQUIRED component 1:" in p
    assert "Implement EVERY required component above" in p


def test_sin_troceo_quita_el_bloque_entero(build, monkeypatch):
    monkeypatch.setenv("COGNIA_SIN_TROCEO", "1")
    p = build(IDEA, "extra")
    assert "REQUIRED component" not in p
    assert "Implement EVERY" not in p
    # la idea INTEGRA sigue en la cabecera: solo desaparece la checklist
    assert IDEA in p
    assert "Respond EXACTLY in this format" in p


def test_sin_troceo_no_toca_python(build, monkeypatch):
    from cognia.program_creator import generator
    monkeypatch.setenv("COGNIA_SIN_TROCEO", "1")
    p = generator._build_prompt("un juego de dados, con puntuacion y rondas",
                                "extra")
    # la evidencia es del prompt WEB; el de python conserva su enumeracion
    assert "- REQUIRED part 1:" in p
