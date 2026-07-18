"""
tests/test_velocity.py
Tests para cognia/velocity.py — selector del mecanismo de decodificacion.

Aislamiento: config.env redirigida a tmp_path y perillas COGNIA_*/LLAMA_*
limpiadas con snapshot/restore manual (patron test_perf_profiles: el fixture
corregido contra la fuga de vars CREADAS por set_config_value).
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cognia import first_run
from cognia import perf_profiles as pp
from cognia import velocity as vel

# Todas las perillas que velocity toca o lee (limpiar y restaurar a mano)
_KNOBS = ("COGNIA_VELOCIDAD", "COGNIA_VELOCIDAD_HIBRIDO",
          "LLAMA_DRAFT_GGUF_PATH", "COGNIA_DRAFT_PATH", "COGNIA_BDRAFT_CKPT",
          "COGNIA_ESFUERZO", "COGNIA_MODELS_DIR", "LLAMA_SERVER_PORT")


@pytest.fixture(autouse=True)
def isolate_config(tmp_path, monkeypatch):
    """Config en tmp_path y entorno limpio, con restauracion REAL.

    monkeypatch.delenv sobre una var AUSENTE no registra nada que restaurar,
    asi que las vars que set_mode/set_hybrid CREAN via set_config_value
    sobrevivirian al test. Snapshot manual + restore cierra esa fuga
    (mismo fixture corregido que tests/test_perf_profiles.py).
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


@pytest.fixture
def draft_file(tmp_path, monkeypatch):
    """Draft GGUF falso en tmp_path, apuntado por COGNIA_DRAFT_PATH."""
    p = tmp_path / "draft-0.5b-q8_0.gguf"
    p.write_bytes(b"gguf")
    monkeypatch.setenv("COGNIA_DRAFT_PATH", str(p))
    return p


# ---------------------------------------------------------------------------
# MODOS: forma basica
# ---------------------------------------------------------------------------

class TestModosShape:
    def test_los_cuatro_modos(self):
        assert list(vel.MODOS) == ["clasico", "dspark", "gemma",
                                   "difusion-dspark"]

    def test_cada_modo_tiene_las_claves(self):
        for spec in vel.MODOS.values():
            assert set(spec) == {"descripcion", "disponible_fn", "requisito"}
            assert callable(spec["disponible_fn"])

    def test_clasico_siempre_disponible(self):
        ok, razon = vel._disponible("clasico")
        assert ok is True and razon == ""

    def test_modos_difusion_no_disponibles_sin_bdraft(self):
        for name in ("gemma", "difusion-dspark"):
            ok, razon = vel._disponible(name)
            assert ok is False
            assert "BDraft entrenado" in razon
            assert "DSPARK" in razon

    def test_bdraft_ckpt_solo_no_alcanza(self, tmp_path, monkeypatch):
        """Aun con checkpoint, falta el pipeline v0: sigue no disponible."""
        ckpt = tmp_path / "bdraft_v0.pt"
        ckpt.write_bytes(b"x")
        monkeypatch.setenv("COGNIA_BDRAFT_CKPT", str(ckpt))
        ok, razon = vel._disponible("gemma")
        assert ok is False
        assert "pipeline" in razon

    def test_per_request_spec_field_es_none(self):
        """Probe b10066: los campos speculative por request se ignoran."""
        assert vel.PER_REQUEST_SPEC_FIELD is None

    def test_build_request_overrides_vacio(self):
        assert vel.build_request_overrides("dspark") == {}
        assert vel.build_request_overrides("clasico") == {}


# ---------------------------------------------------------------------------
# get_mode() / set_mode()
# ---------------------------------------------------------------------------

class TestGetSetMode:
    def test_default_es_clasico(self):
        assert vel.get_mode() == "clasico"

    def test_lee_env(self, monkeypatch):
        monkeypatch.setenv("COGNIA_VELOCIDAD", "dspark")
        assert vel.get_mode() == "dspark"

    def test_basura_cae_a_clasico(self, monkeypatch):
        monkeypatch.setenv("COGNIA_VELOCIDAD", "turbo-cuantico")
        assert vel.get_mode() == "clasico"

    def test_set_dspark_persiste_modo_y_draft(self, isolate_config, draft_file):
        import os
        with patch.object(pp, "_server_running", return_value=False):
            hint = vel.set_mode("dspark")
        assert hint == ""
        assert vel.get_mode() == "dspark"
        assert os.environ["LLAMA_DRAFT_GGUF_PATH"] == str(draft_file)
        content = (isolate_config / "config.env").read_text(encoding="utf-8")
        assert "COGNIA_VELOCIDAD=dspark" in content
        assert f"LLAMA_DRAFT_GGUF_PATH={draft_file}" in content

    def test_set_clasico_limpia_draft(self, isolate_config, draft_file):
        import os
        with patch.object(pp, "_server_running", return_value=False):
            vel.set_mode("dspark")
            vel.set_mode("clasico")
        assert vel.get_mode() == "clasico"
        assert "LLAMA_DRAFT_GGUF_PATH" not in os.environ
        content = (isolate_config / "config.env").read_text(encoding="utf-8")
        assert "COGNIA_VELOCIDAD=clasico" in content
        assert "LLAMA_DRAFT_GGUF_PATH=\n" in content     # valor vacio

    def test_set_dspark_avisa_restart_si_server_vivo(self, draft_file):
        with patch.object(pp, "_server_running", return_value=True):
            hint = vel.set_mode("dspark")
        assert "proximo arranque" in hint

    def test_set_desconocido_lanza(self):
        with pytest.raises(ValueError, match="Modo desconocido"):
            vel.set_mode("warp")

    def test_set_dspark_sin_draft_lanza_con_razon(self, tmp_path, monkeypatch):
        monkeypatch.setenv("COGNIA_DRAFT_PATH",
                           str(tmp_path / "no-existe.gguf"))
        with pytest.raises(ValueError, match="falta el draft GGUF"):
            vel.set_mode("dspark")

    def test_set_gemma_lanza_con_razon_exacta(self):
        with pytest.raises(ValueError, match="BDraft entrenado"):
            vel.set_mode("gemma")
        with pytest.raises(ValueError, match="DSPARK"):
            vel.set_mode("difusion-dspark")

    def test_set_no_disponible_no_toca_config(self, isolate_config):
        with pytest.raises(ValueError):
            vel.set_mode("gemma")
        assert not (isolate_config / "config.env").exists()


