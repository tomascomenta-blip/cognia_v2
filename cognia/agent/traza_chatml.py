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


# Lo que lee el modelo en el turno tool de un call que NUNCA se ejecuto.
CONTENIDO_HUERFANO = "(cancelada: el bucle se corto antes de ejecutarla)"


def parchear_huerfanos(mensajes: list) -> int:
    """Inserta un turno tool sintetico por cada tool_call de un assistant
    que no tiene su turno tool a continuacion (deepagents 0.7.8,
    middleware/patch_tool_calls.py::PatchToolCallsMiddleware: "cancelled -
    another message came in..."). Muta la lista EN SITIO y devuelve cuantos
    inserto.

    POR QUE: los dos `mensajes = None; break` de bucle_nativo (guardia de
    bucle y estancamiento) cortan el for a mitad de las tool_calls del turno:
    el assistant queda con N calls y k<N resultados. Esa lista es la que
    volcar() escribe (mensajes_dump apunta a la misma) y la que un reintento
    podria mandar al server: una traza con huerfanos entrena un formato que
    el template del server rechaza ("tool_call sin tool result"). El parche
    va aqui y no en chat_client porque el dato de que ES huerfano solo
    existe mirando la lista entera.

    Los resultados de un assistant NO son siempre contiguos: bucle_nativo
    apende un `user` de nudge DENTRO del for de tool_calls, justo tras el
    turno tool que lo disparo (loop.py: _aviso_guardia, _aviso_fichero de
    P12, el AVISO de verdict=='warn'), asi que con N calls paralelas y un
    nudge tras la primera, las N-1 restantes tienen su resultado real DESPUES
    del user. Mirar solo el bloque contiguo insertaba un '(cancelada...)'
    por cada una: tool_call_id duplicado y un resultado falso antes del
    real, en TODA traza volcada (revision adversarial 2026-08-24). Por eso
    se cuentan los tool hasta el siguiente assistant y los sinteticos van
    tras el ULTIMO tool real de ese tramo (los ids son unicos por
    corrida: un tool de otro tramo no puede casar)."""
    insertados = 0
    i = 0
    while i < len(mensajes):
        m = mensajes[i]
        if not isinstance(m, dict) or m.get("role") != "assistant":
            i += 1
            continue
        calls = [tc for tc in (m.get("tool_calls") or []) if isinstance(tc, dict)]
        if not calls:
            i += 1
            continue
        # Los turnos tool del tramo hasta el siguiente assistant (user de
        # nudge intercalados incluidos); j = tras el ultimo tool real.
        j = i + 1
        vistos = set()
        k = i + 1
        while k < len(mensajes) and isinstance(mensajes[k], dict) \
                and mensajes[k].get("role") != "assistant":
            if mensajes[k].get("role") == "tool":
                vistos.add(mensajes[k].get("tool_call_id"))
                j = k + 1
            k += 1
        for tc in calls:
            tid = tc.get("id")
            if tid in vistos:
                continue
            nombre = str((tc.get("function") or {}).get("name") or "")
            mensajes.insert(j, {"role": "tool", "tool_call_id": tid,
                                "name": nombre,
                                "content": CONTENIDO_HUERFANO})
            j += 1
            insertados += 1
        i = j
    return insertados


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
        # La traza no lleva tool_calls sin resultado (ver parchear_huerfanos):
        # el bucle ya parchea antes de sus dos cortes, esto cubre a cualquier
        # otro llamador (bancos, horizonte) que traiga una lista cortada.
        parchear_huerfanos(mensajes)
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
