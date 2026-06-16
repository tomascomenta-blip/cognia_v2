"""
cognia/cli.py
==============
Interfaz de linea de comandos (REPL) para Cognia v3.
"""

import contextlib
import datetime
import io
import json
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
    # rich is optional; without it _console stays None and themes are never
    # applied, but _THEMES is still built at import time -- keep Theme harmless.
    Theme = dict

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

# Persisted look: theme + accent come from ~/.cognia/config.env (loaded into
# os.environ by apply_config() before the CLI imports). Accent colors Cognia's
# actual responses; the theme styles everything else. Both survive restarts.
_DEFAULT_ACCENT = "cyan"
_ACCENT      = os.environ.get("COGNIA_ACCENT", "").strip() or _DEFAULT_ACCENT
_saved_theme = os.environ.get("COGNIA_THEME", "").strip()
_theme_idx   = _THEME_ORDER.index(_saved_theme) if _saved_theme in _THEMES else 0
_console     = Console(theme=_THEMES[_THEME_ORDER[_theme_idx]], highlight=False) if _HAS_RICH else None

# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
_session_log      = []
_session_start    = 0.0
_init_lines       = []
_debug_mode       = False
_fast_mode        = False
_session_feedback = []
_history: list    = []

# Conversation continuity: how many prior messages to restore from chat_history
# into _history at REPL startup. Bounded so old sessions don't bloat the prompt
# (the streaming path only feeds _history[-16:] to the model anyway), while still
# giving the synthesis slash commands (/temas, /resumen) recent material.
_HISTORY_SEED_N = 20

# Current session identity (set in repl() at startup). Used to tag persisted
# turns and to power /resume.
_SESSION_ID: str = ""
_SESSION_CWD: str = ""


def _persist_turn(ai, user_text: str, assistant_text: str) -> None:
    """
    Append a completed turn to the in-memory _history buffer AND persist it to
    chat_history so the conversation survives a restart.

    Only the streaming and agent paths call this; the articulated path persists
    itself inside responder_articulado() (respuestas_articuladas.py logs both the
    user and assistant rows), so routing it through here too would double-log.

    Best-effort persistence: a DB hiccup must never break the chat loop.
    """
    _history.append({"role": "user", "content": user_text})
    _history.append({"role": "assistant", "content": assistant_text})
    try:
        ch = getattr(ai, "chat_history", None)
        if ch is not None:
            ch.log(role="user", content=user_text)
            ch.log(role="assistant", content=assistant_text)
    except Exception:
        pass


def _build_memory_block_for(ai, query: str) -> str:
    """
    Bounded HYDRA memory block ([LOCAL]/[MEDIA]/[GLOBAL]) for the streaming
    fast-path; "" when no real memory is relevant to the query.

    The band router (cognia/context/band_router.py, the HYDRA analogue) is
    built once per Cognia instance and cached on it, wired to the SAME memory
    objects the REPL already mutates (perception / working_mem / episodic /
    semantic), so retrieval sees what observe()/persist wrote this session
    instead of a parallel set of instances over the same DB.
    """
    router = getattr(ai, "_hydra_router", None)
    if router is None:
        from cognia.context.band_router import HydraContextRouter
        router = HydraContextRouter(
            db_path=getattr(ai, "db", None),
            perception=getattr(ai, "perception", None),
            working=getattr(ai, "working_mem", None),
            episodic=getattr(ai, "episodic", None),
            semantic=getattr(ai, "semantic", None),
        )
        try:
            ai._hydra_router = router
        except Exception:
            pass
    return router.build_memory_block(query)


def _build_stream_messages(ai, raw: str, system: str, hist_ctx: list) -> list:
    """
    Messages para el fast-path de streaming, con memoria real inyectada.

    POSICION (critica para el KV-cache): el bloque de memoria cambia por turno;
    si fuera ANTES de la historia invalidaria el prefijo KV cacheado del server
    (cache_prompt + --cache-reuse) y forzaria re-prefill de TODA la historia en
    cada turno (una historia de 4k tokens a ~29 tok/s de prefill = >2 min extra
    por turno). Por eso va DENTRO del ULTIMO mensaje user: la historia previa
    queda byte-identica y el server reusa su prefijo. Sin memoria relevante el
    mensaje queda exactamente como antes (cero overhead).
    """
    user_content = raw
    try:
        mem_block = _build_memory_block_for(ai, raw)
        if mem_block:
            user_content = (
                "Contexto de memoria (puede ser relevante o no):\n"
                + mem_block + "\n\nPregunta: " + raw
            )
    except Exception:
        user_content = raw
    messages = [{"role": "system", "content": system}]
    messages.extend(hist_ctx)
    messages.append({"role": "user", "content": user_content})
    return messages

# ---------------------------------------------------------------------------
# Optional FeedbackLearner
# ---------------------------------------------------------------------------
try:
    from cognia.feedback.feedback_learner import FeedbackLearner as _FeedbackLearner
    _feedback_learner = _FeedbackLearner()
except Exception:
    _feedback_learner = None

# ---------------------------------------------------------------------------
# Command registry — drives autocomplete and /ayuda
# ---------------------------------------------------------------------------
_CMD_DESCRIPTIONS = {
    # Memoria y aprendizaje
    "/yo":              "Mostrar perfil de usuario",
    "/yo-actualizar":   "Reconstruir perfil desde historial",
    "/conceptos":       "Listar conceptos aprendidos",
    "/dormir":          "Ciclo de consolidación tipo sueño",
    "/repasar":         "Ver episodios para repasar",
    "/contradicciones": "Ver contradicciones detectadas",
    "/olvido":          "Ciclo de olvido",
    "/observar":        "Observar sin etiqueta   <texto>",
    "/aprender":        "Agregar tarjeta de aprendizaje. Uso: /aprender frente | respuesta [| tema]",
    "/aprendiendo":     "Ver estadisticas del sistema de aprendizaje espaciado",
    "/aprendiendo-buscar": "Buscar tarjetas de aprendizaje  <query>",
    "/investigar":      "Investigar en GitHub    <query>",
    "/aprende-repo":    "Aprender de un repo GitHub <url_o_query>",
    "/crear":           "Crear programa ahora    <idea>",
    "/encolar":         "Encolar idea para sleep <idea>",
    "/corregir":        "Corregir error          <obs> | <mal> | <bien>",
    "/hipotesis":       "Generar hipótesis       <A> | <B>",
    "/experimento":     "Probar afirmacion empiricamente (sandbox)  <afirmacion>",
    "/evaluar-idea":    "Evaluar idea (novedad x factibilidad x impacto)  <idea>",
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
    # Reportes
    "/reporte":         "Reporte de progreso de los ultimos 7 dias",
    "/reporte-json":    "Estadisticas rapidas en formato legible",
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
    "/largo":           "Generacion larga (hasta 5000 tokens) con progreso <pedido>",
    "/modelo":          "Ver/cambiar modelo GGUF del backend (3b|7b)  [clave]",
    "/pensar":          "Razonamiento paso a paso sobre un tema <pregunta>",
    "/revisar":         "Sesion de repaso con tarjetas de memoria espaciada (SM-2)",
    "/memoria-stats":   "Estadisticas de memoria y conocimiento acumulado",
    "/historial":       "Muestra tareas recientes del agente y archivos modificados",
    # Skills
    "/skills":          "Listar skills disponibles",
    "/skill-nuevo":     "Crear nueva skill              <nombre>",
    "/skill-cargar":    "Cargar y ejecutar skill        <nombre> [args]",
    "/skill":           "Aplicar skill (Claude/Cognia) a una tarea: /skill <nombre> [tarea]",
    # Plan
    "/plan":            "Crear plan de tareas con LLM  <objetivo>",
    "/plan-ver":        "Ver todos los planes activos",
    "/plan-ok":         "Marcar paso como completado   <id> <n>",
    "/plan-borrar":     "Eliminar un plan              <id>",
    # Templates
    "/templates":       "Listar templates de conversacion disponibles",
    "/template":        "Iniciar sesion con un template             <id>",
    "/template-guia":   "Ver preguntas guia de un template          <id>",
    # Metas
    "/meta":                    "Crear meta activa             <titulo>",
    "/metas":                   "Listar metas activas",
    "/meta-ok":                 "Marcar meta completada        <id>",
    "/meta-prog":               "Actualizar progreso           <id> <porcentaje>",
    "/meta-borrar":             "Eliminar meta                 <id>",
    "/meta-prioridad":          "Establecer prioridad de meta  <id> <alta|media|baja>",
    "/metas-alta":              "Listar solo metas de alta prioridad",
    "/meta-prioridad-ver":      "Ver prioridades de todas las metas",
    "/metas-ordenar":           "Listar metas ordenadas por prioridad",
    # Historial de chat
    "/sesiones":          "Listar sesiones de chat recientes",
    "/resume":            "Reanudar una sesion previa       [id|directorio|list]",
    "/buscar-historial":  "Buscar en el historial por keyword      <keyword>",
    "/sesion-ver":        "Ver mensajes de una sesion              <id>",
    "/historial-limpiar": "Eliminar historial [session_id|confirmar]",
    # Herramientas nuevas
    "/monitor":         "Ejecutar cmd en background y ver output  <cmd>",
    "/powershell":      "Ejecutar comando PowerShell              <cmd>",
    "/tarea-crear":     "Crear tarea de sesion                    <desc>",
    "/tarea-lista":     "Listar tareas de sesion",
    "/tarea-ok":        "Marcar tarea completada                  <id>",
    "/tarea-borrar":    "Borrar tarea                             <id>",
    "/web-fetch":       "Descargar URL y convertir a texto        <url>",
    "/web-buscar":      "Buscar en la web (DuckDuckGo)            <query>",
    "/buscar-web":      "Buscar en web (DuckDuckGo)               <query>",
    "/buscar-kg":       "Buscar en grafo de conocimiento local    <concepto>",
    "/kg-agregar":      "Agregar triple al Knowledge Graph       <sujeto> <predicado> <objeto>",
    "/kg-stats":        "Ver estadisticas del KG",
    "/kg-predicados":   "Listar predicados en el KG",
    "/kg-exportar":     "Exportar KG a JSON                      [archivo]",
    "/kg-inferir":      "Inferir propiedades y herencia de un concepto  <concepto>",
    "/kg-relacionar":   "Explicar relacion entre dos conceptos   <A> <B>",
    "/kg-responder":    "Responder pregunta usando el KG          <pregunta>",
    "/kg-camino":       "Encontrar camino entre dos conceptos    <A> <B>",
    "/worktree":        "Crear git worktree en rama aislada       <rama>",
    "/notificar":       "Enviar notificacion de escritorio        <mensaje>",
    "/notif":           "Ver notificaciones sin leer",
    "/notif-todas":     "Ver todas las notificaciones",
    "/notif-leer":      "Marcar notificacion como leida          <id>",
    "/notif-limpiar":   "Marcar todas las notificaciones como leidas",
    # UI
    "/resumen-sesion":  "Resumen completo de la sesion actual",
    "/limpiar-sesion":  "Limpiar historial de sesion en memoria (no borra datos persistentes)",
    "/ver-contexto":    "Ver que contexto inyectaria Cognia para una pregunta",
    "/limpiar":         "Limpiar pantalla",
    "/compactar":       "Resumir historial de sesión",
    "/resumir":         "Resume la conversacion actual y guarda en memoria",
    "/memoria":         "Estado de memoria y KG",
    "/modulos":         "Módulos activos en tiempo real",
    "/exportar":        "Exportar historial (json|md|csv)   <formato> [archivo]",
    "/exportar-stats":  "Ver estadisticas del historial",
    "/modo rapido":     "Toggle: saltar confirmaciones",
    "/debug":           "Toggle: mostrar logs INFO",
    "/costo":           "Tokens y tiempo de sesión",
    "/tema":            "Tema visual: /tema cicla, /tema <oscuro|claro|alto_contraste> fija (persiste)",
    "/color":           "Color de acento de las respuestas: /color <nombre|#hex> (persiste)",
    "/memoria-limite":  "Ver/fijar tope de memoria: /memoria-limite <N recuerdos> [MB] (persiste)",
    # Recordatorios
    "/recordar":           "Crear recordatorio temporal        <titulo> en <N> minutos|horas",
    "/recordatorios":      "Ver recordatorios pendientes",
    "/recordar-cancelar":  "Cancelar un recordatorio           <id>",
    # Configuracion
    "/config":             "Configuracion persistente del usuario (~/.cognia_config.json)",
    # Notas inteligentes
    "/notas":              "Ver notas guardadas (hechos, decisiones, acciones, insights, preguntas)",
    "/nota-agregar":       "Agregar nota manual al registro de notas",
    "/notas-buscar":       "Buscar en notas por texto",
    "/notas-stats":        "Estadisticas del sistema de notas",
    "/nota-fijar":         "Fijar una nota por ID",
    # Feedback
    "/feedback":           "Registrar retroalimentacion explicita sobre la ultima respuesta",
    "/feedback-sesion":    "Ver resumen de feedback de la sesion actual",
    # Estadisticas y sugerencias
    "/stats":              "Estadisticas de la sesion actual (turnos, duracion)",
    "/sesion-stats":       "Alias de /stats",
    "/sugerir":            "Ver sugerencias proactivas del motor de contexto",
    # Logros y patrones
    "/logros":             "Ver logros desbloqueados y puntos de gamificacion",
    "/patrones":           "Analizar patrones de conversacion en la sesion actual",
    # Backup y analiticas
    "/backup":             "Hacer backup de cognia.db a directorio seguro",
    "/mi-uso":             "Ver estadisticas de uso de Cognia (racha, eventos, funciones)",
    "/mi-uso-detalle":     "Ver ranking de funciones mas usadas (30 dias)",
    # Memoria semantica y debate
    "/buscar-memoria":     "Busqueda semantica TF-IDF sobre todo el historial de conversaciones",
    "/debate":             "Generar argumentos a favor y en contra de un tema",
    "/contexto-semantico": "Ver contexto de conversacion relacionado semanticamente",
    # Sintesis y analisis
    "/sintetizar":         "Sintetizar conocimiento sobre un tema (notas + KG + conversaciones)",
    "/y-si":               "Analisis hipotetico/contrafactual de una situacion",
    "/temas":              "Ver temas frecuentes en la sesion actual",
    # Perfil y estado
    "/mi-cognia":          "Reporte personal de tu perfil cognitivo en Cognia",
    "/perfil-completo":    "Ver perfil cognitivo completo en JSON",
    "/estado":             "Estado rapido de todos los sistemas de Cognia",
    # Ayuda detallada
    "/ayuda":              "Ayuda detallada sobre un comando especifico. Uso: /ayuda <comando>",
    # Autocritica y reflexion
    "/ver-criticas":        "Ver criticas automaticas de respuestas recientes",
    "/reflexion-profunda":  "Analisis multi-perspectiva de una pregunta (5 lentes cognitivos)",
    "/calidad-respuestas":  "Ver tendencia de calidad de respuestas (7 dias)",
    # Reportes y cadenas
    "/reporte-completo":    "Generar reporte Markdown completo de todos los sistemas (7 dias)",
    "/reporte-semanal":     "Generar y guardar reporte semanal en ~/.cognia_reports/",
    "/cadena-causal":       "Analisis de cadena causal de un concepto",
    "/metas-pendientes":    "Ver objetivos pendientes con progreso",
    # Recomendaciones y mapas
    "/recomendar":          "Ver recomendaciones personalizadas de proximas acciones",
    "/proximos-pasos":      "Ver la accion mas urgente recomendada",
    "/mapa":                "Generar mapa mental ASCII de un concepto desde el KG",
    # Features y vocabulario
    "/features":            "Ver y gestionar feature flags del sistema",
    "/vocabulario":         "Ver vocabulario tecnico de esta sesion",
    "/vocabulario-guardar": "Guardar vocabulario de sesion en el grafo de conocimiento",
    # Cristalizacion de conocimiento
    "/hechos-solidos":      "Ver hechos cristalizados (alta confianza) del grafo de conocimiento",
    "/cristalizar":         "Promover hechos frecuentes a alta confianza en el KG",
    "/conocimiento-ver":    "Ver conocimiento completo sobre un topico (KG + sintesis)",
    # Quiz y exportacion
    "/quiz":                "Quiz interactivo desde el KG y tarjetas de estudio",
    "/quiz-stats":          "Estadisticas de rendimiento en quizzes",
    "/exportar-todo":       "Exportar todos los datos (historial, notas, objetivos, reporte)",
    # Caminos de aprendizaje y etiquetado
    "/camino-nuevo":        "Crear camino de aprendizaje estructurado para un objetivo",
    "/caminos":             "Ver caminos de aprendizaje activos",
    "/camino-avanzar":      "Avanzar al siguiente paso de un camino de aprendizaje",
    "/etiquetar":           "Detectar etiquetas/temas de un texto automaticamente",
    # Memoria personal del usuario
    "/cognia-sabe":         "Ver hechos que Cognia sabe sobre ti",
    "/cognia-aprende":      "Enseniar un hecho sobre ti a Cognia",
    "/cognia-olvida":       "Hacer que Cognia olvide un hecho sobre ti",
    # Argumentacion
    "/argumento":           "Analisis tesis-antitesis-sintesis de una posicion",
    "/conflictos-kg":       "Ver conflictos de consistencia en el grafo de conocimiento",
    "/verificar-kg":        "Ejecutar verificacion de consistencia del KG",
    "/resolver-conflicto":  "Marcar un conflicto del KG como resuelto",
    "/comandos":            "Ver resumen de todos los comandos disponibles por categoria",
    "/digest":              "Ver digest diario de todas las metricas de Cognia",
    "/cognia-info":         "Informacion sobre capacidades y version de Cognia",
    "/inicio-dia":          "Rutina de inicio: digest + recomendacion + tarjetas pendientes",
}

# Public alias used by external tooling / tests
COMMANDS = _CMD_DESCRIPTIONS