# ---------------------------------------------------------------------------
# hybrid_enabled() / set_hybrid()
# ---------------------------------------------------------------------------

class TestHybrid:
    def test_default_off(self):
        assert vel.hybrid_enabled() is False

    def test_round_trip_persistente(self, isolate_config):
        vel.set_hybrid(True)
        assert vel.hybrid_enabled() is True
        content = (isolate_config / "config.env").read_text(encoding="utf-8")
        assert "COGNIA_VELOCIDAD_HIBRIDO=on" in content
        vel.set_hybrid(False)
        assert vel.hybrid_enabled() is False

    def test_valores_on(self, monkeypatch):
        for v in ("1", "on", "true", "si"):
            monkeypatch.setenv("COGNIA_VELOCIDAD_HIBRIDO", v)
            assert vel.hybrid_enabled() is True
        monkeypatch.setenv("COGNIA_VELOCIDAD_HIBRIDO", "off")
        assert vel.hybrid_enabled() is False


# ---------------------------------------------------------------------------
# resolve_mode()
# ---------------------------------------------------------------------------

class TestResolveMode:
    def test_hibrido_off_respeta_modo_fijo(self, draft_file):
        with patch.object(pp, "_server_running", return_value=False):
            vel.set_mode("dspark")
        assert vel.resolve_mode("chat", "hola") == "dspark"
        assert vel.resolve_mode("agente", "analiza esto") == "dspark"

    def test_hibrido_off_modo_fijo_no_disponible_degrada_con_aviso(
            self, monkeypatch, caplog):
        """Config vieja apuntando a gemma sin BDraft: clasico CON AVISO."""
        import logging
        monkeypatch.setenv("COGNIA_VELOCIDAD", "gemma")
        with caplog.at_level(logging.WARNING, logger="cognia.velocity"):
            assert vel.resolve_mode("chat", "hola") == "clasico"
        assert "no disponible" in caplog.text

    def test_hibrido_on_profundo_va_a_clasico(self, monkeypatch, draft_file):
        monkeypatch.setenv("COGNIA_VELOCIDAD_HIBRIDO", "on")
        for kind in ("agente", "razonamiento", "codigo_complejo"):
            assert vel.resolve_mode(kind, "hola") == "clasico"

    def test_hibrido_on_senales_de_texto_van_a_clasico(self, monkeypatch,
                                                       draft_file):
        monkeypatch.setenv("COGNIA_VELOCIDAD_HIBRIDO", "on")
        assert vel.resolve_mode("chat", "analiza este codigo") == "clasico"
        assert vel.resolve_mode("chat", "vamos paso a paso") == "clasico"
        assert vel.resolve_mode("chat", "x" * 801) == "clasico"

    def test_hibrido_on_chat_corto_usa_mejor_disponible(self, monkeypatch,
                                                        draft_file):
        """Sin BDraft, el mejor modo rapido disponible es dspark."""
        monkeypatch.setenv("COGNIA_VELOCIDAD_HIBRIDO", "on")
        assert vel.resolve_mode("chat", "hola, como andas?") == "dspark"

    def test_hibrido_on_sin_draft_cae_a_clasico(self, tmp_path, monkeypatch):
        monkeypatch.setenv("COGNIA_VELOCIDAD_HIBRIDO", "on")
        monkeypatch.setenv("COGNIA_DRAFT_PATH",
                           str(tmp_path / "no-existe.gguf"))
        assert vel.resolve_mode("chat", "hola") == "clasico"

    def test_esfuerzo_alto_siempre_clasico(self, monkeypatch, draft_file):
        monkeypatch.setenv("COGNIA_VELOCIDAD_HIBRIDO", "on")
        for esfuerzo in ("alto", "max"):
            monkeypatch.setenv("COGNIA_ESFUERZO", esfuerzo)
            assert vel.resolve_mode("chat", "hola") == "clasico"
        # esfuerzo normal no bloquea el modo rapido
        monkeypatch.setenv("COGNIA_ESFUERZO", "normal")
        assert vel.resolve_mode("chat", "hola") == "dspark"

    def test_esfuerzo_alto_gana_incluso_con_modo_fijo(self, monkeypatch,
                                                      draft_file):
        with patch.object(pp, "_server_running", return_value=False):
            vel.set_mode("dspark")
        monkeypatch.setenv("COGNIA_ESFUERZO", "alto")
        assert vel.resolve_mode("chat", "hola") == "clasico"


