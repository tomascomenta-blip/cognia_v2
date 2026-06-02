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
import subprocess
import sys
import time
from pathlib import Path

from .cognia import Cognia
from .config import HAS_RESEARCH_ENGINE, HAS_PROGRAM_CREATOR

# ---------------------------------------------------------------------------
# Skills directory
# ---------------------------------------------------------------------------
_SKILLS_DIR = Path(__file__).parent.parent / "cognia_skills"

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
    "/aprende-repo":    "Aprender de un repo GitHub <url_o_query>",
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
    # Herramientas de sistema de archivos
    "/listar":          "Listar archivos            [directorio]",
    "/buscar":          "Buscar patron en archivos  <patron> [dir]",
    "/escribir":        "Escribir archivo           <ruta> <contenido>",
    "/editar":          "Editar archivo (replace)   <ruta> <buscar> | <reemplazo>",
    "/ejecutar":        "Ejecutar comando shell     <cmd>",
    "/diff":            "Explica los cambios git de un archivo <ruta>",
    "/hacer":           "Modo agente: ejecuta tarea con herramientas <tarea>",
    "/pensar":          "Razonamiento paso a paso sobre un tema <pregunta>",
    "/revisar":         "Revisa codigo de un archivo <ruta>",
    "/memoria-stats":   "Estadisticas de memoria y conocimiento acumulado",
    "/historial":       "Muestra tareas recientes del agente y archivos modificados",
    # Skills
    "/skills":          "Listar skills disponibles",
    "/skill-nuevo":     "Crear nueva skill              <nombre>",
    "/skill-cargar":    "Cargar y ejecutar skill        <nombre> [args]",
    # Plan
    "/plan":            "Crear plan de tareas con LLM  <objetivo>",
    "/plan-ver":        "Ver todos los planes activos",
    "/plan-ok":         "Marcar paso como completado   <id> <n>",
    "/plan-borrar":     "Eliminar un plan              <id>",
    # Herramientas nuevas
    "/monitor":         "Ejecutar cmd en background y ver output  <cmd>",
    "/powershell":      "Ejecutar comando PowerShell              <cmd>",
    "/tarea-crear":     "Crear tarea de sesion                    <desc>",
    "/tarea-lista":     "Listar tareas de sesion",
    "/tarea-ok":        "Marcar tarea completada                  <id>",
    "/tarea-borrar":    "Borrar tarea                             <id>",
    "/web-fetch":       "Descargar URL y convertir a texto        <url>",
    "/web-buscar":      "Buscar en la web (DuckDuckGo)            <query>",
    "/worktree":        "Crear git worktree en rama aislada       <rama>",
    "/notificar":       "Enviar notificacion de escritorio        <mensaje>",
    # UI
    "/limpiar":         "Limpiar pantalla",
    "/compactar":       "Resumir historial de sesión",
    "/resumir":         "Resume la conversacion actual y guarda en memoria",
    "/memoria":         "Estado de memoria y KG",
    "/modulos":         "Módulos activos en tiempo real",
    "/exportar":        "Exportar sesión a .md",
    "/modo rapido":     "Toggle: saltar confirmaciones",
    "/debug":           "Toggle: mostrar logs INFO",
    "/costo":           "Tokens y tiempo de sesión",
    "/tema":            "Ciclar tema visual",
}

# Public alias used by external tooling / tests
COMMANDS = _CMD_DESCRIPTIONS

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
    /aprende-repo <url_o_query>     Aprende de un repo GitHub por URL o busqueda
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

  HERRAMIENTAS DE SISTEMA DE ARCHIVOS:
    /listar [directorio]            Listar archivos (max 50)
    /buscar <patron> [dir]          Buscar patron en archivos (max 20 coincidencias)
    /escribir <ruta> <contenido>    Escribir texto a un archivo
    /editar <ruta> <buscar> | <r>   Reemplazar primera ocurrencia en archivo
    /ejecutar <cmd>                 Ejecutar comando shell (timeout 30s)

  SKILLS:
    /skills                         Listar skills disponibles
    /skill-nuevo <nombre>           Crear nueva skill
    /skill-cargar <nombre> [args]   Ejecutar skill con argumentos

  PLANES:
    /plan <objetivo>                Descomponer objetivo en pasos con IA
    /plan-ver                       Ver todos los planes
    /plan-ok <id> <n>               Marcar paso N como completado
    /plan-borrar <id>               Eliminar plan

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

def _strip_code_fences(text: str) -> str:
    """Remove markdown code fences that models wrap code in."""
    import re as _re
    text = text.strip()
    text = _re.sub(r'^```[a-zA-Z0-9_+-]*\n', '', text)
    text = _re.sub(r'\n?```\s*$', '', text)
    return text


_ANSI_GREEN = "\033[92m"
_ANSI_RED   = "\033[91m"
_ANSI_DIM   = "\033[2m"
_ANSI_RESET = "\033[0m"


def _show_file_diff(old_text: str, new_text: str, label: str, print_fn=None) -> None:
    import difflib
    _pf = print_fn or _print_line
    _esc = _escape if _HAS_RICH else (lambda s: s)
    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)
    short_label = label.replace("\\", "/").split("/")[-1]
    diff = list(difflib.unified_diff(old_lines, new_lines, fromfile=f"a/{short_label}", tofile=f"b/{short_label}", n=2))
    if not diff:
        return
    for dl in diff:
        dl_s = dl.rstrip("\n")
        if dl_s.startswith("+++ ") or dl_s.startswith("--- "):
            if _HAS_RICH:
                _pf(f"[detail]{_esc(dl_s)}[/detail]")
            else:
                _pf(f"{_ANSI_DIM}{dl_s}{_ANSI_RESET}")
        elif dl_s.startswith("@@"):
            if _HAS_RICH:
                _pf(f"[detail]{_esc(dl_s)}[/detail]")
            else:
                _pf(f"{_ANSI_DIM}{dl_s}{_ANSI_RESET}")
        elif dl_s.startswith("+"):
            if _HAS_RICH:
                _pf(f"[ok]+ {_esc(dl_s[1:])}[/ok]")
            else:
                _pf(f"{_ANSI_GREEN}+ {dl_s[1:]}{_ANSI_RESET}")
        elif dl_s.startswith("-"):
            if _HAS_RICH:
                _pf(f"[err_cl]- {_esc(dl_s[1:])}[/err_cl]")
            else:
                _pf(f"{_ANSI_RED}- {dl_s[1:]}{_ANSI_RESET}")
        else:
            if _HAS_RICH:
                _pf(f"[detail]  {_esc(dl_s[1:])}[/detail]")
            else:
                _pf(f"  {dl_s[1:]}")


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


def _slash_aprende_repo(ai, target: str) -> str:
    """Fetch a GitHub repo or search query and ingest into semantic memory."""
    import re as _re_ar
    try:
        from cognia.research_engine.github_scraper import GitHubScraper
    except ImportError:
        return "GitHubScraper no disponible."

    scraper = GitHubScraper()
    repos = []

    _url_pat = _re_ar.match(r'https?://github\.com/([^/]+/[^/\s?#]+)', target)
    if _url_pat:
        repo_path = _url_pat.group(1).rstrip('/')
        # Search by repo name as fallback since there's no direct fetch-by-name
        repos = scraper.search_repos(repo_path)
        if not repos:
            repos = scraper.search_repos(repo_path.split('/')[-1])
    else:
        repos = scraper.search_repos(target)

    if not repos:
        return f"No se encontraron repos para: {target}"

    stored = 0
    names = []
    for repo in repos:
        try:
            text = repo.to_learning_text()
            ai.observe(text[:600], provided_label=repo.label())
            stored += 1
            names.append(repo.repo_name)
        except Exception:
            pass

    if stored:
        return f"Aprendido de {stored} repo(s): {', '.join(names)}"
    return "No se pudo almacenar informacion de los repos."


# ---------------------------------------------------------------------------
# Plan helpers
# ---------------------------------------------------------------------------

_PLANS_PATH = Path.home() / ".cognia_plans.json"


