"""
app.py -- Aplicacion Textual de Cognia (CogniaTUI).

Que: arma el layout (header / sidebar | mainview / statusbar + footer), registra
el tema de Cognia, conecta el sidebar con el ContentSwitcher para una navegacion
100% por teclado, y suma la capa de UX: paleta de comandos (ctrl+p), toasts
(notify_ok/info/warn/err), modales de confirmacion (confirm) para acciones
destructivas y la ayuda completa de atajos.

Por que: un unico punto que ensambla los componentes reutilizables de
cognia/tui/widgets/ y define los atajos. No duplica logica de las vistas; solo
orquesta foco, navegacion, notificaciones y confirmaciones.

Nota: este es un frontend NUEVO y paralelo. NO reemplaza ni toca cognia/cli.py.

2026-08-17 (tercera pasada del juicio visual) -- dos cosas de esta capa:
  * los modales de confirmacion pasan el NOMBRE de la accion ("Salir",
    "Limpiar") en vez de un "Si" generico;
  * la paleta de comandos deja de estar medio en ingles: get_system_commands()
    se reimplementa entera en espanol y el buscador lleva su placeholder. Lo que
    la libreria no deja traducir esta declarado en el comentario de esa seccion.
"""

from __future__ import annotations

import logging

from typing import Iterable

from textual import on, work
from textual.app import App, ComposeResult, SystemCommand
from textual.binding import Binding
from textual.command import CommandPalette
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Footer

from ..logger_config import restaurar_consola, silenciar_consola
from .commands import CogniaCommands
from .log_handler import TuiLogHandler
from .theme import COGNIA_THEME_NAME, cognia_theme
from .widgets import CogniaHeader, ConfirmModal, MainView, Sidebar, StatusBar
from .widgets.chat import ChatView
from .widgets.mainview import VIEWS
from .widgets.sidebar import view_key_from_item

# Titulo visible de cada vista, por clave (para el status bar y los toasts).
_TITLES: dict[str, str] = {key: title for key, title, _icon in VIEWS}


