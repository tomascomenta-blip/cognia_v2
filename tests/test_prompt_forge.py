"""
tests/test_prompt_forge.py
Tests para cognia/experts/prompt_forge.py — generacion del prompt de
comportamiento por experto (modalidad 1 del alta).

Sin red ni modelos reales: llm_fn inyectada (nunca _llm_local) y
COGNIA_EXPERTS_DIR a tmp_path (mismo patron que test_experts_registry.py).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cognia.experts import (  # noqa: E402
    add_expert,
    experts_dir,
    get_expert,
    system_prompt_path,
)
from cognia.experts.prompt_forge import (  # noqa: E402
    _FALLBACK_SECTIONS,
    _TITULOS,
    SECCIONES,
    create_expert_with_prompt,
    forge_prompt,
)

# ~200 palabras por seccion -> 8 secciones dan ~1600 palabras.
_TEXTO_LARGO = (
    "Eres un experto dedicado y meticuloso que trabaja con rigor real. " * 20
).strip()


def _silencio(*args, **kwargs):
    pass


@pytest.fixture(autouse=True)
def experts_tmp(tmp_path, monkeypatch):
    """Aisla el directorio de expertos en tmp_path para cada test."""
    monkeypatch.setenv("COGNIA_EXPERTS_DIR", str(tmp_path))
    yield tmp_path


class TestForgePrompt:
    def test_ocho_secciones_y_encabezado(self):
        """Con llm_fn falso largo: 8 secciones '## ' + titulo principal."""
        out = forge_prompt("Chef casero", "recetas de cocina argentina",
                           "chat-7b", llm_fn=lambda p: _TEXTO_LARGO,
                           print_fn=_silencio)
        assert out.startswith("# Prompt de comportamiento: Chef casero")
        assert out.count("\n## ") == len(SECCIONES) == 8
        for key in SECCIONES:
            assert f"## {_TITULOS[key]}" in out

    def test_longitud_total_supera_800_palabras(self):
        out = forge_prompt("Chef casero", "recetas", "chat-7b",
                           llm_fn=lambda p: _TEXTO_LARGO, print_fn=_silencio)
        assert len(out.split()) > 800

    def test_llm_llamado_una_vez_por_seccion(self):
        """Genera seccion por seccion: exactamente 8 llamadas a llm_fn."""
        prompts = []

        def llm(p):
            prompts.append(p)
            return _TEXTO_LARGO

        forge_prompt("Chef", "recetas", "chat-7b", llm_fn=llm,
                     print_fn=_silencio)
        assert len(prompts) == 8
        # Cada prompt de generacion lleva el contexto del experto
        assert all("Chef" in p and "recetas" in p and "chat-7b" in p
                   for p in prompts)

    def test_llm_none_cae_a_fallback_todas(self):
        """llm_fn devuelve None: TODAS las secciones usan plantilla y el
        resultado sigue siendo valido y > 600 palabras."""
        out = forge_prompt("Chef casero", "recetas de cocina", "chat-7b",
                           llm_fn=lambda p: None, print_fn=_silencio)
        assert out.count("\n## ") == 8
        assert len(out.split()) > 600
        # Plantillas parametrizadas con nombre/dedicacion
        assert "Eres Chef casero, un experto dedicado a recetas de cocina" in out
        assert "Tomas Montes" in out  # seccion contexto_cognia

    def test_texto_corto_cae_a_fallback(self):
        """Una respuesta < 50 chars se descarta y entra la plantilla."""
        out = forge_prompt("Chef", "recetas", "chat-7b",
                           llm_fn=lambda p: "ok", print_fn=_silencio)
        assert "Eres Chef, un experto dedicado a recetas" in out
        assert len(out.split()) > 600

    def test_llm_que_lanza_cae_a_fallback(self):
        def llm(p):
            raise ConnectionError("server caido")

        out = forge_prompt("Chef", "recetas", "chat-7b", llm_fn=llm,
                           print_fn=_silencio)
        assert out.count("\n## ") == 8
        assert len(out.split()) > 600

    def test_fallbacks_cubren_todas_las_secciones(self):
        assert set(_FALLBACK_SECTIONS) == set(SECCIONES)


class TestCreateExpertWithPrompt:
    def test_escribe_md_y_registra(self, experts_tmp):
        e = create_expert_with_prompt(
            "chef-casero", "Chef casero", "recetas de cocina",
            "chat-7b", "gguf", llm_fn=lambda p: _TEXTO_LARGO,
            print_fn=_silencio)
        assert e.system_prompt_file == "chef-casero/system_prompt.md"
        ruta = experts_dir() / "chef-casero" / "system_prompt.md"
        assert ruta.is_file()
        contenido = ruta.read_text(encoding="utf-8")
        assert contenido.startswith("# Prompt de comportamiento: Chef casero")
        assert contenido.count("\n## ") == 8
        # Registrado y visible en una carga fresca
        registrado = get_expert("chef-casero")
        assert registrado is not None
        assert registrado.system_prompt_file == "chef-casero/system_prompt.md"
        assert system_prompt_path(registrado) == ruta

    def test_id_duplicado_falla_sin_forjar(self, experts_tmp):
        """Duplicado se detecta ANTES de forjar: 0 llamadas al LLM y sin
        archivo residual."""
        add_expert("chef-casero", "Chef", "recetas", "chat-7b", "gguf")
        llamadas = []

        def llm(p):
            llamadas.append(p)
            return _TEXTO_LARGO

        with pytest.raises(ValueError, match="ya existe"):
            create_expert_with_prompt("chef-casero", "Otro", "otras recetas",
                                      "chat-7b", "gguf", llm_fn=llm,
                                      print_fn=_silencio)
        assert llamadas == []
        assert not (experts_tmp / "chef-casero" / "system_prompt.md").exists()
        # El experto original queda intacto
        assert get_expert("chef-casero").nombre == "Chef"

    def test_rollback_si_add_expert_falla(self, experts_tmp, monkeypatch):
        """Si add_expert falla despues de escribir el .md (p.ej. carrera),
        el .md creado se borra."""
        def boom(*args, **kwargs):
            raise ValueError("ya existe un experto con id: chef-casero")

        monkeypatch.setattr("cognia.experts.prompt_forge.add_expert", boom)
        with pytest.raises(ValueError, match="ya existe"):
            create_expert_with_prompt("chef-casero", "Chef", "recetas",
                                      "chat-7b", "gguf",
                                      llm_fn=lambda p: _TEXTO_LARGO,
                                      print_fn=_silencio)
        assert not (experts_tmp / "chef-casero" / "system_prompt.md").exists()
        assert not (experts_tmp / "chef-casero").exists()
        assert get_expert("chef-casero") is None

    def test_id_invalido_falla_antes_de_escribir(self, experts_tmp):
        with pytest.raises(ValueError, match="id invalido"):
            create_expert_with_prompt("Con Espacios", "X", "x", "chat-7b",
                                      "gguf", llm_fn=lambda p: _TEXTO_LARGO,
                                      print_fn=_silencio)
        assert list(experts_tmp.iterdir()) == []

    def test_backend_invalido_falla_antes_de_escribir(self, experts_tmp):
        with pytest.raises(ValueError, match="backend invalido"):
            create_expert_with_prompt("nuevo", "X", "x", "m", "vllm",
                                      llm_fn=lambda p: _TEXTO_LARGO,
                                      print_fn=_silencio)
        assert list(experts_tmp.iterdir()) == []
