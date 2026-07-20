# -*- coding: utf-8 -*-
"""
cognia/agent/hybrid_router.py
=============================
Ruteo HIBRIDO por dificultad a nivel de SISTEMA (mandato 2026-07-15).

La cascada por dificultad ya existia DENTRO de generar_codigo (3B -> 7B ->
Qwen3.5 -> superorganismo); esto la sube a nivel de tarea: la dificultad
estimada de la TAREA (cero LLM) + el nivel /esfuerzo activo arman un PERFIL
de corrida que deciden cuanto sistema despertar:

  mono                 - tarea trivial: respuesta directa / loop de 1-2 pasos
  agente               - facil-media: loop ReAct con tools, 1 modelo (3B+accion)
  agente+colonia       - media: etapas multi-modelo reactivas permitidas
                         (7B, Qwen3.5-4B, razonador 4B del chat, delegacion)
  agente+colonia+superorganismo - dura: etapa 4 (colonia por pedazos) permitida

Las modalidades NO son rigidas: el perfil es un dict de PERMISOS + umbrales
combinables (p.ej. colonia sin superorganismo, superorganismo con esfuerzo
alto en tarea media). Las etapas siguen siendo REACTIVAS (solo disparan si lo
barato fallo); el perfil decide el PERMISO y el umbral, no fuerza el gasto.

Fuentes de verdad: cognia/effort_levels.py (permisos por nivel) y
cognia/agent/model_router.py (estimador de dificultad de codigo, calibrado).
Kill-switch global: COGNIA_HIBRIDO=0 -> perfil legacy (comportamiento previo:
colonia siempre permitida, superorganismo solo por env, presupuesto intacto).
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from cognia.effort_levels import DEFAULT_EFFORT, get_effort, normalize_effort

# Umbrales base del eje de dificultad (esfuerzo medio; umbral_shift los corre).
# _COLONIA_THR replica el _HEAVY_THRESHOLD calibrado de generar_codigo (0.30):
# a esfuerzo medio el comportamiento de la cascada es EXACTAMENTE el de hoy.
_MONO_THR = 0.12
_COLONIA_THR = 0.30
_SUPER_THR = 0.55

# Mismo archivo que cli._load_config (leido directo para no importar cli:
# tools.py usa este modulo y cli importa tools -> ciclo).
_CONFIG_PATH = Path.home() / ".cognia_config.json"

# Marcadores de encadenamiento multi-paso ("y luego", listas numeradas, etc.).
_SEQ_RX = re.compile(
    r"(\by\s+(luego|despu[eé]s)\b|\b(luego|despu[eé]s|primero|segundo|"
    r"finalmente|ademas|además)\b|\band\s+then\b|\bthen\b|^\s*\d+[.)]\s)",
    re.IGNORECASE | re.MULTILINE)

# Verbos de accion distintos = proxy de sub-objetivos independientes.
_VERB_RX = re.compile(
    r"\b(crea|escrib|busca|investiga|analiza|compara|ejecuta|corre|prueba|"
    r"testea|instala|refactoriza|documenta|resume|convierte|calcula|genera|"
    r"lee|borra|mueve|copia|arregla|corrige|implementa|disenia|diseña|"
    r"verifica|valida|extrae|descarga|agrega|elimina)\w*",
    re.IGNORECASE)

# Artefactos con extension mencionados (mas archivos = mas piezas que tocar).
_FILE_RX = re.compile(r"[\w./\\-]+\.(?:py|txt|md|json|csv|html|js|yml|yaml|toml)\b")


def estimate_task_difficulty(task: str) -> float:
    """Dificultad estimada de una TAREA general en [0,1]. Cero LLM.

    max(dificultad de codigo, senal general multi-paso): el estimador de
    model_router ya esta calibrado para codigo/algoritmos; la senal general
    suma encadenamiento, variedad de verbos de accion, artefactos y longitud
    (tareas de investigacion/orquestacion largas sin una sola senal
    algoritmica). max() garantiza que nada que hoy es "duro" deja de serlo."""
    if not task or not task.strip():
        return 0.0
    from cognia.agent.model_router import estimate_difficulty
    base = estimate_difficulty(task)
    t = task.strip()
    n_seq = len(_SEQ_RX.findall(t))
    n_verbs = len({m.group(0).lower()[:6] for m in _VERB_RX.finditer(t)})
    n_files = len(_FILE_RX.findall(t))
    general = (min(n_seq, 3) / 3 * 0.35
               + min(n_verbs, 4) / 4 * 0.35
               + min(n_files, 3) / 3 * 0.10
               + min(len(t), 600) / 600 * 0.20)
    return round(min(1.0, max(base, general)), 3)


def _config_effort() -> str:
    """Nivel /esfuerzo persistido (~/.cognia_config.json), sin importar cli.

    Higiene del instrumento (mismo patron que _bon_log): bajo pytest NO se
    lee el config del usuario — los unit tests preexistentes codifican el
    comportamiento a esfuerzo default y un config real distinto (p.ej.
    'maximo') los volvia dependientes del entorno. Un test que quiera otro
    nivel lo pasa explicito en route_profile(task, effort_name)."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return DEFAULT_EFFORT
    try:
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8")).get(
            "esfuerzo", DEFAULT_EFFORT)
    except Exception:
        return DEFAULT_EFFORT


