"""
cognia/cli.py
==============
Interfaz de linea de comandos (REPL) para Cognia v3.
"""

import contextlib
import datetime
import io
import logging
import os
import re
import sys
import time

from .cognia import Cognia
from .config import HAS_RESEARCH_ENGINE, HAS_PROGRAM_CREATOR

# ---------------------------------------------------------------------------
# Optional: rich
# ---------------------------------------------------------------------------
try:
    from rich.console import Console
    from rich.markup import escape as _escape
    from rich.panel import Panel
    from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
    from rich.table import Table
    from rich.text import Text
    from rich.theme import Theme
    _HAS_RICH = True
except ImportError:
    _HAS_RICH = False

# ---------------------------------------------------------------------------
# Optional: prompt_toolkit
# ---------------------------------------------------------------------------
try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.history import InMemoryHistory
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.shortcuts import CompleteStyle
    from prompt_toolkit.styles import Style as PTStyle
    _HAS_PT = True
except ImportError:
    _HAS_PT = False

# ---------------------------------------------------------------------------
# ANSI fallback
# ---------------------------------------------------------------------------
_G = "\033[92m"
_R = "\033[0m"

# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------
_BANNER_RAW = """
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣠⠤⠤⠤⠤⣄⠀⠀⠀⠀⠀⠀⢀⣀⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣶⡊⠉⠉⣉⣱⡷⠶⢢⣠⢴⣶⡝⠒⠉⢉⣭⡽⠟⢉⣀⡀⠹⢭⠒⢤⣀⣀⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⡠⠔⢚⣩⡽⠿⠊⢉⣉⡂⣀⣩⠭⢴⠟⠋⠉⠉⠉⠛⠳⢦⣬⣤⡴⠞⠛⠁⠛⠳⣾⣧⠀⠟⠀⠉⠲⢄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⡠⢚⠁⠀⠰⠋⢡⠄⠀⠞⣫⢟⡥⠒⠉⠹⣿⡀⠀⠀⢦⡀⠀⠀⠀⠈⠻⡧⡀⠀⠀⠀⠀⠈⠻⣗⡶⠶⠶⢤⡀⠱⣄⡀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢮⣤⡾⠀⠀⣠⡴⠋⠀⡠⣚⠥⠒⢛⡲⠄⠀⠈⢻⡆⠀⠀⠻⣦⣀⠀⠀⠀⣿⠻⣦⣀⣴⠶⠂⠀⠘⣷⡄⠀⠀⢀⣴⡿⠈⠢⡀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⡠⠖⣉⣁⡀⠀⢀⣾⠋⠴⢿⣽⠋⠀⠞⢉⣉⣽⣳⣄⣀⠀⠋⠀⠀⠀⠈⠙⣷⡄⠀⠁⠀⠙⢤⣯⡀⠀⠀⠀⣼⡇⠀⡾⠋⠁⠀⠳⣄⠘⢆⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⡰⠋⠰⠛⢻⡞⢉⣠⣼⡇⢀⣴⠟⠛⠒⣴⠟⠋⠉⠀⠀⢀⣀⣀⡀⠀⠀⠀⠀⠀⣸⡇⠀⠀⠳⣄⠀⠉⢿⣄⠀⢰⣿⣧⡀⠀⣴⠶⠶⣦⡼⢧⠈⢣⠀⠀⠀⠀
⠀⠀⠀⢀⡞⣡⣶⡄⠀⡟⣳⠿⠋⠙⡍⡽⠁⣀⣤⣤⣿⡄⠀⠀⠀⠀⡿⡉⣀⣀⣤⣤⣤⣴⠾⠥⠽⣦⣄⠀⠉⠻⢶⡼⢻⠀⠈⠇⠘⡷⡄⠘⠂⠀⢀⡍⠻⣷⣄⡇⠀⠀⠀
⠀⠀⠀⠘⣺⠏⢸⢃⣼⠟⢁⡤⠀⣠⢟⡷⠟⢋⣉⣤⡿⠇⠀⠀⠀⢰⣣⠞⠋⠉⠉⠁⡀⠀⠀⠀⠀⠀⠙⢷⣄⠀⠀⢹⣾⠀⠀⠀⠀⢸⡇⠀⣀⡀⣾⠀⠀⠈⢻⡁⢦⠀⠀
⠀⠀⣠⢚⣵⣄⠈⣼⡇⠀⢸⠧⢞⡵⠋⠠⠚⠉⠉⠀⠀⢀⡇⠀⣰⣟⣁⣀⠀⠀⠀⠀⠉⠒⠶⣤⣤⣀⠀⠀⠙⠀⠀⢸⡇⢰⣟⠛⢶⡋⣇⠀⠉⠻⡟⡄⠀⢀⢀⣿⠀⢧⠀
⠀⣰⠃⢸⠁⣿⠀⠸⣧⠀⢸⢣⠋⠀⣠⣤⠶⢶⢒⣤⣔⣻⠣⢼⠟⠁⠀⠙⢷⡄⠀⠀⢀⠀⠀⠀⠈⠓⢟⢦⠀⠀⠀⢸⡇⠈⠻⣦⡀⠈⠻⣷⣄⠀⠘⣿⠀⠸⣿⣇⣀⢸⠀
⠀⡇⠀⠀⣼⠇⠀⢀⣿⠀⣇⣇⣴⠟⠋⢠⣾⠟⠉⠀⠀⠈⠳⣼⠀⠀⠀⠀⠀⠳⠀⠀⠈⢳⣄⠀⠀⠀⢸⣼⠀⠀⠀⠈⡟⢆⠀⠈⢻⡀⠀⠈⢻⣆⠀⣻⠃⠀⠀⢹⡟⠻⡀
⠀⢧⡆⣼⠏⠀⣾⠟⠁⢰⠃⡵⠃⢀⣴⡿⠁⠀⡀⠀⠀⠀⠀⠹⣧⡀⠰⣦⡀⠀⠀⠀⠀⠀⣻⢦⣀⣠⡾⣇⠀⠀⢀⣰⠟⠙⢷⣄⠀⠀⠀⠀⠀⣿⠀⠉⢠⠄⠀⣼⡇⠀⢧
⢀⠞⢡⡟⠀⠀⣿⠀⢀⡏⡼⠁⣴⠟⠁⠀⠀⠀⣿⠀⣀⣀⢀⣴⠘⣷⡀⠈⢻⣦⣀⠀⢀⣾⠟⠉⠀⠀⠉⠻⣷⣄⠀⠀⠀⠀⠀⠙⢷⡄⠀⠀⠀⠉⠀⣠⡟⠀⣼⣟⠀⠀⢸
⢸⠀⠘⣧⠀⡴⠛⠳⢸⢰⠁⢰⠏⠀⠀⠀⢀⣼⡯⠟⠋⠙⠻⣷⡀⠘⠀⠀⠀⠈⠉⠻⣿⠁⠀⠀⢰⡟⠉⠀⠈⢻⣦⠀⠀⠀⣄⠀⠀⡗⠀⢸⡇⣠⣾⠟⢀⣾⠋⠹⣷⢀⡇
⠈⢆⠀⠹⢷⣤⣀⣠⠎⡇⠀⠸⠀⠀⢀⣴⠟⠉⠀⠀⠀⢄⠀⠹⣧⡀⠀⠀⣀⡀⠀⠀⣿⠀⠀⠀⠘⣿⡄⠀⠀⠀⢹⣦⡀⠀⢿⣄⠀⢀⣠⡿⠽⣯⡁⠀⠸⠃⠀⠀⡏⠉⠀
⠀⢠⢷⣄⠀⠈⣉⣉⢢⢳⡀⠀⠀⠀⣾⡏⠀⠀⠠⣀⡤⢿⠀⠀⠙⠷⠶⠛⠉⠈⠀⣰⠟⠀⠀⠀⠀⠘⣷⡀⠀⠠⠛⠉⠉⠀⢈⣯⠗⠛⠁⠀⠀⠈⠃⠀⢀⣴⠇⢠⠇⠀⠀
⠀⢸⡀⠻⣧⠈⠉⠹⣏⢀⣑⠤⣀⣀⠼⠳⣄⠀⠀⠀⠙⠺⠖⣦⣤⠤⣀⡀⠀⠀⠘⠁⠀⠀⠀⠀⠀⠀⢸⢧⡀⠀⠀⢀⣀⢴⣿⣅⡀⠠⠶⢿⢦⣀⣠⣴⠟⠃⡠⠋⠀⠀⠀
⠀⠀⠳⡀⠘⠃⠀⡤⠸⣼⠀⠉⠛⠋⠉⠉⠙⠻⣦⣄⠀⠀⠀⠀⠈⠉⠙⠻⣦⠀⠀⠀⠀⡀⠀⠀⠀⢀⣾⠖⠚⠛⠛⠛⠋⠁⠀⠙⣷⠀⠀⣸⡴⠛⠉⢁⡤⠊⠁⠀⠀⠀⠀
⠀⠀⠀⠘⢦⡀⠸⣧⠀⢻⢇⠀⠳⡤⣤⠆⠀⠀⠈⢻⡇⠀⠀⠀⢰⡄⠀⠀⣿⡇⢀⡾⠛⠛⠻⡝⣲⠟⠋⠀⢀⡄⠀⠀⠀⣀⡄⠀⠋⢀⡴⣻⡄⣤⡶⡍⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠈⠙⠁⠉⠉⠈⠣⡀⠹⣇⠀⠀⠀⠀⠘⠀⠀⠀⢀⡾⢳⡶⠾⠋⠀⠈⠃⠀⠀⣠⠟⢄⣀⣠⡴⠋⠀⠀⠀⣼⢻⣤⣴⠶⠟⠋⣡⡷⣏⢿⡧⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠓⢫⣲⣤⣀⣀⣀⣀⣤⣶⣻⠋⠛⠷⣦⣤⣤⣄⡤⢤⣺⠕⠋⠉⠉⠁⠀⠀⣀⣤⣾⠏⢩⠀⠀⢀⣤⣾⠛⣧⢻⣼⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠓⠮⢭⣉⣉⡩⠥⠚⠈⢇⠀⢠⡄⠀⠉⠉⠙⣿⠀⢠⠶⠖⢫⣩⠟⠛⠛⠉⠀⣠⣿⣦⠶⠿⣭⣸⣇⡿⠞⠁⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠳⣌⡿⣄⠀⠒⠚⠋⠀⠀⠀⣠⡾⠃⠀⢀⣀⠴⠚⠉⠣⢍⣛⣶⡶⠝⠃⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠙⠒⠂⠀⠒⠒⠉⠀⠉⠉⠉⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀

  · · · · · · · · · · · · · · · · · · · · · · · · · · · · · ·

 ██████╗    ██████╗     ██████╗    ███╗   ██╗   ██╗    █████╗
██╔════╝   ██╔═══██╗   ██╔════╝    ████╗  ██║   ██║   ██╔══██╗
██║        ██║   ██║   ██║  ███╗   ██╔██╗ ██║   ██║   ███████║
██║        ██║   ██║   ██║   ██║   ██║╚██╗██║   ██║   ██╔══██║
╚██████╗   ╚██████╔╝   ╚██████╔╝   ██║ ╚████║   ██║   ██║  ██║
 ╚═════╝    ╚═════╝     ╚═════╝    ╚═╝  ╚═══╝   ╚═╝   ╚═╝  ╚═╝

  v3.2 · Fases 1-13 · Sistema cognitivo local
  /ayuda para todos los comandos
"""

