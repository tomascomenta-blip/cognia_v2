"""
Regresion: el planificador colaba espanol crudo y perdia el sujeto.

Medido el 2026-07-19 corriendo /investigar de verdad. Tres defectos distintos:

  1. Vocabulario cerrado al dominio ML. "agentes de coding por linea de
     comandos" -> 'caracteristicas comandos implementarlas'. GitHub y
     HuggingFace hacen AND de todos los terminos, asi que una sola palabra en
     espanol garantiza cero resultados: colar el termino es PEOR que perderlo.
  2. Facetas solo de ML ('quantization', 'efficient inference'), inutiles para
     encontrar herramientas: asi no se cataloga un agente de terminal.
  3. El LLM derivaba del tema: de "mejor modelo para webs bonitas en GPU de
     16GB" salio 'GPU-accelerated rendering', que trajo librerias de graficos
     por computador y ni un solo modelo.

La consecuencia real: la investigacion devolvia 40 hallazgos y ninguno servia.
"""

import pytest

from cognia.research_engine.query_planner import (
    FACETAS_HERRAMIENTAS,
    _es_tecnico,
    _facetas_para,
    _traducir,
    planificar_deterministico,
)


class TestNoSeCuelaEspanol:
    """Una palabra en espanol basta para que la busqueda no devuelva nada."""

    @pytest.mark.parametrize("pregunta", [
        "caracteristicas unicas de los agentes de coding por linea de comandos",
        "servidores MCP gratuitos sin registro ni apikey para agentes de codigo",
        "herramientas de programacion con interfaz bonita",
    ])
    def test_ninguna_query_lleva_espanol(self, pregunta):
        sospechosas = {
            "caracteristicas", "comandos", "implementarlas", "servidores",
            "gratuitos", "registro", "herramientas", "programacion",
            "agentes", "codigo", "bonita", "unicas", "linea",
        }
        for q in planificar_deterministico(pregunta, 5):
            fuera = sospechosas & set(q.lower().split())
            assert not fuera, f"query en espanol: '{q}' contiene {fuera}"

    def test_traduce_el_dominio_de_herramientas(self):
        t = _traducir(["agentes", "herramientas", "servidores", "codigo"])
        assert "agents" in t
        assert "tool" in t or "tools" in t
        assert "server" in t
        assert "code" in t

    def test_descarta_lo_que_no_sabe_traducir(self):
        """Lista blanca: si no se sabe decir en ingles, no va a la query."""
        assert _traducir(["parangaricutirimicuaro"]) == []

    def test_conserva_siglas_y_versiones(self):
        t = _traducir(["mcp", "cli", "gpt-4", "16gb"])
        for esperado in ("mcp", "cli", "gpt-4", "16gb"):
            assert esperado in t


class TestSujetoPreservado:
    """Perder el sustantivo central es el peor fallo posible."""

    def test_pregunta_de_agentes_menciona_agentes(self):
        qs = planificar_deterministico(
            "caracteristicas unicas de los agentes de coding por linea de comandos", 5)
        assert any("agent" in q for q in qs), qs

    def test_pregunta_de_mcp_menciona_mcp(self):
        qs = planificar_deterministico(
            "servidores MCP gratuitos sin registro ni apikey", 5)
        assert any("mcp" in q.lower() for q in qs), qs


class TestFacetasSegunLoQueSeBusca:

    def test_buscar_herramientas_usa_facetas_de_catalogo(self):
        """'quantization' no encuentra un agente de terminal; 'awesome' si."""
        assert _facetas_para(["agent", "cli"]) == FACETAS_HERRAMIENTAS
        assert _facetas_para(["mcp", "server"]) == FACETAS_HERRAMIENTAS

    def test_buscar_papers_conserva_las_facetas_de_ml(self):
        facetas = _facetas_para(["model", "context", "quantization"])
        assert facetas != FACETAS_HERRAMIENTAS
        assert any("inference" in f or "quantization" in f for f in facetas)

    def test_una_pregunta_de_herramientas_produce_awesome(self):
        qs = planificar_deterministico(
            "agentes de coding open source por terminal", 5)
        assert any("awesome" in q for q in qs), qs


class TestFormaDeToken:

    @pytest.mark.parametrize("token", ["mcp", "cli", "gpt-4", "16gb", "agent", "api"])
    def test_tecnicos_pasan(self, token):
        assert _es_tecnico(token) is True

    @pytest.mark.parametrize("token", ["caracteristicas", "implementarlas",
                                       "gratuitos", "programacion"])
    def test_palabras_largas_en_espanol_no_pasan(self, token):
        assert _es_tecnico(token) is False


def test_no_devuelve_queries_vacias():
    """Aunque no se reconozca nada, no se emiten queries vacias."""
    for q in planificar_deterministico("zzz qqq www", 3):
        assert q.strip()
