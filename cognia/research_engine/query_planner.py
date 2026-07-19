"""
query_planner.py — Descompone una pregunta en varias queries de busqueda.

El scraper original recibia la query ya escrita a mano. Eso significa que
Cognia no investigaba una PREGUNTA, ejecutaba una BUSQUEDA que alguien mas
habia pensado. Este modulo cierra ese hueco: entra una pregunta en lenguaje
natural, salen varias queries que cubren distintas facetas.

Funciona sin LLM (descomposicion deterministica por terminos y facetas). Si
Ollama esta levantado, le pide que mejore las queries y usa las suyas cuando
devuelve algo usable. Que el camino deterministico sea el de base y no el
fallback es a proposito: la investigacion no se cae porque Ollama este apagado.

Sin dependencias externas: solo stdlib.
"""

import json
import urllib.request as _req
from typing import List

from .relevance import tokenizar

OLLAMA_URL   = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3.2"
TIMEOUT_SEC  = 20

# GitHub y HuggingFace estan en ingles: buscar 'modelo pequeno contexto' no
# devuelve nada util. Se traducen los terminos de dominio mas comunes.
GLOSARIO = {
    "modelo": "model", "modelos": "models",
    "pequeno": "small", "pequeño": "small", "pequenos": "small", "pequeños": "small",
    "grande": "large", "grandes": "large",
    "contexto": "context", "ventana": "window",
    "memoria": "memory", "atencion": "attention", "atención": "attention",
    "lenguaje": "language", "inferencia": "inference",
    "cuantizacion": "quantization", "cuantización": "quantization",
    "compresion": "compression", "compresión": "compression",
    "entrenamiento": "training", "aprendizaje": "learning",
    "rendimiento": "performance", "velocidad": "speed",
    "peso": "weight", "pesos": "weights", "tamano": "size", "tamaño": "size",
    "largo": "long", "maximo": "maximum", "máximo": "maximum",
    "eficiente": "efficient", "eficiencia": "efficiency",
    "red": "network", "neuronal": "neural", "capa": "layer", "capas": "layers",
    "datos": "data", "conjunto": "dataset",
    "computador": "computer", "computadora": "computer", "maquina": "machine",
    "calidad": "quality",
}

# Vocabulario tecnico, separado en sustantivos (la COSA que se busca) y
# modificadores (como es esa cosa). La distincion importa: una query util
# necesita al menos un sustantivo, y un modificador solo no busca nada.
# 'maximum context' sin 'model' encuentra papers; 'small model' sin 'context'
# encuentra modelos. Hay que llevar de los dos.
NUCLEOS_EN = {
    "model", "models", "context", "window", "memory", "attention", "language",
    "inference", "quantization", "compression", "training", "learning",
    "network", "neural", "layer", "layers", "transformer", "embedding",
    "token", "tokens", "cache", "kv", "dataset", "benchmark", "cpu", "gpu",
    "performance", "speed", "size", "weight", "weights",
}

MODIFICADORES_EN = {
    "small", "large", "tiny", "long", "short", "maximum", "minimum",
    "efficient", "efficiency", "quality", "fast", "cheap", "local",
}

DOMINIO_EN = NUCLEOS_EN | MODIFICADORES_EN

# Cuantos sustantivos y cuantos modificadores lleva el nucleo de la query.
NUCLEO_SUSTANTIVOS  = 2
NUCLEO_MODIFICADORES = 1

# Facetas con las que se recorre un tema: cada una encuentra repos distintos.
FACETAS = [
    "benchmark evaluation",
    "implementation",
    "efficient inference",
    "survey awesome",
    "quantization",
]

# Cuantos terminos usar como nucleo. Mas de 3 y las APIs, que hacen AND de
# todo, empiezan a devolver 0 resultados.
NUCLEO_MAX = 3


def _traducir(terminos: List[str]) -> List[str]:
    """Pasa al ingles los terminos del glosario, deja el resto igual."""
    salida = []
    for t in terminos:
        traducido = GLOSARIO.get(t, t)
        if traducido not in salida:
            salida.append(traducido)
    return salida


