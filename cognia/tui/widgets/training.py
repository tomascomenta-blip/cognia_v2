"""
training.py -- Dashboard de entrenamiento de la TUI de Cognia.

Que: TrainingDashboard muestra el estado de una corrida de entreno -- cabecera
con nombre + badge de estado coloreado, tiles de metricas (epoch / step / tok-s /
loss / lr / batch / eta / vram), dos ProgressBar (epoch y step) y las metricas de
sistema reales (SystemMetrics, reutilizado, no reimplementado). Cuando no hay
corrida (status 'idle') muestra un empty-state claro en lugar de una pantalla
vacia.

Por que: la fuente del progreso es un archivo (lo escribe el harness de la
FASE 2); aca solo se lee por polling no-bloqueante (timer de 1s) y la UI se
re-renderiza SOLO cuando el progreso cambia (reactive con comparacion por
igualdad). Asi la vista queda lista para metricas en vivo sin acoplarse al
entrenador ni bloquear el hilo de la UI.

VRAM honesta: si vram_pct es None se muestra '--' (nunca un numero inventado),
igual que SystemMetrics hace con la GPU.

Convencion: codigo ASCII; los textos de UI pueden ir en UTF-8.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widgets import ProgressBar, Static

from ..theme import COLORS
from ..training_monitor import (
    TrainingMonitor,
    default_progress,
    format_count,
    format_eta,
    normalize_progress,
)
from .metrics import SystemMetrics

# Estado -> (etiqueta visible, clave de color de la paleta) para el badge.
_STATUS_BADGE: Dict[str, Tuple[str, str]] = {
    "idle": ("inactivo", "muted"),
    "running": ("en curso", "info"),
    "done": ("completado", "ok"),
    "error": ("error", "err"),
}

# Ancho fijo de cada tile y tiles por fila (ancho estable -> sin flicker).
_TILE_W = 18
_TILES_PER_ROW = 4


class TrainingDashboard(Vertical):
    """Vista de entrenamiento: cabecera + tiles + barras + metricas, o empty-state."""

    # El progreso completo vive en un reactive: al reasignarlo, watch_progress
    # re-renderiza SOLO si cambio (dicts iguales no disparan el watcher).
    progress: reactive[Dict[str, Any]] = reactive(default_progress, always_update=False)

    def __init__(self, monitor: Optional[TrainingMonitor] = None) -> None:
        super().__init__(id="entrenamiento", classes="view")
        self.border_title = "Entrenamiento"
        # Fuente del progreso (archivo JSON). Inyectable en tests.
        self.monitor = monitor if monitor is not None else TrainingMonitor()

    def compose(self) -> ComposeResult:
        yield Static("", id="train-header")
        yield Static(self._build_empty(), id="train-empty", classes="empty-state")
        with Vertical(id="train-body"):
            yield Static("", id="train-tiles")
            yield ProgressBar(total=100, show_eta=False, id="train-epoch-bar")
            yield ProgressBar(total=100, show_eta=False, id="train-step-bar")
            yield SystemMetrics(id="train-sysmetrics")

    def on_mount(self) -> None:
        # Pinta el estado inicial (con los hijos ya montados) y arranca el poll
        # liviano. read() es barato; el timer no bloquea el hilo de la UI.
        self._apply_progress(self.progress)
        self.set_interval(1.0, self._poll)

    # -- polling no-bloqueante --------------------------------------------

    def _poll(self) -> None:
        """Lee el progreso del archivo (barato) y lo aplica SOLO si cambio."""
        new = self.monitor.read()
        if new != self.progress:
            self.progress = new  # dispara watch_progress -> _render

    def set_progress(self, raw: Dict[str, Any]) -> None:
        """Inyecta un progreso (tests/demo). Normaliza y dispara el re-render."""
        self.progress = normalize_progress(raw)

    def watch_progress(self, progress: Dict[str, Any]) -> None:
        self._apply_progress(progress)

    # -- lectura para tests ------------------------------------------------

    def dashboard_text(self) -> str:
        """Texto plano visible (cabecera + empty-state + tiles) para asserts."""
        parts: List[str] = []
        for sel in ("#train-header", "#train-empty", "#train-tiles"):
            try:
                parts.append(self.query_one(sel, Static).render().plain)
            except NoMatches:
                pass
        return "\n".join(parts)

    # -- render ------------------------------------------------------------

    def _apply_progress(self, progress: Dict[str, Any]) -> None:
        """Actualiza cabecera, empty-state/body, tiles y barras segun progreso.

        Defensivo: si se llama antes de que los hijos esten montados (p.ej. el
        primer disparo del reactive durante el mount), las queries fallan y se
        ignora -- on_mount vuelve a pintar con los hijos ya presentes.
        """
        try:
            header = self.query_one("#train-header", Static)
            empty = self.query_one("#train-empty", Static)
            body = self.query_one("#train-body", Vertical)
            tiles = self.query_one("#train-tiles", Static)
            epoch_bar = self.query_one("#train-epoch-bar", ProgressBar)
            step_bar = self.query_one("#train-step-bar", ProgressBar)
        except NoMatches:
            return

        is_idle = progress.get("status") == "idle"
        # Empty-state vs body: exactamente uno visible (jamas pantalla vacia).
        empty.set_class(not is_idle, "hidden")
        body.set_class(is_idle, "hidden")

        header.update(self._build_header(progress))
        if is_idle:
            return

        tiles.update(self._build_tiles(progress))
        self._update_bar(epoch_bar, progress.get("epoch"), progress.get("total_epochs"))
        self._update_bar(step_bar, progress.get("step"), progress.get("total_steps"))

    @staticmethod
    def _update_bar(bar: ProgressBar, value: Any, total: Any) -> None:
        """Setea total/progress de una ProgressBar (total<=0 -> indeterminada)."""
        try:
            total_f = float(total) if total else 0.0
            value_f = float(value) if value else 0.0
        except (TypeError, ValueError):
            total_f, value_f = 0.0, 0.0
        if total_f > 0:
            bar.update(total=total_f, progress=min(value_f, total_f))
        else:
            bar.update(total=None)

    # -- renderables (Rich Text con la paleta semantica) -------------------

    def _build_header(self, progress: Dict[str, Any]) -> Text:
        status = str(progress.get("status", "idle"))
        label, color_key = _STATUS_BADGE.get(status, _STATUS_BADGE["idle"])
        run_name = str(progress.get("run_name") or "").strip()
        out = Text(no_wrap=True)
        out.append(run_name if run_name else "sin nombre", style=f"bold {COLORS['text']}")
        out.append("   ")
        out.append(f"[ {label} ]", style=f"bold {COLORS[color_key]}")
        return out

    def _build_tiles(self, progress: Dict[str, Any]) -> Text:
        tiles = [
            ("EPOCH", f"{self._int(progress.get('epoch'))}/{self._int(progress.get('total_epochs'))}"),
            ("STEP", f"{format_count(progress.get('step'))}/{format_count(progress.get('total_steps'))}"),
            ("TOK/S", self._num(progress.get("tokens_per_s"), 1)),
            ("LOSS", self._num(progress.get("loss"), 4, g=True)),
            ("LR", self._sci(progress.get("lr"))),
            ("BATCH", format_count(progress.get("batch_size"))),
            ("ETA", format_eta(progress.get("eta_s"))),
            ("VRAM", self._pct(progress.get("vram_pct"))),
        ]
        return self._tiles_grid(tiles)

    @staticmethod
    def _tiles_grid(tiles: List[Tuple[str, str]]) -> Text:
        out = Text(no_wrap=True)
        for i, (label, value) in enumerate(tiles):
            cell = Text()
            cell.append(f"{label} ", style=COLORS["muted"])
            cell.append(value, style=f"bold {COLORS['text']}")
            pad = max(2, _TILE_W - len(cell.plain))
            cell.append(" " * pad)
            out.append_text(cell)
            if (i + 1) % _TILES_PER_ROW == 0 and (i + 1) < len(tiles):
                out.append("\n")
        return out

    # Formatters honestos: None / invalido -> '--' (nunca inventan numeros).
    @staticmethod
    def _int(v: Any) -> str:
        try:
            return str(int(v))
        except (TypeError, ValueError):
            return "--"

    @staticmethod
    def _num(v: Any, prec: int, g: bool = False) -> str:
        if v is None:
            return "--"
        try:
            return f"{float(v):.{prec}g}" if g else f"{float(v):.{prec}f}"
        except (TypeError, ValueError):
            return "--"

    @staticmethod
    def _sci(v: Any) -> str:
        if v is None:
            return "--"
        try:
            return f"{float(v):.1e}"
        except (TypeError, ValueError):
            return "--"

    @staticmethod
    def _pct(v: Any) -> str:
        if v is None:
            return "--"
        try:
            return f"{float(v):.0f}%"
        except (TypeError, ValueError):
            return "--"

    @staticmethod
    def _build_empty() -> Text:
        out = Text(justify="center")
        out.append("[ ^ ]\n\n", style=f"bold {COLORS['accent']}")
        out.append("Sin entrenamiento activo\n", style=f"bold {COLORS['text']}")
        out.append(
            "Inicia una corrida (FASE 2) y las metricas apareceran aqui en vivo.",
            style=COLORS["muted"],
        )
        return out
