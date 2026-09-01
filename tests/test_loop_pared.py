# -*- coding: utf-8 -*-
"""El presupuesto de PARED que el agente puede leer (2026-09-01).

Hasta hoy el bucle no sabia cuanto reloj le quedaba: quien lo mata es el de
fuera (un runner, un cron, la paciencia del dueno) y el bucle se enteraba cuando
ya estaba muerto. Con COGNIA_PARED_S las compuertas pueden elegir entre "gasta
otro ciclo" y "entrega lo que hay", y el bucle puede avisar de que toca dejar de
producir y ponerse a comprobar.

Sin la variable, TODO tiene que comportarse como antes: es la garantia de que
esto no cambia nada para quien no lo usa.
"""
from __future__ import annotations

import time

import pytest

from cognia.agent import loop


@pytest.fixture(autouse=True)
def _limpia_env(monkeypatch):
    monkeypatch.delenv(loop.ENV_PARED, raising=False)
    yield


def test_sin_variable_no_hay_pared(monkeypatch):
    assert loop._pared_total() is None
    assert loop._pared_restante(time.time()) is None


def test_restante_baja_con_el_tiempo(monkeypatch):
    monkeypatch.setenv(loop.ENV_PARED, "600")
    t0 = time.time() - 100
    resto = loop._pared_restante(t0)
    assert resto is not None
    assert 480 < resto <= 500


def test_nunca_negativo(monkeypatch):
    monkeypatch.setenv(loop.ENV_PARED, "10")
    assert loop._pared_restante(time.time() - 999) == 0.0


@pytest.mark.parametrize("valor", ["", "0", "-5", "no-es-un-numero", "None"])
def test_valores_invalidos_se_ignoran(monkeypatch, valor):
    """Una variable mal puesta NO puede hacer que el agente crea que no le queda
    tiempo: eso convertiria una tarea sana en una entrega a medias."""
    monkeypatch.setenv(loop.ENV_PARED, valor)
    assert loop._pared_total() is None
    assert loop._pared_restante(time.time()) is None


def test_el_minimo_para_trabajar_es_positivo():
    # Si fuese 0 la compuerta del contrato retendria cierres sin tiempo para
    # nada, que es el fallo que este numero existe para evitar.
    assert loop._PARED_MINIMA_TRABAJO > 0
