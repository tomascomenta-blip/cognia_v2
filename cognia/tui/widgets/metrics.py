"""
metrics.py -- Indicador de metricas de sistema REALES y en vivo.

Que: SystemMetrics, un widget reutilizable que lee CPU / RAM / disco con psutil y
los refresca cada segundo, coloreando cada valor por umbral con la paleta
semantica (theme.COLORS). GPU/VRAM con empty-state HONESTO: si no hay GPU local
(o no esta pynvml) muestra "GPU --" en muted; NUNCA inventa numeros.

Por que: el header necesita metricas vivas sin bloquear la UI. psutil.cpu_percent
con interval=None es no-bloqueante (la 1a lectura da 0.0 y se corrige al 2do
tick). Los valores viven en reactive(): el re-render ocurre solo cuando un valor
cambia, y el ancho fijo (%3.0f) evita que el layout salte (anti-flickering).

snapshot() expone los valores actuales como dict para reusarlos en el dashboard
de entrenamiento (checkpoint futuro) sin re-leer el hardware.

Convencion: codigo ASCII; los textos de UI (%, etiquetas) pueden ir en UTF-8.
"""

from __future__ import annotations

from pathlib import Path

import psutil
from rich.text import Text
from textual.reactive import reactive
from textual.widgets import Static

from ..theme import COLORS

# Raiz del volumen donde vive el codigo (en Windows = la unidad, p.ej. "D:\\";
# en POSIX = "/"). Se usa para medir el uso de disco del drive del repo.
_DISK_ROOT = Path(__file__).resolve().anchor or "/"

# Umbrales de uso (% ) -> clave de color semantico.
_WARN_AT = 60.0
_ERR_AT = 85.0


def threshold_color(pct: float) -> str:
    """Clave semantica de color (ok/warn/err) por umbral de uso.

    <60% -> ok (verde), 60-85% -> warn (amarillo), >85% -> err (rojo).
    Devuelve la CLAVE; el hex se resuelve con COLORS al renderizar.
    """
    if pct > _ERR_AT:
        return "err"
    if pct >= _WARN_AT:
        return "warn"
    return "ok"


# --- GPU: deteccion honesta, una sola vez (no inventar numeros) --------------
_gpu_probe: tuple | None = None  # (modulo pynvml, handle) si hay GPU
_gpu_checked = False


def _gpu_percent() -> float | None:
    """Util% de la GPU 0 via pynvml, o None si no hay GPU / pynvml ausente.

    La inicializacion de NVML se intenta UNA vez (cacheada). Cualquier fallo o
    ausencia de pynvml devuelve None -> el header muestra "GPU --" (empty-state).
    """
    global _gpu_probe, _gpu_checked
    if not _gpu_checked:
        _gpu_checked = True
        try:
            import pynvml  # type: ignore

            pynvml.nvmlInit()
            if pynvml.nvmlDeviceGetCount() > 0:
                _gpu_probe = (pynvml, pynvml.nvmlDeviceGetHandleByIndex(0))
        except Exception:
            _gpu_probe = None
    if _gpu_probe is None:
        return None
    pynvml, handle = _gpu_probe
    try:
        return float(pynvml.nvmlDeviceGetUtilizationRates(handle).gpu)
    except Exception:
        return None


class SystemMetrics(Static):
    """CPU / RAM / DISK reales (psutil) + GPU honesta, refresco de 1s."""

    # Redondeados a entero: el display es %3.0f, asi el reactive solo cambia
    # cuando el entero cambia -> re-render minimo, sin flicker.
    cpu: reactive[float] = reactive(0.0)
    ram: reactive[float] = reactive(0.0)
    disk: reactive[float] = reactive(0.0)
    gpu: reactive[float | None] = reactive(None)

    def on_mount(self) -> None:
        # Cebar cpu_percent: la 1a llamada con interval=None devuelve 0.0; a
        # partir de aca cada lectura es el % desde la lectura previa (no bloquea).
        psutil.cpu_percent(interval=None)
        self.refresh_metrics()
        self.set_interval(1.0, self.refresh_metrics)

    def refresh_metrics(self) -> None:
        """Lee el hardware (barato) y actualiza los reactive (tick de 1s)."""
        self.cpu = float(round(psutil.cpu_percent(interval=None)))
        self.ram = float(round(psutil.virtual_memory().percent))
        self.disk = float(round(psutil.disk_usage(_DISK_ROOT).percent))
        self.gpu = _gpu_percent()

    def snapshot(self) -> dict:
        """Valores actuales (cpu/ram/disk float 0..100; gpu float o None)."""
        return {"cpu": self.cpu, "ram": self.ram, "disk": self.disk, "gpu": self.gpu}

    def render(self) -> Text:
        text = Text(no_wrap=True)
        for label, value in (("CPU", self.cpu), ("RAM", self.ram), ("DISK", self.disk)):
            text.append(f"{label} ", style=COLORS["muted"])
            text.append(f"{value:3.0f}%", style=COLORS[threshold_color(value)])
            text.append("  ")
        text.append("GPU ", style=COLORS["muted"])
        if self.gpu is None:
            text.append("--", style=COLORS["muted"])
        else:
            text.append(f"{self.gpu:3.0f}%", style=COLORS[threshold_color(self.gpu)])
        return text
