"""
cognia/tasks_board.py
=====================
Tablero de tareas con checkboxes para el CLI (/tarea-*, /tareas) y el agente.

El store viejo (ai._session_tasks en cli.py) era una lista en memoria que
moria al cerrar el CLI. Este modulo lo reemplaza con persistencia JSON:

    ~/.cognia/data/tasks_board.json     (override: COGNIA_TASKS_FILE)

El override se lee a CALL-time (mismo patron que COGNIA_EXPERTS_DIR en
cognia/experts/registry.py), y cada funcion lee/escribe disco en el momento,
sin cache: una carga fresca siempre ve lo ultimo.

Formato del archivo: {"next_id": N, "tasks": [{id, texto, done, origen,
created}]}. next_id solo crece y nunca se reusa aunque se borren tareas,
asi dos adds seguidos (o un add tras un borrar) jamas chocan ids.

API para el agente (/hacer -> _run_agent_task en cli.py): al parsear el
PLAN DE SUBTAREAS, agent_plan_tasks(pasos) crea todas como origen='agente'
(cuadrados vacios) y agent_mark_done(id) los va llenando conforme el loop
completa pasos; board_progress_hook() devuelve el tablero renderizado para
mostrar el avance tras cada paso.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Checkboxes unicode: BALLOT BOX (vacio) y BALLOT BOX WITH CHECK (lleno).
_CHECKBOX_EMPTY = "☐"
_CHECKBOX_DONE = "☑"

_ORIGENES = ("usuario", "agente")


# -- Paths y carga/guardado ---------------------------------------------------

def tasks_file() -> Path:
    """Ruta del JSON del tablero; COGNIA_TASKS_FILE permite override (tests)."""
    override = os.environ.get("COGNIA_TASKS_FILE", "").strip()
    if override:
        return Path(override)
    return Path.home() / ".cognia" / "data" / "tasks_board.json"


def _load() -> dict:
    """
    Carga el tablero desde disco. Archivo ausente o corrupto degrada a
    tablero vacio (mismo criterio que experts/registry.py con JSON roto).
    """
    try:
        raw = json.loads(tasks_file().read_text(encoding="utf-8"))
        tasks = raw.get("tasks") if isinstance(raw, dict) else None
        if isinstance(tasks, list):
            tasks = [t for t in tasks if isinstance(t, dict) and "id" in t]
            max_id = max((int(t["id"]) for t in tasks), default=0)
            next_id = max(int(raw.get("next_id", 0)), max_id + 1)
            return {"next_id": next_id, "tasks": tasks}
    except (OSError, ValueError, TypeError):
        pass
    return {"next_id": 1, "tasks": []}


def _save(board: dict) -> None:
    """Escribe el tablero completo a disco, creando el directorio si falta."""
    path = tasks_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(board, ensure_ascii=False, indent=2),
                    encoding="utf-8")


# -- CRUD ---------------------------------------------------------------------

def add_task(texto: str, origen: str = "usuario") -> int:
    """
    Agrega una tarea pendiente y devuelve su id (entero, nunca reusado).
    Lanza ValueError con texto vacio u origen fuera de usuario/agente.
    """
    texto = (texto or "").strip()
    if not texto:
        raise ValueError("texto vacio: la tarea necesita una descripcion")
    if origen not in _ORIGENES:
        raise ValueError(
            f"origen invalido: {origen!r}. Validos: {', '.join(_ORIGENES)}"
        )
    board = _load()
    tid = board["next_id"]
    board["next_id"] = tid + 1
    board["tasks"].append({
        "id": tid,
        "texto": texto,
        "done": False,
        "origen": origen,
        "created": datetime.now().isoformat(timespec="seconds"),
    })
    _save(board)
    return tid


def _set_done(task_id: int, done: bool) -> bool:
    """Marca done=done en la tarea con ese id. False si no existe."""
    board = _load()
    for t in board["tasks"]:
        if t["id"] == task_id:
            t["done"] = done
            _save(board)
            return True
    return False


def complete_task(task_id: int) -> bool:
    """Marca la tarea como completada (checkbox lleno). False si no existe."""
    return _set_done(task_id, True)


def uncomplete_task(task_id: int) -> bool:
    """Vuelve la tarea a pendiente (checkbox vacio). False si no existe."""
    return _set_done(task_id, False)


def remove_task(task_id: int) -> bool:
    """Borra la tarea del tablero. False si no existe."""
    board = _load()
    before = len(board["tasks"])
    board["tasks"] = [t for t in board["tasks"] if t["id"] != task_id]
    if len(board["tasks"]) == before:
        return False
    _save(board)
    return True


def list_tasks() -> list:
    """Lista de dicts {id, texto, done, origen, created} en orden de alta."""
    return [dict(t) for t in _load()["tasks"]]


# -- Render -------------------------------------------------------------------

def _checkbox_chars() -> tuple:
    """
    (vacio, lleno): checkboxes unicode si la consola los codifica, si no
    fallback ASCII '[ ]'/'[x]'. Se decide con sys.stdout.encoding a
    call-time (pipes y consolas cp1252 no aguantan U+2610/U+2611).
    """
    enc = getattr(sys.stdout, "encoding", None) or ""
    try:
        (_CHECKBOX_EMPTY + _CHECKBOX_DONE).encode(enc)
        return _CHECKBOX_EMPTY, _CHECKBOX_DONE
    except (UnicodeEncodeError, LookupError, TypeError):
        return "[ ]", "[x]"


def render_board(tasks=None) -> str:
    """
    Tablero imprimible: pendientes arriba (checkbox vacio), completadas
    abajo (checkbox lleno), contador 'X/Y completadas' al final. Con
    tasks=None lee el store; una lista explicita permite renderizar
    subconjuntos (p.ej. solo las del agente) sin tocar disco.
    """
    if tasks is None:
        tasks = list_tasks()
    if not tasks:
        return "No hay tareas en el tablero. Crea una con /tarea-crear <desc>."
    empty, full = _checkbox_chars()
    lines = []
    for t in tasks:
        if not t["done"]:
            marca = " (agente)" if t.get("origen") == "agente" else ""
            lines.append(f"  {empty} #{t['id']} {t['texto']}{marca}")
    for t in tasks:
        if t["done"]:
            marca = " (agente)" if t.get("origen") == "agente" else ""
            lines.append(f"  {full} #{t['id']} {t['texto']}{marca}")
    done_n = sum(1 for t in tasks if t["done"])
    lines.append(f"  {done_n}/{len(tasks)} completadas")
    return "\n".join(lines)


# -- API para el agente (/hacer) ----------------------------------------------

def agent_plan_tasks(pasos) -> list:
    """
    Crea cada paso del plan del agente como tarea origen='agente' (cuadrado
    vacio) y devuelve los ids en el mismo orden. Pasos en blanco se saltan.
    """
    return [add_task(p, origen="agente") for p in pasos if (p or "").strip()]


def agent_mark_done(task_id: int) -> bool:
    """El agente llena el checkbox del paso que acaba de completar."""
    return complete_task(task_id)


def board_progress_hook() -> str:
    """
    Tablero renderizado solo con las tareas del agente, para que el loop
    de /hacer muestre el avance (cuadrados llenandose) tras cada paso.
    Cadena vacia si el agente no planifico nada.
    """
    agente = [t for t in list_tasks() if t.get("origen") == "agente"]
    if not agente:
        return ""
    return render_board(agente)
