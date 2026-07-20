"""Regresión CYCLE 7: classify() del router de cascada de habla manda turnos
sociales/triviales al 0.5B rápido y los sustantivos al 3B (calidad gana ante la duda)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cognia_x.experiments.exp021_speculative_decode.cascade_router import classify


def test_sociales_van_a_fast():
    for t in ["Hola, ¿cómo estás?", "Gracias, muy amable.", "sí",
              "Buenas noches, hasta mañana.", "ok", "Genial!"]:
        assert classify(t) == "fast", t


def test_sustantivos_van_a_deep():
    for t in ["¿Por qué el cielo es azul?", "Explícame qué es la fotosíntesis.",
              "Escribe una función en Python para ordenar una lista.",
              "Cuéntame la historia de Roma en detalle.",
              "¿Cuánto es la raíz cuadrada de 144 y cómo se calcula?"]:
        assert classify(t) == "deep", t


def test_default_es_deep_ante_la_duda():
    # frase larga, no claramente social, sin señal de profundidad explícita → calidad
    assert classify("Me gustaría conversar un rato sobre la vida moderna en general") == "deep"
