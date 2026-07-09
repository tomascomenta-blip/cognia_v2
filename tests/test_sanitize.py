# -*- coding: utf-8 -*-
"""Saneo de cola degenerada del responder (casos REALES de la batería e2e)."""
import pytest

from cognia.agent.sanitize import trim_degenerate_tail


@pytest.mark.parametrize("sucio,limpio", [
    ("Listo, tarea completada. fitte fitte fitte fitte fitte",
     "Listo, tarea completada."),
    ("Zanahoria fitte fitte fitte fitte fi",           # fragmento final cortado
     "Zanahoria"),
    ("Listo, conteje 4 líneas en total.txt fitteado fitte fitte fitte fi",
     "Listo, conteje 4 líneas en total.txt fitteado"),
])
def test_corta_cola_real(sucio, limpio):
    assert trim_degenerate_tail(sucio) == limpio


@pytest.mark.parametrize("texto", [
    "Listo, copié origen.txt a copia.txt",
    "El resultado es 391",
    "Listo, terminé el código. fitte kInstruction",   # sin run >=3: no tocar
    "uno dos tres uno dos tres",                      # ciclo de 2+ palabras: no tocar (v1)
    "ja ja ja bueno, el chiste terminó acá",          # el run NO termina el texto
    "",
])
def test_no_toca_texto_legitimo(texto):
    assert trim_degenerate_tail(texto) == texto


def test_todo_degenerado_colapsa_a_una_palabra_nunca_vacio():
    # texto 100% degenerado: colapsa a una sola ocurrencia (nunca a vacío —
    # si el saneo dejara vacío se devuelve el original, señal de bug arriba)
    assert trim_degenerate_tail("fitte fitte fitte fitte") == "fitte"
    assert trim_degenerate_tail("   ") == "   "
