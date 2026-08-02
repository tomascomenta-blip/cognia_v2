"""
tests/test_self_architect_fatigue.py — Regresión del fallback de FatigueAdvisor.

Bug cubierto (cognia_v3/core/self_architect.py, cazado 2026-08-01):
  FatigueAdvisor.get_fatigue_level() sin instancia de Cognia cae al fallback
  que consulta chat_history; en un DB nuevo (sin esa tabla) tiraba
  sqlite3.OperationalError y tumbaba el ciclo entero de diagnóstico.

Fix: try/except sqlite3.Error → ('low', 0.0) (sin señal de carga = fatiga baja).
"""

from __future__ import annotations

from cognia_v3.core.self_architect import FatigueAdvisor


def test_get_fatigue_level_sin_tabla_chat_history(tmp_path):
    """DB nuevo sin chat_history: no debe crashear, debe asumir fatiga baja."""
    db = str(tmp_path / "vacio.db")
    advisor = FatigueAdvisor(db_path=db)
    level, score = advisor.get_fatigue_level()   # sin cognia_instance → fallback DB
    assert level == "low"
    assert score == 0.0


def test_get_fatigue_level_prefiere_score_de_cognia(tmp_path):
    """Con instancia que expone fatigue.score, el DB ni se toca."""
    class _Fatiga:
        score = 0.45

    class _Cognia:
        fatigue = _Fatiga()

    advisor = FatigueAdvisor(db_path=str(tmp_path / "no_existe.db"))
    level, score = advisor.get_fatigue_level(cognia_instance=_Cognia())
    assert score == 0.45
    assert level == "moderate"
