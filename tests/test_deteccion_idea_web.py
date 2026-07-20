"""
Detectar "idea web" no puede ser casar "html" como subcadena.

Bug del 2026-07-20: se encargo un modulo Python de busqueda web que mencionaba
"html.parser" (stdlib de Python) y "respuestas HTML de ejemplo". El detector
casaba la pista "html" en cualquier posicion, declaro la idea web y el pipeline
genero una PAGINA HTML que simulaba un buscador en vez del modulo. Encima la
vista de navegador la evaluo como pagina y reprocho que "no cambia sola".

La familia afectada era amplia: todo pedido de Python que roce lo web
(scraping, cliente HTTP, parseo de HTML) generaba una pagina.
"""

import pytest

from cognia.program_creator.generator import _es_idea_web


# ── El bug exacto ──────────────────────────────────────────────────────────

def test_modulo_python_que_menciona_html_parser_no_es_web():
    idea = (
        "Buscador web multi-estrategia sin API key: una funcion "
        "buscar(consulta, max_resultados). Parseo de HTML con html.parser de "
        "la stdlib, sin BeautifulSoup. Solo stdlib (urllib, json). Incluye "
        "tests unitarios con unittest."
    )
    assert _es_idea_web(idea) is False


@pytest.mark.parametrize("idea", [
    "scraper en Python con urllib que extrae titulos del HTML de una pagina",
    "cliente HTTP en Python (stdlib) que descarga y parsea HTML",
    "modulo Python para convertir HTML a texto plano, con unittest",
])
def test_python_que_roza_lo_web_sigue_siendo_python(idea):
    assert _es_idea_web(idea) is False


# ── Lo que SI debe seguir detectandose como web ────────────────────────────

@pytest.mark.parametrize("idea", [
    "una pagina web con animaciones",
    "landing page para un producto",
    "dashboard web de inversiones",
    "aplicacion web de notas",
    "website personal con CSS moderno",
])
def test_las_ideas_web_de_verdad_siguen_detectandose(idea):
    assert _es_idea_web(idea) is True


def test_pista_debil_sola_sigue_contando_como_web():
    """Sin senal de Python, "html" suelto sigue significando web: es la
    heuristica original y hay ideas que solo dicen eso."""
    assert _es_idea_web("un reloj animado en HTML y CSS") is True


def test_pista_fuerte_gana_aunque_nombre_python():
    """Si piden explicitamente una pagina, da igual que citen Python."""
    assert _es_idea_web("una pagina web generada desde un script python") is True


def test_idea_de_terminal_no_es_web():
    assert _es_idea_web("gestor de tareas en terminal con SQLite") is False


def test_texto_vacio_no_revienta():
    assert _es_idea_web("") is False
    assert _es_idea_web(None) is False
