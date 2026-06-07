"""
tests/test_cli_notification_commands.py
Tests for /notif /notif-todas /notif-leer /notif-limpiar CLI commands.
"""
import sys
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helper to build a fake notification dict
# ---------------------------------------------------------------------------

def _make_notif(id_, level="info", title="Test", body="", read=False):
    return {
        "id": id_,
        "user_id": "cli_user",
        "title": title,
        "body": body,
        "level": level,
        "read": read,
        "created_at": 0.0,
        "source": "system",
    }


# ---------------------------------------------------------------------------
# /notif — show unread notifications
# ---------------------------------------------------------------------------

def test_slash_notif_no_exception():
    mock_nc = MagicMock()
    mock_nc.get_all.return_value = [
        _make_notif(1, "success", "Meta completada!", "Aprender Python"),
        _make_notif(2, "info",    "Curiosity: nueva respuesta", "Que es FastAPI?"),
    ]
    with patch.dict("sys.modules", {"cognia.notifications.notification_center": MagicMock(
        NotificationCenter=MagicMock(return_value=mock_nc)
    )}):
        from cognia.cli import _slash_notif
        # Should not raise
        _slash_notif("")
    mock_nc.get_all.assert_called_once_with("cli_user", limit=10, include_read=False)


def test_slash_notif_empty_prints_message(capsys):
    mock_nc = MagicMock()
    mock_nc.get_all.return_value = []
    with patch.dict("sys.modules", {"cognia.notifications.notification_center": MagicMock(
        NotificationCenter=MagicMock(return_value=mock_nc)
    )}):
        from cognia.cli import _slash_notif
        _slash_notif("")
    out = capsys.readouterr().out
    assert "Sin notificaciones" in out


# ---------------------------------------------------------------------------
# /notif-todas — show all notifications including read
# ---------------------------------------------------------------------------

def test_slash_notif_todas_no_exception():
    mock_nc = MagicMock()
    mock_nc.get_all.return_value = [
        _make_notif(1, "info",    "Msg 1", read=False),
        _make_notif(2, "success", "Msg 2", read=True),
    ]
    with patch.dict("sys.modules", {"cognia.notifications.notification_center": MagicMock(
        NotificationCenter=MagicMock(return_value=mock_nc)
    )}):
        from cognia.cli import _slash_notif_todas
        _slash_notif_todas("")
    mock_nc.get_all.assert_called_once_with("cli_user", limit=20, include_read=True)


# ---------------------------------------------------------------------------
# /notif-leer <id> — mark a notification as read
# ---------------------------------------------------------------------------

def test_slash_notif_leer_calls_mark_read():
    mock_nc = MagicMock()
    mock_nc.mark_read.return_value = True
    with patch.dict("sys.modules", {"cognia.notifications.notification_center": MagicMock(
        NotificationCenter=MagicMock(return_value=mock_nc)
    )}):
        from cognia.cli import _slash_notif_leer
        _slash_notif_leer("1")
    mock_nc.mark_read.assert_called_once_with(1, "cli_user")


def test_slash_notif_leer_empty_args_prints_usage(capsys):
    with patch.dict("sys.modules", {"cognia.notifications.notification_center": MagicMock()}):
        from cognia.cli import _slash_notif_leer
        _slash_notif_leer("")
    out = capsys.readouterr().out
    # _print_line may output to stdout; strip markup
    combined = out
    assert "notif-leer" in combined or "Uso" in combined


# ---------------------------------------------------------------------------
# /notif-limpiar — mark all as read
# ---------------------------------------------------------------------------

def test_slash_notif_limpiar_calls_mark_all_read():
    mock_nc = MagicMock()
    mock_nc.mark_all_read.return_value = 5
    with patch.dict("sys.modules", {"cognia.notifications.notification_center": MagicMock(
        NotificationCenter=MagicMock(return_value=mock_nc)
    )}):
        from cognia.cli import _slash_notif_limpiar
        _slash_notif_limpiar("")
    mock_nc.mark_all_read.assert_called_once_with("cli_user")
