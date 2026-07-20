"""
cognia/colonia — la colonia de micro-expertos, viva dentro de Cognia.

Pedido del dueno (2026-07-20): el superorganismo "pero dentro de Cognia".
Los micro-expertos entrenados por scripts/entrenar_flota.py (torch, GPU) se
exportan a pesos.npz y aqui corren en numpy puro (<4 ms CPU, sin torch, la
misma puerta que los shards). La feromona registra discrepancias con las
heuristicas y refuerza por resultados; un experto solo manda cuando su rastro
lo sostiene (regla pre-registrada en planes/FLOTA_MICROEXPERTOS.md).

    from cognia.colonia import opinar
    clase, confianza = opinar("idea_router", "pagina web con graficos")
"""

from __future__ import annotations

import logging

from . import feromona  # noqa: F401  (parte de la API publica)
from .experto_numpy import ExpertoNumpy, verificar_paridad  # noqa: F401

logger = logging.getLogger(__name__)

_expertos: dict = {}


def opinar(tarea: str, texto: str) -> tuple[str, float]:
    """
    La opinion del experto de la tarea: (clase, confianza). ('', 0.0) si el
    experto no existe o falla — la colonia es una mejora, nunca una
    dependencia: sin experto, las heuristicas siguen mandando solas.
    """
    try:
        if tarea not in _expertos:
            _expertos[tarea] = ExpertoNumpy(tarea)
        return _expertos[tarea].opinar(texto)
    except Exception as e:
        logger.warning("Colonia: sin experto para %s (%s)", tarea, e)
        return "", 0.0
