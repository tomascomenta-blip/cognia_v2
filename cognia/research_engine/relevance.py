"""
relevance.py — Puntuacion de relevancia y degradacion de queries.

Lo comparten github_scraper y hf_scraper. Resuelve dos fallas medidas del
scraper original:

  1. Ordenar por popularidad (estrellas/descargas) pone arriba resultados
     irrelevantes. Medido: la query 'long context small language model'
     devolvia como #1 el repo jettbrains/-L- (149 estrellas), que es un
     informe del W3C de 2019.
  2. Las APIs de busqueda hacen AND de todos los terminos, asi que una query
     de 6 palabras devuelve 0 resultados y el scraper fallaba en silencio.
     Medido: 'linear attention hybrid mamba language model' -> 0 resultados.

Sin dependencias externas: solo stdlib.
"""

import math
import re
from typing import Iterator, List

# Palabras vacias es/en. Se descartan al puntuar y al degradar queries.
STOPWORDS = {
    # ingles
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "how",
    "in", "is", "it", "of", "on", "or", "that", "the", "to", "what", "which",
    "with", "using", "use", "best", "most",
    # espanol
    "de", "la", "el", "los", "las", "un", "una", "unos", "unas", "y", "o",
    "que", "con", "para", "por", "en", "del", "al", "se", "su", "sus", "es",
    "son", "mas", "menos", "como", "cual", "cuales", "sobre", "mejor",
    # verbos y rellenos que no aportan a una busqueda tecnica
    "posible", "posibles", "puede", "pueden", "podria", "poder", "hacer",
    "tener", "manejar", "maneja", "usar", "quiero", "necesito", "actualmente",
    "can", "able", "possible", "want", "need", "currently", "handle",
}

# Cobertura minima de terminos para no descartar un resultado por ruido.
COBERTURA_MINIMA = 0.34

# Cuanto texto se mira al puntuar. Una descripcion de repo o un model card
# resumen su tema en las primeras lineas; mas alla de esto solo se acumulan
# coincidencias por azar. Ver la explicacion en cobertura().
TEXTO_MAX_PUNTUACION = 1000

PESO_RELEVANCIA = 10.0

# Divisor para normalizar la popularidad a ~[0,1]: 10^7 = 10 millones de
# estrellas o descargas es el techo practico.
_ESCALA_POPULARIDAD = 7.0

# La popularidad vale, como maximo, esta fraccion de UN termino acertado.
# Menor que 1 a proposito: ver la invariante en puntuar().
_TOPE_POPULARIDAD = 0.9


def tokenizar(texto: str) -> List[str]:
    """Palabras significativas en minuscula, sin stopwords ni palabras de 1 letra."""
    crudo = re.findall(r"[a-z0-9]+", (texto or "").lower())
    return [t for t in crudo if len(t) > 1 and t not in STOPWORDS]


def cobertura(terminos: List[str], texto: str) -> float:
    """
    Fraccion de los terminos de la query que aparecen en el texto (0.0 a 1.0).

    Solo mira los primeros TEXTO_MAX_PUNTUACION caracteres. No es una
    optimizacion: es correccion. La probabilidad de acertar un termino por
    azar crece con el largo del texto, asi que sin tope un documento enorme
    le gana a una descripcion precisa de una linea.

    Medido: la descripcion de GitHub de 'china-dictatorship' tiene 64.765
    caracteres — un documento entero metido en el campo descripcion — y
    matcheaba 5 de 10 terminos de una pregunta sobre modelos de lenguaje
    ('model', 'small', 'window', 'quality', 'cpu') sin tener nada que ver.
    Con el tope matchea lo que de verdad describe al repo.
    """
    if not terminos:
        return 1.0
    blob = (texto or "").lower()[:TEXTO_MAX_PUNTUACION]
    encontrados = sum(1 for t in terminos if t in blob)
    return encontrados / len(terminos)


def puntuar(terminos: List[str], texto: str, popularidad: int) -> float:
    """
    Puntua un resultado. La relevancia domina; la popularidad solo desempata.

    INVARIANTE: la popularidad nunca puede compensar un termino acertado de
    menos. Un peso fijo no lo garantiza — con una pregunta de 10 terminos cada
    termino vale 1.0, y log10(3106 estrellas) = 3.49 se come tres terminos.
    Medido: asi era como 'china-dictatorship' encabezaba una busqueda sobre
    modelos de lenguaje. Por eso el peso se escala con el numero de terminos.
    """
    cob       = cobertura(terminos, texto)
    valor_pop = min(1.0, math.log10(1 + max(0, popularidad)) / _ESCALA_POPULARIDAD)
    peso_pop  = (PESO_RELEVANCIA / max(1, len(terminos))) * _TOPE_POPULARIDAD
    return cob * PESO_RELEVANCIA + valor_pop * peso_pop


def degradar_query(query: str) -> Iterator[str]:
    """
    Genera versiones cada vez mas cortas de una query, para reintentar cuando
    la busqueda devuelve 0 resultados.

    Conserva los terminos mas informativos primero. Como heuristica de
    'informativo' usa la longitud de la palabra: 'mamba' y 'attention' pesan
    mas que 'model', que aparece en todo.

    'linear attention hybrid mamba language model'
        -> 'attention hybrid mamba language'   (4 terminos)
        -> 'attention mamba language'          (3)
        -> 'attention mamba'                   (2)
        -> 'attention'                         (1)
    """
    terminos = tokenizar(query)
    if len(terminos) <= 1:
        return

    # Ordenar por informatividad descendente, conservando el orden original
    # entre los que sobreviven para que la query siga leyendose natural.
    ranking = sorted(terminos, key=len, reverse=True)

    for n in range(len(terminos) - 1, 0, -1):
        conservar = set(ranking[:n])
        reducida = [t for t in terminos if t in conservar]
        yield " ".join(reducida)


def filtrar_y_ordenar(items: List[dict], query: str, texto_de, popularidad_de) -> List[dict]:
    """
    Descarta el ruido y ordena por relevancia.

    Args:
        items:         resultados crudos de la API
        query:         la query original
        texto_de:      callable item -> texto donde buscar los terminos
        popularidad_de: callable item -> int (estrellas o descargas)

    Returns:
        Los items que superan COBERTURA_MINIMA, de mas a menos relevante.
    """
    terminos = tokenizar(query)
    puntuados = []

    for item in items:
        texto = texto_de(item)
        if cobertura(terminos, texto) < COBERTURA_MINIMA:
            continue
        puntuados.append((puntuar(terminos, texto, popularidad_de(item)), item))

    puntuados.sort(key=lambda par: par[0], reverse=True)
    return [item for _, item in puntuados]