# ---------------------------------------------------------------------------
# Themes
# ---------------------------------------------------------------------------
_THEMES = {
    "oscuro": Theme({
        "ok":       "bold bright_green",
        "mod":      "bold cyan",
        "detail":   "dim white",
        "info_dim": "dim grey62",
        "footer":   "dim grey50",
        "spinner":  "magenta",
        "warn_cl":  "yellow",
        "err_cl":   "red",
    }),
    "claro": Theme({
        "ok":       "bold green",
        "mod":      "bold blue",
        "detail":   "grey30",
        "info_dim": "grey50",
        "footer":   "grey50",
        "spinner":  "dark_magenta",
        "warn_cl":  "dark_orange",
        "err_cl":   "red",
    }),
    "alto_contraste": Theme({
        "ok":       "bold white",
        "mod":      "bold bright_white",
        "detail":   "white",
        "info_dim": "grey74",
        "footer":   "grey74",
        "spinner":  "bright_white",
        "warn_cl":  "bright_yellow",
        "err_cl":   "bright_red",
    }),
}
_THEME_ORDER = list(_THEMES)
_theme_idx   = 0
_console     = Console(theme=_THEMES["oscuro"], highlight=False) if _HAS_RICH else None

# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
_session_log   = []
_session_start = 0.0
_init_lines    = []
_debug_mode    = False
_fast_mode     = False

