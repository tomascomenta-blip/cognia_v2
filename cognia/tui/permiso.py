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


class PantallaPermiso(ModalScreen[str]):
    """TRES opciones sobre la vista. El default es NO, igual que en consola.

    Devuelve "una" / "siempre" / "no" (antes: un bool). El tercero es la
    VALVULA (2026-08-25): con solo Si/No, la unica forma que tenia el dueno de
    dejar de contestar lo mismo cuarenta veces era el modo bypass — o sea que la
    fatiga de confirmaciones terminaba APAGANDO el gate, que es como se
    perdieron 3 capturas. Quien graba la regla es el llamador
    (cli._permiso_en_vista): esta pantalla no toca disco.
    `lo_aprobado` es el patron NORMALIZADO que quedaria guardado, y se ENSENA:
    puede ser mas ancho que el comando que se esta viendo."""

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
        ("s", "responder('una')", "Si, una vez"),
        ("y", "responder('una')", "Si, una vez"),
        ("a", "responder('siempre')", "Siempre en este proyecto"),
        ("n", "responder('no')", "No"),
        ("escape", "responder('no')", "No"),
        ("enter", "responder('no')", "No (default)"),
    ]

    def __init__(self, kind: str, detalle: str, lo_aprobado: str = "") -> None:
        super().__init__()
        self._kind = kind or "accion"
        self._detalle = detalle or ""
        self._lo_aprobado = lo_aprobado or ""

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(f"PERMISO · {self._kind}", classes="titulo",
                         markup=False)
            # markup=False: el detalle es un comando del usuario y puede traer
            # corchetes; con markup, rich se lo come o revienta el parser.
            yield Static(self._detalle[:400], markup=False)
            if self._lo_aprobado:
                yield Static(f"siempre = {self._lo_aprobado}", classes="pista",
                             markup=False)
            yield Static("s = una vez · a = siempre en este proyecto · "
                         "n / esc / enter = NO", classes="pista", markup=False)

    def action_responder(self, valor) -> None:
        """Acepta "una"/"siempre"/"no" y tambien el bool de antes.

        El bool sigue valiendo porque hay quien llama a `action_responder(True)`
        para simular la tecla (tests/test_cli_permiso_desde_hilo): romper esa
        firma cambiaria el contrato por un detalle de tipos, no por politica."""
        if isinstance(valor, bool):
            valor = "una" if valor else "no"
        valor = str(valor or "no")
        self.dismiss(valor if valor in ("una", "siempre", "no") else "no")
