# -*- coding: utf-8 -*-
"""Gate del auto-decompose (E-INT): dificultad/encadenamiento, no longitud."""
import re

from cognia.agent.model_router import estimate_difficulty

# misma regex del gate en cli.py (_run_agent_task)
_MULTI = re.compile(
    r"(,?\s+y\s+(luego|despu[eé]s)\b|,\s*then\b|\band\s+then\b|;\s*(luego|then)\b)",
    re.IGNORECASE)


def _decompone(task: str) -> bool:
    return estimate_difficulty(task) >= 0.30 or bool(_MULTI.search(task))


def test_larga_pero_simple_no_descompone():
    # >120 chars (gate viejo la descomponia) pero trivial: cero senales duras
    t = ("escribí un archivo llamado notas_de_la_reunion_del_martes.txt con el "
         "texto 'la reunión fue muy buena y todos estuvieron de acuerdo en todo'")
    assert len(t) > 120
    assert not _decompone(t)


def test_corta_pero_dura_descompone():
    t = "implementá quicksort in-place sin usar librerías, cuidando overflow"
    assert len(t) < 120
    assert _decompone(t)


def test_encadenada_descompone():
    assert _decompone("creá datos.csv con 3 filas y luego contá las líneas")
    assert _decompone("write the file, then run the tests")


def test_simple_corta_no_descompone():
    assert not _decompone("escribí hola en nota.txt")
