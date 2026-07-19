"""
Tests for the arXiv source and the counter-evidence step (G1 y G2 del plan
planes/INVESTIGACION_Y_ANTIRUIDO.md).

El parseo se fija contra XML REAL de la API, guardado en
tests/fixtures/arxiv_kv_cache.xml, para que un cambio de formato lo rompa
aqui y no en produccion.

Offline: no network, no LLM.
"""

from pathlib import Path

import pytest

from cognia.research_engine.arxiv_scraper import (
    ArxivScraper,
    PaperContent,
    parsear_feed,
)
from cognia.research_engine.web_research import Digest, Hallazgo

FIXTURE = Path(__file__).parent / "fixtures" / "arxiv_kv_cache.xml"


@pytest.fixture
def xml_real():
    return FIXTURE.read_text(encoding="utf-8")


@pytest.fixture
def papers(xml_real):
    return parsear_feed(xml_real)


# ── Parseo del Atom XML ─────────────────────────────────────────────────

def test_parsea_todas_las_entradas(papers):
    assert len(papers) == 3


def test_campos_basicos_no_vacios(papers):
    for p in papers:
        assert p.titulo, "todo paper debe traer titulo"
        assert p.abstract, "todo paper debe traer abstract"
        assert p.url.startswith("https://arxiv.org/abs/")
        assert p.autores, "todo paper debe traer autores"
        assert p.publicado


def test_arxiv_id_se_extrae_de_la_url(papers):
    for p in papers:
        assert p.arxiv_id
        assert "/" not in p.arxiv_id
        assert p.arxiv_id in p.url


def test_titulo_y_abstract_sin_saltos_de_linea(papers):
    """arXiv mete saltos de linea y sangrias dentro de los campos."""
    for p in papers:
        assert "\n" not in p.titulo
        assert "\n" not in p.abstract
        assert "  " not in p.titulo, "los espacios dobles deben colapsarse"


def test_anio_sale_de_la_fecha(papers):
    for p in papers:
        assert p.anio().isdigit() and len(p.anio()) == 4


def test_categorias_presentes(papers):
    assert any(p.categorias for p in papers), "alguna entrada debe traer categorias"


def test_to_learning_text_lleva_url_y_abstract(papers):
    texto = papers[0].to_learning_text()
    assert papers[0].url in texto
    assert "Abstract:" in texto
    assert papers[0].titulo in texto


def test_label_es_compacto(papers):
    for p in papers:
        assert len(p.label()) <= 70


def test_xml_ilegible_no_revienta():
    assert parsear_feed("esto no es xml") == []
    assert parsear_feed("") == []


def test_feed_sin_entradas_devuelve_lista_vacia():
    vacio = ("<?xml version='1.0' encoding='UTF-8'?>"
             "<feed xmlns='http://www.w3.org/2005/Atom'></feed>")
    assert parsear_feed(vacio) == []


def test_max_papers_recorta(xml_real):
    assert len(parsear_feed(xml_real, max_papers=2)) == 2


# ── Construccion de la query ────────────────────────────────────────────

def test_query_usa_el_and_explicito_de_arxiv():
    """
    arXiv SI entiende booleanos, al reves que GitHub y HuggingFace. Hay que
    pedir el AND en vez de rezar para que la API lo haga sola.
    """
    scraper = ArxivScraper(categorias=[])
    q = scraper._construir_search_query("long context small model")
    assert q == "all:long AND all:context AND all:small AND all:model"


def test_query_ignora_stopwords():
    scraper = ArxivScraper(categorias=[])
    q = scraper._construir_search_query("the best of the models")
    assert "all:the" not in q and "all:best" not in q
    assert "all:models" in q


def test_query_vacia_no_genera_busqueda():
    scraper = ArxivScraper()
    assert scraper._construir_search_query("de la que") == ""


def test_query_se_acota_a_categorias_de_ml_por_defecto():
    """
    La regresion medida: sin filtro de categoria, 'model small window' traia
    'Locality of the windowed local density of states' (math-ph) y un paper
    de q-bio sobre entrada viral al nucleo celular. arXiv cubre toda la
    ciencia; GitHub y HuggingFace no. Sin acotar, la busqueda esta mal
    planteada — no es ruido que se filtre despues.
    """
    q = ArxivScraper()._construir_search_query("small context model")
    assert "cat:cs.CL" in q and "cat:cs.LG" in q
    assert q.startswith("(all:"), "los terminos van agrupados aparte"
    assert " AND (cat:" in q, "las categorias van en su propio parentesis con OR"


def test_categorias_vacias_buscan_en_toda_la_ciencia():
    """Escotilla de salida para preguntas que no son de ML."""
    q = ArxivScraper(categorias=[])._construir_search_query("protein folding")
    assert "cat:" not in q


def test_respeta_la_cortesia_de_tres_segundos():
    """
    arXiv permite usar la API sin key a cambio de 3 s entre peticiones. Bajar
    esto es romper el trato, no optimizar.
    """
    from cognia.research_engine import arxiv_scraper
    assert arxiv_scraper._REQUEST_DELAY >= 3.0


# ── Contraevidencia en el informe ───────────────────────────────────────

def _hallazgo(fuente, titulo, pop=0):
    return Hallazgo(fuente=fuente, titulo=titulo, url=f"https://x/{titulo}",
                    resumen="", popularidad=pop)


def test_paper_no_muestra_contador_de_popularidad():
    """Un paper no tiene estrellas ni descargas; '0 descargas' es ruido."""
    linea = _hallazgo("arxiv", "Un Paper").linea()
    assert "descargas" not in linea and "estrellas" not in linea

    linea_repo = _hallazgo("github", "un/repo", pop=42).linea()
    assert "42 estrellas" in linea_repo


def test_informe_separa_las_tres_fuentes():
    d = Digest(pregunta="p", queries=["q"], hallazgos=[
        _hallazgo("huggingface", "org/modelo", 10),
        _hallazgo("arxiv", "Un Paper"),
        _hallazgo("github", "org/repo", 5),
    ])
    md = d.to_markdown()
    assert "## Modelos (HuggingFace)" in md
    assert "## Evidencia (arXiv)" in md
    assert "## Codigo (GitHub)" in md


def test_contraevidencia_se_muestra_y_dice_que_no_es_veredicto():
    """
    La decision de diseno central de G2: la contraevidencia es material para
    el humano, NO un fallo automatico. El informe tiene que decirlo.
    """
    d = Digest(
        pregunta="p", queries=["q"],
        hallazgos=[_hallazgo("huggingface", "org/modelo", 10)],
        contraevidencia=[_hallazgo("arxiv", "Limitaciones de org/modelo")],
    )
    md = d.to_markdown()
    assert "## Contraevidencia" in md
    assert "NO son un veredicto" in md
    assert "Limitaciones de org/modelo" in md


def test_sin_contraevidencia_no_aparece_la_seccion():
    d = Digest(pregunta="p", queries=["q"],
               hallazgos=[_hallazgo("github", "org/repo", 5)])
    assert "## Contraevidencia" not in d.to_markdown()
