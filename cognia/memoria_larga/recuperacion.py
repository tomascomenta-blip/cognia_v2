# -*- coding: utf-8 -*-
"""Recuperación tras crash: LOAD SESSION → último checkpoint → estado →
memorias relevantes → ficheros → errores → siguiente acción.

Sin horizonte ni flags: cualquier /hacer deja checkpoints (integracion.py), así
que `cognia hacer --retomar` y `/hacer retomar` funcionan siempre, y el REPL
avisa al arrancar si en este cwd hay una tarea a medias.
"""
from __future__ import annotations

import logging
import os

from cognia.memoria_larga import checkpoint as _cp

_LOG = logging.getLogger(__name__)


def tarea_pendiente(cwd: str | None = None, almacen=None) -> dict | None:
    """El checkpoint `en_curso` más reciente de este cwd (o de cualquiera si cwd=None)."""
    try:
        return _cp.ultimo(cwd=cwd or os.getcwd(), almacen=almacen, solo_abiertos=True)
    except Exception as exc:
        _LOG.warning("recuperacion: no pude buscar checkpoints (%s)", exc)
        return None


def aviso_al_arrancar(cwd: str | None = None, almacen=None) -> str:
    cp = tarea_pendiente(cwd, almacen)
    if not cp:
        return ""
    return (f"[!] Hay una tarea a medias en este directorio (checkpoint #{cp.get('n')}, paso {cp.get('paso')}): "
            f"\"{str(cp.get('tarea') or '')[:90]}\". Escribí /hacer retomar para continuarla, "
            f"o /checkpoint sellar para descartarla.")


def prompt_de_retomada(cp: dict, contexto_mgr=None) -> str:
    """El guidance para relanzar la tarea desde el checkpoint (con memorias si hay recuperador)."""
    tarea = str(cp.get("tarea") or "")
    if contexto_mgr is not None:
        try:
            return contexto_mgr.bloque_de_retomada(cp, tarea)
        except Exception as exc:
            _LOG.warning("recuperacion: bloque con memorias degradado (%s); uso solo el checkpoint", exc)
    return ("CONTINUACIÓN tras reinicio. No empieces de cero: parte de la tarea ya está hecha.\n"
            + _cp.render(cp, max_chars=1800)
            + "\n\nVerificá en disco lo que dudes y seguí desde SIGUIENTE ACCIÓN.")


def sellar(cp: dict, estado: str = "retomada", almacen=None) -> None:
    try:
        _cp.sellar(cp["task_id"], estado, almacen)
    except Exception as exc:
        _LOG.warning("recuperacion: no pude sellar %s (%s)", cp.get("task_id"), exc)


__all__ = ["tarea_pendiente", "aviso_al_arrancar", "prompt_de_retomada", "sellar"]
