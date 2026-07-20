"""
cognia/busqueda_web.py — busqueda web general sin API key.

Cierra (en parte) la brecha que el dueno dejo anotada el 2026-07-20: sin
busqueda web general, Cognia no puede responder "cual es el mejor X". El
research_engine ya tenia GitHub, HuggingFace y arXiv, que son catalogos: sirven
para encontrar repos y papers, no para preguntas abiertas.

POR QUE SOLO APIs JSON, y ningun raspado de HTML
-------------------------------------------------
Se intento primero con lite.duckduckgo.com. El parser no salio en dos
reparaciones seguidas — la segunda dejo el modulo PEOR que la primera (de 3
resultados a 0, y de paso rompio Wikipedia), asi que se corto por la regla 11
del repo en vez de seguir adivinando. Mantener estado entre filas de una tabla
HTML (<tr> del enlace -> <tr> del fragmento) resulto estar por encima del techo
de qwen2.5-coder-14b en este harness.

Pero la decision no es solo por el techo del modelo: raspar HTML es fragil por
definicion. La pagina cambia, el parser deja de casar y te quedas sin buscador
EN SILENCIO, que es precisamente el modo de fallo que mas caro sale en este
repo. Una API JSON es un contrato: cuando se rompe, se rompe con un codigo de
error que se puede registrar. Por eso las tres fuentes son APIs y por eso cada
fallo pasa por logger.warning con su causa.

Autoria: el modulo lo escribio Cognia (via G4: generar -> revisar -> integrar,
sin pasar por el sandbox de program_creator, que prohibe la red por diseno).
El centinela anadio en la revision el docstring, la proteccion contra None en
_sin_html y la limpieza del titulo de arXiv (el XML lo parte en varias lineas).

    from cognia.busqueda_web import buscar
    for r in buscar("python asyncio", 3):
        print(r["titulo"], r["url"])
"""

from __future__ import annotations

import html
import json
import logging
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)

# Wikipedia rechaza con 403 el User-Agent por defecto de urllib
# ("Python-urllib/3.12"): exige uno identificable. HackerNews y arXiv no lo
# piden, por eso el fallo solo se veia en una de las tres fuentes.
USER_AGENT = "Cognia/1.0 (+local research)"
TIMEOUT = 10


