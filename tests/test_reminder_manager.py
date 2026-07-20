"""
tests/test_reminder_manager.py
================================
Tests for ReminderManager.
"""

import time
import tempfile
import os
import pytest

from cognia.reminders.reminder_manager import ReminderManager


@pytest.fixture
def rm(tmp_path):
    """ReminderManager using an isolated temp DB. Checker stopped after test."""
    db = str(tmp_path / "test_reminders.db")
    manager = ReminderManager(db_path=db)
    yield manager
    manager.stop()


# ── Basic CRUD ─────────────────────────────────────────────────────────

def test_create_returns_dict_with_id_and_pending_status(rm):
    r = rm.create("user1", "Test reminder", fire_at=time.time() + 3600)
    assert isinstance(r["id"], int)
    assert r["id"] > 0
    assert r["status"] == "pending"
    assert r["title"] == "Test reminder"
    assert r["user_id"] == "user1"


def test_create_relative_fire_at_is_approx_now_plus_seconds(rm):
    before = time.time()
    r = rm.create_relative("user1", "Relative reminder", minutes=60)
    after = time.time()
    assert before + 3600 - 5 <= r["fire_at"] <= after + 3600 + 5


def test_get_pending_includes_created_reminder(rm):
    rm.create("user2", "Pending one", fire_at=time.time() + 7200)
    pending = rm.get_pending("user2")
    assert len(pending) >= 1
    titles = [p["title"] for p in pending]
    assert "Pending one" in titles


def test_get_pending_excludes_other_users(rm):
    rm.create("user_a", "Only for A", fire_at=time.time() + 3600)
    pending = rm.get_pending("user_b")
    titles = [p["title"] for p in pending]
    assert "Only for A" not in titles


def test_cancel_changes_status_to_cancelled(rm):
    r = rm.create("user3", "To cancel", fire_at=time.time() + 3600)
    result = rm.cancel(r["id"], "user3")
    assert result is True
    # Must not appear in pending anymore
    pending = rm.get_pending("user3")
    ids = [p["id"] for p in pending]
    assert r["id"] not in ids


def test_cancel_wrong_user_returns_false(rm):
    r = rm.create("user4", "Mine", fire_at=time.time() + 3600)
    result = rm.cancel(r["id"], "wrong_user")
    assert result is False


# ── _check_and_fire ────────────────────────────────────────────────────

def test_check_and_fire_does_not_crash_on_empty_db(rm):
    # Should not raise even with empty table
    rm._check_and_fire()


def test_check_and_fire_fires_past_reminder(rm):
    # Create reminder with fire_at in the past
    r = rm.create("user5", "Past reminder", fire_at=time.time() - 1)

    fired_notifications = []

    class FakeNC:
        def create(self, **kwargs):
            fired_notifications.append(kwargs)

    rm.set_notification_center(FakeNC())
    rm._check_and_fire()

    # Reminder should now be fired
    pending = rm.get_pending("user5")
    ids = [p["id"] for p in pending]
    assert r["id"] not in ids

    # Notification was created
    assert len(fired_notifications) >= 1
    assert fired_notifications[0]["title"] == "Past reminder"


def test_check_and_fire_does_not_fire_future_reminder(rm):
    r = rm.create("user6", "Future reminder", fire_at=time.time() + 9999)
    rm._check_and_fire()
    pending = rm.get_pending("user6")
    ids = [p["id"] for p in pending]
    assert r["id"] in ids


def test_check_and_fire_does_not_double_fire(rm):
    fired_count = [0]

    class CountingNC:
        def create(self, **kwargs):
            fired_count[0] += 1

    rm.set_notification_center(CountingNC())
    r = rm.create("user7", "Once", fire_at=time.time() - 1)
    rm._check_and_fire()
    rm._check_and_fire()  # Second call should be a no-op for same reminder
    assert fired_count[0] == 1


# ── Recurrencia (Cal.com nativo, 2026-07-14) ───────────────────────────

def test_create_recur_valida_y_persiste(rm):
    r = rm.create("u1", "Standup", fire_at=time.time() + 3600, recur="daily")
    assert r["recur"] == "daily"
    pend = rm.get_pending("u1")
    assert pend[0]["recur"] == "daily"


def test_create_recur_invalido_lanza(rm):
    with pytest.raises(ValueError, match="recur invalido"):
        rm.create("u1", "x", fire_at=time.time() + 10, recur="cada_rato")


def test_recur_none_es_disparo_unico(rm):
    """Un recordatorio no recurrente que dispara NO deja otro pendiente."""
    rm.create("u1", "una vez", fire_at=time.time() - 1)   # ya vencido
    rm._check_and_fire()
    assert rm.get_pending("u1") == []


def test_recur_daily_reagenda_al_disparar(rm):
    rm.create("u1", "diario", fire_at=time.time() - 1, recur="daily")
    rm._check_and_fire()
    pend = rm.get_pending("u1")
    assert len(pend) == 1                     # se creó la próxima ocurrencia
    assert pend[0]["recur"] == "daily"
    assert pend[0]["fire_at"] > time.time()   # y es futura


def test_proxima_ocurrencia_no_dispara_para_ponerse_al_dia():
    from cognia.reminders.reminder_manager import _proxima_ocurrencia
    ahora = time.time()
    # fire_at hace 10 días, daily -> la próxima es futura, UNA sola
    prox = _proxima_ocurrencia(ahora - 10 * 86400, "daily", ahora)
    assert prox > ahora
    assert prox - ahora <= 86400 + 1          # dentro del próximo día


def test_proxima_ocurrencia_monthly_arrastra_fin_de_mes():
    from cognia.reminders.reminder_manager import _proxima_ocurrencia
    import datetime
    # 31 de enero + monthly -> 28/29 de feb (no 31 inexistente)
    ene31 = datetime.datetime(2027, 1, 31, 9, 0).timestamp()
    ahora = datetime.datetime(2027, 1, 31, 10, 0).timestamp()
    prox = _proxima_ocurrencia(ene31, "monthly", ahora)
    d = datetime.datetime.fromtimestamp(prox)
    assert d.month == 2 and d.day in (28, 29)


def test_migracion_recur_es_idempotente(tmp_path):
    """Reabrir el manager sobre la misma DB no falla (ADD COLUMN una vez)."""
    db = str(tmp_path / "mig.db")
    m1 = ReminderManager(db_path=db)
    m1.create("u1", "x", fire_at=time.time() + 10, recur="weekly")
    m1.stop()
    m2 = ReminderManager(db_path=db)          # no debe lanzar
    assert m2.get_pending("u1")[0]["recur"] == "weekly"
    m2.stop()
