"""
widgets -- Componentes reutilizables de la TUI de Cognia.

Cada widget vive en su propio archivo y se exporta aca para imports cortos:
    from cognia.tui.widgets import CogniaHeader, Sidebar, MainView, StatusBar, LogsPanel
"""

from .header import CogniaHeader
from .logspanel import LogsPanel
from .mainview import VIEWS, MainView
from .sidebar import Sidebar, view_key_from_item
from .statusbar import StatusBar

__all__ = [
    "CogniaHeader",
    "LogsPanel",
    "MainView",
    "VIEWS",
    "Sidebar",
    "view_key_from_item",
    "StatusBar",
]