# ---------------------------------------------------------------------------
# Command registry — drives autocomplete and /ayuda
# ---------------------------------------------------------------------------
_CMD_DESCRIPTIONS = {
    # Memoria y aprendizaje
    "/yo":              "Introspección completa del sistema",
    "/conceptos":       "Listar conceptos aprendidos",
    "/dormir":          "Ciclo de consolidación tipo sueño",
    "/repasar":         "Ver episodios para repasar",
    "/contradicciones": "Ver contradicciones detectadas",
    "/olvido":          "Ciclo de olvido",
    "/observar":        "Observar sin etiqueta   <texto>",
    "/aprender":        "Enseñar con etiqueta    <texto> | <label>",
    "/investigar":      "Investigar en GitHub    <query>",
    "/crear":           "Crear programa ahora    <idea>",
    "/encolar":         "Encolar idea para sleep <idea>",
    "/corregir":        "Corregir error          <obs> | <mal> | <bien>",
    "/hipotesis":       "Generar hipótesis       <A> | <B>",
    "/explicar":        "Autoexplicación         <texto>",
    # Conocimiento
    "/grafo":           "Ver knowledge graph     <concepto>",
    "/hecho":           "Agregar hecho al grafo  <subj> | <pred> | <obj>",
    "/objetivos":       "Ver objetivos cognitivos",
    "/predecir":        "Predicciones temporales <concepto>",
    "/inferir":         "Inferencias             <concepto>",
    "/narrativa":       "Narrativa de concepto   <concepto>",
    # Seguridad
    "/seguridad":       "Estado de cifrado",
    "/bloquear":        "Bloquear cifrado",
    "/desbloquear":     "Desbloquear cifrado     <passphrase>",
    # Personalización
    "/usuarios":        "Listar perfiles de usuario",
    "/usuario":         "Cambiar usuario activo  <id>",
    "/estilo_info":     "Ver estilo de aprendizaje",
    "/indice_personal": "Ver índice personal",
    "/indice_add":      "Añadir al índice        <concepto>",
    "/escalar":         "Ver nivel de escala actual",
    # Mesh
    "/mesh_iniciar":    "Iniciar MeshNode        [puerto]",
    "/mesh_peer":       "Conectar peer           <url>",
    "/mesh_publicar":   "Publicar conocimiento   <subj> | <pred> | <obj>",
    "/mesh_estado":     "Ver estado del mesh",
    # Sistema
    "/doctor":          "Verificar instalación",
    "/update":          "Actualizar Cognia",
    "/leer":            "Leer archivo al contexto   <ruta>",
    "/proyecto":        "Leer proyecto completo     <ruta>",
    "/distill":         "Destilación SRDN (dry-run)",
    "/distill run":     "Destilación SRDN (ejecutar)",
    "/ayuda":           "Mostrar todos los comandos",
    "/salir":           "Salir del REPL",
    # UI
    "/limpiar":         "Limpiar pantalla",
    "/compactar":       "Resumir historial de sesión",
    "/memoria":         "Estado de memoria y KG",
    "/modulos":         "Módulos activos en tiempo real",
    "/exportar":        "Exportar sesión a .md",
    "/modo rapido":     "Toggle: saltar confirmaciones",
    "/debug":           "Toggle: mostrar logs INFO",
    "/costo":           "Tokens y tiempo de sesión",
    "/tema":            "Ciclar tema visual",
}

# ---------------------------------------------------------------------------
# Autocompleter — activates on '/', shows descriptions as meta
# ---------------------------------------------------------------------------
if _HAS_PT:
    class _CogniaCompleter(Completer):
        def get_completions(self, document, complete_event):
            text = document.text_before_cursor
            if not text.startswith("/"):
                return
            if " " in text:
                return
            lower = text.lower()
            for cmd, desc in _CMD_DESCRIPTIONS.items():
                if cmd.lower().startswith(lower):
                    yield Completion(
                        cmd,
                        start_position=-len(text),
                        display=cmd,
                        display_meta=desc,
                    )