# ---------------------------------------------------------------------------
# Detailed per-command help
# ---------------------------------------------------------------------------
_CMD_DETAILS = {
    "/hacer": (
        "Ejecuta una tarea de forma autonoma usando un loop ReAct de hasta 8 pasos. "
        "Usa herramientas como /buscar-web, /kg-agregar, /ejecutar para completar la tarea. "
        "Ejemplo: /hacer Investiga las ventajas de FastAPI vs Flask"
    ),
    "/largo": (
        "Genera una respuesta larga (hasta 5000 tokens) con el fast-path llama.cpp "
        "y continuacion automatica por rondas, mostrando progreso. "
        "Lento (~10 min a 8 tok/s). Requiere llama-server/GGUF disponible. "
        "Ejemplo: /largo Escribe una guia completa de asyncio en Python"
    ),
    "/experimento": (
        "Pone a prueba una afirmacion de forma EMPIRICA. El LLM disena un "
        "experimento Python autocontenido (solo stdlib), se corre en el sandbox "
        "seguro (scan de imports + timeout) y se lee el VEREDICTO del stdout. "
        "Si el sandbox rechaza el codigo, se reporta el fallo (no se finge exito). "
        "Ejemplo: /experimento ordenar con sort() es mas rapido que bubble sort"
    ),
    "/evaluar-idea": (
        "Autoevalua una idea en tres ejes 0.0-1.0 con el LLM vivo: novedad "
        "(que tan original), factibilidad (que tan realista de implementar) e "
        "impacto (efecto potencial). El VALOR es el producto de los tres. Si la "
        "respuesta no se puede parsear tras un reintento, se reporta el fallo "
        "(no se inventan numeros). "
        "Ejemplo: /evaluar-idea un IDE que escribe sus propios tests"
    ),
    "/modelo": (
        "Ver o cambiar en caliente el modelo GGUF del backend llama.cpp. "
        "Sin args lista el activo y los disponibles; con clave (3b|7b) para el "
        "server actual, recarga con el GGUF elegido y verifica via /props. "
        "Medido: 3b 40% pass@1 ~8tok/s, 7b 50% ~2.2tok/s, cascada 60%. "
        "Ejemplo: /modelo 7b"
    ),
    "/meta": (
        "Crea un nuevo objetivo de usuario persistente en la base de datos. "
        "El sistema rastrea el progreso automaticamente. "
        "Ejemplo: /meta Aprender Python en 30 dias"
    ),
    "/config": (
        "Gestiona la configuracion persistente en ~/.cognia_config.json. "
        "Subcomandos: ver, set, reset, exportar."
    ),
    "/recordar": (
        "Crea un recordatorio con tiempo relativo. "
        "Ejemplo: /recordar Revisar tests en 30 minutos"
    ),
    "/kg-agregar": (
        "Agrega un triple al grafo de conocimiento. "
        "Formato: sujeto | predicado | objeto. "
        "Ejemplo: /kg-agregar Python | es_un | lenguaje_de_programacion"
    ),
    "/exportar": (
        "Exporta el historial de conversacion. "
        "Formatos: json, md, csv. "
        "Ejemplo: /exportar md mi_historial.md"
    ),
    "/aprende-repo": (
        "Indexa un repositorio Git local para que Cognia pueda responder preguntas sobre el codigo. "
        "Ejemplo: /aprende-repo /ruta/al/repo"
    ),
    "/skills": (
        "Lista todos los skills disponibles en cognia_skills/. "
        "Los skills son plantillas de prompts reutilizables."
    ),
    "/plan": (
        "Crea un plan de implementacion paso a paso. "
        "El plan persiste en ~/.cognia_plans.json."
    ),
    "/yo": (
        "Muestra el perfil inferido del usuario basado en el historial de conversaciones."
    ),
    "/feedback": (
        "Registra retroalimentacion explicita sobre la ultima respuesta del sistema. "
        "Senales validas: positivo, negativo, neutral. "
        "Ejemplo: /feedback positivo"
    ),
    "/feedback-sesion": (
        "Muestra un resumen de la retroalimentacion registrada en la sesion actual, "
        "con conteo de senales positivas, negativas y neutrales."
    ),
    "/ayuda": (
        "Muestra ayuda detallada sobre un comando especifico. "
        "Si el comando no tiene descripcion detallada muestra la descripcion corta. "
        "Ejemplo: /ayuda /hacer"
    ),
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
    /aprende-repo <url_o_query>     Aprende de un repo GitHub por URL o busqueda
    /corregir <obs> | <mal> | <bien>Corregir error
    /hipotesis <A> | <B>            Generar hipotesis
    /experimento <afirmacion>       Probar afirmacion empiricamente (sandbox)
    /evaluar-idea <idea>            Evaluar idea (novedad x factibilidad x impacto)
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

  TEMPLATES:
    /templates                      Listar templates de conversacion disponibles
    /template <id>                  Iniciar sesion con un template (initial_prompt + preguntas)
    /template-guia <id>             Ver solo las preguntas guia de un template

  METAS:
    /meta <titulo>                  Crear meta activa
    /metas                          Listar metas activas
    /meta-ok <id>                   Marcar meta completada
    /meta-prog <id> <porcentaje>    Actualizar progreso de meta
    /meta-borrar <id>               Eliminar meta
    /meta-prioridad <id> <nivel>    Establecer prioridad (alta/media/baja)
    /metas-alta                     Listar solo metas de alta prioridad
    /meta-prioridad-ver             Ver prioridades de todas las metas
    /metas-ordenar                  Listar metas ordenadas por prioridad

  REPORTES:
    /reporte                        Reporte de progreso de los ultimos 7 dias (Markdown)
    /reporte-json                   Estadisticas rapidas (metas, mensajes, sesiones, insights)
    /yo                             Mostrar perfil de usuario (temas, patrones, idioma)
    /yo-actualizar                  Reconstruir perfil desde historial de chat

  SISTEMA:
    /doctor                         Verificar instalacion
    /update                         Actualizar Cognia
    /distill  /  /distill run       Destilacion SRDN
    /ayuda    /  /salir

  HISTORIAL DE CHAT:
    /sesiones                       Listar sesiones de chat recientes
    /buscar-historial <keyword>     Buscar en el historial por keyword
    /sesion-ver <id>                Ver mensajes de una sesion (ID o primeros 8 chars)
    /historial-limpiar [id|confirmar] Eliminar historial de sesion o todo

  BUSQUEDA:
    /buscar-web <query>             Buscar en web via DuckDuckGo (respuesta directa + temas)
    /buscar-kg <concepto>           Buscar hechos en el grafo de conocimiento local

  KNOWLEDGE GRAPH:
    /kg-agregar <s> <p> <o>         Agregar triple (sujeto predicado objeto) al KG
    /kg-stats                       Ver estadisticas del KG (triples, conceptos, predicados)
    /kg-predicados                  Listar predicados unicos en el KG
    /kg-exportar [archivo]          Exportar KG a JSON (default: kg_export.json)
    /kg-inferir <concepto>          Inferir propiedades y herencia de un concepto
    /kg-relacionar <A> <B>          Explicar relacion entre dos conceptos
    /kg-responder <pregunta>        Responder pregunta usando el KG (multi-hop)
    /kg-camino <A> <B>              Encontrar camino entre dos conceptos

  NOTIFICACIONES:
    /notif                          Ver notificaciones sin leer (ultimas 10)
    /notif-todas                    Ver todas las notificaciones (ultimas 20)
    /notif-leer <id>                Marcar una notificacion como leida
    /notif-limpiar                  Marcar todas las notificaciones como leidas

  RECORDATORIOS:
    /recordar <titulo> en <N> minutos|horas  Crear recordatorio temporal
    /recordatorios                  Ver recordatorios pendientes
    /recordar-cancelar <id>         Cancelar un recordatorio

  UI / SLASH:
    /limpiar                        Limpiar pantalla
    /compactar                      Resumir historial de sesion
    /memoria                        Estado de memoria y KG
    /modulos                        Modulos activos en tiempo real
    /exportar <formato> [archivo]   Exportar historial (json|md|csv); archivo opcional
    /exportar-stats                 Ver estadisticas del historial
    /modo rapido                    Toggle: saltar confirmaciones
    /debug                          Toggle: mostrar logs INFO
    /costo                          Tokens y tiempo de sesion
    /tema                           Ciclar tema visual

  CONFIGURACION:
    /config              Mostrar configuracion actual
    /config set k v      Cambiar valor de configuracion
    /config reset        Restablecer valores por defecto
    /config exportar     Exportar configuracion como JSON

  RETROALIMENTACION:
    /feedback [positivo|negativo|neutral]  Registrar feedback explicito
    /feedback-sesion                       Ver feedback de esta sesion

  ESTADISTICAS Y SUGERENCIAS:
    /stats             Estadisticas de la sesion actual
    /sugerir           Ver sugerencias proactivas del sistema

  NOTAS INTELIGENTES:
    /notas [tipo]         Ver notas (hechos/decisiones/acciones/insights/preguntas)
    /nota-agregar <text>  Agregar nota manual
    /notas-buscar <q>     Buscar en notas
    /notas-stats          Estadisticas de notas
    /nota-fijar <id>      Fijar nota por ID

  APRENDIZAJE ESPACIADO:
    /aprender <f> | <r> [| tema]   Crear tarjeta de estudio
    /revisar                        Sesion de repaso interactiva
    /aprendiendo                    Estadisticas de aprendizaje
    /aprendiendo-buscar <q>         Buscar tarjetas por texto

  LOGROS Y PATRONES:
    /logros [todos]    Ver logros (sin arg = solo desbloqueados)
    /patrones          Analizar patrones de tu sesion actual

  AYUDA DETALLADA:
    /ayuda <comando>   Descripcion completa de un comando

  BACKUP Y ANALITICAS:
    /backup [dir]        Backup de cognia.db (default: ~/.cognia_backups/)
    /mi-uso              Estadisticas de uso personal
    /mi-uso-detalle      Ranking de funciones mas usadas

  MEMORIA SEMANTICA Y DEBATE:
    /buscar-memoria <q>       Busqueda semantica en historial
    /contexto-semantico <q>   Ver contexto relacionado
    /debate <tema>            Argumentos pro/contra de un tema

  SINTESIS Y ANALISIS:
    /sintetizar <tema>    Sintesis de conocimiento multi-fuente
    /y-si <situacion>     Analisis hipotetico y contrafactual
    /temas                Temas frecuentes en esta sesion

  PERFIL Y ESTADO:
    /mi-cognia         Reporte personal (logros, aprendizaje, objetivos)
    /estado            Estado rapido de todos los sistemas
    /perfil-completo   Perfil cognitivo completo en JSON

  AUTOCRITICA Y REFLEXION:
    /ver-criticas              Ver criticas automaticas de respuestas
    /calidad-respuestas        Tendencia de calidad (7 dias)
    /reflexion-profunda <q>    Analisis con 5 lentes cognitivos

  REPORTES Y CADENAS:
    /reporte-completo [arch]  Reporte Markdown completo (7 dias)
    /reporte-semanal          Guardar reporte semanal automaticamente
    /cadena-causal <c>        Analisis de cadena causal
    /metas-pendientes         Objetivos pendientes con progreso

  RECOMENDACIONES Y MAPAS:
    /recomendar           Recomendaciones personalizadas (hasta 5)
    /proximos-pasos       Accion mas urgente recomendada
    /mapa <concepto>      Mapa mental ASCII desde el grafo de conocimiento

  FEATURES Y VOCABULARIO:
    /features                  Ver feature flags del sistema
    /vocabulario               Vocabulario tecnico de esta sesion
    /vocabulario-guardar       Guardar vocabulario en el KG

  CRISTALIZACION DE CONOCIMIENTO:
    /hechos-solidos           Ver hechos de alta confianza
    /cristalizar              Promover hechos frecuentes a alta confianza
    /conocimiento-ver <t>     Ver todo el conocimiento sobre un topico

  QUIZ Y EXPORTACION:
    /quiz [tema]         Quiz interactivo (KG + tarjetas SM-2)
    /quiz-stats          Estadisticas de rendimiento
    /exportar-todo [d]   Exportar todo a directorio (default: ~/.cognia_exports/)

  CAMINOS DE APRENDIZAJE:
    /camino-nuevo <obj>   Crear camino estructurado (5 pasos)
    /caminos              Ver caminos activos con progreso
    /camino-avanzar <id>  Marcar paso completado
    /etiquetar <texto>    Detectar temas/etiquetas en texto

  MEMORIA PERSONAL:
    /cognia-sabe               Ver lo que Cognia sabe de ti
    /cognia-aprende <hecho>    Enseniar un hecho sobre ti
    /cognia-olvida <id>        Hacer olvidar un hecho

ARGUMENTACION:
  /argumento <tesis>         Analisis tesis-antitesis-sintesis

  INSPECCION Y SESION:
    /ver-contexto <q>    Ver contexto que se inyectaria para una pregunta
    /resumen-sesion      Resumen completo de la sesion
    /limpiar-sesion      Limpiar historial en memoria de esta sesion
    /sesiones            Listar sesiones recientes (id, fecha, directorio)
    /resume [id|dir]     Reanudar una sesion previa (por id o directorio)

  CONSISTENCIA KG:
    /verificar-kg             Detectar inconsistencias en el KG
    /conflictos-kg            Ver conflictos sin resolver
    /resolver-conflicto <id>  Marcar conflicto como resuelto
    /comandos                 Resumen de comandos por categoria

  INICIO Y DIGEST:
    /digest          Digest diario (metas, repaso, notas, logros)
    /inicio-dia      Rutina de inicio del dia
    /cognia-info     Capacidades y version de Cognia
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
    _r("  /exportar    ",              "cyan");  _r("exportar historial\n",     "dim white")
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


def _slash_exportar_sesion():
    ts       = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"cognia_sesion_{ts}.md"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(f"# Sesion Cognia — {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
        for entry in _session_log:
            f.write(f"**> {entry['input']}**\n\n```\n{entry['output']}\n```\n\n---\n\n")
    _print_line(f"[ok]Exportado:[/ok] [mod]{filename}[/mod]")


def _slash_exportar(args: str) -> None:
    """Exporta el historial de chat en formato json, md o csv."""
    parts = args.strip().split(None, 1)
    if not parts:
        print("Uso: /exportar <formato> [archivo]")
        print("Formatos: json, md, csv")
        print("Ejemplo: /exportar json historial.json")
        return

    fmt = parts[0].lower()
    if fmt not in ("json", "md", "csv"):
        print(f"Formato no valido: {fmt}")
        print("Formatos disponibles: json, md, csv")
        return

    _default_names = {"json": "cognia_historial.json", "md": "cognia_historial.md", "csv": "cognia_historial.csv"}
    filename = parts[1].strip() if len(parts) > 1 else _default_names[fmt]

    try:
        from cognia.export.history_exporter import HistoryExporter
        exporter = HistoryExporter()
        messages = exporter.get_messages()
        if fmt == "json":
            content = exporter.to_json(messages)
        elif fmt == "md":
            content = exporter.to_markdown(messages)
        else:
            content = exporter.to_csv(messages)
        Path(filename).write_text(content, encoding="utf-8")
        print(f"Historial exportado a {filename} ({len(messages)} mensajes)")
    except Exception as e:
        print(f"Error al exportar historial: {e}")


def _slash_exportar_stats() -> None:
    """Muestra estadisticas del historial de chat."""
    try:
        from cognia.export.history_exporter import HistoryExporter
        exporter = HistoryExporter()
        messages = exporter.get_messages()
        total = len(messages)
        user_count = sum(1 for m in messages if m.get("role") == "user")
        cognia_count = total - user_count
        first_ts = messages[0].get("timestamp", "N/A") if messages else "N/A"
        last_ts = messages[-1].get("timestamp", "N/A") if messages else "N/A"
        lines = [
            "Estadisticas del historial:",
            f"  Total mensajes: {total}",
            f"  Mensajes de usuario: {user_count}",
            f"  Mensajes de Cognia: {cognia_count}",
            f"  Primer mensaje: {first_ts}",
            f"  Ultimo mensaje: {last_ts}",
        ]
        _show_response("\n".join(lines), "cyan")
    except Exception as e:
        print(f"Error al obtener estadisticas: {e}")


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


def _slash_stats() -> None:
    user_turns      = sum(1 for e in _history if e.get("role") == "user")
    assistant_turns = sum(1 for e in _history if e.get("role") == "assistant")
    total_turns     = user_turns + assistant_turns
    elapsed_min     = int((time.time() - _session_start) / 60) if _session_start else 0
    content = (
        f"Estadisticas de sesion:\n"
        f"  Turnos usuario   : {user_turns}\n"
        f"  Turnos asistente : {assistant_turns}\n"
        f"  Total            : {total_turns}\n"
        f"  Duracion         : {elapsed_min} min"
    )
    if _HAS_RICH and _console:
        _console.print(Panel(content, title="[cyan]Stats de sesion[/cyan]",
                             border_style="cyan", padding=(0, 1)))
    else:
        print(content)


def _slash_sugerir() -> None:
    try:
        import requests
        resp = requests.get("http://localhost:8765/proactive/suggestions", timeout=2)
        if resp.status_code == 200:
            suggestions = resp.json().get("suggestions", [])
            if not suggestions:
                print("No hay sugerencias pendientes.")
                return
            print("Sugerencias:")
            for i, s in enumerate(suggestions, 1):
                print(f"  {i}. {s}")
        else:
            print(f"Error al obtener sugerencias: {resp.status_code}")
    except Exception:
        print("Servicio de sugerencias no disponible. Inicia cognia_desktop_api.py.")


def _slash_logros(args: str) -> None:
    try:
        import requests
        resp = requests.get("http://localhost:8765/achievements", timeout=2)
        if resp.status_code != 200:
            print(f"Error: {resp.status_code}")
            return
        data = resp.json()
        items = data if isinstance(data, list) else data.get("achievements", [])
        show_all = args.strip().lower() == "todos"
        shown = 0
        for item in items:
            if show_all or item.get("unlocked"):
                status = "[X]" if item.get("unlocked") else "[ ]"
                pts = item.get("points", 0)
                print(f"  {status} {item.get('name','')} ({pts} pts) - {item.get('description','')}")
                shown += 1
        if shown == 0:
            print("Aun no has desbloqueado logros. Empieza a chatear!")
        else:
            r2 = requests.get("http://localhost:8765/achievements/stats", timeout=2)
            if r2.status_code == 200:
                s = r2.json()
                print(f"\n  Total: {s.get('unlocked',0)}/{s.get('total',0)} | Puntos: {s.get('points',0)}")
    except Exception:
        print("Servicio de logros no disponible.")


def _slash_patrones(args: str) -> None:
    if not _history:
        print("No hay historial en esta sesion.")
        return

    user_msgs = [h["content"] for h in _history if h.get("role") == "user"]
    if not user_msgs:
        print("No hay mensajes de usuario.")
        return

    q_words = {"como": 0, "por que": 0, "que": 0, "cuando": 0, "donde": 0}
    for msg in user_msgs:
        lower = msg.lower()
        for w in q_words:
            if w in lower:
                q_words[w] += 1

    stop = {"para", "como", "esta", "este", "esto", "tiene", "desde", "hasta", "sobre"}
    word_freq = {}
    for msg in user_msgs:
        for word in msg.lower().split():
            w = word.strip(".,?!;:")
            if len(w) > 4 and w not in stop:
                word_freq[w] = word_freq.get(w, 0) + 1
    top_words = sorted(word_freq.items(), key=lambda x: -x[1])[:5]

    print(f"Patrones en esta sesion ({len(user_msgs)} mensajes):")
    print(f"  Palabras frecuentes: {', '.join(w for w,_ in top_words) or 'ninguna'}")
    top_q = max(q_words.items(), key=lambda x: x[1])
    if top_q[1] > 0:
        print(f"  Tipo de pregunta mas comun: '{top_q[0]}' ({top_q[1]} veces)")
    avg_len = sum(len(m) for m in user_msgs) // len(user_msgs)
    print(f"  Longitud promedio de mensaje: {avg_len} caracteres")


def _slash_backup(args: str) -> None:
    import shutil, datetime
    from pathlib import Path
    db_candidates = [Path("cognia.db"), Path.home() / "cognia.db", Path("storage/cognia.db")]
    src = next((p for p in db_candidates if p.exists()), None)
    if src is None:
        print("No se encontro cognia.db para hacer backup.")
        return
    dest_dir = Path(args.strip()) if args.strip() else Path.home() / ".cognia_backups"
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = dest_dir / f"cognia_backup_{stamp}.db"
    shutil.copy2(src, dest)
    size_kb = dest.stat().st_size // 1024
    print(f"Backup guardado: {dest} ({size_kb} KB)")


def _slash_mi_uso(args: str) -> None:
    try:
        import requests
        resp = requests.get("http://localhost:8765/analytics/stats", timeout=2)
        if resp.status_code == 200:
            s = resp.json()
            print(f"Uso de Cognia:")
            print(f"  Eventos totales : {s.get('total_events', 0)}")
            print(f"  Dias activos    : {s.get('active_days', 0)}")
            print(f"  Racha actual    : {s.get('streak', 0)} dia(s)")
            print(f"  Hoy             : {s.get('today_count', 0)} eventos")
            if s.get('top_feature'):
                print(f"  Funcion estrella: {s.get('top_feature')}")
        else:
            print(f"Error: {resp.status_code}")
    except Exception:
        print("Servicio de analiticas no disponible.")


def _slash_mi_uso_detalle(args: str) -> None:
    try:
        import requests
        resp = requests.get("http://localhost:8765/analytics/top-features", timeout=2)
        if resp.status_code == 200:
            features = resp.json().get("features", resp.json() if isinstance(resp.json(), list) else [])
            if not features:
                print("Sin datos de uso aun.")
                return
            print("Funciones mas usadas (ultimos 30 dias):")
            for i, f in enumerate(features[:10], 1):
                bar = "#" * min(20, f.get("total", 0))
                print(f"  {i:2}. {f.get('feature','?'):20} {bar} ({f.get('total',0)})")
        else:
            print(f"Error: {resp.status_code}")
    except Exception:
        print("Servicio de analiticas no disponible.")


def _slash_buscar_memoria(args: str) -> None:
    if not args.strip():
        print("Uso: /buscar-memoria <texto a buscar semanticamente>")
        return
    try:
        import requests, urllib.parse
        q = urllib.parse.quote(args.strip())
        resp = requests.get(f"http://localhost:8765/memory/search?q={q}&limit=5", timeout=5)
        if resp.status_code == 200:
            results = resp.json().get("results", [])
            if not results:
                print("Sin resultados semanticos para esa busqueda.")
                return
            print(f"Resultados semanticos para '{args.strip()}':")
            for i, r in enumerate(results, 1):
                score = round(r.get("score", 0), 3)
                role = r.get("role", "?")
                content = r.get("content", "")[:120]
                ts = r.get("ts", 0)
                from datetime import datetime
                date_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d") if ts else "?"
                print(f"  {i}. [{role}] ({date_str}, score={score}) {content}")
        else:
            print(f"Error: {resp.status_code}")
    except Exception:
        print("Servicio de busqueda semantica no disponible.")


def _slash_debate(args: str) -> None:
    if not args.strip():
        print("Uso: /debate <tema o proposicion>")
        return
    tema = args.strip()
    print(f"Debate: '{tema}'")
    print()
    print("A FAVOR:")
    pros = [
        f"  + {tema} puede mejorar la eficiencia en contextos especificos.",
        f"  + Existen casos documentados donde {tema.lower()} ha generado valor.",
        f"  + La adopcion de {tema.lower()} reduce costos a largo plazo.",
    ]
    for p in pros:
        print(p)
    print()
    print("EN CONTRA:")
    cons = [
        f"  - {tema} introduce complejidad adicional que puede ser evitable.",
        f"  - Los riesgos de {tema.lower()} no siempre estan bien evaluados.",
        f"  - La implementacion de {tema.lower()} requiere recursos significativos.",
    ]
    for c in cons:
        print(c)
    print()
    print("CONCLUSION: Evalua el contexto especifico antes de decidir.")


def _slash_contexto_semantico(args: str) -> None:
    if not args.strip():
        print("Uso: /contexto-semantico <consulta>")
        return
    try:
        import requests, urllib.parse
        q = urllib.parse.quote(args.strip())
        resp = requests.get(f"http://localhost:8765/memory/search/context?q={q}&window=3", timeout=5)
        if resp.status_code == 200:
            context = resp.json().get("context", [])
            if not context:
                print("Sin contexto encontrado.")
                return
            print(f"Contexto semantico para '{args.strip()}':")
            for msg in context:
                role = msg.get("role", "?")
                content = msg.get("content", "")[:150]
                print(f"  [{role}] {content}")
        else:
            print(f"Error: {resp.status_code}")
    except Exception:
        print("Servicio no disponible.")


def _slash_sintetizar(args: str) -> None:
    if not args.strip():
        print("Uso: /sintetizar <tema>")
        return
    try:
        import requests, urllib.parse
        q = urllib.parse.quote(args.strip())
        resp = requests.get(f"http://localhost:8765/synthesis?q={q}", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            print(data.get("synthesis", "Sin sintesis disponible."))
            sources = data.get("sources", [])
            if sources:
                print(f"\n[Fuentes: {', '.join(sources)}]")
        else:
            print(f"Error: {resp.status_code}")
    except Exception:
        print("Servicio de sintesis no disponible.")


def _slash_y_si(args: str) -> None:
    if not args.strip():
        print("Uso: /y-si <situacion hipotetica>")
        return
    sit = args.strip()
    print(f"Analisis hipotetico: 'y si {sit}'")
    print()
    print("Escenario probable:")
    print(f"  Si {sit}, es probable que los sistemas relacionados se vean afectados.")
    print(f"  El impacto dependeria de la escala y el contexto de implementacion.")
    print()
    print("Riesgos:")
    print(f"  - Consecuencias no anticipadas de '{sit}'.")
    print(f"  - Resistencia o friccion en la adopcion del cambio.")
    print(f"  - Dependencias externas que limiten el resultado.")
    print()
    print("Oportunidades:")
    print(f"  - Nuevos patrones de uso derivados de '{sit}'.")
    print(f"  - Aprendizaje y adaptacion del sistema ante el cambio.")
    print()
    print("Recomendacion: prueba en escala pequena antes de generalizar.")


def _slash_temas(args: str) -> None:
    if not _history:
        print("No hay historial en esta sesion.")
        return
    user_msgs = [h["content"] for h in _history if h.get("role") == "user"]
    stop = {"para","como","esta","este","esto","tiene","desde","hasta","sobre","cuando",
            "donde","quien","cuales","porque","tambien","puede","todos","solo","muy"}
    word_freq = {}
    for msg in user_msgs:
        for word in msg.lower().split():
            w = word.strip(".,?!;:()")
            if len(w) > 4 and w not in stop:
                word_freq[w] = word_freq.get(w, 0) + 1
    topics = sorted(word_freq.items(), key=lambda x: -x[1])[:8]
    if not topics:
        print("Sin temas identificados.")
        return
    print(f"Temas en esta sesion ({len(user_msgs)} mensajes):")
    for word, count in topics:
        bar = "*" * min(10, count)
        print(f"  {word:20} {bar} ({count})")


def _slash_mi_cognia(args: str) -> None:
    try:
        import requests
        resp = requests.get("http://localhost:8765/cognitive-profile/summary", timeout=5)
        if resp.status_code == 200:
            summary = resp.json().get("summary", "")
            print(summary if summary else "Perfil no disponible.")
        else:
            resp2 = requests.get("http://localhost:8765/cognitive-profile", timeout=5)
            if resp2.status_code == 200:
                p = resp2.json()
                print("Perfil cognitivo de Cognia:")
                ach = p.get("achievements", {})
                print(f"  Logros     : {ach.get('unlocked',0)}/{ach.get('total',0)} ({ach.get('points',0)} pts)")
                learn = p.get("learning", {})
                print(f"  Aprendizaje: {learn.get('mastered',0)} dominadas, {learn.get('due_today',0)} para hoy")
                goals = p.get("goals", {})
                print(f"  Objetivos  : {goals.get('completed',0)} completados, {goals.get('pending',0)} pendientes")
                analytics = p.get("analytics", {})
                print(f"  Racha      : {analytics.get('streak',0)} dia(s)")
                score = p.get("overall_score", 0)
                print(f"  Puntuacion : {score}/1000")
            else:
                print(f"Error: {resp2.status_code}")
    except Exception:
        print("Servicio de perfil cognitivo no disponible.")


def _slash_perfil_completo(args: str) -> None:
    try:
        import requests, json
        resp = requests.get("http://localhost:8765/cognitive-profile", timeout=5)
        if resp.status_code == 200:
            print(json.dumps(resp.json(), indent=2, ensure_ascii=False))
        else:
            print(f"Error: {resp.status_code}")
    except Exception:
        print("Servicio de perfil cognitivo no disponible.")


def _slash_estado(args: str) -> None:
    import threading
    results = {}
    errors = []

    def fetch(name, url):
        try:
            import requests
            r = requests.get(url, timeout=2)
            if r.status_code == 200:
                results[name] = r.json()
        except Exception:
            errors.append(name)

    endpoints = {
        "notas": "http://localhost:8765/notes/stats",
        "logros": "http://localhost:8765/achievements/stats",
        "uso": "http://localhost:8765/analytics/stats",
        "aprendizaje": "http://localhost:8765/learning/stats",
    }
    threads = [threading.Thread(target=fetch, args=(n, u)) for n, u in endpoints.items()]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=3)

    if not results and errors:
        print("Servicio no disponible. Inicia cognia_desktop_api.py.")
        return

    print("Estado de Cognia:")
    if "notas" in results:
        n = results["notas"]
        print(f"  Notas      : {n.get('total',0)} total, {n.get('pinned',0)} fijadas")
    if "logros" in results:
        a = results["logros"]
        print(f"  Logros     : {a.get('unlocked',0)}/{a.get('total',0)} ({a.get('points',0)} pts)")
    if "uso" in results:
        u = results["uso"]
        print(f"  Racha      : {u.get('streak',0)} dia(s) | Hoy: {u.get('today_count',0)} eventos")
    if "aprendizaje" in results:
        l = results["aprendizaje"]
        print(f"  Estudio    : {l.get('total',0)} tarjetas, {l.get('due_today',0)} para revisar")


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
# Meta (goal) helpers
# ---------------------------------------------------------------------------

_CLI_USER_ID = "cli_user"


def _slash_meta(titulo: str) -> None:
    try:
        from cognia.goals.goal_tracker import GoalTracker
    except Exception:
        print("Sistema de metas no disponible.")
        return
    try:
        gt = GoalTracker()
        goal = gt.create_goal(_CLI_USER_ID, titulo)
        print(f"Meta creada: {titulo} (id: {goal['id']})")
    except Exception as e:
        _print_line(f"[err_cl]Error al crear meta: {e}[/err_cl]")


def _slash_metas() -> None:
    try:
        from cognia.goals.goal_tracker import GoalTracker
    except Exception:
        print("Sistema de metas no disponible.")
        return
    try:
        gt = GoalTracker()
        goals = gt.get_goals(_CLI_USER_ID, status="active")
        if not goals:
            print("Sin metas activas.")
            return
        lines = ["Metas activas:"]
        for g in goals:
            lines.append(f"  [{g['id']}] {g['title']} -- {g['progress_pct']}% ({g['status']})")
        _show_response("\n".join(lines), "cyan")
    except Exception as e:
        _print_line(f"[err_cl]Error al listar metas: {e}[/err_cl]")


def _slash_meta_ok(id_str: str) -> None:
    try:
        from cognia.goals.goal_tracker import GoalTracker
    except Exception:
        print("Sistema de metas no disponible.")
        return
    try:
        goal_id = int(id_str)
        gt = GoalTracker()
        ok = gt.update_progress(goal_id, 100, user_id=_CLI_USER_ID)
        if ok:
            print(f"Meta {goal_id} completada.")
        else:
            print(f"Meta {goal_id} no encontrada.")
    except ValueError:
        _print_line("[warn_cl]El id debe ser un numero.[/warn_cl]")
    except Exception as e:
        _print_line(f"[err_cl]Error: {e}[/err_cl]")


def _slash_meta_prog(args: str) -> None:
    try:
        from cognia.goals.goal_tracker import GoalTracker
    except Exception:
        print("Sistema de metas no disponible.")
        return
    parts = args.strip().split()
    if len(parts) < 2:
        _print_line("[warn_cl]Uso: /meta-prog <id> <porcentaje>[/warn_cl]")
        return
    try:
        goal_id = int(parts[0])
        pct = int(parts[1])
    except ValueError:
        _print_line("[warn_cl]id y porcentaje deben ser numeros.[/warn_cl]")
        return
    try:
        gt = GoalTracker()
        ok = gt.update_progress(goal_id, pct, user_id=_CLI_USER_ID)
        if ok:
            print(f"Meta {goal_id}: progreso actualizado a {pct}%")
        else:
            print(f"Meta {goal_id} no encontrada.")
    except Exception as e:
        _print_line(f"[err_cl]Error: {e}[/err_cl]")


def _slash_meta_borrar(id_str: str) -> None:
    try:
        from cognia.goals.goal_tracker import GoalTracker
    except Exception:
        print("Sistema de metas no disponible.")
        return
    try:
        goal_id = int(id_str)
        gt = GoalTracker()
        ok = gt.delete_goal(goal_id, _CLI_USER_ID)
        if ok:
            print(f"Meta {goal_id} eliminada.")
        else:
            print(f"Meta {goal_id} no encontrada.")
    except ValueError:
        _print_line("[warn_cl]El id debe ser un numero.[/warn_cl]")
    except Exception as e:
        _print_line(f"[err_cl]Error: {e}[/err_cl]")


# ---------------------------------------------------------------------------
# Meta priority helpers
# ---------------------------------------------------------------------------

_PRIORITIES_PATH = Path.home() / ".cognia_priorities.json"
_VALID_PRIORITIES = ("alta", "media", "baja")


def _load_priorities() -> dict:
    if _PRIORITIES_PATH.exists():
        try:
            import json as _j
            return _j.loads(_PRIORITIES_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_priorities(priorities: dict) -> None:
    import json as _j
    _PRIORITIES_PATH.write_text(_j.dumps(priorities, ensure_ascii=False, indent=2), encoding="utf-8")


def _slash_meta_prioridad(args: str) -> None:
    parts = args.strip().split()
    if len(parts) < 2:
        print("Uso: /meta-prioridad <id> <alta|media|baja>")
        return
    id_str, nivel = parts[0], parts[1].lower()
    if nivel not in _VALID_PRIORITIES:
        print(f"Prioridad invalida. Opciones: alta, media, baja")
        return
    try:
        goal_id = int(id_str)
    except ValueError:
        print("El id debe ser un numero.")
        return
    priorities = _load_priorities()
    priorities[str(goal_id)] = nivel
    _save_priorities(priorities)
    print(f"Meta {goal_id}: prioridad establecida como {nivel}")


def _slash_metas_alta(args: str) -> None:
    try:
        from cognia.goals.goal_tracker import GoalTracker
    except Exception:
        print("Sistema de metas no disponible.")
        return
    try:
        gt = GoalTracker()
        goals = gt.get_goals(_CLI_USER_ID, status="active")
        priorities = _load_priorities()
        alta = [g for g in goals if priorities.get(str(g["id"])) == "alta"]
        if not alta:
            print("Sin metas de alta prioridad.")
            return
        lines = ["Metas de alta prioridad:"]
        for g in alta:
            lines.append(f"  [{g['id']}] {g['title']} -- {g['progress_pct']}% ({g['status']})")
        _show_response("\n".join(lines), "cyan")
    except Exception as e:
        _print_line(f"[err_cl]Error al listar metas alta prioridad: {e}[/err_cl]")


def _slash_meta_prioridad_ver(args: str) -> None:
    try:
        from cognia.goals.goal_tracker import GoalTracker
    except Exception:
        print("Sistema de metas no disponible.")
        return
    try:
        gt = GoalTracker()
        goals = gt.get_goals(_CLI_USER_ID, status="active")
        priorities = _load_priorities()
        lines = ["Prioridades actuales:"]
        for g in goals:
            nivel = priorities.get(str(g["id"]), "(sin prioridad)")
            lines.append(f"  [{g['id']}] {g['title']} -- {nivel}")
        if len(lines) == 1:
            lines.append("  Sin metas activas.")
        _show_response("\n".join(lines), "cyan")
    except Exception as e:
        _print_line(f"[err_cl]Error al mostrar prioridades: {e}[/err_cl]")


def _slash_metas_ordenar(args: str) -> None:
    try:
        from cognia.goals.goal_tracker import GoalTracker
    except Exception:
        print("Sistema de metas no disponible.")
        return
    try:
        gt = GoalTracker()
        goals = gt.get_goals(_CLI_USER_ID, status="active")
        priorities = _load_priorities()
        _order = {"alta": 0, "media": 1, "baja": 2}
        _label = {"alta": "[ALTA] ", "media": "[MEDIA]", "baja": "[BAJA] "}

        def _sort_key(g):
            return _order.get(priorities.get(str(g["id"]), ""), 3)

        sorted_goals = sorted(goals, key=_sort_key)
        lines = ["Metas (ordenadas por prioridad):"]
        for g in sorted_goals:
            nivel = priorities.get(str(g["id"]), "")
            tag = _label.get(nivel, "[--]   ")
            lines.append(f"  {tag} [{g['id']}] {g['title']} -- {g['progress_pct']}%")
        if len(lines) == 1:
            lines.append("  Sin metas activas.")
        _show_response("\n".join(lines), "cyan")
    except Exception as e:
        _print_line(f"[err_cl]Error al ordenar metas: {e}[/err_cl]")


# ---------------------------------------------------------------------------
# Notification commands
# ---------------------------------------------------------------------------

def _slash_notif(args: str) -> None:
    try:
        from cognia.notifications.notification_center import NotificationCenter
    except Exception:
        print("Sistema de notificaciones no disponible.")
        return
    try:
        nc = NotificationCenter()
        items = nc.get_all(_CLI_USER_ID, limit=10, include_read=False)
        if not items:
            print("(Sin notificaciones)")
            return
        lines = [f"Notificaciones ({len(items)} sin leer):"]
        for i, n in enumerate(items, 1):
            body_part = f" -- {n['body']}" if n.get("body") else ""
            lines.append(f"  [{i}] [{n['level']}] {n['title']}{body_part}")
        _show_response("\n".join(lines), "cyan")
    except Exception as e:
        _print_line(f"[err_cl]Error al listar notificaciones: {e}[/err_cl]")


def _slash_notif_todas(args: str) -> None:
    try:
        from cognia.notifications.notification_center import NotificationCenter
    except Exception:
        print("Sistema de notificaciones no disponible.")
        return
    try:
        nc = NotificationCenter()
        items = nc.get_all(_CLI_USER_ID, limit=20, include_read=True)
        if not items:
            print("(Sin notificaciones)")
            return
        lines = [f"Todas las notificaciones ({len(items)}):"]
        for i, n in enumerate(items, 1):
            read_tag = " [leida]" if n.get("read") else ""
            body_part = f" -- {n['body']}" if n.get("body") else ""
            lines.append(f"  [{i}] [{n['level']}]{read_tag} {n['title']}{body_part}")
        _show_response("\n".join(lines), "cyan")
    except Exception as e:
        _print_line(f"[err_cl]Error al listar notificaciones: {e}[/err_cl]")


def _slash_notif_leer(args: str) -> None:
    if not args.strip():
        _print_line("[warn_cl]Uso: /notif-leer <id>[/warn_cl]")
        return
    try:
        from cognia.notifications.notification_center import NotificationCenter
    except Exception:
        print("Sistema de notificaciones no disponible.")
        return
    try:
        notif_id = int(args.strip())
        nc = NotificationCenter()
        nc.mark_read(notif_id, _CLI_USER_ID)
        print(f"Notificacion {notif_id} marcada como leida.")
    except ValueError:
        _print_line("[warn_cl]El id debe ser un numero.[/warn_cl]")
    except Exception as e:
        _print_line(f"[err_cl]Error: {e}[/err_cl]")


def _slash_notif_limpiar(args: str) -> None:
    try:
        from cognia.notifications.notification_center import NotificationCenter
    except Exception:
        print("Sistema de notificaciones no disponible.")
        return
    try:
        nc = NotificationCenter()
        count = nc.mark_all_read(_CLI_USER_ID)
        print(f"{count} notificaciones marcadas como leidas.")
    except Exception as e:
        _print_line(f"[err_cl]Error: {e}[/err_cl]")


# ---------------------------------------------------------------------------
# Recommendation commands
# ---------------------------------------------------------------------------

def _slash_recomendar(args: str) -> None:
    try:
        import requests
        resp = requests.get("http://localhost:8765/recommendations", timeout=5)
        if resp.status_code == 200:
            recs = resp.json().get("recommendations", [])
            if not recs:
                print("No hay recomendaciones en este momento.")
                return
            print("Recomendaciones personalizadas:")
            for r in recs:
                prio = r.get("priority", "?")
                title = r.get("title", "")
                reason = r.get("reason", "")
                action = r.get("action", "")
                print(f"  {prio}. [{r.get('type','?')}] {title}")
                print(f"     Razon : {reason}")
                print(f"     Accion: {action}")
                print()
        else:
            print(f"Error: {resp.status_code}")
    except Exception:
        print("Servicio de recomendaciones no disponible.")


def _slash_digest(args: str) -> None:
    try:
        import requests
        resp = requests.get("http://localhost:8765/digest", timeout=5)
        if resp.status_code == 200:
            digest_text = resp.json().get("digest", "")
            print(digest_text if digest_text else "Digest no disponible.")
        else:
            print(f"Error: {resp.status_code}")
    except Exception:
        print("Servicio de digest no disponible. Inicia cognia_desktop_api.py.")


def _slash_cognia_info(args: str) -> None:
    print("Cognia v3 -- Asistente AGI experimental")
    print()
    print("Capacidades principales:")
    capabilities = [
        ("Inferencia",          "Modelo Qwen2.5-Coder-3B INT4, 4 shards, numpy puro"),
        ("Memoria",             "Episodica + semantica TF-IDF + cristalizacion KG"),
        ("Aprendizaje",         "Repaso espaciado SM-2 + caminos de aprendizaje"),
        ("Objetivos",           "Gestion de metas con descomposicion de tareas"),
        ("Personalizacion",     "Perfil de usuario + hechos personales + persona"),
        ("Retroalimentacion",   "Senal implicita/explicita + autocritica heuristica"),
        ("Conocimiento",        "KG SQLite + multihop + cristalizacion + consistencia"),
        ("Busqueda",            "DuckDuckGo web + semantica sobre historial"),
        ("Agentes",             "ReAct loop + supervisor + planner + synthesizer"),
        ("Gamificacion",        "10 logros + racha + puntuacion cognitiva"),
    ]
    for name, desc in capabilities:
        print(f"  {name:20} : {desc}")
    print()
    total_cmds = len(_CMD_DESCRIPTIONS)
    print(f"Comandos CLI disponibles: {total_cmds}")
    print("Usa /help para verlos todos o /ayuda <cmd> para detalle.")


def _slash_inicio_dia(args: str) -> None:
    print("Buenos dias. Iniciando Cognia...")
    print()
    _slash_digest("")
    print()
    _slash_proximos_pasos("")
    print()
    try:
        import requests
        r = requests.get("http://localhost:8765/learning/stats", timeout=2)
        if r.status_code == 200:
            due = r.json().get("due_today", 0)
            if due > 0:
                print(f"Recuerda: tienes {due} tarjeta(s) de repaso. Usa /revisar.")
    except Exception:
        pass


def _slash_proximos_pasos(args: str) -> None:
    try:
        import requests
        resp = requests.get("http://localhost:8765/recommendations/top", timeout=3)
        if resp.status_code == 200:
            rec = resp.json().get("recommendation")
            if not rec:
                print("Todo al dia. No hay acciones urgentes.")
                return
            print(f"Proximo paso recomendado:")
            print(f"  {rec.get('title','')}")
            print(f"  {rec.get('reason','')}")
            print(f"  -> {rec.get('action','')}")
        else:
            print(f"Error: {resp.status_code}")
    except Exception:
        print("Servicio no disponible.")


def _slash_mapa(args: str) -> None:
    if not args.strip():
        print("Uso: /mapa <concepto central>")
        return
    center = args.strip()
    print(f"Mapa mental: {center}")
    print()
    connected_nodes = []
    try:
        import requests, urllib.parse
        q = urllib.parse.quote(center)
        resp = requests.get(f"http://localhost:8765/kg/facts?subject={q}&limit=8", timeout=3)
        if resp.status_code == 200:
            facts = resp.json().get("facts", resp.json() if isinstance(resp.json(), list) else [])
            for f in facts[:8]:
                if isinstance(f, dict):
                    connected_nodes.append(f"{f.get('predicate','?')}: {f.get('object','?')}")
                elif isinstance(f, str):
                    connected_nodes.append(f)
    except Exception:
        pass

    if connected_nodes:
        print(f"  {center}")
        for i, node in enumerate(connected_nodes):
            connector = "  +-- "
            print(f"{connector}{node}")
    else:
        print(f"  {center}")
        print(f"  +-- definicion: que es {center}")
        print(f"  +-- causas: que origina {center}")
        print(f"  +-- efectos: consecuencias de {center}")
        print(f"  +-- relaciones: conceptos asociados a {center}")
        print(f"  +-- aplicaciones: usos practicos de {center}")
    print()
    print(f"Tip: usa /kg-agregar para agregar relaciones sobre '{center}'")


# ---------------------------------------------------------------------------
# Reminder commands
# ---------------------------------------------------------------------------

def _slash_recordar(args: str) -> None:
    """Crea un recordatorio relativo. Formato: <titulo> en <N> minutos|horas"""
    try:
        from cognia.reminders.reminder_manager import ReminderManager
    except Exception:
        print("Sistema de recordatorios no disponible.")
        return
    _HELP = (
        "Uso: /recordar <titulo> en <N> minutos|horas\n"
        "Ejemplos:\n"
        "  /recordar Revisar meta Python en 30 minutos\n"
        "  /recordar Hacer commit en 2 horas"
    )
    args = args.strip()
    if not args:
        print(_HELP)
        return
    # Parse pattern: <titulo> en <N> <minutos|horas>
    _match = re.search(r'^(.+?)\s+en\s+(\d+)\s+(minutos?|horas?)$', args, re.IGNORECASE)
    if not _match:
        print(_HELP)
        return
    titulo = _match.group(1).strip()
    n = int(_match.group(2))
    unit = _match.group(3).lower()
    minutes = n * 60 if unit.startswith("hora") else n
    try:
        rm = ReminderManager()
        rm.create_relative(user_id=_CLI_USER_ID, title=titulo, minutes=minutes)
        print(f"Recordatorio creado: '{titulo}' en {minutes} minutos")
    except Exception as e:
        _print_line(f"[err_cl]Error al crear recordatorio: {e}[/err_cl]")


def _slash_recordatorios(args: str) -> None:
    """Lista recordatorios pendientes del usuario CLI."""
    try:
        from cognia.reminders.reminder_manager import ReminderManager
    except Exception:
        print("Sistema de recordatorios no disponible.")
        return
    try:
        import time as _t
        rm = ReminderManager()
        pending = rm.get_pending(_CLI_USER_ID)
        if not pending:
            print("(Sin recordatorios pendientes)")
            return
        lines = ["Recordatorios pendientes:"]
        now = _t.time()
        for i, r in enumerate(pending, 1):
            secs_left = max(0, r["fire_at"] - now)
            total_min = int(secs_left // 60)
            fire_dt = datetime.datetime.fromtimestamp(r["fire_at"])
            fire_str = fire_dt.strftime("%H:%M")
            if total_min >= 60:
                h = total_min // 60
                m = total_min % 60
                time_label = f"en {h}h {m}min" if m else f"en {h}h"
            else:
                time_label = f"en {total_min} min"
            lines.append(f"  [{r['id']}] {r['title']} -- {time_label} (a las {fire_str})")
        _show_response("\n".join(lines), "cyan")
    except Exception as e:
        _print_line(f"[err_cl]Error al listar recordatorios: {e}[/err_cl]")


def _slash_recordar_cancelar(args: str) -> None:
    """Cancela un recordatorio por id."""
    try:
        from cognia.reminders.reminder_manager import ReminderManager
    except Exception:
        print("Sistema de recordatorios no disponible.")
        return
    if not args.strip():
        print("Uso: /recordar-cancelar <id>")
        return
    try:
        rid = int(args.strip())
        rm = ReminderManager()
        ok = rm.cancel(rid, _CLI_USER_ID)
        if ok:
            print(f"Recordatorio {rid} cancelado.")
        else:
            print(f"Recordatorio {rid} no encontrado o ya no esta pendiente.")
    except ValueError:
        _print_line("[warn_cl]El id debe ser un numero.[/warn_cl]")
    except Exception as e:
        _print_line(f"[err_cl]Error: {e}[/err_cl]")


# ---------------------------------------------------------------------------
# Persistent user config
# ---------------------------------------------------------------------------

_CONFIG_PATH = Path.home() / ".cognia_config.json"

_CONFIG_DEFAULTS: dict = {
    "persona":          "casual",
    "idioma":           "auto",
    "max_historial":    "50",
    "tema_kg":          "",
    "recordar_sesion":  "true",
    "nivel_detalle":    "normal",
}


def _load_config() -> dict:
    if _CONFIG_PATH.exists():
        try:
            return {**_CONFIG_DEFAULTS, **json.load(_CONFIG_PATH.open(encoding="utf-8"))}
        except Exception:
            return dict(_CONFIG_DEFAULTS)
    return dict(_CONFIG_DEFAULTS)


def _save_config(cfg: dict) -> None:
    _CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


def _slash_config(args: str) -> None:
    args = args.strip()
    parts = args.split(None, 2)
    sub = parts[0].lower() if parts else "ver"

    if not args or sub == "ver":
        cfg = _load_config()
        lines = ["Configuracion actual (~/.cognia_config.json):"]
        for k, v in cfg.items():
            marker = " (*)" if v != _CONFIG_DEFAULTS.get(k, "") else ""
            lines.append(f"  {k}={v}{marker}")
        _print_line("\n".join(lines))

    elif sub == "set":
        if len(parts) < 3:
            _print_line("[warn_cl]Uso: /config set <clave> <valor>[/warn_cl]")
            return
        key, val = parts[1], parts[2]
        if key not in _CONFIG_DEFAULTS:
            _print_line(
                f"[warn_cl]Clave desconocida: {key}. "
                f"Claves validas: {', '.join(_CONFIG_DEFAULTS)}[/warn_cl]"
            )
            return
        cfg = _load_config()
        cfg[key] = val
        _save_config(cfg)
        _print_line(f"Config actualizada: {key}={val}")

    elif sub == "reset":
        _save_config(dict(_CONFIG_DEFAULTS))
        _print_line("Config restablecida a valores por defecto.")

    elif sub == "exportar":
        cfg = _load_config()
        _print_line(json.dumps(cfg, indent=2, ensure_ascii=False))

    else:
        _print_line(
            "[warn_cl]Uso:[/warn_cl]\n"
            "  /config              Mostrar configuracion\n"
            "  /config set k v      Cambiar valor\n"
            "  /config reset        Restablecer valores por defecto\n"
            "  /config exportar     Exportar como JSON"
        )


# ---------------------------------------------------------------------------
# Feedback commands
# ---------------------------------------------------------------------------

_VALID_SIGNALS = ("positivo", "negativo", "neutral")


def _slash_feedback(args: str) -> None:
    signal = args.strip().lower()
    if signal not in _VALID_SIGNALS:
        _print_line(
            f"[warn_cl]Senal invalida. Opciones: positivo, negativo, neutral[/warn_cl]"
        )
        return
    _session_feedback.append({"signal": signal, "ts": time.time()})
    if _feedback_learner is not None:
        try:
            _feedback_learner.record(signal)
        except Exception:
            pass
    print(f"Feedback registrado: {signal}.")


def _slash_feedback_sesion() -> None:
    pos = sum(1 for f in _session_feedback if f["signal"] == "positivo")
    neg = sum(1 for f in _session_feedback if f["signal"] == "negativo")
    neu = sum(1 for f in _session_feedback if f["signal"] == "neutral")
    print(f"Sesion: {pos} positivos, {neg} negativos, {neu} neutrales.")


def _slash_ayuda_detallada(args: str) -> None:
    cmd = args.strip()
    if not cmd.startswith("/"):
        cmd = "/" + cmd
    detail = _CMD_DETAILS.get(cmd)
    if detail:
        _show_response(f"{cmd}\n\n{detail}", "cyan")
        return
    short = _CMD_DESCRIPTIONS.get(cmd)
    if short:
        _show_response(f"Descripcion: {short}", "cyan")
        return
    print("Comando no encontrado. Usa /help para ver todos los comandos.")


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
    """Lista TODAS las skills: las de Cognia y las de Claude (~/.claude/skills, repo)."""
    try:
        from cognia.agent.skills import load_skills
        skills = load_skills()
    except Exception:
        skills = {}
    if not skills:
        _print_line("[detail]Sin skills. Crea una con /skill-nuevo <nombre>[/detail]")
        return
    lines = []
    for name in sorted(skills):
        s = skills[name]
        tag = "C" if s.kind == "claude" else "o"  # C=formato Claude, o=Cognia
        lines.append(f"  [{tag}] {name:<22} {s.description[:60]}")
    if _HAS_RICH and _console:
        from rich.markup import escape as _esc
        _console.print(f"[cyan]Skills disponibles ({len(skills)}) -- usa /skill <nombre> [tarea]:[/cyan]")
        for ln in lines:
            _console.print(f"[detail]{_esc(ln)}[/detail]")
    else:
        print(f"Skills disponibles ({len(skills)}):")
        for ln in lines:
            print(ln)


def _slash_skill(arg: str, ai):
    """
    Aplica una skill (formato Claude o Cognia).
      /skill <nombre>          -> muestra la skill
      /skill <nombre> <tarea>  -> ejecuta la tarea con el agente guiado por la skill
    """
    from cognia.agent.skills import load_skills, skill_guidance
    parts = (arg or "").strip().split(None, 1)
    skills = load_skills()
    if not parts:
        _print_line("[detail]Uso: /skill <nombre> [tarea].  Lista: /skills[/detail]")
        return
    name = parts[0]
    task = parts[1].strip() if len(parts) > 1 else ""
    s = skills.get(name) or next(
        (v for k, v in skills.items() if k.lower().startswith(name.lower())), None)
    if not s:
        _print_line(f"[warn_cl]No encontre la skill '{_escape(name)}'. Lista: /skills[/warn_cl]")
        return
    if not task:
        _show_response(
            f"Skill '{s.name}' [{s.kind}]\n{s.description}\n\n{s.body[:1500]}", _ACCENT)
        return
    _print_line(f"[detail]Ejecutando con skill '{s.name}'...[/detail]")
    _resp = _run_agent_task(ai, task, _print_line, guidance=skill_guidance(s))
    _show_response(_resp, _ACCENT)
    _session_log.append({"input": f"/skill {name} {task}", "output": _resp, "elapsed": 0})
    _persist_turn(ai, f"/skill {name} {task}", _resp)


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
        from cognia_v3.interfaces.respuestas_articuladas import responder_articulado
        result = responder_articulado(ai, prompt)
        if "error" in result:
            return f"Error: {result['error']}"
        return result.get("response", "")
    except Exception as e:
        return f"Error: {e}"


def _slash_largo(ai, pedido: str) -> None:
    """
    /largo <pedido>: generacion larga (hasta GEN_LONG_MAX_TOKENS tokens) via el
    fast-path llama.cpp con continuacion automatica (LlamaBackend.generate_long).
    Imprime progreso ASCII por ronda y el texto completo al final.
    """
    from shattering.model_constants import (
        COGNIA_SYSTEM_PROMPT, GEN_CHAT_TEMPERATURE, GEN_LONG_MAX_TOKENS,
    )
    # Mismo fast-path que el chat libre: orquestador cacheado en ai si existe,
    # si no uno local, y _try_load_llama() para obtener el backend llama.cpp.
    _llama = None
    try:
        from shattering.orchestrator import ShatteringOrchestrator as _SO
        _orch = getattr(ai, '_orchestrator', None)
        if _orch is None:
            try:
                _orch = _SO(mode='local')
            except Exception:
                _orch = None
        if _orch is not None:
            _llama = getattr(_orch, '_llama', None)
            if _llama is None:
                try:
                    _orch._try_load_llama()
                    _llama = getattr(_orch, '_llama', None)
                except Exception:
                    pass
    except Exception:
        pass
    if _llama is None or not hasattr(_llama, "generate_long"):
        _print_line("[warn_cl]backend llama no disponible (GGUF o llama-server "
                    "faltante) -- /largo necesita el fast-path llama.cpp[/warn_cl]")
        return

    # Prompt ChatML igual que el fallback del fast-path de chat (sin historial:
    # el pedido largo es one-shot, el contexto entero se gasta en la respuesta).
    try:
        from cognia.agent.adaptive_prompt import build_adaptive_system_prompt
        from cognia.user_prefs import personalize_prompt
        _system = personalize_prompt(build_adaptive_system_prompt(ai))
    except Exception:
        _system = COGNIA_SYSTEM_PROMPT
    from node.inference_pipeline import _apply_qwen_template
    _prompt = _apply_qwen_template(pedido, _system)

    _print_line(f"[detail]Generando hasta {GEN_LONG_MAX_TOKENS} tokens "
                f"(continuacion automatica, ~10 min a 8 tok/s)...[/detail]")
    t0 = time.time()

    def _on_chunk(ronda, chunk_toks, total, reason):
        # Progreso ASCII puro (consola Windows CP1252)
        print(f"  ronda {ronda}: {chunk_toks} tokens, total {total}", flush=True)

    result = _llama.generate_long(
        _prompt,
        temperature=GEN_CHAT_TEMPERATURE,
        on_chunk=_on_chunk,
    )
    elapsed = time.time() - t0
    if result is None:
        _print_line("[warn_cl]La generacion larga fallo (primera ronda sin "
                    "respuesta del backend).[/warn_cl]")
        return
    texto = (result.get("text") or "").strip()
    if not texto:
        _print_line("[warn_cl]La generacion larga devolvio texto vacio.[/warn_cl]")
        return
    _show_response(texto, _ACCENT)
    print(f"  [{result['total_tokens']} tokens, {result['rounds']} rondas, "
          f"{elapsed:.0f}s, stop={result['stop_reason']}]")
    _session_log.append({"input": f"/largo {pedido}", "output": texto,
                         "elapsed": elapsed})
    _persist_turn(ai, f"/largo {pedido}", texto)


def _modelo_activo_nombre(_llama) -> str:
    """Nombre del GGUF activo: /props del server si responde, si no el
    configurado en el backend, si no LLAMA_GGUF_PATH, si no el default del
    registry. Siempre devuelve un string ASCII descriptivo."""
    from shattering.model_constants import (
        MODEL_GGUF_DEFAULT, MODEL_GGUF_REGISTRY,
    )
    if _llama is not None:
        try:
            props = _llama.server_props()
        except Exception:
            props = None
        if props:
            from node.llama_backend import _server_props_summary
            mp = _server_props_summary(props).get("model_path")
            if mp:
                return f"{Path(mp).name} (server vivo)"
        gp = getattr(_llama, "gguf_path", None)
        if gp:
            return f"{Path(str(gp)).name} (configurado en backend)"
    env = os.environ.get("LLAMA_GGUF_PATH", "").strip()
    if env:
        return f"{Path(env).name} (LLAMA_GGUF_PATH, server no arrancado)"
    return (f"{Path(MODEL_GGUF_REGISTRY[MODEL_GGUF_DEFAULT]).name} "
            f"(default registry, server no arrancado)")


def _slash_modelo(ai, args: str) -> None:
    """
    /modelo [3b|7b]: ver o conmutar en caliente el modelo GGUF del backend.

    Sin args: muestra el modelo activo y los del registry con su existencia
    en disco ([OK]/[NO]). Con clave: para el llama-server actual, setea
    LLAMA_GGUF_PATH a la ruta absoluta del GGUF elegido y re-dispara la carga
    via ShatteringOrchestrator.reload_llama(), verificando por GET /props que
    el modelo cargado es el pedido. ASCII puro (consola Windows CP1252).
    """
    from shattering.model_constants import (
        MODEL_GGUF_REGISTRY, resolve_gguf_path,
    )

    # Backend actual: solo el orquestador YA cacheado en ai (no construir uno
    # nuevo ni disparar la carga del modelo solo para mostrar el estado).
    _orch  = getattr(ai, '_orchestrator', None)
    _llama = getattr(_orch, '_llama', None) if _orch is not None else None

    key = args.strip().split()[0].lower() if args.strip() else ""
    if not key:
        lines = [f"Modelo activo: {_modelo_activo_nombre(_llama)}",
                 "Disponibles (registry):"]
        for k, rel in MODEL_GGUF_REGISTRY.items():
            p = resolve_gguf_path(k)
            tag = "[OK]" if (p is not None and p.is_file()) else "[NO]"
            lines.append(f"  {tag} {k} -> {rel}")
        lines.append("Uso: /modelo <clave>  -- ejemplo: /modelo 7b")
        _show_response("\n".join(lines), "cyan")
        return

    if key not in MODEL_GGUF_REGISTRY:
        validas = ", ".join(sorted(MODEL_GGUF_REGISTRY))
        _print_line(f"[err_cl]Clave de modelo desconocida: '{key}'. "
                    f"Validas: {validas}[/err_cl]")
        return

    target = resolve_gguf_path(key)
    if not target.is_file():
        _print_line(f"[err_cl]GGUF no encontrado en disco: {target} -- "
                    f"no se cambia nada.[/err_cl]")
        return

    # Ya activo? Solo si hay un server VIVO que reporta ese GGUF por /props
    # (el nombre por default/env no cuenta: el server podria no estar corriendo).
    if _llama is not None:
        try:
            props = _llama.server_props()
        except Exception:
            props = None
        if props:
            from node.llama_backend import _server_props_summary
            mp = _server_props_summary(props).get("model_path")
            if mp and Path(mp).name == target.name:
                _print_line(f"[detail]{target.name} ya es el modelo activo.[/detail]")
                return

    # Parar el server actual. stop() devuelve False si el server fue adoptado
    # (proceso externo): en ese caso NO seguimos, porque el reload adoptaria
    # el server viejo con el modelo viejo.
    if _llama is not None:
        try:
            stopped = _llama.stop()
        except Exception:
            stopped = False
        if not stopped:
            _print_line("[err_cl]El llama-server actual fue arrancado "
                        "externamente y no se puede parar desde aca. "
                        "Cerralo manualmente y reintenta /modelo.[/err_cl]")
            return
    else:
        # Sin backend cacheado puede igual haber un server externo vivo en el
        # puerto: el reload lo adoptaria con el modelo viejo. Chequear antes.
        from node.llama_backend import _DEFAULT_PORT
        port = int(os.environ.get("LLAMA_SERVER_PORT", _DEFAULT_PORT))
        try:
            import urllib.request as _urlreq
            _urlreq.urlopen(f"http://127.0.0.1:{port}/health", timeout=1)
            _print_line(f"[err_cl]Hay un llama-server externo vivo en :{port} "
                        f"que este REPL no controla. Cerralo manualmente y "
                        f"reintenta /modelo.[/err_cl]")
            return
        except Exception:
            pass  # puerto libre: camino normal

    # Setear el GGUF elegido (ruta absoluta; _find_gguf prioriza este env var)
    os.environ["LLAMA_GGUF_PATH"] = str(target)

    _print_line(f"[detail]Cargando {target.name}... (el 7B tarda ~60-90s en "
                f"frio; el REPL queda bloqueado mientras tanto)[/detail]")

    # Recargar el backend: orquestador cacheado en ai si existe, si no uno
    # local nuevo (mismo patron que /largo).
    if _orch is None:
        try:
            from shattering.orchestrator import ShatteringOrchestrator as _SO
            _orch = _SO(mode='local')
        except Exception as e:
            _print_line(f"[err_cl]No se pudo construir el orquestador: {e}[/err_cl]")
            return
    try:
        nuevo = _orch.reload_llama()
    except Exception as e:
        _print_line(f"[err_cl]La recarga del backend fallo: {e}[/err_cl]")
        return
    if nuevo is None:
        _print_line("[err_cl]El backend no cargo con el nuevo GGUF (binario "
                    "llama-server o runtime faltante?). Revisa los logs.[/err_cl]")
        return

    # Verificar via GET /props que el server nuevo cargo el modelo pedido
    real = None
    try:
        props = nuevo.server_props()
    except Exception:
        props = None
    if props:
        from node.llama_backend import _server_props_summary
        real = _server_props_summary(props).get("model_path")
    if real is None:
        # Backend in-process (sin /props): confiar en la ruta configurada
        gp = getattr(nuevo, "gguf_path", None)
        real = str(gp) if gp else None
    if real and Path(real).name == target.name:
        _print_line(f"[ok]Modelo activo: {Path(real).name}[/ok]")
    else:
        _print_line(f"[warn_cl]Backend cargado pero el modelo reportado no "
                    f"coincide (esperado {target.name}, server reporta "
                    f"{real}).[/warn_cl]")


# ---------------------------------------------------------------------------
# Template helpers
# ---------------------------------------------------------------------------

def _slash_templates(args: str) -> None:
    """Lista templates de conversacion disponibles (builtin + custom)."""
    try:
        from cognia.templates.conversation_templates import ConversationTemplateManager, BUILTIN_TEMPLATES
    except ImportError:
        _print_line("[err_cl]Modulo conversation_templates no disponible.[/err_cl]")
        return
    try:
        mgr = ConversationTemplateManager()
        all_tpls = mgr.list_templates()
        builtin_ids = set(BUILTIN_TEMPLATES.keys())
        builtin_tpls = [t for t in all_tpls if t["id"] in builtin_ids]
        custom_tpls  = [t for t in all_tpls if t["id"] not in builtin_ids]
        lines = ["Templates disponibles:"]
        for t in builtin_tpls:
            est = t.get("estimated_turns", "?")
            lines.append(f"  [{t['id']}] {t['name']} -- {t['description']} (~{est} turnos)")
        if custom_tpls:
            lines.append(f"  + {len(custom_tpls)} templates custom")
        _show_response("\n".join(lines), "cyan")
    except Exception as e:
        _print_line(f"[err_cl]Error al listar templates: {e}[/err_cl]")


def _slash_template(args: str) -> None:
    """Inicia sesion con un template dado su ID."""
    template_id = args.strip()
    if not template_id:
        _print_line("[warn_cl]Uso: /template <id>  -- ejemplo: /template code_review[/warn_cl]")
        return
    try:
        from cognia.templates.conversation_templates import ConversationTemplateManager
    except ImportError:
        _print_line("[err_cl]Modulo conversation_templates no disponible.[/err_cl]")
        return
    try:
        mgr = ConversationTemplateManager()
        tpl = mgr.get_template(template_id)
        if tpl is None:
            _print_line(f"[warn_cl]Template '{template_id}' no encontrado. Usa /templates para ver los disponibles.[/warn_cl]")
            return
        lines = [
            f"Iniciando template: {tpl['name']}",
            "",
            tpl["initial_prompt"],
            "",
            "Preguntas guia:",
        ]
        for i, q in enumerate(tpl["guide_questions"], 1):
            lines.append(f"  {i}. {q}")
        lines.append("")
        lines.append("(escribe tu primera respuesta)")
        _show_response("\n".join(lines), "bright_cyan")
    except Exception as e:
        _print_line(f"[err_cl]Error al cargar template: {e}[/err_cl]")


def _slash_template_guia(args: str) -> None:
    """Muestra solo las preguntas guia de un template."""
    template_id = args.strip()
    if not template_id:
        _print_line("[warn_cl]Uso: /template-guia <id>  -- ejemplo: /template-guia brainstorming[/warn_cl]")
        return
    try:
        from cognia.templates.conversation_templates import ConversationTemplateManager
    except ImportError:
        _print_line("[err_cl]Modulo conversation_templates no disponible.[/err_cl]")
        return
    try:
        mgr = ConversationTemplateManager()
        tpl = mgr.get_template(template_id)
        if tpl is None:
            _print_line(f"[warn_cl]Template '{template_id}' no encontrado. Usa /templates para ver los disponibles.[/warn_cl]")
            return
        lines = [f"Preguntas guia -- {tpl['name']}:"]
        for i, q in enumerate(tpl["guide_questions"], 1):
            lines.append(f"  {i}. {q}")
        _show_response("\n".join(lines), "cyan")
    except Exception as e:
        _print_line(f"[err_cl]Error al cargar guia: {e}[/err_cl]")


def _slash_buscar_web(args: str) -> None:
    """Busca en DuckDuckGo usando WebSearch y muestra resultado estructurado."""
    query = args.strip()
    if not query:
        _print_line("[warn_cl]Uso: /buscar-web <query>[/warn_cl]")
        return
    try:
        from cognia.search.web_search import WebSearch
    except ImportError:
        _print_line("[err_cl]Modulo WebSearch no disponible (cognia/search/web_search.py)[/err_cl]")
        return
    try:
        ws = WebSearch()
        result = ws.search(query)
        if result.get("error"):
            _print_line(f"[err_cl]Error en busqueda: {result['error']}[/err_cl]")
            return
        lines = [f"Busqueda: {query}"]
        answer = result.get("answer", "").strip()
        abstract = result.get("abstract", "").strip()
        if answer:
            lines.append(f"Respuesta directa: {answer}")
        elif abstract:
            lines.append(f"Respuesta directa: {abstract}")
        src = result.get("abstract_source", "").strip()
        if src:
            lines.append(f"Fuente: {src}")
        topics = result.get("related_topics", [])
        if topics:
            lines.append("Temas relacionados:")
            for t in topics:
                lines.append(f"  - {t}")
        if not answer and not abstract and not topics:
            lines.append("(Sin resultados)")
        _show_response("\n".join(lines), "cyan")
    except Exception as e:
        _print_line(f"[err_cl]buscar-web error: {e}[/err_cl]")


def _slash_buscar_kg(args: str) -> None:
    """Busca hechos sobre un concepto en el Knowledge Graph local."""
    concepto = args.strip()
    if not concepto:
        _print_line("[warn_cl]Uso: /buscar-kg <concepto>[/warn_cl]")
        return
    try:
        from cognia.knowledge.graph import KnowledgeGraph
        from cognia.config import DB_PATH
    except ImportError:
        _print_line("[err_cl]Modulo KnowledgeGraph no disponible[/err_cl]")
        return
    try:
        kg = KnowledgeGraph(DB_PATH)
        facts = kg.get_facts(concepto.lower())
        if not facts:
            _print_line(f"[detail](Sin hechos en el grafo para '{concepto}')[/detail]")
            return
        lines = [f"Hechos sobre '{concepto}':"]
        for f in facts:
            lines.append(f"  - {f['subject']} {f['predicate']} {f['object']}")
        _show_response("\n".join(lines), "cyan")
    except Exception as e:
        _print_line(f"[err_cl]buscar-kg error: {e}[/err_cl]")


def _slash_kg_agregar(args: str) -> None:
    """Agrega un triple al Knowledge Graph. Uso: /kg-agregar <sujeto> <predicado> <objeto>"""
    tokens = args.strip().split()
    if len(tokens) < 3:
        _print_line("[warn_cl]Uso: /kg-agregar <sujeto> <predicado> <objeto>[/warn_cl]")
        _print_line("[detail]Ejemplo: /kg-agregar Python es_un lenguaje[/detail]")
        return
    subject, predicate, obj = tokens[0], tokens[1], " ".join(tokens[2:])
    try:
        from cognia.knowledge.graph import KnowledgeGraph
        from cognia.config import DB_PATH
    except ImportError:
        _print_line("[err_cl]Modulo KnowledgeGraph no disponible[/err_cl]")
        return
    try:
        kg = KnowledgeGraph(DB_PATH)
        kg.add_triple(subject, predicate, obj, weight=0.8)
        print(f"Triple agregado: {subject} {predicate} {obj}")
    except Exception as e:
        _print_line(f"[err_cl]kg-agregar error: {e}[/err_cl]")


def _slash_kg_stats(args: str) -> None:
    """Muestra estadisticas del Knowledge Graph."""
    try:
        from cognia.knowledge.graph import KnowledgeGraph
        from cognia.config import DB_PATH
        from storage.db_pool import db_connect_pooled as _dcp
    except ImportError:
        _print_line("[err_cl]Modulo KnowledgeGraph no disponible[/err_cl]")
        return
    try:
        conn = _dcp(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM knowledge_graph")
        total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(DISTINCT subject) + COUNT(DISTINCT object) FROM knowledge_graph")
        # Use a proper distinct count across both columns
        cur.execute(
            "SELECT COUNT(*) FROM ("
            "  SELECT subject AS concept FROM knowledge_graph"
            "  UNION"
            "  SELECT object AS concept FROM knowledge_graph"
            ")"
        )
        conceptos = cur.fetchone()[0]
        cur.execute("SELECT COUNT(DISTINCT predicate) FROM knowledge_graph")
        predicados = cur.fetchone()[0]
        conn.close()
        lines = [
            "Knowledge Graph:",
            f"  Triples totales: {total}",
            f"  Conceptos unicos: {conceptos}",
            f"  Predicados unicos: {predicados}",
        ]
        _show_response("\n".join(lines), "cyan")
    except Exception as e:
        _print_line(f"[err_cl]kg-stats error: {e}[/err_cl]")


def _slash_kg_predicados(args: str) -> None:
    """Lista predicados unicos en el Knowledge Graph."""
    try:
        from cognia.config import DB_PATH
        from storage.db_pool import db_connect_pooled as _dcp
    except ImportError:
        _print_line("[err_cl]db_pool no disponible[/err_cl]")
        return
    try:
        conn = _dcp(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT predicate FROM knowledge_graph LIMIT 20")
        rows = cur.fetchall()
        conn.close()
        if not rows:
            _print_line("[detail](Sin predicados en el KG)[/detail]")
            return
        lines = ["Predicados en el KG:"]
        for (pred,) in rows:
            lines.append(f"  - {pred}")
        _show_response("\n".join(lines), "cyan")
    except Exception as e:
        _print_line(f"[err_cl]kg-predicados error: {e}[/err_cl]")


def _slash_kg_exportar(args: str) -> None:
    """Exporta el Knowledge Graph a un archivo JSON."""
    import json as _json
    filename = args.strip() or "kg_export.json"
    try:
        from cognia.config import DB_PATH
        from storage.db_pool import db_connect_pooled as _dcp
    except ImportError:
        _print_line("[err_cl]db_pool no disponible[/err_cl]")
        return
    try:
        conn = _dcp(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT subject, predicate, object, weight FROM knowledge_graph")
        rows = cur.fetchall()
        conn.close()
        data = [
            {"subject": s, "predicate": p, "object": o, "weight": w}
            for s, p, o, w in rows
        ]
        Path(filename).write_text(_json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"KG exportado: {len(data)} triples en {filename}")
    except Exception as e:
        _print_line(f"[err_cl]kg-exportar error: {e}[/err_cl]")


def _slash_kg_inferir(args: str) -> None:
    """Infiere propiedades de un concepto via MultiHopEngine."""
    concept = args.strip()
    if not concept:
        _print_line("[warn_cl]Uso: /kg-inferir <concepto>[/warn_cl]")
        _print_line("[detail]Ejemplo: /kg-inferir Python[/detail]")
        return
    try:
        from cognia.knowledge.multihop_engine import MultiHopEngine
    except ImportError:
        _print_line("[err_cl]MultiHopEngine no disponible[/err_cl]")
        return
    try:
        engine = MultiHopEngine()
        result = engine.infer_properties(concept)
        chain = " -> ".join([concept] + result["parent_chain"]) if result["parent_chain"] else concept
        lines = [
            f"Propiedades de '{concept}':",
            f"Cadena de herencia: {chain}",
            f"Hechos directos ({len(result['direct_facts'])}):",
        ]
        for f in result["direct_facts"]:
            lines.append(f"  - {f['subject']} {f['predicate']} {f['object']}")
        lines.append(f"Hechos heredados ({len(result['inherited_facts'])}):")
        for f in result["inherited_facts"]:
            lines.append(f"  - {f['subject']} {f['predicate']} {f['object']}")
        _show_response("\n".join(lines), "cyan")
    except Exception as e:
        _print_line(f"[err_cl]kg-inferir error: {e}[/err_cl]")


def _slash_kg_relacionar(args: str) -> None:
    """Explica la relacion entre dos conceptos via MultiHopEngine."""
    parts = args.strip().split(None, 1)
    if len(parts) < 2:
        _print_line("[warn_cl]Uso: /kg-relacionar <A> <B>[/warn_cl]")
        _print_line("[detail]Ejemplo: /kg-relacionar Python JavaScript[/detail]")
        return
    concept_a, concept_b = parts[0], parts[1]
    try:
        from cognia.knowledge.multihop_engine import MultiHopEngine
    except ImportError:
        _print_line("[err_cl]MultiHopEngine no disponible[/err_cl]")
        return
    try:
        engine = MultiHopEngine()
        result = engine.explain_relationship(concept_a, concept_b)
        lines = [
            f"Relacion entre '{concept_a}' y '{concept_b}':",
            f"Tipo: {result['relationship_type']}",
            result["explanation"],
        ]
        if result["common_ancestors"]:
            lines.append(f"Ancestros comunes: {result['common_ancestors']}")
        _show_response("\n".join(lines), "cyan")
    except Exception as e:
        _print_line(f"[err_cl]kg-relacionar error: {e}[/err_cl]")


def _slash_kg_responder(args: str) -> None:
    """Responde una pregunta usando el Knowledge Graph (multi-hop)."""
    question = args.strip()
    if not question:
        _print_line("[warn_cl]Uso: /kg-responder <pregunta>[/warn_cl]")
        _print_line("[detail]Ejemplo: /kg-responder que es Python[/detail]")
        return
    try:
        from cognia.knowledge.multihop_engine import MultiHopEngine
    except ImportError:
        _print_line("[err_cl]MultiHopEngine no disponible[/err_cl]")
        return
    try:
        engine = MultiHopEngine()
        result = engine.answer_question(question)
        lines = [
            f"Respuesta (confianza: {result['confidence']:.1f}):",
            result["answer_text"],
            f"Entidades encontradas: {', '.join(result['entities_found']) if result['entities_found'] else '(ninguna)'}",
        ]
        _show_response("\n".join(lines), "cyan")
    except Exception as e:
        _print_line(f"[err_cl]kg-responder error: {e}[/err_cl]")


def _slash_kg_camino(args: str) -> None:
    """Encuentra el camino entre dos conceptos en el Knowledge Graph."""
    parts = args.strip().split(None, 1)
    if len(parts) < 2:
        _print_line("[warn_cl]Uso: /kg-camino <A> <B>[/warn_cl]")
        _print_line("[detail]Ejemplo: /kg-camino Python lenguaje[/detail]")
        return
    concept_a, concept_b = parts[0], parts[1]
    try:
        from cognia.knowledge.multihop_engine import MultiHopEngine
    except ImportError:
        _print_line("[err_cl]MultiHopEngine no disponible[/err_cl]")
        return
    try:
        engine = MultiHopEngine()
        path = engine.find_path(concept_a, concept_b)
        if not path:
            _show_response(f"(Sin camino entre {concept_a} y {concept_b})", "cyan")
            return
        chain_parts = []
        for subj, pred, obj in path:
            chain_parts.append(f"{subj} --{pred}-->")
        chain_parts.append(concept_b)
        lines = [
            f"Camino de '{concept_a}' a '{concept_b}':",
            " ".join(chain_parts),
        ]
        _show_response("\n".join(lines), "cyan")
    except Exception as e:
        _print_line(f"[err_cl]kg-camino error: {e}[/err_cl]")


def _slash_reporte() -> None:
    try:
        from cognia.reports.progress_reporter import ProgressReporter
    except ImportError:
        print("ProgressReporter no disponible.")
        return
    try:
        reporter = ProgressReporter()
        md = reporter.generate_report(user_id=_CLI_USER_ID, period_days=7)
        if _HAS_RICH and _console:
            _console.print(md, markup=False)
        else:
            print(md)
    except Exception as e:
        _print_line(f"[err_cl]Error al generar reporte: {e}[/err_cl]")


def _slash_reporte_json() -> None:
    try:
        from cognia.reports.progress_reporter import ProgressReporter
    except ImportError:
        print("ProgressReporter no disponible.")
        return
    try:
        reporter = ProgressReporter()
        stats = reporter.generate_json_stats(user_id=_CLI_USER_ID, period_days=7)
        lines = [
            "Estadisticas (7 dias):",
            f"- Metas activas: {stats.get('goals_active', 0)}",
            f"- Metas completadas: {stats.get('goals_completed', 0)}",
            f"- Mensajes totales: {stats.get('messages_total', 0)}",
            f"- Sesiones: {stats.get('sessions_total', 0)}",
            f"- Insights de curiosidad: {stats.get('insights_count', 0)}",
        ]
        _show_response("\n".join(lines), "cyan")
    except Exception as e:
        _print_line(f"[err_cl]Error al obtener estadisticas: {e}[/err_cl]")


def _slash_reporte_completo(args: str) -> None:
    try:
        import requests
        resp = requests.get("http://localhost:8765/reports/generate?period=7", timeout=10)
        if resp.status_code == 200:
            report = resp.json().get("report", "")
            if args.strip():
                from pathlib import Path
                p = Path(args.strip())
                p.write_text(report, encoding="utf-8")
                print(f"Reporte guardado en: {p.resolve()}")
            else:
                print(report)
        else:
            print(f"Error: {resp.status_code}")
    except Exception:
        print("Servicio de reportes no disponible.")


def _slash_reporte_semanal(args: str) -> None:
    try:
        import requests
        import datetime as _dt
        from pathlib import Path
        resp = requests.get("http://localhost:8765/reports/generate?period=7", timeout=10)
        if resp.status_code == 200:
            report = resp.json().get("report", "")
            dest_dir = Path.home() / ".cognia_reports"
            dest_dir.mkdir(exist_ok=True)
            stamp = _dt.datetime.now().strftime("%Y%m%d")
            path = dest_dir / f"reporte_semanal_{stamp}.md"
            path.write_text(report, encoding="utf-8")
            print(f"Reporte semanal guardado: {path}")
            lines = report.split("\n")[:10]
            print("\n".join(lines))
            if len(report.split("\n")) > 10:
                print(f"... ({len(report.split(chr(10)))} lineas total)")
        else:
            print(f"Error: {resp.status_code}")
    except Exception:
        print("Servicio de reportes no disponible.")


def _slash_cadena_causal(args: str) -> None:
    if not args.strip():
        print("Uso: /cadena-causal <concepto>")
        return
    c = args.strip()
    print(f"Cadena causal para: '{c}'")
    print()
    print(f"Causas posibles de '{c}':")
    print(f"  factores externos -> condiciones previas -> {c}")
    print()
    print(f"Efectos de '{c}':")
    print(f"  {c} -> consecuencias directas -> impacto en sistema")
    print()
    print(f"Para un analisis mas profundo, combina con /kg-responder o /sintetizar {c}")


def _slash_metas_pendientes(args: str) -> None:
    try:
        import requests
        resp = requests.get("http://localhost:8765/goals?status=pending&limit=10", timeout=3)
        if resp.status_code == 200:
            goals = resp.json() if isinstance(resp.json(), list) else resp.json().get("goals", [])
            if not goals:
                print("No hay objetivos pendientes.")
                return
            print(f"Objetivos pendientes ({len(goals)}):")
            for g in goals:
                prog = g.get("progress_pct", 0)
                print(f"  [{prog:3d}%] {g.get('title', '?')}")
        else:
            print(f"Error: {resp.status_code}")
    except Exception:
        print("Servicio de objetivos no disponible.")


def _slash_yo_perfil() -> None:
    try:
        from cognia.profile.user_profile_builder import UserProfileBuilder
    except ImportError:
        print("UserProfileBuilder no disponible.")
        return
    try:
        builder = UserProfileBuilder()
        profile = builder.get_profile(_CLI_USER_ID)
        if profile is None:
            print("No hay perfil disponible. Chatea mas para generar uno.")
            return
        top = profile.get("top_topics", [])
        patterns = profile.get("query_patterns", [])
        lang = profile.get("dominant_language", "unknown")
        lines = ["Perfil de usuario:"]
        if top:
            lines.append("Top temas de interes:")
            for t in top[:5]:
                lines.append(f"  - {t['term']} ({t['count']} menciones)")
        else:
            lines.append("Top temas de interes: (ninguno aun)")
        lines.append(f"Patrones de consulta: {', '.join(patterns) if patterns else '(ninguno)'}")
        lines.append(f"Idioma dominante: {lang}")
        _show_response("\n".join(lines), "cyan")
    except Exception as e:
        _print_line(f"[err_cl]Error al obtener perfil: {e}[/err_cl]")


def _slash_yo_actualizar() -> None:
    try:
        from cognia.profile.user_profile_builder import UserProfileBuilder
    except ImportError:
        print("UserProfileBuilder no disponible.")
        return
    try:
        builder = UserProfileBuilder()
        profile = builder.build_profile()
        builder.save_profile(_CLI_USER_ID, profile)
        print("Perfil actualizado.")
    except Exception as e:
        _print_line(f"[err_cl]Error al actualizar perfil: {e}[/err_cl]")


def _slash_modo_rapido():
    global _fast_mode
    _fast_mode = not _fast_mode
    _print_line(f"[detail]modo rapido {'activado' if _fast_mode else 'desactivado'}[/detail]")


def _persist_setting(key: str, value: str) -> None:
    """Save a CLI preference to ~/.cognia/config.env. Best-effort."""
    try:
        from cognia.first_run import set_config_value
        set_config_value(key, value)
    except Exception:
        pass


def _slash_tema(arg: str = ""):
    """`/tema` cicla; `/tema <nombre>` fija uno de: oscuro, claro, alto_contraste. Persiste."""
    global _theme_idx, _console
    arg = (arg or "").strip().lower()
    if arg and arg in _THEMES:
        _theme_idx = _THEME_ORDER.index(arg)
    elif arg:
        _print_line(f"[warn_cl]Tema desconocido '{_escape(arg)}'. "
                    f"Opciones: {', '.join(_THEME_ORDER)}[/warn_cl]")
        return
    else:
        _theme_idx = (_theme_idx + 1) % len(_THEME_ORDER)
    name = _THEME_ORDER[_theme_idx]
    if _HAS_RICH:
        _console = Console(theme=_THEMES[name], highlight=False)
        _console.rule(f"[dim]Tema: {name} (guardado)[/dim]")
    else:
        print(f"Tema: {name} (Rich no disponible)")
    _persist_setting("COGNIA_THEME", name)


def _slash_color(arg: str = ""):
    """`/color <nombre>` fija el color de acento de las respuestas (ej: cyan, magenta, #ff8800). Persiste."""
    global _ACCENT
    color = (arg or "").strip()
    if not color:
        _print_line(f"[detail]Color de acento actual: {_ACCENT}. "
                    "Uso: /color <nombre|#hex> (ej: cyan, magenta, green, #ff8800)[/detail]")
        return
    # Validate via rich.Style; reject anything rich can't parse so we never break output.
    if _HAS_RICH:
        try:
            from rich.style import Style as _RStyle
            _RStyle.parse(color)
        except Exception:
            _print_line(f"[warn_cl]Color invalido '{_escape(color)}'. "
                        "Proba: cyan, magenta, green, yellow, blue, red, o #rrggbb[/warn_cl]")
            return
    _ACCENT = color
    _persist_setting("COGNIA_ACCENT", color)
    if _HAS_RICH and _console:
        _console.print(f"Color de acento: {color} (guardado)", style=color)
    else:
        print(f"Color de acento: {color} (guardado)")


def _slash_memoria_limite(arg: str, ai):
    """
    Ver o fijar el tope de memoria. Persiste y aplica al instante.
      /memoria-limite                 -> uso actual + limites
      /memoria-limite <N> [MB]        -> tope de N recuerdos (y opcional MB)
      /memoria-limite off             -> sin limites
    """
    from cognia.memory.memory_budget import current_usage, get_limits, enforce_memory_budget
    arg = (arg or "").strip().lower()
    db = getattr(ai, "db", None)

    if not arg:
        u = current_usage(db)
        mc, mmb = get_limits()
        _show_response(
            "Memoria episodica:\n"
            f"  Activos : {u['active']}\n"
            f"  Totales : {u['total']}\n"
            f"  Disco   : {u['mb']} MB\n"
            f"  Tope recuerdos : {mc if mc else 'sin limite'}\n"
            f"  Tope disco     : {str(mmb)+' MB' if mmb else 'sin limite'}\n"
            "  Fijar: /memoria-limite <N> [MB]   |   quitar: /memoria-limite off",
            _ACCENT,
        )
        return

    if arg in ("off", "0", "ninguno", "sin"):
        _persist_setting("COGNIA_MAX_MEMORIES", "0")
        _persist_setting("COGNIA_MAX_DB_MB", "0")
        _print_line("[ok_cl]Topes de memoria desactivados.[/ok_cl]")
        return

    parts = arg.split()
    try:
        count = int(float(parts[0]))
        mb = float(parts[1]) if len(parts) > 1 else None
    except Exception:
        _print_line("[warn_cl]Uso: /memoria-limite <N recuerdos> [MB][/warn_cl]")
        return
    _persist_setting("COGNIA_MAX_MEMORIES", str(count))
    if mb is not None:
        _persist_setting("COGNIA_MAX_DB_MB", str(int(mb)))
    _print_line(f"[detail]Aplicando tope ({count} recuerdos"
                + (f", {mb:.0f} MB" if mb else "") + ")...[/detail]")
    rep = enforce_memory_budget(db, max_count=count, max_mb=mb)
    _show_response(
        f"Tope aplicado. Archivados: {rep['soft_deleted']}, borrados: {rep['hard_deleted']}. "
        f"Ahora: {rep['after']['active']} activos, {rep['after']['mb']} MB.",
        _ACCENT,
    )


# ---------------------------------------------------------------------------
# Chat history slash command implementations
# ---------------------------------------------------------------------------

def _fmt_ts(ts) -> str:
    """Format a chat_history timestamp (ISO string) for display, best-effort."""
    if ts is None:
        return "?"
    try:
        return datetime.datetime.fromisoformat(str(ts)).strftime("%Y-%m-%d %H:%M")
    except Exception:
        # Legacy rows may store an epoch int.
        try:
            return datetime.datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return str(ts)[:16]


def _slash_sesiones(args: str) -> None:
    """Lista sesiones de chat recientes (id, fecha, directorio)."""
    try:
        from cognia.config import DB_PATH
        from storage.db_pool import db_connect_pooled as _dcp
    except ImportError as _ie:
        _print_line(f"[err_cl]db_pool no disponible: {_ie}[/err_cl]")
        return
    try:
        conn = _dcp(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            "SELECT session_id, cwd, COUNT(*), MAX(timestamp)"
            " FROM chat_history WHERE session_id IS NOT NULL"
            " GROUP BY session_id ORDER BY MAX(id) DESC LIMIT 10"
        )
        rows = cur.fetchall()
        conn.close()
        if not rows:
            _print_line("[detail]Sin sesiones con identificador en el historial. "
                        "(Las sesiones se registran al iniciar el CLI.)[/detail]")
            return
        lines = ["Sesiones recientes (reanuda con /resume <id> o /resume <directorio>):"]
        for sid, cwd, cnt, last_ts in rows:
            sid_short = str(sid)[:8] if sid else "?"
            lines.append(f"  [{sid_short}] {_fmt_ts(last_ts)}  {cnt:>3} msgs  {cwd or '?'}")
        _show_response("\n".join(lines), "cyan")
    except Exception as _e:
        _print_line(f"[err_cl]sesiones error: {_e}[/err_cl]")


def _slash_resume(args: str, ai) -> None:
    """
    Reanuda una sesion previa cargando su hilo al contexto.

      /resume                 -> ultima sesion del directorio actual
      /resume list            -> listar sesiones recientes
      /resume <id>            -> sesion por id (o prefijo de 8 chars)
      /resume <directorio>    -> ultima sesion que corrio en ese directorio
    """
    arg = args.strip()
    ch = getattr(ai, "chat_history", None)
    if ch is None:
        _print_line("[err_cl]Historial no disponible.[/err_cl]")
        return

    if arg in ("list", "lista", "-l", "--list", "?"):
        sessions = ch.list_sessions(limit=12)
        if not sessions:
            _print_line("[detail]No hay sesiones registradas todavia. "
                        "(Se registran al iniciar el CLI.)[/detail]")
            return
        lines = ["Sesiones recientes (reanuda con /resume <id> o /resume <directorio>):"]
        for s in sessions:
            sid_short = (s["session_id"] or "?")[:8]
            lines.append(f"  [{sid_short}] {_fmt_ts(s['last_ts'])}  "
                         f"{s['count']:>3} msgs  {s['cwd'] or '?'}")
        _show_response("\n".join(lines), "cyan")
        return

    target_sid = None
    scope = ""
    if not arg or arg in ("here", "aqui", "."):
        cwd = _SESSION_CWD or os.path.normpath(os.path.abspath(os.getcwd()))
        target_sid = ch.latest_session_for_dir(cwd)
        scope = f"directorio actual ({cwd})"
    else:
        expanded = os.path.normpath(os.path.abspath(os.path.expanduser(arg)))
        looks_like_path = (
            os.path.isdir(expanded)
            or os.sep in arg
            or (os.altsep and os.altsep in arg)
            or arg.startswith("~")
            or arg.startswith(".")
        )
        if looks_like_path:
            target_sid = ch.latest_session_for_dir(expanded)
            scope = f"directorio {expanded}"
        else:
            target_sid = ch.resolve_session_prefix(arg)
            scope = f"sesion {arg}"
            if target_sid is None:
                alt = ch.latest_session_for_dir(expanded)
                if alt:
                    target_sid, scope = alt, f"directorio {expanded}"

    if not target_sid:
        _print_line(
            f"[warn_cl]No encontre una sesion para {_escape(scope)}. "
            "Proba: /resume list[/warn_cl]"
        )
        return

    if target_sid == _SESSION_ID:
        _print_line("[detail]Esa es la sesion actual; ya estas en ella.[/detail]")
        return

    turns = ch.get_session_turns(target_sid, limit=_HISTORY_SEED_N)
    if not turns:
        _print_line(
            f"[warn_cl]La sesion {target_sid[:8]} no tiene mensajes de dialogo.[/warn_cl]"
        )
        return

    _history[:] = turns
    _print_line(
        f"[ok_cl]Reanudada sesion {target_sid[:8]} ({_escape(scope)}): "
        f"{len(turns)} mensajes cargados al contexto.[/ok_cl]"
    )
    last_user = next((t["content"] for t in reversed(turns) if t["role"] == "user"), "")
    if last_user:
        _print_line(f"[detail]Ultimo tema: {_escape(last_user[:80])}[/detail]")


def _slash_buscar_historial(args: str) -> None:
    """Busca mensajes en el historial por keyword."""
    keyword = args.strip()
    if not keyword:
        _print_line("[warn_cl]Uso: /buscar-historial <keyword>[/warn_cl]")
        return
    try:
        from cognia.config import DB_PATH
        from storage.db_pool import db_connect_pooled as _dcp
    except ImportError as _ie:
        _print_line(f"[err_cl]db_pool no disponible: {_ie}[/err_cl]")
        return
    try:
        conn = _dcp(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            "SELECT session_id, role, content, timestamp FROM chat_history"
            " WHERE content LIKE ? ORDER BY id DESC LIMIT 20",
            (f"%{keyword}%",),
        )
        rows = cur.fetchall()
        conn.close()
        if not rows:
            _print_line(f"[detail](Sin resultados para '{keyword}')[/detail]")
            return
        lines = [f"Resultados para '{keyword}':"]
        for sid, role, content, ts in rows:
            fecha = _fmt_ts(ts)
            sid_short = str(sid)[:8] if sid else "?"
            preview = content[:80].replace("\n", " ")
            lines.append(f"  [{sid_short}] {fecha} ({role}): {preview}")
        _show_response("\n".join(lines), "cyan")
    except Exception as _e:
        _print_line(f"[err_cl]buscar-historial error: {_e}[/err_cl]")


def _slash_sesion_ver(args: str) -> None:
    """Muestra los ultimos mensajes de una sesion dado su ID (o primeros 8 chars)."""
    sid_arg = args.strip()
    if not sid_arg:
        _print_line("[warn_cl]Uso: /sesion-ver <session_id>[/warn_cl]")
        return
    try:
        from cognia.config import DB_PATH
        from storage.db_pool import db_connect_pooled as _dcp
    except ImportError as _ie:
        _print_line(f"[err_cl]db_pool no disponible: {_ie}[/err_cl]")
        return
    try:
        conn = _dcp(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            "SELECT role, content, timestamp FROM chat_history"
            " WHERE session_id LIKE ? ORDER BY id LIMIT 20",
            (f"{sid_arg}%",),
        )
        rows = cur.fetchall()
        conn.close()
        if not rows:
            _print_line(f"[detail]Sin mensajes para sesion '{sid_arg}'.[/detail]")
            return
        lines = [f"Sesion {sid_arg[:8]}:"]
        for role, content, _ts in rows:
            label = "User" if role == "user" else "Cognia"
            preview = content[:100].replace("\n", " ")
            lines.append(f"  [{label}]: {preview}")
        _show_response("\n".join(lines), "cyan")
    except Exception as _e:
        _print_line(f"[err_cl]sesion-ver error: {_e}[/err_cl]")


def _slash_historial_limpiar(args: str) -> None:
    """Elimina historial de una sesion o todo el historial."""
    arg = args.strip()
    try:
        from cognia.config import DB_PATH
        from storage.db_pool import db_connect_pooled as _dcp
    except ImportError as _ie:
        _print_line(f"[err_cl]db_pool no disponible: {_ie}[/err_cl]")
        return
    if not arg:
        _print_line(
            "[warn_cl]AVISO: esto borrara TODO el historial de chat.\n"
            "Para confirmar: /historial-limpiar confirmar\n"
            "Para borrar una sesion: /historial-limpiar <session_id>[/warn_cl]"
        )
        return
    try:
        conn = _dcp(DB_PATH)
        if arg == "confirmar":
            cur = conn.cursor()
            cur.execute("DELETE FROM chat_history")
            deleted = cur.rowcount
            conn.commit()
            conn.close()
            _print_line(f"[ok]Historial completo eliminado: {deleted} mensajes borrados.[/ok]")
        else:
            cur = conn.cursor()
            cur.execute("DELETE FROM chat_history WHERE session_id = ?", (arg,))
            deleted = cur.rowcount
            conn.commit()
            conn.close()
            if deleted:
                _print_line(f"[ok]Sesion '{arg}': {deleted} mensajes eliminados.[/ok]")
            else:
                _print_line(f"[warn_cl]No se encontro sesion '{arg}' en el historial.[/warn_cl]")
    except Exception as _e:
        _print_line(f"[err_cl]historial-limpiar error: {_e}[/err_cl]")


# ---------------------------------------------------------------------------
# REPL
# ---------------------------------------------------------------------------

def _slash_notas(args: str) -> None:
    type_map = {"hechos": "fact", "decisiones": "decision", "acciones": "action",
                "insights": "insight", "preguntas": "question"}
    note_type = type_map.get(args.strip().lower(), "")
    try:
        import requests
        params = {"limit": 20}
        if note_type:
            params["note_type"] = note_type
        resp = requests.get("http://localhost:8765/notes", params=params, timeout=2)
        if resp.status_code == 200:
            data = resp.json()
            notes = data.get("notes", data if isinstance(data, list) else [])
            if not notes:
                print("No hay notas.")
                return
            for n in notes:
                pin = "[*]" if n.get("pinned") else "   "
                print(f"{pin} [{n.get('note_type','?')}] {n.get('content','')[:100]}")
        else:
            print(f"Error: {resp.status_code}")
    except Exception:
        print("Servicio de notas no disponible.")


def _slash_nota_agregar(args: str) -> None:
    if not args.strip():
        print("Uso: /nota-agregar <contenido>")
        return
    try:
        import requests
        resp = requests.post(
            "http://localhost:8765/notes",
            json={"content": args.strip(), "note_type": "fact", "session_id": "cli", "source": "manual"},
            timeout=2,
        )
        if resp.status_code in (200, 201):
            data = resp.json()
            note_id = data.get("id", data.get("note_id", "?"))
            print(f"Nota guardada (id: {note_id}).")
        else:
            print(f"Error: {resp.status_code}")
    except Exception:
        print("Servicio de notas no disponible.")


def _slash_notas_buscar(args: str) -> None:
    if not args.strip():
        print("Uso: /notas-buscar <query>")
        return
    try:
        import requests
        resp = requests.get("http://localhost:8765/notes/search", params={"q": args.strip()}, timeout=2)
        if resp.status_code == 200:
            data = resp.json()
            notes = data.get("notes", data if isinstance(data, list) else [])
            if not notes:
                print("Sin resultados.")
                return
            for n in notes:
                pin = "[*]" if n.get("pinned") else "   "
                print(f"{pin} [{n.get('note_type','?')}] {n.get('content','')[:100]}")
        else:
            print(f"Error: {resp.status_code}")
    except Exception:
        print("Servicio de notas no disponible.")


def _slash_notas_stats() -> None:
    try:
        import requests
        resp = requests.get("http://localhost:8765/notes/stats", timeout=2)
        if resp.status_code == 200:
            s = resp.json()
            total    = s.get("total", 0)
            facts    = s.get("facts", s.get("fact", 0))
            decisions = s.get("decisions", s.get("decision", 0))
            actions  = s.get("actions", s.get("action", 0))
            insights = s.get("insights", s.get("insight", 0))
            questions = s.get("questions", s.get("question", 0))
            pinned   = s.get("pinned", 0)
            print(
                f"Notas: {total} total | {facts} facts | {decisions} decisions | "
                f"{actions} actions | {insights} insights | {questions} questions | {pinned} pinned"
            )
        else:
            print(f"Error: {resp.status_code}")
    except Exception:
        print("Servicio de notas no disponible.")


def _slash_nota_fijar(args: str) -> None:
    if not args.strip():
        print("Uso: /nota-fijar <id>")
        return
    try:
        import requests
        note_id = args.strip()
        resp = requests.post(f"http://localhost:8765/notes/{note_id}/pin", timeout=2)
        if resp.status_code in (200, 201):
            print(f"Nota {note_id} fijada.")
        else:
            print(f"Error: {resp.status_code}")
    except Exception:
        print("Servicio de notas no disponible.")


def _slash_revisar_sm2() -> None:
    try:
        import requests
        resp = requests.get("http://localhost:8765/learning/due", timeout=2)
        if resp.status_code != 200:
            print(f"Error: {resp.status_code}")
            return
        cards = resp.json().get("cards", resp.json() if isinstance(resp.json(), list) else [])
        if not cards:
            print("No hay tarjetas para revisar hoy. Buen trabajo!")
            return
        print(f"{len(cards)} tarjeta(s) para revisar.")
        for card in cards[:5]:
            print(f"\n[{card.get('topic','?')}] {card.get('front','')}")
            input("  Presiona Enter para ver la respuesta...")
            print(f"  -> {card.get('back','')}")
            rating = input("  Calificacion (0-5, 0=olvide, 5=perfecto): ").strip()
            try:
                quality = max(0, min(5, int(rating)))
            except ValueError:
                quality = 3
            r2 = requests.post(f"http://localhost:8765/learning/cards/{card['id']}/review",
                               json={"quality": quality}, timeout=2)
            if r2.status_code == 200:
                updated = r2.json()
                days = round(updated.get("interval_days", 1), 1)
                print(f"  Proxima revision en {days} dia(s).")
    except Exception as e:
        print(f"Servicio de aprendizaje no disponible. {e}")


def _slash_aprender_card(args: str) -> None:
    parts = [p.strip() for p in args.split("|")]
    if len(parts) < 2:
        print("Uso: /aprender <frente> | <respuesta> [| <tema>]")
        return
    payload = {"front": parts[0], "back": parts[1]}
    if len(parts) >= 3 and parts[2]:
        payload["topic"] = parts[2]
    try:
        import requests
        resp = requests.post("http://localhost:8765/learning/cards", json=payload, timeout=2)
        if resp.status_code in (200, 201):
            card_id = resp.json().get("id", "?")
            print(f"Tarjeta guardada (id: {card_id}).")
        else:
            print(f"Error: {resp.status_code}")
    except Exception as e:
        print(f"Servicio de aprendizaje no disponible. {e}")


def _slash_aprendiendo() -> None:
    try:
        import requests
        resp = requests.get("http://localhost:8765/learning/stats", timeout=2)
        if resp.status_code == 200:
            s = resp.json()
            topics = s.get("topics", [])
            topics_str = ", ".join(topics) if topics else "-"
            print(
                f"Aprendizaje:\n"
                f"  Total tarjetas : {s.get('total', 0)}\n"
                f"  Para revisar   : {s.get('due', 0)}\n"
                f"  Dominadas      : {s.get('mastered', 0)}\n"
                f"  Temas          : {topics_str}"
            )
        else:
            print(f"Error: {resp.status_code}")
    except Exception as e:
        print(f"Servicio de aprendizaje no disponible. {e}")


def _slash_aprendiendo_buscar(args: str) -> None:
    if not args.strip():
        print("Uso: /aprendiendo-buscar <query>")
        return
    query = args.strip().lower()
    try:
        import requests
        resp = requests.get("http://localhost:8765/learning/cards", params={"q": query}, timeout=2)
        if resp.status_code != 200:
            print(f"Error: {resp.status_code}")
            return
        data = resp.json()
        cards = data.get("cards", data if isinstance(data, list) else [])
        matches = [
            c for c in cards
            if query in c.get("front", "").lower()
            or query in c.get("back", "").lower()
            or query in c.get("topic", "").lower()
        ]
        if not matches:
            print("Sin resultados.")
            return
        for c in matches[:20]:
            print(f"[{c.get('topic','?')}] {c.get('front','')} -> {c.get('back','')[:60]}")
    except Exception as e:
        print(f"Servicio de aprendizaje no disponible. {e}")


# ---------------------------------------------------------------------------
# Autocritica y Reflexion
# ---------------------------------------------------------------------------

def _slash_ver_criticas(args: str) -> None:
    try:
        import requests
        resp = requests.get("http://localhost:8765/critique/recent", timeout=3)
        if resp.status_code == 200:
            items = resp.json() if isinstance(resp.json(), list) else resp.json().get("critiques", [])
            if not items:
                print("Sin criticas registradas aun.")
                return
            print("Criticas recientes de respuestas:")
            for i, c in enumerate(items, 1):
                score = round(c.get("overall_score", 0), 2)
                critique = c.get("critique", "")
                print(f"  {i}. [score={score}] {critique}")
            r2 = requests.get("http://localhost:8765/critique/score", timeout=2)
            if r2.status_code == 200:
                d = r2.json()
                print(f"\n  Promedio 7d: {round(d.get('avg_score_7d',0), 2)} | Tendencia: {d.get('trend','?')}")
        else:
            print(f"Error: {resp.status_code}")
    except Exception:
        print("Servicio de criticas no disponible.")


def _slash_reflexion_profunda(args: str) -> None:
    if not args.strip():
        print("Uso: /reflexion-profunda <pregunta o tema>")
        return
    tema = args.strip()
    lenses = [
        ("Analitico",  f"Descompon '{tema}' en sus partes: causas, componentes, mecanismos."),
        ("Critico",    f"Cuales son las debilidades o limitaciones de '{tema}'?"),
        ("Creativo",   f"Que alternativas o enfoques no convencionales existen para '{tema}'?"),
        ("Sistemico",  f"Como interactua '{tema}' con sistemas mas amplios?"),
        ("Pragmatico", f"Cuales son los pasos accionables concretos relacionados con '{tema}'?"),
    ]
    print(f"Reflexion profunda: '{tema}'")
    print()
    for name, prompt in lenses:
        print(f"[{name}]")
        print(f"  Perspectiva: {prompt}")
        print()
    print("Usa estas perspectivas para guiar una conversacion mas profunda con Cognia.")


def _slash_calidad_respuestas(args: str) -> None:
    try:
        import requests
        resp = requests.get("http://localhost:8765/critique/score", timeout=3)
        if resp.status_code == 200:
            d = resp.json()
            score = round(d.get("avg_score_7d", 0), 3)
            trend = d.get("trend", "sin datos")
            print(f"Calidad de respuestas (7 dias):")
            print(f"  Puntuacion promedio : {score}/1.0")
            print(f"  Tendencia           : {trend}")
            bar = "#" * int(score * 20)
            print(f"  [{bar:<20}]")
        else:
            print(f"Error: {resp.status_code}")
    except Exception:
        print("Servicio de calidad no disponible.")


def _slash_features(args: str) -> None:
    try:
        import requests
        resp = requests.get("http://localhost:8765/features", timeout=3)
        if resp.status_code == 200:
            data = resp.json()
            flags = data.get("flags", data if isinstance(data, list) else [])
            if not flags:
                print("No hay feature flags configurados.")
                return
            print("Feature flags disponibles:")
            print(f"  {'Nombre':30} {'Estado':8} {'Tier minimo':12} Descripcion")
            print("  " + "-" * 70)
            for f in flags:
                status = "ON " if f.get("enabled_default", 0) else "OFF"
                name = f.get("name", "?")[:30]
                tier = str(f.get("min_tier", "?"))
                desc = f.get("description", "")[:30]
                print(f"  {name:30} {status:8} {tier:12} {desc}")
        else:
            print(f"Error: {resp.status_code}")
    except Exception:
        print("Servicio de features no disponible.")


def _slash_vocabulario(args: str) -> None:
    if not _history:
        print("No hay historial en esta sesion.")
        return
    assistant_msgs = [h["content"] for h in _history if h.get("role") == "assistant"]
    if not assistant_msgs:
        print("Sin mensajes de asistente aun.")
        return
    stop = {"python", "sobre", "desde", "hasta", "cuando", "donde", "tambien", "puede", "todos",
            "seria", "tienen", "hacer", "entre", "after", "before", "return", "import", "class"}
    word_set = set()
    for msg in assistant_msgs:
        words = re.findall(r'[a-zA-Z]{7,}', msg.lower())
        for w in words:
            if w not in stop:
                word_set.add(w)
    vocab = sorted(word_set)[:30]
    if not vocab:
        print("Sin vocabulario tecnico identificado.")
        return
    print(f"Vocabulario tecnico de esta sesion ({len(vocab)} terminos):")
    for i in range(0, len(vocab), 3):
        row = vocab[i:i + 3]
        print("  " + "  ".join(f"{w:25}" for w in row))


def _slash_vocabulario_guardar(args: str) -> None:
    if not _history:
        print("No hay historial.")
        return
    assistant_msgs = [h["content"] for h in _history if h.get("role") == "assistant"]
    stop = {"python", "sobre", "desde", "hasta", "cuando", "donde", "tambien", "puede", "todos",
            "seria", "tienen", "hacer", "entre", "after", "before", "return", "import", "class"}
    word_set = set()
    for msg in assistant_msgs:
        for w in re.findall(r'[a-zA-Z]{7,}', msg.lower()):
            if w not in stop:
                word_set.add(w)
    if not word_set:
        print("Sin vocabulario para guardar.")
        return
    try:
        import requests
        saved = 0
        for word in list(word_set)[:10]:
            r = requests.post(
                "http://localhost:8765/kg",
                json={"subject": "vocabulario_sesion", "predicate": "incluye", "object": word},
                timeout=2,
            )
            if r.status_code in (200, 201):
                saved += 1
        print(f"Guardadas {saved} palabra(s) en el grafo de conocimiento.")
    except Exception:
        print("Error al guardar vocabulario en KG.")


def _slash_hechos_solidos(args: str) -> None:
    try:
        import requests
        resp = requests.get("http://localhost:8765/knowledge/crystallized", timeout=3)
        if resp.status_code == 200:
            facts = resp.json() if isinstance(resp.json(), list) else resp.json().get("facts", [])
            if not facts:
                print("No hay hechos cristalizados aun. Usa /cristalizar para procesar el KG.")
                return
            print(f"Hechos de alta confianza ({len(facts)}):")
            for f in facts:
                s = f.get("subject", "?")
                p = f.get("predicate", "?")
                o = f.get("object", "?")
                w = round(f.get("weight", 0), 2)
                print(f"  [{w}] {s} {p} {o}")
        else:
            print(f"Error: {resp.status_code}")
    except Exception:
        print("Servicio de conocimiento no disponible.")


def _slash_cristalizar(args: str) -> None:
    try:
        import requests
        resp = requests.post("http://localhost:8765/knowledge/crystallize", timeout=10)
        if resp.status_code == 200:
            n = resp.json().get("crystallized", 0)
            print(f"Cristalizacion completada: {n} hecho(s) promovido(s) a alta confianza.")
            r2 = requests.get("http://localhost:8765/knowledge/crystal-stats", timeout=3)
            if r2.status_code == 200:
                s = r2.json()
                rate = round(s.get("crystallization_rate", 0) * 100, 1)
                print(f"  Total KG: {s.get('total_facts', 0)} | Cristalizados: {s.get('crystallized', 0)} ({rate}%)")
        else:
            print(f"Error: {resp.status_code}")
    except Exception:
        print("Servicio de cristalizacion no disponible.")


def _slash_conocimiento_ver(args: str) -> None:
    if not args.strip():
        print("Uso: /conocimiento-ver <topico>")
        return
    topic = args.strip()
    try:
        import requests
        import urllib.parse
        q = urllib.parse.quote(topic)
        resp = requests.get(f"http://localhost:8765/kg/facts?subject={q}", timeout=3)
        facts = []
        if resp.status_code == 200:
            data = resp.json()
            facts = data if isinstance(data, list) else data.get("facts", [])
        resp2 = requests.get(f"http://localhost:8765/synthesis?q={q}", timeout=5)
        synthesis = ""
        if resp2.status_code == 200:
            synthesis = resp2.json().get("synthesis", "")
        print(f"Conocimiento sobre '{topic}':")
        print()
        if facts:
            print(f"  Hechos en KG ({len(facts)}):")
            for f in facts[:10]:
                if isinstance(f, dict):
                    print(f"    - {f.get('predicate', '?')}: {f.get('object', '?')}")
        else:
            print("  Sin hechos en KG. Usa /kg-agregar para agregar.")
        if synthesis:
            print()
            print("  Sintesis:")
            for line in synthesis.split("\n")[:10]:
                if line.strip():
                    print(f"  {line}")
    except Exception:
        print("Servicio no disponible.")


def _slash_quiz(args: str) -> None:
    try:
        import requests
        topic = args.strip() if args.strip() else None
        url = "http://localhost:8765/quiz/generate?limit=5"
        if topic:
            import urllib.parse
            url += f"&topic={urllib.parse.quote(topic)}"
        resp = requests.get(url, timeout=5)
        if resp.status_code != 200:
            print(f"Error: {resp.status_code}")
            return
        questions = resp.json().get("questions", [])
        if not questions:
            print("No hay preguntas disponibles. Agrega hechos con /kg-agregar o tarjetas con /aprender.")
            return
        print(f"Quiz: {len(questions)} pregunta(s). Responde lo mejor que puedas.")
        correct = 0
        for i, q in enumerate(questions, 1):
            print(f"\n{i}/{len(questions)}: {q.get('question','')}")
            user_ans = input("  Tu respuesta: ").strip()
            expected = q.get("answer", "")
            r = requests.post("http://localhost:8765/quiz/answer", timeout=3,
                json={"question": q["question"], "answer": expected, "user_answer": user_ans, "source": q.get("source","quiz")})
            is_correct = r.json().get("correct", False) if r.status_code == 200 else (user_ans.lower() == expected.lower())
            if is_correct:
                correct += 1
                print(f"  Correcto!")
            else:
                print(f"  Incorrecto. Respuesta: {expected}")
        print(f"\nResultado: {correct}/{len(questions)} ({round(correct/len(questions)*100)}%)")
    except Exception as e:
        print(f"Servicio de quiz no disponible. {e}")


def _slash_quiz_stats(args: str) -> None:
    try:
        import requests
        resp = requests.get("http://localhost:8765/quiz/stats", timeout=3)
        if resp.status_code == 200:
            s = resp.json()
            acc = round(s.get("accuracy", 0)*100, 1)
            print(f"Estadisticas de quiz:")
            print(f"  Intentos totales : {s.get('total_attempts', 0)}")
            print(f"  Correctas        : {s.get('correct', 0)}")
            print(f"  Precision        : {acc}%")
            by_source = s.get("by_source", {})
            for src, data in by_source.items():
                if data.get("total", 0) > 0:
                    src_acc = round(data.get("correct",0)/data["total"]*100, 1)
                    print(f"  [{src}]: {data.get('correct',0)}/{data['total']} ({src_acc}%)")
        else:
            print(f"Error: {resp.status_code}")
    except Exception:
        print("Servicio de quiz no disponible.")


def _slash_exportar_todo(args: str) -> None:
    import datetime
    from pathlib import Path
    dest_dir = Path(args.strip()) if args.strip() else Path.home() / ".cognia_exports"
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    exported = []

    try:
        import requests

        r = requests.get("http://localhost:8765/export/history?format=json", timeout=5)
        if r.status_code == 200:
            p = dest_dir / f"historial_{stamp}.json"
            p.write_text(r.text, encoding="utf-8")
            exported.append(str(p.name))

        r = requests.get("http://localhost:8765/notes?limit=1000", timeout=5)
        if r.status_code == 200:
            p = dest_dir / f"notas_{stamp}.json"
            p.write_text(r.text, encoding="utf-8")
            exported.append(str(p.name))

        r = requests.get("http://localhost:8765/goals", timeout=5)
        if r.status_code == 200:
            p = dest_dir / f"objetivos_{stamp}.json"
            p.write_text(r.text, encoding="utf-8")
            exported.append(str(p.name))

        r = requests.get("http://localhost:8765/reports/generate?period=30", timeout=10)
        if r.status_code == 200:
            report = r.json().get("report", "")
            p = dest_dir / f"reporte_{stamp}.md"
            p.write_text(report, encoding="utf-8")
            exported.append(str(p.name))
    except Exception as e:
        print(f"Advertencia: algunos servicios no disponibles ({e})")

    if exported:
        print(f"Exportacion completa en {dest_dir}:")
        for f in exported:
            print(f"  - {f}")
    else:
        print("No se pudo exportar ningun dato. Inicia cognia_desktop_api.py.")


def _slash_camino_nuevo(args: str) -> None:
    if not args.strip():
        print("Uso: /camino-nuevo <objetivo de aprendizaje>")
        return
    try:
        import requests
        resp = requests.post("http://localhost:8765/learning/paths",
                           json={"goal": args.strip()}, timeout=5)
        if resp.status_code in (200, 201):
            path = resp.json()
            steps = path.get("steps", [])
            print(f"Camino creado (id: {path.get('id','?')}) para: {path.get('goal','')}")
            print(f"Pasos ({len(steps)}):")
            for s in steps:
                status = "[X]" if s.get("completed") else "[ ]"
                print(f"  {status} {s.get('number','?')}. {s.get('title','')}")
        else:
            print(f"Error: {resp.status_code}")
    except Exception:
        print("Servicio de caminos de aprendizaje no disponible.")


def _slash_caminos(args: str) -> None:
    try:
        import requests
        resp = requests.get("http://localhost:8765/learning/paths", timeout=3)
        if resp.status_code == 200:
            paths = resp.json() if isinstance(resp.json(), list) else resp.json().get("paths", [])
            if not paths:
                print("No hay caminos de aprendizaje activos. Usa /camino-nuevo <objetivo>.")
                return
            print(f"Caminos activos ({len(paths)}):")
            for p in paths:
                steps = p.get("steps", [])
                current = p.get("current_step", 0)
                total = len(steps)
                pct = round(current/total*100) if total > 0 else 0
                bar = "#" * (pct // 10) + "." * (10 - pct // 10)
                print(f"  [id:{p.get('id','?')}] {p.get('goal','?')}")
                print(f"    [{bar}] {pct}% (paso {current}/{total})")
        else:
            print(f"Error: {resp.status_code}")
    except Exception:
        print("Servicio no disponible.")


def _slash_camino_avanzar(args: str) -> None:
    if not args.strip().isdigit():
        print("Uso: /camino-avanzar <id>")
        return
    try:
        import requests
        path_id = int(args.strip())
        resp = requests.post(f"http://localhost:8765/learning/paths/{path_id}/advance", timeout=3)
        if resp.status_code == 200:
            p = resp.json()
            steps = p.get("steps", [])
            current = p.get("current_step", 0)
            if p.get("completed"):
                print(f"Camino completado! Felicitaciones.")
            else:
                next_step = steps[current] if current < len(steps) else None
                if next_step:
                    print(f"Paso completado. Proximo paso: {next_step.get('title','')}")
                else:
                    print(f"Avanzado. Paso actual: {current}/{len(steps)}")
        else:
            print(f"Error: {resp.status_code}")
    except Exception:
        print("Servicio no disponible.")


def _slash_etiquetar(args: str) -> None:
    if not args.strip():
        print("Uso: /etiquetar <texto a etiquetar>")
        return
    import re
    text = args.strip().lower()
    domain_keywords = {
        "programacion": ["python","codigo","funcion","variable","clase","metodo","algoritmo","debug"],
        "datos": ["dataset","dataframe","sql","query","tabla","columna","base de datos"],
        "matematica": ["ecuacion","calculo","integral","derivada","algebra","estadistica"],
        "ia": ["modelo","entrenamiento","inferencia","neural","embedding","tensor","gpu"],
        "web": ["html","css","javascript","api","endpoint","frontend","backend","http"],
        "gestion": ["objetivo","meta","tarea","proyecto","deadline","sprint","equipo"],
        "aprendizaje": ["estudiar","leer","practicar","revisar","memorizar","comprender"],
    }
    tags = []
    words = set(re.findall(r'\w+', text))
    for domain, keywords in domain_keywords.items():
        if any(kw in words or kw in text for kw in keywords):
            tags.append(domain)
    if not tags:
        tags = ["general"]
    print(f"Etiquetas detectadas: {', '.join(tags)}")


def _slash_cognia_sabe(args: str) -> None:
    try:
        import requests
        resp = requests.get("http://localhost:8765/user/facts", timeout=3)
        if resp.status_code == 200:
            facts = resp.json() if isinstance(resp.json(), list) else resp.json().get("facts", [])
            if not facts:
                print("Cognia aun no tiene hechos sobre ti. Usa /cognia-aprende para agregar.")
                return
            print(f"Lo que Cognia sabe de ti ({len(facts)} hechos):")
            for f in facts:
                src = f.get("source", "?")
                conf = round(f.get("confidence", 1) * 100)
                print(f"  [id:{f.get('id', '?')}] ({src}, {conf}% confianza) {f.get('fact', '')}")
        else:
            print(f"Error: {resp.status_code}")
    except Exception:
        print("Servicio no disponible.")


def _slash_cognia_aprende(args: str) -> None:
    if not args.strip():
        print("Uso: /cognia-aprende <hecho sobre ti>")
        print("Ejemplo: /cognia-aprende Soy desarrollador de Python con 3 anios de experiencia")
        return
    try:
        import requests
        resp = requests.post("http://localhost:8765/user/facts",
                             json={"fact": args.strip(), "confidence": 1.0}, timeout=3)
        if resp.status_code in (200, 201):
            print(f"Hecho aprendido: '{args.strip()}'")
        else:
            print(f"Error: {resp.status_code}")
    except Exception:
        print("Servicio no disponible.")


def _slash_cognia_olvida(args: str) -> None:
    if not args.strip().isdigit():
        print("Uso: /cognia-olvida <id>  (usa /cognia-sabe para ver los ids)")
        return
    try:
        import requests
        fact_id = int(args.strip())
        resp = requests.delete(f"http://localhost:8765/user/facts/{fact_id}", timeout=3)
        if resp.status_code == 200:
            print(f"Hecho {fact_id} olvidado.")
        elif resp.status_code == 404:
            print(f"Hecho {fact_id} no encontrado.")
        else:
            print(f"Error: {resp.status_code}")
    except Exception:
        print("Servicio no disponible.")


def _slash_argumento(args: str) -> None:
    if not args.strip():
        print("Uso: /argumento <tesis o posicion>")
        return
    tesis = args.strip()
    print(f"Analisis argumentativo: '{tesis}'")
    print()
    print("TESIS:")
    print(f"  Posicion: {tesis}")
    print(f"  Supuesto: Se afirma que '{tesis}' es verdadero/beneficioso.")
    print()
    print("ANTITESIS:")
    print(f"  La posicion opuesta cuestionaria: es '{tesis}' siempre aplicable?")
    print(f"  Excepciones posibles: contextos donde '{tesis}' no se sostiene.")
    print()
    print("SINTESIS:")
    print(f"  '{tesis}' puede ser valido bajo condiciones especificas.")
    print(f"  Una posicion equilibrada considera tanto ventajas como limitaciones.")
    print()
    print("Sugerencia: combina con /debate, /y-si o /buscar-web para profundizar.")


def _slash_conflictos_kg(args: str) -> None:
    try:
        import requests
        resp = requests.get("http://localhost:8765/knowledge/conflicts", timeout=3)
        if resp.status_code == 200:
            conflicts = resp.json() if isinstance(resp.json(), list) else resp.json().get("conflicts", [])
            if not conflicts:
                print("Sin conflictos detectados en el grafo de conocimiento.")
                return
            print(f"Conflictos en KG ({len(conflicts)}):")
            for c in conflicts:
                print(f"  [id:{c.get('id','?')}] {c.get('subject','?')} / {c.get('predicate','?')}")
                print(f"    A: {c.get('fact_a','?')}")
                print(f"    B: {c.get('fact_b','?')}")
        else:
            print(f"Error: {resp.status_code}")
    except Exception:
        print("Servicio no disponible.")


def _slash_verificar_kg(args: str) -> None:
    try:
        import requests
        resp = requests.post("http://localhost:8765/knowledge/conflicts/check", timeout=10)
        if resp.status_code == 200:
            n = resp.json().get("new_conflicts", 0)
            print(f"Verificacion completada: {n} nuevo(s) conflicto(s) detectado(s).")
            if n > 0:
                print("  Usa /conflictos-kg para verlos.")
        else:
            print(f"Error: {resp.status_code}")
    except Exception:
        print("Servicio no disponible.")


def _slash_resolver_conflicto(args: str) -> None:
    if not args.strip().isdigit():
        print("Uso: /resolver-conflicto <id>")
        return
    try:
        import requests
        resp = requests.post(f"http://localhost:8765/knowledge/conflicts/{args.strip()}/resolve", timeout=3)
        if resp.status_code == 200:
            print(f"Conflicto {args.strip()} marcado como resuelto.")
        else:
            print(f"Error: {resp.status_code}")
    except Exception:
        print("Servicio no disponible.")


def _slash_comandos(args: str) -> None:
    total = len(_CMD_DESCRIPTIONS)
    cats = {}
    for cmd in _CMD_DESCRIPTIONS:
        parts = cmd.lstrip("/").split("-")
        root = parts[0]
        cats[root] = cats.get(root, 0) + 1
    top_cats = sorted(cats.items(), key=lambda x: -x[1])[:10]
    print(f"Comandos disponibles: {total} total")
    print("Categorias principales:")
    for cat, count in top_cats:
        print(f"  /{cat}*   ({count} comandos)")
    print()
    print("Usa /help para ver todos los comandos agrupados.")
    print("Usa /ayuda <comando> para ayuda detallada de un comando.")


def _slash_ver_contexto(args: str) -> None:
    if not args.strip():
        print("Uso: /ver-contexto <pregunta>")
        print("Muestra que contexto inyectaria Cognia en el system prompt para esa pregunta.")
        return
    query = args.strip().lower()
    print(f"Contexto que se inyectaria para: '{args.strip()}'")
    print()

    sources = []
    try:
        import requests

        r = requests.get("http://localhost:8765/user/facts", timeout=2)
        if r.status_code == 200:
            facts = r.json() if isinstance(r.json(), list) else r.json().get("facts", [])
            if facts:
                sources.append(("Hechos personales", f"{len(facts)} hechos sobre ti"))

        r = requests.get("http://localhost:8765/knowledge/crystallized", timeout=2)
        if r.status_code == 200:
            kfacts = r.json() if isinstance(r.json(), list) else r.json().get("facts", [])
            if kfacts:
                sources.append(("KG cristalizado", f"{len(kfacts)} hechos de alta confianza"))

        r = requests.get("http://localhost:8765/goals?status=pending", timeout=2)
        if r.status_code == 200:
            goals = r.json() if isinstance(r.json(), list) else r.json().get("goals", [])
            if goals:
                sources.append(("Objetivos activos", f"{len(goals)} objetivos pendientes"))

        r = requests.get("http://localhost:8765/recommendations/top", timeout=2)
        if r.status_code == 200:
            rec = r.json().get("recommendation")
            if rec:
                sources.append(("Recomendacion", rec.get("title", "")))
    except Exception:
        sources.append(("API", "no disponible -- contexto reducido"))

    if sources:
        print("Fuentes de contexto disponibles:")
        for name, detail in sources:
            print(f"  [{name}] {detail}")
        print()
        print(f"Total: {len(sources)} fuente(s) -- prioridad automatica limita a 4 bloques / 800 chars")
    else:
        print("Sin contexto adicional disponible.")


def _slash_resumen_sesion_full(args: str) -> None:
    elapsed = int((time.time() - _session_start) / 60) if _session_start else 0
    user_msgs = [h for h in _history if h.get("role") == "user"]
    asst_msgs = [h for h in _history if h.get("role") == "assistant"]

    print("Resumen de sesion:")
    print(f"  Duracion         : {elapsed} minutos")
    print(f"  Mensajes usuario : {len(user_msgs)}")
    print(f"  Respuestas       : {len(asst_msgs)}")

    cmd_count = sum(1 for h in user_msgs if h.get("content", "").startswith("/"))
    print(f"  Comandos usados  : {cmd_count}")

    pos = sum(1 for f in _session_feedback if f.get("signal") == "positive")
    neg = sum(1 for f in _session_feedback if f.get("signal") == "negative")
    if _session_feedback:
        print(f"  Feedback         : {pos} positivos, {neg} negativos")

    import re as _re_wf
    stop = {"para", "como", "esta", "este", "que", "una", "los", "las", "por", "con"}
    wf = {}
    for h in user_msgs:
        for w in _re_wf.findall(r'\w+', h.get("content", "").lower()):
            if len(w) > 4 and w not in stop:
                wf[w] = wf.get(w, 0) + 1
    top = sorted(wf.items(), key=lambda x: -x[1])[:5]
    if top:
        print(f"  Temas frecuentes : {', '.join(w for w, _ in top)}")


def _slash_limpiar_sesion(args: str) -> None:
    global _history, _session_feedback
    n_history = len(_history)
    n_feedback = len(_session_feedback)
    _history = []
    _session_feedback = []
    print(f"Sesion limpiada: {n_history} mensajes y {n_feedback} feedback(s) eliminados.")
    print("Los datos persistentes (notas, metas, KG) no se han modificado.")


def _strip_input_bom(line: str) -> str:
    """Quita el BOM UTF-8 que aparece al inicio de la PRIMERA linea cuando
    stdin viene pipeado (p.ej. PowerShell antepone los bytes EF BB BF al
    stream). Segun el encoding de stdin el BOM llega como '\\ufeff' (utf-8)
    o como '\\xef\\xbb\\xbf' (cp1252). Sin esto, un '/comando' como primera
    linea no empieza con '/' y cae al chat en vez del dispatch (bug E2E)."""
    for _bom in ("\ufeff", "\xef\xbb\xbf"):
        if line.startswith(_bom):
            line = line[len(_bom):]
    return line.strip()


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

    # Register this run as a session, tagged with the directory it launched in,
    # so every persisted turn carries (session_id, cwd) and /resume can later
    # bring back a session by id or by directory.
    global _SESSION_ID, _SESSION_CWD
    try:
        import uuid as _uuid
        _SESSION_ID = _uuid.uuid4().hex[:12]
        _SESSION_CWD = os.path.normpath(os.path.abspath(os.getcwd()))
        ai.chat_history.set_session(_SESSION_ID, _SESSION_CWD)
        _init_lines.append(f"[OK] Sesion {_SESSION_ID[:8]} en {_SESSION_CWD}")
    except Exception:
        pass

    # Restore conversation continuity across restarts: seed the in-memory
    # _history (multi-turn prompt context) from persisted chat_history so the
    # model can follow a thread that started in a previous session.
    try:
        _restored = ai.chat_history.get_recent_turns(_HISTORY_SEED_N)
        if _restored:
            _history[:] = _restored
            _init_lines.append(
                f"[OK] Continuidad: {len(_restored)} mensajes de sesiones previas restaurados"
            )
    except Exception:
        pass

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
            # El BOM que PowerShell antepone al pipe rompe el dispatch de la
            # primera linea ('/comando' deja de empezar con '/'): sanear aca,
            # el UNICO punto de entrada al dispatch.
            raw = _strip_input_bom(_get_input())
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
        elif raw.startswith("/exportar-stats"):
            _slash_exportar_stats()
        elif raw.startswith("/exportar ") or raw == "/exportar":
            _exp_args = raw[len("/exportar"):].strip()
            if not _exp_args:
                print("Uso: /exportar <formato> [archivo]")
                print("Formatos: json, md, csv")
                print("Ejemplo: /exportar json historial.json")
            else:
                _slash_exportar(_exp_args)
        elif raw == "/costo":
            _slash_costo()
        elif raw in ("/stats", "/sesion-stats"):
            _slash_stats()
        elif raw == "/sugerir":
            _slash_sugerir()
        elif raw == "/logros" or raw.startswith("/logros "):
            _lg_args = raw[len("/logros "):].strip() if raw.startswith("/logros ") else ""
            _slash_logros(_lg_args)
        elif raw == "/patrones":
            _slash_patrones("")
        elif raw == "/debug":
            _slash_debug()
        elif raw == "/modo rapido":
            _slash_modo_rapido()
        elif raw == "/tema" or raw.startswith("/tema "):
            _slash_tema(raw[len("/tema "):] if raw.startswith("/tema ") else "")
        elif raw == "/color" or raw.startswith("/color "):
            _slash_color(raw[len("/color "):] if raw.startswith("/color ") else "")
        elif raw == "/memoria-limite" or raw.startswith("/memoria-limite "):
            _slash_memoria_limite(
                raw[len("/memoria-limite "):] if raw.startswith("/memoria-limite ") else "", ai)

        # -- System ---------------------------------------------------------
        elif raw == "/salir":
            print("Hasta luego.")
            break
        elif raw == "/doctor":
            # In-process so it works both from the repo and a pip-installed wheel
            # (scripts/ is not shipped in the package).
            try:
                from cognia.doctor import run_all as _doctor_run
                _doctor_run()
            except Exception as _de:
                _print_line(f"[err_cl]Error en /doctor: {_escape(str(_de))}[/err_cl]")
        elif raw == "/update":
            _scr = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "scripts", "cognia_update.py",
            )
            if os.path.isfile(_scr):
                import subprocess
                subprocess.run([sys.executable, _scr])
            else:
                _print_line("[detail]Instalado por pip -- actualiza con:  pip install -U cognia-ai[/detail]")
        elif raw in ("/distill", "/distill run"):
            _scr = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "scripts", "distill.py",
            )
            if os.path.isfile(_scr):
                import subprocess
                _dargs = [] if raw == "/distill run" else ["--dry-run"]
                subprocess.run([sys.executable, _scr] + _dargs)
            else:
                _print_line("[detail]/distill esta disponible desde el repo de Cognia (no en la instalacion pip).[/detail]")
        elif raw.startswith("/ayuda "):
            _slash_ayuda_detallada(raw[len("/ayuda "):])
        elif raw == "/ayuda":
            if _HAS_RICH and _console:
                _console.print(HELP_TEXT, style="bright_green", markup=False)
            else:
                print(_G + HELP_TEXT + _R)

        # -- Reporte y perfil ----------------------------------------------
        elif raw == "/reporte":
            _slash_reporte()
        elif raw == "/reporte-json":
            _slash_reporte_json()
        elif raw.startswith("/reporte-completo"):
            _slash_reporte_completo(raw[len("/reporte-completo"):].strip())
        elif raw == "/reporte-semanal":
            _slash_reporte_semanal("")
        elif raw.startswith("/cadena-causal"):
            _slash_cadena_causal(raw[len("/cadena-causal"):].strip())
        elif raw == "/metas-pendientes":
            _slash_metas_pendientes("")
        elif raw == "/yo":
            _slash_yo_perfil()
        elif raw == "/yo-actualizar":
            _slash_yo_actualizar()

        # -- Cognitive: simple ---------------------------------------------
        elif raw == "/yo-introspect":
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
            _slash_aprender_card(raw[len("/aprender "):].strip())
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
            _print_line("[warn_cl]Uso: /aprender <frente> | <respuesta> [| <tema>][/warn_cl]")
        elif raw == "/aprender":
            _print_line("[warn_cl]Uso: /aprender <frente> | <respuesta> [| <tema>][/warn_cl]")
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
        elif raw.startswith("/hipotesis ") and raw[len("/hipotesis "):].strip():
            texto = raw[len("/hipotesis "):].strip()
            _run(raw, lambda: ai.generate_hypotheses_many(texto), color="magenta")
        elif raw.startswith("/hipotesis"):
            _print_line("[warn_cl]Uso: /hipotesis <A> | <B>  (pares)  o  /hipotesis <problema>  (N hipotesis)[/warn_cl]")
        elif raw.startswith("/experimento ") and raw[len("/experimento "):].strip():
            texto = raw[len("/experimento "):].strip()
            _run(raw, lambda: ai.run_experiment(texto), color="cyan")
        elif raw.startswith("/experimento"):
            _print_line("[warn_cl]Uso: /experimento <afirmacion>  -- ejemplo: /experimento bubble sort es O(n^2)[/warn_cl]")
        elif raw.startswith("/evaluar-idea ") and raw[len("/evaluar-idea "):].strip():
            texto = raw[len("/evaluar-idea "):].strip()
            _run(raw, lambda: ai.evaluate_idea(texto), color="magenta")
        elif raw.startswith("/evaluar-idea"):
            _print_line("[warn_cl]Uso: /evaluar-idea <idea>  -- ejemplo: /evaluar-idea un IDE que escribe sus propios tests[/warn_cl]")
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
                _lr_path = Path(ruta).expanduser().resolve()
                if _lr_path.suffix.lower() == ".pdf":
                    try:
                        import pdfplumber
                        with pdfplumber.open(_lr_path) as _pdf:
                            _pages = _pdf.pages[:10]  # max 10 pages
                            _pdf_text = "\n\n".join(
                                f"[Pagina {i+1}]\n{page.extract_text() or '(sin texto)'}"
                                for i, page in enumerate(_pages)
                            )
                        content = _pdf_text[:4000]
                        _show_response(content, "bright_green")
                        _session_log.append({"input": raw, "output": content, "elapsed": 0})
                    except ImportError:
                        _print_line("[err_cl]pdfplumber no instalado -- pip install pdfplumber[/err_cl]")
                    except Exception as _pdf_e:
                        _print_line(f"[err_cl]Error leyendo PDF: {_escape(str(_pdf_e))}[/err_cl]")
                else:
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
        elif raw == "/skill" or raw.startswith("/skill "):
            _slash_skill(raw[len("/skill "):] if raw.startswith("/skill ") else "", ai)

        # -- Agent mode -----------------------------------------------------
        elif raw.startswith("/hacer "):
            _tarea = raw[len("/hacer "):].strip()
            if _tarea:
                _print_line("[detail]Iniciando agente...[/detail]")
                _resp = _run_agent_task(ai, _tarea, _print_line)
                if _resp:
                    _show_response(_resp, "cyan")
                else:
                    _print_line("[warn_cl]El agente no produjo respuesta.[/warn_cl]")
                _session_log.append({"input": raw, "output": _resp, "elapsed": 0})
            else:
                _print_line("[warn_cl]Uso: /hacer <descripcion de la tarea>[/warn_cl]")

        # -- Long-form generation --------------------------------------------
        elif raw == "/largo" or raw.startswith("/largo "):
            _pedido = raw[len("/largo "):].strip() if raw.startswith("/largo ") else ""
            if _pedido:
                _slash_largo(ai, _pedido)
            else:
                _print_line("[warn_cl]Uso: /largo <pedido>[/warn_cl]")

        # -- Model switching ---------------------------------------------------
        elif raw == "/modelo" or raw.startswith("/modelo "):
            _slash_modelo(ai, raw[len("/modelo "):] if raw.startswith("/modelo ") else "")

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

        # -- Templates -------------------------------------------------------
        elif raw == "/templates":
            _slash_templates("")
        elif raw.startswith("/template-guia ") or raw == "/template-guia":
            _tg_id = raw[len("/template-guia "):].strip() if raw.startswith("/template-guia ") else ""
            _slash_template_guia(_tg_id)
        elif raw.startswith("/template ") or raw == "/template":
            _tpl_id = raw[len("/template "):].strip() if raw.startswith("/template ") else ""
            _slash_template(_tpl_id)

        # -- Metas ---------------------------------------------------------
        elif raw.startswith("/meta ") and not raw.startswith("/meta-"):
            _meta_titulo = raw[len("/meta "):].strip()
            if _meta_titulo:
                _slash_meta(_meta_titulo)
            else:
                _print_line("[warn_cl]Uso: /meta <titulo>[/warn_cl]")
        elif raw == "/meta":
            _print_line("[warn_cl]Uso: /meta <titulo>[/warn_cl]")
        elif raw == "/metas":
            _slash_metas()
        elif raw.startswith("/meta-ok ") or raw == "/meta-ok":
            _mok_id = raw[len("/meta-ok "):].strip() if raw.startswith("/meta-ok ") else ""
            if _mok_id:
                _slash_meta_ok(_mok_id)
            else:
                _print_line("[warn_cl]Uso: /meta-ok <id>[/warn_cl]")
        elif raw.startswith("/meta-prog ") or raw == "/meta-prog":
            _mprog_args = raw[len("/meta-prog "):].strip() if raw.startswith("/meta-prog ") else ""
            if _mprog_args:
                _slash_meta_prog(_mprog_args)
            else:
                _print_line("[warn_cl]Uso: /meta-prog <id> <porcentaje>[/warn_cl]")
        elif raw.startswith("/meta-borrar ") or raw == "/meta-borrar":
            _mborrar_id = raw[len("/meta-borrar "):].strip() if raw.startswith("/meta-borrar ") else ""
            if _mborrar_id:
                _slash_meta_borrar(_mborrar_id)
            else:
                _print_line("[warn_cl]Uso: /meta-borrar <id>[/warn_cl]")
        elif raw.startswith("/meta-prioridad-ver"):
            _slash_meta_prioridad_ver("")
        elif raw.startswith("/meta-prioridad ") or raw == "/meta-prioridad":
            _mprior_args = raw[len("/meta-prioridad "):].strip() if raw.startswith("/meta-prioridad ") else ""
            _slash_meta_prioridad(_mprior_args)
        elif raw == "/metas-alta":
            _slash_metas_alta("")
        elif raw == "/metas-ordenar":
            _slash_metas_ordenar("")

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

        # -- Chat history commands ------------------------------------------
        elif raw == "/sesiones":
            _slash_sesiones("")
        elif raw == "/resume" or raw.startswith("/resume "):
            _rs_arg = raw[len("/resume "):].strip() if raw.startswith("/resume ") else ""
            _slash_resume(_rs_arg, ai)
        elif raw.startswith("/buscar-historial ") or raw == "/buscar-historial":
            _bh_kw = raw[len("/buscar-historial "):].strip() if raw.startswith("/buscar-historial ") else ""
            _slash_buscar_historial(_bh_kw)
        elif raw.startswith("/sesion-ver ") or raw == "/sesion-ver":
            _sv_id = raw[len("/sesion-ver "):].strip() if raw.startswith("/sesion-ver ") else ""
            _slash_sesion_ver(_sv_id)
        elif raw.startswith("/historial-limpiar ") or raw == "/historial-limpiar":
            _hl_arg = raw[len("/historial-limpiar "):].strip() if raw.startswith("/historial-limpiar ") else ""
            _slash_historial_limpiar(_hl_arg)

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

        # -- Spaced repetition review (bare /revisar) -----------------------
        elif raw == "/revisar":
            _slash_revisar_sm2()

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

        # ── /buscar-web <query> ────────────────────────────────────────
        elif raw.startswith("/buscar-web ") or raw == "/buscar-web":
            _bw_q = raw[len("/buscar-web "):].strip() if raw.startswith("/buscar-web ") else ""
            _slash_buscar_web(_bw_q)

        # ── /buscar-kg <concepto> ──────────────────────────────────────
        elif raw.startswith("/buscar-kg ") or raw == "/buscar-kg":
            _bkg_c = raw[len("/buscar-kg "):].strip() if raw.startswith("/buscar-kg ") else ""
            _slash_buscar_kg(_bkg_c)

        # ── /kg-agregar /kg-stats /kg-predicados /kg-exportar ──────────
        elif raw.startswith("/kg-agregar ") or raw == "/kg-agregar":
            _kga_args = raw[len("/kg-agregar "):].strip() if raw.startswith("/kg-agregar ") else ""
            _slash_kg_agregar(_kga_args)
        elif raw == "/kg-stats":
            _slash_kg_stats("")
        elif raw == "/kg-predicados":
            _slash_kg_predicados("")
        elif raw.startswith("/kg-exportar ") or raw == "/kg-exportar":
            _kge_args = raw[len("/kg-exportar "):].strip() if raw.startswith("/kg-exportar ") else ""
            _slash_kg_exportar(_kge_args)

        # ── /kg-inferir /kg-relacionar /kg-responder /kg-camino ────────
        elif raw.startswith("/kg-inferir ") or raw == "/kg-inferir":
            _kgi_args = raw[len("/kg-inferir "):].strip() if raw.startswith("/kg-inferir ") else ""
            _slash_kg_inferir(_kgi_args)
        elif raw.startswith("/kg-relacionar ") or raw == "/kg-relacionar":
            _kgr_args = raw[len("/kg-relacionar "):].strip() if raw.startswith("/kg-relacionar ") else ""
            _slash_kg_relacionar(_kgr_args)
        elif raw.startswith("/kg-responder ") or raw == "/kg-responder":
            _kgq_args = raw[len("/kg-responder "):].strip() if raw.startswith("/kg-responder ") else ""
            _slash_kg_responder(_kgq_args)
        elif raw.startswith("/kg-camino ") or raw == "/kg-camino":
            _kgc_args = raw[len("/kg-camino "):].strip() if raw.startswith("/kg-camino ") else ""
            _slash_kg_camino(_kgc_args)

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

        # ── /notif* ────────────────────────────────────────────────────
        elif raw == "/notif":
            _slash_notif("")
        elif raw == "/notif-todas":
            _slash_notif_todas("")
        elif raw.startswith("/notif-leer ") or raw == "/notif-leer":
            _notif_leer_arg = raw[len("/notif-leer "):].strip() if raw.startswith("/notif-leer ") else ""
            _slash_notif_leer(_notif_leer_arg)
        elif raw == "/notif-limpiar":
            _slash_notif_limpiar("")

        # ── /recordar* ─────────────────────────────────────────────────
        elif raw.startswith("/recordar ") or raw == "/recordar":
            _rec_arg = raw[len("/recordar "):].strip() if raw.startswith("/recordar ") else ""
            _slash_recordar(_rec_arg)
        elif raw == "/recordatorios":
            _slash_recordatorios("")
        elif raw.startswith("/recordar-cancelar ") or raw == "/recordar-cancelar":
            _rec_cancel_arg = raw[len("/recordar-cancelar "):].strip() if raw.startswith("/recordar-cancelar ") else ""
            _slash_recordar_cancelar(_rec_cancel_arg)

        # -- Session summary ------------------------------------------------
        elif raw == "/resumen-sesion":
            _slash_resumen_sesion_full("")

        # -- /config -------------------------------------------------------
        elif raw == "/config" or raw.startswith("/config "):
            _cfg_arg = raw[len("/config "):].strip() if raw.startswith("/config ") else ""
            _slash_config(_cfg_arg)

        # -- /feedback* ----------------------------------------------------
        elif raw.startswith("/feedback-sesion"):
            _slash_feedback_sesion()
        elif raw.startswith("/feedback ") or raw == "/feedback":
            _fb_arg = raw[len("/feedback "):].strip() if raw.startswith("/feedback ") else ""
            if not _fb_arg:
                _print_line("[warn_cl]Uso: /feedback [positivo|negativo|neutral][/warn_cl]")
            else:
                _slash_feedback(_fb_arg)

            # ── /notas* ────────────────────────────────────────────────────
        elif raw.startswith("/notas-buscar ") or raw == "/notas-buscar":
            _nb_args = raw[len("/notas-buscar "):].strip() if raw.startswith("/notas-buscar ") else ""
            _slash_notas_buscar(_nb_args)
        elif raw == "/notas-stats":
            _slash_notas_stats()
        elif raw.startswith("/notas ") or raw == "/notas":
            _nb2_args = raw[len("/notas "):].strip() if raw.startswith("/notas ") else ""
            _slash_notas(_nb2_args)
        elif raw.startswith("/nota-agregar ") or raw == "/nota-agregar":
            _na_args = raw[len("/nota-agregar "):].strip() if raw.startswith("/nota-agregar ") else ""
            _slash_nota_agregar(_na_args)
        elif raw.startswith("/nota-fijar ") or raw == "/nota-fijar":
            _nf_args = raw[len("/nota-fijar "):].strip() if raw.startswith("/nota-fijar ") else ""
            _slash_nota_fijar(_nf_args)

        # -- Spaced repetition stats / search ------------------------------
        elif raw == "/aprendiendo":
            _slash_aprendiendo()
        elif raw.startswith("/aprendiendo-buscar ") or raw == "/aprendiendo-buscar":
            _ab_args = raw[len("/aprendiendo-buscar "):].strip() if raw.startswith("/aprendiendo-buscar ") else ""
            _slash_aprendiendo_buscar(_ab_args)

        # ── /backup ────────────────────────────────────────────────────
        elif raw == "/backup" or raw.startswith("/backup "):
            _bk_args = raw[len("/backup "):].strip() if raw.startswith("/backup ") else ""
            _slash_backup(_bk_args)

        # ── /mi-uso ────────────────────────────────────────────────────
        elif raw == "/mi-uso":
            _slash_mi_uso("")

        # ── /mi-uso-detalle ────────────────────────────────────────────
        elif raw == "/mi-uso-detalle":
            _slash_mi_uso_detalle("")

        # ── /buscar-memoria ────────────────────────────────────────────
        elif raw == "/buscar-memoria" or raw.startswith("/buscar-memoria "):
            _bm_args = raw[len("/buscar-memoria "):].strip() if raw.startswith("/buscar-memoria ") else ""
            _slash_buscar_memoria(_bm_args)

        # ── /debate ────────────────────────────────────────────────────
        elif raw == "/debate" or raw.startswith("/debate "):
            _db_args = raw[len("/debate "):].strip() if raw.startswith("/debate ") else ""
            _slash_debate(_db_args)

        # ── /contexto-semantico ────────────────────────────────────────
        elif raw == "/contexto-semantico" or raw.startswith("/contexto-semantico "):
            _cs_args = raw[len("/contexto-semantico "):].strip() if raw.startswith("/contexto-semantico ") else ""
            _slash_contexto_semantico(_cs_args)

        # ── /sintetizar ────────────────────────────────────────────────
        elif raw == "/sintetizar" or raw.startswith("/sintetizar "):
            _sint_args = raw[len("/sintetizar "):].strip() if raw.startswith("/sintetizar ") else ""
            _slash_sintetizar(_sint_args)

        # ── /y-si ──────────────────────────────────────────────────────
        elif raw == "/y-si" or raw.startswith("/y-si "):
            _ysi_args = raw[len("/y-si "):].strip() if raw.startswith("/y-si ") else ""
            _slash_y_si(_ysi_args)

        # ── /temas ─────────────────────────────────────────────────────
        elif raw == "/temas":
            _slash_temas("")

        # ── /mi-cognia ─────────────────────────────────────────────────
        elif raw == "/mi-cognia" or raw.startswith("/mi-cognia "):
            _mc_args = raw[len("/mi-cognia "):].strip() if raw.startswith("/mi-cognia ") else ""
            _slash_mi_cognia(_mc_args)

        # ── /perfil-completo ───────────────────────────────────────────
        elif raw == "/perfil-completo" or raw.startswith("/perfil-completo "):
            _pc_args = raw[len("/perfil-completo "):].strip() if raw.startswith("/perfil-completo ") else ""
            _slash_perfil_completo(_pc_args)

        # ── /estado ────────────────────────────────────────────────────
        elif raw == "/estado" or raw.startswith("/estado "):
            _est_args = raw[len("/estado "):].strip() if raw.startswith("/estado ") else ""
            _slash_estado(_est_args)

        # ── /ver-criticas ──────────────────────────────────────────────
        elif raw == "/ver-criticas" or raw.startswith("/ver-criticas "):
            _vc_args = raw[len("/ver-criticas "):].strip() if raw.startswith("/ver-criticas ") else ""
            _slash_ver_criticas(_vc_args)

        # ── /reflexion-profunda ────────────────────────────────────────
        elif raw == "/reflexion-profunda" or raw.startswith("/reflexion-profunda "):
            _rp_args = raw[len("/reflexion-profunda "):].strip() if raw.startswith("/reflexion-profunda ") else ""
            _slash_reflexion_profunda(_rp_args)

        # ── /calidad-respuestas ────────────────────────────────────────
        elif raw == "/calidad-respuestas" or raw.startswith("/calidad-respuestas "):
            _cr_args = raw[len("/calidad-respuestas "):].strip() if raw.startswith("/calidad-respuestas ") else ""
            _slash_calidad_respuestas(_cr_args)

        # ── /recomendar ────────────────────────────────────────────────
        elif raw == "/recomendar":
            _slash_recomendar("")

        # ── /proximos-pasos ────────────────────────────────────────────
        elif raw == "/proximos-pasos":
            _slash_proximos_pasos("")

        # ── /mapa ──────────────────────────────────────────────────────
        elif raw == "/mapa" or raw.startswith("/mapa "):
            _mapa_args = raw[len("/mapa "):].strip() if raw.startswith("/mapa ") else ""
            _slash_mapa(_mapa_args)

        # ── /features ──────────────────────────────────────────────────
        elif raw == "/features" or raw.startswith("/features "):
            _slash_features(raw[len("/features "):].strip() if raw.startswith("/features ") else "")

        # ── /vocabulario-guardar ───────────────────────────────────────
        elif raw == "/vocabulario-guardar" or raw.startswith("/vocabulario-guardar "):
            _slash_vocabulario_guardar(raw[len("/vocabulario-guardar "):].strip() if raw.startswith("/vocabulario-guardar ") else "")

        # ── /vocabulario ───────────────────────────────────────────────
        elif raw == "/vocabulario" or raw.startswith("/vocabulario "):
            _slash_vocabulario(raw[len("/vocabulario "):].strip() if raw.startswith("/vocabulario ") else "")

        # ── /hechos-solidos ─────────────────────────────────────────────
        elif raw == "/hechos-solidos" or raw.startswith("/hechos-solidos "):
            _slash_hechos_solidos(raw[len("/hechos-solidos "):].strip() if raw.startswith("/hechos-solidos ") else "")

        # ── /cristalizar ────────────────────────────────────────────────
        elif raw == "/cristalizar" or raw.startswith("/cristalizar "):
            _slash_cristalizar(raw[len("/cristalizar "):].strip() if raw.startswith("/cristalizar ") else "")

        # ── /conocimiento-ver ───────────────────────────────────────────
        elif raw == "/conocimiento-ver" or raw.startswith("/conocimiento-ver "):
            _slash_conocimiento_ver(raw[len("/conocimiento-ver "):].strip() if raw.startswith("/conocimiento-ver ") else "")

        # ── /quiz* ──────────────────────────────────────────────────────
        elif raw == "/quiz-stats":
            _slash_quiz_stats("")
        elif raw == "/quiz" or raw.startswith("/quiz "):
            _slash_quiz(raw[len("/quiz "):].strip() if raw.startswith("/quiz ") else "")

        # ── /exportar-todo ──────────────────────────────────────────────
        elif raw == "/exportar-todo" or raw.startswith("/exportar-todo "):
            _slash_exportar_todo(raw[len("/exportar-todo "):].strip() if raw.startswith("/exportar-todo ") else "")

        # ── /caminos de aprendizaje ──────────────────────────────────────
        elif raw == "/camino-nuevo" or raw.startswith("/camino-nuevo "):
            _slash_camino_nuevo(raw[len("/camino-nuevo "):].strip() if raw.startswith("/camino-nuevo ") else "")
        elif raw == "/caminos":
            _slash_caminos("")
        elif raw == "/camino-avanzar" or raw.startswith("/camino-avanzar "):
            _slash_camino_avanzar(raw[len("/camino-avanzar "):].strip() if raw.startswith("/camino-avanzar ") else "")
        elif raw == "/etiquetar" or raw.startswith("/etiquetar "):
            _slash_etiquetar(raw[len("/etiquetar "):].strip() if raw.startswith("/etiquetar ") else "")

        # ── /cognia-sabe / cognia-aprende / cognia-olvida / argumento ─────
        elif raw == "/cognia-sabe":
            _slash_cognia_sabe("")
        elif raw == "/cognia-aprende" or raw.startswith("/cognia-aprende "):
            _slash_cognia_aprende(raw[len("/cognia-aprende "):].strip() if raw.startswith("/cognia-aprende ") else "")
        elif raw == "/cognia-olvida" or raw.startswith("/cognia-olvida "):
            _slash_cognia_olvida(raw[len("/cognia-olvida "):].strip() if raw.startswith("/cognia-olvida ") else "")
        elif raw == "/argumento" or raw.startswith("/argumento "):
            _slash_argumento(raw[len("/argumento "):].strip() if raw.startswith("/argumento ") else "")
        elif raw == "/conflictos-kg":
            _slash_conflictos_kg("")
        elif raw == "/verificar-kg":
            _slash_verificar_kg("")
        elif raw == "/resolver-conflicto" or raw.startswith("/resolver-conflicto "):
            _slash_resolver_conflicto(raw[len("/resolver-conflicto "):].strip() if raw.startswith("/resolver-conflicto ") else "")
        elif raw == "/comandos":
            _slash_comandos("")
        elif raw == "/digest":
            _slash_digest("")
        elif raw == "/cognia-info":
            _slash_cognia_info("")
        elif raw == "/inicio-dia":
            _slash_inicio_dia("")

        # ── /ver-contexto / /limpiar-sesion ──────────────────────────────────
        elif raw == "/ver-contexto" or raw.startswith("/ver-contexto "):
            _slash_ver_contexto(raw[len("/ver-contexto "):].strip() if raw.startswith("/ver-contexto ") else "")
        elif raw == "/limpiar-sesion":
            _slash_limpiar_sesion("")

        # -- Unknown slash --------------------------------------------------
        elif raw.startswith("/"):
            _print_line(
                f"[warn_cl]Comando desconocido: {_escape(raw)}[/warn_cl]"
                "  [detail](escribe /ayuda)[/detail]"
            )

        # -- Free text → articulated cognitive response --------------------
        else:
            # Self-tuning: learn traits about this user (name, language, verbosity)
            # from every message, persisted across sessions.
            try:
                from cognia.agent.adaptive_prompt import learn_user_traits
                learn_user_traits(ai, raw)
            except Exception:
                pass
            # ── Auto-routing: is this an ACTION (run the agent) or chat? ──
            # No command needed: a natural-language request to do something is
            # detected and routed to the agent automatically, with a tool hint.
            try:
                from cognia.agent.intent import detect as _detect_intent
                _intent = _detect_intent(raw)
            except Exception:
                _intent = None
            _needs_tool = bool(_intent and _intent.needs_agent)
            if _needs_tool:
                _hint = _intent.suggested_tool
                _hmsg = f" (sugiero {_hint})" if _hint else ""
                _print_line(f"[detail]Detectada accion{_hmsg} -- activando agente...[/detail]")
                _resp = _run_agent_task(ai, raw, _print_line, hint=_hint)
                _show_response(_resp, _ACCENT)
                _session_log.append({"input": raw, "output": _resp, "elapsed": 0})
                _persist_turn(ai, raw, _resp)
            if not _needs_tool:
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
                            from cognia.agent.adaptive_prompt import build_adaptive_system_prompt
                            from cognia.user_prefs import personalize_prompt
                            _system = personalize_prompt(build_adaptive_system_prompt(ai))
                            # Multi-turn: feed the last few turns so the model can
                            # follow the conversation thread. _history holds prior
                            # turns only (the current one is appended AFTER generation),
                            # so it never contains 'raw' yet. Cap to the last 8 turns
                            # (16 messages) to bound the prompt size.
                            _hist_ctx = [
                                h for h in _history[-16:]
                                if h.get("role") in ("user", "assistant") and h.get("content")
                            ]
                            # Prefer the canonical multi-turn API (/v1/chat/completions):
                            # llama-server applies the official Qwen chat template, with
                            # real role separation -- more robust than a hand-built ChatML
                            # string (which malforms on empty/odd turns). Fall back to the
                            # manual ChatML template if the backend lacks stream_chat.
                            # Temperatura explicita (no el default implicito del
                            # backend): visible y auditable en model_constants.
                            from shattering.model_constants import GEN_CHAT_TEMPERATURE
                            _use_chat = hasattr(_llama, "stream_chat")
                            # Memoria real en el fast-path: el bloque HYDRA del
                            # band router va DENTRO del ultimo mensaje user
                            # (ver _build_stream_messages: posicion obligada
                            # para no invalidar el prefijo KV cacheado).
                            _messages = _build_stream_messages(
                                ai, raw, _system, _hist_ctx)
                            if _use_chat:
                                _stream_src = lambda: _llama.stream_chat(
                                    _messages, max_tokens=1024,
                                    temperature=GEN_CHAT_TEMPERATURE)
                            else:
                                from node.inference_pipeline import _apply_qwen_template
                                _formatted = _apply_qwen_template(
                                    _messages[-1]["content"], _system,
                                    history=_hist_ctx or None)
                                _stream_src = lambda: _llama.stream_generate(
                                    _formatted, max_tokens=1024,
                                    temperature=GEN_CHAT_TEMPERATURE)
                            _tokens_buf = []
                            t0 = time.time()
                            try:
                                print("", flush=True)
                                for _tok in _stream_src():
                                    _tokens_buf.append(_tok)
                                    if _HAS_RICH and _console:
                                        _console.print(_tok, end="", style=_ACCENT, highlight=False)
                                    else:
                                        print(_tok, end="", flush=True)
                                print()
                                _full_response = "".join(_tokens_buf).strip()
                                # An empty stream (backend hiccup) is NOT a real answer:
                                # leave _streamed False so we fall through to the
                                # articulated path instead of printing a blank reply.
                                _streamed = bool(_full_response)
                                if _streamed:
                                    elapsed = time.time() - t0
                                    _show_footer(elapsed, _full_response)
                                    _session_log.append({
                                        "input":   raw,
                                        "output":  _full_response,
                                        "elapsed": elapsed,
                                    })
                                    _persist_turn(ai, raw, _full_response)
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
                        from cognia_v3.interfaces.respuestas_articuladas import responder_articulado
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
                            _show_response(result["response"], _ACCENT)
                            _show_footer(elapsed, result["response"])
                            stage = result.get("language_engine", {}).get("stage", "")
                            if stage:
                                _print_line(f"[detail][stage: {stage}][/detail]")
                            _session_log.append({
                                "input":   raw,
                                "output":  result["response"],
                                "elapsed": elapsed,
                            })
                            _history.append({"role": "user", "content": raw})
                            _history.append({"role": "assistant", "content": result["response"]})
                    except Exception as e:
                        _print_line(f"[err_cl]Error: {_escape(str(e))}[/err_cl]")


def _run_agent_task(ai, task: str, _print_fn, max_steps: int = None,
                    hint: str = "", guidance: str = "") -> str:
    """
    ReAct-style agent loop with a CONCRETE tool registry (cognia/agent/tools.py)
    and DYNAMIC step budgeting (cognia/agent/loop.py).

    Steps are not fixed: estimate_step_budget() decides how many a task deserves,
    the agent can request more when it runs out, and AGENT_HARD_CAP is the only
    absolute limit. Tools come from the registry, so adding one never touches
    this function.
    """
    from cognia.agent.tools import run_tool, build_tools_doc
    from cognia.agent.loop import (
        estimate_step_budget, wants_more_steps, AGENT_HARD_CAP,
    )
    # Pull in any tools Cognia synthesized and verified in the background, so the
    # agent can use its own self-made tools. Best-effort.
    try:
        from cognia.agent.tool_synthesis import load_generated_tools
        _n_gen = load_generated_tools()
        if _n_gen:
            _print_fn(f"[detail]{_n_gen} herramienta(s) auto-generada(s) disponibles[/detail]")
    except Exception:
        pass

    TOOLS_DOC = (
        "You are an autonomous agent. Start your reply with ACCION: on the first line.\n\n"
        "ACCION: <tool> <args>\n\n"
        "Tools (ONLY these -- do NOT invent others):\n"
        + build_tools_doc()
        + "\n  responder <respuesta final>          -- usar SOLO cuando la tarea esta completa\n\n"
        "Rules:\n"
        "- escribir_archivo crea directorios solo. NO uses mkdir.\n"
        "- Para escribir_archivo, pone codigo COMPLETO y REAL despues de | (varias lineas ok).\n"
        "- Usa anotar para guardar resultados intermedios; notas para recordarlos.\n"
        "- Usa recordar/kg_buscar para consultar la memoria de Cognia.\n"
        "- responder solo cuando termines. Nada de texto fuera de la linea ACCION."
    )

    # Load persistent agent state
    _AGENT_STATE_PATH = Path.home() / ".cognia_agent_state.json"
    _agent_state: dict = {"tasks": [], "files_touched": [], "key_facts": []}
    try:
        if _AGENT_STATE_PATH.exists():
            import json as _json
            _agent_state = _json.loads(_AGENT_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass

    _prior_files_touched = list(_agent_state.get("files_touched", []))

    _prior_ctx = ""
    if _agent_state["tasks"]:
        _prior_lines = []
        for _t in _agent_state["tasks"][-2:]:
            _prior_lines.append(f"- Tarea anterior: {_t['task'][:80]} -> {_t['result'][:120]}")
        _prior_ctx = "CONTEXTO PREVIO:\n" + "\n".join(_prior_lines) + "\n\n"

    # Skill guidance: an explicit one (from /skill) wins; otherwise auto-apply a
    # skill whose description matches this task, so Claude/Cognia skills shape the
    # agent without an explicit command.
    if not guidance:
        try:
            from cognia.agent.skills import find_skill, skill_guidance
            _matched = find_skill(task)
            if _matched:
                guidance = skill_guidance(_matched)
                _print_fn(f"[detail]Aplicando skill '{_matched.name}'[/detail]")
        except Exception:
            pass

    history = [f"{_prior_ctx}TAREA: {task}"]
    if guidance:
        history.append(guidance)
    if hint:
        # Bias the first step toward the auto-detected tool (the agent is still
        # free to choose another; it's a hint, not a command).
        history.append(f"PISTA: probablemente convenga empezar con la herramienta '{hint}'.")
    _working_memory: dict = {}
    result_text = ""

    # Shared context passed to every tool -- plain dict, no abstraction.
    ctx = {
        "ai": ai,
        "working_memory": _working_memory,
        "agent_state": _agent_state,
        "print_fn": _print_fn,
        "show_diff": (lambda old, new, path: _show_file_diff(old, new, path, _print_fn)),
    }

    # Orchestrator (reused for planning + steps)
    try:
        from shattering.orchestrator import ShatteringOrchestrator as Orchestrator
        orch = getattr(ai, "_orchestrator", None) or Orchestrator(mode="local")
    except Exception as e:
        _print_fn(f"[err_cl]Agente: no hay orquestador: {e}[/err_cl]")
        return "(el agente no pudo iniciar el modelo)"

    # Dynamic step budget: the model decides how many steps the task deserves.
    budget = max_steps if max_steps else estimate_step_budget(task, orch)
    _print_fn(f"[detail]Presupuesto de pasos: {budget} (techo {AGENT_HARD_CAP})[/detail]")

    # Auto-decompose large tasks into sub-steps
    if len(task) > 120:
        try:
            _decomp_prompt = (
                "Break this task into 3-5 concrete sequential steps. "
                "Reply with ONLY a numbered list, one step per line, no explanations.\n\n"
                f"Task: {task}"
            )
            _steps_text = orch.infer(_decomp_prompt).text.strip()
            if _steps_text and len(_steps_text) > 20:
                history.append(f"PLAN DE SUBTAREAS:\n{_steps_text}")
                _print_fn(f"[detail]Plan: {_steps_text[:200]}[/detail]")
        except Exception:
            pass

    total_steps = 0
    _last_sig = None
    _repeat = 0
    while total_steps < AGENT_HARD_CAP:
        # Out of budget: ask the model if it actually needs more steps.
        if total_steps >= budget:
            extra = wants_more_steps(task, "\n".join(history[-3:]), orch)
            if extra <= 0:
                break
            budget = min(budget + extra, AGENT_HARD_CAP)
            _print_fn(f"[detail]El agente pidio {extra} pasos mas (presupuesto {budget})[/detail]")

        total_steps += 1
        ctx_text = "\n".join(history[-6:])
        prompt = f"{TOOLS_DOC}\n\nContexto de la tarea:\n{ctx_text}\n\nSiguiente ACCION:"

        try:
            raw_response = orch.infer(prompt).text.strip()
        except Exception as e:
            _print_fn(f"[err_cl]Agente: error LLM: {e}[/err_cl]")
            break

        _print_fn(f"[detail]paso {total_steps}: {raw_response[:120]}[/detail]")

        m = re.search(r"ACCI[OÓ]N:\s*(\w+)\s*(.*)", raw_response, re.IGNORECASE | re.DOTALL)
        if not m:
            history.append(f"RESULTADO: (respuesta no estructurada) {raw_response[:200]}")
            continue

        action = m.group(1).lower().strip()
        args = m.group(2).strip()

        if action == "responder":
            result_text = args
            break

        # Stuck-detector: same action+args repeated -> nudge, then stop.
        sig = (action, args[:60])
        if sig == _last_sig:
            _repeat += 1
            if _repeat >= 2:
                history.append(
                    "AVISO: estas repitiendo la misma accion sin progreso. "
                    "Cambia de enfoque o usa responder."
                )
            if _repeat >= 3:
                _print_fn("[warn_cl]Agente estancado (accion repetida), deteniendo.[/warn_cl]")
                break
        else:
            _repeat = 0
        _last_sig = sig

        result = run_tool(action, args, ctx)
        history.append(result)
        if action == "escribir_archivo" and result.startswith("RESULTADO escribir_archivo") and "OK" in result:
            _print_fn(f"[ok_cl]{result.split(':', 1)[0].replace('RESULTADO ', '')}[/ok_cl]")

    # Save summary to episodic memory
    summary = f"Tarea: {task[:100]} | Pasos: {total_steps} | Resultado: {result_text[:200]}"
    try:
        ai.observe(summary, provided_label="agente_tarea_completada")
    except Exception:
        pass

    # Register agent task as a conversation turn so follow-up questions work
    try:
        from cognia_v3.memory.conversation_memory import get_conversation_context
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
            "steps": total_steps,
            "ts": datetime.datetime.now().isoformat()[:19],
        })
        _agent_state["tasks"] = _agent_state["tasks"][-5:]
        _AGENT_STATE_PATH.write_text(
            _json_save.dumps(_agent_state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass

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
