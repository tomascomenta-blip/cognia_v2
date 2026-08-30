"""
cognia/user_prefs.py
====================
User personalization + run-mode preferences, persisted in ~/.cognia/config.env.

Separate from the LEARNED traits in cognia/agent/adaptive_prompt.py: those are
inferred from chat over time; these are what the user EXPLICITLY chose in the
onboarding wizard (or via `cognia modo`). Both end up shaping the reply, but
these are deterministic and user-owned.

Kept ASCII-only (the Windows CP1252 CLI), pure where it matters: personalization_suffix
takes a plain dict so it is trivially unit-testable without touching disk.
"""

from __future__ import annotations

from typing import Dict, Optional

# Config keys (namespaced, stored in ~/.cognia/config.env)
K_USER_NAME = "COGNIA_USER_NAME"
K_LANG      = "COGNIA_LANG"       # "espanol" | "ingles"
K_STYLE     = "COGNIA_STYLE"      # "breve" | "detallada" | "tecnica" | "amigable"
K_RUN_MODE  = "COGNIA_RUN_MODE"   # "local" | "compartido" | "memoria"

# Claves que otros modulos DECLARAN y persisten por save_pref(). Se duplica el
# literal a proposito (importar cognia.simple_mode / cognia.cli_visibilidad
# desde aqui crea un ciclo: los dos importan user_prefs); lo que ata las dos
# copias es un test, no la buena fe:
# tests/test_user_prefs.py::test_las_constantes_duplicadas_coinciden.
K_UI_MODE   = "COGNIA_UI_MODE"    # cognia/simple_mode.py    "sencillo" | "avanzado"
K_CMD_NIVEL = "COGNIA_CMD_NIVEL"  # cognia/cli_visibilidad.py "nucleo" | "todo"

_PERSONALIZATION_KEYS = (K_USER_NAME, K_LANG, K_STYLE)

# EL FILTRO DE load_prefs(). Una clave que no este aqui se escribe bien en
# ~/.cognia/config.env y NO SE RELEE: la preferencia funciona en la sesion y
# se olvida al reiniciar, sin ninguna excepcion ni aviso. Le paso a
# COGNIA_UI_MODE (`/modo avanzado`) y le habria pasado a COGNIA_CMD_NIVEL
# (`/avanzado`): los dos vivian de que first_run.apply_config() rellenase
# os.environ, o sea del fallback, no de la preferencia.
#
# Punto de extension: dar de alta una clave es anadirla a esta tupla. El
# guardian que lo obliga es
# tests/test_user_prefs.py::test_toda_clave_persistente_declarada_esta_dada_de_alta,
# que recorre el paquete con AST buscando `K_* = "COGNIA_..."` y falla si
# alguna no esta.
PERSISTED_KEYS = _PERSONALIZATION_KEYS + (K_RUN_MODE, K_UI_MODE, K_CMD_NIVEL)

LANG_CHOICES  = ("espanol", "ingles")
STYLE_CHOICES = ("breve", "detallada", "tecnica", "amigable")
MODE_LABELS = {
    "local":      "Local (este equipo)",
    "compartido": "Compartido (red local)",
    "memoria":    "Solo memoria (sin LLM)",
}

_STYLE_LINE = {
    "breve":     "Prefiere respuestas breves y directas, sin relleno.",
    "detallada": "Prefiere respuestas detalladas, con ejemplos.",
    "tecnica":   "Prefiere un tono tecnico y preciso.",
    "amigable":  "Prefiere un tono cercano y amigable.",
}


def load_prefs() -> Dict[str, str]:
    """Read the persisted preference keys from ~/.cognia/config.env.

    Filtra por PERSISTED_KEYS a proposito (config.env tambien lleva rutas de
    modelos y flags de backend, que no son preferencias del dueno). El precio
    de ese filtro es que una clave sin dar de alta desaparece EN SILENCIO: ver
    el comentario de PERSISTED_KEYS.
    """
    from cognia.first_run import _load_config
    cfg = _load_config()
    return {k: cfg[k] for k in PERSISTED_KEYS if cfg.get(k)}


def save_pref(key: str, value: str) -> None:
    """Persist one personalization/run-mode key (and reflect it in os.environ)."""
    from cognia.first_run import set_config_value
    set_config_value(key, value)


def get_run_mode() -> Optional[str]:
    return load_prefs().get(K_RUN_MODE)


def personalization_suffix(prefs: Dict[str, str]) -> str:
    """Build the system-prompt addendum from explicit user preferences.

    Pure: takes a dict, returns a string. Empty string when nothing is set, so
    appending it to any prompt is a no-op for users who skipped personalization.
    """
    parts = []

    name = (prefs.get(K_USER_NAME) or "").strip()
    if name:
        parts.append(f"El usuario se llama {name}; dirigite a el por su nombre cuando sea natural.")

    lang = (prefs.get(K_LANG) or "").strip().lower()
    if lang == "ingles":
        parts.append("Respondele en ingles salvo que escriba en otro idioma.")
    elif lang == "espanol":
        parts.append("Respondele en espanol salvo que escriba en otro idioma.")

    style = (prefs.get(K_STYLE) or "").strip().lower()
    if style in _STYLE_LINE:
        parts.append(_STYLE_LINE[style])

    if not parts:
        return ""
    return "\n\nPreferencias del usuario (configuradas):\n- " + "\n- ".join(parts)


def personalize_prompt(prompt: str, prefs: Optional[Dict[str, str]] = None) -> str:
    """Append the user's explicit personalization to a system prompt.

    No-op when nothing is configured, so it never alters the canonical identity
    prompt for a fresh user. Best-effort: any error returns the prompt unchanged.
    """
    try:
        if prefs is None:
            prefs = load_prefs()
        return prompt + personalization_suffix(prefs)
    except Exception:
        return prompt
