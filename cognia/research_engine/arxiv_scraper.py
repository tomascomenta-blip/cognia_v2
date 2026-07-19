"""
arxiv_scraper.py — Scraper de arXiv para investigacion de Cognia.

Tercer hermano de github_scraper y hf_scraper. GitHub tiene el codigo,
HuggingFace tiene los modelos, arXiv tiene la evidencia: los benchmarks, las
mediciones y las limitaciones. En la comparacion del 2026-07-19 casi todo lo
que decidio la respuesta (NoLiMa, HELMET, RULER, los papers de arquitectura)
salio de aqui y era invisible para las otras dos fuentes.

Devuelve Atom XML, que se parsea con xml.etree de la stdlib. Sin API key.

CORTESIA OBLIGATORIA: arXiv pide 3 segundos entre peticiones. Es lento a
proposito. No bajar _REQUEST_DELAY: es la condicion para poder usar la API
sin key ni registro.
"""

import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import List

from .relevance import degradar_query, filtrar_y_ordenar, tokenizar

ARXIV_API          = "https://export.arxiv.org/api/query"
DEFAULT_MAX_PAPERS = 5
ABSTRACT_MAX_CHARS = 1500
REQUEST_TIMEOUT    = 30
# arXiv pide 3 segundos entre peticiones. Ver nota de cabecera.
_REQUEST_DELAY     = 3.0

_ATOM  = "{http://www.w3.org/2005/Atom}"
_ARXIV = "{http://arxiv.org/schemas/atom}"

# Cuantos candidatos pedir antes de filtrar por relevancia.
_FACTOR_SOBREMUESTREO = 3

# Categorias de ML. arXiv es la unica de las tres fuentes que NO esta acotada
# al dominio: GitHub y HuggingFace son de facto sitios de software y modelos,
# pero arXiv cubre toda la ciencia. Medido: la query 'model small window' sin
# filtro devolvia 'Locality of the windowed local density of states' (math-ph)
# y 'Narrow escape to small windows on a small ball modeling the viral entry
# into the cell nucleus' (q-bio) — coinciden las palabras y no el tema.
# No es ruido a filtrar despues, es una busqueda mal planteada.
CATEGORIAS_ML = ["cs.CL", "cs.LG", "cs.AI", "cs.NE", "stat.ML"]


@dataclass
class PaperContent:
    arxiv_id:   str
    titulo:     str
    url:        str
    abstract:   str
    autores:    List[str] = field(default_factory=list)
    publicado:  str       = ""
    actualizado: str      = ""
    categorias: List[str] = field(default_factory=list)
    comentario: str       = ""

    def anio(self) -> str:
        return self.publicado[:4] if self.publicado else ""

    def to_learning_text(self) -> str:
        partes = [f"Paper arXiv: {self.titulo}"]
        if self.autores:
            firma = ", ".join(self.autores[:4])
            if len(self.autores) > 4:
                firma += " et al."
            partes.append(f"Autores: {firma}")
        if self.publicado:
            partes.append(f"Publicado: {self.publicado[:10]}")
        if self.categorias:
            partes.append(f"Categorias: {', '.join(self.categorias[:5])}")
        if self.comentario:
            partes.append(f"Nota de los autores: {self.comentario}")
        partes.append(f"URL: {self.url}")
        if self.abstract:
            partes.append(f"Abstract:\n{self.abstract}")
        return "\n\n".join(partes)

    def label(self) -> str:
        """Etiqueta compacta para episodic.store()."""
        corto = self.titulo[:60].strip()
        anio  = self.anio()
        return f"{corto} ({anio})" if anio else corto


def _texto(nodo, etiqueta: str) -> str:
    """Texto de un hijo, normalizando los saltos de linea que mete arXiv."""
    hijo = nodo.find(etiqueta)
    if hijo is None or not hijo.text:
        return ""
    return " ".join(hijo.text.split())


def parsear_feed(xml_crudo: str, max_papers: int = DEFAULT_MAX_PAPERS) -> List[PaperContent]:
    """
    Parsea el Atom XML de arXiv a PaperContent.

    Separado de la llamada HTTP a proposito: asi los tests pueden fijar el
    parseo contra XML real guardado, sin red.
    """
    try:
        raiz = ET.fromstring(xml_crudo)
    except ET.ParseError as exc:
        print(f"[arxiv] XML ilegible: {exc}")
        return []

    papers = []
    for entrada in raiz.findall(f"{_ATOM}entry")[:max_papers]:
        id_url = _texto(entrada, f"{_ATOM}id")
        # id_url es 'http://arxiv.org/abs/2502.14856v1'
        arxiv_id = id_url.rsplit("/", 1)[-1] if id_url else ""

        abstract = _texto(entrada, f"{_ATOM}summary")[:ABSTRACT_MAX_CHARS]

        autores = []
        for autor in entrada.findall(f"{_ATOM}author"):
            nombre = _texto(autor, f"{_ATOM}name")
            if nombre:
                autores.append(nombre)

        categorias = [
            c.attrib.get("term", "")
            for c in entrada.findall(f"{_ATOM}category")
            if c.attrib.get("term")
        ]

        papers.append(PaperContent(
            arxiv_id    = arxiv_id,
            titulo      = _texto(entrada, f"{_ATOM}title"),
            url         = id_url.replace("http://", "https://"),
            abstract    = abstract,
            autores     = autores,
            publicado   = _texto(entrada, f"{_ATOM}published"),
            actualizado = _texto(entrada, f"{_ATOM}updated"),
            categorias  = categorias,
            comentario  = _texto(entrada, f"{_ARXIV}comment"),
        ))

    return papers


