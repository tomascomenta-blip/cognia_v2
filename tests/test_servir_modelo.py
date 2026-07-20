"""
Script para levantar el llama-server que Cognia espera encontrar.

Sin backend, Cognia degrada a sus fallbacks en silencio — el modo de fallo que
mas costo cazar la madrugada del 2026-07-20. El doctor y el bucle del agente ya
avisan ("arranca llama-server o configura COGNIA_LLM_URL"), pero no habia
ningun comando que lo hiciera: habia que recordar la ruta del binario, cual de
los .gguf y los flags.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import servir_modelo as SM


class TestEleccionDeModelo:

    def test_prefiere_el_coder_14b(self, monkeypatch):
        """Es con el que se midio todo el trabajo del repo."""
        monkeypatch.setattr(SM, "modelos", lambda: [
            Path("qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf"),
            Path("qwen2.5-coder-14b-instruct-q4_k_m-00001-of-00002.gguf"),
            Path("UIGEN-X-8B.Q8_0.gguf"),
        ])
        assert "coder-14b" in SM.elegir(None).name

    def test_busca_por_trozo_del_nombre(self, monkeypatch):
        monkeypatch.setattr(SM, "modelos", lambda: [
            Path("qwen2.5-coder-14b-instruct.gguf"),
            Path("UIGEN-X-8B.Q8_0.gguf"),
        ])
        assert SM.elegir("uigen").name == "UIGEN-X-8B.Q8_0.gguf"

    def test_no_distingue_mayusculas(self, monkeypatch):
        monkeypatch.setattr(SM, "modelos", lambda: [Path("UIGEN-X-8B.Q8_0.gguf")])
        assert SM.elegir("UIGEN") is not None

    def test_patron_que_no_casa_devuelve_None(self, monkeypatch):
        monkeypatch.setattr(SM, "modelos", lambda: [Path("qwen.gguf")])
        assert SM.elegir("noexiste") is None

    def test_sin_modelos_devuelve_None(self, monkeypatch):
        monkeypatch.setattr(SM, "modelos", lambda: [])
        assert SM.elegir(None) is None


class TestFicherosPartidos:
    """
    De un .gguf partido en varios, llama.cpp solo necesita el primero: carga el
    resto solo. Ofrecer las demas partes como si fueran modelos distintos
    confundiria al usuario.
    """

    def test_solo_ofrece_la_primera_parte(self, tmp_path, monkeypatch):
        for nombre in ("m-00001-of-00002.gguf", "m-00002-of-00002.gguf",
                       "suelto.gguf"):
            (tmp_path / nombre).write_bytes(b"x")
        monkeypatch.setattr(SM, "DIR_MODELOS", tmp_path)

        nombres = [m.name for m in SM.modelos()]
        assert "m-00001-of-00002.gguf" in nombres
        assert "m-00002-of-00002.gguf" not in nombres
        assert "suelto.gguf" in nombres


class TestNoPisaLoQueYaCorre:

    def test_detecta_un_servidor_vivo(self, monkeypatch):
        class _Resp:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *a): return False

        monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _Resp())
        assert SM.responde(8080) is True

    def test_puerto_muerto_es_False(self, monkeypatch):
        monkeypatch.setattr("urllib.request.urlopen",
                            lambda *a, **k: (_ for _ in ()).throw(OSError()))
        assert SM.responde(9099) is False


def test_sirve_en_el_puerto_que_sondea_llm_local():
    """
    Si el script sirviera en otro puerto, Cognia no lo encontraria y volveriamos
    al fallo silencioso que este script existe para evitar.
    """
    from cognia.llm_local import LLAMA_URL_DEFECTO
    assert str(SM.PUERTO) in LLAMA_URL_DEFECTO
