"""
cognia/scale_manager.py
=======================
ScaleManager â€” Fase 5: Escalado DinÃ¡mico.

Detecta el nivel de operaciÃ³n Ã³ptimo en runtime segÃºn:
  - RAM disponible del sistema
  - Cantidad de memorias episÃ³dicas activas en la DB
  - Peers activos en la red mesh (si Fase 3 estÃ¡ disponible)

NIVELES:
  1 â€” LOCAL PURO      (<4GB RAM  o  <100 memorias)
      Modelo: llama3.2:3b-q4_K_M  |  timeout 60s
  2 â€” SEMI-DISTRIBUIDO (4-12GB RAM  y  100-10.000 memorias)
      Modelo: llama3.2:8b-q4_K_M  |  timeout 90s
  3 â€” RED COMPLETA    (>12GB RAM  y  >10.000 memorias)
      Modelo: mixtral:8x7b-q3_K   |  timeout 120s

Funciona en Windows (no usa os.uname, no usa /proc directamente).
Sin dependencias externas: usa psutil si disponible, sino fallback
a ctypes (Windows) o /proc/meminfo (Linux/Mac).

RESTRICCIONES:
  - No modifica la DB ni el modelo activo directamente (solo informa).
  - Retrocompatible: model_router.py lo consulta opcionalmente.
  - El hilo watch() es daemon â€” muere solo cuando el proceso principal muere.
"""

from __future__ import annotations

import os
import sys
import time
import threading
from dataclasses import dataclass, field
from typing import Optional

from logger_config import get_logger

logger = get_logger(__name__)


@dataclass
class LevelConfig:
    level: int
    name: str
    model: str
    timeout_s: int
    ram_min_gb: float
    ram_max_gb: float
    mem_min: int
    mem_max: int
    peers_min: int

LEVEL_CONFIGS: list[LevelConfig] = [
    LevelConfig(
        level=1, name="LOCAL PURO",
        model=os.environ.get("COGNIA_MODEL_L1", "llama3.2:3b-q4_K_M"),
        timeout_s=60,
        ram_min_gb=0, ram_max_gb=4.0,
        mem_min=0, mem_max=100,
        peers_min=0,
    ),
    LevelConfig(
        level=2, name="SEMI-DISTRIBUIDO",
        model=os.environ.get("COGNIA_MODEL_L2", "llama3.2:8b-q4_K_M"),
        timeout_s=90,
        ram_min_gb=4.0, ram_max_gb=12.0,
        mem_min=100, mem_max=10_000,
        peers_min=0,
    ),
    LevelConfig(
        level=3, name="RED COMPLETA",
        model=os.environ.get("COGNIA_MODEL_L3", "mixtral:8x7b-q3_K"),
        timeout_s=120,
        ram_min_gb=12.0, ram_max_gb=-1,
        mem_min=10_000, mem_max=-1,
        peers_min=0,
    ),
]


def _get_available_ram_gb() -> float:
    """Retorna RAM disponible en GB. Funciona en Windows, Linux y macOS."""
    try:
        import psutil
        return psutil.virtual_memory().available / (1024 ** 3)
    except ImportError:
        pass

    if sys.platform == "win32":
        try:
            import ctypes
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(stat)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return stat.ullAvailPhys / (1024 ** 3)
        except Exception:
            pass

    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    kb = int(line.split()[1])
                    return kb / (1024 ** 2)
    except Exception:
        pass

    logger.warning("ScaleManager: no se pudo detectar RAM -- asumiendo 2GB")
    return 2.0


class ScaleManager:
    """Detecta el nivel optimo de operacion y expone modelo/timeout recomendados."""

    def __init__(self, db_path: Optional[str] = None, watch_interval: int = 60):
        self._db_path = db_path
        self._watch_interval = watch_interval
        self._current_level: int = 1
        self._lock = threading.Lock()
        self._watcher: Optional[threading.Thread] = None
        self._hit_counts: dict[int, int] = {1: 0, 2: 0, 3: 0}
        self._current_level = self.detect_level()

    def detect_level(self) -> int:
        ram_gb    = _get_available_ram_gb()
        mem_count = self._count_memories()
        peers     = self._count_peers()
        level     = self._compute_level(ram_gb, mem_count, peers)
        with self._lock:
            self._current_level = level
            self._hit_counts[level] = self._hit_counts.get(level, 0) + 1
        logger.info(
            "ScaleManager: nivel=%d | RAM=%.1fGB | memorias=%d | peers=%d",
            level, ram_gb, mem_count, peers,
        )
        return level

    def _compute_level(self, ram_gb: float, mem_count: int, peers: int) -> int:
        if ram_gb >= 12.0 and mem_count >= 10_000:
            return 3
        if ram_gb >= 4.0 and mem_count >= 100:
            return 2
        return 1

    def _count_memories(self) -> int:
        if not self._db_path or not os.path.exists(self._db_path):
            return 0
        try:
            import sqlite3
            with sqlite3.connect(self._db_path, timeout=3) as conn:
                cur = conn.execute(
                    "SELECT COUNT(*) FROM episodic_memory WHERE forgotten = 0"
                )
                row = cur.fetchone()
                return row[0] if row else 0
        except Exception:
            return 0

    def _count_peers(self) -> int:
        try:
            from network.mesh_node import get_active_peers
            return get_active_peers()
        except Exception:
            return 0

    @property
    def level(self) -> int:
        with self._lock:
            return self._current_level

    def get_config(self) -> LevelConfig:
        return LEVEL_CONFIGS[self.level - 1]

    def select_model(self) -> str:
        return self.get_config().model

    def get_timeout(self) -> int:
        return self.get_config().timeout_s

    def status(self) -> dict:
        cfg = self.get_config()
        return {
            "level":      cfg.level,
            "name":       cfg.name,
            "model":      cfg.model,
            "timeout_s":  cfg.timeout_s,
            "ram_gb":     round(_get_available_ram_gb(), 2),
            "memories":   self._count_memories(),
            "peers":      self._count_peers(),
            "hit_counts": dict(self._hit_counts),
        }

    def watch(self) -> None:
        if self._watcher and self._watcher.is_alive():
            return
        self._watcher = threading.Thread(
            target=self._watch_loop,
            name="ScaleManager-watcher",
            daemon=True,
        )
        self._watcher.start()
        logger.info("ScaleManager: watcher iniciado (intervalo=%ds)", self._watch_interval)

    def _watch_loop(self) -> None:
        while True:
            time.sleep(self._watch_interval)
            try:
                old = self._current_level
                new = self.detect_level()
                if new != old:
                    logger.info("ScaleManager: nivel cambio %d -> %d", old, new)
            except Exception as exc:
                logger.warning("ScaleManager watcher error: %s", exc)


_instance: Optional[ScaleManager] = None
_instance_lock = threading.Lock()


def get_scale_manager(db_path: Optional[str] = None) -> ScaleManager:
    """Retorna la instancia singleton de ScaleManager."""
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = ScaleManager(db_path=db_path)
            _instance.watch()
        return _instance