# ---------------------------------------------------------------------------
# Help text
# ---------------------------------------------------------------------------
HELP_TEXT = """
  COGNIA v3 -- Comandos disponibles
  ----------------------------------
  Texto sin / se trata como mensaje al sistema cognitivo (chat libre).

  MEMORIA Y APRENDIZAJE:
    /observar <texto>               Observar sin etiqueta
    /aprender <texto> | <label>     Ensenar con etiqueta
    /corregir <obs> | <mal> | <bien>Corregir error
    /hipotesis <A> | <B>            Generar hipotesis
    /yo                             Introspección completa
    /conceptos                      Listar conceptos
    /dormir                         Consolidacion tipo sueno
    /repasar                        Ver episodios para repasar
    /contradicciones                Ver contradicciones
    /explicar <texto>               Autoexplicacion
    /olvido                         Ciclo de olvido

  CONOCIMIENTO v3:
    /grafo <concepto>               Ver knowledge graph
    /hecho <subj> | <pred> | <obj>  Agregar hecho al grafo
    /objetivos                      Ver objetivos cognitivos
    /predecir <concepto>            Ver predicciones temporales
    /inferir <concepto>             Inferencias sobre concepto

  SEGURIDAD:
    /desbloquear <pass>             Desbloquear cifrado
    /bloquear                       Bloquear cifrado
    /seguridad                      Estado de cifrado

  PERSONALIZACION:
    /usuarios                       Listar perfiles
    /usuario <id>                   Cambiar usuario activo
    /estilo_info                    Ver estilo de aprendizaje
    /indice_personal                Ver indice personal
    /indice_add <concepto>          Anadir concepto al indice
    /escalar                        Ver nivel de escala actual

  INGESTION DE ARCHIVOS:
    /leer <ruta>                    Leer un archivo (txt, md, py, pdf, etc.)
    /proyecto <ruta>                Leer todos los archivos de un directorio

  SISTEMA:
    /doctor                         Verificar instalacion
    /update                         Actualizar Cognia
    /distill  /  /distill run       Destilacion SRDN
    /ayuda    /  /salir

  UI / SLASH:
    /limpiar                        Limpiar pantalla
    /compactar                      Resumir historial de sesion
    /memoria                        Estado de memoria y KG
    /modulos                        Modulos activos en tiempo real
    /exportar                       Exportar sesion a .md con timestamp
    /modo rapido                    Toggle: saltar confirmaciones
    /debug                          Toggle: mostrar logs INFO
    /costo                          Tokens y tiempo de sesion
    /tema                           Ciclar tema visual
"""

# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def _strip_markup(text):
    return re.sub(r"\[/?[^\]]+\]", "", text)


def _to_str(result):
    """Convert any Cognia return value to a displayable string."""
    if result is None:
        return ""
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        return "\n".join(f"  {k}: {v}" for k, v in result.items())
    return str(result)


def _cmd_color(raw):
    cmd = raw.lstrip("/").split()[0] if raw else ""
    if cmd in {"aprender", "corregir", "hecho", "indice_add", "dormir", "investigar", "crear", "encolar"}:
        return "bright_green"
    if cmd in {"hipotesis", "explicar", "narrativa", "inferir"}:
        return "magenta"
    if cmd in {"olvido", "bloquear", "desbloquear", "escalar"}:
        return "yellow"
    return "cyan"


def _print_line(text):
    if _HAS_RICH and _console:
        _console.print(text)
    else:
        print(_strip_markup(text))


def _show_response(text, color="cyan"):
    text = _to_str(text)
    if _HAS_RICH and _console:
        _console.print(Panel(_escape(text.strip()), border_style=color, padding=(0, 1)))
    else:
        print(f"\n{text}\n")


