# -*- coding: utf-8 -*-
"""Contradicciones con historial: "la base de datos es SQLite" y luego "es PostgreSQL".

No se borra nada: la vieja pasa a 'superada' (con `valid_until`) y la nueva la
apunta por `supersedes`, así `historial` puede contar A → B → C y retrieval puede
penalizar la superada sin perderla. Solo aplica a tipos con clave canónica
(`decision`, `hecho`, `restriccion`) y solo si la memoria trae `entidad` y `valor`.
"""
from __future__ import annotations

import logging

from . import Memoria
from .extraccion import normalizar, normalizar_valor

logger = logging.getLogger(__name__)

TIPOS_CON_CLAVE = ("decision", "hecho", "restriccion")


def _valor_norm(v: str) -> str:
    return normalizar(normalizar_valor(v))


def detectar(almacen, memoria: Memoria) -> Memoria | None:
    """La vigente más reciente con la misma entidad y tipo pero OTRO valor, o None."""
    if memoria.tipo not in TIPOS_CON_CLAVE or not memoria.entidad or not memoria.valor:
        return None
    try:
        v = _valor_norm(memoria.valor)
        candidatas = [m for m in almacen.por_entidad(memoria.entidad, task_id=memoria.task_id or None, solo_vigentes=True)
                      if m.id != memoria.id and m.tipo == memoria.tipo and _valor_norm(m.valor) != v]
        if not candidatas:
            return None
        return max(candidatas, key=lambda m: (m.timestamp, m.id or 0))
    except Exception as e:  # noqa: BLE001 — se avisa; sin detección la memoria igual se guarda
        logger.warning("memoria_larga.contradicciones.detectar falló (%s)", e)
        return None


def resolver(almacen, vieja: Memoria, nueva: Memoria) -> None:
    """La vieja queda superada por la nueva (ambas deben estar ya guardadas)."""
    if vieja.id is None or nueva.id is None:
        logger.warning("memoria_larga.contradicciones.resolver: ids faltantes (vieja=%s, nueva=%s); no hago nada",
                       vieja.id, nueva.id)
        return
    almacen.superar(vieja.id, nueva.id)
    vieja.estado, vieja.superseded_by = "superada", nueva.id
    nueva.supersedes = vieja.id


def historial(almacen, entidad: str, task_id: str | None = None) -> list[Memoria]:
    """Cadena `supersedes` de la más vieja a la vigente, para la entidad dada.

    Arranca en la vigente (o la más reciente si ninguna lo es) y camina hacia
    atrás por `supersedes`; si alguna del medio fue borrada, la cadena se corta
    ahí y se avisa.
    """
    todas = almacen.por_entidad(entidad, task_id=task_id)
    if not todas:
        return []
    por_id = {m.id: m for m in todas}
    vigentes = [m for m in todas if m.estado == "vigente"]
    cabeza = max(vigentes or todas, key=lambda m: (m.timestamp, m.id or 0))
    cadena = [cabeza]
    vistos = {cabeza.id}
    actual = cabeza
    while actual.supersedes is not None and actual.supersedes not in vistos:
        anterior = por_id.get(actual.supersedes) or almacen.obtener(actual.supersedes)
        if anterior is None:
            logger.warning("memoria_larga.historial(%r): la memoria %s ya no existe; cadena cortada",
                           entidad, actual.supersedes)
            break
        cadena.append(anterior)
        vistos.add(anterior.id)
        actual = anterior
    cadena.reverse()
    return cadena


__all__ = ["detectar", "resolver", "historial", "TIPOS_CON_CLAVE"]
