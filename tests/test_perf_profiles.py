"""
tests/test_perf_profiles.py
Tests for cognia/perf_profiles.py — perfiles de optimizacion CPU/GPU.

Aislamiento: config.env redirigida a tmp_path (patron test_cli_personalization)
y perillas LLAMA_*/COGNIA_PERF_PROFILE limpiadas del entorno en cada test.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from cognia import first_run
from cognia import perf_profiles as pp

# Todas las perillas que apply_profile toca (limpiar y dejar restaurar a monkeypatch)
_KNOBS = ("LLAMA_N_GPU_LAYERS", "LLAMA_CTX_SIZE", "LLAMA_N_THREADS",
          "COGNIA_PERF_PROFILE", "LLAMA_SERVER_PORT")


@pytest.fixture(autouse=True)
def isolate_config(tmp_path, monkeypatch):
    """Config en tmp_path y entorno limpio, con restauracion REAL.

    monkeypatch.delenv sobre una var AUSENTE no registra nada que restaurar,
    asi que las vars que apply_profile CREA via set_config_value sobrevivirian
    al test (fuga detectada por la verificacion adversarial de la tanda-1).
    Snapshot manual + restore en el teardown cierra esa fuga.
    """
    import os
    monkeypatch.setattr(first_run, "COGNIA_HOME", tmp_path)
    monkeypatch.setattr(first_run, "CONFIG_FILE", tmp_path / "config.env")
    snapshot = {k: os.environ.get(k) for k in _KNOBS}
    for k in _KNOBS:
        monkeypatch.delenv(k, raising=False)
    yield tmp_path
    for k, v in snapshot.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


# ---------------------------------------------------------------------------
# PROFILES: forma basica
# ---------------------------------------------------------------------------

class TestProfilesShape:
    def test_has_cpu_and_gpu(self):
        assert set(pp.PROFILES) == {"cpu", "gpu"}

    def test_cpu_knobs(self):
        cpu = pp.PROFILES["cpu"]
        assert cpu["LLAMA_N_GPU_LAYERS"] == "0"
        assert cpu["LLAMA_CTX_SIZE"] == "4096"
        assert cpu["COGNIA_PERF_PROFILE"] == "cpu"
        assert int(cpu["LLAMA_N_THREADS"]) >= 1

    def test_gpu_knobs(self):
        gpu = pp.PROFILES["gpu"]
        assert gpu["LLAMA_N_GPU_LAYERS"] == "99"
        assert gpu["LLAMA_CTX_SIZE"] == "16384"
        assert gpu["COGNIA_PERF_PROFILE"] == "gpu"
        assert int(gpu["LLAMA_N_THREADS"]) >= int(pp.PROFILES["cpu"]["LLAMA_N_THREADS"])


# ---------------------------------------------------------------------------
# current_profile()
# ---------------------------------------------------------------------------

class TestCurrentProfile:
    def test_default_is_cpu(self):
        """Sin COGNIA_PERF_PROFILE en el entorno, el default es 'cpu'."""
        assert pp.current_profile() == "cpu"

    def test_reads_env(self, monkeypatch):
        monkeypatch.setenv("COGNIA_PERF_PROFILE", "gpu")
        assert pp.current_profile() == "gpu"

    def test_garbage_falls_back_to_cpu(self, monkeypatch):
        monkeypatch.setenv("COGNIA_PERF_PROFILE", "cuantico")
        assert pp.current_profile() == "cpu"


# ---------------------------------------------------------------------------
# apply_profile()
# ---------------------------------------------------------------------------

class TestApplyProfile:
    def test_apply_gpu_sets_envs(self):
        applied = pp.apply_profile("gpu")
        assert applied == pp.PROFILES["gpu"]
        import os
        assert os.environ["LLAMA_N_GPU_LAYERS"] == "99"
        assert os.environ["LLAMA_CTX_SIZE"] == "16384"
        assert os.environ["COGNIA_PERF_PROFILE"] == "gpu"
        assert pp.current_profile() == "gpu"

    def test_apply_persists_to_config_file(self, isolate_config):
        pp.apply_profile("gpu")
        content = (isolate_config / "config.env").read_text(encoding="utf-8")
        assert "LLAMA_N_GPU_LAYERS=99" in content
        assert "LLAMA_CTX_SIZE=16384" in content
        assert "COGNIA_PERF_PROFILE=gpu" in content

    def test_apply_cpu_over_gpu_switches_back(self):
        """Volver a cpu pisa las perillas gpu (update in place en config.env)."""
        pp.apply_profile("gpu")
        pp.apply_profile("cpu")
        import os
        assert os.environ["LLAMA_N_GPU_LAYERS"] == "0"
        assert os.environ["LLAMA_CTX_SIZE"] == "4096"
        assert pp.current_profile() == "cpu"

    def test_apply_invalid_raises_value_error(self):
        with pytest.raises(ValueError, match="Perfil desconocido"):
            pp.apply_profile("tpu")

    def test_apply_invalid_does_not_touch_config(self, isolate_config):
        with pytest.raises(ValueError):
            pp.apply_profile("tpu")
        assert not (isolate_config / "config.env").exists()


# ---------------------------------------------------------------------------
# profile_summary()
# ---------------------------------------------------------------------------

class TestProfileSummary:
    def test_summary_contains_all_knobs(self):
        text = pp.profile_summary("gpu")
        for knob in ("LLAMA_N_GPU_LAYERS", "LLAMA_CTX_SIZE",
                     "LLAMA_N_THREADS", "COGNIA_PERF_PROFILE"):
            assert knob in text
        assert "99" in text and "16384" in text

    def test_summary_marks_active_profile(self):
        pp.apply_profile("cpu")
        assert "(activo)" in pp.profile_summary("cpu")
        assert "(activo)" not in pp.profile_summary("gpu")

    def test_summary_shows_current_value_arrow(self, monkeypatch):
        """Perilla distinta al perfil se muestra con '->' (actual -> nuevo)."""
        monkeypatch.setenv("LLAMA_N_GPU_LAYERS", "0")
        text = pp.profile_summary("gpu")
        assert "LLAMA_N_GPU_LAYERS: 0 -> 99" in text

    def test_summary_invalid_raises(self):
        with pytest.raises(ValueError, match="Perfil desconocido"):
            pp.profile_summary("npu")


# ---------------------------------------------------------------------------
# restart_backend_hint() / kill_llama_server()
# ---------------------------------------------------------------------------

class TestRestartHint:
    def test_hint_when_server_running(self):
        with patch.object(pp, "_server_running", return_value=True):
            hint = pp.restart_backend_hint()
        assert "proximo arranque" in hint
        assert "8088" in hint

    def test_empty_when_no_server(self):
        with patch.object(pp, "_server_running", return_value=False):
            assert pp.restart_backend_hint() == ""

    def test_hint_uses_custom_port(self, monkeypatch):
        monkeypatch.setenv("LLAMA_SERVER_PORT", "9099")
        with patch.object(pp, "_server_running", return_value=True):
            assert "9099" in pp.restart_backend_hint()

    def test_garbage_port_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("LLAMA_SERVER_PORT", "no-un-puerto")
        assert pp._server_port() == 8088


class TestKillLlamaServer:
    def test_returns_false_when_nothing_to_kill(self):
        """Sin procesos llama-server devuelve False y no lanza (via psutil)."""
        pytest.importorskip("psutil")
        with patch("psutil.process_iter", return_value=[]):
            assert pp.kill_llama_server() is False

    def test_only_matches_exact_binary_names(self):
        """No toca procesos con nombres parecidos pero distintos."""
        pytest.importorskip("psutil")
        from unittest.mock import MagicMock
        otro = MagicMock()
        otro.info = {"name": "mi-llama-server-monitor.exe"}
        with patch("psutil.process_iter", return_value=[otro]):
            assert pp.kill_llama_server() is False
        otro.terminate.assert_not_called()

    def test_fallback_without_psutil_uses_exact_name(self, monkeypatch):
        """Sin psutil degrada a taskkill/pkill por nombre exacto, sin lanzar."""
        import builtins
        real_import = builtins.__import__

        def no_psutil(name, *args, **kwargs):
            if name == "psutil":
                raise ImportError("psutil no disponible")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", no_psutil)
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            from unittest.mock import MagicMock
            return MagicMock(returncode=128)  # "no encontrado"

        monkeypatch.setattr(pp.subprocess, "run", fake_run)
        assert pp.kill_llama_server() is False
        assert any("llama-server" in part for part in captured["cmd"])
