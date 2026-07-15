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
#
# Knobs de MODALIDAD (hibrido por dificultad, 2026-07-15): que miembros caros
# puede despertar una tarea en este nivel. cognia/agent/hybrid_router.py los
# combina con la dificultad estimada de la tarea para armar el perfil de la
# corrida (mono / agente / +colonia / +superorganismo, combinables):
#   colonia         - etapas multi-modelo reactivas permitidas (7B, Qwen3.5-4B,
#                     razonador 4B del chat)
#   superorganismo  - etapa 4 (colonia por pedazos) permitida si la dificultad
#                     de la tarea cruza su umbral
#   delegacion_max  - profundidad maxima de sub-agentes (delegar_subtarea)
#   bon_max         - techo de candidatos best-of-N en generar_codigo
#   umbral_shift    - desplaza el eje de dificultad de las etapas caras
#                     (negativo = entran antes; positivo = entran mas tarde)
#   pasos_factor    - multiplicador del presupuesto de pasos del loop /hacer
EFFORT_LEVELS = {
    "bajo": {
        "max_tokens":     512,
        "alternativas":   1,
        "profundidad":    1,
        "verificaciones": 0,
        "reintentos":     0,
        "subtareas_max":  3,
        "colonia":        False,
        "superorganismo": False,
        "delegacion_max": 0,
        "bon_max":        3,
        "umbral_shift":   0.15,
        "pasos_factor":   0.5,
        "descripcion":    "rapido: una pasada, sin verificacion ni alternativas",
    },
    "medio": {
        "max_tokens":     1024,
        "alternativas":   2,
        "profundidad":    1,
        "verificaciones": 1,
        "reintentos":     1,
        "subtareas_max":  5,
        "colonia":        True,
        "superorganismo": True,
        "delegacion_max": 2,
        "bon_max":        10,
        "umbral_shift":   0.0,
        "pasos_factor":   1.0,
        "descripcion":    "equilibrado: 1 verificacion, pocas alternativas",
    },
    "alto": {
        "max_tokens":     2048,
        "alternativas":   3,
        "profundidad":    2,
        "verificaciones": 2,
        "reintentos":     2,
        "subtareas_max":  8,
        "colonia":        True,
        "superorganismo": True,
        "delegacion_max": 2,
        "bon_max":        10,
        "umbral_shift":   -0.10,
        "pasos_factor":   1.25,
        "descripcion":    "profundo: deliberacion + 2 verificaciones",
    },
    "maximo": {
        "max_tokens":     5000,
        "alternativas":   5,
        "profundidad":    3,
        "verificaciones": 3,
        "reintentos":     3,
        "subtareas_max":  12,
        "colonia":        True,
        "superorganismo": True,
        "delegacion_max": 3,
        "bon_max":        10,
        "umbral_shift":   -0.20,
        "pasos_factor":   1.5,
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
