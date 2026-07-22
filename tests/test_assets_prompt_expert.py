# -*- coding: utf-8 -*-
"""Tests del experto de imágenes (expandir un pedido en un prompt de difusión).

Todo CPU/sin-GPU: el módulo es solo texto. El LLM se inyecta como fake (patrón
LlmFn) para no depender de un servidor; también se prueba el fallback a plantilla
cuando no hay LLM o cuando el LLM devuelve None/basura."""
import importlib

import pytest

pe = importlib.import_module("cognia.assets.prompt_expert")


def test_import_expuesto_en_paquete():
    mod = importlib.import_module("cognia.assets")
    assert hasattr(mod, "expandir_prompt")
    assert hasattr(mod, "generar_desde_pedido")


def test_plantilla_sin_llm():
    # llm inyectado que "no existe": forzamos la vía plantilla pasando un fn None.
    d = pe.expandir_prompt("un perro", llm=lambda *a, **k: None)
    assert d["fuente"] == "plantilla"
    assert d["prompt"].startswith("un perro")
    assert d["negative"] == pe.NEGATIVO_ASSET


def test_plantilla_sesga_por_estilo():
    d = pe.expandir_prompt("a chest", estilo="pixel", llm=lambda *a, **k: None)
    assert "pixels" in d["prompt"]
    d2 = pe.expandir_prompt("a chest", estilo="pvz", llm=lambda *a, **k: None)
    assert "cartoon" in d2["prompt"]


def test_llm_inyectado_se_usa():
    fake = lambda prompt, system="", mt=200, temp=0.7: (
        "a fluffy golden retriever puppy, big round eyes, soft fur, "
        "soft studio lighting, high detail")
    d = pe.expandir_prompt("un perro", llm=fake)
    assert d["fuente"] == "llm"
    assert "golden retriever" in d["prompt"]
    assert d["negative"] == pe.NEGATIVO_ASSET


def test_llm_basura_cae_a_plantilla():
    # Respuesta demasiado corta -> no es útil -> plantilla.
    d = pe.expandir_prompt("un gato", llm=lambda *a, **k: "ok")
    assert d["fuente"] == "plantilla"


def test_llm_excepcion_no_rompe():
    def revienta(*a, **k):
        raise RuntimeError("server caído")
    d = pe.expandir_prompt("un dragón", llm=revienta)
    assert d["fuente"] == "plantilla"
    assert d["prompt"].startswith("un dragón")


def test_pedido_vacio_falla():
    with pytest.raises(ValueError):
        pe.expandir_prompt("   ")


def test_limpiar_salida_quita_comillas_y_vinetas():
    assert pe._limpiar_salida_llm('"a red apple, shiny"') == "a red apple, shiny"
    assert pe._limpiar_salida_llm("- a blue car, glossy") == "a blue car, glossy"
    assert pe._limpiar_salida_llm("1. a green frog") == "a green frog"
    assert pe._limpiar_salida_llm("2) a green frog") == "a green frog"


def test_limpiar_salida_quita_prefijos_y_lineas():
    assert pe._limpiar_salida_llm("Prompt: a wizard hat") == "a wizard hat"
    # toma la primera línea con contenido
    assert pe._limpiar_salida_llm("\n\n  a lone tower  \nblah") == "a lone tower"
    assert pe._limpiar_salida_llm("") == ""


def test_limpiar_salida_recorta_frase_larga():
    largo = "a, " * 300  # >400 chars
    out = pe._limpiar_salida_llm(largo)
    assert len(out) <= 400