# ---------------------------------------------------------------------------
# velocity_summary()
# ---------------------------------------------------------------------------

class TestSummary:
    def test_contiene_modos_y_estados(self, draft_file):
        out = vel.velocity_summary()
        for name in vel.MODOS:
            assert name in out
        assert "[ACTIVO]" in out           # clasico default
        assert "[disponible]" in out       # dspark con draft presente
        assert "no disponible" in out      # gemma/difusion-dspark
        assert "BDraft entrenado" in out

    def test_marca_activo_el_modo_seteado(self, draft_file):
        with patch.object(pp, "_server_running", return_value=False):
            vel.set_mode("dspark")
        out = vel.velocity_summary()
        linea_dspark = next(l for l in out.splitlines()
                            if l.strip().startswith("dspark"))
        assert "[ACTIVO]" in linea_dspark

    def test_estado_hibrido_y_nota_esfuerzo(self, monkeypatch):
        out = vel.velocity_summary()
        assert "Hibrido" in out and "OFF" in out
        assert "esfuerzo" in out.lower()
        monkeypatch.setenv("COGNIA_VELOCIDAD_HIBRIDO", "on")
        assert "ON" in vel.velocity_summary()


# ---------------------------------------------------------------------------
# node/llama_backend.py: cmd del server con draft (estilo
# test_server_backend_builds_cmd_with_env_tunables)
# ---------------------------------------------------------------------------

class TestServerCmdConDraft:
    def _build_cmd(self, tmp_path, monkeypatch):
        fake_gguf = tmp_path / "model.gguf"
        fake_gguf.touch()
        fake_bin = tmp_path / "llama-server.exe"
        fake_bin.touch()
        monkeypatch.setenv("LLAMA_SERVER_PATH", str(fake_bin))

        from node.llama_backend import _LlamaServerBackend
        captured = {}

        def fake_popen(cmd, **kwargs):
            captured["cmd"] = cmd
            return MagicMock(pid=1234)

        with (
            patch.object(_LlamaServerBackend, "_ping",
                         MagicMock(side_effect=[False, True])),
            patch("node.llama_backend.subprocess.Popen",
                  side_effect=fake_popen),
        ):
            _LlamaServerBackend(fake_gguf, port=18089)
        return captured["cmd"]

    def test_cmd_incluye_draft_cuando_env_seteada(self, tmp_path, monkeypatch):
        draft = tmp_path / "draft.gguf"
        draft.touch()
        monkeypatch.setenv("LLAMA_DRAFT_GGUF_PATH", str(draft))
        monkeypatch.setenv("LLAMA_N_GPU_LAYERS", "99")
        cmd = self._build_cmd(tmp_path, monkeypatch)
        assert cmd[cmd.index("--model-draft") + 1] == str(draft)
        # b10066: sin --spec-type draft-simple, --model-draft es no-op silencioso
        assert cmd[cmd.index("--spec-type") + 1] == "draft-simple"
        assert cmd[cmd.index("--gpu-layers-draft") + 1] == "99"
        assert cmd[cmd.index("--spec-draft-n-max") + 1] == "8"
        assert cmd[cmd.index("--spec-draft-n-min") + 1] == "1"
        assert cmd[cmd.index("--spec-draft-p-min") + 1] == "0.75"

    def test_cmd_sin_draft_cuando_env_ausente(self, tmp_path, monkeypatch):
        monkeypatch.delenv("LLAMA_DRAFT_GGUF_PATH", raising=False)
        cmd = self._build_cmd(tmp_path, monkeypatch)
        assert "--model-draft" not in cmd
        assert "--spec-type" not in cmd

    def test_cmd_sin_draft_cuando_archivo_no_existe(self, tmp_path,
                                                    monkeypatch):
        monkeypatch.setenv("LLAMA_DRAFT_GGUF_PATH",
                           str(tmp_path / "fantasma.gguf"))
        cmd = self._build_cmd(tmp_path, monkeypatch)
        assert "--model-draft" not in cmd

    def test_set_mode_dspark_termina_en_el_cmd(self, tmp_path, monkeypatch,
                                               draft_file):
        """Integracion velocity -> llama_backend: set_mode('dspark') deja la
        env que el proximo arranque del server convierte en flags."""
        with patch.object(pp, "_server_running", return_value=False):
            vel.set_mode("dspark")
        cmd = self._build_cmd(tmp_path, monkeypatch)
        assert cmd[cmd.index("--model-draft") + 1] == str(draft_file)
