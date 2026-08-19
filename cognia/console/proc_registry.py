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
                # lineas_total cuenta TODO lo emitido, no lo retenido: la resta
                # con len(output_tail) es cuanto se DESCARTO del buffer
                # circular. Sin ese dato, ver_salida presentaria la cola de un
                # build de 10k lineas como si fuera la salida entera.
                entry["lineas_total"] += 1
                entry["output_tail"].append(line.rstrip("\r\n"))
    except Exception:
        # pipe roto (kill) -- el estado final lo decide el returncode
        pass
    rc = proc.wait()
    with _LOCK:
        entry["returncode"] = rc
        entry["status"] = "done" if rc == 0 else "failed"


def spawn_shell(cmd: str, shell: bool = True, cwd: str = None,
                env: dict = None) -> int:
    """Lanza cmd en background y devuelve su id en el registro.

    stdout+stderr van combinados al buffer circular del entry; un hilo lector
    daemon los consume sin bloquear al REPL. ``cwd`` corre el comando en otro
    directorio sin tener que prefijar 'cd ... &&' (el encadenado, ademas, el
    sentinel lo reclasifica a CONFIRM). ``env`` reemplaza el entorno del hijo
    (None = hereda el del proceso).
    """
    global _NEXT_ID
    proc = subprocess.Popen(
        cmd, shell=shell, cwd=cwd or None, env=env or None,
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
        "cwd": cwd or None,
        "lineas_total": 0,
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
                "lineas_total": e["lineas_total"],
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


def get_info(shell_id: int):
    """Ficha del shell (sin el Popen), o None si el id no existe.

    Trae 'descartadas' = lineas que el buffer circular ya tiro. Quien muestra
    la salida TIENE que poder decir "no viste el principio": una cola
    presentada como salida completa es un vacio silencioso, y de esos salen
    las conclusiones falsas.
    """
    with _LOCK:
        e = _REGISTRY.get(shell_id)
        if e is None:
            return None
        retenidas = len(e["output_tail"])
        return {
            "id":           e["id"],
            "cmd":          e["cmd"],
            "cwd":          e["cwd"],
            "status":       e["status"],
            "returncode":   e["returncode"],
            "uptime_s":     round(time.time() - e["started"], 1),
            "retenidas":    retenidas,
            "lineas_total": e["lineas_total"],
            "descartadas":  max(0, e["lineas_total"] - retenidas),
            "buffer_max":   _MAX_TAIL,
        }


def kill_shell(shell_id: int) -> bool:
    """Termina el shell. True si al volver YA NO ESTA VIVO; False si no existe
    o si sigue corriendo.

    POR QUE SE MIRA EL RESULTADO (2026-08-18): antes esto devolvia True
    incondicionalmente, con terminate() y kill() dentro de un `except:
    pass`. O sea: un proceso que sobrevivio al kill (elevado, colgado en E/S
    del kernel, con hijos propios) se reportaba como "shell terminado" y el
    usuario -- o el agente -- seguia adelante creyendo que habia liberado el
    puerto, el fichero o la GPU. Es exactamente la leccion de la casa "matar
    el shell NO mata el proceso", esta vez escrita en el codigo que mata.
    """
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
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    pass          # sigue vivo: lo dice el return de abajo
        except Exception:
            pass
    # el hilo lector marca done/failed al cerrar el pipe; si el proceso ya no
    # corre pero el lector aun no llego, reflejamos el kill aca mismo
    with _LOCK:
        if entry["status"] == "running" and proc.poll() is not None:
            entry["status"] = "failed"
            entry["returncode"] = proc.poll()
    return proc.poll() is not None


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
