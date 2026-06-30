"""
training_monitor.py -- Lectura no-bloqueante del progreso de entrenamiento.

Que: TrainingMonitor lee un JSON de progreso (que el harness de la FASE 2
escribira) desde una ruta conocida y lo normaliza a un esquema estable. Si el
archivo no existe o no parsea, devuelve un progreso 'idle' SIN levantar
excepcion -- el dashboard interpreta 'idle' como su empty-state.

Por que: la TUI no debe bloquear ni romperse por el estado del entrenamiento.
La lectura es barata (un JSON chico) y se hace por polling desde un timer; el
parseo defensivo evita que un archivo a medio escribir tumbe la UI.

Esquema de progreso (dict): status ('idle'|'running'|'done'|'error'), run_name,
epoch, total_epochs, step, total_steps, tokens_per_s, loss, lr, batch_size,
eta_s, vram_pct, started_at, updated_at.

Convencion: codigo ASCII; los textos de UI pueden ir en UTF-8.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Union

# Estados validos de una corrida. Cualquier otro valor degrada a 'idle'.
_VALID_STATUS = ("idle", "running", "done", "error")

# Esquema con sus defaults. read()/normalize devuelven SIEMPRE un dict con estas
# claves, para que el dashboard no tenga que chequear presencia campo a campo.
_DEFAULT_PROGRESS: Dict[str, Any] = {
    "status": "idle",
    "run_name": "",
    "epoch": 0,
    "total_epochs": 0,
    "step": 0,
    "total_steps": 0,
    "tokens_per_s": None,
    "loss": None,
    "lr": None,
    "batch_size": None,
    "eta_s": None,
    "vram_pct": None,
    "started_at": None,
    "updated_at": None,
}

# Ruta por defecto del archivo de progreso (el harness de entreno lo escribe).
# <repo>/cognia_x/training_progress.json -- el repo es parents[2] de este modulo
# (cognia/tui/training_monitor.py -> cognia/tui -> cognia -> <repo>).
_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROGRESS_PATH = _REPO_ROOT / "cognia_x" / "training_progress.json"


def default_progress() -> Dict[str, Any]:
    """Copia fresca del progreso 'idle' (no compartir el dict mutable)."""
    return dict(_DEFAULT_PROGRESS)


def normalize_progress(raw: Any) -> Dict[str, Any]:
    """Mezcla `raw` sobre los defaults y sanea el status.

    Acepta dicts parciales (claves faltantes -> default). Un `raw` que no es
    dict, o un status desconocido, degradan a 'idle' de forma segura.
    """
    out = dict(_DEFAULT_PROGRESS)
    if isinstance(raw, dict):
        for key in out:
            if key in raw:
                out[key] = raw[key]
    if out.get("status") not in _VALID_STATUS:
        out["status"] = "idle"
    return out


class TrainingMonitor:
    """Lee y normaliza el progreso de entrenamiento desde un JSON (pura/sin estado)."""

    def __init__(self, path: Optional[Union[str, Path]] = None) -> None:
        self.path = Path(path) if path is not None else DEFAULT_PROGRESS_PATH

    def read(self) -> Dict[str, Any]:
        """Progreso normalizado del archivo, o 'idle' si falta / no parsea.

        Nunca levanta: cualquier error de IO o de JSON cae a 'idle'.
        """
        try:
            text = self.path.read_text(encoding="utf-8")
        except (OSError, ValueError):
            return default_progress()
        try:
            data = json.loads(text)
        except (ValueError, TypeError):
            return default_progress()
        return normalize_progress(data)


def format_eta(seconds: Optional[float]) -> str:
    """ETA legible: None/negativo/invalido -> '--'; '45s' / '12m 30s' / '1h 23m'."""
    if seconds is None:
        return "--"
    try:
        s = int(seconds)
    except (TypeError, ValueError):
        return "--"
    if s < 0:
        return "--"
    if s < 60:
        return f"{s}s"
    if s < 3600:
        m, sec = divmod(s, 60)
        return f"{m}m {sec}s" if sec else f"{m}m"
    h, rem = divmod(s, 3600)
    m = rem // 60
    return f"{h}h {m}m" if m else f"{h}h"


def format_count(n: Optional[float]) -> str:
    """Entero con separador de miles ('1,200'); None/invalido -> '--'."""
    if n is None:
        return "--"
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return "--"
