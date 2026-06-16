"""
cognia/effort_levels.py
=======================
Niveles de esfuerzo para el razonamiento de Cognia (objetivo /esfuerzo).

Un dict plano nivel -> parametros: fuente UNICA de verdad para que el comando
/esfuerzo, los loops de razonamiento y el futuro orquestador de flujos acuerden
cuanto "esfuerzo" gastar (tiempo/profundidad de razonamiento, # de verificaciones,
# de alternativas exploradas, complejidad de los planes). Centraliza constantes
que hoy estan dispersas y hardcodeadas en reasoning/*.py.

A ~8 tok/s el nivel 'maximo' multiplica las llamadas LLM -> puede tardar minutos;
por eso el default es 'medio' y el comando muestra los parametros del nivel activo.
"""

from __future__ import annotations

DEFAULT_EFFORT = "medio"

# Parametros monotonos por nivel (cada uno >= el anterior salvo donde no aplica).
EFFORT_LEVELS = {
    "bajo": {
        "max_tokens":     512,
        "alternativas":   1,
        "profundidad":    1,
        "verificaciones": 0,
        "reintentos":     0,
        "subtareas_max":  3,
        "descripcion":    "rapido: una pasada, sin verificacion ni alternativas",
    },
    "medio": {
        "max_tokens":     1024,
        "alternativas":   2,
        "profundidad":    1,
        "verificaciones": 1,
        "reintentos":     1,
        "subtareas_max":  5,
        "descripcion":    "equilibrado: 1 verificacion, pocas alternativas",
    },
    "alto": {
        "max_tokens":     2048,
        "alternativas":   3,
        "profundidad":    2,
        "verificaciones": 2,
        "reintentos":     2,
        "subtareas_max":  8,
        "descripcion":    "profundo: deliberacion + 2 verificaciones",
    },
    "maximo": {
        "max_tokens":     5000,
        "alternativas":   5,
        "profundidad":    3,
        "verificaciones": 3,
        "reintentos":     3,
        "subtareas_max":  12,
        "descripcion":    "exhaustivo: maxima profundidad/alternativas (lento en CPU)",
    },
}

# Aliases con acento / sinonimos -> clave canonica
_ALIASES = {
    "máximo": "maximo",
    "max":    "maximo",
    "minimo": "bajo",
    "mínimo": "bajo",
    "normal": "medio",
}


def normalize_effort(name: str) -> str | None:
    """Clave canonica de un nivel (acepta acentos/sinonimos), o None si no existe."""
    if not name:
        return None
    key = name.strip().lower()
    key = _ALIASES.get(key, key)
    return key if key in EFFORT_LEVELS else None


def get_effort(name: str) -> dict:
    """Parametros del nivel; cae a DEFAULT_EFFORT si el nombre no es valido."""
    return EFFORT_LEVELS[normalize_effort(name) or DEFAULT_EFFORT]


def effort_names() -> list:
    """Nombres canonicos en orden de menor a mayor esfuerzo."""
    return list(EFFORT_LEVELS)