def _show_footer(elapsed, text):
    text   = _to_str(text)
    tokens = max(1, len(text) // 4)
    if _HAS_RICH and _console:
        _console.print(
            f"[footer]tokens ~{tokens}  ·  {elapsed:.2f}s  ·  Cognia v3.2[/footer]",
            justify="right",
        )


class _VerboseFilter(logging.Filter):
    """Suppresses INFO/DEBUG records during the spinner unless debug mode is on."""
    def filter(self, record):
        return _debug_mode or record.levelno >= logging.WARNING


def _run(raw, fn, color=None):
    """Execute fn() under a spinner, display result in panel, append to log.

    Redirects stdout during execution so internal Cognia print() calls do not
    bleed into the spinner line. In debug mode they appear below the panel.
    """
    effective_color = color or _cmd_color(raw)

    if _HAS_RICH and _console:
        flt      = _VerboseFilter()
        logging.root.addFilter(flt)
        captured = io.StringIO()
        try:
            with _console.status("[spinner]Procesando...[/spinner]", spinner="dots"):
                t0 = time.time()
                with contextlib.redirect_stdout(captured):
                    result = fn()
        finally:
            logging.root.removeFilter(flt)
        elapsed = time.time() - t0
        if _debug_mode:
            txt = captured.getvalue().strip()
            if txt:
                _console.print(txt, style="info_dim", markup=False)
    else:
        t0     = time.time()
        result = fn()
        elapsed = time.time() - t0

    result = _to_str(result)
    if result:
        _show_response(result, effective_color)
        _show_footer(elapsed, result)
    _session_log.append({"input": raw, "output": result, "elapsed": elapsed})


# ---------------------------------------------------------------------------
# Startup panel (two-column, Claude Code style)
# ---------------------------------------------------------------------------

def _print_startup_panel():
    if not _HAS_RICH or not _console:
        print(_G + _BANNER_RAW + _R)
        return

    # Dark green (#003300) -> matrix green (#00FF41), interpolated per non-empty line
    banner_lines = _BANNER_RAW.split("\n")
    non_empty = [l for l in banner_lines if l.strip()]
    total = max(1, len(non_empty) - 1)
    left_text = Text(no_wrap=False)
    colored_idx = 0
    for line in banner_lines:
        if line.strip():
            t = colored_idx / total
            g_val = int(0x33 + t * (0xFF - 0x33))
            b_val = int(t * 0x41)
            style = f"#00{g_val:02x}{b_val:02x}"
            left_text.append(line + "\n", style=style)
            colored_idx += 1
        else:
            left_text.append("\n")

    right_text = Text()
    _r = right_text.append
    _r("Slash commands\n",              "bold cyan")
    _r("─" * 33 + "\n",               "dim bright_green")
    _r("  /yo          ",              "cyan");  _r("introspección\n",          "dim white")
    _r("  /dormir      ",              "cyan");  _r("ciclo de sueño\n",         "dim white")
    _r("  /observar    ",              "cyan");  _r("<texto>\n",                "dim white")
    _r("  /aprender    ",              "cyan");  _r("<texto> | <label>\n",      "dim white")
    _r("  /grafo       ",              "cyan");  _r("<concepto>\n",             "dim white")
    _r("  /inferir     ",              "cyan");  _r("<concepto>\n",             "dim white")
    _r("  /memoria     ",              "cyan");  _r("estado de memoria\n",      "dim white")
    _r("  /modulos     ",              "cyan");  _r("modulos activos\n",        "dim white")
    _r("  /exportar    ",              "cyan");  _r("exportar sesion .md\n",    "dim white")
    _r("  /debug       ",              "cyan");  _r("toggle logs INFO\n",       "dim white")
    _r("  /tema        ",              "cyan");  _r("ciclar tema visual\n",     "dim white")
    _r("\n", "")
    _r("  Texto libre ", "dim");        _r("->", "bright_green"); _r(" chat cognitivo\n", "dim")
    _r("  Tab ", "dim bright_green");   _r("autocompletar  ", "dim")
    _r("↑↓ ", "dim bright_green");      _r("historial\n", "dim")
    _r("\n", "")
    _r("  Escribe ", "dim");            _r("/ayuda", "bold bright_green"); _r(" para todo.\n", "dim")

    grid = Table.grid(expand=True, padding=(0, 2))
    grid.add_column(ratio=3, overflow="fold")
    grid.add_column(ratio=2)
    grid.add_row(left_text, right_text)

    _console.print(Panel(
        grid,
        title="[bright_green]Cognia v3.2[/bright_green]",
        border_style="bright_green",
        padding=(0, 1),
    ))


# ---------------------------------------------------------------------------
# Startup animation
# ---------------------------------------------------------------------------

def _animate_startup(lines):
    if not _HAS_RICH or not _console:
        for line in lines:
            print(line)
        return

    ok_count = 0
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if "[OK]" in stripped:
            rest   = stripped.replace("[OK]", "", 1).strip()
            parts  = rest.split("  ", 1) if "  " in rest else [rest, ""]
            name   = parts[0].strip()
            detail = parts[1].strip() if len(parts) > 1 else ""
            if detail:
                _console.print(
                    f"[ok][[/ok][ok]OK[/ok][ok]][/ok] [mod]{_escape(name)}[/mod]"
                    f"  [detail]{_escape(detail)}[/detail]"
                )
            else:
                _console.print(f"[ok][[/ok][ok]OK[/ok][ok]][/ok] [mod]{_escape(name)}[/mod]")
            ok_count += 1
            time.sleep(0.045)
        elif "[WARN]" in stripped or "[!]" in stripped:
            _console.print(f"[warn_cl]{_escape(stripped)}[/warn_cl]")
        elif _debug_mode:
            _console.print(f"[info_dim]{_escape(stripped)}[/info_dim]")

    if ok_count > 0:
        with Progress(
            SpinnerColumn(style="magenta"),
            TextColumn("[mod]Iniciando sistema...[/mod]"),
            BarColumn(bar_width=40, style="cyan", complete_style="bright_green"),
            TextColumn("[ok]{task.percentage:>3.0f}%[/ok]"),
            console=_console,
            transient=True,
        ) as progress:
            task = progress.add_task("", total=40)
            for _ in range(40):
                time.sleep(0.012)
                progress.advance(task)

    _console.rule("[dim]Sistema listo[/dim]")


# ---------------------------------------------------------------------------
# UI slash command implementations
# ---------------------------------------------------------------------------

def _slash_limpiar():
    if _HAS_RICH and _console:
        _console.clear()
        _print_startup_panel()
    else:
        os.system("cls" if sys.platform == "win32" else "clear")
        print(_G + _BANNER_RAW + _R)


def _slash_compactar():
    if _HAS_RICH and _console:
        _console.clear()
        _print_startup_panel()
        if _session_log:
            rows = []
            for entry in _session_log[-5:]:
                inp = _escape(entry["input"][:70])
                out = _escape(entry["output"][:100].replace("\n", " "))
                rows.append(f"[mod]{inp}[/mod]\n[detail]{out}[/detail]")
            _console.print(Panel(
                "\n\n".join(rows),
                title="[cyan]Ultimas interacciones[/cyan]",
                border_style="cyan",
                padding=(0, 1),
            ))
        else:
            _console.print("[detail]Sin historial aun.[/detail]")
    else:
        print("Historial compactado.")


def _slash_modulos():
    ok_lines = [l for l in _init_lines if "[OK]" in l]
    if not ok_lines:
        _print_line("[detail]No hay informacion de modulos disponible.[/detail]")
        return
    if _HAS_RICH and _console:
        _console.print(Panel(
            _escape("\n".join(ok_lines)),
            title="[cyan]Modulos activos[/cyan]",
            border_style="cyan",
            padding=(0, 1),
        ))
    else:
        print("\n".join(ok_lines))


def _slash_exportar():
    ts       = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"cognia_sesion_{ts}.md"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(f"# Sesion Cognia — {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
        for entry in _session_log:
            f.write(f"**> {entry['input']}**\n\n```\n{entry['output']}\n```\n\n---\n\n")
    _print_line(f"[ok]Exportado:[/ok] [mod]{filename}[/mod]")


def _slash_costo():
    total_elapsed = time.time() - _session_start if _session_start else 0.0
    total_tokens  = sum(max(1, len(e["output"]) // 4) for e in _session_log)
    content = (
        f"Llamadas       {len(_session_log)}\n"
        f"Tokens aprox.  {total_tokens}\n"
        f"Tiempo total   {total_elapsed:.1f}s\n"
        f"Modelo         Cognia v3.2 (local)"
    )
    if _HAS_RICH and _console:
        _console.print(Panel(content, title="[cyan]Costo de sesion[/cyan]",
                             border_style="cyan", padding=(0, 1)))
    else:
        print(content)


def _slash_debug():
    global _debug_mode
    _debug_mode = not _debug_mode
    _print_line(f"[detail]debug {'activado' if _debug_mode else 'desactivado'}[/detail]")


def _slash_modo_rapido():
    global _fast_mode
    _fast_mode = not _fast_mode
    _print_line(f"[detail]modo rapido {'activado' if _fast_mode else 'desactivado'}[/detail]")


def _slash_tema():
    global _theme_idx, _console
    _theme_idx = (_theme_idx + 1) % len(_THEME_ORDER)
    name = _THEME_ORDER[_theme_idx]
    if _HAS_RICH:
        _console = Console(theme=_THEMES[name], highlight=False)
        _console.rule(f"[dim]Tema: {name}[/dim]")
    else:
        print(f"Tema: {name} (Rich no disponible)")


# ---------------------------------------------------------------------------
# REPL
# ---------------------------------------------------------------------------

def repl():
    global _session_start, _init_lines, _console, _debug_mode, _fast_mode

    # Force UTF-8 stdout on Windows so block/box chars render without crash
    if hasattr(sys.stdout, "buffer") and sys.stdout.encoding.lower().replace("-", "") not in ("utf8",):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    _session_start = time.time()

    # Capture Cognia() init output for animated replay
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ai = Cognia()
    _init_lines[:] = buf.getvalue().splitlines()

    # Startup panel + animated modules
    _print_startup_panel()
    _animate_startup(_init_lines)

    # Build input function
    if _HAS_PT:
        _pt_style = PTStyle.from_dict({
            "":                                        "ansiyellow bold",
            "completion-menu.completion":              "bg:#1c1c2e fg:#c8c8d8",
            "completion-menu.completion.current":      "bg:#004466 fg:#ffffff",
            "completion-menu.meta.completion":         "bg:#1c1c2e fg:#667788",
            "completion-menu.meta.completion.current": "bg:#004466 fg:#aaccdd",
            "scrollbar.background":                    "bg:#1c1c2e",
            "scrollbar.button":                        "bg:#334455",
        })
        _kb = KeyBindings()

        @_kb.add("tab")
        def _tab_complete(event):
            buff = event.app.current_buffer
            if buff.complete_state:
                buff.complete_next()
            else:
                buff.start_completion(select_first=True)

        session = PromptSession(
            history=InMemoryHistory(),
            completer=_CogniaCompleter(),
            complete_while_typing=True,
            complete_style=CompleteStyle.MULTI_COLUMN,
            complete_in_thread=True,
            key_bindings=_kb,
            style=_pt_style,
        )

        def _get_input():
            line = session.prompt("cognia> ").strip()
            while line.endswith("\\"):
                continuation = session.prompt("  ").strip()
                line = line[:-1].rstrip() + " " + continuation
            return line
    else:
        def _get_input():
            return input(_G + "cognia> " + _R).strip()

    # -----------------------------------------------------------------------
    # Main loop
    # -----------------------------------------------------------------------
    while True:
        try:
            raw = _get_input()
        except (EOFError, KeyboardInterrupt):
            print("\nHasta luego.")
            break

        if not raw:
            continue

        # -- UI slash -------------------------------------------------------
        if raw == "/limpiar":
            _slash_limpiar()
        elif raw == "/compactar":
            _slash_compactar()
        elif raw == "/memoria":
            _run(raw, ai.introspect, color="cyan")
        elif raw == "/modulos":
            _slash_modulos()
        elif raw == "/exportar":
            _slash_exportar()
        elif raw == "/costo":
            _slash_costo()
        elif raw == "/debug":
            _slash_debug()
        elif raw == "/modo rapido":
            _slash_modo_rapido()
        elif raw == "/tema":
            _slash_tema()

        # -- System ---------------------------------------------------------
        elif raw == "/salir":
            print("Hasta luego.")
            break
        elif raw == "/doctor":
            import subprocess
            script = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "scripts", "cognia_doctor.py",
            )
            subprocess.run([sys.executable, script])
        elif raw == "/update":
            import subprocess
            script = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "scripts", "cognia_update.py",
            )
            subprocess.run([sys.executable, script])
        elif raw == "/distill":
            import subprocess
            script = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "scripts", "distill.py",
            )
            subprocess.run([sys.executable, script, "--dry-run"])
        elif raw == "/distill run":
            import subprocess
            script = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "scripts", "distill.py",
            )
            subprocess.run([sys.executable, script])
        elif raw == "/ayuda":
            if _HAS_RICH and _console:
                _console.print(HELP_TEXT, style="bright_green", markup=False)
            else:
                print(_G + HELP_TEXT + _R)

        # -- Cognitive: simple ---------------------------------------------
        elif raw == "/yo":
            _run(raw, ai.introspect, color="cyan")
        elif raw == "/conceptos":
            _run(raw, ai.list_concepts, color="cyan")
        elif raw == "/olvido":
            _run(raw, ai.forget_cycle, color="yellow")
        elif raw == "/dormir":
            _run(raw, ai._sleep_sync, color="bright_green")
        elif raw == "/repasar":
            _run(raw, ai.review_due, color="cyan")
        elif raw == "/contradicciones":
            _run(raw, ai.show_contradictions, color="yellow")
        elif raw == "/objetivos":
            _run(raw, ai.show_goals, color="cyan")
        elif raw in ("/research", "/investigaciones"):
            if HAS_RESEARCH_ENGINE:
                from cognia.research_engine import show_research_history
                _run(raw, lambda: show_research_history(ai.db), color="cyan")
            else:
                _print_line("[warn_cl][WARN] Modulo de investigacion no disponible.[/warn_cl]")
        elif raw in ("/programs", "/library", "/biblioteca"):
            if HAS_PROGRAM_CREATOR:
                from cognia.program_creator import show_library
                _run(raw, show_library, color="cyan")
            else:
                _print_line("[warn_cl][WARN] Modulo de programacion hobby no disponible.[/warn_cl]")
        elif raw == "/program_stats":
            if HAS_PROGRAM_CREATOR:
                from cognia.program_creator import get_session_stats
                stats = get_session_stats()
                _show_response(
                    f"Sesiones:    {stats['sessions_run']}\n"
                    f"Intentos:    {stats['programs_attempted']}\n"
                    f"Guardados:   {stats['programs_stored']}\n"
                    f"Ultima vez:  {stats['last_run']}",
                    "cyan",
                )
            else:
                _print_line("[warn_cl][WARN] Modulo de programacion hobby no disponible.[/warn_cl]")

        # -- Cognitive: with arguments --------------------------------------
        elif raw.startswith("/repasar "):
            parts = raw[len("/repasar "):].split()
            try:
                ep_id    = int(parts[0])
                correcto = len(parts) < 2 or parts[1].lower() in ("correcto", "si", "sí", "yes")
                _run(raw, lambda: ai.mark_review(ep_id, correcto), color="bright_green")
            except Exception:
                _print_line("[warn_cl]Uso: /repasar <id> correcto|incorrecto[/warn_cl]")
        elif raw.startswith("/aprender ") and "|" in raw:
            partes = raw[len("/aprender "):].split("|", 1)
            _run(raw, lambda: ai.learn(partes[0].strip(), partes[1].strip()), color="bright_green")
        elif raw.startswith("/investigar "):
            _query = raw[len("/investigar "):].strip()
            _run(raw, lambda: ai.github_research(_query), color="bright_green")
        elif raw == "/investigar":
            _print_line("[warn_cl]Uso: /investigar <query>  — ejemplo: /investigar machine learning Python[/warn_cl]")
        elif raw.startswith("/crear "):
            _idea = raw[len("/crear "):].strip()
            _run(raw, lambda: ai.create_program(_idea), color="bright_green")
        elif raw == "/crear":
            _print_line("[warn_cl]Uso: /crear <idea>  — ejemplo: /crear juego de Snake en terminal[/warn_cl]")
        elif raw.startswith("/encolar "):
            if HAS_PROGRAM_CREATOR:
                _idea_enc = raw[len("/encolar "):].strip()
                try:
                    from cognia.program_creator.generator import add_custom_idea, get_custom_ideas
                    ok = add_custom_idea(_idea_enc)
                    n  = len(get_custom_ideas())
                    _show_response(
                        f"Idea encolada para el proximo /dormir: '{_idea_enc}'\n"
                        f"Ideas pendientes: {n}"
                        if ok else
                        f"La idea ya estaba en la cola.",
                        "bright_green",
                    )
                except Exception as _e:
                    _print_line(f"[warn_cl][ERROR] {_e}[/warn_cl]")
            else:
                _print_line("[warn_cl][WARN] ProgramCreator no disponible.[/warn_cl]")
        elif raw == "/encolar":
            _print_line("[warn_cl]Uso: /encolar <idea>  — ejemplo: /encolar juego de tetris ASCII[/warn_cl]")
        elif raw.startswith("/observar "):
            texto = raw[len("/observar "):].strip()
            _run(raw, lambda: ai.process(texto), color="cyan")
        elif raw.startswith("/corregir ") and raw.count("|") >= 2:
            partes = raw[len("/corregir "):].split("|")
            _run(raw, lambda: ai.correct(
                partes[0].strip(), partes[1].strip(), partes[2].strip()), color="bright_green")
        elif raw.startswith("/hipotesis ") and "|" in raw:
            partes = raw[len("/hipotesis "):].split("|", 1)
            _run(raw, lambda: ai.generate_hypothesis(
                partes[0].strip(), partes[1].strip()), color="magenta")
        elif raw.startswith("/explicar "):
            texto = raw[len("/explicar "):].strip()
            _run(raw, lambda: ai.explain(texto), color="magenta")
        elif raw.startswith("/grafo "):
            concepto = raw[len("/grafo "):].strip()
            _run(raw, lambda: ai.show_graph(concepto), color="cyan")
        elif raw.startswith("/hecho ") and raw.count("|") >= 2:
            partes = raw[len("/hecho "):].split("|")
            _run(raw, lambda: ai.add_fact(
                partes[0].strip(), partes[1].strip(), partes[2].strip()), color="bright_green")
        elif raw.startswith("/predecir "):
            concepto = raw[len("/predecir "):].strip()
            _run(raw, lambda: ai.predict_next(concepto), color="cyan")
        elif raw.startswith("/inferir "):
            concepto = raw[len("/inferir "):].strip()
            _run(raw, lambda: ai.infer_about(concepto), color="magenta")
        elif raw.startswith("/narrativa "):
            concepto = raw[len("/narrativa "):].strip()
            _run(raw, lambda: ai.get_narrative(concepto), color="magenta")

        # -- Mesh -----------------------------------------------------------
        elif raw.startswith("/mesh_iniciar"):
            parts = raw.split()
            port  = int(parts[1]) if len(parts) > 1 else 7474
            _run(raw, lambda: ai.start_mesh(port), color="cyan")
        elif raw.startswith("/mesh_peer "):
            peer = raw[len("/mesh_peer "):].strip()
            _run(raw, lambda: ai.connect_mesh_peer(peer), color="cyan")
        elif raw.startswith("/mesh_publicar ") and raw.count("|") >= 2:
            partes = raw[len("/mesh_publicar "):].split("|")
            triple = [{"subject":   partes[0].strip(),
                       "predicate": partes[1].strip(),
                       "object":    partes[2].strip()}]
            _run(raw, lambda: ai.publish_knowledge(triple), color="bright_green")
        elif raw == "/mesh_estado":
            _run(raw, ai.mesh_status, color="cyan")

        # -- Security -------------------------------------------------------
        elif raw == "/seguridad":
            _run(raw, ai.security_status, color="yellow")
        elif raw == "/bloquear":
            _run(raw, ai.lock_security, color="yellow")
        elif raw.startswith("/desbloquear "):
            passphrase = raw[len("/desbloquear "):].strip()
            if passphrase:
                _run(raw, lambda: ai.unlock_security(passphrase), color="yellow")
            else:
                _print_line("[warn_cl]Uso: /desbloquear <passphrase>[/warn_cl]")

        # -- Scale ----------------------------------------------------------
        elif raw == "/escalar":
            try:
                from cognia.scale_manager import get_scale_manager
                sm = get_scale_manager()
                st = sm.status()
                _show_response(
                    f"Nivel        {st['level']}: {st['name']}\n"
                    f"Modelo       {st['model']}\n"
                    f"Timeout      {st['timeout_s']}s\n"
                    f"RAM          {st['ram_gb']} GB\n"
                    f"Memorias     {st['memories']}\n"
                    f"Peers        {st['peers']}\n"
                    f"Historial    {st['hit_counts']}",
                    "cyan",
                )
            except Exception as e:
                _print_line(f"[warn_cl]ScaleManager no disponible: {e}[/warn_cl]")

        # -- User profiles --------------------------------------------------
        elif raw == "/usuarios":
            try:
                from cognia.user_profile import list_users
                users = list_users(ai.db)
                if users:
                    _show_response(
                        "\n".join(
                            f"[{u['id']}] {u['name']}  (interacciones: {u.get('interactions', 0)})"
                            for u in users
                        ),
                        "cyan",
                    )
                else:
                    _print_line("[detail]No hay usuarios registrados.[/detail]")
            except Exception as e:
                _print_line(f"[warn_cl]No disponible: {e}[/warn_cl]")
        elif raw.startswith("/usuario "):
            uid = raw[len("/usuario "):].strip()
            try:
                from cognia.user_profile import switch_user
                _run(raw, lambda: switch_user(ai, uid), color="cyan")
            except Exception as e:
                _print_line(f"[warn_cl]No disponible: {e}[/warn_cl]")
        elif raw == "/estilo_info":
            try:
                from cognia.learning.style_engine import StyleEngine
                se   = StyleEngine(ai.db)
                info = se.get_style_info()
                _show_response("\n".join(f"{k}: {v}" for k, v in info.items()), "cyan")
            except Exception as e:
                _print_line(f"[warn_cl]No disponible: {e}[/warn_cl]")
        elif raw == "/indice_personal":
            try:
                from cognia.memory.personal_index import PersonalIndex
                pi        = PersonalIndex(ai.db)
                conceptos = pi.list_concepts()
                if conceptos:
                    _show_response("\n".join(f"- {c}" for c in conceptos), "cyan")
                else:
                    _print_line("[detail]Indice vacio. Usa: /indice_add <concepto>[/detail]")
            except Exception as e:
                _print_line(f"[warn_cl]No disponible: {e}[/warn_cl]")
        elif raw.startswith("/indice_add "):
            concepto = raw[len("/indice_add "):].strip()
            if concepto:
                try:
                    from cognia.memory.personal_index import PersonalIndex
                    pi = PersonalIndex(ai.db)
                    _run(raw, lambda: pi.add_concept(concepto), color="bright_green")
                except Exception as e:
                    _print_line(f"[warn_cl]No disponible: {e}[/warn_cl]")
            else:
                _print_line("[warn_cl]Uso: /indice_add <concepto>[/warn_cl]")

        # -- Ingestion ------------------------------------------------------
        elif raw.startswith("/leer "):
            ruta = raw[len("/leer "):].strip()
            if ruta:
                from cognia.ingest import ingest_file
                _run(raw, lambda: ingest_file(ai, ruta), color="bright_green")
            else:
                _print_line("[warn_cl]Uso: /leer <ruta_al_archivo>[/warn_cl]")
        elif raw.startswith("/proyecto "):
            ruta = raw[len("/proyecto "):].strip()
            if ruta:
                from cognia.ingest import ingest_directory
                _run(raw, lambda: ingest_directory(ai, ruta), color="bright_green")
            else:
                _print_line("[warn_cl]Uso: /proyecto <ruta_al_directorio>[/warn_cl]")

        # -- Unknown slash --------------------------------------------------
        elif raw.startswith("/"):
            _print_line(
                f"[warn_cl]Comando desconocido: {_escape(raw)}[/warn_cl]"
                "  [detail](escribe /ayuda)[/detail]"
            )

        # -- Free text → articulated cognitive response --------------------
        else:
            try:
                from respuestas_articuladas import responder_articulado
                if _HAS_RICH and _console:
                    flt      = _VerboseFilter()
                    logging.root.addFilter(flt)
                    captured = io.StringIO()
                    try:
                        with _console.status("[spinner]Procesando...[/spinner]", spinner="dots"):
                            t0 = time.time()
                            with contextlib.redirect_stdout(captured):
                                result = responder_articulado(ai, raw)
                    finally:
                        logging.root.removeFilter(flt)
                    elapsed = time.time() - t0
                    if _debug_mode:
                        txt = captured.getvalue().strip()
                        if txt:
                            _console.print(txt, style="info_dim", markup=False)
                else:
                    t0      = time.time()
                    result  = responder_articulado(ai, raw)
                    elapsed = time.time() - t0

                if "error" in result:
                    _print_line(f"[err_cl]Error: {_escape(str(result['error']))}[/err_cl]")
                else:
                    _show_response(result["response"], "cyan")
                    _show_footer(elapsed, result["response"])
                    stage = result.get("language_engine", {}).get("stage", "")
                    if stage:
                        _print_line(f"[detail][stage: {stage}][/detail]")
                    _session_log.append({
                        "input":   raw,
                        "output":  result["response"],
                        "elapsed": elapsed,
                    })
            except Exception as e:
                _print_line(f"[err_cl]Error: {_escape(str(e))}[/err_cl]")


if __name__ == "__main__":
    repl()
