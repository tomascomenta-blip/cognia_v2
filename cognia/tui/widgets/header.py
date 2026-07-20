"""
header.py -- Barra superior propia de la TUI.

Que: muestra "Cognia" (marca) a la izquierda y las metricas de sistema reales
(CPU/RAM/DISK + GPU honesta) a la derecha, via el widget SystemMetrics.

Por que: el Header nativo de Textual no expone un area de metricas a la derecha
con color por valor. Este widget solo compone la marca y delega las metricas en
SystemMetrics (cognia/tui/widgets/metrics.py), que lee psutil en vivo.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static

from .metrics import SystemMetrics


class CogniaHeader(Horizontal):
    """Barra superior: marca a la izquierda, metricas de sistema a la derecha."""

    def compose(self) -> ComposeResult:
        yield Static("Cognia", id="brand")
        yield SystemMetrics(id="metrics")
