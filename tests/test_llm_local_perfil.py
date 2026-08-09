# -*- coding: utf-8 -*-
"""Perfil barato por nombre del GGUF servido (obra 2026-08-09, WP4 / A8).

REGRESION que motiva esto: el fast-path del chat desviaba turnos al 0.5B/4B
(speech_cascade / fleet_router) y pegaba CoT dirigido de 3B aunque el server
sirviera gpt-oss-20b — el turno lo respondia un modelo menor SIN decirlo
(EVIDENCIA_BASELINE 2026-08-09). Estos helpers son el guard: deteccion
POSITIVA por nombre, sin senal = comportamiento historico intacto.
"""
import pytest

import cognia.backend_activo as backend_activo
import cognia.llm_local as llm_local
from cognia.llm_local import (
    _tamano_b,
    es_modelo_chico,
    es_razonador_grande,
    nombre_modelo_servido,
    presupuesto_chat,
)


class TestTamano:
    def test_extrae_tamano_del_nombre(self):
        assert _tamano_b("gpt-oss-20b-MXFP4.gguf") == 20.0
        assert _tamano_b("qwen2.5-coder-3b-q4_k_m.gguf") == 3.0
        assert _tamano_b("qwen2.5-0.5b-instruct-q8_0.gguf") == 0.5
        assert _tamano_b("Qwythos-9B-Q4_K_M.gguf") == 9.0

    def test_21b_no_matchea_1b(self):
        # El substring pelado ('1b' in nombre) clasificaba 21b como chico.
        assert _tamano_b("modelo-21b.gguf") == 21.0

    def test_sin_tamano_devuelve_none(self):
        assert _tamano_b("mistral-nemo.gguf") is None
        assert _tamano_b("") is None

    def test_version_no_es_tamano(self):
        # 'qwen2.5' no debe leerse como 2.5B: el numero va pegado a la b.
        assert _tamano_b("qwen2.5-coder-14b.gguf") == 14.0


class TestClasificacion:
    def test_gpt_oss_20b_es_razonador_grande(self):
        # EL caso de la evidencia baseline: el 20B recibia desvios al 0.5B.
        assert es_razonador_grande("gpt-oss-20b-MXFP4.gguf")
        assert not es_modelo_chico("gpt-oss-20b-MXFP4.gguf")

    def test_flota_grande_por_tamano(self):
        assert es_razonador_grande("Qwythos-9B-Q4_K_M.gguf")
        assert es_razonador_grande("qwen2.5-coder-14b-instruct-q4_k_m.gguf")

    def test_chicos_siguen_chicos(self):
        # El comportamiento historico (3B + cascada/stepwise) queda intacto.
        for n in ("qwen2.5-coder-3b-q4_k_m.gguf",
                  "qwen2.5-0.5b-instruct-q8_0.gguf",
                  "qwen3-4b-q4.gguf"):
            assert es_modelo_chico(n), n
            assert not es_razonador_grande(n), n

    def test_tamano_declarado_gana_al_token_de_familia(self):
        # Un 4B 'thinking' es chico: el tamano manda sobre la familia.
        assert not es_razonador_grande("qwen3-4b-thinking-q4.gguf")

    def test_familia_razonadora_sin_tamano(self):
        assert es_razonador_grande("qwq-32b-preview.gguf")
        assert es_razonador_grande("gpt-oss-safetensors.gguf")

    def test_sin_senal_no_activa_el_guard(self):
        # /props caido o nombre raro: deteccion positiva o nada.
        assert not es_razonador_grande("")
        assert not es_razonador_grande("desconocido")


class TestPresupuestoChat:
    def test_razonador_sube_al_piso(self):
        # medio=1024 muere en finish=length con el 20B pensando ("9 bugs
        # identicos" de la memoria: el presupuesto cubre PENSAMIENTO+respuesta).
        assert presupuesto_chat(1024, True) == 4096

    def test_razonador_no_recorta_presupuestos_altos(self):
        assert presupuesto_chat(5000, True) == 5000

    def test_chico_conserva_el_nivel_de_esfuerzo(self):
        assert presupuesto_chat(1024, False) == 1024
        assert presupuesto_chat(512, False) == 512


class _BackendFalso:
    """Forma minima del LlamaBackend real: _impl con _base y _gguf_path."""

    class _Impl:
        pass

    def __init__(self, base, gguf=None):
        self._impl = self._Impl()
        self._impl._base = base
        self._impl._gguf_path = gguf

    @property
    def gguf_path(self):
        return self._impl._gguf_path


class TestNombreModeloServido:
    @pytest.fixture(autouse=True)
    def _aislar(self, monkeypatch):
        monkeypatch.setattr(backend_activo, "_props_cache", {})
        monkeypatch.setattr(llm_local, "_backend", None)

    def test_props_manda_sobre_gguf_path(self, monkeypatch):
        """Un server ADOPTADO conserva el _gguf_path del objeto, no lo que
        sirve (la averia historica :8088): /props es la fuente primaria."""
        url = "http://127.0.0.1:8080"
        backend_activo._props_cache[url] = {
            "modelo": "gpt-oss-20b-MXFP4.gguf", "n_ctx": 16384, "puerto": 8080}
        b = _BackendFalso(url, gguf="C:/modelos/qwen2.5-coder-3b.gguf")
        assert nombre_modelo_servido(b) == "gpt-oss-20b-MXFP4.gguf"

    def test_sin_props_cae_al_gguf_path(self, monkeypatch):
        url = "http://127.0.0.1:9999"
        backend_activo._props_cache[url] = {}    # /props no respondio
        b = _BackendFalso(url, gguf="C:/modelos/qwen2.5-coder-3b.gguf")
        assert nombre_modelo_servido(b) == "qwen2.5-coder-3b.gguf"

    def test_sin_nada_devuelve_vacio(self, monkeypatch):
        monkeypatch.setattr(llm_local, "detectar_backend",
                            lambda forzar=False: None)
        b = _BackendFalso("", gguf=None)
        b._impl._base = ""
        assert nombre_modelo_servido(b) == ""
