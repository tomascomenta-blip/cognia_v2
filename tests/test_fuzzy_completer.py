"""
tests/test_fuzzy_completer.py
=============================
Paleta fuzzy de /comandos (fzf-style): FuzzyCompleter de prompt_toolkit
envolviendo al _CogniaCompleter real de cli.py.

POR QUE se testea el envoltorio directo y no la PromptSession: el fuzzy
es pura composicion (FuzzyCompleter(inner)) y get_completions funciona
con un Document sintetico, sin tty ni consola Win32 — el mismo camino
que recorre el REPL al teclear.

NOTA sobre '/hz' -> '/hacer' (pedido original): el fuzzy de
prompt_toolkit exige SUBSECUENCIA (letras en orden) y 'hacer' no
contiene 'z', asi que ese par es imposible por diseno del matcher. Se
prueban pares reales equivalentes: '/hcr' -> '/hacer', '/plr' ->
'/pulir', '/esfz' -> '/esfuerzo'.
"""

import pytest

pytest.importorskip("prompt_toolkit")

from prompt_toolkit.completion import CompleteEvent, FuzzyCompleter
from prompt_toolkit.document import Document

import cognia.cli as cli


def _completer_fuzzy():
    inner_cls = getattr(cli, "_CogniaCompleter", None)
    if inner_cls is None:  # sin prompt_toolkit el REPL cae a input() plano
        pytest.skip("cli sin prompt_toolkit: no hay _CogniaCompleter")
    return FuzzyCompleter(inner_cls())


def _textos(entrada: str) -> list:
    doc = Document(entrada, len(entrada))
    comps = list(_completer_fuzzy().get_completions(doc, CompleteEvent()))
    return [c.text for c in comps]


def test_fuzzy_hcr_ofrece_hacer():
    # subsecuencia h-c-r dentro de 'hacer': el typo/atajo no castiga
    assert "/hacer" in _textos("/hcr")


def test_fuzzy_plr_ofrece_pulir():
    assert "/pulir" in _textos("/plr")


def test_fuzzy_esfz_ofrece_esfuerzo():
    assert "/esfuerzo" in _textos("/esfz")


def test_prefijo_exacto_sigue_funcionando():
    # regresion: lo que el completer viejo ofrecia por prefijo debe
    # seguir apareciendo envuelto en fuzzy
    assert "/hacer" in _textos("/hac")


def test_match_exacto_va_primero():
    # el comando tipeado completo debe quedar arriba: si el fuzzy
    # reordenara el match exacto, el Tab del usuario elegiria otro
    textos = _textos("/pulir")
    assert textos and textos[0] == "/pulir"


def test_sin_slash_no_explota_y_no_sugiere():
    # el inner solo se activa con '/': texto libre no debe sugerir nada
    assert _textos("hola mundo") == []


def test_letra_inexistente_no_matchea():
    # documenta el limite del matcher: 'z' no esta en 'hacer', asi que
    # '/hz' NO puede ofrecer /hacer (subsecuencia estricta)
    assert "/hacer" not in _textos("/hz")
