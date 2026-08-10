# -*- coding: utf-8 -*-
"""
cognia/agent/traza_chatml.py
============================
Captura de trazas chatml COMPLETAS del bucle nativo, para fine-tuning.

POR QUE EXISTE: la lista viva ``mensajes`` de ``bucle_nativo`` (loop.py) es la
UNICA fuente fiel de la conversacion (system/user/assistant con tool_calls y
``arguments`` crudos del server, turnos tool, avisos de estancamiento) y hoy no
se persiste en ningun lado. El bus de eventos y la bitacora NO sirven para esto:
``ToolInicio`` emite args[:120] y el trace [:200] — tool calls mutilados que
entrenarian un formato truncado. Este modulo vuelca la lista viva tal cual.

POR QUE ESTE DIRECTORIO: las trazas van a ``~/.cognia/data/trazas/`` — FUERA de
``~/.cognia/data/tareas/`` a proposito, porque ``estado_tarea.podar_viejas()``
retiene solo 20 tareas y se comeria el dataset. Aqui NO hay poda automatica.

ADVERTENCIAS (documentadas, no re-descubrir):
1. ``_recortar_mensajes`` (loop.py) muta los ``tool.content`` viejos cuando el
   contexto presiona: la traza refleja lo que el modelo vio AL FINAL de la
   corrida — correcto para entrenar, NO es un log forense.
2. Las trazas pueden contener contenido de archivos del workspace: quedan en
   ``~/.cognia/data/`` y JAMAS se commitean al repo.
3. En la traza van SOLO los NOMBRES de los flags COGNIA_* presentes en el
   entorno, nunca sus valores (misma disciplina que la bitacora: un valor de
   flag puede ser una ruta con nombre de usuario o un secreto).

Todo es best-effort: un fallo de disco aqui JAMAS rompe el bucle del agente.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path


def habilitada() -> bool:
    """COGNIA_TRAZAS=1, leido a CALL-TIME (no a import) para que el banco
    pueda encenderlo en el mismo proceso antes de correr las tareas."""
    return os.environ.get("COGNIA_TRAZAS", "").strip() == "1"


def dir_trazas() -> Path:
    """Directorio de trazas; COGNIA_TRAZAS_DIR permite override (tests).
    Se crea si no existe. SIN poda automatica (ver docstring del modulo)."""
    override = os.environ.get("COGNIA_TRAZAS_DIR", "").strip()
    ruta = Path(override) if override else (
        Path.home() / ".cognia" / "data" / "trazas")
    ruta.mkdir(parents=True, exist_ok=True)
    return ruta


def _flags_cognia() -> list:
    """SOLO los NOMBRES de flags COGNIA_* del entorno — jamas valores."""
    return sorted(k for k in os.environ if k.startswith("COGNIA_"))


def _escribir_atomico(ruta: Path, datos: dict) -> None:
    """Escribir a .tmp y os.replace: una traza a medias no existe nunca."""
    tmp = ruta.with_suffix(ruta.suffix + ".tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    os.replace(tmp, ruta)


def _archivos_de(task_id: str) -> list:
    """Los volcados de una tarea: <id>.json y <id>-cNN.json, ordenados.
    El filtro por stem evita que '20260809-x' matchee '20260809-xy'."""
    base = dir_trazas()
    out = []
    for p in sorted(base.glob(task_id + "*.json")):
        stem = p.stem
        if stem == task_id or stem.startswith(task_id + "-c"):
            out.append(p)
    return out


def volcar(task_id: str, mensajes: list, schemas: list, sampling: dict,
           perfil: dict, resultado: dict) -> str:
    """Vuelca la conversacion a ``<dir_trazas>/<task_id>[-cNN].json``.

    Devuelve el TASK_ID usado ('' si el flag esta apagado o algo fallo): el
    hook del loop lo publica en ``ctx['_traza_task_id']`` y los selladores
    (horizonte, bancos, epilogo del contrato) sellan por ese id — por eso el
    retorno es el id y no la ruta.

    Resolucion del task_id cuando llega vacio (orden congelado en el plan):
    1. ``bitacora.task_id_activo()`` — import perezoso y TOLERANTE: el getter
       lo agrega la ola 2; si aun no existe se sigue de largo. Asi traza y
       bitacora comparten id en modo horizonte y ``ciclos_con_contrato``
       puede sellar directo.
    2. ``estado_tarea.nuevo_task_id(<primer mensaje user>)``.

    Sufijos ``-c02``, ``-c03``...: el horizonte invoca ``bucle_nativo`` una
    vez por ciclo; cada ciclo es un volcado aparte de la MISMA tarea.
    Best-effort TOTAL: cualquier excepcion devuelve '' sin propagar.
    """
    if not habilitada():
        return ""
    try:
        mensajes = list(mensajes or [])
        if not task_id:
            try:
                from cognia.agent import bitacora as _bit
                getter = getattr(_bit, "task_id_activo", None)
                if getter is not None:
                    task_id = str(getter() or "")
            except Exception:
                pass
        if not task_id:
            from cognia.agent.estado_tarea import nuevo_task_id
            primer_user = next((m.get("content") or "" for m in mensajes
                                if m.get("role") == "user"), "")
            task_id = nuevo_task_id(primer_user)

        previos = len(_archivos_de(task_id))
        nombre = (task_id + ".json" if previos == 0
                  else f"{task_id}-c{previos + 1:02d}.json")
        datos = {
            "version": 1,
            "task_id": task_id,
            "ts": datetime.now().isoformat(timespec="seconds"),
            "modelo": (perfil or {}).get("modelo", ""),
            "perfil": (perfil or {}).get("nombre", ""),
            # 'url' fuera: es config de la maquina, no del ejemplo. Del resto
            # del sampling depende reproducir la decodificacion en el trainer.
            "sampling": {k: v for k, v in (sampling or {}).items()
                         if k != "url"},
            "flags": _flags_cognia(),
            "schemas": list(schemas or []),
            "mensajes": mensajes,
            "resultado": dict(resultado or {}),
            "calidad": None,
        }
        _escribir_atomico(dir_trazas() / nombre, datos)
        return task_id
    except Exception:
        return ""


def sellar(task_id: str, etiqueta: dict) -> bool:
    """Merge de ``etiqueta`` en ``calidad`` de TODOS los volcados de la tarea
    (idempotente: sellar dos veces lo mismo deja el mismo archivo). El sello
    de EVIDENCIA REAL (``verificar_ws``/``contrato_ok``/``gate``) es lo que
    separa dataset de ruido — sin sello, la traza no entrena.
    Best-effort: False si no hay archivos o algo fallo, jamas lanza."""
    try:
        archivos = _archivos_de(task_id)
        if not archivos or not isinstance(etiqueta, dict):
            return False
        for ruta in archivos:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
            datos["calidad"] = {**(datos.get("calidad") or {}), **etiqueta}
            _escribir_atomico(ruta, datos)
        return True
    except Exception:
        return False