class ArxivScraper:
    """Scraper de arXiv sin dependencias externas ni API key."""

    def __init__(self, max_papers: int = DEFAULT_MAX_PAPERS, categorias: List[str] = None):
        """
        Args:
            max_papers: cuantos papers devolver como maximo
            categorias: categorias de arXiv a las que acotar. Por defecto las
                de ML, porque es el dominio de Cognia. Pasar [] para buscar
                en toda la ciencia (util para preguntas de otro campo).
        """
        self.max_papers = max(1, min(max_papers, 20))
        self.categorias = CATEGORIAS_ML if categorias is None else categorias
        self._ultima_peticion = 0.0

    # ── HTTP helpers ────────────────────────────────────────────────────

    def _esperar_turno(self) -> None:
        """Garantiza los 3 segundos entre peticiones que pide arXiv."""
        desde = time.time() - self._ultima_peticion
        if self._ultima_peticion and desde < _REQUEST_DELAY:
            time.sleep(_REQUEST_DELAY - desde)
        self._ultima_peticion = time.time()

    def _get(self, url: str) -> str:
        self._esperar_turno()
        req = urllib.request.Request(url, headers={"User-Agent": "CogniaResearch/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            print(f"[arxiv] HTTP {e.code}")
            return ""
        except Exception as exc:
            print(f"[arxiv] Error de conexion: {exc}")
            return ""

    # ── API calls ───────────────────────────────────────────────────────

    def _construir_search_query(self, query: str) -> str:
        """
        Traduce una query de palabras al lenguaje de busqueda de arXiv.

        A diferencia de GitHub y HuggingFace, arXiv SI entiende booleanos, asi
        que se puede pedir el AND explicitamente en vez de rezar. Cada termino
        se busca en todos los campos, y todo se acota por categoria:

            (all:small AND all:context) AND (cat:cs.CL OR cat:cs.LG)

        El parentesis de categorias no es opcional en la practica: sin el,
        arXiv devuelve fisica y biologia que coinciden por palabra suelta.
        """
        terminos = tokenizar(query)
        if not terminos:
            return ""

        base = " AND ".join(f"all:{t}" for t in terminos)
        if not self.categorias:
            return base

        cats = " OR ".join(f"cat:{c}" for c in self.categorias)
        return f"({base}) AND ({cats})"

    def _buscar_crudo(self, query: str) -> List[PaperContent]:
        """Una sola llamada a la API. Devuelve los papers ya parseados."""
        search = self._construir_search_query(query)
        if not search:
            return []

        params = urllib.parse.urlencode({
            "search_query": search,
            "start":        0,
            "max_results":  self.max_papers * _FACTOR_SOBREMUESTREO,
            "sortBy":       "relevance",
            "sortOrder":    "descending",
        })
        crudo = self._get(f"{ARXIV_API}?{params}")
        if not crudo:
            return []
        return parsear_feed(crudo, max_papers=self.max_papers * _FACTOR_SOBREMUESTREO)

    def search_papers(self, query: str) -> List[PaperContent]:
        """
        Busca papers por query, filtra por relevancia y devuelve los mejores.

        Misma degradacion que los otros dos scrapers: si el AND de todos los
        terminos no devuelve nada, se reintenta con menos terminos.
        """
        print(f"[arxiv] Buscando: '{query}' (max {self.max_papers} papers)...")
        papers     = self._buscar_crudo(query)
        query_real = query

        if not papers:
            for reducida in degradar_query(query):
                print(f"[arxiv] 0 resultados. Reintentando con: '{reducida}'")
                papers = self._buscar_crudo(reducida)
                if papers:
                    query_real = reducida
                    break

        if not papers:
            print(f"[arxiv] Sin resultados para '{query}' ni sus reducciones.")
            return []

        relevantes = filtrar_y_ordenar(
            papers, query_real,
            texto_de = lambda p: f"{p.titulo} {p.abstract}",
            # arXiv no tiene estrellas ni descargas: la relevancia es lo unico
            # que ordena, mas el orden que ya devuelve la propia API.
            popularidad_de = lambda p: 0,
        )
        print(f"[arxiv] {len(papers)} candidatos, {len(relevantes)} relevantes. "
              f"Procesando {min(self.max_papers, len(relevantes))}...")

        salida = relevantes[: self.max_papers]
        for p in salida:
            print(f"[arxiv] OK  {p.arxiv_id}  {p.titulo[:60]}")
        return salida
