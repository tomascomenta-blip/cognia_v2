"""
theme.py -- Sistema de diseno (paleta semantica) de la TUI de Cognia.

Que: define COLORS, la paleta semantica de toda la interfaz (hex), y construye
a partir de ella un textual.theme.Theme registrable en la App. Asi la misma
fuente de verdad alimenta tanto el codigo Python (logs, empty-states,
indicadores del header) como el CSS (app.tcss via variables $primary, $success,
etc.). Tambien expone helpers que usan esa paleta: level_color (color por nivel
de log) y empty_state (el renderable uniforme de los empty-states de las vistas).

Por que: evitar que los colores se dupliquen y diverjan entre Python y el .tcss.

2026-08-17 -- COLORS ya no declara sus propios hex: los toma de
cognia/ux/paleta.py, la unica fuente de verdad del color del producto (la misma
que alimenta los tres temas del CLI, el marco verde del prompt y el gradiente
del banner). El accent pasa de violeta (#a371f7) a VERDE por decision del
dueno: la TUI hereda el verde del REPL, porque con dos identidades distintas
abrir la pantalla de agentes parecia entrar en otra aplicacion.

2026-08-17 (segunda pasada, sobre el render medido) -- el tema deja de delegar
en las DERIVACIONES de Textual tres cosas que salian mal en esta base oscura:

  * la PISTA de los scrollbars, que Textual calcula como background-darken-1 y
    con este fondo (#0d1117) daba #000000 puro: el color mas oscuro de la
    pantalla dentro de un panel claro, 27 celdas que se leen como un agujero.
    Ahora es `border`, el mismo gris estructural de la pista de las barras de
    progreso, y el pulgar sube de 2.67:1 a 5.69:1 contra ella.
  * el CURSOR BORROSO de bloque (block-cursor-blurred-*), que era el acento al
    30% y sobre el panel daba un oliva turbio. Ahora es la misma banda gris que
    usa el resto de la seleccion.
  * las variables de SELECCION (selection-*), que no existen en Textual: son el
    idioma unico de "seleccionado" que consumen el menu, las tablas y el
    OptionList de la paleta de comandos desde app.tcss.

Nota de arranque: estas variables PROPIAS solo existen cuando el tema esta
registrado, y app.tcss se parsea antes de eso. CogniaTUI las publica en
get_theme_variable_defaults() para que el primer parseo no reviente.

Convencion: los nombres y el codigo son ASCII puro; los valores son hex. Los
textos de UI (renderizados por Textual en UTF-8) pueden llevar acentos.
"""

from __future__ import annotations

from rich.text import Text
from textual.theme import Theme

from cognia.ux import paleta

# Paleta semantica. Base oscura estilo "terminal pro" (GitHub-dark-ish), con el
# verde de Cognia como color de identidad (accent). Todo derivado de paleta.py.
COLORS: dict[str, str] = {
    "bg": paleta.SUPERFICIE["fondo"],            # fondo de la app
    "panel": paleta.SUPERFICIE["panel"],         # fondo de paneles
    "panel_alt": paleta.SUPERFICIE["panel_alt"], # fondo alternativo / item activo
    "border": paleta.SUPERFICIE["borde"],        # bordes de paneles
    "text": paleta.SEMANTICO["texto"],           # texto primario
    "muted": paleta.SEMANTICO["detalle"],        # texto secundario / placeholder
    "accent": paleta.ACENTO_HEX,                 # identidad Cognia (verde)
    "ok": paleta.SEMANTICO["ok"],                # verde -- exito / saludable
    "info": paleta.SEMANTICO["info"],            # azul -- informativo
    "warn": paleta.SEMANTICO["aviso"],           # amarillo -- advertencia
    "err": paleta.SEMANTICO["error"],            # rojo -- error / critico
    # Roles de INTERFAZ (no de contenido), agregados 2026-08-17:
    "sel": paleta.SUPERFICIE["borde"],           # fondo de "seleccionado" (fila tenue)
    "scroll": paleta.VERDE["estado"],            # pulgar de scrollbar en reposo
    "scroll_hover": paleta.VERDE["marco"],       # pulgar bajo el puntero
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


def empty_state(icon: str, message: str, hint: str) -> Text:
    """Renderable centrado y uniforme de un empty-state: icono (accent) + mensaje
    (bold) + pista (muted). Fuente unica del look de los empty-states de todas las
    vistas (chat / memoria / modelos / entrenamiento) para que no se dupliquen."""
    text = Text(justify="center")
    text.append(f"{icon}\n\n", style=f"bold {COLORS['accent']}")
    text.append(f"{message}\n", style=f"bold {COLORS['text']}")
    text.append(hint, style=COLORS["muted"])
    return text


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
            # -- Scrollbars -------------------------------------------------
            # Textual deriva la PISTA de `background-darken-1` y con este fondo
            # (#0d1117) eso da #000000 PURO: 27 celdas de negro absoluto en el
            # panel de logs, lo mas oscuro de toda la pantalla, que se lee como
            # un agujero y no como un control. Se fija a `border`, el mismo gris
            # estructural con el que ya se dibuja la pista de las barras de
            # progreso: la ranura queda POR ENCIMA del panel, no por debajo de
            # todo. El pulgar en reposo es el verde apagado de la barra de estado
            # (5.69:1 contra la pista, contra 2.67:1 del derivado #325C10) y
            # escala a marco -> acento con hover y arrastre.
            "scrollbar-background": COLORS["border"],
            "scrollbar-background-hover": COLORS["border"],
            "scrollbar-background-active": COLORS["border"],
            "scrollbar-corner-color": COLORS["border"],
            "scrollbar": COLORS["scroll"],
            "scrollbar-hover": COLORS["scroll_hover"],
            "scrollbar-active": COLORS["accent"],
            # -- UN solo idioma de "seleccionado" ---------------------------
            # Decision 2026-08-17: la seleccion es FILA TENUE + TEXTO CLARO, no
            # bloque de neon. El bloque de acento (block-cursor-background, que
            # sigue siendo el verde) tapa el color semantico de las celdas: el
            # 'falta' rojo sobre neon da 2.11:1 y sobre la banda oliva del cursor
            # borroso daba 2.58:1. Sobre esta banda gris da 3.64:1 y el verde de
            # 'ok', el azul y el amarillo siguen leyendose (>=4.8:1). El foco no
            # se pierde: lo marca el borde del panel, y el texto del item pasa de
            # blanco a acento cuando el widget tiene el foco.
            "selection-background": COLORS["sel"],
            "selection-foreground": COLORS["accent"],
            "selection-foreground-blurred": COLORS["text"],
            # Lo que NO se sobreescribe por CSS (OptionList de la paleta de
            # comandos, Select, ...) cae en el cursor borroso: mismo idioma.
            "block-cursor-blurred-background": COLORS["sel"],
            "block-cursor-blurred-foreground": COLORS["text"],
            "block-cursor-blurred-text-style": "bold",
        },
    )
