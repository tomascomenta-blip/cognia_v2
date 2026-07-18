"""
cognia/console/monitors.py
==========================
Monitores en background para el REPL de Cognia (/monitores).

Un Monitor corre check_fn() en un hilo daemon cada interval_s segundos.
check_fn devuelve None (seguir chequeando) o un str (evento: se guarda,
el monitor queda "fired" y el hilo termina). Si pasa timeout_s sin disparar,
el monitor queda "timeout" y tambien encola un evento para que el usuario
se entere.

Los eventos disparados se acumulan en una cola global; el loop del REPL los
drena entre turnos con pop_fired_events() y los imprime.

Constructores listos para los casos tipicos:
    monitor_output_regex(shell_id, pattern, ...)  -> regex sobre proc_registry
    monitor_file_exists(path, ...)                -> aparece un archivo
    monitor_url_healthy(url, ..., esperar_caida)  -> URL responde (o se cae)

Uso:
    from cognia.console.monitors import monitor_file_exists, pop_fired_events
    mid = monitor_file_exists("build/out.gguf", "espera del build")
    ...
    for ev in pop_fired_events():
        print(ev)
"""

from __future__ import annotations

import re
import threading
import time
import urllib.request
from pathlib import Path

# Defaults conservadores: chequear cada 2s, rendirse a los 10 minutos.
_DEFAULT_INTERVAL_S = 2.0
_DEFAULT_TIMEOUT_S = 600.0

# Registro global de monitores + cola de eventos disparados.
_MONITORS: dict[int, "Monitor"] = {}
_LOCK = threading.Lock()
_NEXT_ID = 1
_FIRED: list[str] = []


def _push_event(msg: str) -> None:
    with _LOCK:
        _FIRED.append(msg)


class Monitor:
    """Monitor periodico en hilo daemon.

    Estados: running -> fired | timeout | stopped | error.
    check_fn: sin argumentos; None = seguir, str = evento (dispara y termina).
    """

    def __init__(self, monitor_id: int, descripcion: str, check_fn,
                 interval_s: float = _DEFAULT_INTERVAL_S,
                 timeout_s: float = _DEFAULT_TIMEOUT_S):
        self.id = monitor_id
        self.descripcion = descripcion
        self.check_fn = check_fn
        self.interval_s = interval_s
        self.timeout_s = timeout_s
        self.started = time.time()
        self.status = "running"
        self.evento: str | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name=f"monitor-{monitor_id}",
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            if time.time() - self.started > self.timeout_s:
                self.status = "timeout"
                _push_event(f"[monitor {self.id}] TIMEOUT tras {self.timeout_s:g}s: {self.descripcion}")
                return
            try:
                result = self.check_fn()
            except Exception as exc:
                self.status = "error"
                _push_event(f"[monitor {self.id}] ERROR en '{self.descripcion}': {exc}")
                return
            if result is not None:
                self.status = "fired"
                self.evento = str(result)
                _push_event(f"[monitor {self.id}] {self.descripcion}: {result}")
                return
            self._stop.wait(self.interval_s)
        self.status = "stopped"


# ── API publica ───────────────────────────────────────────────────────────────

def start_monitor(descripcion: str, check_fn,
                  interval_s: float = _DEFAULT_INTERVAL_S,
                  timeout_s: float = _DEFAULT_TIMEOUT_S) -> int:
    """Registra y arranca un monitor generico; devuelve su id."""
    global _NEXT_ID
    with _LOCK:
        mid = _NEXT_ID
        _NEXT_ID += 1
    mon = Monitor(mid, descripcion, check_fn, interval_s, timeout_s)
    with _LOCK:
        _MONITORS[mid] = mon
    mon.start()
    return mid


def list_monitors() -> list[dict]:
    """Snapshot de todos los monitores (para el comando /monitores)."""
    with _LOCK:
        mons = list(_MONITORS.values())
    out = []
    for m in mons:
        out.append({
            "id":          m.id,
            "descripcion": m.descripcion,
            "status":      m.status,
            "started":     m.started,
            "interval_s":  m.interval_s,
            "timeout_s":   m.timeout_s,
            "evento":      m.evento,
        })
    return sorted(out, key=lambda d: d["id"])


def pop_fired_events() -> list[str]:
    """Drena y devuelve los eventos disparados desde la ultima llamada.

    El loop del REPL llama esto entre turnos y le imprime la lista al usuario.
    """
    with _LOCK:
        events = list(_FIRED)
        _FIRED.clear()
    return events


def stop_monitor(monitor_id: int) -> bool:
    """Detiene un monitor por id. False si no existe."""
    with _LOCK:
        mon = _MONITORS.get(monitor_id)
    if mon is None:
        return False
    mon.stop()
    return True


# ── Constructores tipicos ─────────────────────────────────────────────────────

def monitor_output_regex(shell_id: int, pattern: str, descripcion: str = "",
                         interval_s: float = _DEFAULT_INTERVAL_S,
                         timeout_s: float = _DEFAULT_TIMEOUT_S) -> int:
    """Dispara cuando una linea de salida del shell matchea el regex.

    Si el shell termina sin match, dispara igual avisando el estado final
    (mejor un evento explicito que esperar el timeout).
    """
    from cognia.console import proc_registry

    rx = re.compile(pattern)
    desc = descripcion or f"regex '{pattern}' en shell {shell_id}"

    def check() -> str | None:
        for line in proc_registry.get_output(shell_id):
            if rx.search(line):
                return f"match: {line}"
        status = proc_registry.get_status(shell_id)
        if status not in (None, "running"):
            return f"shell {shell_id} termino ({status}) sin coincidencias"
        return None

    return start_monitor(desc, check, interval_s, timeout_s)


def monitor_file_exists(path: str, descripcion: str = "",
                        interval_s: float = _DEFAULT_INTERVAL_S,
                        timeout_s: float = _DEFAULT_TIMEOUT_S) -> int:
    """Dispara cuando el archivo (o directorio) aparece en disco."""
    p = Path(path)
    desc = descripcion or f"aparicion de {p}"

    def check() -> str | None:
        if p.exists():
            return f"existe {p}"
        return None

    return start_monitor(desc, check, interval_s, timeout_s)


def monitor_url_healthy(url: str, descripcion: str = "",
                        esperar_caida: bool = False,
                        interval_s: float = _DEFAULT_INTERVAL_S,
                        timeout_s: float = _DEFAULT_TIMEOUT_S) -> int:
    """Dispara cuando la URL responde saludable (o cuando se cae, con
    esperar_caida=True: util para saber que un servidor termino de apagarse)."""
    desc = descripcion or (f"caida de {url}" if esperar_caida else f"salud de {url}")

    def _up() -> bool:
        try:
            with urllib.request.urlopen(url, timeout=3) as r:
                return 200 <= r.status < 400
        except Exception:
            return False

    def check() -> str | None:
        up = _up()
        if esperar_caida and not up:
            return f"{url} dejo de responder"
        if not esperar_caida and up:
            return f"{url} responde OK"
        return None

    return start_monitor(desc, check, interval_s, timeout_s)
