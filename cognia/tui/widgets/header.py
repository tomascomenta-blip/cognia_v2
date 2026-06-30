"""
header.py -- Barra superior propia de la TUI.

Que: muestra "Cognia" (marca) a la izquierda y los indicadores de sistema
(CPU/RAM/DISK) a la derecha, coloreados por la semantica de la paleta.

Por que: el Header nativo de Textual no expone un area de metricas a la derecha
con control de color por valor. Este widget es el lugar donde, en el proximo
checkpoint, se cablearan las metricas reales (psutil). Por ahora son placeholder
("--") con color muted para dejar claro que aun no hay datos.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static

from ..theme import COLORS


class CogniaHeader(Horizontal):
    """Barra superior: marca a la izquierda, metricas de sistema a la derecha."""

    def compose(self) -> ComposeResult:
        yield Static("Cognia", id="brand")
        yield Static(self._render_metrics(), id="metrics")

    def update_metrics(self, cpu: str = "--", ram: str = "--", disk: str = "--") -> None:
        """Refresca los indicadores. Placeholder hasta cablear psutil real."""
        self.query_one("#metrics", Static).update(self._render_metrics(cpu, ram, disk))

    def _render_metrics(self, cpu: str = "--", ram: str = "--", disk: str = "--") -> Text:
        text = Text(no_wrap=True)
        for label, value in (("CPU", cpu), ("RAM", ram), ("DISK", disk)):
            text.append(f"{label} ", style=COLORS["muted"])
            text.append(value, style=self._value_style(value))
            text.append("   ")
        return text

    @staticmethod
    def _value_style(value: str) -> str:
        """Color por umbral; placeholder ('--') queda muted."""
        if value == "--":
            return COLORS["muted"]
        try:
            pct = float(value.rstrip("%"))
        except ValueError:
            return COLORS["text"]
        if pct >= 90:
            return COLORS["err"]
        if pct >= 70:
            return COLORS["warn"]
        return COLORS["ok"]
