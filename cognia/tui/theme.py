"""
theme.py -- Sistema de diseno (paleta semantica) de la TUI de Cognia.

Que: define COLORS, la paleta semantica unica de toda la interfaz (hex), y
construye a partir de ella un textual.theme.Theme registrable en la App. Asi la
misma fuente de verdad alimenta tanto el codigo Python (markup de logs, indicadores
del header) como el CSS (app.tcss via variables $primary, $success, etc.).

Por que: evitar que los colores se dupliquen y diverjan entre Python y el .tcss.
Cambiar un hex aca cambia toda la TUI de forma consistente.

Convencion: los nombres y el codigo son ASCII puro; los valores son hex. Los
textos de UI (renderizados por Textual en UTF-8) pueden llevar acentos.
"""

from __future__ import annotations

from textual.theme import Theme

# Paleta semantica. Base oscura estilo "terminal pro" (GitHub-dark-ish), con un
# violeta como color de identidad de Cognia (accent).
COLORS: dict[str, str] = {
    "bg": "#0d1117",        # fondo de la app
    "panel": "#161b22",     # fondo de paneles
    "panel_alt": "#1c2330", # fondo alternativo / item activo
    "border": "#30363d",    # bordes de paneles
    "text": "#e6edf3",      # texto primario
    "muted": "#8b949e",     # texto secundario / placeholder
    "accent": "#a371f7",    # identidad Cognia (violeta)
    "ok": "#3fb950",        # verde -- exito / saludable
    "info": "#58a6ff",      # azul -- informativo
    "warn": "#d29922",      # amarillo -- advertencia
    "err": "#f85149",       # rojo -- error / critico
}

# Nivel de log -> color semantico. Usado por LogsPanel.write(msg, level).
_LEVEL_TO_KEY: dict[str, str] = {
    "ok": "ok",
    "info": "info",
    "warn": "warn",
    "warning": "warn",
    "err": "err",
    "error": "err",
    "muted": "muted",
    "debug": "muted",
}

COGNIA_THEME_NAME = "cognia"


def level_color(level: str) -> str:
    """Devuelve el hex semantico para un nivel de log (ok/info/warn/err/muted)."""
    return COLORS[_LEVEL_TO_KEY.get(level.lower(), "info")]


def markup(text: str, color: str) -> str:
    """Envuelve `text` en markup de Rich con `color` (hex o clave de COLORS)."""
    hex_color = COLORS.get(color, color)
    return f"[{hex_color}]{text}[/]"


def cognia_theme() -> Theme:
    """Construye el Theme de Textual a partir de COLORS (fuente de verdad unica)."""
    return Theme(
        name=COGNIA_THEME_NAME,
        primary=COLORS["accent"],
        secondary=COLORS["info"],
        accent=COLORS["accent"],
        success=COLORS["ok"],
        warning=COLORS["warn"],
        error=COLORS["err"],
        foreground=COLORS["text"],
        background=COLORS["bg"],
        surface=COLORS["panel"],
        panel=COLORS["panel_alt"],
        dark=True,
        variables={
            "border": COLORS["border"],
            "text-muted": COLORS["muted"],
            "footer-key-foreground": COLORS["accent"],
        },
    )
