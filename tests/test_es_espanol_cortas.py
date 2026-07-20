# -*- coding: utf-8 -*-
"""Regresión del fix de instrumento es_espanol (diagnóstico G5 2026-07-10):
respuestas CORTAS correctas no deben fallar por falta de stopwords."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cognia_v3" / "eval" / "suites"))
from suite_oracle import es_espanol  # noqa: E402


def test_cortas_espanol_o_neutras_pasan():
    assert es_espanol("Feliz")
    assert es_espanol("7")
    assert es_espanol("uno, dos, tres, cuatro, cinco")
    assert es_espanol("Primavera, verano, otoño, invierno")
    assert es_espanol("Sintió mucho frío apenas entró.")


def test_cortas_con_ingles_dominante_vetadas():
    assert not es_espanol("The answer is happy")
    assert not es_espanol("It is the answer")


def test_largas_mantienen_semantica_original():
    assert es_espanol(
        "La respuesta es que el equipo perdió todos los partidos de la temporada")
    assert not es_espanol(
        "The team lost all the games of the season and it was very sad for everyone")
    # larga sin dominancia clara de es -> sigue fallando (conservador)
    assert not es_espanol(
        "one two three four five six seven eight nine ten eleven twelve")
