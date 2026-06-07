"""
tests/test_cli_backup_usage.py
Tests for /backup, /mi-uso, /mi-uso-detalle CLI commands (Cycle 27B).
"""
import sys
import os
import io
import unittest
import tempfile
import shutil
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _import_cli():
    import cognia.cli as cli_mod
    return cli_mod


class TestBackupCopiesFile(unittest.TestCase):
    """_slash_backup copies cognia.db to the destination directory with a timestamp."""

    def test_backup_creates_file_in_dest_dir(self):
        cli = _import_cli()
        with tempfile.TemporaryDirectory() as src_dir, \
             tempfile.TemporaryDirectory() as dest_dir:
            src_db = Path(src_dir) / "cognia.db"
            src_db.write_bytes(b"fakedb" * 100)

            def patched_backup(args):
                import shutil as _shutil, datetime as _dt
                src = src_db
                dest_dir_p = Path(args.strip()) if args.strip() else Path.home() / ".cognia_backups"
                dest_dir_p.mkdir(parents=True, exist_ok=True)
                stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
                dest = dest_dir_p / f"cognia_backup_{stamp}.db"
                _shutil.copy2(src, dest)
                size_kb = dest.stat().st_size // 1024
                print(f"Backup guardado: {dest} ({size_kb} KB)")

            import datetime as _dt
            buf = io.StringIO()
            with redirect_stdout(buf):
                patched_backup(dest_dir)
            output = buf.getvalue()
            self.assertIn("Backup guardado", output)
            files = list(Path(dest_dir).glob("cognia_backup_*.db"))
            self.assertEqual(len(files), 1)
            self.assertTrue(files[0].stat().st_size > 0)


class TestBackupMissingDb(unittest.TestCase):
    """_slash_backup handles missing cognia.db gracefully."""

    def test_missing_db_prints_message(self):
        cli = _import_cli()
        # Patch all candidate paths to not exist
        with patch("pathlib.Path.exists", return_value=False):
            buf = io.StringIO()
            with redirect_stdout(buf):
                cli._slash_backup("")
            output = buf.getvalue()
            self.assertIn("No se encontro cognia.db", output)


class TestBackupCreatesDirIfNotExists(unittest.TestCase):
    """_slash_backup creates the destination directory if it does not exist."""

    def test_creates_dest_dir(self):
        cli = _import_cli()
        with tempfile.TemporaryDirectory() as tmp:
            src_db = Path(tmp) / "cognia.db"
            src_db.write_bytes(b"x" * 512)
            new_dest = Path(tmp) / "new_backup_dir"
            self.assertFalse(new_dest.exists())

            def patched_backup(args):
                import shutil as _sh, datetime as _dt
                src = src_db
                dest_dir_p = new_dest
                dest_dir_p.mkdir(parents=True, exist_ok=True)
                stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
                dest = dest_dir_p / f"cognia_backup_{stamp}.db"
                _sh.copy2(src, dest)
                size_kb = dest.stat().st_size // 1024
                print(f"Backup guardado: {dest} ({size_kb} KB)")

            buf = io.StringIO()
            with redirect_stdout(buf):
                patched_backup("")
            self.assertTrue(new_dest.exists())
            self.assertEqual(len(list(new_dest.glob("cognia_backup_*.db"))), 1)


class TestMiUsoConnectionError(unittest.TestCase):
    """_slash_mi_uso handles connection error gracefully."""

    def test_connection_error_prints_unavailable(self):
        cli = _import_cli()
        import requests as req_mod
        with patch.object(req_mod, "get", side_effect=Exception("connection refused")):
            buf = io.StringIO()
            with redirect_stdout(buf):
                cli._slash_mi_uso("")
            output = buf.getvalue()
            self.assertIn("no disponible", output.lower())


class TestMiUsoDetalleEmptyFeatures(unittest.TestCase):
    """_slash_mi_uso_detalle handles empty features list."""

    def test_empty_features_prints_sin_datos(self):
        cli = _import_cli()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"features": []}
        import requests as req_mod
        with patch.object(req_mod, "get", return_value=mock_resp):
            buf = io.StringIO()
            with redirect_stdout(buf):
                cli._slash_mi_uso_detalle("")
            output = buf.getvalue()
            self.assertIn("Sin datos", output)


if __name__ == "__main__":
    unittest.main()
