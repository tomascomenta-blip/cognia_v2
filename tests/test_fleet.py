"""
tests/test_fleet.py
Tests for node/fleet.py — local GGUF fleet registry.

No network, no real models: COGNIA_MODELS_DIR points at tmp_path.
"""

from __future__ import annotations


def _touch(path, size=10):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


class TestModelsDir:
    def test_env_override_wins(self, tmp_path, monkeypatch):
        monkeypatch.setenv("COGNIA_MODELS_DIR", str(tmp_path))
        from node.fleet import models_dir
        assert models_dir() == tmp_path

    def test_default_is_home_cognia_models(self, monkeypatch):
        monkeypatch.delenv("COGNIA_MODELS_DIR", raising=False)
        from node.fleet import models_dir
        assert models_dir().parts[-2:] == (".cognia", "models")


class TestFleetStatus:
    def test_empty_dir_nothing_present(self, tmp_path, monkeypatch):
        """Directorio vacio: ningun modelo presente, sin excepciones."""
        monkeypatch.setenv("COGNIA_MODELS_DIR", str(tmp_path))
        from node.fleet import fleet_status
        status = fleet_status()
        assert len(status) >= 3
        assert all(not m["presente"] for m in status)
        assert all(m["gb"] == 0 for m in status)

    def test_single_file_model_present(self, tmp_path, monkeypatch):
        """El 0.5B (archivo unico) se reporta presente cuando existe."""
        monkeypatch.setenv("COGNIA_MODELS_DIR", str(tmp_path))
        _touch(tmp_path / "qwen2.5-coder-0.5b-instruct-q8_0.gguf")
        from node.fleet import fleet_status
        by_key = {m["key"]: m for m in fleet_status()}
        assert by_key["coder-0.5b"]["presente"] is True
        assert by_key["chat-7b"]["presente"] is False

    def test_multipart_needs_all_parts(self, tmp_path, monkeypatch):
        """Un multiparte con una sola parte NO cuenta como presente."""
        monkeypatch.setenv("COGNIA_MODELS_DIR", str(tmp_path))
        _touch(tmp_path / "qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf")
        from node.fleet import fleet_status
        by_key = {m["key"]: m for m in fleet_status()}
        assert by_key["chat-7b"]["presente"] is False

        # 10 MB por parte para que el redondeo a 2 decimales de GB no de 0
        _touch(tmp_path / "qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf", size=10_000_000)
        _touch(tmp_path / "qwen2.5-7b-instruct-q4_k_m-00002-of-00002.gguf", size=10_000_000)
        by_key = {m["key"]: m for m in fleet_status()}
        assert by_key["chat-7b"]["presente"] is True
        assert by_key["chat-7b"]["gb"] > 0
