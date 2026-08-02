"""
tests/test_model_selector.py — Selector de modelos del CLI (2026-08-01).

Bugs cubiertos:
  1. MODEL_GGUF_REGISTRY estatico desincronizado del disco: /modelo listaba
     solo 3b/7b (ambos [NO]) y no se podia cambiar a NADA aunque hubiera 14
     GGUFs servibles en ~/.cognia/models. Fix: discover_gguf_registry().
  2. El dispatch del REPL mandaba /modelo al handler de EXPERTOS
     (_slash_modelos): la rama real de /modelo era codigo muerto.
  3. servir_flota.py no tenia modo "solo" (un unico modelo que hace todo).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shattering.model_constants import discover_gguf_registry, match_gguf_key


def _touch(d: Path, nombre: str) -> Path:
    p = d / nombre
    p.write_bytes(b"GGUF")
    return p


class TestDiscoverGgufRegistry:

    def test_lista_los_gguf_reales(self, tmp_path, monkeypatch):
        monkeypatch.setenv("COGNIA_MODELS_DIR", str(tmp_path))
        _touch(tmp_path, "Un-Modelo-9B.Q4_K.gguf")
        _touch(tmp_path, "gpt-oss-20b-MXFP4.gguf")
        reg = discover_gguf_registry()
        assert "un-modelo-9b.q4_k" in reg
        assert "gpt-oss-20b-mxfp4" in reg
        assert Path(reg["gpt-oss-20b-mxfp4"]).is_file()

    def test_excluye_proyectores_mmproj(self, tmp_path, monkeypatch):
        monkeypatch.setenv("COGNIA_MODELS_DIR", str(tmp_path))
        _touch(tmp_path, "Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf")
        _touch(tmp_path, "mmproj-Qwen2.5-VL-3B-Instruct-f16.gguf")
        reg = discover_gguf_registry()
        assert not any(k.startswith("mmproj-") for k in reg)
        assert "qwen2.5-vl-3b-instruct-q4_k_m" in reg

    def test_multiparte_solo_la_primera_y_sin_sufijo(self, tmp_path, monkeypatch):
        monkeypatch.setenv("COGNIA_MODELS_DIR", str(tmp_path))
        _touch(tmp_path, "coder-14b-q4_k_m-00001-of-00002.gguf")
        _touch(tmp_path, "coder-14b-q4_k_m-00002-of-00002.gguf")
        reg = discover_gguf_registry()
        assert list(reg) == ["coder-14b-q4_k_m"]
        assert reg["coder-14b-q4_k_m"].endswith("00001-of-00002.gguf")

    def test_directorio_inexistente_no_revienta(self, tmp_path, monkeypatch):
        monkeypatch.setenv("COGNIA_MODELS_DIR", str(tmp_path / "no-existe"))
        assert discover_gguf_registry() == {}

    def test_un_gguf_nuevo_aparece_sin_tocar_codigo(self, tmp_path, monkeypatch):
        """El caso Qwythos: soltar el GGUF en la carpeta basta."""
        monkeypatch.setenv("COGNIA_MODELS_DIR", str(tmp_path))
        assert discover_gguf_registry() == {}
        _touch(tmp_path, "Huihui-Qwythos-9B-abliterated-Q4_K.gguf")
        reg = discover_gguf_registry()
        assert match_gguf_key("qwythos", reg) == ["huihui-qwythos-9b-abliterated-q4_k"]


class TestMatchGgufKey:

    REG = {
        "gpt-oss-20b-mxfp4": "x",
        "qwen2.5-coder-14b": "y",
        "qwen2.5-7b": "z",
    }

    def test_exacta_gana(self):
        assert match_gguf_key("qwen2.5-7b", self.REG) == ["qwen2.5-7b"]

    def test_substring_unico(self):
        assert match_gguf_key("gpt-oss", self.REG) == ["gpt-oss-20b-mxfp4"]

    def test_substring_ambiguo_devuelve_todas(self):
        assert len(match_gguf_key("qwen", self.REG)) == 2

    def test_sin_match(self):
        assert match_gguf_key("llama3", self.REG) == []

    def test_case_insensitive(self):
        assert match_gguf_key("GPT-OSS", self.REG) == ["gpt-oss-20b-mxfp4"]


class TestFlotaSolo:

    def test_combo_solo_existe(self):
        from scripts import servir_flota as SF
        assert "solo" in SF.COMBOS
        script, args = SF.COMBOS["solo"][0]
        assert script == "servir_modelo.py"
        assert "--sin-draft" in args

    def test_dispatch_modelo_no_cae_en_expertos(self):
        """Regresion bug 2: /modelo tiene que llegar a _slash_modelo, no al
        usage de /modelos. Se verifica sobre el fuente: la rama de /modelos
        no debe capturar tambien /modelo."""
        src = (Path(__file__).resolve().parent.parent
               / "cognia" / "cli.py").read_text(encoding="utf-8")
        malo = 'raw == "/modelos" or raw.startswith("/modelos ") \\\n                or raw == "/modelo"'
        assert malo not in src
