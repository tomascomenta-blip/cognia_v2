# -*- coding: utf-8 -*-
"""Regresion de la auditoria 2026-08-01 (area A7: doctor e instalacion).

Cuatro agujeros del mismo patron — el doctor aprobaba sin verificar:

1. check_inference_speed daba [OK] midiendo tok/s de la ruta de shards NPZ
   que genera BASURA (768 tokens de ruido): contaba tokens, no leia el texto.
2. Ni el wrapper scripts/cognia_doctor.py ni main() llamaban apply_config():
   el doctor corria ciego a ~/.cognia/config.env y dio "Todo en orden" sobre
   un sistema DEGRADADO.
3. check_ollama declaraba OK con un 200 pelado en /api/tags aunque
   /api/generate diera 404 (tags vacio = cero modelos instalados).
4. cognia.__version__ no existia; cognia_update.py migraba el DB del REPO en
   vez del de ~/.cognia y pip --upgrade rompia pins.
"""

import io
import contextlib
import sys
import types

import pytest

import cognia.doctor as D


def _capture(fn):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ret = fn()
    return ret, buf.getvalue()


# ---------------------------------------------------------------- inferencia

class _FakeResult:
    def __init__(self, text, mode, toks=10):
        self.text = text
        self.mode = mode
        self.tokens_generated = toks


class _FakeOrch:
    """Orquestador de mentira: infer() devuelve lo que le inyecte el test."""
    resultado = _FakeResult("OK OK OK", "llama.cpp")

    def __init__(self, *a, **k):
        pass

    def _shards_available(self):
        return True

    def _try_load_llama(self):
        pass

    def infer(self, *a, **k):
        return self.resultado


@pytest.fixture
def orch_falso(monkeypatch):
    mod = types.ModuleType("shattering.orchestrator")
    mod.ShatteringOrchestrator = _FakeOrch
    monkeypatch.setitem(sys.modules, "shattering.orchestrator", mod)
    monkeypatch.setattr(D, "_shard_dir", lambda: "hay_shards")
    monkeypatch.setattr(D, "_manifest_path", lambda: "manifest.json")
    return _FakeOrch


class TestInferenciaConMarcador:

    def test_basura_en_gguf_es_FALLO(self, orch_falso):
        """El bug exacto: 768 tokens de ruido salian [OK] por tener tok/s."""
        orch_falso.resultado = _FakeResult("瑜瑜瑜" * 20, "llama.cpp", 768)
        ret, out = _capture(D.check_inference_speed)
        assert ret is False
        assert "[FAIL]" in out

    def test_ok_real_pasa(self, orch_falso):
        orch_falso.resultado = _FakeResult("OK OK OK OK", "llama.cpp", 12)
        ret, out = _capture(D.check_inference_speed)
        assert ret is True
        assert "[OK]" in out

    def test_ruta_npz_no_da_OK_verde(self, orch_falso):
        """mode != llama.cpp (shards NPZ / simulacion) → WARN, nunca [OK]."""
        orch_falso.resultado = _FakeResult("OK", "local", 5)
        ret, out = _capture(D.check_inference_speed)
        assert "[WARN]" in out
        assert "[OK]" not in out


# --------------------------------------------------------------- apply_config

class TestDoctorLeeConfig:

    def test_run_all_llama_apply_config(self):
        """El wrapper y /doctor entran por main()/run_all(), no por __main__:
        apply_config tiene que estar DENTRO de run_all o el doctor sondea sin
        LLAMA_SERVER_URL ni el modelo de config.env."""
        import inspect
        src = inspect.getsource(D.run_all)
        assert "apply_config" in src


# -------------------------------------------------------------------- ollama

class _FakeResp:
    def __init__(self, status, body):
        self.status = status
        self._body = body

    def read(self):
        return self._body


class TestOllamaValidaTags:

    def test_200_sin_json_de_modelos_no_es_OK(self, monkeypatch):
        """Un proxy u otro servicio en el 11434 tambien devuelve 200."""
        monkeypatch.setattr(D.urllib.request, "urlopen",
                            lambda *a, **k: _FakeResp(200, b"<html>hola</html>"))
        ret, out = _capture(D.check_ollama)
        assert "[WARN]" in out and "[OK]" not in out

    def test_tags_vacio_no_es_OK(self, monkeypatch):
        """Ollama sin modelos: /api/tags 200 con lista vacia, /api/generate 404."""
        monkeypatch.setattr(D.urllib.request, "urlopen",
                            lambda *a, **k: _FakeResp(200, b'{"models": []}'))
        ret, out = _capture(D.check_ollama)
        assert "[WARN]" in out and "sin modelos" in out

    def test_tags_con_modelos_es_OK(self, monkeypatch):
        monkeypatch.setattr(
            D.urllib.request, "urlopen",
            lambda *a, **k: _FakeResp(200, b'{"models": [{"name": "llama3.2:3b"}]}'))
        ret, out = _capture(D.check_ollama)
        assert "[OK]" in out and "llama3.2:3b" in out


# ------------------------------------------------------- cableado del doctor

class TestCableado:

    def test_run_all_incluye_los_checks_nuevos(self):
        import inspect
        src = inspect.getsource(D.run_all)
        assert "check_flota" in src
        assert "check_backend_audit" in src
        assert "check_fleet30" in src

    def test_backend_audit_reporta_degradados(self, monkeypatch, tmp_path):
        import datetime
        home = tmp_path / "home"
        (home / ".cognia").mkdir(parents=True)
        t = datetime.datetime.now().isoformat(timespec="seconds")
        (home / ".cognia" / "backend_audit.jsonl").write_text(
            '{"t": "%s", "via": "cli.fast_path.sin_llama", "degradado": true}\n'
            'linea corrupta no-json\n' % t, encoding="utf-8")
        monkeypatch.setattr(D.os.path, "expanduser", lambda p: str(home))
        ret, out = _capture(D.check_backend_audit)
        assert "[WARN]" in out and "DEGRADADO" in out


# ------------------------------------------------------- version del paquete

class TestVersion:

    def test_version_existe_y_es_la_del_producto(self):
        import cognia
        assert hasattr(cognia, "__version__")
        # En este checkout sale de pyproject.toml; instalada, de la metadata.
        assert cognia.__version__ not in ("", "dev")


# ------------------------------------------------------------- cognia_update

class TestUpdateDefaults:

    def _src(self):
        from pathlib import Path
        p = Path(D.__file__).resolve().parent.parent / "scripts" / "cognia_update.py"
        return p.read_text(encoding="utf-8")

    def test_db_default_es_el_del_usuario(self):
        src = self._src()
        assert '".cognia", "cognia_memory.db"' in src

    def test_pip_sin_upgrade(self):
        """--upgrade subia TODAS las deps aunque requirements estuviera
        satisfecho, rompiendo pins de transitivas probadas."""
        src = self._src()
        assert '"--upgrade"' not in src
