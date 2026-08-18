"""
cognia.tui -- Interfaz de terminal (TUI) profesional de Cognia, sobre Textual.

Frontend NUEVO y paralelo: NO reemplaza ni modifica cognia/cli.py (el CLI viejo
sigue existiendo). Esta es la fundacion (design system + layout por componentes);
el chat, las metricas y las pantallas reales se cablean en checkpoints siguientes.

Uso:
    python -m cognia.tui      # arranca la TUI
    from cognia.tui import CogniaTUI
    CogniaTUI().run()

Por que CogniaTUI se importa PEREZOSO (PEP 562)
-----------------------------------------------
Antes este modulo hacia `from .app import CogniaTUI` en el cuerpo. Consecuencia
MEDIDA en un venv limpio con el wheel instalado y sin textual: `python -m
cognia.tui` moria con el ModuleNotFoundError crudo de `from textual import on,
work` ANTES de ejecutar una sola linea de __main__.py, porque importar el
submodulo __main__ obliga a importar el paquete primero. O sea: el mensaje de
ayuda de __main__.py era codigo MUERTO, imposible de alcanzar. Con __getattr__
el paquete importa sin textual, el error salta donde hay quien lo explique, y
`from cognia.tui import CogniaTUI` sigue funcionando igual. De paso, importar
`cognia.tui.puente` (el puente de eventos, que corre fuera de la TUI) ya no
arrastra la App entera.
"""

__all__ = ["CogniaTUI"]


def __getattr__(name: str):
    if name == "CogniaTUI":
        from .app import CogniaTUI
        return CogniaTUI
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(list(globals()) + __all__)
