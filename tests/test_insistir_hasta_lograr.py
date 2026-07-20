"""
Insistir hasta cumplir la especificacion, sabiendo cuando parar.

Tecnica que Cognia encontro investigando el 2026-07-20:
`snwfdhmp/awesome-ralph` (913 estrellas) — correr al agente en bucle hasta
cumplir la especificacion en vez de aceptar el primer intento.

Aqui "especificacion cumplida" no es una opinion del modelo: es que el programa
supere las compuertas montadas esa misma noche — corre en el sandbox, sus tests
no estan en rojo (G2) y la nota llega al umbral. Lo que separa esto de un bucle
de reintentos tonto es el disyuntor: si dos rondas seguidas fallan dejando el
sintoma identico, insistir no aporta y se corta.

Verificado en real: ronda 1 fallo, ronda 2 produjo una cola de prioridad de 81
lineas con 3 tests en verde.
"""

import pytest

from cognia.program_creator import program_creator as PC
from cognia.program_creator.program_creator import (
    HobbySessionResult,
    crear_hasta_lograr,
)


def _resultado(stored, titulos=()):
    return HobbySessionResult(
        attempted=1, successful=stored, stored=stored,
        programs=[type("M", (), {"title": t})() for t in titulos],
        duration_sec=1.0, timestamp="2026-07-20T00:00:00")


class TestParaEnCuantoLoLogra:

    def test_no_gasta_rondas_de_mas(self, monkeypatch):
        """Si la primera ronda lo consigue, no hay segunda."""
        rondas = []

        def falso(**kw):
            rondas.append(1)
            return _resultado(1, ["Cola de prioridad"])

        monkeypatch.setattr(PC, "run_program_hobby", falso)
        r = crear_hasta_lograr("lo que sea", max_rondas=4, verbose=False)

        assert len(rondas) == 1
        assert r.stored == 1

    def test_insiste_hasta_que_sale(self, monkeypatch):
        """El caso real: la ronda 1 fallo y la 2 lo logro."""
        rondas = []

        def falso(**kw):
            rondas.append(1)
            return _resultado(1, ["Bien"]) if len(rondas) >= 2 else _resultado(0)

        monkeypatch.setattr(PC, "run_program_hobby", falso)
        r = crear_hasta_lograr("lo que sea", max_rondas=4, verbose=False)

        assert len(rondas) == 2
        assert r.stored == 1


class TestSabeParar:
    """Un bucle que no sabe parar es el bucle de parches que hay que evitar."""

    def test_el_disyuntor_corta_antes_del_maximo(self, monkeypatch):
        """
        Rondas identicas y esteriles: el disyuntor corta a la segunda, sin
        gastar las 8 que se pidieron.
        """
        rondas = []

        def falso(**kw):
            rondas.append(1)
            return _resultado(0)

        monkeypatch.setattr(PC, "run_program_hobby", falso)
        crear_hasta_lograr("imposible", max_rondas=8, verbose=False)

        assert len(rondas) < 8, "deberia haber cortado por falta de avance"
        assert len(rondas) <= 3

    def test_respeta_el_maximo_de_rondas(self, monkeypatch):
        """Aunque cada ronda cambie el sintoma, no se pasa del limite."""
        rondas = []

        def falso(**kw):
            rondas.append(1)
            return _resultado(0)

        monkeypatch.setattr(PC, "run_program_hobby", falso)
        crear_hasta_lograr("x", max_rondas=2, verbose=False)

        assert len(rondas) <= 2

    def test_devuelve_el_ultimo_resultado_aunque_falle(self, monkeypatch):
        monkeypatch.setattr(PC, "run_program_hobby", lambda **kw: _resultado(0))
        r = crear_hasta_lograr("x", max_rondas=2, verbose=False)

        assert isinstance(r, HobbySessionResult)
        assert r.stored == 0


class TestPasaLaIdeaTalCual:

    def test_la_idea_llega_como_forced_idea(self, monkeypatch):
        """Insistir con OTRA idea no seria insistir."""
        vistas = []

        def falso(**kw):
            vistas.append(kw.get("forced_idea"))
            return _resultado(1, ["ok"])

        monkeypatch.setattr(PC, "run_program_hobby", falso)
        crear_hasta_lograr("cola de prioridad con heapq", verbose=False)

        assert vistas == ["cola de prioridad con heapq"]

    def test_cada_ronda_genera_una_sola_vez(self, monkeypatch):
        """
        max_attempts=1 por ronda: la insistencia la lleva el bucle de fuera,
        que es quien sabe parar. Si cada ronda hiciera 2-3 intentos, el
        disyuntor no veria las huellas.
        """
        vistas = []

        def falso(**kw):
            vistas.append(kw.get("max_attempts"))
            return _resultado(1, ["ok"])

        monkeypatch.setattr(PC, "run_program_hobby", falso)
        crear_hasta_lograr("x", verbose=False)

        assert vistas == [1]


def test_el_maximo_por_defecto_es_razonable():
    assert 2 <= PC.MAX_RONDAS_INSISTIENDO <= 6
