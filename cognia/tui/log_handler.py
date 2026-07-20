"""
log_handler.py -- Puente entre el logging de Python y la vista Logs de la TUI.

Que: TuiLogHandler es un logging.Handler que empuja cada LogRecord (formateado y
coloreado por nivel) al LogsPanel de la TUI, para que los logs REALES de Cognia
aparezcan en vivo en la vista "Logs". El nivel del record (levelno) se mapea al
nivel semantico del panel (info/warn/err/muted) que LogsPanel.write ya colorea.

Por que: la TUI no debe re-inventar un sistema de logs ni acoplarse a cada
subsistema. Instalando un handler en el root logger (lo hace app.py en on_mount),
cualquier logging.getLogger(...).info(...) de cognia se ve sin tocar el emisor.

Thread-safety: un log puede emitirse desde CUALQUIER hilo (p.ej. el worker de
inferencia). Tocar widgets de Textual solo es seguro en el hilo de la UI, asi que
si el record viene de otro hilo se reenvia con app.call_from_thread; si viene del
propio hilo de la UI (caso comun) se escribe directo. El id del hilo de la UI se
captura al construir el handler, que app.py crea dentro de on_mount (hilo de UI).

Robustez: emit() esta envuelto en try/except -- un fallo al loguear (panel aun no
montado, app cerrandose, loop detenido) NUNCA debe tumbar la app ni el logging.

Convencion: codigo ASCII; los textos de UI pueden ir en UTF-8.
"""

from __future__ import annotations

import logging
import threading


def _panel_level(levelno: int) -> str:
    """Mapea el levelno de logging al nivel semantico del LogsPanel.

    ERROR/CRITICAL -> err, WARNING -> warn, INFO -> info, DEBUG (y menores) -> muted.
    """
    if levelno >= logging.ERROR:
        return "err"
    if levelno >= logging.WARNING:
        return "warn"
    if levelno >= logging.INFO:
        return "info"
    return "muted"


class TuiLogHandler(logging.Handler):
    """logging.Handler que vuelca los logs al LogsPanel (#logs) de la TUI."""

    def __init__(self, app, panel_id: str = "#logs", level: int = logging.INFO) -> None:
        super().__init__(level)
        self._app = app
        self._panel_id = panel_id
        # Capturado en el hilo donde se construye el handler: app.py lo crea en
        # on_mount, que corre en el hilo de la UI -> este es el id de ese hilo.
        self._ui_thread_id = threading.get_ident()

    def emit(self, record: logging.LogRecord) -> None:
        """Formatea el record y lo escribe en el panel (directo o cross-thread).

        Nunca levanta: cualquier fallo (panel ausente, app cerrada, loop parado)
        se traga -- loguear jamas debe romper la TUI.
        """
        try:
            msg = self._format_record(record)
            level = _panel_level(record.levelno)
            if threading.get_ident() == self._ui_thread_id:
                self._write(msg, level)
            else:
                # Otro hilo (worker): el unico punto seguro para tocar widgets.
                self._app.call_from_thread(self._write, msg, level)
        except Exception:
            # Best-effort: ni la TUI ni el logger se caen por un log perdido.
            pass

    @staticmethod
    def _format_record(record: logging.LogRecord) -> str:
        """Texto de una linea: '<logger>: <mensaje>' (sin el 'root' por ruido)."""
        msg = record.getMessage()
        name = record.name
        if name and name != "root":
            return f"{name}: {msg}"
        return msg

    def _write(self, msg: str, level: str) -> None:
        """Corre en el hilo de la UI: ubica el panel y escribe la linea coloreada."""
        try:
            panel = self._app.query_one(self._panel_id)
        except Exception:
            return  # panel aun no montado o app sin ese id -> se ignora la linea
        panel.write(msg, level)
