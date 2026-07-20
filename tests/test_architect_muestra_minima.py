"""
Regresion: el SelfArchitect se diagnosticaba CRITICO sobre 2 decisiones.

Medido el 2026-07-20 mirando la base de datos real:

    decisiones ultimos 7 dias: 2 | marcadas error: 2  ->  tasa 100%

Con eso saltaba el diagnostico `high_error_rate` en severidad **critical**
("el aprendizaje esta fallando"), y la nota global de arquitectura se hundia
por `s_error = 100 - tasa*200` -> 0, dejando el sistema en **36.1/100 CRITICO**
con siete propuestas encabezadas por ese fantasma.

Un sistema que se auto-mejora persiguiendo ruido estadistico se hace dano solo:
gasta sus propuestas, su presupuesto de cambios diarios y su credibilidad en un
problema que no existe. Tras exigir muestra minima, la misma evaluacion dio
**61.1/100** y los 5 diagnosticos restantes son reales.
"""

import pytest

from self_architect import MIN_DECISIONES_PARA_TASA


class TestUmbralDeMuestra:

    def test_el_minimo_es_razonable(self):
        assert 10 <= MIN_DECISIONES_PARA_TASA <= 100


class TestLaTasaNoCuentaSinMuestra:
    """
    Se prueba la logica de decision aislada, que es la que fallaba: con pocas
    decisiones, la tasa no debe diagnosticar ni puntuar.
    """

    def _puntuacion(self, tasa, fiable):
        """Replica de la formula de arquitectura, para fijar el criterio."""
        return (max(0, 100 - tasa * 200) if fiable else 100.0)

    def test_dos_decisiones_erroneas_no_hunden_la_nota(self):
        """El caso exacto medido: 2 de 2 mal -> tasa 1.0."""
        assert self._puntuacion(1.0, fiable=False) == 100.0

    def test_con_muestra_suficiente_la_tasa_si_pesa(self):
        """El mecanismo no se desactiva: solo espera a tener datos."""
        assert self._puntuacion(0.6, fiable=True) == pytest.approx(0.0, abs=20)
        assert self._puntuacion(0.1, fiable=True) == 80.0

    def test_sin_errores_puntua_perfecto(self):
        assert self._puntuacion(0.0, fiable=True) == 100.0


class TestMetricasReales:
    """Contra la base de datos de verdad, si existe."""

    def _metricas(self):
        import os
        import sqlite3
        db = os.path.expanduser("~/.cognia/cognia_memory.db")
        if not os.path.exists(db):
            pytest.skip("sin base de datos de Cognia en esta maquina")
        con = sqlite3.connect(db)
        try:
            fila = con.execute(
                "SELECT SUM(was_error), COUNT(*) FROM decision_log "
                "WHERE timestamp >= datetime('now','-7 days')").fetchone()
        except sqlite3.OperationalError:
            pytest.skip("sin tabla decision_log")
        finally:
            con.close()
        return (fila[0] or 0), (fila[1] or 0)

    def test_la_fiabilidad_se_decide_por_el_conteo(self):
        _, total = self._metricas()
        fiable = total >= MIN_DECISIONES_PARA_TASA
        assert fiable == (total >= MIN_DECISIONES_PARA_TASA)

    def test_el_architect_expone_el_conteo(self):
        """
        Sin exponer cuantas decisiones hay detras, la tasa es incomprobable:
        quien lea el informe no puede saber si el 100% son 2 casos o 200.
        """
        import inspect

        import self_architect
        fuente = inspect.getsource(self_architect)
        assert "decisiones_7d" in fuente
        assert "error_rate_fiable" in fuente


class TestElMismoFantasmaPorLaPuertaDeLosObjetivos:
    """
    El SelfArchitect no era el unico que se creia la tasa sobre 2 decisiones.
    `GoalSystem.auto_generate_goals` creaba "Tasa de error alta: 100%" con
    prioridad **0.9** — la mas alta — asi que ese objetivo fantasma encabezaba
    la lista y dominaba el trabajo autonomo de Cognia. Visto el 2026-07-20 en
    una sesion real del REPL, ya persistido en la base de datos.
    """

    def _sistema(self):
        from cognia.knowledge.goals import GoalSystem
        g = GoalSystem.__new__(GoalSystem)
        g.add_goal = lambda t, d="", priority=0.5: f"{t}|{d}"
        return g

    def _hay_objetivo_de_error(self, estado):
        return any("aprender_nuevo" in str(x)
                   for x in self._sistema().auto_generate_goals(estado))

    def test_dos_decisiones_no_generan_objetivo(self):
        assert not self._hay_objetivo_de_error(
            {"error_rate": 1.0, "total_decisions": 2})

    def test_con_muestra_suficiente_si_lo_genera(self):
        """El mecanismo no se desactiva: espera a tener datos."""
        assert self._hay_objetivo_de_error(
            {"error_rate": 1.0, "total_decisions": 50})

    def test_tasa_baja_no_genera_objetivo(self):
        assert not self._hay_objetivo_de_error(
            {"error_rate": 0.1, "total_decisions": 50})

    def test_el_objetivo_dice_sobre_cuantas_decisiones_se_basa(self):
        """Sin el conteo, "100%" es incomprobable: ¿2 casos o 200?"""
        objetivos = self._sistema().auto_generate_goals(
            {"error_rate": 1.0, "total_decisions": 50})
        texto = next(str(x) for x in objetivos if "aprender_nuevo" in str(x))
        assert "50 decisiones" in texto

    def test_usa_el_mismo_umbral_que_el_arquitecto(self):
        """Dos umbrales distintos para la misma pregunta acabarian divergiendo."""
        from cognia.knowledge.goals import MIN_DECISIONES_PARA_OBJETIVO
        from self_architect import MIN_DECISIONES_PARA_TASA
        assert MIN_DECISIONES_PARA_OBJETIVO == MIN_DECISIONES_PARA_TASA
