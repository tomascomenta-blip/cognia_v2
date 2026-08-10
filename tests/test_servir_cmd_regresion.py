"""
Regresion de la ola 2 (I2): los flags aditivos de servir_modelo.py
(--pid-file, --ctk/--ctv, --fit-off) y servir_vlm.py (--pid-file) NO deben
cambiar ni un byte del comando armado cuando NO se usan. construir_cmd() se
factorizo exactamente para poder afirmar esto en un test.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import servir_modelo as SM
from scripts import servir_vlm as SV

# El comando historico EXACTO (pre-ola-2) para exe/modelo/puerto/ctx dados.
_BASE = ["llama-server.exe", "--model", "m.gguf", "--port", "8080",
         "--ctx-size", "8192", "--parallel", "1",
         "--n-gpu-layers", "99", "--flash-attn", "on", "--jinja"]


class TestConstruirCmd:

    def test_sin_flags_byte_identico_al_historico(self):
        cmd = SM.construir_cmd(Path("llama-server.exe"), Path("m.gguf"),
                               8080, 8192)
        assert cmd == _BASE

    def test_flags_aditivos_van_al_final_sin_perturbar_la_base(self):
        cmd = SM.construir_cmd(Path("llama-server.exe"), Path("m.gguf"),
                               8080, 8192, ctk="q8_0", ctv="q4_0",
                               fit_off=True)
        assert cmd[:len(_BASE)] == _BASE
        assert cmd[len(_BASE):] == ["--cache-type-k", "q8_0",
                                    "--cache-type-v", "q4_0",
                                    "--fit", "off"]

    def test_ctk_solo_no_arrastra_ctv(self):
        cmd = SM.construir_cmd("e", "m", 8080, 8192, ctk="f16")
        assert "--cache-type-k" in cmd and "--cache-type-v" not in cmd

    def test_fit_off_agrega_fit_off(self):
        cmd = SM.construir_cmd("e", "m", 8080, 8192, fit_off=True)
        i = cmd.index("--fit")
        assert cmd[i + 1] == "off"

    def test_tupla_de_caches_b10066(self):
        # La tupla congelada del plan: cualquier otro valor muere en argparse.
        assert SM.CACHES_KV == ("f32", "f16", "bf16", "q8_0", "q4_0",
                                "q4_1", "iq4_nl", "q5_0", "q5_1")

    def test_cache_invalido_revienta_antes_de_lanzar(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv",
                            ["servir_modelo.py", "--ctk", "q3_k"])
        with pytest.raises(SystemExit) as e:
            SM.main()
        assert e.value.code == 2       # argparse: choices invalido
        assert "q3_k" in capsys.readouterr().err


class _ProcFalso:
    pid = 4242

    def poll(self):
        return None


class TestPidFile:

    def test_servir_modelo_escribe_el_pid(self, tmp_path, monkeypatch):
        pidfile = tmp_path / "cerebro.pid"
        monkeypatch.setattr(SM, "estado", lambda *a, **k: "ausente")
        monkeypatch.setattr(SM, "binario",
                            lambda: Path("llama-server.exe"))
        monkeypatch.setattr(SM, "elegir", lambda p: Path("m.gguf"))
        monkeypatch.setattr(SM, "modelos", lambda: [])
        monkeypatch.setattr(SM, "responde", lambda *a, **k: True)
        monkeypatch.setattr(SM.subprocess, "Popen",
                            lambda *a, **k: _ProcFalso())
        # el chequeo /props usa urlopen: que falle (esta en try/except pass)
        monkeypatch.setattr("urllib.request.urlopen",
                            lambda *a, **k: (_ for _ in ()).throw(OSError()))
        monkeypatch.setattr(sys, "argv",
                            ["servir_modelo.py", "--sin-draft",
                             "--pid-file", str(pidfile)])
        assert SM.main() == 0
        assert pidfile.read_text(encoding="utf-8") == "4242"

    def test_servir_modelo_sin_pid_file_no_escribe_nada(self, tmp_path,
                                                        monkeypatch):
        monkeypatch.setattr(SM, "estado", lambda *a, **k: "ausente")
        monkeypatch.setattr(SM, "binario",
                            lambda: Path("llama-server.exe"))
        monkeypatch.setattr(SM, "elegir", lambda p: Path("m.gguf"))
        monkeypatch.setattr(SM, "modelos", lambda: [])
        monkeypatch.setattr(SM, "responde", lambda *a, **k: True)
        monkeypatch.setattr(SM.subprocess, "Popen",
                            lambda *a, **k: _ProcFalso())
        monkeypatch.setattr("urllib.request.urlopen",
                            lambda *a, **k: (_ for _ in ()).throw(OSError()))
        monkeypatch.setattr(sys, "argv", ["servir_modelo.py", "--sin-draft"])
        assert SM.main() == 0
        assert list(tmp_path.iterdir()) == []

    def test_servir_vlm_escribe_el_pid(self, tmp_path, monkeypatch):
        pidfile = tmp_path / "vlm.pid"
        # responde: False en el pre-chequeo (no hay VLM), True al esperar
        respuestas = iter([False, True, True, True])
        monkeypatch.setattr(SV, "responde",
                            lambda *a, **k: next(respuestas))
        monkeypatch.setattr(SV, "binario",
                            lambda: Path("llama-server.exe"))
        monkeypatch.setattr(SV, "elegir",
                            lambda p: (Path("vl.gguf"), Path("mmproj.gguf")))
        monkeypatch.setattr(SV.subprocess, "Popen",
                            lambda *a, **k: _ProcFalso())
        monkeypatch.setattr(sys, "argv",
                            ["servir_vlm.py", "--pid-file", str(pidfile)])
        assert SV.main() == 0
        assert pidfile.read_text(encoding="utf-8") == "4242"
