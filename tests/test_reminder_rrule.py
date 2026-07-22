# -*- coding: utf-8 -*-
"""Tests del soporte RRULE (RFC-5545) en reminders (Cal.com nativo extendido).

Verifica que las reglas con FREQ= habilitan cadencias que daily/weekly/monthly
no cubren, que la serie se agota con COUNT/UNTIL (no reagenda), y que los atajos
previos siguen intactos (compatibilidad hacia atrás)."""
import datetime

import pytest

from cognia.reminders import reminder_manager as rm


def _ts(y, mo, d, h=9):
    return datetime.datetime(y, mo, d, h, 0, 0).timestamp()


def test_backward_compat_daily_weekly_monthly():
    base = _ts(2026, 3, 10)
    assert rm._proxima_ocurrencia(base, "daily", base) == base + 86400.0
    assert rm._proxima_ocurrencia(base, "weekly", base) == base + 604800.0
    prox_m = rm._proxima_ocurrencia(base, "monthly", base)
    dt = datetime.datetime.fromtimestamp(prox_m)
    assert (dt.year, dt.month, dt.day) == (2026, 4, 10)


def test_es_rrule_detecta():
    assert rm._es_rrule("FREQ=WEEKLY;INTERVAL=2;BYDAY=FR")
    assert not rm._es_rrule("daily")
    assert not rm._es_rrule(None)


def test_rrule_cada_dos_semanas_viernes():
    # dtstart un viernes; la próxima ocurrencia cae 14 días después, en viernes.
    base = _ts(2026, 3, 6)  # 2026-03-06 es viernes
    assert datetime.datetime.fromtimestamp(base).weekday() == 4
    prox = rm._proxima_ocurrencia(base, "FREQ=WEEKLY;INTERVAL=2;BYDAY=FR", base)
    dt = datetime.datetime.fromtimestamp(prox)
    assert dt.weekday() == 4
    assert (dt - datetime.datetime.fromtimestamp(base)).days == 14


def test_rrule_ultimo_viernes_de_mes():
    base = _ts(2026, 3, 1)
    prox = rm._proxima_ocurrencia(base, "FREQ=MONTHLY;BYDAY=-1FR", base)
    dt = datetime.datetime.fromtimestamp(prox)
    assert dt.weekday() == 4
    # es el último viernes: sumar 7 días lo saca del mes
    assert (dt + datetime.timedelta(days=7)).month != dt.month


def test_rrule_serie_agotada_devuelve_none():
    base = _ts(2026, 3, 6)
    # COUNT=1 -> solo la ocurrencia inicial; no hay 'after' -> None (no reagenda)
    prox = rm._proxima_ocurrencia(base, "FREQ=DAILY;COUNT=1", base)
    assert prox is None


def test_rrule_salta_ocurrencias_pasadas():
    # daemon caído: 'ahora' muy posterior a fire_at -> próxima estrictamente futura
    base = _ts(2026, 3, 6)
    ahora = _ts(2026, 5, 1)
    prox = rm._proxima_ocurrencia(base, "FREQ=WEEKLY;BYDAY=FR", ahora)
    assert prox > ahora


def test_create_acepta_rrule_y_rechaza_basura(tmp_path):
    mgr = rm.ReminderManager(db_path=str(tmp_path / "rem.db"))
    try:
        r = mgr.create("u1", "revision quincenal", _ts(2026, 3, 6),
                       recur="FREQ=WEEKLY;INTERVAL=2;BYDAY=FR")
        assert r["recur"].startswith("FREQ=")
        with pytest.raises(ValueError):
            mgr.create("u1", "mala", _ts(2026, 3, 6), recur="cada_luna_llena")
    finally:
        mgr.stop()
