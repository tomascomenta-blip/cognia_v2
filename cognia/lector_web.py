"""
lector_web.py — leer el TEXTO de una pagina web.

PARA QUE: el motor de investigacion encuentra enlaces pero no lee lo que hay
detras. Juzga un repo por su descripcion de una linea y un paper por su
abstract. Este modulo convierte "encontre un link" en "lei la fuente": es la
pieza que hace posible verificar un hallazgo contra su contenido real en vez
de contra su titulo.

Deliberadamente simple: el extractor solo distingue dentro/fuera de tags
ignorados (script, style...). No mantiene estado entre filas ni estructuras
complejas — eso es justo lo que se midio que excede al modelo local, y ademas
no hace falta para extraer texto legible.

Seguridad: solo http/https. Un lector que abre file:// es un agujero — leeria
cualquier fichero local y lo metería en el contexto del modelo.

Autoria: escrito por Cognia via G4 (generar -> revisar -> integrar). Sus dos
primeros bugs (timeout en Request en vez de urlopen, `re` sin importar) los
tapaba su propio except y TODA url devolvia "": el patron de degradacion
silenciosa de siempre, esta vez en el modulo recien nacido. El centinela
corrigio ademas el except de la reparacion, que referenciaba
html.parser.HTMLParseError — eliminado de Python en la 3.5 — con lo que
cualquier error de red lanzaba AttributeError al evaluar la tupla del except.

    from cognia.lector_web import leer
    texto = leer("https://es.wikipedia.org/wiki/Rust", max_chars=4000)
"""

from __future__ import annotations

import html
import html.parser
import logging
import re
import urllib.request

logger = logging.getLogger(__name__)

USER_AGENT = "Cognia/1.0 (+local research)"
TIMEOUT = 10

# Una pagina mas grande que esto es un dump, no un articulo.
MAX_BYTES = 500_000

# Dentro de estos tags no hay texto para humanos.
_IGNORADOS = {"script", "style", "noscript", "template", "svg"}

# Tags que separan bloques: sin el salto de linea el texto sale todo pegado.
_BLOQUES = {"br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}


class _ExtractorTexto(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.profundidad_ignorados = 0
        self.texto_acumulado: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in _IGNORADOS:
            self.profundidad_ignorados += 1
        elif self.profundidad_ignorados == 0 and tag in _BLOQUES:
            self.texto_acumulado.append("\n")

    def handle_endtag(self, tag):
        # Sin dejarlo ir por debajo de 0: HTML real trae </script> huerfanos.
        if tag in _IGNORADOS and self.profundidad_ignorados > 0:
            self.profundidad_ignorados -= 1

    def handle_data(self, data):
        if self.profundidad_ignorados == 0:
            self.texto_acumulado.append(data)


def leer(url: str, max_chars: int = 4000) -> str:
    """
    Texto visible de la pagina, limpio y recortado a max_chars. "" si no se
    pudo. NUNCA lanza.
    """
    if not url.startswith(("http://", "https://")):
        logger.warning("Lector: esquema no permitido en %s (solo http/https)",
                       url)
        return ""

    try:
        peticion = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(peticion, timeout=TIMEOUT) as respuesta:
            # Un PDF o un zip decodificado a lo bruto mete basura binaria en
            # el contexto del modelo: mejor nada que eso.
            if respuesta.headers.get_content_type() not in ("text/html",
                                                            "text/plain"):
                return ""
            crudo = respuesta.read(MAX_BYTES)
            charset = respuesta.headers.get_content_charset() or "utf-8"
            contenido = crudo.decode(charset, errors="replace")

        extractor = _ExtractorTexto()
        extractor.feed(contenido)
        texto = "".join(extractor.texto_acumulado)

        texto = html.unescape(texto)
        texto = re.sub(r"\n{3,}", "\n\n", texto)
        texto = re.sub(r"[ \t]+", " ", texto)
        return texto.strip()[:max_chars]

    except Exception as e:
        # Amplio a proposito, porque el contrato es no lanzar NUNCA. El
        # riesgo conocido de un except asi es que esconda bugs propios (ya
        # escondio dos en este mismo modulo): por eso SIEMPRE deja warning
        # con la causa — un "" con su porque en el log, no un "" mudo.
        logger.warning("Lector: no pude leer %s: %s", url, e)
        return ""
