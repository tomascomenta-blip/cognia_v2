# -*- coding: utf-8 -*-
"""Tests de la edición SEARCH/REPLACE en cascada (idea de Aider).

Cada test falla sin la estrategia que ejercita y pasa con ella: match exacto,
match tolerante a sangría (el fallo típico del modelo pequeño), todo-o-nada en
varios bloques, y el error-como-prompt con pista de líneas parecidas."""
import pytest

from cognia.agent.edit_block import (
    EditError, apply_edit, apply_edits, parse_bloques,
)


def test_match_exacto():
    content = "def f():\n    return 1\n"
    nuevo, como = apply_edit(content, "    return 1", "    return 2")
    assert nuevo == "def f():\n    return 2\n"
    assert como == "exacto"


def test_match_sangria_reindenta():
    # El fichero tiene el bloque con 8 espacios; el modelo lo manda con 4.
    content = "class C:\n    def m(self):\n        x = 1\n        return x\n"
    search = "def m(self):\n    x = 1\n    return x"      # sangría "equivocada"
    replace = "def m(self):\n    x = 2\n    return x"
    nuevo, como = apply_edit(content, search, replace)
    assert como == "sangria"
    # Se re-aplica la sangría real del fichero (8 espacios en el cuerpo).
    assert "        x = 2\n" in nuevo
    assert "    def m(self):\n" in nuevo


def test_search_no_encontrado_da_pista():
    content = "alpha = 1\nbeta = 2\ngamma = 3\n"
    with pytest.raises(EditError) as ei:
        apply_edit(content, "beta = 22", "beta = 99")
    msg = str(ei.value)
    assert "SEARCH" in msg
    assert "parecidas" in msg  # difflib surfacea 'beta = 2'


def test_search_vacio_rechazado():
    with pytest.raises(EditError):
        apply_edit("x=1\n", "   ", "y=2")


def test_varios_bloques_todo_o_nada():
    content = "a = 1\nb = 2\nc = 3\n"
    bloques = [("a = 1", "a = 10"), ("c = 3", "c = 30")]
    nuevo, estr = apply_edits(content, bloques)
    assert nuevo == "a = 10\nb = 2\nc = 30\n"
    assert estr == ["exacto", "exacto"]


def test_un_bloque_falla_no_aplica_ninguno():
    content = "a = 1\nb = 2\n"
    bloques = [("a = 1", "a = 10"), ("NOEXISTE", "x")]
    with pytest.raises(EditError) as ei:
        apply_edits(content, bloques)
    assert "bloque 2/2" in str(ei.value)


def test_parse_bloques_formato_estandar():
    texto = ("<<<<<<< SEARCH\nviejo\n=======\nnuevo\n>>>>>>> REPLACE\n")
    bloques = parse_bloques(texto)
    assert bloques == [("viejo", "nuevo")]


def test_parse_varios_bloques():
    texto = (
        "<<<<<<< SEARCH\nuno\n=======\n1\n>>>>>>> REPLACE\n"
        "algo de ruido entre bloques\n"
        "<<<<<<< SEARCH\ndos\n=======\n2\n>>>>>>> REPLACE\n"
    )
    assert parse_bloques(texto) == [("uno", "1"), ("dos", "2")]


def test_reemplazo_multilinea_por_menos_lineas():
    content = "inicio\nviejo1\nviejo2\nviejo3\nfin\n"
    nuevo, como = apply_edit(content, "viejo1\nviejo2\nviejo3", "nuevo_unico")
    assert nuevo == "inicio\nnuevo_unico\nfin\n"
