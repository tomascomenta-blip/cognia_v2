"""
tests/test_language_engine_pertinencia.py
=========================================
La compuerta que decide si Cognia investiga tiene que mirar si el contexto viene
al caso, no solo cuanto ocupa.

Caso real (2026-07-19): ante una pregunta sobre los modelos MiniCPM de OpenBMB,
la memoria devolvio 15 episodios del concepto 'conocimiento_python'. El contexto
pasaba el umbral de 300 caracteres, `_maybe_investigate` cortaba ahi, y la
investigacion no se ejecutaba nunca — mientras la busqueda web ya recuperaba 12
de 12 fuentes correctas que se descartaban sin usarse. El modelo respondia de
memoria parametrica e inventaba (DINOv2 para leer capturas; BLIP como
"Bootstrap-Large-Language-Model-Instruct").
"""

import pytest

from cognia.language_engine import LanguageEngine


@pytest.fixture
def motor():
    # No se construye el engine completo: _contexto_pertinente no toca estado.
    return LanguageEngine.__new__(LanguageEngine)


CTX_PYTHON = ("Python es un lenguaje de programacion interpretado de alto nivel "
              "muy usado en ciencia de datos y automatizacion. " * 4)


class TestContextoPertinente:
    def test_contexto_de_otro_tema_no_es_pertinente(self, motor):
        assert len(CTX_PYTHON) >= 300          # pasaria el umbral viejo
        assert motor._contexto_pertinente(
            "que modelos publica OpenBMB MiniCPM", CTX_PYTHON) is False

    def test_contexto_del_tema_si_es_pertinente(self, motor):
        assert motor._contexto_pertinente(
            "para que sirve Python en ciencia de datos", CTX_PYTHON) is True

    def test_ignora_acentos(self, motor):
        ctx = "La fotosintesis convierte luz solar en energia quimica. " * 6
        assert motor._contexto_pertinente("explicame la fotosíntesis", ctx) is True

    def test_pregunta_sin_terminos_de_contenido_no_fuerza_investigacion(self, motor):
        """Ante '¿y eso?' no hay nada que comparar: se conserva la conducta
        previa en vez de disparar una busqueda inutil."""
        assert motor._contexto_pertinente("y eso?", CTX_PYTHON) is True

    def test_contexto_vacio(self, motor):
        assert motor._contexto_pertinente("OpenBMB MiniCPM", "") is False

    def test_falla_hacia_el_comportamiento_previo(self, motor):
        """Si evaluar la pertinencia explota, se responde True (no investigar),
        que es lo que hacia antes: el fix no puede introducir un modo nuevo de
        fallo."""
        class Rompe:
            def __contains__(self, x):
                raise RuntimeError("boom")
        assert motor._contexto_pertinente(Rompe(), CTX_PYTHON) is True
