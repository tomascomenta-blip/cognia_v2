import unittest
from unittest.mock import patch
from io import BytesIO
import json
import xml.etree.ElementTree as ET
from urllib.error import URLError

from cognia.busqueda_web import buscar, _sin_html

WIKIPEDIA_RESPONSE = json.dumps({
    "query": {"search": [
        {"ns": 0, "title": "Python", "pageid": 2330,
         "snippet": "utiles en programacion asincrona. Nuevas funciones en <span class=\"searchmatch\">asyncio</span>: Mejoras"}
    ]}
}).encode('utf-8')

HACKERNEWS_RESPONSE = json.dumps({
    "hits": [
        {"title": "I don't understand Python's Asyncio",
         "url": "http://lucumr.pocoo.org/2016/10/30/i-dont-understand-asyncio/",
         "story_text": None, "author": "kaishiro"},
        {"title": None, "url": None, "story_text": "soy un comentario"}
    ]
}).encode('utf-8')

ARXIV_RESPONSE = b"""<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2508.01675v1</id>
    <title>Asynchronous Federated Learning with non-convex
  client objective functions</title>
    <summary>Federated Learning (FL) enables collaborative
  model training.</summary>
  </entry>
</feed>"""

class TestBusquedaWeb(unittest.TestCase):

    def setUp(self):
        pass

    def test_buscar_wikipedia(self):
        with patch('urllib.request.urlopen') as mock_urlopen:
            mock_urlopen.return_value = BytesIO(WIKIPEDIA_RESPONSE)
            resultados = buscar("python asyncio", 1)
            self.assertEqual(len(resultados), 1)
            self.assertEqual(resultados[0]["titulo"], "Python")
            self.assertEqual(resultados[0]["url"], "https://es.wikipedia.org/wiki/Python")
            self.assertEqual(resultados[0]["fragmento"], "utiles en programacion asincrona. Nuevas funciones en asyncio: Mejoras")
            self.assertEqual(resultados[0]["fuente"], "wikipedia")

    def test_buscar_hackernews(self):
        with patch('urllib.request.urlopen', side_effect=[
                BytesIO(b'{}'),                    # wikipedia: sin "query" -> []
                BytesIO(HACKERNEWS_RESPONSE)]):      # hackernews: si responde
            resultados = buscar("python asyncio", 2)
            self.assertEqual(len(resultados), 1)
            self.assertEqual(resultados[0]["titulo"], "I don't understand Python's Asyncio")
            self.assertEqual(resultados[0]["url"], "http://lucumr.pocoo.org/2016/10/30/i-dont-understand-asyncio/")
            self.assertEqual(resultados[0]["fragmento"], "")
            self.assertEqual(resultados[0]["fuente"], "hackernews")

    def test_buscar_arxiv(self):
        with patch('urllib.request.urlopen', side_effect=[
                BytesIO(b'{}'),                    # wikipedia: sin "query" -> []
                BytesIO(b'{}'),                    # hackernews: sin "hits" -> []
                BytesIO(ARXIV_RESPONSE)]):          # arxiv: si responde
            resultados = buscar("python asyncio", 1)
            self.assertEqual(len(resultados), 1)
            self.assertEqual(resultados[0]["titulo"], "Asynchronous Federated Learning with non-convex client objective functions")
            self.assertEqual(resultados[0]["url"], "http://arxiv.org/abs/2508.01675v1")
            self.assertEqual(resultados[0]["fragmento"], "Federated Learning (FL) enables collaborative model training.")
            self.assertEqual(resultados[0]["fuente"], "arxiv")

    def test_buscar_con_URLError(self):
        with patch('urllib.request.urlopen', side_effect=URLError("mocked error")) as mock_urlopen:
            resultados = buscar("python asyncio", 1)
            self.assertEqual(resultados, [])

    def test_buscar_cascada_wikipedia_vacia(self):
        with patch('urllib.request.urlopen', side_effect=[BytesIO(b'{}'), BytesIO(HACKERNEWS_RESPONSE), BytesIO(ARXIV_RESPONSE)]) as mock_urlopen:
            resultados = buscar("python asyncio", 1)
            self.assertEqual(len(resultados), 1)
            self.assertEqual(resultados[0]["fuente"], "hackernews")

    def test_buscar_todas_fuentes_vacias(self):
        with patch('urllib.request.urlopen', side_effect=[BytesIO(b'{}'), BytesIO(b'{}'), BytesIO(b'{}')]) as mock_urlopen:
            resultados = buscar("python asyncio", 1)
            self.assertEqual(resultados, [])

    def test_una_fuente_no_monopoliza_el_resultado(self):
        """
        Regresion del bug de diseno del 2026-07-20: buscar() era una cascada
        ("la primera fuente que devuelva algo gana") y Wikipedia se lo quedaba
        todo, porque casa de forma laxa y SIEMPRE devuelve algo. HackerNews y
        arXiv no se consultaban nunca. Medido: buscar("rust ownership model")
        devolvia el articulo de Ethereum.

        Con las tres fuentes respondiendo, el resultado debe traer mas de una.
        """
        with patch('urllib.request.urlopen', side_effect=[
                BytesIO(WIKIPEDIA_RESPONSE),
                BytesIO(HACKERNEWS_RESPONSE),
                BytesIO(ARXIV_RESPONSE)]):
            resultados = buscar("python asyncio", 6)

        fuentes = {r["fuente"] for r in resultados}
        self.assertGreater(len(fuentes), 1,
                           f"una sola fuente monopolizo el resultado: {fuentes}")
        self.assertIn("wikipedia", fuentes)
        self.assertIn("hackernews", fuentes)

    def test_no_repite_la_misma_url(self):
        """Las fuentes se solapan; mezclar sin deduplicar repetiria enlaces."""
        misma = json.dumps({"hits": [
            {"title": "A", "url": "https://ejemplo/x", "story_text": None},
            {"title": "B", "url": "https://ejemplo/x", "story_text": None},
        ]}).encode()
        with patch('urllib.request.urlopen', side_effect=[
                BytesIO(b'{}'), BytesIO(misma), BytesIO(b'<feed></feed>')]):
            resultados = buscar("lo que sea", 6)

        urls = [r["url"] for r in resultados]
        self.assertEqual(len(urls), len(set(urls)), f"urls repetidas: {urls}")

    def test_sin_html(self):
        texto_html = "utiles en programacion asincrona. Nuevas funciones en <span class=\"searchmatch\">asyncio</span>: Mejoras"
        texto_plano = _sin_html(texto_html)
        self.assertEqual(texto_plano, "utiles en programacion asincrona. Nuevas funciones en asyncio: Mejoras")

if __name__ == '__main__':
    unittest.main()