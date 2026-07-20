"""
Regresion: cache_hit_rate valia 0.000 siempre, y eso engordaba la fatiga.

`record_embedding_cached()` y `record_embedding_computed()` suman en la ventana
por ciclo solo si esta ya existe (`if self._cache_hits:`), pero las llamadas
llegan antes de que el ciclo la cree. Medido el 2026-07-20 tras dos
observaciones reales de Cognia:

    _cache_hits    [0, 0]      total_cheap_ops     14
    _cache_misses  [0, 0]      total_expensive_ops 80

Los totales SI tenian los datos; la ventana no. Con la ventana en cero,
`cache_hit_rate` salia 0.000 pasara lo que pasara, y esa metrica entra en el
score de fatiga: Cognia acababa limitandose sola (menos top_k, menos pasos de
inferencia) por un numero que nunca se llenaba. Y el SelfArchitect diagnosticaba
"Low embedding cache efficiency" acertando por casualidad.
"""

import pytest

from cognia.fatiga_cognitiva import CognitiveFatigueMonitor


def _monitor():
    return CognitiveFatigueMonitor()


class TestCaeALosTotales:

    def test_con_la_ventana_vacia_usa_los_totales(self):
        m = _monitor()
        # Situacion medida: llamadas antes de que exista la ventana del ciclo.
        for _ in range(3):
            m.record_embedding_cached()
        for _ in range(1):
            m.record_embedding_computed()

        rate = m.get_state()["cache_hit_rate"]
        assert rate == pytest.approx(0.75, abs=0.01), (
            f"3 hits de 4 ops deberian dar 0.75, dio {rate}")

    def test_sin_ninguna_operacion_es_cero(self):
        assert _monitor().get_state()["cache_hit_rate"] == 0.0

    def test_solo_misses_da_cero(self):
        m = _monitor()
        for _ in range(5):
            m.record_embedding_computed()
        assert m.get_state()["cache_hit_rate"] == 0.0

    def test_solo_hits_da_uno(self):
        m = _monitor()
        for _ in range(5):
            m.record_embedding_cached()
        assert m.get_state()["cache_hit_rate"] == 1.0


class TestLaVentanaPorCicloMandaSiTieneDatos:
    """
    El fallback no sustituye a la ventana: si el ciclo SI recogio datos, esos
    son mas informativos porque reflejan el momento, no toda la sesion.
    """

    def test_si_la_ventana_tiene_datos_se_usa_esa(self):
        m = _monitor()
        m.start_cycle()
        for _ in range(4):
            m.record_embedding_cached()
        m.record_embedding_computed()

        rate = m.get_state()["cache_hit_rate"]
        assert rate == pytest.approx(0.8, abs=0.01)


class TestNoEsSiempreCero:
    """El sintoma exacto: daba igual lo que pasara, salia 0.000."""

    def test_una_sesion_con_aciertos_no_puede_dar_cero(self):
        m = _monitor()
        for _ in range(10):
            m.record_embedding_cached()
        for _ in range(2):
            m.record_embedding_computed()

        assert m.get_state()["cache_hit_rate"] > 0.0

    def test_el_ratio_esta_entre_cero_y_uno(self):
        m = _monitor()
        for _ in range(7):
            m.record_embedding_cached()
        for _ in range(13):
            m.record_embedding_computed()

        rate = m.get_state()["cache_hit_rate"]
        assert 0.0 <= rate <= 1.0
        assert rate == pytest.approx(7 / 20, abs=0.01)


class TestReferenciaDeCicloAutocalibrada:
    """
    Los umbrales de ciclo (80 / 300 / 800 ms) se escribieron para un ciclo
    ligero. Medido el 2026-07-20: un `observe()` real tarda 5.300-11.000 ms en
    esta maquina — entre 66 y 140 veces el "normal". Con eso el componente
    temporal quedaba clavado en su maximo SIEMPRE: dejaba de medir nada y solo
    empujaba a Cognia a limitarse sola (top_k mas bajo, menos pasos de
    inferencia) por estar en un equipo donde los ciclos duran segundos.

    La referencia pasa a calibrarse con la mediana observada, pero solo cuando
    supera la constante con holgura: en una maquina rapida no cambia nada.
    """

    def test_sin_datos_usa_la_constante(self):
        from cognia.fatiga_cognitiva import NORMAL_CYCLE_MS
        assert _monitor()._referencia_ciclo() == NORMAL_CYCLE_MS

    def test_una_maquina_rapida_no_recalibra(self):
        """Si los ciclos ya son rapidos, la constante sigue mandando."""
        from cognia.fatiga_cognitiva import NORMAL_CYCLE_MS
        m = _monitor()
        for _ in range(10):
            m._cycle_times.append(60.0)
        assert m._referencia_ciclo() == NORMAL_CYCLE_MS

    def test_una_maquina_lenta_si_recalibra(self):
        m = _monitor()
        for _ in range(10):
            m._cycle_times.append(5000.0)
        assert m._referencia_ciclo() == 5000.0

    def test_no_calibra_con_pocos_ciclos(self):
        """Un arranque en frio no puede fijar la referencia."""
        from cognia.fatiga_cognitiva import NORMAL_CYCLE_MS
        m = _monitor()
        for _ in range(3):
            m._cycle_times.append(9000.0)
        assert m._referencia_ciclo() == NORMAL_CYCLE_MS

    def test_usa_mediana_no_media(self):
        """Un pico aislado no puede mover la referencia."""
        m = _monitor()
        for _ in range(9):
            m._cycle_times.append(1000.0)
        m._cycle_times.append(100000.0)      # un pico enorme
        assert m._referencia_ciclo() == 1000.0

    def test_el_componente_temporal_deja_de_estar_saturado(self):
        """
        El sintoma: con ciclos de 8 s el componente temporal estaba al maximo
        pasara lo que pasara. Tras calibrar, un ciclo TIPICO no satura.
        """
        m = _monitor()
        for _ in range(10):
            m._cycle_times.append(8000.0)

        ref = m._referencia_ciclo()
        assert ref == 8000.0
        # Un ciclo igual a la referencia no puede puntuar como critico.
        from cognia.fatiga_cognitiva import (CRITICAL_CYCLE_MS, HIGH_CYCLE_MS,
                                             NORMAL_CYCLE_MS)
        comp = m._normalize(8000.0, ref,
                            ref * (HIGH_CYCLE_MS / NORMAL_CYCLE_MS),
                            ref * (CRITICAL_CYCLE_MS / NORMAL_CYCLE_MS))
        assert comp < 50, f"un ciclo normal no deberia puntuar {comp}"