def _nucleo(terminos: List[str]) -> List[str]:
    """
    Los terminos mas informativos, en el orden en que venian.

    'Informativo' NO es 'largo': con la pregunta real del dueño, ordenar por
    longitud se quedaba con 'maximum context posible' — colaba un relleno en
    espanol sin traducir y tiraba 'model', que es el sustantivo central.

    Ordenar solo por orden de aparicion tampoco basta: se quedaba con
    'model small maximum' y perdia 'context'. Lo que hace falta es llevar de
    los dos tipos — sustantivos (que se busca) y modificadores (como es) —
    tomando los primeros de cada uno, que en ambos idiomas suelen ser los
    centrales de la pregunta.
    """
    sustantivos   = [t for t in terminos if t in NUCLEOS_EN][:NUCLEO_SUSTANTIVOS]
    modificadores = [t for t in terminos if t in MODIFICADORES_EN][:NUCLEO_MODIFICADORES]
    elegidos = set(sustantivos + modificadores)

    # Si la pregunta no usa vocabulario conocido, caer a los terminos mas
    # largos para no devolver una query vacia.
    if not elegidos:
        elegidos = set(sorted(terminos, key=len, reverse=True)[:NUCLEO_MAX])

    return [t for t in terminos if t in elegidos]


def terminos_de_busqueda(pregunta: str) -> List[str]:
    """
    Terminos de la pregunta traducidos al ingles, para PUNTUAR resultados.

    Existe porque puntuar una pregunta en espanol contra resultados en ingles
    da cobertura cero en todo, y entonces el desempate por popularidad pasa a
    ser el unico criterio. Medido: con la pregunta del dueño en espanol, el
    resultado mejor puntuado de GitHub era 'china-dictatorship' (3106
    estrellas), que no tiene nada que ver.
    """
    return _traducir(tokenizar(pregunta))


def planificar_deterministico(pregunta: str, n: int = 5) -> List[str]:
    """
    Descompone la pregunta sin usar LLM.

    'modelo pequeno que maneje el maximo contexto posible'
        -> ['small maximum context', 'small maximum benchmark evaluation',
            'small maximum implementation', ...]
    """
    terminos = _traducir(tokenizar(pregunta))
    if not terminos:
        return []

    nucleo  = _nucleo(terminos)
    queries = [" ".join(nucleo)]

    # Para las facetas se usan menos terminos del nucleo: la faceta ya aporta
    # dos palabras y el AND de la API no perdona.
    base = " ".join(nucleo[:2])
    for faceta in FACETAS:
        if len(queries) >= n:
            break
        queries.append(f"{base} {faceta}")

    return queries[:n]


def _pedir_a_ollama(pregunta: str, n: int) -> List[str]:
    """Le pide queries a Ollama. Devuelve [] si no esta o si responde basura."""
    prompt = (
        f"Break this research question into {n} distinct English search queries "
        f"for GitHub and HuggingFace.\n\n"
        f"Question: {pregunta}\n\n"
        f"Rules:\n"
        f"- Each query must be 2 to 4 words. Longer queries return zero results.\n"
        f"- Each query must cover a DIFFERENT facet of the question.\n"
        f"- Use the technical English terms practitioners actually use.\n"
        f"- Output ONLY the queries, one per line, no numbering, no extra text.\n"
    )
    try:
        payload = json.dumps({
            "model":  OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": 200},
        }).encode("utf-8")

        req = _req.Request(
            OLLAMA_URL, data=payload,
            headers={"Content-Type": "application/json"},
        )
        with _req.urlopen(req, timeout=TIMEOUT_SEC) as resp:
            texto = json.loads(resp.read()).get("response", "")
    except Exception as exc:
        print(f"[planner] Ollama no disponible ({exc}). Usando plan deterministico.")
        return []

    queries = []
    for linea in texto.splitlines():
        limpia = linea.strip().lstrip("-*0123456789. ").strip().strip('"')
        # Descartar lineas que claramente no son queries.
        if 2 <= len(limpia.split()) <= 6 and not limpia.endswith(":"):
            queries.append(limpia)
    return queries[:n]


def planificar_busquedas(pregunta: str, n: int = 5, usar_llm: bool = True) -> List[str]:
    """
    Convierte una pregunta en n queries de busqueda.

    Args:
        pregunta: la pregunta en lenguaje natural (espanol o ingles)
        n:        cuantas queries generar
        usar_llm: si intentar mejorarlas con Ollama

    Returns:
        Lista de queries. Nunca vacia si la pregunta tiene alguna palabra util.
    """
    plan = planificar_deterministico(pregunta, n)

    if usar_llm:
        del_llm = _pedir_a_ollama(pregunta, n)
        if del_llm:
            print(f"[planner] Ollama propuso {len(del_llm)} queries.")
            # Se mezclan: primero las del LLM, y se completan con las
            # deterministicas que no esten repetidas.
            vistas = {q.lower() for q in del_llm}
            plan = del_llm + [q for q in plan if q.lower() not in vistas]

    return plan[:n]
