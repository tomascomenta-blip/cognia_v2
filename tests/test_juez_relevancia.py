"""
El juez de relevancia: el LLM decide si un hallazgo RESPONDE, no si casa.

Motivo (medido 2026-07-20): el ranking lexico puntuaba por coincidencia de
palabras y colaba homonimos. "Bernhard Rust" (politico aleman) salia arriba en
una pregunta sobre el lenguaje Rust, y rusty.hpp (C++) por encima del
compilador real. El LLM estaba levantado y solo redactaba: nunca juzgaba.
"""

from dataclasses import dataclass
from unittest.mock import patch

from cognia.research_engine.juez import _parsear_veredictos, juzgar


@dataclass
class H:
    fuente: str
    titulo: str
    resumen: str
    relevancia: float
    extra: str = ""


def _lote():
    return [
        H("wikipedia", "Bernhard Rust", "German Nazi politician.", 10.0),
        H("github", "rust-lang/rust", "The Rust programming language.", 9.0),
        H("hackernews", "Borrow checker deep dive", "Ownership in Rust.", 8.0),
    ]


# ── El parser ──────────────────────────────────────────────────────────────

def test_parser_formato_exacto():
    assert _parsear_veredictos("1: SI\n2: NO") == {1: True, 2: False}


def test_parser_tolerante_a_variantes():
    assert _parsear_veredictos("1. YES\n2 - no\n3: si") == {
        1: True, 2: False, 3: True}


def test_parser_ignora_lineas_ajenas():
    assert _parsear_veredictos("claro, aqui va:\n1: SI\ngracias") == {1: True}


def test_parser_sin_nada_reconocible():
    assert _parsear_veredictos("no puedo ayudarte con eso") == {}


# ── El juicio ──────────────────────────────────────────────────────────────

def test_el_no_hunde_y_reordena():
    """El caso Bernhard Rust: NO explicito -> relevancia x0.1 y al final."""
    hs = _lote()
    with patch("cognia.research_engine.juez.disponible", return_value=True), \
         patch("cognia.research_engine.juez.generar",
               return_value="1: NO\n2: SI\n3: SI"):
        out = juzgar("rust ownership", hs)

    assert [h.titulo for h in out] == [
        "rust-lang/rust", "Borrow checker deep dive", "Bernhard Rust"]
    assert out[-1].relevancia == 1.0          # 10.0 * 0.1


def test_en_la_duda_no_se_descarta():
    """
    Numero ausente de la respuesta = SI implicito. El modelo puede cortar la
    lista; eso no es culpa del hallazgo. Regresion: la primera version
    castigaba a los no juzgados, al reves.
    """
    hs = _lote()
    with patch("cognia.research_engine.juez.disponible", return_value=True), \
         patch("cognia.research_engine.juez.generar",
               return_value="1: NO"):          # solo juzga el primero
        out = juzgar("rust ownership", hs)

    # 2 y 3 sin juicio: conservan relevancia y van antes que el hundido.
    assert out[0].titulo == "rust-lang/rust"
    assert out[0].relevancia == 9.0
    assert out[1].relevancia == 8.0
    assert out[-1].titulo == "Bernhard Rust"


def test_sin_llm_pasa_todo_tal_cual():
    hs = _lote()
    with patch("cognia.research_engine.juez.disponible", return_value=False):
        out = juzgar("rust ownership", hs)
    assert out == hs
    assert out[0].relevancia == 10.0


def test_llm_caido_no_lanza():
    hs = _lote()
    with patch("cognia.research_engine.juez.disponible", return_value=True), \
         patch("cognia.research_engine.juez.generar", return_value=None):
        out = juzgar("rust ownership", hs)
    assert out == hs


def test_respuesta_imparseable_no_lanza():
    hs = _lote()
    with patch("cognia.research_engine.juez.disponible", return_value=True), \
         patch("cognia.research_engine.juez.generar",
               return_value="lo siento, no entiendo"):
        out = juzgar("rust ownership", hs)
    assert out == hs


def test_no_se_pierde_ni_duplica_ningun_hallazgo():
    """Regresion: el reorden de la v2 usaba la variable muerta del bucle y
    evaluaba los tres grupos contra un indice constante."""
    hs = _lote() + [H("github", f"extra-{i}", "x", 1.0) for i in range(15)]
    with patch("cognia.research_engine.juez.disponible", return_value=True), \
         patch("cognia.research_engine.juez.generar",
               return_value="1: NO\n2: SI"):
        out = juzgar("rust ownership", hs)

    assert len(out) == len(hs)
    assert {h.titulo for h in out} == {h.titulo for h in hs}


def test_lote_vacio():
    assert juzgar("lo que sea", []) == []
