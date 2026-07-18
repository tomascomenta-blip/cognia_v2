"""
cognia/console/proc_registry.py
===============================
Registro global de subprocesos lanzados desde la consola (/shells).

Cada shell lanzado con spawn_shell() queda registrado con un id autoincremental,
su Popen, timestamp de inicio, estado (running/done/failed) y un buffer circular
con las ultimas 200 lineas de salida (stdout+stderr combinados). Un hilo lector
daemon drena el pipe linea a linea para que el proceso nunca se bloquee por
buffer lleno, y marca el estado final cuando el proceso termina.

Al salir del interprete, cleanup_atexit() (registrado via atexit) mata todos
los shells que sigan vivos para no dejar procesos huerfanos.

Uso:
    from cognia.console.proc_registry import spawn_shell, get_output
    sid = spawn_shell("ping localhost")
    print("\\n".join(get_output(sid, last_n=10)))
"""

from __future__ import annotations

import atexit
import subprocess
import threading
import time
from collections import deque

# Maximo de lineas retenidas por shell (buffer circular).
_MAX_TAIL = 200

# Registro global {id: entry}. Protegido por _LOCK porque los hilos lectores
# actualizan status/output_tail mientras el REPL consulta desde su hilo.
_REGISTRY: dict[int, dict] = {}
_LOCK = threading.Lock()
_NEXT_ID = 1


def _reader_loop(entry: dict) -> None:
    """Drena stdout del proceso hacia output_tail y marca el estado final."""
    proc = entry["proc"]
    try:
        for line in proc.stdout:
            with _LOCK:
                entry["output_tail"].append(line.rstrip("\r\n"))
    except Exception:
        # pipe roto (kill) -- el estado final lo decide el returncode
        pass
    rc = proc.wait()
    with _LOCK:
        entry["returncode"] = rc
        entry["status"] = "done" if rc == 0 else "failed"


def spawn_shell(cmd: str, shell: bool = True) -> int:
    """Lanza cmd en background y devuelve su id en el registro.

    stdout+stderr van combinados al buffer circular del entry; un hilo lector
    daemon los consume sin bloquear al REPL.
    """
    global _NEXT_ID
    proc = subprocess.Popen(
        cmd, shell=shell,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    entry = {
        "id": 0,  # se asigna bajo lock
        "cmd": cmd,
        "proc": proc,
        "started": time.time(),
        "status": "running",
        "returncode": None,
        "output_tail": deque(maxlen=_MAX_TAIL),
    }
    with _LOCK:
        entry["id"] = _NEXT_ID
        _NEXT_ID += 1
        _REGISTRY[entry["id"]] = entry
    threading.Thread(
        target=_reader_loop, args=(entry,),
        daemon=True, name=f"shell-reader-{entry['id']}",
    ).start()
    return entry["id"]


def list_shells() -> list[dict]:
    """Snapshot de todos los shells registrados (para el comando /shells).

    No expone el Popen: solo campos serializables para mostrar en tabla.
    """
    with _LOCK:
        entries = list(_REGISTRY.values())
        out = []
        for e in entries:
            running = e["status"] == "running"
            out.append({
                "id":         e["id"],
                "cmd":        e["cmd"],
                "status":     e["status"],
                "started":    e["started"],
                "uptime_s":   round(time.time() - e["started"], 1) if running else None,
                "returncode": e["returncode"],
                "tail_lines": len(e["output_tail"]),
            })
    return sorted(out, key=lambda d: d["id"])


def get_output(shell_id: int, last_n: int | None = None) -> list[str]:
    """Ultimas lineas de salida del shell (todas las retenidas, o last_n)."""
    with _LOCK:
        entry = _REGISTRY.get(shell_id)
        if entry is None:
            return []
        lines = list(entry["output_tail"])
    if last_n is not None and last_n >= 0:
        return lines[-last_n:] if last_n else []
    return lines


def get_status(shell_id: int) -> str | None:
    """Estado actual del shell: running/done/failed, o None si no existe."""
    with _LOCK:
        entry = _REGISTRY.get(shell_id)
        return entry["status"] if entry else None


def kill_shell(shell_id: int) -> bool:
    """Termina el shell (terminate, luego kill). False si el id no existe."""
    with _LOCK:
        entry = _REGISTRY.get(shell_id)
    if entry is None:
        return False
    proc = entry["proc"]
    if proc.poll() is None:
        try:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        except Exception:
            pass
    # el hilo lector marca done/failed al cerrar el pipe; si el proceso ya no
    # corre pero el lector aun no llego, reflejamos el kill aca mismo
    with _LOCK:
        if entry["status"] == "running" and proc.poll() is not None:
            entry["status"] = "failed"
            entry["returncode"] = proc.poll()
    return True


def cleanup_atexit() -> None:
    """Mata todos los shells vivos al salir del proceso (registrado en atexit)."""
    with _LOCK:
        procs = [e["proc"] for e in _REGISTRY.values()]
    for proc in procs:
        if proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass


atexit.register(cleanup_atexit)
