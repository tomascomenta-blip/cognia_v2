"""
commands.py -- Paleta de comandos de la TUI de Cognia (ctrl+p).

Que: CogniaCommands es un Provider de Textual que ofrece las acciones de Cognia
como comandos buscables: ir a cada vista, limpiar el chat y salir. `discover()`
las lista todas al abrir la paleta (sin texto); `search(query)` filtra con el
matcher difuso nativo y resalta la coincidencia. Cada comando dispara un metodo
de la App (action_show_view, action_clear_chat, action_request_quit, ...).

Por que: la paleta es la forma idiomatica de Textual 8.x de exponer acciones sin
saturar el footer ni inventar menus propios. Una sola fuente de verdad (_COMMANDS)
define nombre/ayuda/callback, asi no se desincroniza de las acciones reales.

Convencion: codigo y nombres ASCII; los textos de comando visibles pueden llevar
acentos. Se registra en la App con `COMMANDS = App.COMMANDS | {CogniaCommands}`.
"""

from __future__ import annotations

from typing import Callable, List, Tuple

from textual.command import DiscoveryHit, Hit, Hits, Provider


class CogniaCommands(Provider):
    """Provider de la paleta: comandos de navegacion y acciones de Cognia."""

    def _commands(self) -> List[Tuple[str, str, Callable[[], None]]]:
        """Arma (nombre, ayuda, callback) ligando los metodos de la App.

        Cada callback llama una accion real de CogniaTUI, de modo que la paleta
        comparte el comportamiento (y la confirmacion) de los atajos de teclado.
        """
        app = self.app
        return [
            ("Ir a Chat", "Abrir la vista de conversacion",
             lambda: app.action_show_view("chat")),
            ("Ir a Entrenamiento", "Abrir el dashboard de entrenamiento",
             lambda: app.action_show_view("entrenamiento")),
            ("Ir a Memoria", "Abrir la vista de memoria",
             lambda: app.action_show_view("memoria")),
            ("Ir a Modelos", "Abrir la vista de modelos",
             lambda: app.action_show_view("modelos")),
            ("Ir a Logs", "Abrir el panel de logs",
             lambda: app.action_show_view("logs")),
            ("Ir a Ayuda", "Mostrar los atajos de teclado",
             lambda: app.action_help()),
            ("Limpiar chat", "Borrar la conversacion actual",
             lambda: app.action_clear_chat()),
            ("Salir", "Cerrar Cognia",
             lambda: app.action_request_quit()),
        ]

    async def discover(self) -> Hits:
        """Lista todos los comandos al abrir la paleta (antes de escribir)."""
        for name, help_text, callback in self._commands():
            yield DiscoveryHit(name, callback, help=help_text)

    async def search(self, query: str) -> Hits:
        """Filtra los comandos por `query` con el matcher difuso de Textual."""
        matcher = self.matcher(query)
        for name, help_text, callback in self._commands():
            score = matcher.match(name)
            if score > 0:
                yield Hit(
                    score,
                    matcher.highlight(name),
                    callback,
                    help=help_text,
                )
