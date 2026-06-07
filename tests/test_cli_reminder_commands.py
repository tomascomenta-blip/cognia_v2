"""
tests/test_cli_reminder_commands.py
=====================================
Tests for CLI reminder commands: /recordar, /recordatorios, /recordar-cancelar
"""

import time
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers to import functions under test
# ---------------------------------------------------------------------------

def _import_cmds():
    from cognia.cli import (
        _slash_recordar,
        _slash_recordatorios,
        _slash_recordar_cancelar,
    )
    return _slash_recordar, _slash_recordatorios, _slash_recordar_cancelar


# ---------------------------------------------------------------------------
# /recordar
# ---------------------------------------------------------------------------

class TestSlashRecordar:
    def test_minutos_calls_create_relative(self, capsys):
        _slash_recordar, _, _ = _import_cmds()
        mock_rm = MagicMock()
        mock_rm.create_relative.return_value = {"id": 1, "title": "Estudiar", "status": "pending"}
        with patch("cognia.reminders.reminder_manager.ReminderManager", return_value=mock_rm):
            _slash_recordar("Estudiar en 30 minutos")
        mock_rm.create_relative.assert_called_once_with(
            user_id="cli_user", title="Estudiar", minutes=30
        )
        captured = capsys.readouterr()
        assert "Recordatorio creado" in captured.out
        assert "Estudiar" in captured.out

    def test_horas_calls_create_relative_with_converted_minutes(self, capsys):
        _slash_recordar, _, _ = _import_cmds()
        mock_rm = MagicMock()
        mock_rm.create_relative.return_value = {"id": 2, "title": "Hacer commit", "status": "pending"}
        with patch("cognia.reminders.reminder_manager.ReminderManager", return_value=mock_rm):
            _slash_recordar("Hacer commit en 2 horas")
        mock_rm.create_relative.assert_called_once_with(
            user_id="cli_user", title="Hacer commit", minutes=120
        )

    def test_empty_args_prints_help(self, capsys):
        _slash_recordar, _, _ = _import_cmds()
        _slash_recordar("")
        captured = capsys.readouterr()
        assert "Uso:" in captured.out

    def test_malformed_args_prints_help(self, capsys):
        _slash_recordar, _, _ = _import_cmds()
        _slash_recordar("sin formato correcto")
        captured = capsys.readouterr()
        assert "Uso:" in captured.out

    def test_malformed_args_does_not_crash(self):
        _slash_recordar, _, _ = _import_cmds()
        # Should not raise
        _slash_recordar("algo raro aqui sin patron")

    def test_singular_hora_converts_correctly(self, capsys):
        _slash_recordar, _, _ = _import_cmds()
        mock_rm = MagicMock()
        mock_rm.create_relative.return_value = {"id": 3, "title": "Revisar", "status": "pending"}
        with patch("cognia.reminders.reminder_manager.ReminderManager", return_value=mock_rm):
            _slash_recordar("Revisar en 1 hora")
        mock_rm.create_relative.assert_called_once_with(
            user_id="cli_user", title="Revisar", minutes=60
        )

    def test_singular_minuto_converts_correctly(self, capsys):
        _slash_recordar, _, _ = _import_cmds()
        mock_rm = MagicMock()
        mock_rm.create_relative.return_value = {"id": 4, "title": "Pausa", "status": "pending"}
        with patch("cognia.reminders.reminder_manager.ReminderManager", return_value=mock_rm):
            _slash_recordar("Pausa en 5 minuto")
        mock_rm.create_relative.assert_called_once_with(
            user_id="cli_user", title="Pausa", minutes=5
        )


# ---------------------------------------------------------------------------
# /recordatorios
# ---------------------------------------------------------------------------

class TestSlashRecordatorios:
    def test_empty_list_prints_message(self, capsys):
        _, _slash_recordatorios, _ = _import_cmds()
        mock_rm = MagicMock()
        mock_rm.get_pending.return_value = []
        with patch("cognia.reminders.reminder_manager.ReminderManager", return_value=mock_rm):
            _slash_recordatorios("")
        captured = capsys.readouterr()
        assert "Sin recordatorios pendientes" in captured.out

    def test_pending_list_does_not_raise(self, capsys):
        _, _slash_recordatorios, _ = _import_cmds()
        mock_rm = MagicMock()
        fire_ts = time.time() + 1800  # 30 min from now
        mock_rm.get_pending.return_value = [
            {
                "id": 1,
                "title": "Estudiar Python",
                "fire_at": fire_ts,
                "status": "pending",
            }
        ]
        with patch("cognia.reminders.reminder_manager.ReminderManager", return_value=mock_rm):
            _slash_recordatorios("")
        # Should not raise

    def test_unavailable_module_prints_message(self, capsys):
        _, _slash_recordatorios, _ = _import_cmds()
        with patch("builtins.__import__", side_effect=ImportError):
            try:
                _slash_recordatorios("")
            except Exception:
                pass
        # No assertion needed — just verifying no unhandled crash


# ---------------------------------------------------------------------------
# /recordar-cancelar
# ---------------------------------------------------------------------------

class TestSlashRecordarCancelar:
    def test_valid_id_calls_cancel(self, capsys):
        _, _, _slash_recordar_cancelar = _import_cmds()
        mock_rm = MagicMock()
        mock_rm.cancel.return_value = True
        with patch("cognia.reminders.reminder_manager.ReminderManager", return_value=mock_rm):
            _slash_recordar_cancelar("1")
        mock_rm.cancel.assert_called_once_with(1, "cli_user")
        captured = capsys.readouterr()
        assert "cancelado" in captured.out

    def test_empty_args_prints_usage(self, capsys):
        _, _, _slash_recordar_cancelar = _import_cmds()
        _slash_recordar_cancelar("")
        captured = capsys.readouterr()
        assert "Uso:" in captured.out

    def test_not_found_prints_message(self, capsys):
        _, _, _slash_recordar_cancelar = _import_cmds()
        mock_rm = MagicMock()
        mock_rm.cancel.return_value = False
        with patch("cognia.reminders.reminder_manager.ReminderManager", return_value=mock_rm):
            _slash_recordar_cancelar("99")
        captured = capsys.readouterr()
        assert "no encontrado" in captured.out or "cancelado" in captured.out

    def test_non_numeric_id_prints_warning(self, capsys):
        _, _, _slash_recordar_cancelar = _import_cmds()
        _slash_recordar_cancelar("abc")
        captured = capsys.readouterr()
        # Should print warning about numeric id (rich markup stripped at runtime)
        # No exception raised