def _hibrido_off() -> bool:
    return (os.environ.get("COGNIA_HIBRIDO", "").strip().lower()
            in ("0", "off", "false", "no"))


def route_profile(task: str, effort_name: str = None) -> dict:
    """Perfil hibrido de la corrida para `task` bajo el /esfuerzo dado.

    Devuelve un dict plano de permisos/umbrales que consumen el loop /hacer
    (pasos, delegacion), generar_codigo (etapas 7B/q35/superorganismo, BoN)
    y el fast-path de chat (razonador 4B). Sin effort_name se lee el nivel
    activo del config (default 'medio')."""
    d = estimate_task_difficulty(task)
    name = normalize_effort(effort_name or "") or (
        normalize_effort(_config_effort()) or DEFAULT_EFFORT)
    eff = get_effort(name)
    if _hibrido_off():
        return {
            "dificultad": d, "esfuerzo": name, "modalidad": "legacy",
            "mono": False, "colonia": True, "colonia_7b": True,
            "colonia_q35": True, "superorganismo": False,
            "razonador_4b": True, "umbral_pesado": _COLONIA_THR,
            "bon_max": 10, "delegacion_max": 2, "pasos_factor": 1.0,
        }
    shift = float(eff.get("umbral_shift", 0.0))
    umbral_pesado = round(max(0.05, _COLONIA_THR + shift), 3)
    umbral_super = round(max(0.10, _SUPER_THR + shift), 3)
    permiso_colonia = bool(eff.get("colonia", True))
    superorganismo = bool(eff.get("superorganismo", True)) and d >= umbral_super
    mono = d < _MONO_THR
    modalidad = "mono" if mono else "agente"
    if permiso_colonia and d >= umbral_pesado:
        modalidad += "+colonia"
    if superorganismo:
        modalidad += "+superorganismo"
    return {
        "dificultad": d,
        "esfuerzo": name,
        "modalidad": modalidad,
        "mono": mono,
        # Permisos por esfuerzo (la etapa reactiva decide si GASTA; separables
        # a futuro si se mide que conviene 7B sin q35 o viceversa).
        "colonia": permiso_colonia,
        "colonia_7b": permiso_colonia,
        "colonia_q35": permiso_colonia,
        # Decision (permiso + dificultad de la tarea): la etapa 4 ademas exige
        # su propio gate reactivo (nada confirmo) y el env explicito manda.
        "superorganismo": superorganismo,
        "razonador_4b": permiso_colonia,
        "umbral_pesado": umbral_pesado,
        "bon_max": int(eff.get("bon_max", 10)),
        "delegacion_max": int(eff.get("delegacion_max", 2)),
        "pasos_factor": float(eff.get("pasos_factor", 1.0)),
    }
