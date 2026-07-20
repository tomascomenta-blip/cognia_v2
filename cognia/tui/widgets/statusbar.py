"""
statusbar.py -- Barra de estado inferior.

Que: una franja con el estado actual a la izquierda (p.ej. "Listo") y el
contexto a la derecha (p.ej. la seccion activa). Se actualiza via set_status().

Por que: dar feedback persistente de "que esta haciendo el sistema" y "donde
estoy" sin robar espacio del area principal. El Footer nativo (atajos) va debajo.
"""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

from ..theme import COLORS


class StatusBar(Static):
    """Estado a la izquierda, contexto a la derecha."""

    def __init__(self) -> None:
        super().__init__(id="statusbar")
        # Nombres con sufijo _text: evitan colisionar con atributos internos del
        # MessagePump de Textual (p.ej. self._context, que es un context manager).
        self._status_text = "Listo"
        self._context_text = ""

    def on_mount(self) -> None:
        self._refresh()

    def set_status(self, status: str | None = None, context: str | None = None) -> None:
        """Actualiza estado y/o contexto; lo que sea None se conserva."""
        if status is not None:
            self._status_text = status
        if context is not None:
            self._context_text = context
        self._refresh()

    def _refresh(self) -> None:
        text = Text(no_wrap=True)
        text.append(" * ", style=f"bold {COLORS['ok']}")
        text.append(self._status_text, style=COLORS["text"])
        if self._context_text:
            text.append("   |   ", style=COLORS["muted"])
            text.append(self._context_text, style=COLORS["info"])
        self.update(text)