class CogniaTUI(App):
    """TUI de Cognia: navegacion por teclado + paleta/toasts/modales/ayuda."""

    CSS_PATH = "app.tcss"
    TITLE = "Cognia"

    # Paleta de comandos: la nativa de Textual (system commands) + las de Cognia.
    COMMANDS = App.COMMANDS | {CogniaCommands}

    BINDINGS = [
        Binding("q", "request_quit", "Salir"),
        Binding("question_mark", "help", "Ayuda"),
        Binding("ctrl+l", "clear_chat", "Limpiar chat"),
        # Paleta de comandos: ctrl+p (nativo, lo re-declaramos explicito porque
        # agregar el bind ":" suprime el default que Textual pone solo) y ":".
        Binding("ctrl+p", "command_palette", "Comandos", show=False),
        Binding("colon", "command_palette", "Comandos", show=False),
        Binding("tab", "focus_next", "Panel sig.", show=False),
        Binding("shift+tab", "focus_previous", "Panel ant.", show=False),
    ]
    # Teclas 1..N -> ir directo a cada vista (ocultas del footer para no saturar).
    BINDINGS += [
        Binding(str(i + 1), f"show_view('{key}')", title, show=False)
        for i, (key, title, _icon) in enumerate(VIEWS)
    ]

    # Vista activa actual; se inicializa al boot para no notificar el primer sync.
    _current_view_key: str = VIEWS[0][0]

    def compose(self) -> ComposeResult:
        yield CogniaHeader(id="header")
        with Horizontal(id="body"):
            yield Sidebar()
            yield MainView()
        yield StatusBar()
        yield Footer()

    # Handler de logging instalado en los loggers de la app (vista Logs en vivo).
    _log_handler: TuiLogHandler | None = None
    _prev_root_level: int | None = None
    # Nivel que tenia el handler de CONSOLA antes de callarlo mientras la TUI
    # es duena de la pantalla (None = no se callo). Ver _install_log_handler.
    _prev_consola_level: int | None = None
    # Se instala en el root (libs/genericos) Y en "cognia" (su logger usa
    # propagate=False en logger_config.py: sus logs NO llegan al root, asi que hay
    # que enganchar tambien ahi para ver los logs REALES de Cognia en la vista).
    _LOG_TARGETS: tuple[str, ...] = ("", "cognia")

    def get_theme_variable_defaults(self) -> dict[str, str]:
        """Valores por defecto de las variables PROPIAS del tema de Cognia.

        app.tcss se parsea en el arranque, ANTES de que on_mount registre el
        tema: en ese primer parseo solo existen las variables del tema default
        de Textual, asi que un `$selection-background` propio abortaba la app
        con UnresolvedVariableError. Textual expone este hook justamente para
        eso y hace `{**defaults, **variables_del_tema_activo}`, o sea que el
        tema vivo sigue mandando; esto solo evita el agujero del primer parseo.
        """
        return dict(cognia_theme().variables)

    def on_mount(self) -> None:
        self.register_theme(cognia_theme())
        self.theme = COGNIA_THEME_NAME
        self.query_one(Sidebar).focus()
        self._current_view_key = VIEWS[0][0]
        self._sync_context(VIEWS[0][0])
        self._install_log_handler()

    def on_unmount(self) -> None:
        self._remove_log_handler()

    # --- Logging en vivo: root logger -> LogsPanel (vista Logs) ----------------

    def _install_log_handler(self) -> None:
        """Conecta los loggers de la app al LogsPanel para ver logs reales en vivo.

        Se ejecuta en on_mount (hilo de la UI), asi el handler captura el id de
        ese hilo para distinguir logs de la UI (escritura directa) de logs de un
        worker (call_from_thread). Engancha el MISMO handler al root (libs) y al
        logger "cognia" (propagate=False -> no llega al root). Baja el nivel del
        root a INFO si estaba mas alto (default WARNING) y guarda el previo.
        """
        try:
            root = logging.getLogger()
            self._prev_root_level = root.level
            if root.level == logging.NOTSET or root.level > logging.INFO:
                root.setLevel(logging.INFO)
            self._log_handler = TuiLogHandler(self, level=logging.INFO)
            for name in self._LOG_TARGETS:
                logger = logging.getLogger(name) if name else root
                # Higiene: sacar handlers de la TUI de apps previas (tests secuenciales).
                for h in list(logger.handlers):
                    if isinstance(h, TuiLogHandler):
                        logger.removeHandler(h)
                logger.addHandler(self._log_handler)
        except Exception:
            self._log_handler = None  # best-effort: la TUI funciona sin logs en vivo

        # El handler de CONSOLA de logger_config se quedo con el objeto stderr
        # REAL en el import (StreamHandler(sys.stderr)), asi que Textual no lo
        # intercepta: un WARNING escribe ANSI crudo ENCIMA de la pantalla
        # alterna. Se calla mientras la TUI manda. Solo si el panel quedo
        # instalado: si _install fallo, la consola es la unica salida visible y
        # callarla seria cambiar un log feo por ningun log.
        if self._log_handler is not None:
            self._prev_consola_level = silenciar_consola()

    def _remove_log_handler(self) -> None:
        """Quita el handler de todos los loggers y restaura el nivel del root."""
        try:
            if self._log_handler is not None:
                for name in self._LOG_TARGETS:
                    logging.getLogger(name).removeHandler(self._log_handler)
                self._log_handler = None
            if self._prev_root_level is not None:
                logging.getLogger().setLevel(self._prev_root_level)
                self._prev_root_level = None
            # La consola vuelve a hablar: ya no hay pantalla alterna que ensuciar.
            restaurar_consola(self._prev_consola_level)
            self._prev_consola_level = None
        except Exception:
            pass

    # --- Navegacion: sidebar -> ContentSwitcher -------------------------------

    @on(Sidebar.Highlighted)
    def _on_highlight(self, event: Sidebar.Highlighted) -> None:
        item_id = event.item.id if event.item else None
        key = view_key_from_item(item_id)
        if not key:
            return
        self.query_one(MainView).current = key
        self._sync_context(key)
        # Toast solo cuando la vista REALMENTE cambia (no en el sync del boot).
        if key != self._current_view_key:
            self._current_view_key = key
            self.notify_info(f"Vista: {_TITLES.get(key, key)}")

    def action_show_view(self, key: str) -> None:
        """Salta a una vista por su clave moviendo el cursor del sidebar."""
        sidebar = self.query_one(Sidebar)
        for index, (vkey, _title, _icon) in enumerate(VIEWS):
            if vkey == key:
                sidebar.index = index
                break

    def action_help(self) -> None:
        self.action_show_view("ayuda")

    def _sync_context(self, key: str) -> None:
        self.query_one(StatusBar).set_status(context=_TITLES.get(key, ""))

    # --- Paleta de comandos EN ESPANOL ----------------------------------------
    #
    # La paleta mezclaba los comandos de Cognia (en espanol, los pone
    # commands.CogniaCommands) con los de Textual EN INGLES: "Keys", "Quit",
    # "Theme", "Screenshot", "Show help for the focused widget and a summary of
    # available keys". No son literales de una libreria congelada: salen de
    # App.get_system_commands(), que existe justamente para reimplementarla.
    #
    # Lo que SI se puede traducir (todo lo de aca abajo): los cinco/seis
    # comandos del sistema con su ayuda, y el placeholder del buscador
    # ("Search for commands…" / "Search for themes…", que se pasan al construir
    # CommandPalette).
    #
    # Lo que NO se puede, y queda en ingles a proposito porque taparlo seria
    # peor que declararlo:
    #   * "No matches found" -- literal hardcodeado dentro de
    #     CommandPalette._start_no_matches_countdown (textual/command.py); no hay
    #     hook, solo se cambiaria monkeypatcheando la clase;
    #   * los NOMBRES de los temas que lista "Tema" ("cognia", "textual-dark",
    #     "nord", ...): son identificadores registrados en Textual, no etiquetas.
    #     El de Cognia se llama "cognia" y es el unico que la app usa.

    def get_system_commands(self, screen: Screen) -> Iterable[SystemCommand]:
        """Comandos del sistema de Textual, en espanol (reemplaza al original).

        Se reimplementa entera en vez de traducir sobre `super()`: los
        SystemCommand son tuplas inmutables y filtrar por su titulo en ingles
        seria un acoplamiento peor. La logica condicional (panel de ayuda ya
        abierto, widget maximizable) es la misma que la de Textual 8.x.
        """
        yield SystemCommand("Tema", "Cambiar el tema de la interfaz",
                            self.action_change_theme)
        # El "Quit" del sistema NO se traduce: se ELIMINA. Cierra sin preguntar,
        # y la paleta ya ofrece el "Salir" de Cognia (CogniaCommands), que pasa
        # por el ConfirmModal. Tenerlos a los dos dejaba dos entradas con el
        # mismo nombre y distinto comportamiento.
        if screen.query("HelpPanel"):
            yield SystemCommand("Teclas", "Ocultar el panel de teclas y ayuda",
                                self.action_hide_help_panel)
        else:
            yield SystemCommand(
                "Teclas",
                "Mostrar la ayuda del widget enfocado y las teclas disponibles",
                self.action_show_help_panel,
            )
        if screen.maximized is not None:
            yield SystemCommand("Restaurar", "Devolver el panel a su tamano normal",
                                screen.action_minimize)
        elif screen.focused is not None and screen.focused.allow_maximize:
            yield SystemCommand("Maximizar", "Agrandar el panel enfocado a toda la pantalla",
                                screen.action_maximize)
        yield SystemCommand("Captura de pantalla",
                            "Guardar un SVG con lo que se ve ahora",
                            lambda: self.set_timer(0.1, self.deliver_screenshot))

    def action_command_palette(self) -> None:
        """Abre la paleta con el buscador en espanol (el default es ingles)."""
        if self.use_command_palette and not CommandPalette.is_open(self):
            self.push_screen(CommandPalette(id="--command-palette",
                                            placeholder="Buscar comandos..."))

    def search_themes(self) -> None:
        """Lista de temas con el buscador en espanol.

        Los NOMBRES de los temas siguen siendo los identificadores registrados
        en Textual ("cognia", "textual-dark", ...): eso no es traducible.
        """
        from textual.theme import ThemeProvider

        self.push_screen(CommandPalette(providers=[ThemeProvider],
                                        placeholder="Buscar temas..."))

    # --- Acciones con confirmacion (workers: no bloquean el loop) -------------

    @work
    async def action_request_quit(self) -> None:
        """Salir con confirmacion: 'q' no cierra directo, pregunta primero."""
        if await self.confirm("Seguro que quieres salir de Cognia?", confirmar="Salir"):
            self.exit()

    @work
    async def action_clear_chat(self) -> None:
        """Limpiar el chat con confirmacion; notifica al completar."""
        if await self.confirm("Limpiar la conversacion actual?", confirmar="Limpiar"):
            self.query_one(ChatView).clear()
            self.notify_ok("Chat limpiado")

    async def confirm(self, question: str, confirmar: str = "Si") -> bool:
        """Muestra un ConfirmModal y espera la respuesta (True=si, False=no).

        `confirmar` es la etiqueta del boton que confirma: se pasa el NOMBRE de
        la accion ("Salir", "Limpiar") para que el boton diga que va a pasar en
        vez de un "Si" que obliga a releer la pregunta.

        push_screen_wait corre el modal en el loop async sin congelar la UI; debe
        invocarse desde un worker (por eso las acciones que confirman son @work).
        """
        return await self.push_screen_wait(ConfirmModal(question, confirmar=confirmar))

    # --- Toasts (notify) con severidad semantica ------------------------------

    def notify_ok(self, message: str, title: str = "Listo") -> None:
        """Exito. Textual no tiene toast 'success': usa severidad informativa."""
        self.notify(message, title=title, severity="information")

    def notify_info(self, message: str, title: str = "Info") -> None:
        """Informativo (azul)."""
        self.notify(message, title=title, severity="information")

    def notify_warn(self, message: str, title: str = "Atencion") -> None:
        """Advertencia (amarillo)."""
        self.notify(message, title=title, severity="warning")

    def notify_err(self, message: str, title: str = "Error") -> None:
        """Error (rojo)."""
        self.notify(message, title=title, severity="error")
