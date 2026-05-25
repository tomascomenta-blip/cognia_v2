"""
cognia/agents/daemon.py — Phase 25

AgentDaemon: lógica autónoma del agent runtime integrable en cognia_idle.py.

Comportamiento:
  IDLE (usuario inactivo):
    1. Procesa TaskQueue pendientes (max TIME_BUDGET_SECONDS por tick)
    2. Si no hay tareas → deja que cognia_idle haga su ciclo normal

  ACTIVE (usuario activo):
    tick() retorna inmediatamente sin hacer nada

  Throttling por fatiga:
    fatigue >= PAUSE_THRESHOLD (90) → no tick
    fatigue >= SLOW_THRESHOLD  (70) → tick cada SLOW_INTERVAL segundos
    fatigue <  SLOW_THRESHOLD       → tick cada NORMAL_INTERVAL segundos

  FS Watcher:
    Detecta cambios en archivos .py del directorio actual.
    Al detectar cambio → encola tarea "analiza el archivo <path>".
    Usa polling si watchdog no está disponible.
"""

from __future__ import annotations

import os
import time
import threading
from pathlib import Path
from typing import Optional

from cognia.agents.supervisor import CogniaAgentRuntime, AGENTS_DB_PATH

# ── Umbrales de fatiga (0-100) ────────────────────────────────────────────────
PAUSE_THRESHOLD  = 90.0   # pausar el daemon completamente
SLOW_THRESHOLD   = 70.0   # reducir frecuencia

NORMAL_INTERVAL  = 10     # segundos entre ticks en condiciones normales
SLOW_INTERVAL    = 60     # segundos entre ticks cuando hay fatiga alta

# ── FS Watcher ────────────────────────────────────────────────────────────────
FS_POLL_INTERVAL = 5.0    # segundos entre comprobaciones de cambios de archivos
_WATCH_EXTENSIONS = {".py", ".json", ".yaml", ".yml"}


class AgentDaemon:
    """
    Wrapper del CogniaAgentRuntime para integración síncrona con cognia_idle.py.

    Uso en cognia_idle.py:
        daemon = AgentDaemon()
        daemon.start_fs_watcher(".")   # opcional
        # en idle_watchdog:
        daemon.tick(fatigue_score=cognia.fatigue_monitor.score)
    """

    def __init__(
        self,
        db_path: str = AGENTS_DB_PATH,
        episodic_memory=None,
        vector_cache=None,
        orchestrator=None,
    ) -> None:
        self._runtime = CogniaAgentRuntime(
            db_path=db_path,
            episodic_memory=episodic_memory,
            vector_cache=vector_cache,
            orchestrator=orchestrator,
        )
        self._last_tick:       float = 0.0
        self._watcher_thread:  Optional[threading.Thread] = None
        self._watcher_stop:    threading.Event = threading.Event()
        self._lock = threading.Lock()

    # ── Tick público ─────────────────────────────────────────────────────────

    def tick(self, fatigue_score: float = 0.0, user_active: bool = False) -> Optional[str]:
        """
        Procesa una tarea pendiente si las condiciones lo permiten.

        Args:
            fatigue_score: score de fatiga actual (0-100)
            user_active:   True si el usuario está activo (no hacer nada)

        Returns:
            task_id procesado o None
        """
        if user_active:
            return None

        if fatigue_score >= PAUSE_THRESHOLD:
            return None

        interval = SLOW_INTERVAL if fatigue_score >= SLOW_THRESHOLD else NORMAL_INTERVAL
        now = time.monotonic()
        if now - self._last_tick < interval:
            return None

        with self._lock:
            self._last_tick = now
            if self._runtime.pending() == 0:
                return None
            return self._runtime.tick()

    # ── Submit ────────────────────────────────────────────────────────────────

    def submit(self, description: str, priority: float = 0.0) -> str:
        return self._runtime.submit(description, priority=priority)

    def pending(self) -> int:
        return self._runtime.pending()

    def status(self, task_id: str):
        return self._runtime.status(task_id)

    # ── FS Watcher ────────────────────────────────────────────────────────────

    def start_fs_watcher(self, watch_path: str = ".") -> None:
        """
        Inicia el FS watcher en un hilo daemon.
        Al detectar cambios en archivos relevantes encola una tarea de análisis.
        """
        if self._watcher_thread is not None:
            return
        self._watcher_stop.clear()
        self._watcher_thread = threading.Thread(
            target=self._fs_watch_loop,
            args=(watch_path,),
            daemon=True,
            name="agent-fs-watcher",
        )
        self._watcher_thread.start()

    def stop_fs_watcher(self) -> None:
        self._watcher_stop.set()
        if self._watcher_thread:
            self._watcher_thread.join(timeout=FS_POLL_INTERVAL + 1)
            self._watcher_thread = None

    def _fs_watch_loop(self, watch_path: str) -> None:
        """
        Polling loop: registra mtimes de archivos relevantes.
        Al detectar cambio encola tarea de análisis (deduplica por path).
        """
        snapshots: dict[str, float] = {}
        pending_tasks: set[str] = set()   # paths ya encolados (evita flood)

        while not self._watcher_stop.is_set():
            try:
                current = _snapshot(watch_path)
                for path, mtime in current.items():
                    if path in pending_tasks:
                        continue
                    if path in snapshots and snapshots[path] != mtime:
                        # Archivo modificado → encolar análisis
                        self.submit(f"analiza el archivo {path}", priority=0.5)
                        pending_tasks.add(path)
                snapshots = current
            except Exception:
                pass
            self._watcher_stop.wait(FS_POLL_INTERVAL)

        # Al salir: limpiar pending_tasks para que próximos cambios se detecten
        pending_tasks.clear()


def _snapshot(root: str) -> dict[str, float]:
    """Retorna {path: mtime} para todos los archivos relevantes bajo root (no recursivo profundo)."""
    result: dict[str, float] = {}
    root_path = Path(root)
    if not root_path.is_dir():
        return result
    try:
        for entry in root_path.iterdir():
            if entry.is_file() and entry.suffix in _WATCH_EXTENSIONS:
                try:
                    result[str(entry)] = entry.stat().st_mtime
                except OSError:
                    pass
    except OSError:
        pass
    return result


# ── Integración con fatiga_cognitiva.py ──────────────────────────────────────

def get_fatigue_score(cognia_instance) -> float:
    """
    Extrae el score de fatiga de una instancia de Cognia.
    Retorna 0.0 si el monitor no está disponible.
    """
    try:
        monitor = getattr(cognia_instance, "fatigue_monitor", None)
        if monitor is not None:
            return float(monitor.score)
    except Exception:
        pass
    return 0.0
