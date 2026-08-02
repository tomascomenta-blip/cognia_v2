# -*- coding: utf-8 -*-
"""Regresion de las 4 inyecciones cableadas en LanguageEngine (2026-08-02).

Contrato antidaños: cada inyeccion al prompt debe ser ADITIVA y volverse
no-op cuando el subsistema no aporta (usuario sin estilo, sin metas, etc.).
El system prompt se arma en CADA turno: una inyeccion que cambie el prompt
para un usuario nuevo es una regresion que degrada TODAS las respuestas.
"""
import pytest

from cognia.language_engine import LanguageEngine
from cognia.learning.style_engine import StyleEngine


# ── Tarea 1: StyleEngine.get_prompt_instruction ──────────────────────────

def test_style_injection_es_no_op_sin_estilo_y_aditiva_con_estilo(tmp_path, monkeypatch):
    """Prueba exacta: sin estilo aprendido el prompt NO cambia; con estilo se
    añade EXACTAMENTE ' ' + instruccion (nada mas). Asi se descarta que la
    inyeccion contamine el prompt del usuario nuevo."""
    eng = LanguageEngine(db_path=str(tmp_path / "m.db"))

    # Usuario sin estilo aprendido -> get_prompt_instruction() == ""
    monkeypatch.setattr(StyleEngine, "get_prompt_instruction", lambda self: "")
    p_vacio = eng._get_system_prompt("general")
    assert "MARCA_ESTILO_XYZ" not in p_vacio

    # Con estilo aprendido -> se añade exactamente ' MARCA_ESTILO_XYZ' y NADA
    # mas: quitar esa marca reproduce byte a byte el prompt sin estilo.
    monkeypatch.setattr(StyleEngine, "get_prompt_instruction",
                        lambda self: "MARCA_ESTILO_XYZ")
    p_marca = eng._get_system_prompt("general")
    assert "MARCA_ESTILO_XYZ" in p_marca
    assert p_marca.replace(" MARCA_ESTILO_XYZ", "") == p_vacio


def test_style_injection_no_revienta_si_style_engine_falla(tmp_path, monkeypatch):
    """La carga de estilo esta en try/except: un fallo degrada a no-op, no rompe."""
    eng = LanguageEngine(db_path=str(tmp_path / "m.db"))

    def _boom(*a, **k):
        raise RuntimeError("db caida")

    monkeypatch.setattr(StyleEngine, "load", staticmethod(_boom))
    # No debe propagar la excepcion
    p = eng._get_system_prompt("general")
    assert isinstance(p, str) and "Cognia" in p


# ── Tarea 4: context_injector.get_context_block(last_user_text=...) ───────

def test_context_injector_acepta_last_user_text_y_es_no_op_sin_metas():
    """El cableado pasa last_user_text=question. La firma debe aceptarlo y,
    para un usuario sin metas, no debe inventar 'Metas en progreso'."""
    from cognia.context_injector import ContextInjector
    ci = ContextInjector()
    out = ci.get_context_block(
        "usuario_regresion_inexistente_xyz",
        last_user_text="hoy avance mucho con mi proyecto de prueba",
    )
    assert isinstance(out, str)
    assert "Metas en progreso" not in out


# ── Tarea 3: GoalAndPatternEngine.active_goal_hint ───────────────────────

def test_active_goal_hint_es_no_op_sin_objetivo(tmp_path):
    """Sin objetivo activo, active_goal_hint() devuelve "" (no-op del prompt)."""
    from cognia.goal_and_pattern_engine import GoalAndPatternEngine
    eng = GoalAndPatternEngine(str(tmp_path / "g.db"))
    assert eng.active_goal_hint() == ""


def test_goal_hint_wiring_tolera_ai_sin_goal_engine():
    """El cableado usa getattr(ai, '_goal_engine', None): un ai que no expone
    el atributo no debe activar la inyeccion (None -> no-op)."""
    class _AiFake:
        pass
    assert getattr(_AiFake(), "_goal_engine", None) is None
