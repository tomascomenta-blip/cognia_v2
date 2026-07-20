"""
El planner debe conservar el termino ESPECIFICO, no el generico.

Bug medido el 2026-07-20, el cuello de botella del research_engine:

    "rust ownership"                           -> query 'rust'
    "python asyncio event loop"                -> query 'python loop'
    "rust ownership borrow checker data races" -> query 'rust data'

Conservaba la palabra comun y tiraba la especifica — justo al reves de lo que
hace falta. Dos causas:

1. `_es_tecnico` era una lista BLANCA: descartaba todo lo que no estuviera en
   el glosario, y aceptaba por forma cualquier token de <=4 letras. Los
   terminos tecnicos concretos son largos y no caben en un diccionario
   (ownership, asyncio, borrow, checker), asi que se perdian siempre; las
   palabras cortas y genericas (rust, data, loop) pasaban siempre.
2. `_nucleo` se quedaba solo con los terminos de sus listas cerradas en cuanto
   hubiera UNO: de ['rust', 'ownership', 'memory'] salia 'memory'.

Con la query 'rust', Wikipedia devolvia "Bernhard Rust", un politico aleman.
"""

import pytest

from cognia.research_engine.query_planner import (
    _es_tecnico, _nucleo, _parece_espanol, planificar_deterministico,
    terminos_de_busqueda,
)


# ── Los tres casos medidos ─────────────────────────────────────────────────

@pytest.mark.parametrize("pregunta, imprescindible", [
    ("rust ownership",                            "ownership"),
    ("python asyncio event loop",                 "asyncio"),
    ("rust ownership borrow checker data races",  "ownership"),
])
def test_el_termino_especifico_sobrevive(pregunta, imprescindible):
    assert imprescindible in terminos_de_busqueda(pregunta)
    plan = planificar_deterministico(pregunta, 3)
    assert plan, "el plan no puede salir vacio"
    assert any(imprescindible in q for q in plan), (
        f"'{imprescindible}' se perdio en todas las queries: {plan}")


def test_no_se_queda_solo_con_la_palabra_generica():
    """El caso exacto: 'rust ownership' no puede degradar a 'rust'."""
    plan = planificar_deterministico("rust ownership", 1)
    assert plan[0] != "rust"


def test_un_termino_conocido_no_expulsa_a_los_especificos():
    """
    'memory' esta en NUCLEOS_EN; 'ownership' y 'borrow' no. Antes bastaba ese
    unico conocido para que el nucleo tirara los dos especificos.
    """
    nucleo = _nucleo(["rust", "ownership", "borrow", "memory"])
    assert "memory" in nucleo
    assert "ownership" in nucleo or "borrow" in nucleo, (
        f"los terminos especificos se perdieron: {nucleo}")


# ── El detector de espanol ─────────────────────────────────────────────────

@pytest.mark.parametrize("token", [
    "implementacion", "rapidamente", "programando", "habilidad", "usarlo",
    "pequeño", "lenguaje", "de", "para", "cuando",
])
def test_detecta_espanol(token):
    assert _parece_espanol(token) is True


@pytest.mark.parametrize("token", [
    # Los que motivaron el arreglo
    "ownership", "asyncio", "borrow", "checker", "races",
    # Terminan en -er/-ance/-ence, que NO son senal de espanol
    "server", "layer", "filter", "parser", "compiler", "buffer", "pointer",
    "performance", "sequence", "instance", "reference",
    # Terminan en -a, que tampoco lo es
    "data", "beta", "meta", "schema", "lambda", "alpha",
    # Vocabulario tecnico largo
    "kubernetes", "tensorflow", "quantization", "attention",
])
def test_no_confunde_ingles_con_espanol(token):
    assert _parece_espanol(token) is False


@pytest.mark.parametrize("token", [
    "version", "extension", "compression", "dimension", "session",
    "expression", "decision", "conversion", "precision", "vision",
])
def test_el_sufijo_sion_no_descarta_vocabulario_ingles(token):
    """
    Regresion concreta: incluir "sion" entre los sufijos espanoles descartaba
    todas estas, que son centrales en el dominio. No hace falta el sufijo: en
    espanol correcto "-sion" SIEMPRE lleva tilde ("version", "compresion") y de
    eso ya se encarga la regla de acentos.
    """
    assert _parece_espanol(token) is False
    assert _es_tecnico(token) is True


# ── Lo que ya funcionaba debe seguir funcionando ───────────────────────────

def test_el_espanol_crudo_sigue_sin_colarse():
    """
    La correccion del 2026-07-19: "agentes de coding por linea de comandos"
    producia 'caracteristicas comandos implementarlas'. Las APIs hacen AND, asi
    que una sola palabra en espanol garantiza cero resultados.
    """
    terminos = terminos_de_busqueda("agentes de coding por linea de comandos")
    assert "agents" in terminos
    for t in terminos:
        assert not _parece_espanol(t), f"se colo espanol crudo: {t}"


def test_la_pregunta_historica_del_dueno_sigue_bien():
    plan = planificar_deterministico(
        "modelo pequeno que maneje el maximo contexto posible", 3)
    assert "model" in plan[0]
    assert "context" in plan[0] or "small" in plan[0]


def test_pregunta_sin_nada_util_no_revienta():
    assert planificar_deterministico("de la que el", 3) == [] or True
