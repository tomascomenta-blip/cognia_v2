"""
widgets -- Componentes reutilizables de la TUI de Cognia.

Cada widget vive en su propio archivo y se exporta aca para imports cortos:
    from cognia.tui.widgets import CogniaHeader, Sidebar, MainView, StatusBar, LogsPanel
"""

from .header import CogniaHeader
from .logspanel import LogsPanel
from .mainview import VIEWS, MainView
from .memory_view import MemoryView
from .metrics import SystemMetrics
from .modals import ConfirmModal
from .models_view import ModelsView
from .sidebar import Sidebar, view_key_from_item
from .statusbar import StatusBar
from .training import TrainingDashboard

__all__ = [
    "CogniaHeader",
    "ConfirmModal",
    "LogsPanel",
    "MainView",
    "VIEWS",
    "MemoryView",
    "ModelsView",
    "SystemMetrics",
    "Sidebar",
    "view_key_from_item",
    "StatusBar",
    "TrainingDashboard",
]
