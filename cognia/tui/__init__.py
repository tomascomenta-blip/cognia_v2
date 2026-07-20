"""
cognia.tui -- Interfaz de terminal (TUI) profesional de Cognia, sobre Textual.

Frontend NUEVO y paralelo: NO reemplaza ni modifica cognia/cli.py (el CLI viejo
sigue existiendo). Esta es la fundacion (design system + layout por componentes);
el chat, las metricas y las pantallas reales se cablean en checkpoints siguientes.

Uso:
    python -m cognia.tui      # arranca la TUI
    from cognia.tui import CogniaTUI
    CogniaTUI().run()
"""

from .app import CogniaTUI

__all__ = ["CogniaTUI"]
