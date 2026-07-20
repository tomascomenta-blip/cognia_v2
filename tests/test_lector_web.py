"""
El lector de paginas: de "encontre un link" a "lei la fuente".

Sus dos primeros bugs (timeout como kwarg de Request, `re` sin importar) los
tapaba su propio except y TODA url devolvia "" en silencio. Y la reparacion
metio un tercero: referenciar html.parser.HTMLParseError, eliminado de Python
en la 3.5, con lo que un simple error de red lanzaba AttributeError al evaluar
la tupla del except. Estos tests fijan el contrato para que no vuelvan.
"""

import io
import urllib.error
from unittest.mock import patch

import pytest

from cognia.lector_web import leer


class _Respuesta(io.BytesIO):
    """urlopen de mentira: cuerpo + cabeceras minimas."""

    def __init__(self, cuerpo: bytes, content_type: str = "text/html",
                 charset: str = "utf-8"):
        super().__init__(cuerpo)
        self._ct, self._cs = content_type, charset

    @property
    def headers(self):
        r = self

        class _H:
            def get_content_type(self):
                return r._ct

            def get_content_charset(self):
                return r._cs
        return _H()


HTML = b"""<html><head><title>Titulo</title>
<style>body { color: red; }</style>
<script>var basura = "no debe salir";</script>
</head><body>
<h1>Rust</h1>
<p>Es un lenguaje con <b>ownership</b>.</p>
<script>mas_basura();</script>
<p>Y borrow checker.</p>
</body></html>"""


def _con(respuesta):
    return patch("urllib.request.urlopen", return_value=respuesta)


def test_extrae_el_texto_visible():
    with _con(_Respuesta(HTML)):
        t = leer("https://ejemplo.com/rust")
    assert "Rust" in t and "ownership" in t and "borrow checker" in t


def test_ignora_script_y_style():
    """El contenido de <script>/<style> no es texto para humanos."""
    with _con(_Respuesta(HTML)):
        t = leer("https://ejemplo.com/rust")
    assert "basura" not in t
    assert "color: red" not in t


def test_los_bloques_separan_con_salto():
    with _con(_Respuesta(HTML)):
        t = leer("https://ejemplo.com/rust")
    assert "\n" in t, "sin saltos el texto sale todo pegado"


def test_respeta_max_chars():
    with _con(_Respuesta(HTML)):
        assert len(leer("https://ejemplo.com/x", max_chars=10)) <= 10


def test_rechaza_lo_que_no_es_texto():
    """Un PDF decodificado a lo bruto mete basura binaria en el contexto."""
    with _con(_Respuesta(b"%PDF-1.4 ...", content_type="application/pdf")):
        assert leer("https://ejemplo.com/paper.pdf") == ""


@pytest.mark.parametrize("url", [
    "file:///C:/Windows/win.ini",
    "ftp://viejo.example/fichero",
    "javascript:alert(1)",
])
def test_solo_http_y_https(url):
    """Un lector que abre file:// leeria cualquier fichero local."""
    assert leer(url) == ""


def test_error_de_red_devuelve_vacio_sin_lanzar():
    """
    Regresion del tercer bug: la tupla del except referenciaba
    html.parser.HTMLParseError (no existe en Python 3) y este caso, en vez de
    devolver "", lanzaba AttributeError.
    """
    with patch("urllib.request.urlopen",
               side_effect=urllib.error.URLError("dns roto")):
        assert leer("https://no-existe.example") == ""


def test_html_malformado_no_lanza():
    roto = b"<html><p>texto <script>sin cerrar... </p><b><i>"
    with _con(_Respuesta(roto)):
        t = leer("https://ejemplo.com/roto")   # no debe lanzar
    assert isinstance(t, str)


def test_endtag_huerfano_no_rompe_el_contador():
    """HTML real trae </script> sin su <script>: no puede dejar el contador
    negativo y tragarse el resto de la pagina."""
    huerfano = b"<html></script><p>este texto debe salir</p></html>"
    with _con(_Respuesta(huerfano)):
        t = leer("https://ejemplo.com/h")
    assert "este texto debe salir" in t
