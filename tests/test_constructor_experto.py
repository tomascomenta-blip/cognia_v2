"""
CONSTRUCTOR experto (reformulacion de flota 2026-07-24): COGNIA_CONSTRUCTOR_URL
manda las peticiones de HTML a un backend experto en UI (UIGEN-X) ANTES del
camino normal. Mismo contrato que COGNIA_CRITICO_URL: call-time, y un experto
caido nunca rompe la generacion.
"""

from unittest.mock import patch

from cognia.program_creator import generator as g


def test_html_va_al_constructor_si_hay_url(monkeypatch):
    monkeypatch.setenv("COGNIA_CONSTRUCTOR_URL", "http://127.0.0.1:8082")
    llamadas = []

    def _post(url, prompt, system, temperature):
        llamadas.append(url)
        return "Title: X\nDescription: d\nHTML Code:\n```html\n<html></html>\n```"

    with patch.object(g, "_preguntar_constructor", side_effect=_post):
        raw = g._call_llm("haz una pagina", "html")
    assert llamadas == ["http://127.0.0.1:8082"]
    assert "```html" in raw


def test_python_NO_va_al_constructor(monkeypatch):
    monkeypatch.setenv("COGNIA_CONSTRUCTOR_URL", "http://127.0.0.1:8082")
    with patch.object(g, "_preguntar_constructor") as _pc, \
         patch.object(g, "generar", return_value="algo"):
        g._call_llm("haz un script", "python")
    _pc.assert_not_called()


def test_constructor_caido_cae_al_camino_normal(monkeypatch):
    monkeypatch.setenv("COGNIA_CONSTRUCTOR_URL", "http://127.0.0.1:8082")
    with patch.object(g, "_preguntar_constructor", return_value=None), \
         patch.object(g, "generar", return_value="fallback ok") as _gen:
        raw = g._call_llm("haz una pagina", "html")
    assert raw == "fallback ok"
    _gen.assert_called_once()


def test_la_url_se_lee_en_call_time(monkeypatch):
    """Sin env no se intenta el experto, con env exportada a mitad de sesion si."""
    monkeypatch.delenv("COGNIA_CONSTRUCTOR_URL", raising=False)
    with patch.object(g, "_preguntar_constructor") as _pc, \
         patch.object(g, "generar", return_value="x"):
        g._call_llm("pagina", "html")
    _pc.assert_not_called()
