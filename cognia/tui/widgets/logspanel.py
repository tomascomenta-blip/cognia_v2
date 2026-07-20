"""
logspanel.py -- Panel de logs en tiempo real.

Que: RichLog con write(msg, level) que colorea cada linea por nivel
(ok/info/warn/err/muted) usando la paleta semantica y antepone un timestamp.
La firma extiende (no rompe) a RichLog.write: si no se pasa `level`, delega tal cual.

Por que: centralizar el formato de logs de la TUI en un solo lugar. Cualquier
subsistema (chat, training, daemon) escribira aqui sin saber de colores ni de
Rich. app.py conecta el root logger a este panel via TuiLogHandler, asi los logs
REALES de Cognia aparecen en vivo; al boot se siembra una linea de empty-state
("Sin logs todavia") para que el panel nunca arranque vacio.
"""

from __future__ import annotations

import time

from rich.text import Text
from textual.widgets import RichLog

from ..theme import level_color

# Etiqueta corta y fija (4 chars) por nivel, para alinear las columnas.
_LEVEL_TAG: dict[str, str] = {
    "ok": "OK  ",
    "info": "INFO",
    "warn": "WARN",
    "warning": "WARN",
    "err": "ERR ",
    "error": "ERR ",
    "muted": "... ",
    "debug": "DBG ",
}


class LogsPanel(RichLog):
    """Log scrollable y coloreado por nivel."""

    def __init__(self, **kwargs) -> None:
        super().__init__(highlight=False, markup=False, wrap=True, **kwargs)
        self.border_title = "Logs"

    def on_mount(self) -> None:
        self.write("Panel de logs conectado al logger de Cognia.", "info")
        self.write("Sin logs todavia. Los eventos de Cognia apareceran aqui en vivo.", "muted")

    def write(self, content, level=None, *args, **kwargs):
        """Escribe una linea. Con `level` (str) formatea con timestamp + color.

        Convive con la firma nativa de RichLog.write(content, width, expand,
        shrink, scroll_end, ...): su replay de renders diferidos (on_resize) llama
        write() con esos args POSICIONALES, y `width` es int|None. El 2do arg solo
        es un 'nivel' de Cognia cuando es un str -> ese chequeo discrimina ambas
        firmas y evita el crash al mostrar la vista Logs por primera vez.
        """
        if isinstance(level, str) and isinstance(content, str):
            return super().write(self._format_line(content, level), *args, **kwargs)
        return super().write(content, level, *args, **kwargs)

    @staticmethod
    def _format_line(msg: str, level: str) -> Text:
        color = level_color(level)
        tag = _LEVEL_TAG.get(level.lower(), "INFO")
        line = Text(no_wrap=False)
        line.append(time.strftime("%H:%M:%S "), style="dim")
        line.append(f"{tag} ", style=f"bold {color}")
        line.append(msg, style=color)
        return line
