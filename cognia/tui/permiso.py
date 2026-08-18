"""
cognia/tui/permiso.py
=====================
El gate de permisos, preguntado DENTRO de la vista de agentes.

POR QUE EXISTE (medido, spike T4, ConPTY, 2026-08-18): con una App de Textual
abierta, el selector de prompt_toolkit (cognia/ux/selector.py) llamado desde el
hilo de la corrida NO VUELVE NUNCA — su dibujo se va al _PrintCapture de
Textual (que lo descarta) y sus teclas se las lleva el driver de Textual. El
agente quedaba colgado, mudo, sosteniendo una tool a medias, y el usuario no
tenia forma de enterarse.

La via que SI funciona (misma medicion): el hilo postea esta pantalla con
``app.call_from_thread(app.push_screen, PantallaPermiso(...), callback)`` y se
bloquea en un ``threading.Event`` -> respuesta True en 1.229,5 ms, App sana y
modos de consola 503/7 al salir.

Se usa push_screen CON CALLBACK y no push_screen_wait: el wait exige un worker
de Textual (lanza NoActiveWorker si no lo hay) y quien pregunta es un
``threading.Thread`` pelado.

Convencion del repo: comentarios en espanol SIN acentos; solo stdlib+textual.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static


class PantallaPermiso(ModalScreen[bool]):
    """Si/No sobre la vista. El default es NO, igual que el gate de consola."""

    DEFAULT_CSS = """
    PantallaPermiso {
        align: center middle;
    }
    PantallaPermiso > Vertical {
        width: 70%;
        max-width: 90;
        height: auto;
        border: round $warning;
        background: $surface;
        padding: 1 2;
    }
    PantallaPermiso .titulo { color: $warning; text-style: bold; }
    PantallaPermiso .pista  { color: $text-muted; }
    """

    BINDINGS = [
        ("s", "responder(True)", "Si"),
        ("y", "responder(True)", "Si"),
        ("n", "responder(False)", "No"),
        ("escape", "responder(False)", "No"),
        ("enter", "responder(False)", "No (default)"),
    ]

    def __init__(self, kind: str, detalle: str) -> None:
        super().__init__()
        self._kind = kind or "accion"
        self._detalle = detalle or ""

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(f"PERMISO · {self._kind}", classes="titulo",
                         markup=False)
            # markup=False: el detalle es un comando del usuario y puede traer
            # corchetes; con markup, rich se lo come o revienta el parser.
            yield Static(self._detalle[:400], markup=False)
            yield Static("s = ejecutar · n / esc / enter = NO", classes="pista",
                         markup=False)

    def action_responder(self, valor: bool) -> None:
        self.dismiss(bool(valor))
