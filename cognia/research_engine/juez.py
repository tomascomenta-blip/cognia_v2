"""
juez.py — El juicio de relevancia que le faltaba al motor de investigacion.

EL PROBLEMA, medido el 2026-07-20 en este mismo motor: todo el pipeline era
coincidencia lexica. La query 'rust' trajo a "Bernhard Rust" (un politico
aleman de 1940) y rusty.hpp (una libreria de C++) ranqueo por ENCIMA del
compilador real de Rust. Nada se preguntaba nunca "¿esto responde a la
pregunta?". El LLM estaba levantado durante toda la busqueda y solo se usaba
al final, para redactar el resumen: explicaba los resultados, nunca los
juzgaba. Este modulo lo pone a juzgar.

Decisiones de diseno, y su porque:

- UNA llamada al LLM para todo el lote, no una por hallazgo. Cada llamada
  cuesta segundos; una investigacion trae 40+ hallazgos.
- Solo se juzgan los primeros max_llm (ya vienen ordenados por el ranking
  lexico): el juicio refina el top, no reemplaza al ranking.
- En la duda, NO descartar. Un numero ausente de la respuesta del modelo se
  trata como SI: descartar de mas es peor que dejar ruido, porque el ranking
  lexico ya ordena y el resumidor final ve el top completo.
- Los juzgados NO se HUNDEN (relevancia x 0.1), no se borran. Borrar evidencia
  hace irrecuperable un fallo del juez; hundirla lo deja visible y reversible.
- Sin LLM, los hallazgos pasan tal cual. El juicio es una mejora, no una
  dependencia: la investigacion no se cae sin modelo.

Autoria: escrito por Cognia via G4 (generar -> revisar -> integrar). El
centinela corrigio en revision la regla de la duda (castigaba a los no
juzgados, al reves de lo pedido) y el reorden (usaba la variable muerta del
bucle anterior, evaluando los tres grupos contra un indice constante).
"""

from __future__ import annotations

import logging
from typing import List

from ..llm_local import disponible, generar

logger = logging.getLogger(__name__)

# Cuantos hallazgos del top se juzgan. 12 es lo que ve el resumidor final:
# juzgar mas es pagar latencia por hallazgos que nadie va a leer.
MAX_JUZGADOS = 12

# Factor de hundimiento para los juzgados NO. No es 0: el hallazgo sigue ahi,
# al final, por si el juez se equivoco.
HUNDIMIENTO = 0.1


def _parsear_veredictos(texto: str) -> dict[int, bool]:
    """
    Extrae {numero: es_relevante} de la respuesta del modelo.

    Tolerante a proposito: acepta "1: SI", "1. YES", "1 - no", con cualquier
    caja y espaciado. Una linea que no siga el patron se ignora sin drama —
    la regla de la duda del llamador cubre los numeros que falten.
    """
    veredictos: dict[int, bool] = {}
    for linea in texto.splitlines():
        limpia = linea.strip().replace(".", ":").replace("-", ":")
        cabeza, _, cola = limpia.partition(":")
        if not cabeza.strip().isdigit():
            continue
        decision = cola.strip().upper()
        if decision.startswith(("SI", "YES")):
            veredictos[int(cabeza)] = True
        elif decision.startswith("NO"):
            veredictos[int(cabeza)] = False
    return veredictos


def juzgar(pregunta: str, hallazgos: List, max_llm: int = MAX_JUZGADOS) -> List:
    """
    Reordena los hallazgos segun si RESPONDEN a la pregunta, no si casan.

    Devuelve la lista completa: primero los juzgados SI (por su relevancia
    original), luego los no juzgados, al final los NO con la relevancia
    hundida. Nunca lanza; sin LLM o con respuesta imparseable devuelve la
    lista tal cual.
    """
    if not hallazgos or not disponible():
        return hallazgos

    lote = hallazgos[:max_llm]
    entrada = "\n".join(
        f"{i + 1}. [{h.fuente}] {h.titulo[:80]} :: {h.resumen[:200]}"
        for i, h in enumerate(lote)
    )
    prompt = (
        f"Question: {pregunta}\n\n"
        f"Search results:\n{entrada}\n\n"
        f"For EACH numbered result, answer whether it helps answer the "
        f"question. SI = it contributes to answering THIS question. "
        f"NO = it is about something else, even if it shares words with the "
        f"question.\n"
        f"Answer with EXACTLY one line per number, no other text:\n"
        f"1: SI\n2: NO\n..."
    )

    respuesta = generar(prompt, temperature=0.1, max_tokens=200)
    if not respuesta:
        logger.warning("Juez: el LLM no respondio; hallazgos sin juzgar.")
        return hallazgos

    veredictos = _parsear_veredictos(respuesta)
    if not veredictos:
        logger.warning("Juez: respuesta imparseable, me la salto: %r",
                       respuesta[:120])
        return hallazgos

    # La regla de la duda: solo el NO explicito hunde. Un numero ausente es un
    # SI implicito — el modelo puede cortar la lista y eso no es culpa del
    # hallazgo.
    si, sin_juicio, no = [], [], []
    for i, h in enumerate(lote):
        veredicto = veredictos.get(i + 1)
        if veredicto is False:
            h.relevancia *= HUNDIMIENTO
            no.append(h)
        elif veredicto is True:
            si.append(h)
        else:
            sin_juicio.append(h)

    if no:
        logger.info("Juez: hundidos %d de %d por no responder a la pregunta.",
                    len(no), len(lote))

    return si + sin_juicio + hallazgos[max_llm:] + no
