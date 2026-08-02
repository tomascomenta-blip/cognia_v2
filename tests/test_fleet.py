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


class TestEscaneoDisco:
    """fleet_status() lista tambien lo que esta en disco y no en FLEET
    (regresion 2026-08-01: gpt-oss/UIGEN/OpenReasoning/VL invisibles)."""

    def test_gguf_no_listado_aparece_con_rol(self, tmp_path, monkeypatch):
        monkeypatch.setenv("COGNIA_MODELS_DIR", str(tmp_path))
        _touch(tmp_path / "gpt-oss-20b-MXFP4.gguf", size=10_000_000)
        from node.fleet import fleet_status
        by_key = {m["key"]: m for m in fleet_status()}
        assert "gpt-oss-20b-mxfp4" in by_key
        m = by_key["gpt-oss-20b-mxfp4"]
        assert m["presente"] is True
        assert "pensador" in m["rol"]
        assert m["params"] == "20B"
        assert m["gb"] > 0

    def test_mmproj_se_saltea(self, tmp_path, monkeypatch):
        monkeypatch.setenv("COGNIA_MODELS_DIR", str(tmp_path))
        _touch(tmp_path / "mmproj-Qwen2.5-VL-7B-Instruct-f16.gguf")
        _touch(tmp_path / "Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf")
        from node.fleet import fleet_status
        keys = [m["key"] for m in fleet_status()]
        assert "qwen2.5-vl-7b-instruct-q4_k_m" in keys
        assert not any(k.startswith("mmproj") for k in keys)

    def test_multiparte_escaneado_exige_todas_las_partes(self, tmp_path, monkeypatch):
        monkeypatch.setenv("COGNIA_MODELS_DIR", str(tmp_path))
        _touch(tmp_path / "otro-9b-q4-00001-of-00002.gguf")
        from node.fleet import fleet_status
        by_key = {m["key"]: m for m in fleet_status()}
        assert by_key["otro-9b-q4"]["presente"] is False
        _touch(tmp_path / "otro-9b-q4-00002-of-00002.gguf")
        by_key = {m["key"]: m for m in fleet_status()}
        assert by_key["otro-9b-q4"]["presente"] is True

    def test_estaticos_no_se_duplican(self, tmp_path, monkeypatch):
        """Un archivo ya cubierto por FLEET no genera entrada extra."""
        monkeypatch.setenv("COGNIA_MODELS_DIR", str(tmp_path))
        _touch(tmp_path / "qwen2.5-coder-0.5b-instruct-q8_0.gguf")
        from node.fleet import fleet_status
        keys = [m["key"] for m in fleet_status()]
        assert keys.count("coder-0.5b") == 1
        assert "qwen2.5-coder-0.5b-instruct-q8_0" not in keys
