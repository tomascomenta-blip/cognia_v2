"""
cognia_x/lcd/history.py — undo/redo por escena (snapshots de la escena LCD).

Pila de snapshots JSON (via scene.to_json(); Scene.from_json() los reconstruye
al volver), no diffs: simple, determinista, y barato porque las escenas son
chicas. push(scene) registra `scene` como el nuevo checkpoint "actual" (asi el
tope de la pila SIEMPRE es el ultimo estado conocido) y limpia el redo_stack
(convencion estandar: un cambio nuevo invalida el redo previo). undo() saca el
checkpoint actual, lo guarda para poder rehacer, y devuelve el que queda
arriba (el anterior); redo() hace el camino inverso.
"""
from __future__ import annotations

from cognia_x.lcd.scene import Scene

DEFAULT_MAX = 30


class SceneHistory:
    """undo_stack/redo_stack de strings JSON (via scene.to_json()). El tope de
    undo_stack representa el checkpoint mas reciente empujado (el 'actual')."""

    def __init__(self, max_snapshots: int = DEFAULT_MAX):
        self.max_snapshots = max_snapshots
        self.undo_stack: list = []
        self.redo_stack: list = []

    def push(self, scene: Scene) -> None:
        """Registra `scene` como nuevo checkpoint. Descarta el snapshot mas
        viejo si se pasa el tope; limpia el redo_stack (rehacer ya no aplica)."""
        self.undo_stack.append(scene.to_json())
        if len(self.undo_stack) > self.max_snapshots:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def undo(self):
        """Descarta el checkpoint actual (tope) y devuelve el anterior (Scene).
        None si no hay un estado previo al que volver (pila vacia o con un
        unico checkpoint -- no hay 'antes' de el)."""
        if len(self.undo_stack) < 2:
            return None
        current = self.undo_stack.pop()
        self.redo_stack.append(current)
        return Scene.from_json(self.undo_stack[-1])

    def redo(self):
        """Reaplica el ultimo checkpoint deshecho. None si no hay nada que
        rehacer (redo_stack vacio, p.ej. tras un push nuevo)."""
        if not self.redo_stack:
            return None
        nxt = self.redo_stack.pop()
        self.undo_stack.append(nxt)
        return Scene.from_json(nxt)

    def __len__(self) -> int:
        return len(self.undo_stack)
