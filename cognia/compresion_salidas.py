"""
compresion_salidas.py — Recortar texto antes de gastarlo en contexto.

POR QUE EXISTE: el llama-server local corre con n_ctx=8192. Cada traceback,
cada listado y cada digest de investigacion que se le manda al modelo se come
parte de esa ventana, y lo que no cabe se pierde en silencio.

La idea sale de la investigacion que hizo Cognia sola el 2026-07-20 sobre
agentes de coding: `headroomlabs-ai/headroom` (60k estrellas) comprime salidas
de herramientas antes de que lleguen al LLM y reporta 20% menos tokens en
codigo y 60-95% en JSON. El algoritmo de colapsar lineas repetidas con contador
y recortar el medio lo escribio la propia Cognia (`generated_programs/
text_compressor_01`, 3 tests en verde, 89% de ahorro medido sobre 100 lineas
de log). Aqui se integra al repo y se le anade lo que faltaba para el caso
real: conservar el FINAL.

Por que el final importa: el codigo del repo recortaba con `error[:600]`, que
en un traceback se queda con la cabecera y tira la ultima linea — que es
justo donde dice que fallo. Comprimir bien no es cortar, es decidir que sobra.

Sin dependencias externas: solo stdlib.
"""

from __future__ import annotations

import re
from typing import List

# Cuantas lineas se dejan antes de recortar el medio.
MAX_LINEAS_DEFECTO = 40

# Reparto del recorte. Se guarda mas del final que del principio porque en un
# traceback, un log o una salida de tests, la conclusion esta al final.
PROPORCION_FINAL = 0.6

MARCA_RECORTE = "... [{n} lineas recortadas] ..."


def _colapsar_repetidas(lineas: List[str]) -> List[str]:
    """Une lineas consecutivas identicas en una sola con contador."""
    salida: List[str] = []
    i = 0
    while i < len(lineas):
        veces = 1
        while i + 1 < len(lineas) and lineas[i] == lineas[i + 1]:
            i += 1
            veces += 1
        salida.append(lineas[i] if veces == 1 else f"{lineas[i]}   (x{veces})")
        i += 1
    return salida


def comprimir(texto: str, max_lineas: int = MAX_LINEAS_DEFECTO) -> str:
    """
    Version corta de `texto` conservando principio y, sobre todo, final.

    Dos pasadas: primero colapsa repeticiones consecutivas (un log de 200
    lineas iguales pasa a una), y si aun sobran lineas, recorta el medio.
    """
    if not texto:
        return ""

    lineas = _colapsar_repetidas(texto.splitlines())
    if len(lineas) <= max_lineas:
        return "\n".join(lineas)

    n_final   = max(1, int(max_lineas * PROPORCION_FINAL))
    n_inicio  = max(1, max_lineas - n_final)
    recortadas = len(lineas) - n_inicio - n_final

    return "\n".join(
        lineas[:n_inicio]
        + [MARCA_RECORTE.format(n=recortadas)]
        + lineas[-n_final:]
    )


def comprimir_error(texto: str, max_chars: int = 1200) -> str:
    """
    Compresion pensada para tracebacks: la ultima linea es sagrada.

    `error[:600]` se quedaba con "Traceback (most recent call last):" y las
    rutas de los frames, y tiraba el `KeyError: 'cuadrdo'` del final, que es
    lo unico que el modelo necesita para arreglarlo.
    """
    if not texto:
        return ""

    texto = comprimir(texto, max_lineas=30)
    if len(texto) <= max_chars:
        return texto

    lineas = texto.splitlines()
    # La ultima linea no vacia lleva el tipo de excepcion y el mensaje.
    ultimas = [l for l in lineas if l.strip()][-3:]
    cola = "\n".join(ultimas)

    espacio = max_chars - len(cola) - len(MARCA_RECORTE)
    cabeza  = texto[:max(0, espacio)]

    return f"{cabeza}\n{MARCA_RECORTE.format(n='?')}\n{cola}"


def ahorro(original: str, comprimido: str) -> float:
    """Fraccion de caracteres ahorrados, entre 0 y 1."""
    if not original:
        return 0.0
    return max(0.0, 1.0 - len(comprimido) / len(original))
