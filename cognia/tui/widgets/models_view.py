"""
models_view.py -- Vista Modelos de la TUI: registry de GGUF + cual esta activo.

Que: ModelsView lista cada modelo del registry canonico
(shattering/model_constants.MODEL_GGUF_REGISTRY) en una tabla navegable por
teclado, mostrando clave, archivo, si EXISTE en disco (ok/falta), tamano si
existe, y cual es el modelo ACTIVO (env LLAMA_GGUF_PATH, o MODEL_GGUF_DEFAULT)
resaltado con un marcador. Al seleccionar una fila (Enter) se marca ese modelo
como activo seteando os.environ['LLAMA_GGUF_PATH'] -- afecta la PROXIMA carga del
backend (no recarga nada en caliente) -- y se avisa con un toast.

Por que: dar visibilidad real del estado de los pesos sin cargar ningun modelo.
La vista solo hace stat() de unos pocos archivos locales (metadata, microsegundos):
NUNCA construye un GGUF ni levanta llama-server, por eso no puede bloquear la UI.
La conmutacion es solo una variable de entorno (barata, reversible, sin tocar
disco): la carga pesada del modelo sigue siendo perezosa en CogniaBackend.

Las constantes salen de shattering/model_constants.py (fuente unica); resolve_gguf_path
se referencia a nivel de modulo para poder mockearla en los tests.

Convencion: codigo ASCII; los textos de UI pueden ir en UTF-8.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import DataTable, Static

from shattering.model_constants import (
    MODEL_GGUF_DEFAULT,
    MODEL_GGUF_REGISTRY,
    resolve_gguf_path,
)
from ..theme import COLORS

# Marcador de la fila activa (ASCII) y etiquetas de estado de existencia.
_ACTIVE_MARK = ">"
_OK = "ok"
_MISSING = "falta"


def _human_size(num_bytes: int) -> str:
    """Tamano legible: '512 B' / '300.0 MB' / '4.4 GB'. Negativo -> '--'."""
    if num_bytes is None or num_bytes < 0:
        return "--"
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024.0 or unit == "TB":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"


def model_rows() -> List[dict]:
    """Una fila por modelo del registry, con existencia/tamano resueltos en disco.

    best-effort: cualquier fallo de stat por modelo degrada a no-existe/tamano '--'
    (jamas levanta). Devuelve dicts {key, path, name, exists, size, active}.
    `active` se computa contra el modelo activo actual (env o default).
    """
    active = active_key()
    rows: List[dict] = []
    for key in MODEL_GGUF_REGISTRY:
        rel = MODEL_GGUF_REGISTRY[key]
        path = resolve_gguf_path(key)
        name = Path(rel).name
        exists, size = False, None
        try:
            if path is not None and path.is_file():
                exists = True
                size = path.stat().st_size
        except OSError:
            exists, size = False, None
        rows.append({
            "key": key,
            "path": path,
            "name": name,
            "exists": exists,
            "size": size,
            "active": key == active,
        })
    return rows


def active_key() -> Optional[str]:
    """Clave del modelo ACTIVO: env LLAMA_GGUF_PATH (matcheado al registry) si
    esta seteada, si no MODEL_GGUF_DEFAULT. Una env apuntando fuera del registry
    devuelve None (modelo personalizado, no listado)."""
    env = os.environ.get("LLAMA_GGUF_PATH")
    if not env:
        return MODEL_GGUF_DEFAULT
    env_name = Path(env).name
    for key in MODEL_GGUF_REGISTRY:
        path = resolve_gguf_path(key)
        if path is None:
            continue
        if str(path) == env or path.name == env_name:
            return key
    return None  # env a un path fuera del registry -> personalizado


class ModelsView(Vertical):
    """Tabla navegable del registry de modelos GGUF, con marca del activo."""

    def __init__(self) -> None:
        super().__init__(id="modelos", classes="view")
        self.border_title = "Modelos"
        # key del modelo por fila (DataTable.RowSelected nos da la row key).
        self._row_keys: List[str] = []

    def compose(self) -> ComposeResult:
        yield Static("", id="models-summary")
        table = DataTable(id="models-table", cursor_type="row", zebra_stripes=True)
        yield table

    def on_mount(self) -> None:
        table = self.query_one("#models-table", DataTable)
        table.add_columns(" ", "Clave", "Archivo", "Estado", "Tamano")
        self.refresh_models()

    # -- carga (stat de archivos locales: liviano, no carga ningun modelo) ----

    def refresh_models(self) -> None:
        """Repuebla la tabla y la cabecera con el estado actual del registry."""
        rows = model_rows()
        active = active_key()
        table = self.query_one("#models-table", DataTable)
        table.clear()
        self._row_keys = []
        for r in rows:
            mark = _ACTIVE_MARK if r["active"] else " "
            estado = self._estado_cell(r["exists"])
            size = _human_size(r["size"]) if r["exists"] else "--"
            name_style = COLORS["text"] if r["exists"] else COLORS["muted"]
            table.add_row(
                Text(mark, style=f"bold {COLORS['accent']}"),
                Text(r["key"], style=f"bold {name_style}"),
                Text(r["name"], style=name_style),
                estado,
                Text(size, style=COLORS["muted"]),
                key=r["key"],
            )
            self._row_keys.append(r["key"])
        self.query_one("#models-summary", Static).update(self._build_summary(rows, active))

    # -- lectura para tests ------------------------------------------------

    def table_text(self) -> str:
        """Texto plano de TODAS las celdas de la tabla (para asserts)."""
        table = self.query_one("#models-table", DataTable)
        parts: List[str] = []
        for i in range(table.row_count):
            for cell in table.get_row_at(i):
                parts.append(cell.plain if hasattr(cell, "plain") else str(cell))
        return " ".join(parts)

    @staticmethod
    def _estado_cell(exists: bool) -> Text:
        if exists:
            return Text(_OK, style=f"bold {COLORS['ok']}")
        return Text(_MISSING, style=f"bold {COLORS['err']}")

    @staticmethod
    def _build_summary(rows: List[dict], active: Optional[str]) -> Text:
        present = sum(1 for r in rows if r["exists"])
        out = Text(no_wrap=True)
        out.append("Modelos GGUF  ", style=f"bold {COLORS['text']}")
        out.append(f"{present}/{len(rows)} en disco", style=COLORS["muted"])
        out.append("   activo: ", style=COLORS["muted"])
        if active is None:
            out.append("personalizado (LLAMA_GGUF_PATH)", style=f"bold {COLORS['warn']}")
        else:
            out.append(active, style=f"bold {COLORS['accent']}")
        return out

    # -- conmutar el activo (solo env var: barato, afecta la PROXIMA carga) ----

    @on(DataTable.RowSelected, "#models-table")
    def _on_row_selected(self, event: DataTable.RowSelected) -> None:
        """Enter sobre una fila: marca ese modelo como activo via env var."""
        key = event.row_key.value if event.row_key is not None else None
        if not key or key not in MODEL_GGUF_REGISTRY:
            return
        path = resolve_gguf_path(key)
        if path is None:
            return
        os.environ["LLAMA_GGUF_PATH"] = str(path)
        self.refresh_models()
        notify = getattr(self.app, "notify_ok", None)
        if callable(notify):
            notify(f"Modelo activo: {key}")