def _pedir(url: str):
    """Peticion GET con el User-Agent propio. Uso interno."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    return urllib.request.urlopen(req, timeout=TIMEOUT)


def _sin_html(texto: str | None) -> str:
    """
    Texto plano a partir de un fragmento con marcado.

    Los snippets de Wikipedia vienen con <span class="searchmatch"> dentro y
    los resumenes de arXiv con saltos de linea del XML. Acepta None porque
    ElementTree devuelve None en un nodo vacio, y reventar aqui tumbaria la
    fuente entera por un solo resultado mal formado.
    """
    if not texto:
        return ""
    texto = re.sub(r"<[^>]+>", "", texto)
    texto = html.unescape(texto)
    return re.sub(r"\s+", " ", texto).strip()


def _buscar_wikipedia(consulta: str, max_resultados: int) -> list[dict]:
    try:
        url = ("https://es.wikipedia.org/w/api.php?action=query&list=search"
               f"&format=json&srsearch={urllib.parse.quote(consulta)}"
               f"&srlimit={max_resultados}")
        with _pedir(url) as respuesta:
            data = json.load(respuesta)
        resultados = []
        for r in data["query"]["search"]:
            titulo = r["title"]
            resultados.append({
                "titulo":    titulo,
                "url":       "https://es.wikipedia.org/wiki/"
                             + urllib.parse.quote(titulo),
                "fragmento": _sin_html(r.get("snippet")),
                "fuente":    "wikipedia",
            })
        return resultados
    except Exception as e:                    # contrato: no propagar NUNCA
        logger.warning("Fallo en Wikipedia: %s", e)
        return []


def _buscar_hackernews(consulta: str, max_resultados: int) -> list[dict]:
    try:
        url = ("https://hn.algolia.com/api/v1/search"
               f"?query={urllib.parse.quote(consulta)}"
               f"&hitsPerPage={max_resultados}")
        with _pedir(url) as respuesta:
            data = json.load(respuesta)
        resultados = []
        for hit in data["hits"]:
            # Los hits de tipo comentario traen title y url a null: saltarlos,
            # no meterlos con None y que el llamador se los coma.
            if not hit.get("title") or not hit.get("url"):
                continue
            resultados.append({
                "titulo":    hit["title"],
                "url":       hit["url"],
                "fragmento": _sin_html(hit.get("story_text")),
                "fuente":    "hackernews",
            })
        return resultados
    except Exception as e:                    # contrato: no propagar NUNCA
        logger.warning("Fallo en HackerNews: %s", e)
        return []


def _buscar_arxiv(consulta: str, max_resultados: int) -> list[dict]:
    _ATOM = {"atom": "http://www.w3.org/2005/Atom"}
    try:
        url = ("http://export.arxiv.org/api/query?search_query=all:"
               f"{urllib.parse.quote(consulta)}&max_results={max_resultados}")
        with _pedir(url) as respuesta:
            raiz = ET.fromstring(respuesta.read())
        resultados = []
        for entrada in raiz.findall(".//atom:entry", _ATOM):
            titulo = entrada.find("atom:title", _ATOM)
            enlace = entrada.find("atom:id", _ATOM)
            if titulo is None or enlace is None:
                continue
            resumen = entrada.find("atom:summary", _ATOM)
            resultados.append({
                # El XML de arXiv parte los titulos en varias lineas: sin
                # limpiar, el titulo sale con saltos y espacios de sangrado.
                "titulo":    _sin_html(titulo.text),
                "url":       (enlace.text or "").strip(),
                "fragmento": _sin_html(resumen.text if resumen is not None else ""),
                "fuente":    "arxiv",
            })
        return resultados
    except Exception as e:                    # contrato: no propagar NUNCA
        logger.warning("Fallo en arXiv: %s", e)
        return []


# Dict y no tupla para poder pedir un subconjunto por nombre. El orden de
# insercion es el orden de consulta.
FUENTES = {
    "wikipedia":  _buscar_wikipedia,
    "hackernews": _buscar_hackernews,
    "arxiv":      _buscar_arxiv,
}


def buscar(consulta: str, max_resultados: int = 5,
           fuentes: "tuple[str, ...] | None" = None) -> list[dict]:
    """
    Consulta TODAS las fuentes y mezcla los resultados.

    Cada dict trae: titulo, url, fragmento, fuente. Devuelve [] si todas las
    fuentes fallan o ninguna encuentra nada — el llamador distingue los dos
    casos por los warnings del log, no por el valor de retorno.

    POR QUE NO ES UNA CASCADA: lo fue, y estaba mal. Con "la primera fuente que
    devuelva algo gana", Wikipedia se lo quedaba todo: siempre devuelve algo
    porque casa de forma laxa, asi que HackerNews y arXiv no se consultaban
    NUNCA. Medido: buscar("rust ownership model") devolvia el articulo de
    Ethereum, y las dos fuentes que si sabian de eso ni se llegaban a llamar.
    Es la misma degradacion silenciosa de siempre — una fuente mediocre que
    responde a todo tapa a las buenas, y por arriba parece que funciona.

    Se reparte el cupo entre las fuentes que respondan, en vez de dejar que una
    monopolice. Se deduplica por url porque las fuentes se solapan.

    `fuentes` limita la busqueda a un subconjunto, por nombre. Lo usa el
    research_engine, que ya tiene su propio ArxivScraper (con abstract, ano y
    categorias) y solo quiere de aqui lo que no cubre: wikipedia y hackernews.
    Un nombre desconocido se ignora con un warning en vez de reventar.
    """
    if fuentes is None:
        elegidas = list(FUENTES.values())
    else:
        elegidas = []
        for nombre in fuentes:
            if nombre not in FUENTES:
                logger.warning("Fuente desconocida, la ignoro: %s", nombre)
                continue
            elegidas.append(FUENTES[nombre])
    if not elegidas:
        return []

    por_fuente = max(1, max_resultados // len(elegidas) + 1)

    mezcla: list[dict] = []
    vistas: set[str] = set()
    for fuente in elegidas:
        for r in fuente(consulta, por_fuente):
            if r["url"] in vistas:
                continue
            vistas.add(r["url"])
            mezcla.append(r)

    return mezcla[:max_resultados]
