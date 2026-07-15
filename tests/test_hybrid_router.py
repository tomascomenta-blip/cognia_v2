"""
tests/test_hybrid_router.py
Ruteo hibrido por dificultad a nivel de sistema (cognia/agent/hybrid_router.py):
dificultad general de tarea, perfil combinable por /esfuerzo, kill-switch env,
y los knobs de modalidad nuevos de effort_levels.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cognia.agent.hybrid_router import (   # noqa: E402
    estimate_task_difficulty, route_profile,
)

TRIVIAL = "dime la fecha de hoy"
FACIL = "crea un archivo hola.txt con el texto 'hola mundo'"
CODIGO_DURO = ("Escribe una funcion `min_jumps(nums)` con dynamic programming "
               "que calcule el minimo de saltos para llegar al final, "
               "optimizada O(n), con edge cases de arrays vacios y overflow. "
               "Ejemplos: min_jumps([2,3,1,1,4]) == 2, min_jumps([1]) == 0, "
               "min_jumps([2,1]) == 1, sin importar librerias externas.")
MEDIA = ("compara los archivos a.py y b.py, y luego escribe las diferencias "
         "en diff.md con ejemplos")
MULTI_PASO = ("Investiga las ventajas de FastAPI, luego compara con Flask, "
              "despues escribe un resumen en resumen.md, ejecuta los tests "
              "del proyecto y finalmente genera un informe con los resultados "
              "en informe.md, ademas valida que el json de config parsea.")


# ── estimate_task_difficulty ────────────────────────────────────────────────

def test_dificultad_trivial_baja():
    assert estimate_task_difficulty(TRIVIAL) < 0.12
    assert estimate_task_difficulty("") == 0.0


def test_dificultad_codigo_duro_alta():
    # nunca menor que el estimador de codigo calibrado (max de ambos)
    from cognia.agent.model_router import estimate_difficulty
    d = estimate_task_difficulty(CODIGO_DURO)
    assert d >= estimate_difficulty(CODIGO_DURO)
    assert d >= 0.55


def test_dificultad_multipaso_general_sube():
    # sin una sola senal algoritmica fuerte, el encadenamiento + verbos la sube
    d = estimate_task_difficulty(MULTI_PASO)
    assert d >= 0.30


def test_dificultad_en_rango_y_ordenada():
    ds = [estimate_task_difficulty(t) for t in (TRIVIAL, FACIL, MULTI_PASO)]
    assert all(0.0 <= x <= 1.0 for x in ds)
    assert ds[0] < ds[2]


# ── route_profile: modalidades combinables ──────────────────────────────────

def test_perfil_trivial_es_mono():
    p = route_profile(TRIVIAL, "medio")
    assert p["mono"] is True
    assert p["modalidad"] == "mono"
    assert p["superorganismo"] is False


def test_perfil_facil_es_agente_sin_colonia():
    p = route_profile(FACIL, "medio")
    assert p["modalidad"] == "agente"
    assert p["mono"] is False
    assert p["superorganismo"] is False


def test_perfil_duro_medio_activa_colonia_y_superorganismo():
    p = route_profile(CODIGO_DURO, "medio")
    assert "colonia" in p["modalidad"]
    assert p["colonia_7b"] and p["colonia_q35"]
    # dificultad >= 0.55 a esfuerzo medio -> etapa 4 permitida
    assert p["superorganismo"] is True
    assert "superorganismo" in p["modalidad"]


def test_perfil_bajo_niega_colonia_y_superorganismo():
    p = route_profile(CODIGO_DURO, "bajo")
    assert p["colonia_7b"] is False and p["colonia_q35"] is False
    assert p["superorganismo"] is False
    assert p["razonador_4b"] is False
    assert p["delegacion_max"] == 0
    assert p["modalidad"] == "agente"     # punto intermedio: duro pero acotado


def test_perfil_alto_baja_umbrales():
    # esfuerzo alto corre el eje: una tarea media entra antes a colonia
    p_medio = route_profile(MULTI_PASO, "medio")
    p_alto = route_profile(MULTI_PASO, "alto")
    assert p_alto["umbral_pesado"] < p_medio["umbral_pesado"]
    assert p_alto["pasos_factor"] > p_medio["pasos_factor"]


def test_perfil_maximo_superorganismo_en_tarea_media():
    # puntos intermedios REALES: la misma tarea media es agente+colonia a
    # esfuerzo medio y ademas despierta la etapa 4 solo a esfuerzo maximo
    p_medio = route_profile(MEDIA, "medio")
    p_max = route_profile(MEDIA, "maximo")
    assert p_medio["modalidad"] == "agente+colonia"
    assert p_medio["superorganismo"] is False
    assert p_max["superorganismo"] is True
    assert "superorganismo" in p_max["modalidad"]


def test_perfil_medio_replica_umbral_calibrado():
    # a esfuerzo medio el umbral pesado ES el _HEAVY_THRESHOLD de hoy (0.30):
    # cero regresion en la cascada de generar_codigo
    p = route_profile(FACIL, "medio")
    assert p["umbral_pesado"] == pytest.approx(0.30)
    assert p["bon_max"] == 10 and p["delegacion_max"] == 2
    assert p["pasos_factor"] == pytest.approx(1.0)


def test_perfil_sin_nivel_usa_config_o_default(tmp_path, monkeypatch):
    import cognia.agent.hybrid_router as hr
    monkeypatch.setattr(hr, "_CONFIG_PATH", tmp_path / "no_existe.json")
    p = route_profile(FACIL)
    assert p["esfuerzo"] == "medio"
    (tmp_path / "cfg.json").write_text('{"esfuerzo": "alto"}', encoding="utf-8")
    monkeypatch.setattr(hr, "_CONFIG_PATH", tmp_path / "cfg.json")
    assert route_profile(FACIL)["esfuerzo"] == "alto"


def test_kill_switch_hibrido_off(monkeypatch):
    monkeypatch.setenv("COGNIA_HIBRIDO", "0")
    p = route_profile(CODIGO_DURO, "bajo")
    # legacy: colonia permitida, superorganismo solo por env, sin recortes
    assert p["modalidad"] == "legacy"
    assert p["colonia_7b"] is True and p["superorganismo"] is False
    assert p["umbral_pesado"] == pytest.approx(0.30)
    assert p["pasos_factor"] == pytest.approx(1.0)


# ── superorganismo_enabled(profile): env explicito manda ───────────────────

def test_superorganismo_enabled_env_manda(monkeypatch):
    from cognia.agent.superorganismo import superorganismo_enabled
    perfil_on = {"superorganismo": True}
    monkeypatch.delenv("COGNIA_SUPERORGANISMO", raising=False)
    assert superorganismo_enabled() is False              # sin env ni perfil
    assert superorganismo_enabled(perfil_on) is True      # perfil decide
    monkeypatch.setenv("COGNIA_SUPERORGANISMO", "0")
    assert superorganismo_enabled(perfil_on) is False     # env off gana
    monkeypatch.setenv("COGNIA_SUPERORGANISMO", "1")
    assert superorganismo_enabled({}) is True             # env on gana


# ── effort_levels: knobs de modalidad presentes y monotonos ────────────────

def test_effort_knobs_modalidad():
    from cognia.effort_levels import EFFORT_LEVELS, effort_names
    names = effort_names()
    for k in ("colonia", "superorganismo", "delegacion_max", "bon_max",
              "umbral_shift", "pasos_factor"):
        assert all(k in EFFORT_LEVELS[n] for n in names), f"falta {k}"
    # monotonia: mas esfuerzo nunca recorta capacidad
    for k in ("delegacion_max", "bon_max", "pasos_factor"):
        vals = [EFFORT_LEVELS[n][k] for n in names]
        assert vals == sorted(vals), f"{k} no es monotono: {vals}"
    shifts = [EFFORT_LEVELS[n]["umbral_shift"] for n in names]
    assert shifts == sorted(shifts, reverse=True), f"umbral_shift: {shifts}"
    assert EFFORT_LEVELS["bajo"]["colonia"] is False
    assert EFFORT_LEVELS["medio"]["colonia"] is True