def _plans_load() -> dict:
    if _PLANS_PATH.exists():
        try:
            import json as _j
            return _j.loads(_PLANS_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"plans": []}


def _plans_save(data: dict) -> None:
    import json as _j
    _PLANS_PATH.write_text(_j.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _plans_next_id(data: dict) -> str:
    ids = []
    for p in data.get("plans", []):
        try:
            ids.append(int(p["id"][1:]))
        except (ValueError, KeyError, IndexError):
            pass
    return f"p{max(ids) + 1 if ids else 1}"


def _slash_plan_crear(ai, goal: str) -> str:
    from shattering.orchestrator import ShatteringOrchestrator as _O
    orch = getattr(ai, '_orchestrator', None) or _O(mode='local')
    prompt = (
        f"Descompone este objetivo en 3 a 5 pasos concretos y accionables. "
        f"Devuelve SOLO una lista numerada, un paso por linea, sin introduccion ni conclusion.\n\n"
        f"Objetivo: {goal}"
    )
    result = orch.infer(prompt)
    raw_text = result.text.strip()
    steps = []
    for line in raw_text.splitlines():
        line = line.strip()
        if not line:
            continue
        import re as _re_plan
        line = _re_plan.sub(r'^[\d]+[.)]\s*|^[-*]\s*', '', line).strip()
        if line:
            steps.append({"text": line, "done": False})
    if not steps:
        return "No se pudo descomponer el objetivo. Intenta ser mas especifico."
    data = _plans_load()
    plan_id = _plans_next_id(data)
    import datetime as _dt
    data["plans"].append({
        "id": plan_id,
        "goal": goal,
        "created": _dt.datetime.now().isoformat(timespec="seconds"),
        "steps": steps,
    })
    _plans_save(data)
    lines = [f"Plan {plan_id}: {goal}", ""]
    for i, s in enumerate(steps, 1):
        lines.append(f"  [ ] {i}. {s['text']}")
    lines.append(f"\nUsa /plan-ok {plan_id} <n> para marcar un paso como completado.")
    return "\n".join(lines)


def _slash_plan_ver() -> str:
    data = _plans_load()
    plans = data.get("plans", [])
    if not plans:
        return "No hay planes activos. Crea uno con /plan <objetivo>."
    lines = []
    for p in plans:
        done_count = sum(1 for s in p["steps"] if s.get("done"))
        total = len(p["steps"])
        lines.append(f"[{p['id']}] {p['goal']}  ({done_count}/{total} pasos)")
        for i, s in enumerate(p["steps"], 1):
            mark = "[x]" if s.get("done") else "[ ]"
            lines.append(f"  {mark} {i}. {s['text']}")
        lines.append("")
    return "\n".join(lines).strip()


def _slash_plan_ok(plan_id: str, step_n: int) -> str:
    data = _plans_load()
    for p in data["plans"]:
        if p["id"] == plan_id:
            if step_n < 1 or step_n > len(p["steps"]):
                return f"Paso invalido. El plan {plan_id} tiene {len(p['steps'])} pasos."
            p["steps"][step_n - 1]["done"] = True
            _plans_save(data)
            done = sum(1 for s in p["steps"] if s.get("done"))
            total = len(p["steps"])
            return f"Paso {step_n} completado. ({done}/{total} pasos del plan {plan_id})"
    return f"Plan '{plan_id}' no encontrado."


def _slash_plan_borrar(plan_id: str) -> str:
    data = _plans_load()
    before = len(data["plans"])
    data["plans"] = [p for p in data["plans"] if p["id"] != plan_id]
    if len(data["plans"]) == before:
        return f"Plan '{plan_id}' no encontrado."
    _plans_save(data)
    return f"Plan {plan_id} eliminado."


# ---------------------------------------------------------------------------
# Skill helpers
# ---------------------------------------------------------------------------

def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Return (frontmatter_dict, body) from a skill .md file."""
    lines = text.splitlines()
    fm: dict = {}
    if not lines or lines[0].strip() != "---":
        return fm, text
    end = -1
    for i, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            end = i
            break
    if end == -1:
        return fm, text
    for line in lines[1:end]:
        if ":" in line:
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip()
    body = "\n".join(lines[end + 1:]).lstrip("\n")
    return fm, body


def _slash_skills():
    _SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(_SKILLS_DIR.glob("*.md"))
    if not files:
        _print_line("[detail]Sin skills. Crea una con /skill-nuevo <nombre>[/detail]")
        return
    lines = []
    for f in files:
        try:
            fm, _ = _parse_frontmatter(f.read_text(encoding="utf-8", errors="replace"))
            desc = fm.get("description", "")
        except OSError:
            desc = ""
        lines.append(f"  {f.stem:<20} {desc}")
    if _HAS_RICH and _console:
        from rich.markup import escape as _esc
        _console.print("[cyan]Skills disponibles:[/cyan]")
        for ln in lines:
            _console.print(f"[detail]{_esc(ln)}[/detail]")
    else:
        print("Skills disponibles:")
        for ln in lines:
            print(ln)


def _slash_skill_nuevo(nombre: str):
    if not nombre or not re.match(r'^[\w\-]+$', nombre):
        _print_line("[warn_cl]Nombre invalido. Solo letras, numeros, guiones.[/warn_cl]")
        return
    _SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    dest = _SKILLS_DIR / f"{nombre}.md"
    if dest.exists():
        _print_line(f"[warn_cl]Ya existe: {dest}[/warn_cl]")
        return
    template = (
        f"---\n"
        f"name: {nombre}\n"
        f"description: <descripcion de la skill>\n"
        f"---\n"
        f"\n"
        f"# Instrucciones\n"
        f"\n"
        f"<escribe aqui el prompt o instrucciones de la skill>\n"
        f"\n"
        f"## Ejemplo de uso\n"
        f"/skill-cargar {nombre} <input de ejemplo>\n"
    )
    dest.write_text(template, encoding="utf-8")
    _print_line(f"[ok]Skill creada:[/ok] [mod]{dest}[/mod]")
    try:
        if sys.platform == "win32":
            os.startfile(str(dest))
    except Exception:
        pass


def _slash_skill_cargar(ai, nombre: str, args: str):
    if not nombre or not re.match(r'^[\w\-]+$', nombre):
        _print_line("[warn_cl]Nombre invalido. Solo letras, numeros, guiones.[/warn_cl]")
        return
    skill_file = _SKILLS_DIR / f"{nombre}.md"
    if not skill_file.exists():
        _print_line(f"[err_cl]Skill no encontrada: {nombre}[/err_cl]")
        return
    try:
        text = skill_file.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        _print_line(f"[err_cl]No se pudo leer la skill: {e}[/err_cl]")
        return
    _, body = _parse_frontmatter(text)
    prompt = body.replace("{input}", args)
    _run(f"/skill-cargar {nombre}", lambda: _call_articulated(ai, prompt), color="magenta")


def _call_articulated(ai, prompt: str) -> str:
    try:
        from respuestas_articuladas import responder_articulado
        result = responder_articulado(ai, prompt)
        if "error" in result:
            return f"Error: {result['error']}"
        return result.get("response", "")
    except Exception as e:
        return f"Error: {e}"


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
            _print_line("[warn_cl]Uso: /investigar <query>  -- ejemplo: /investigar machine learning Python[/warn_cl]")
        elif raw.startswith("/aprende-repo "):
            _ar_target = raw[len("/aprende-repo "):].strip()
            _print_line("[detail]Buscando y aprendiendo de GitHub...[/detail]")
            _ar_result = _slash_aprende_repo(ai, _ar_target)
            _show_response(_ar_result, "bright_green")
        elif raw == "/aprende-repo":
            _print_line("[warn_cl]Uso: /aprende-repo <url_o_query>  -- ejemplo: /aprende-repo https://github.com/huggingface/transformers[/warn_cl]")
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
        elif raw == "/observar":
            _print_line("[warn_cl]Uso: /observar <texto>[/warn_cl]")
        elif raw.startswith("/aprender ") and "|" not in raw:
            _print_line("[warn_cl]Uso: /aprender <texto> | <etiqueta>[/warn_cl]")
        elif raw == "/aprender":
            _print_line("[warn_cl]Uso: /aprender <texto> | <etiqueta>[/warn_cl]")
        elif raw.startswith("/corregir ") and raw.count("|") >= 2:
            partes = raw[len("/corregir "):].split("|")
            _run(raw, lambda: ai.correct(
                partes[0].strip(), partes[1].strip(), partes[2].strip()), color="bright_green")
        elif raw.startswith("/corregir"):
            _print_line("[warn_cl]Uso: /corregir <obs> | <incorrecto> | <correcto>[/warn_cl]")
        elif raw.startswith("/hipotesis ") and "|" in raw:
            partes = raw[len("/hipotesis "):].split("|", 1)
            _run(raw, lambda: ai.generate_hypothesis(
                partes[0].strip(), partes[1].strip()), color="magenta")
        elif raw.startswith("/hipotesis"):
            _print_line("[warn_cl]Uso: /hipotesis <A> | <B>[/warn_cl]")
        elif raw.startswith("/explicar "):
            texto = raw[len("/explicar "):].strip()
            _run(raw, lambda: ai.explain(texto), color="magenta")
        elif raw == "/explicar":
            _print_line("[warn_cl]Uso: /explicar <texto>[/warn_cl]")
        elif raw.startswith("/grafo "):
            concepto = raw[len("/grafo "):].strip()
            _run(raw, lambda: ai.show_graph(concepto), color="cyan")
        elif raw == "/grafo":
            _print_line("[warn_cl]Uso: /grafo <concepto>[/warn_cl]")
        elif raw.startswith("/hecho ") and raw.count("|") >= 2:
            partes = raw[len("/hecho "):].split("|")
            _run(raw, lambda: ai.add_fact(
                partes[0].strip(), partes[1].strip(), partes[2].strip()), color="bright_green")
        elif raw.startswith("/hecho"):
            _print_line("[warn_cl]Uso: /hecho <sujeto> | <predicado> | <objeto>[/warn_cl]")
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

        # -- Herramientas de sistema de archivos ----------------------------
        elif raw.startswith("/listar"):
            _ruta = raw[len("/listar"):].strip() or "."
            _p = Path(_ruta)
            if not _p.exists():
                _print_line(f"[err_cl]No existe: {_ruta}[/err_cl]")
            elif not _p.is_dir():
                _print_line(f"[err_cl]No es un directorio: {_ruta}[/err_cl]")
            else:
                _entries = sorted(_p.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
                _shown = _entries[:50]
                for _e in _shown:
                    if _e.is_dir():
                        _print_line(f"[detail]  [dir]  {_e.name}/[/detail]")
                    else:
                        _sz = _e.stat().st_size
                        if _sz >= 1_048_576:
                            _szstr = f"{_sz/1_048_576:.1f} MB"
                        elif _sz >= 1024:
                            _szstr = f"{_sz/1024:.1f} KB"
                        else:
                            _szstr = f"{_sz} B"
                        _print_line(f"  [success_dim]{_e.name}[/success_dim]  [detail]({_szstr})[/detail]")
                if len(_entries) > 50:
                    _print_line(f"[warn_cl]... {len(_entries)-50} entradas omitidas (max 50)[/warn_cl]")
                _print_line(f"[detail]{min(len(_entries),50)}/{len(_entries)} entradas en {_ruta}[/detail]")

        elif raw.startswith("/buscar "):
            _rest = raw[len("/buscar "):].strip()
            if not _rest:
                _print_line("[warn_cl]Uso: /buscar <patron> [directorio][/warn_cl]")
            else:
                _parts = _rest.split(" ", 1)
                _pat = _parts[0]
                if len(_parts) > 1 and Path(_parts[1]).is_dir():
                    _sdir = Path(_parts[1])
                else:
                    _sdir = Path(".")
                    if len(_parts) > 1:
                        _pat = _rest  # entire rest is pattern
                _SKIP = {".git", "venv", "__pycache__", ".mypy_cache", "node_modules", ".tox"}
                _matches = []
                try:
                    _compiled = re.compile(_pat)
                except re.error as _re_err:
                    _print_line(f"[err_cl]Patron invalido: {_re_err}[/err_cl]")
                    _compiled = None
                if _compiled:
                    for _fp in _sdir.rglob("*"):
                        if any(s in _fp.parts for s in _SKIP):
                            continue
                        if not _fp.is_file():
                            continue
                        try:
                            _raw_bytes = _fp.read_bytes()
                            if b"\x00" in _raw_bytes[:8192]:
                                continue  # skip binary
                            _lines = _raw_bytes.decode("utf-8", errors="replace").splitlines()
                            for _lno, _ln in enumerate(_lines, 1):
                                if _compiled.search(_ln):
                                    _matches.append((_fp, _lno, _ln.strip()))
                                    if len(_matches) >= 20:
                                        break
                        except (OSError, PermissionError):
                            continue
                        if len(_matches) >= 20:
                            break
                    if not _matches:
                        _print_line(f"[detail]Sin coincidencias para '{_pat}'[/detail]")
                    else:
                        for _mf, _ml, _mc in _matches:
                            _print_line(f"  [success_dim]{_mf}[/success_dim][detail]:{_ml}:[/detail] {_escape(_mc)}")
                        if len(_matches) == 20:
                            _print_line("[warn_cl]... limite de 20 coincidencias alcanzado[/warn_cl]")

        elif raw.startswith("/escribir "):
            _rest = raw[len("/escribir "):].strip()
            if not _rest or " " not in _rest:
                _print_line("[warn_cl]Uso: /escribir <ruta> <contenido>[/warn_cl]")
            else:
                _wpath_str, _wcontent = _rest.split(" ", 1)
                _wpath = Path(_wpath_str).resolve()
                _cwd_resolved = Path.cwd().resolve()
                if not str(_wpath).startswith(str(_cwd_resolved)):
                    _print_line(f"[err_cl]Ruta fuera del directorio de trabajo: {_escape(_wpath_str)}[/err_cl]")
                    _wpath = None
                if _wpath is not None and _wpath.exists() and not _fast_mode:
                    _print_line(f"[warn_cl]El archivo ya existe: {_wpath}. Sobreescribir? (s/n)[/warn_cl]")
                    try:
                        _confirm = input("> ").strip().lower()
                    except (EOFError, KeyboardInterrupt):
                        _confirm = "n"
                    if _confirm not in ("s", "si", "y", "yes"):
                        _print_line("[detail]Operacion cancelada.[/detail]")
                        _wpath = None
                if _wpath is not None:
                    try:
                        _wpath.parent.mkdir(parents=True, exist_ok=True)
                        _wcontent = _strip_code_fences(_wcontent)
                        _wold = _wpath.read_text(encoding="utf-8") if _wpath.exists() else ""
                        _wpath.write_text(_wcontent, encoding="utf-8")
                        _wsz = _wpath.stat().st_size
                        _show_file_diff(_wold, _wcontent, str(_wpath))
                        _print_line(f"[ok]Escrito: {_wpath} ({_wsz} bytes)[/ok]")
                    except (OSError, PermissionError) as _we:
                        _print_line(f"[err_cl]Error al escribir: {_we}[/err_cl]")

        elif raw.startswith("/editar "):
            _rest = raw[len("/editar "):].strip()
            if not _rest or " " not in _rest:
                _print_line("[warn_cl]Uso: /editar <ruta> <buscar> | <reemplazo>[/warn_cl]")
            else:
                _epath_str, _erest = _rest.split(" ", 1)
                if " | " not in _erest:
                    _print_line("[warn_cl]Separador ' | ' requerido entre buscar y reemplazo[/warn_cl]")
                else:
                    _esearch, _ereplace = _erest.split(" | ", 1)
                    _epath = Path(_epath_str).resolve()
                    if not str(_epath).startswith(str(Path.cwd().resolve())):
                        _print_line(f"[err_cl]Ruta fuera del directorio de trabajo: {_escape(_epath_str)}[/err_cl]")
                    elif not _epath.is_file():
                        _print_line(f"[err_cl]Archivo no encontrado: {_epath}[/err_cl]")
                    else:
                        try:
                            _eoriginal = _epath.read_text(encoding="utf-8")
                            if _esearch not in _eoriginal:
                                _print_line(f"[warn_cl]Patron no encontrado en {_epath}[/warn_cl]")
                            else:
                                _enew = _eoriginal.replace(_esearch, _ereplace, 1)
                                _print_line(f"[detail]Diff en {_epath}:[/detail]")
                                _show_file_diff(_eoriginal, _enew, str(_epath))
                                if not _fast_mode:
                                    _print_line("[warn_cl]Confirmar escritura? (s/n)[/warn_cl]")
                                    try:
                                        _econfirm = input("> ").strip().lower()
                                    except (EOFError, KeyboardInterrupt):
                                        _econfirm = "n"
                                else:
                                    _econfirm = "s"
                                if _econfirm in ("s", "si", "y", "yes"):
                                    _epath.write_text(_enew, encoding="utf-8")
                                    _print_line(f"[success_dim]Guardado: {_epath}[/success_dim]")
                                else:
                                    _print_line("[detail]Operacion cancelada.[/detail]")
                        except (OSError, PermissionError) as _ee:
                            _print_line(f"[err_cl]Error al editar: {_ee}[/err_cl]")

        elif raw.startswith("/ejecutar "):
            _cmd = raw[len("/ejecutar "):].strip()
            _BLOCKED = [
                "rm -rf", "format", "del /s", "del /q", "del /f",
                ":(){:|:&};:", "python -c", "python3 -c", "powershell",
                "mkfs", "dd if=", "> /dev/", "shutdown", "reboot",
            ]
            _cmd_lower = _cmd.lower()
            # collapse repeated spaces so "rm  -rf" doesn't bypass "rm -rf"
            import re as _re_sec
            _cmd_normalized = _re_sec.sub(r"\s+", " ", _cmd_lower)
            if any(_b in _cmd_normalized for _b in _BLOCKED):
                _print_line(f"[err_cl]Comando bloqueado por seguridad: {_escape(_cmd)}[/err_cl]")
            else:
                _print_line(f"[detail][ejecutar] $ {_escape(_cmd)}[/detail]")
                try:
                    _proc = subprocess.run(
                        _cmd,
                        shell=True,
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                    _out = (_proc.stdout + _proc.stderr).strip()
                    _out_lines = _out.splitlines()
                    for _ol in _out_lines[:50]:
                        _print_line(f"  {_escape(_ol)}")
                    if len(_out_lines) > 50:
                        _print_line(f"[warn_cl]... {len(_out_lines)-50} lineas omitidas (max 50)[/warn_cl]")
                    if _proc.returncode != 0:
                        _print_line(f"[warn_cl]Codigo de salida: {_proc.returncode}[/warn_cl]")
                except subprocess.TimeoutExpired:
                    _print_line("[err_cl]Timeout: el comando excedio 30 segundos[/err_cl]")
                except Exception as _xe:
                    _print_line(f"[err_cl]Error al ejecutar: {_escape(str(_xe))}[/err_cl]")

        # -- Git diff ------------------------------------------------------
        elif raw.startswith("/diff "):
            _diff_target = raw[len("/diff "):].strip()
            try:
                import subprocess as _sp_diff
                _diff_out = _sp_diff.run(
                    ["git", "diff", "HEAD", "--", _diff_target],
                    capture_output=True, text=True, timeout=10
                ).stdout
                if not _diff_out.strip():
                    _diff_out = _sp_diff.run(
                        ["git", "diff", "--cached", "--", _diff_target],
                        capture_output=True, text=True, timeout=10
                    ).stdout
                if not _diff_out.strip():
                    _print_line(f"[detail]Sin cambios git para: {_diff_target}[/detail]")
                else:
                    _diff_prompt = (
                        f"Analiza este git diff y explica los cambios en 3-5 puntos clave. "
                        f"Se conciso y enfocado en el impacto:\n\n{_diff_out[:3000]}"
                    )
                    from shattering.orchestrator import ShatteringOrchestrator as _O
                    _orch_d = getattr(ai, '_orchestrator', None) or _O(mode='local')
                    _diff_result = _orch_d.infer(_diff_prompt)
                    _show_response(_diff_result.text, "cyan")
            except FileNotFoundError:
                _print_line("[err_cl]git no disponible en PATH[/err_cl]")
            except Exception as _de:
                _print_line(f"[err_cl]Error en diff: {_de}[/err_cl]")
        elif raw == "/diff":
            _print_line("[warn_cl]Uso: /diff <archivo>  -- ejemplo: /diff cognia/cli.py[/warn_cl]")

        # -- Skills --------------------------------------------------------
        elif raw == "/skills":
            _slash_skills()
        elif raw.startswith("/skill-nuevo"):
            _nombre = raw[len("/skill-nuevo"):].strip()
            if _nombre:
                _slash_skill_nuevo(_nombre)
            else:
                _print_line("[warn_cl]Uso: /skill-nuevo <nombre>[/warn_cl]")
        elif raw.startswith("/skill-cargar"):
            _rest = raw[len("/skill-cargar"):].strip()
            if not _rest:
                _print_line("[warn_cl]Uso: /skill-cargar <nombre> [args][/warn_cl]")
            else:
                _parts2 = _rest.split(" ", 1)
                _sname = _parts2[0]
                _sargs = _parts2[1] if len(_parts2) > 1 else ""
                _slash_skill_cargar(ai, _sname, _sargs)

        # -- Agent mode -----------------------------------------------------
        elif raw.startswith("/hacer "):
            _tarea = raw[len("/hacer "):].strip()
            if _tarea:
                _print_line("[detail]Iniciando agente...[/detail]")
                _resp = _run_agent_task(ai, _tarea, _print_line)
                _show_response(_resp, "cyan")
                _session_log.append({"input": raw, "output": _resp, "elapsed": 0})
            else:
                _print_line("[warn_cl]Uso: /hacer <descripcion de la tarea>[/warn_cl]")

        # -- Plan system ---------------------------------------------------
        elif raw.startswith("/plan ") and not raw.startswith("/plan-"):
            _plan_goal = raw[len("/plan "):].strip()
            if _plan_goal:
                _print_line("[detail]Descomponiendo objetivo...[/detail]")
                _plan_result = _slash_plan_crear(ai, _plan_goal)
                _show_response(_plan_result, "bright_cyan")
            else:
                _print_line("[warn_cl]Uso: /plan <objetivo>[/warn_cl]")
        elif raw == "/plan-ver" or raw == "/plan":
            _show_response(_slash_plan_ver(), "cyan")
        elif raw.startswith("/plan-ok "):
            _plan_parts = raw[len("/plan-ok "):].strip().split()
            if len(_plan_parts) >= 2:
                try:
                    _show_response(_slash_plan_ok(_plan_parts[0], int(_plan_parts[1])), "bright_green")
                except ValueError:
                    _print_line("[warn_cl]Uso: /plan-ok <id> <n>  -- n debe ser un numero[/warn_cl]")
            else:
                _print_line("[warn_cl]Uso: /plan-ok <id> <n>  -- ejemplo: /plan-ok p1 2[/warn_cl]")
        elif raw == "/plan-ok":
            _print_line("[warn_cl]Uso: /plan-ok <id> <n>  -- ejemplo: /plan-ok p1 2[/warn_cl]")
        elif raw.startswith("/plan-borrar "):
            _pb_id = raw[len("/plan-borrar "):].strip()
            if _pb_id:
                _show_response(_slash_plan_borrar(_pb_id), "yellow")
            else:
                _print_line("[warn_cl]Uso: /plan-borrar <id>  -- ejemplo: /plan-borrar p1[/warn_cl]")
        elif raw == "/plan-borrar":
            _print_line("[warn_cl]Uso: /plan-borrar <id>[/warn_cl]")

        # -- Deep reasoning ------------------------------------------------
        elif raw.startswith("/pensar ") or raw == "/pensar":
            _q = raw[len("/pensar"):].strip()
            if not _q:
                _print_line("[warn_cl]Uso: /pensar <pregunta>[/warn_cl]")
            else:
                _print_line("[detail]Iniciando razonamiento profundo...[/detail]")
                try:
                    from shattering.orchestrator import ShatteringOrchestrator as _O
                    _orch_p = getattr(ai, '_orchestrator', None) or _O(mode='local')
                    _cot_prompt = (
                        f"Razona paso a paso sobre la siguiente pregunta. "
                        f"Para cada paso, escribe 'Paso N:' seguido de tu razonamiento. "
                        f"Al final escribe 'Conclusion:' con tu respuesta final.\n\n"
                        f"Pregunta: {_q}"
                    )
                    _cot_result = _orch_p.infer(_cot_prompt)
                    _cot_text = _cot_result.text.strip()
                    for _line in _cot_text.split('\n'):
                        if _line.strip():
                            if _line.strip().startswith('Paso ') or _line.strip().startswith('Conclusion'):
                                _print_line(f"[bold]{_line.strip()}[/bold]")
                            else:
                                _print_line(_line.strip())
                    try:
                        _summary = f"Razonamiento sobre: {_q[:80]} | {_cot_text[:200]}"
                        ai.observe(_summary, provided_label="razonamiento_profundo")
                    except Exception:
                        pass
                except Exception as _pe:
                    _print_line(f"[err_cl]Error en razonamiento: {_pe}[/err_cl]")

        # -- Agent history --------------------------------------------------
        elif raw == "/historial":
            _AGENT_STATE_PATH = Path.home() / ".cognia_agent_state.json"
            try:
                import json as _json_h
                _st = _json_h.loads(_AGENT_STATE_PATH.read_text(encoding="utf-8"))
                if _st.get("tasks"):
                    _print_line("[bold]Tareas recientes del agente:[/bold]")
                    for _t in reversed(_st["tasks"]):
                        _print_line(f"  [{_t.get('ts','?')}] {_t['task'][:60]} ({_t.get('steps',0)} pasos)")
                        _print_line(f"    -> {_t['result'][:100]}")
                else:
                    _print_line("Sin historial de tareas.")
                if _st.get("files_touched"):
                    _print_line(f"[bold]Archivos tocados:[/bold] {', '.join(_st['files_touched'][-5:])}")
            except FileNotFoundError:
                _print_line("Sin historial. Usa /hacer <tarea> primero.")
            except Exception as _e:
                _print_line(f"[err_cl]Error leyendo historial: {_e}[/err_cl]")

        # -- Conversation summary -------------------------------------------
        elif raw == "/resumir":
            try:
                from shattering.orchestrator import ShatteringOrchestrator as _O
                _orch_r = getattr(ai, '_orchestrator', None) or _O(mode='local')
                _hist_snippet = []
                for _entry in _session_log[-6:]:
                    _hist_snippet.append(f"Usuario: {_entry['input'][:80]}")
                    _hist_snippet.append(f"Cognia: {_entry['output'][:80]}")
                if not _hist_snippet:
                    _print_line("No hay historial de conversacion para resumir.")
                else:
                    _summary_prompt = (
                        "Resume esta conversacion en 2-3 oraciones, destacando los temas clave:\n\n"
                        + "\n".join(_hist_snippet)
                        + "\n\nResumen:"
                    )
                    _sum_result = _orch_r.infer(_summary_prompt)
                    _summary_text = _sum_result.text.strip()
                    try:
                        ai.observe(_summary_text, provided_label="resumen_sesion")
                    except Exception:
                        pass
                    _print_line("[success_dim]Resumen guardado en memoria:[/success_dim]")
                    _print_line(_summary_text)
            except Exception as _re:
                _print_line(f"[err_cl]Error al resumir: {_re}[/err_cl]")

        # -- Code review ----------------------------------------------------
        elif raw.startswith("/revisar "):
            _ruta_rev = raw[len("/revisar "):].strip()
            _p_rev = Path(_ruta_rev)
            if not _p_rev.exists():
                _print_line(f"[err_cl]No existe: {_ruta_rev}[/err_cl]")
            elif not _p_rev.is_file():
                _print_line(f"[err_cl]No es un archivo: {_ruta_rev}[/err_cl]")
            else:
                try:
                    _code = _p_rev.read_text(encoding="utf-8", errors="replace")
                    if len(_code) > 8000:
                        _code = _code[:8000] + "\n... (truncado)"
                    _ext = _p_rev.suffix.lower()
                    _lang = {
                        "py": "Python", "js": "JavaScript", "ts": "TypeScript",
                        "c": "C", "cpp": "C++", "rs": "Rust", "go": "Go",
                    }.get(_ext.lstrip("."), "codigo")
                    _review_prompt = (
                        f"Eres un revisor de codigo experto. Analiza este archivo {_lang} "
                        f"y proporciona una revision estructurada con:\n"
                        f"1. Resumen (1 oracion)\n"
                        f"2. Problemas criticos (si los hay)\n"
                        f"3. Mejoras sugeridas (max 3)\n"
                        f"4. Puntos positivos (max 2)\n\n"
                        f"Archivo: {_p_rev.name}\n\n```{_ext.lstrip('.')}\n{_code}\n```\n\n"
                        f"Revision:"
                    )
                    from shattering.orchestrator import ShatteringOrchestrator as _O
                    _orch_rev = getattr(ai, '_orchestrator', None) or _O(mode='local')
                    _print_line(f"[detail]Revisando {_p_rev.name}...[/detail]")
                    _rev_result = _orch_rev.infer(_review_prompt)
                    _show_response(_rev_result.text, "cyan")
                    try:
                        ai.observe(
                            f"Revision de {_p_rev.name}: {_rev_result.text[:200]}",
                            provided_label="revision_codigo",
                        )
                    except Exception:
                        pass
                except Exception as _re:
                    _print_line(f"[err_cl]Error al revisar: {_re}[/err_cl]")

        # -- Memory stats dashboard -----------------------------------------
        elif raw == "/memoria-stats":
            try:
                _ms_lines = []
                try:
                    ep_count = ai.episodic.count()
                    _ms_lines.append(f"Episodios guardados: {ep_count}")
                except Exception:
                    pass
                try:
                    _ms_lines.append(f"Observaciones en esta sesion: {ai._session_observations}")
                except Exception:
                    pass
                try:
                    _ms_lines.append(f"Total interacciones: {ai.interaction_count}")
                except Exception:
                    pass
                try:
                    cryst = ai.semantic.get_crystallized()
                    if cryst:
                        _ms_lines.append(
                            f"Conceptos cristalizados ({len(cryst)}): "
                            + ", ".join(c["concept"] for c in cryst[:8])
                        )
                    else:
                        _ms_lines.append("Conceptos cristalizados: ninguno aun (necesitan support>=5)")
                except Exception:
                    pass
                try:
                    all_concepts = ai.semantic.list_all()
                    if all_concepts:
                        _top = sorted(all_concepts, key=lambda x: x.get("confidence", 0), reverse=True)[:5]
                        _ms_lines.append(
                            "Top conceptos semanticos: "
                            + ", ".join(
                                f"{c['concept']} ({c.get('confidence', 0):.2f})"
                                for c in _top
                            )
                        )
                except Exception:
                    pass
                try:
                    from storage.db_pool import db_connect_pooled as _dcp
                    _conn = _dcp(ai.db)
                    _cur = _conn.cursor()
                    _cur.execute("SELECT COUNT(*) FROM contradictions")
                    _cont_count = _cur.fetchone()[0]
                    _conn.close()
                    _ms_lines.append(f"Contradicciones detectadas: {_cont_count}")
                except Exception:
                    pass
                if _ms_lines:
                    _show_response("\n".join(_ms_lines), "cyan")
                else:
                    _print_line("[detail]No hay estadisticas disponibles.[/detail]")
            except Exception as _e:
                _print_line(f"[err_cl]Error: {_e}[/err_cl]")

        # ── /monitor <cmd> ────────────────────────────────────────────
        elif raw.startswith("/monitor "):
            _mon_cmd = raw[len("/monitor "):].strip()
            if not _mon_cmd:
                _print_line("[warn_cl]Uso: /monitor <comando>[/warn_cl]")
            else:
                import subprocess as _sp, threading as _th
                _print_line(f"[detail]Monitoreando: {_escape(_mon_cmd)}  (Ctrl+C para parar)[/detail]")
                try:
                    _mon_proc = _sp.Popen(
                        _mon_cmd, shell=True, stdout=_sp.PIPE, stderr=_sp.STDOUT,
                        text=True, encoding="utf-8", errors="replace",
                    )
                    try:
                        for _line in _mon_proc.stdout:
                            _print_line(_line.rstrip())
                    except KeyboardInterrupt:
                        _mon_proc.terminate()
                        _print_line("[detail]Monitor detenido.[/detail]")
                    _mon_proc.wait()
                    _print_line(f"[detail]Proceso terminado (exit {_mon_proc.returncode})[/detail]")
                except Exception as _e:
                    _print_line(f"[err_cl]Error en monitor: {_e}[/err_cl]")

        # ── /powershell <cmd> ──────────────────────────────────────────
        elif raw.startswith("/powershell "):
            _ps_cmd = raw[len("/powershell "):].strip()
            if not _ps_cmd:
                _print_line("[warn_cl]Uso: /powershell <comando>[/warn_cl]")
            else:
                import subprocess as _sp, sys as _sys
                _ps_exe = "powershell.exe" if _sys.platform == "win32" else "pwsh"
                try:
                    _ps_res = _sp.run(
                        [_ps_exe, "-NonInteractive", "-Command", _ps_cmd],
                        capture_output=True, text=True, timeout=120,
                        encoding="utf-8", errors="replace",
                    )
                    _out = (_ps_res.stdout + _ps_res.stderr).strip()
                    _show_response(_out or f"(exit {_ps_res.returncode})", "green")
                except Exception as _e:
                    _print_line(f"[err_cl]PowerShell error: {_e}[/err_cl]")

        # ── /tarea-crear /tarea-lista /tarea-ok /tarea-borrar ──────────
        elif raw.startswith("/tarea-crear ") or raw == "/tarea-crear":
            _tdesc = raw[len("/tarea-crear "):].strip() if raw.startswith("/tarea-crear ") else ""
            if not _tdesc:
                _print_line("[warn_cl]Uso: /tarea-crear <descripcion>[/warn_cl]")
            else:
                if not hasattr(ai, "_session_tasks"):
                    ai._session_tasks = []
                _tid = len(ai._session_tasks) + 1
                ai._session_tasks.append({"id": _tid, "desc": _tdesc, "done": False})
                _print_line(f"[ok_cl]Tarea #{_tid} creada: {_escape(_tdesc)}[/ok_cl]")

        elif raw == "/tarea-lista":
            if not getattr(ai, "_session_tasks", None):
                _print_line("[detail]No hay tareas en esta sesion.[/detail]")
            else:
                _tlines = []
                for _t in ai._session_tasks:
                    _status = "[OK]" if _t["done"] else "[ ]"
                    _tlines.append(f"  {_status} #{_t['id']} {_t['desc']}")
                _show_response("\n".join(_tlines), "cyan")

        elif raw.startswith("/tarea-ok ") or raw == "/tarea-ok":
            _tok_id = raw[len("/tarea-ok "):].strip() if raw.startswith("/tarea-ok ") else ""
            if not _tok_id:
                _print_line("[warn_cl]Uso: /tarea-ok <id>[/warn_cl]")
            else:
                try:
                    _tok_n = int(_tok_id)
                    _found = next((t for t in getattr(ai, "_session_tasks", []) if t["id"] == _tok_n), None)
                    if _found:
                        _found["done"] = True
                        _print_line(f"[ok_cl]Tarea #{_tok_n} completada.[/ok_cl]")
                    else:
                        _print_line(f"[warn_cl]Tarea #{_tok_n} no encontrada.[/warn_cl]")
                except ValueError:
                    _print_line("[warn_cl]El id debe ser un numero.[/warn_cl]")

        elif raw.startswith("/tarea-borrar ") or raw == "/tarea-borrar":
            _tbid = raw[len("/tarea-borrar "):].strip() if raw.startswith("/tarea-borrar ") else ""
            if not _tbid:
                _print_line("[warn_cl]Uso: /tarea-borrar <id>[/warn_cl]")
            else:
                try:
                    _tbn = int(_tbid)
                    _before = len(getattr(ai, "_session_tasks", []))
                    ai._session_tasks = [t for t in getattr(ai, "_session_tasks", []) if t["id"] != _tbn]
                    if len(ai._session_tasks) < _before:
                        _print_line(f"[ok_cl]Tarea #{_tbn} eliminada.[/ok_cl]")
                    else:
                        _print_line(f"[warn_cl]Tarea #{_tbn} no encontrada.[/warn_cl]")
                except ValueError:
                    _print_line("[warn_cl]El id debe ser un numero.[/warn_cl]")

        # ── /web-fetch <url> ───────────────────────────────────────────
        elif raw.startswith("/web-fetch ") or raw == "/web-fetch":
            _wf_url = raw[len("/web-fetch "):].strip() if raw.startswith("/web-fetch ") else ""
            if not _wf_url or not _wf_url.startswith("http"):
                _print_line("[warn_cl]Uso: /web-fetch <url>  (debe empezar con http)[/warn_cl]")
            else:
                try:
                    import urllib.request as _ur, html as _html_mod
                    _req = _ur.Request(
                        _wf_url,
                        headers={"User-Agent": "CogniaBot/1.0 (+cognia-ai)"},
                    )
                    with _ur.urlopen(_req, timeout=15) as _resp:
                        _raw_bytes = _resp.read(1_000_000)
                    _ct = _resp.headers.get("content-type", "")
                    _text = _raw_bytes.decode("utf-8", errors="replace")
                    # Strip HTML tags to plain text
                    import re as _re2
                    _text = _re2.sub(r"<style[^>]*>.*?</style>", " ", _text, flags=_re2.DOTALL | _re2.IGNORECASE)
                    _text = _re2.sub(r"<script[^>]*>.*?</script>", " ", _text, flags=_re2.DOTALL | _re2.IGNORECASE)
                    _text = _re2.sub(r"<[^>]+>", " ", _text)
                    _text = _re2.sub(r"\s{3,}", "\n\n", _text).strip()
                    _text = _html_mod.unescape(_text)
                    _preview = _text[:3000]
                    _show_response(f"[{_wf_url}]\n\n{_preview}", "cyan")
                    # Inject into session context
                    try:
                        ai.observe(f"Contenido de {_wf_url}:\n{_text[:500]}", provided_label="web_fetch")
                    except Exception:
                        pass
                except Exception as _e:
                    _print_line(f"[err_cl]web-fetch error: {_e}[/err_cl]")

        # ── /web-buscar <query> ────────────────────────────────────────
        elif raw.startswith("/web-buscar ") or raw == "/web-buscar":
            _wb_q = raw[len("/web-buscar "):].strip() if raw.startswith("/web-buscar ") else ""
            if not _wb_q:
                _print_line("[warn_cl]Uso: /web-buscar <query>[/warn_cl]")
            else:
                try:
                    import urllib.request as _ur2, urllib.parse as _up2, json as _json2
                    _enc_q = _up2.quote_plus(_wb_q)
                    # DDG Instant Answer API — free, no auth, no scraping
                    _ddg_api = f"https://api.duckduckgo.com/?q={_enc_q}&format=json&no_redirect=1&no_html=1&skip_disambig=1"
                    _req2 = _ur2.Request(_ddg_api, headers={"User-Agent": "CogniaBot/1.0"})
                    with _ur2.urlopen(_req2, timeout=15) as _r2:
                        _data2 = _json2.loads(_r2.read())
                    _lines2 = [f"Resultados para: {_wb_q}\n"]
                    _abstract = _data2.get("Abstract", "").strip()
                    if _abstract:
                        _src = _data2.get("AbstractURL", "")
                        _lines2.append(f"Resumen: {_abstract[:300]}")
                        if _src:
                            _lines2.append(f"Fuente: {_src}\n")
                    _direct_results = _data2.get("Results", [])
                    for _i, _r in enumerate(_direct_results[:5], 1):
                        _lines2.append(f"{_i}. {_r.get('Text','')[:80]}")
                        _lines2.append(f"   {_r.get('FirstURL','')}")
                    _related = [t for t in _data2.get("RelatedTopics", [])
                                if isinstance(t, dict) and t.get("Text")]
                    if _related and not _direct_results:
                        _lines2.append("Temas relacionados:")
                        for _rr in _related[:6]:
                            _lines2.append(f"  - {_rr['Text'][:90]}")
                    if len(_lines2) <= 1:
                        _lines2.append("(Sin resultados directos — prueba otra busqueda)")
                    _show_response("\n".join(_lines2), "cyan")
                except Exception as _e:
                    _print_line(f"[err_cl]web-buscar error: {_e}[/err_cl]")

        # ── /worktree <rama> ───────────────────────────────────────────
        elif raw.startswith("/worktree ") or raw == "/worktree":
            _wt_rama = raw[len("/worktree "):].strip() if raw.startswith("/worktree ") else ""
            if not _wt_rama:
                _print_line("[warn_cl]Uso: /worktree <nombre-rama>[/warn_cl]")
            else:
                import subprocess as _sp2
                _wt_path = f"../{_wt_rama}-worktree"
                try:
                    _r1 = _sp2.run(
                        ["git", "worktree", "add", "-b", _wt_rama, _wt_path],
                        capture_output=True, text=True, cwd=".",
                    )
                    if _r1.returncode == 0:
                        _print_line(f"[ok_cl]Worktree creado en {_wt_path} (rama: {_wt_rama})[/ok_cl]")
                        _print_line(f"[detail]Usa: cd {_wt_path}  para trabajar ahi[/detail]")
                    else:
                        _print_line(f"[err_cl]{_r1.stderr.strip()}[/err_cl]")
                except Exception as _e:
                    _print_line(f"[err_cl]worktree error: {_e}[/err_cl]")

        # ── /notificar <mensaje> ───────────────────────────────────────
        elif raw.startswith("/notificar ") or raw == "/notificar":
            _notif_msg = raw[len("/notificar "):].strip() if raw.startswith("/notificar ") else ""
            if not _notif_msg:
                _print_line("[warn_cl]Uso: /notificar <mensaje>[/warn_cl]")
            else:
                import sys as _sys2
                try:
                    if _sys2.platform == "win32":
                        import subprocess as _sp3
                        _ps_notif = (
                            f"Add-Type -AssemblyName System.Windows.Forms; "
                            f"[System.Windows.Forms.MessageBox]::Show('{_notif_msg}', 'Cognia')"
                        )
                        _sp3.Popen(
                            ["powershell.exe", "-WindowStyle", "Hidden", "-Command", _ps_notif],
                            creationflags=0x08000000,  # CREATE_NO_WINDOW
                        )
                        _print_line(f"[ok_cl]Notificacion enviada: {_escape(_notif_msg)}[/ok_cl]")
                    else:
                        import subprocess as _sp3
                        _sp3.Popen(["notify-send", "Cognia", _notif_msg])
                        _print_line(f"[ok_cl]Notificacion enviada: {_escape(_notif_msg)}[/ok_cl]")
                except Exception as _e:
                    _print_line(f"[err_cl]notificar error: {_e}[/err_cl]")

        # -- Unknown slash --------------------------------------------------
        elif raw.startswith("/"):
            _print_line(
                f"[warn_cl]Comando desconocido: {_escape(raw)}[/warn_cl]"
                "  [detail](escribe /ayuda)[/detail]"
            )

        # -- Free text → articulated cognitive response --------------------
        else:
            # Fast-path: stream tokens from llama.cpp if available
            _streamed = False
            try:
                from shattering.orchestrator import ShatteringOrchestrator as _SO
                _orch_cli = getattr(ai, '_orchestrator', None)
                if _orch_cli is None:
                    try:
                        _orch_cli = _SO(mode='local')
                    except Exception:
                        _orch_cli = None
                if _orch_cli is not None:
                    _llama = getattr(_orch_cli, '_llama', None)
                    if _llama is None:
                        try:
                            _orch_cli._try_load_llama()
                            _llama = getattr(_orch_cli, '_llama', None)
                        except Exception:
                            pass
                    if _llama is not None:
                        from node.inference_pipeline import _apply_qwen_template
                        _system = "Eres Cognia, un sistema de IA con memoria episodica y grafo de conocimiento."
                        _formatted = _apply_qwen_template(raw, _system)
                        _tokens_buf = []
                        t0 = time.time()
                        try:
                            print("", flush=True)
                            for _tok in _llama.stream_generate(_formatted, max_tokens=512):
                                _tokens_buf.append(_tok)
                                if _HAS_RICH and _console:
                                    _console.print(_tok, end="", style="cyan", highlight=False)
                                else:
                                    print(_tok, end="", flush=True)
                            print()
                            _streamed = True
                            _full_response = "".join(_tokens_buf)
                            elapsed = time.time() - t0
                            _show_footer(elapsed, _full_response)
                            _session_log.append({
                                "input":   raw,
                                "output":  _full_response,
                                "elapsed": elapsed,
                            })
                            try:
                                ai.observe(_full_response[:300], provided_label="respuesta_streaming")
                            except Exception:
                                pass
                        except Exception as _se:
                            if _tokens_buf:
                                _streamed = True  # partial stream — don't retry
                            print()
            except Exception:
                pass

            if not _streamed:
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


def _run_agent_task(ai, task: str, _print_fn, max_steps: int = 8) -> str:
    """
    ReAct-style agent loop. Uses the orchestrator LLM to plan tool calls,
    executes them, feeds results back, until DONE or max_steps.
    """
    TOOLS_DOC = """You are an autonomous agent. Start your reply with ACCION: on the first line.

ACCION: <tool> <args>

Tools (ONLY these — do NOT invent others):
  leer_archivo <path>
  escribir_archivo <path> | <content>   (content can be multiple lines of real code)
  buscar <pattern> | <directory>
  listar <directory>
  ejecutar <shell command>
  memorizar <text>
  responder <final answer>

Rules:
- escribir_archivo auto-creates directories. Do NOT use mkdir.
- For escribir_archivo, write COMPLETE, REAL code after the | separator (multiple lines ok).
- Use responder only when the task is fully done.
- No explanations outside the ACCION line."""

    # Load persistent agent state
    _AGENT_STATE_PATH = Path.home() / ".cognia_agent_state.json"
    _agent_state: dict = {"tasks": [], "files_touched": [], "key_facts": []}
    try:
        if _AGENT_STATE_PATH.exists():
            import json as _json
            _agent_state = _json.loads(_AGENT_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass

    # Capture files known before this task starts
    _prior_files_touched = list(_agent_state.get("files_touched", []))

    # Build prior context from last 2 tasks
    _prior_ctx = ""
    if _agent_state["tasks"]:
        _prior_lines = []
        for _t in _agent_state["tasks"][-2:]:
            _prior_lines.append(f"- Tarea anterior: {_t['task'][:80]} -> {_t['result'][:120]}")
        _prior_ctx = "CONTEXTO PREVIO:\n" + "\n".join(_prior_lines) + "\n\n"

    history = [f"{_prior_ctx}TAREA: {task}"]
    result_text = ""
    step = 0

    for step in range(max_steps):
        # last 6 history entries to avoid context overflow
        ctx = "\n".join(history[-6:])
        prompt = f"{TOOLS_DOC}\n\nContexto de la tarea:\n{ctx}\n\nSiguiente ACCION:"

        try:
            from shattering.orchestrator import ShatteringOrchestrator as Orchestrator
            orch = getattr(ai, '_orchestrator', None) or Orchestrator(mode='local')
            result = orch.infer(prompt)
            raw_response = result.text.strip()
        except Exception as e:
            _print_fn(f"[err_cl]Agente: error LLM: {e}[/err_cl]")
            break

        _print_fn(f"[detail]paso {step+1}: {raw_response[:120]}[/detail]")

        m = re.search(r'ACCI[OÓ]N:\s*(\w+)\s*(.*)', raw_response, re.IGNORECASE | re.DOTALL)
        if not m:
            history.append(f"RESULTADO: (respuesta no estructurada) {raw_response[:200]}")
            continue

        action = m.group(1).lower().strip()
        args   = m.group(2).strip()

        if action == "responder":
            result_text = args
            break

        elif action == "leer_archivo":
            path = Path(args.strip())
            try:
                content = path.read_text(encoding="utf-8", errors="replace")[:3000]
                history.append(f"RESULTADO leer_archivo {path}: {content}")
            except Exception as e:
                history.append(f"RESULTADO leer_archivo ERROR: {e}")

        elif action == "escribir_archivo":
            parts = args.split(" | ", 1)
            if len(parts) == 2:
                wpath, content = Path(parts[0].strip()), _strip_code_fences(parts[1])
                try:
                    wpath.parent.mkdir(parents=True, exist_ok=True)
                    _wa_old = wpath.read_text(encoding="utf-8") if wpath.exists() else ""
                    wpath.write_text(content, encoding="utf-8")
                    history.append(f"RESULTADO escribir_archivo {wpath}: OK ({len(content)} chars)")
                    _show_file_diff(_wa_old, content, str(wpath), _print_fn)
                    _print_fn(f"[ok]Archivo escrito: {wpath}[/ok]")
                    if str(wpath) not in _agent_state["files_touched"]:
                        _agent_state["files_touched"].append(str(wpath))
                        _agent_state["files_touched"] = _agent_state["files_touched"][-10:]
                except Exception as e:
                    history.append(f"RESULTADO escribir_archivo ERROR: {e}")
            else:
                history.append("RESULTADO escribir_archivo ERROR: formato incorrecto (usa ruta | contenido)")

        elif action == "buscar":
            parts = args.split(" | ", 1)
            patron = parts[0].strip()
            directorio = parts[1].strip() if len(parts) > 1 else "."
            results = []
            try:
                # Try ripgrep first (fast, shows file:line)
                r = subprocess.run(
                    ["rg", "--no-heading", "-n", "--max-count", "3", "-l", patron, directorio],
                    capture_output=True, text=True, timeout=10
                )
                if r.returncode == 0 and r.stdout.strip():
                    results = r.stdout.strip().splitlines()[:10]
            except Exception:
                pass
            if not results:
                # Fallback: regex content search with file:line:content
                try:
                    try:
                        compiled = re.compile(patron, re.IGNORECASE)
                    except re.error:
                        compiled = None
                    _SKIP = {'.git', 'venv', '__pycache__', '.pytest_cache', 'node_modules'}
                    for _p in Path(directorio).rglob("*"):
                        if _p.is_file() and not any(x in _p.parts for x in _SKIP):
                            try:
                                for _i, _ln in enumerate(_p.read_text(errors='replace').splitlines(), 1):
                                    if (compiled and compiled.search(_ln)) or (not compiled and patron.lower() in _ln.lower()):
                                        results.append(f"{_p}:{_i}: {_ln.strip()[:100]}")
                                        if len(results) >= 15:
                                            break
                            except Exception:
                                pass
                        if len(results) >= 15:
                            break
                except Exception:
                    pass
            if not results:
                # Last fallback: glob filename match
                try:
                    import glob as _glob
                    results = _glob.glob(f"{directorio}/**/*{patron}*", recursive=True)[:10]
                except Exception:
                    pass
            if results:
                history.append(f"RESULTADO buscar '{patron}': " + " | ".join(results))
            else:
                history.append(f"RESULTADO buscar '{patron}': sin resultados")

        elif action == "listar":
            try:
                entries = sorted(Path(args.strip() or ".").iterdir(), key=lambda p: (p.is_file(), p.name))[:30]
                listing = [f"{'D' if e.is_dir() else 'F'} {e.name}" for e in entries]
                history.append(f"RESULTADO listar: {listing}")
            except Exception as e:
                history.append(f"RESULTADO listar ERROR: {e}")

        elif action == "ejecutar":
            _BLOCK = [
                "rm -rf", "format", "del /s", "del /q", "del /f",
                ":(){", "python -c", "python3 -c", "powershell",
                "mkfs", "dd if=", "> /dev/", "shutdown", "reboot",
            ]
            import re as _re_sec_ag
            _args_normalized = _re_sec_ag.sub(r"\s+", " ", args.lower())
            if any(b in _args_normalized for b in _BLOCK):
                _print_fn("[err_cl]ejecutar: BLOQUEADO por seguridad[/err_cl]")
                history.append("RESULTADO ejecutar: BLOQUEADO por seguridad")
            else:
                _esc_cmd = _escape(args) if _HAS_RICH else args
                _print_fn(f"[detail]$ {_esc_cmd}[/detail]")
                try:
                    r = subprocess.run(args, shell=True, capture_output=True, text=True, timeout=30)
                    out = (r.stdout + r.stderr).strip()
                    _esc_fn = _escape if _HAS_RICH else (lambda s: s)
                    for _ol in out.splitlines()[:40]:
                        _print_fn(f"  {_esc_fn(_ol)}")
                    if r.returncode != 0:
                        _print_fn(f"[warn_cl]codigo de salida: {r.returncode}[/warn_cl]")
                    history.append(f"RESULTADO ejecutar: {out[:1500] or '(sin output)'}")
                except Exception as e:
                    history.append(f"RESULTADO ejecutar ERROR: {e}")

        elif action == "memorizar":
            try:
                ai.observe(args, provided_label="agente_tarea")
                history.append("RESULTADO memorizar: guardado en memoria episodica")
            except Exception as e:
                history.append(f"RESULTADO memorizar: (sin memoria episodica disponible) {e}")

        else:
            _valid = "leer_archivo, escribir_archivo, buscar, listar, ejecutar, memorizar, responder"
            _mkdir_hint = ""
            if action in ("mkdir", "crear_directorio", "crear_carpeta", "create_dir", "makedir"):
                _mkdir_hint = " Para crear un directorio con un archivo usa escribir_archivo <dir/file> | <contenido> — crea los directorios automaticamente."
            history.append(
                f"ERROR: herramienta '{action}' no existe. Herramientas validas: {_valid}.{_mkdir_hint}"
            )

    # Save summary to episodic memory
    summary = f"Tarea: {task[:100]} | Pasos: {step+1} | Resultado: {result_text[:200]}"
    try:
        ai.observe(summary, provided_label="agente_tarea_completada")
    except Exception:
        pass

    # Register agent task as a conversation turn so follow-up questions work
    try:
        from conversation_memory import get_conversation_context
        from vectors import text_to_vector
        _task_vec = text_to_vector(task[:200])
        if _task_vec:
            get_conversation_context(ai).add_turn(
                user_text   = f"/hacer {task[:300]}",
                cognia_text = (result_text or summary)[:400],
                vector      = _task_vec,
            )
    except Exception:
        pass

    # Save agent state
    try:
        import json as _json_save
        _agent_state["tasks"].append({
            "task": task[:100],
            "result": (result_text or "(sin respuesta)")[:150],
            "steps": step + 1,
            "ts": datetime.datetime.now().isoformat()[:19],
        })
        _agent_state["tasks"] = _agent_state["tasks"][-5:]
        _AGENT_STATE_PATH.write_text(
            _json_save.dumps(_agent_state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass

    # Offer git commit hint if new files were written during this task
    _newly_written = [
        f for f in _agent_state.get("files_touched", [])
        if f not in _prior_files_touched
    ]
    if _newly_written:
        _print_fn(
            f"[detail]Archivos escritos: {', '.join(Path(f).name for f in _newly_written[:3])}[/detail]"
        )
        _print_fn(
            "[detail]Tip: usa /ejecutar git add . && git commit -m '<msg>' para guardar los cambios[/detail]"
        )

    return result_text or "(el agente no produjo una respuesta final)"


if __name__ == "__main__":
    repl()
