"""
busqueda_web como fuente del research_engine.

GitHub y HuggingFace son CATALOGOS: saben de repos y de modelos, no de
conceptos. Wikipedia y HackerNews son lo que permite responder preguntas
abiertas, que es la brecha que el dueno dejo anotada el 2026-07-20.

No se le pide arxiv a busqueda_web aunque lo tenga: el ArxivScraper del propio
research_engine da abstract, ano y categorias, y pedir las dos duplicaria.
"""

from unittest.mock import patch

from cognia.research_engine.web_research import investigar


RESULTADOS_WEB = [
    {"titulo": "Rust (lenguaje)", "url": "https://es.wikipedia.org/wiki/Rust",
     "fragmento": "Rust es un lenguaje con ownership y borrow checker.",
     "fuente": "wikipedia"},
    {"titulo": "Understanding Rust ownership", "url": "https://news.example/1",
     "fragmento": "Ownership explicado.", "fuente": "hackernews"},
]


def _investigar_solo_web(**kw):
    """Aisla la fuente web: sin GitHub, HF, arXiv, LLM ni contraevidencia."""
    return investigar("rust ownership", n_queries=1, max_por_fuente=3,
                      usar_github=False, usar_hf=False, usar_arxiv=False,
                      usar_llm=False, con_contra=False, **kw)


def test_los_resultados_web_entran_como_hallazgos():
    with patch("cognia.research_engine.web_research.buscar",
               return_value=RESULTADOS_WEB):
        digest = _investigar_solo_web(usar_web=True)

    fuentes = {h.fuente for h in digest.hallazgos}
    assert "wikipedia" in fuentes
    assert "hackernews" in fuentes


def test_usar_web_false_no_consulta_nada():
    with patch("cognia.research_engine.web_research.buscar") as mock_buscar:
        digest = _investigar_solo_web(usar_web=False)

    mock_buscar.assert_not_called()
    assert digest.hallazgos == []


def test_no_le_pide_arxiv_a_busqueda_web():
    """El research_engine ya tiene ArxivScraper: pedirlo aqui duplicaria."""
    with patch("cognia.research_engine.web_research.buscar",
               return_value=RESULTADOS_WEB) as mock_buscar:
        _investigar_solo_web(usar_web=True)

    assert mock_buscar.called
    for llamada in mock_buscar.call_args_list:
        assert "arxiv" not in llamada.kwargs.get("fuentes", ())


def test_una_fuente_web_caida_no_tumba_la_investigacion():
    """
    Contrato: una fuente de red que revienta no puede llevarse por delante una
    investigacion que ya tiene resultados de GitHub y arXiv.
    """
    with patch("cognia.research_engine.web_research.buscar",
               side_effect=OSError("red caida")):
        digest = _investigar_solo_web(usar_web=True)   # no debe lanzar

    assert digest.hallazgos == []


def test_popularidad_cero_no_inventada():
    """
    Ni Wikipedia ni HN dan una metrica comparable con estrellas o descargas.
    puntuar() usa popularidad: un 0 honesto es mejor que un numero inventado
    que los colocaria por encima de repos con traccion real.
    """
    with patch("cognia.research_engine.web_research.buscar",
               return_value=RESULTADOS_WEB):
        digest = _investigar_solo_web(usar_web=True)

    for h in digest.hallazgos:
        assert h.popularidad == 0
