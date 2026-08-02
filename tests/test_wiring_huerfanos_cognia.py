# -*- coding: utf-8 -*-
"""
tests/test_wiring_huerfanos_cognia.py
=====================================
Regresion del cableado de subsistemas huerfanos en cognia/cognia.py y
cognia/context_injector.py (sesion 2026-08-02):

  1. GoalAndPatternEngine (modulo entero): __init__ lo construye, observe()
     llama pre_observe/post_observe/tick, _sleep_sync() llama run_pattern_batch.
  2. ContinuousLearning.consolidate_slow() corre en _sleep_sync.
  3. StalenessDetector.apply_decay() corre en _sleep_sync.
  4. GoalSystem.resolve_goal() cierra objetivos cuya condicion ya no aplica.
  5. fatigue.reset_state() corre al final de _sleep_sync.
  6. apply_feedback() evoluciona el perfil cognitivo.
  7. context_injector suma get_suggestions_context + auto_detect_progress.

INVARIANTE CENTRAL: el ciclo observe/sleep sigue corriendo CON y SIN cada
subsistema (degradacion a no-op, nunca excepcion que tumbe el ciclo).
"""

import os
import tempfile

import pytest

from cognia.cognia import Cognia


@pytest.fixture(scope="module")
def ai():
    """Una sola instancia Cognia con DB temporal (construirla es caro)."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    inst = Cognia(db_path=path)
    yield inst
    try:
        os.unlink(path)
    except OSError:
        pass


# ── PASOS 7+8: GoalAndPatternEngine ────────────────────────────────────

class TestGoalEngineCableado:
    def test_init_construye_goal_engine(self, ai):
        # El modulo estaba huerfano: ahora debe existir el atributo (y salvo
        # fallo de import, ser una instancia real, no None).
        assert hasattr(ai, "_goal_engine")
        assert ai._goal_engine is not None

    def test_observe_con_goal_engine_retorna_dict(self, ai):
        res = ai.observe("quiero aprender python desde cero", provided_label="programacion")
        assert isinstance(res, dict)
        assert res.get("action") == "learned"
        # post_observe enriquece el result con el objetivo activo detectado.
        assert "active_goal" in res

    def test_observe_sin_goal_engine_sigue_corriendo(self, ai):
        # Simular fallo del subsistema: el ciclo NO debe romperse.
        original = ai._goal_engine
        ai._goal_engine = None
        try:
            res = ai.observe("una observacion cualquiera para inferir")
            assert isinstance(res, dict)
            assert res.get("action") == "infer"
            assert "active_goal" not in res
        finally:
            ai._goal_engine = original


# ── _sleep_sync: run_pattern_batch + continuous + staleness + resolve + reset ──

class TestSleepCableado:
    def test_sleep_con_subsistemas_retorna_str(self, ai):
        ai.observe("gato es un animal domestico", provided_label="animal")
        ai.observe("perro es un animal leal", provided_label="animal")
        out = ai._sleep_sync()
        assert isinstance(out, str)
        assert "CICLO DE SUENO" in out

    def test_sleep_sin_goal_engine_ni_fatiga_sigue_corriendo(self, ai):
        ge, fa = ai._goal_engine, ai.fatigue
        ai._goal_engine = None
        ai.fatigue = None
        try:
            out = ai._sleep_sync()
            assert isinstance(out, str)
            assert "CICLO DE SUENO" in out
        finally:
            ai._goal_engine = ge
            ai.fatigue = fa

    def test_sleep_resetea_fatiga(self, ai):
        if not ai.fatigue:
            pytest.skip("sin monitor de fatiga en esta build")
        ai.observe("algo para acumular algo de fatiga cognitiva medible")
        ai._sleep_sync()
        # reset_state deja el score en 0.0 tras el ciclo de sueno.
        assert ai.fatigue._fatigue_score == 0.0

    def test_resolve_goal_cierra_objetivo_satisfecho(self, ai):
        # Sembrar un objetivo cuya condicion ya NO aplica (0 contradicciones
        # pendientes) y verificar que _sleep_sync lo cierra.
        gid = ai.goal_system.add_goal("resolver_contradiccion",
                                      "contradiccion de prueba", priority=0.8)
        activos_antes = {g["id"] for g in ai.goal_system.get_active_goals(top_k=50)}
        assert gid in activos_antes
        ai._sleep_sync()
        activos_despues = {g["id"] for g in ai.goal_system.get_active_goals(top_k=50)}
        assert gid not in activos_despues


# ── apply_feedback: evolucion del perfil cognitivo ─────────────────────

class TestFeedbackEvolucion:
    def test_apply_feedback_no_revienta_y_retorna_str(self, ai):
        out = ai.apply_feedback(response_id="r-test-1", correct=False,
                                correction_text="la respuesta correcta era otra")
        assert isinstance(out, str)
        assert "Feedback" in out

    def test_apply_feedback_sin_perfil_sigue_corriendo(self, ai):
        original = ai.cognitive_profile
        ai.cognitive_profile = None
        try:
            out = ai.apply_feedback(response_id="r-test-2", correct=True)
            assert isinstance(out, str)
        finally:
            ai.cognitive_profile = original


# ── context_injector: sugerencias + progreso ───────────────────────────

class TestContextInjectorWiring:
    def test_get_context_block_con_texto_no_revienta(self):
        from cognia.context_injector import ContextInjector
        inj = ContextInjector()
        # Con last_user_text se ejercita la rama auto_detect_progress.
        out = inj.get_context_block("local", "quiero aprender python y testing")
        assert isinstance(out, str)

    def test_get_context_block_retrocompatible_sin_texto(self):
        from cognia.context_injector import ContextInjector
        inj = ContextInjector()
        out = inj.get_context_block("local")
        assert isinstance(out, str)

    def test_suggester_atributo_presente(self):
        from cognia.context_injector import ContextInjector
        inj = ContextInjector()
        assert hasattr(inj, "_goal_suggester")
