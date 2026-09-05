# -*- coding: utf-8 -*-
"""Deduplicación ANTES de guardar: la misma cosa dicha tres veces es UNA memoria.

Tres puertas, de la más barata a la más cara:
  1. mismo `hash` (contenido normalizado) vigente en la misma tarea;
  2. mismo `tipo` + `entidad` + `valor` vigente (la decisión repetida con otras palabras);
  3. candidatos por FTS (top 5 con el resumen) y Jaccard de tokens ≥ 0.8; si el
     llamador pasa `vector` y el candidato tiene el suyo en `vectores`, además coseno
     ≥ `umbral_cos`. No hay embeddings aquí: quien los tiene es retrieval.
`fusionar` NO inserta la nueva: une referencias/tags/entidades en la existente,
sube la confianza 0,1 y toma la importancia máxima. El llamador descarta la nueva.
"""
from __future__ import annotations

import logging
import math
import re
import time

from . import Memoria
from .extraccion import normalizar, normalizar_valor, hash_contenido

logger = logging.getLogger(__name__)

UMBRAL_JACCARD = 0.8


def _tokens(texto: str) -> set[str]:
    return set(re.findall(r"\w+", normalizar(texto)))


def jaccard(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def coseno(a, b) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    num = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return num / (na * nb) if na and nb else 0.0


def es_duplicada(almacen, memoria: Memoria, umbral_cos: float = 0.92, vector=None) -> Memoria | None:
    """Devuelve la memoria vigente que ya dice lo mismo, o None."""
    try:
        h = memoria.hash or hash_contenido(memoria.contenido)
        # 1. hash exacto en la misma tarea (task_id vacío = sin filtro de tarea)
        for m in almacen.por_hash(h, task_id=memoria.task_id or None):
            if m.id != memoria.id:
                return m
        # 2. misma tripleta tipo+entidad+valor vigente
        if memoria.entidad and memoria.valor:
            v = normalizar(normalizar_valor(memoria.valor))
            for m in almacen.por_entidad(memoria.entidad, task_id=memoria.task_id or None, solo_vigentes=True):
                if m.id != memoria.id and m.tipo == memoria.tipo and normalizar(normalizar_valor(m.valor)) == v:
                    return m
        # 3. parecido léxico (y vectorial si hay con qué)
        consulta = memoria.resumen or memoria.contenido[:200]
        candidatos = almacen.buscar_lexico(consulta, task_id=memoria.task_id or None, tipos=[memoria.tipo],
                                           limite=5, solo_vigentes=True)
        for m, _score in candidatos:
            if m.id == memoria.id:
                continue
            if jaccard(m.contenido, memoria.contenido) >= UMBRAL_JACCARD:
                return m
            if vector is not None:
                vm = almacen.vector(m.id)
                if vm is not None and coseno(vector, vm) >= umbral_cos:
                    return m
        return None
    except Exception as e:  # noqa: BLE001 — un fallo aquí no debe impedir guardar; se avisa
        logger.warning("memoria_larga.dedup.es_duplicada falló (%s); trato la memoria como nueva", e)
        return None


def _union(a, b) -> list:
    return list(dict.fromkeys(list(a or []) + list(b or [])))


def fusionar(almacen, existente: Memoria, nueva: Memoria) -> Memoria:
    """Une la nueva en la existente y la devuelve actualizada. La nueva no se inserta."""
    campos = {
        "referencias": _union(existente.referencias, nueva.referencias),
        "tags": _union(existente.tags, nueva.tags),
        "entidades": _union(existente.entidades, nueva.entidades),
        "confianza": min(1.0, float(existente.confianza) + 0.1),
        "importancia": max(int(existente.importancia), int(nueva.importancia)),
        "timestamp": time.time(),
    }
    # Si la existente no tenía entidad/valor y la nueva sí, se completan (misma cosa mejor tipada).
    if not existente.entidad and nueva.entidad:
        campos["entidad"] = nueva.entidad
    if not existente.valor and nueva.valor:
        campos["valor"] = nueva.valor
    if not almacen.actualizar(existente.id, **campos):
        logger.warning("memoria_larga.dedup.fusionar: la memoria %s no existe ya; devuelvo la existente sin cambios", existente.id)
        return existente
    actual = almacen.obtener(existente.id)
    return actual if actual is not None else existente


__all__ = ["es_duplicada", "fusionar", "jaccard", "coseno", "UMBRAL_JACCARD"]
