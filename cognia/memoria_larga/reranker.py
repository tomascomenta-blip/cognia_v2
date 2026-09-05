# -*- coding: utf-8 -*-
"""reranker.py — funciones puras de puntuación para memoria_larga.

Separadas del Recuperador para que `scripts/memoria_larga/banco.py` pueda
optimizar los pesos sin tocar el algoritmo de candidatos:

    puntuar(senales, pesos)      -> float   (Σ pesos[k]·senales[k])
    normalizar_pesos(pesos)      -> dict    (rellena con PESOS_DEFECTO, ignora desconocidas avisando)
    cargar_pesos(ruta=None)      -> dict    (~/.cognia/memoria_larga_pesos.json; roto → defecto avisando)
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from . import PESOS_DEFECTO

_log = logging.getLogger(__name__)

SENALES = tuple(PESOS_DEFECTO.keys())
RUTA_PESOS = Path.home() / ".cognia" / "memoria_larga_pesos.json"


def normalizar_pesos(pesos: dict | None) -> dict:
    """Devuelve un dict con TODAS las claves de PESOS_DEFECTO.

    Las que falten toman el defecto; las desconocidas se descartan con aviso;
    los valores no numéricos también (aviso) para que un JSON a medias no
    reviente el retrieval."""
    base = dict(PESOS_DEFECTO)
    if not pesos:
        return base
    if not isinstance(pesos, dict):
        _log.warning("memoria_larga.reranker: pesos no es dict (%s); uso PESOS_DEFECTO",
                     type(pesos).__name__)
        return base
    for k, v in pesos.items():
        if k not in base:
            _log.warning("memoria_larga.reranker: peso desconocido %r ignorado", k)
            continue
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            _log.warning("memoria_larga.reranker: peso %r=%r no numérico; uso defecto %s",
                         k, v, base[k])
            continue
        base[k] = float(v)
    return base


def puntuar(senales: dict, pesos: dict) -> float:
    """score = Σ pesos[k]·senales[k] sobre las claves de `pesos` (señal ausente = 0)."""
    total = 0.0
    for k, w in pesos.items():
        s = senales.get(k, 0.0)
        try:
            total += float(w) * float(s)
        except (TypeError, ValueError):
            _log.warning("memoria_larga.reranker: señal %r=%r no numérica; la cuento como 0", k, s)
    return total


def cargar_pesos(ruta: str | os.PathLike | None = None) -> dict:
    """Pesos desde JSON si existe; si no existe → defecto en silencio; si está
    roto o no es un objeto → defecto AVISANDO (kill-switch: borrar el fichero)."""
    p = Path(ruta) if ruta else RUTA_PESOS
    if not p.exists():
        return dict(PESOS_DEFECTO)
    try:
        datos = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        _log.warning("memoria_larga.reranker: %s ilegible (%s); uso PESOS_DEFECTO", p, e)
        return dict(PESOS_DEFECTO)
    if not isinstance(datos, dict):
        _log.warning("memoria_larga.reranker: %s no contiene un objeto JSON; uso PESOS_DEFECTO", p)
        return dict(PESOS_DEFECTO)
    return normalizar_pesos(datos)


__all__ = ["puntuar", "normalizar_pesos", "cargar_pesos", "SENALES", "RUTA_PESOS"]
