"""
sidebar.py -- Menu lateral de navegacion.

Que: ListView con un item por seccion de VIEWS (Chat, Entrenamiento, Memoria,
Modelos, Logs, Ayuda). Navegable 100% por teclado: flechas y j/k mueven el
cursor; el item resaltado dispara el cambio de vista en el ContentSwitcher.

Por que: un unico componente focalizable que es la fuente de la navegacion. El
id de cada item (nav-<clave>) mapea 1:1 con el id de la vista, de modo que la App
puede traducir highlighted -> ContentSwitcher.current sin tablas extra.
"""

from __future__ import annotations

from textual.binding import Binding
from textual.widgets import Label, ListItem, ListView

from .mainview import VIEWS

# Prefijo del id de cada item del menu. La clave de la vista va despues.
ITEM_PREFIX = "nav-"


def view_key_from_item(item_id: str | None) -> str | None:
    """Traduce el id de un ListItem (nav-<clave>) a la clave de la vista."""
    if item_id and item_id.startswith(ITEM_PREFIX):
        return item_id[len(ITEM_PREFIX):]
    return None


class Sidebar(ListView):
    """Menu lateral; j/k y flechas mueven el cursor."""

    BINDINGS = [
        Binding("j", "cursor_down", "Bajar", show=False),
        Binding("k", "cursor_up", "Subir", show=False),
    ]

    def __init__(self) -> None:
        items = [
            ListItem(Label(f"{icon}  {title}"), id=f"{ITEM_PREFIX}{key}")
            for key, title, icon in VIEWS
        ]
        super().__init__(*items, id="sidebar", initial_index=0)
        self.border_title = "Menu"
