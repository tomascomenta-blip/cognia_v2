"""Tests de cognia/presupuesto_pared.py — el tope de pared duro por celda."""

import time

import pytest

from cognia.presupuesto_pared import (PRESUPUESTO_DEFECTO, PresupuestoAgotado,
                                      con_presupuesto, presupuesto_celda)


def test_devuelve_el_resultado():
    assert con_presupuesto(5, lambda a, b: a + b, 2, b=3) == 5


def test_relanza_la_excepcion_de_fn():
    def _rompe():
        raise ValueError("propia")
    with pytest.raises(ValueError, match="propia"):
        con_presupuesto(5, _rompe)


def test_corta_el_goteo_lento():
    t0 = time.time()
    with pytest.raises(PresupuestoAgotado, match="presupuesto de pared"):
        con_presupuesto(0.2, time.sleep, 3)
    # el corte llega por el reloj, no por el fin del trabajo
    assert time.time() - t0 < 1.5


def test_presupuesto_celda_env(monkeypatch):
    monkeypatch.delenv("COGNIA_PRESUPUESTO_CELDA", raising=False)
    assert presupuesto_celda() == PRESUPUESTO_DEFECTO
    monkeypatch.setenv("COGNIA_PRESUPUESTO_CELDA", "300")
    assert presupuesto_celda() == 300
    monkeypatch.setenv("COGNIA_PRESUPUESTO_CELDA", "abc")
    assert presupuesto_celda() == PRESUPUESTO_DEFECTO
    monkeypatch.setenv("COGNIA_PRESUPUESTO_CELDA", "0")
    assert presupuesto_celda() == 1
