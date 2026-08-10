"""
cognia/agent/bitacora.py
========================
Bitacora APPEND-ONLY por tarea (modo horizonte, COGNIA_HORIZONTE=1).

POR QUE EXISTE (mecanismo PRO-LONG, medido 97.4% en ARC-AGI-3): en tareas de
horizonte largo el agente no puede cargar toda su historia al contexto; lo que
SI puede es consultarla programaticamente. Este modulo suscribe un sink al bus
tipado (cognia/ux/events.py) y escribe una linea JSON por evento en

    <dir_tareas()>/<task_id>/bitacora.jsonl

y la tool bitacora_buscar (tools.py) la consulta con regex DEL ARNES — el
modelo pregunta, el arnes grepea; el modelo jamas escribe la bitacora.

Reglas:
- TokenTexto/RazonamientoTick se saltan (alta frecuencia, ruido).
- El sink traga toda excepcion (contrato del bus: el adorno no rompe el turno).
- flush por linea: un crash deja la bitacora legible hasta el ultimo evento.
- Eventos de sub-agentes (delegar_subtarea recursivo) caen en la bitacora del
  task RAIZ: hay un solo task activo modulo-global, a proposito.
"""

from __future__ import annotations

import json
import re
import time

from cognia.agent.estado_tarea import dir_tareas, nuevo_task_id, podar_viejas

# Eventos de streaming que no aportan a la traza de horizonte.
_SALTAR = ("TokenTexto", "RazonamientoTick")

# Estado del task activo (uno por proceso; documentado en el docstring).
_activo = {"task_id": "", "fh": None, "sink": None}


def _escribir(linea_dict: dict) -> None:
    fh = _activo.get("fh")
    if fh is None:
        return
    try:
        fh.write(json.dumps(linea_dict, ensure_ascii=False) + "\n")
        fh.flush()
    except Exception:
        pass


def iniciar(tarea: str, config_efectiva: dict) -> str:
    """Abre la bitacora de una tarea nueva, suscribe el sink al bus y devuelve
    el task_id. La primera linea es la config efectiva de la corrida (modelo,
    perfil, presupuesto, NOMBRES de flags COGNIA_* — jamas valores, para que
    ningun token se fugue a disco)."""
    cerrar()                          # idempotente: una tarea a la vez
    task_id = nuevo_task_id(tarea)
    ruta = dir_tareas() / task_id / "bitacora.jsonl"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    _activo["task_id"] = task_id
    _activo["fh"] = open(ruta, "a", encoding="utf-8")
    _escribir({"tipo": "config_efectiva", "ts": time.time(),
               "task_id": task_id, **(config_efectiva or {})})

    from cognia.ux import events as _ev

    def _sink(evento):
        try:
            if type(evento).__name__ in _SALTAR:
                return
            d = _ev.a_dict(evento)
            d["task_id"] = _activo["task_id"]
            _escribir(d)
        except Exception:
            pass                      # contrato del bus: jamas romper el turno

    _ev.suscribir(_sink)
    _activo["sink"] = _sink
    podar_viejas(excluir=task_id)
    return task_id


def anotar(payload: dict) -> None:
    """Linea propia del outer loop (p.ej. ciclo_fin) sin tocar el contrato de
    dataclasses del bus. No-op sin bitacora activa."""
    if _activo.get("fh") is None:
        return
    d = dict(payload or {})
    d.setdefault("ts", time.time())
    d["task_id"] = _activo["task_id"]
    _escribir(d)


def task_id_activo() -> str:
    """Task_id de la tarea de horizonte activa ('' si no hay ninguna).

    POR QUE: traza_chatml.volcar() lo consulta PRIMERO al resolver un task_id
    vacio (plan C6, ola 2) — asi traza y bitacora comparten id en modo
    horizonte y ciclos_con_contrato puede sellar directo por ese id."""
    return _activo.get("task_id", "") or ""


def cerrar() -> None:
    """Desuscribe el sink y cierra el archivo. Idempotente; nunca lanza."""
    sink = _activo.get("sink")
    if sink is not None:
        try:
            from cognia.ux import events as _ev
            _ev.desuscribir(sink)
        except Exception:
            pass
    fh = _activo.get("fh")
    if fh is not None:
        try:
            fh.close()
        except Exception:
            pass
    _activo.update({"task_id": "", "fh": None, "sink": None})


def _ruta_de(task_id: str):
    """Ruta de la bitacora de ese task (o del activo, o la mas reciente)."""
    tid = task_id or _activo.get("task_id")
    if tid:
        return dir_tareas() / tid / "bitacora.jsonl"
    try:
        dirs = sorted((d for d in dir_tareas().iterdir() if d.is_dir()),
                      key=lambda d: d.name, reverse=True)
    except OSError:
        return None
    return (dirs[0] / "bitacora.jsonl") if dirs else None


def _formatear(d: dict) -> str:
    """Linea legible para el modelo: 'paso N | tool | ok | resumen' para
    ToolFin; forma generica corta para el resto."""
    tipo = d.get("tipo", "?")
    if tipo == "ToolFin":
        ok = "ok" if d.get("ok") else "ERROR"
        return (f"paso {d.get('paso', '?')} | {d.get('tool', '?')} "
                f"{(d.get('args') or '')[:60]} | {ok} | "
                f"{(d.get('resumen') or '')[:120]}")
    if tipo == "PasoIntencion":
        return f"paso {d.get('paso', '?')} | intencion | {(d.get('intencion') or '')[:120]}"
    if tipo == "ciclo_fin":
        return (f"ciclo {d.get('ciclo', '?')} fin | contrato "
                f"{d.get('contrato', '?')} | motivo {d.get('motivo_relevo', '')}")
    resto = {k: v for k, v in d.items()
             if k not in ("tipo", "ts", "task_id")}
    return f"{tipo} | {str(resto)[:140]}"


def buscar(patron: str, ultimas_n: int = 20, task_id: str = "") -> str:
    """Grep DEL ARNES sobre la bitacora: re.search por linea (case-insensitive)
    sobre el JSON crudo, devuelve las ultimas ``ultimas_n`` coincidencias
    formateadas. El modelo consulta; el arnes filtra."""
    ruta = _ruta_de(task_id)
    if ruta is None or not ruta.exists():
        return "(sin bitacora: no hay tarea de horizonte activa ni previa)"
    # Cotas anti-backtracking-catastrofico: el patron lo escribio el MODELO
    # (input no confiable para re): patron <=200 chars y busqueda sobre una
    # vista de <=500 chars por linea. No elimina el ReDoS teorico pero acota
    # el peor caso a algo que no cuelga el turno (revision 2026-08-09).
    try:
        rx = re.compile((patron or ".")[:200], re.IGNORECASE)
    except re.error as exc:
        return f"(patron invalido: {exc})"
    hits = []
    try:
        with open(ruta, "r", encoding="utf-8") as fh:
            for linea in fh:
                if not rx.search(linea[:500]):
                    continue
                try:
                    hits.append(_formatear(json.loads(linea)))
                except ValueError:
                    continue
    except OSError as exc:
        return f"(no pude leer la bitacora: {exc})"
    if not hits:
        return f"(sin coincidencias para '{patron}' en la bitacora)"
    n = max(1, int(ultimas_n or 20))
    return "\n".join(hits[-n:])
