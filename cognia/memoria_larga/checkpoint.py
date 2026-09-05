# -*- coding: utf-8 -*-
"""Checkpoint de TAREA (no de ficheros): lo que hace falta para destruir el
contexto y continuar.

Antes (auditoría 2026-09-04) no existía: `harness/checkpoints.py` guarda el
estado previo de un FICHERO antes de escribirlo, `estado_tarea` solo vive con
COGNIA_HORIZONTE=1, y `~/.cognia_agent_state.json` se escribe al FINAL de la
tarea. Si el proceso moría a mitad de un /hacer, no quedaba tarea, plan, canal
ni next_action.

Un checkpoint es un dict JSON:
  n, task_id, session_id, cwd, tarea, paso, timestamp, motivo,
  estado ('en_curso'|'completa'|'incompleta'|'retomada'),
  resumen_estado (render del canal), canal (serializado, si hay),
  completado [..], pendiente [..], decisiones [..], errores [..],
  ficheros [..], next_action, ultima_intencion, memorias (ids), trace_cola [..],
  mensajes_fuera (cuántos quedaron fuera de la ventana), tokens_historicos.
Se persiste DOS veces (cinturón y tirantes): tabla `checkpoints` del almacén y
`<dir>/tareas/<task_id>/checkpoint.json` (tmp + os.replace = atómico). Si el
almacén falla, el JSON basta para retomar; si falla el JSON, el almacén basta.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

_LOG = logging.getLogger(__name__)


def dir_base() -> Path:
    for var in ("COGNIA_MEMORIA_DIR",):
        v = os.environ.get(var, "").strip()
        if v:
            return Path(v)
    home = os.environ.get("COGNIA_HOME", "").strip()
    return Path(home) if home else Path.home() / ".cognia"


def ruta_checkpoint(task_id: str) -> Path:
    return dir_base() / "tareas" / task_id / "checkpoint.json"


def _escribir_atomico(ruta: Path, data: dict) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, ruta)


def crear(*, task_id: str, session_id: str, cwd: str, tarea: str, paso: int, motivo: str,
          estado_canal=None, canal_mod=None, ficheros=(), trace=(), next_action: str = "",
          ultima_intencion: str = "", faltan=(), memorias_ids=(), mensajes_fuera: int = 0,
          tokens_historicos: int = 0, estado: str = "en_curso", n: int | None = None,
          decisiones=(), errores=(), completado=()) -> dict:
    cp = {
        "n": n, "task_id": task_id, "session_id": session_id, "cwd": cwd, "tarea": tarea,
        "paso": int(paso), "timestamp": time.time(), "motivo": motivo, "estado": estado,
        "resumen_estado": "", "canal": None,
        "completado": list(completado), "pendiente": list(faltan), "decisiones": list(decisiones),
        "errores": list(errores), "ficheros": list(ficheros)[:60],
        "next_action": next_action or "", "ultima_intencion": ultima_intencion or "",
        "memorias": list(memorias_ids)[:200],
        "trace_cola": [dict(t) for t in list(trace)[-8:]] if trace else [],
        "mensajes_fuera": int(mensajes_fuera), "tokens_historicos": int(tokens_historicos),
    }
    if estado_canal is not None and canal_mod is not None:
        try:
            cp["resumen_estado"] = canal_mod.render(estado_canal, tope_chars=1600)
            cp["canal"] = canal_mod.serializar(estado_canal)
            pend = estado_canal.get("pendientes") if isinstance(estado_canal, dict) else None
            if pend and not cp["pendiente"]:
                cp["pendiente"] = [str(p.get("texto", p) if isinstance(p, dict) else p) for p in pend][:12]
        except Exception as exc:
            _LOG.warning("checkpoint: canal no serializable (%s)", exc)
    return cp


def guardar(cp: dict, almacen=None) -> dict:
    """Persiste en almacén (si hay) y en JSON. Devuelve el cp con `n` asignado."""
    if almacen is not None:
        try:
            n = almacen.checkpoint_guardar(cp)
            if cp.get("n") is None and n:
                cp["n"] = n
        except Exception as exc:
            _LOG.warning("checkpoint: almacén no disponible (%s); solo JSON", exc)
    if cp.get("n") is None:
        # sin almacén: numerar por lo que haya en disco
        try:
            previo = cargar_json(cp["task_id"])
            cp["n"] = int((previo or {}).get("n") or 0) + 1
        except Exception:
            cp["n"] = 1
    try:
        _escribir_atomico(ruta_checkpoint(cp["task_id"]), cp)
    except Exception as exc:
        # último recurso: volcado de emergencia junto al cwd
        _LOG.warning("checkpoint: no pude escribir el JSON (%s); volcado de emergencia", exc)
        try:
            emergencia = Path(cp.get("cwd") or ".") / ".cognia_checkpoint_emergencia.json"
            emergencia.write_text(json.dumps(cp, ensure_ascii=False), encoding="utf-8")
        except Exception as exc2:
            _LOG.warning("checkpoint: ni el volcado de emergencia (%s)", exc2)
    return cp


def cargar_json(task_id: str) -> dict | None:
    try:
        r = ruta_checkpoint(task_id)
        if r.is_file():
            return json.loads(r.read_text(encoding="utf-8"))
    except Exception as exc:
        _LOG.warning("checkpoint: JSON ilegible de %s (%s)", task_id, exc)
    return None


def ultimo(cwd: str | None = None, almacen=None, solo_abiertos: bool = True) -> dict | None:
    """El checkpoint más reciente (opcionalmente del mismo cwd). Mira el almacén y el disco."""
    candidatos: list[dict] = []
    if almacen is not None:
        try:
            cp = almacen.checkpoint_ultimo(cwd=cwd)
            if cp:
                candidatos.append(cp)
        except Exception as exc:
            _LOG.warning("checkpoint: almacén no consultable (%s)", exc)
    try:
        base = dir_base() / "tareas"
        if base.is_dir():
            for d in base.iterdir():
                r = d / "checkpoint.json"
                if r.is_file():
                    try:
                        cp = json.loads(r.read_text(encoding="utf-8"))
                        if not cwd or _mismo_dir(cp.get("cwd"), cwd):
                            candidatos.append(cp)
                    except Exception:
                        continue
    except Exception as exc:
        _LOG.warning("checkpoint: disco no listable (%s)", exc)
    if solo_abiertos:
        candidatos = [c for c in candidatos if c.get("estado") == "en_curso"]
    if not candidatos:
        return None
    return max(candidatos, key=lambda c: float(c.get("timestamp") or 0))


def _mismo_dir(a, b) -> bool:
    try:
        return os.path.normcase(os.path.normpath(str(a))) == os.path.normcase(os.path.normpath(str(b)))
    except Exception:
        return False


def sellar(task_id: str, estado: str, almacen=None) -> None:
    cp = cargar_json(task_id)
    if cp:
        cp["estado"] = estado
        cp["timestamp"] = time.time()
        guardar(cp, almacen)


def render(cp: dict, max_chars: int = 1800) -> str:
    """Bloque para el prompt: qué había, qué falta, y el siguiente paso."""
    partes = [f"CHECKPOINT #{cp.get('n')} de la tarea {cp.get('task_id')} (paso {cp.get('paso')}, {cp.get('estado')})"]
    if cp.get("resumen_estado"):
        partes.append(cp["resumen_estado"].strip())
    if cp.get("completado"):
        partes.append("HECHO: " + "; ".join(str(x)[:100] for x in cp["completado"][:8]))
    if cp.get("pendiente"):
        partes.append("PENDIENTE: " + "; ".join(str(x)[:100] for x in cp["pendiente"][:8]))
    if cp.get("decisiones"):
        partes.append("DECISIONES: " + "; ".join(str(x)[:120] for x in cp["decisiones"][:6]))
    if cp.get("errores"):
        partes.append("ERRORES RECIENTES: " + "; ".join(str(x)[:120] for x in cp["errores"][:4]))
    if cp.get("ficheros"):
        partes.append("FICHEROS TOCADOS: " + ", ".join(str(x) for x in cp["ficheros"][:15]))
    if cp.get("next_action"):
        partes.append("SIGUIENTE ACCIÓN: " + str(cp["next_action"])[:300])
    txt = "\n".join(partes)
    cola = "\n… (checkpoint recortado)"
    return txt if len(txt) <= max_chars else txt[:max_chars - len(cola)] + cola


__all__ = ["crear", "guardar", "cargar_json", "ultimo", "sellar", "render", "dir_base", "ruta_checkpoint"]
