"""
tests/test_experts_registry.py
Tests para cognia/experts/registry.py — registro persistente de expertos.

Sin red ni modelos reales: COGNIA_EXPERTS_DIR apunta a tmp_path
(mismo patron que tests/test_fleet.py con COGNIA_MODELS_DIR).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cognia.experts import (  # noqa: E402
    BUILTIN_EXPERTS,
    add_expert,
    get_expert,
    load_registry,
    registry_path,
    remove_expert,
    render_modelos_table,
    set_enabled,
)

_BUILTIN_IDS = [
    "cerebro-principal", "programador", "portero-draft",
    "razonador-logos", "tecnico-techne", "comunicador-rhetor",
]


@pytest.fixture(autouse=True)
def experts_tmp(tmp_path, monkeypatch):
    """Aisla el registro en tmp_path para cada test."""
    monkeypatch.setenv("COGNIA_EXPERTS_DIR", str(tmp_path))
    yield tmp_path


class TestBuiltins:
    def test_builtin_presentes(self):
        """Sin JSON: el registro son exactamente los 6 builtin de codigo."""
        experts = load_registry()
        assert [e.id for e in experts] == _BUILTIN_IDS
        assert all(e.builtin for e in experts)
        assert all(e.enabled for e in experts)

    def test_builtin_backends_derivados_de_lo_existente(self):
        """Los gguf usan keys de node/fleet.py; los shards, logos/techne/rhetor."""
        by_id = {e.id: e for e in load_registry()}
        assert by_id["cerebro-principal"].model_key == "chat-7b"
        assert by_id["programador"].model_key == "coder-14b"
        assert by_id["portero-draft"].model_key == "coder-0.5b"
        assert all(by_id[i].backend == "gguf"
                   for i in ("cerebro-principal", "programador", "portero-draft"))
        assert by_id["razonador-logos"].model_key == "logos"
        assert by_id["tecnico-techne"].model_key == "techne"
        assert by_id["comunicador-rhetor"].model_key == "rhetor"
        assert all(by_id[i].backend == "shards"
                   for i in ("razonador-logos", "tecnico-techne", "comunicador-rhetor"))

    def test_get_expert(self):
        assert get_expert("programador").nombre == "Programador"
        assert get_expert("no-existe") is None


class TestAddRemove:
    def test_add_round_trip_persistente(self, experts_tmp):
        """add_expert escribe registry.json y una carga fresca lo ve."""
        add_expert("mistral-local", "Mistral local", "pruebas con ollama",
                   "mistral", "ollama")
        assert registry_path().is_file()
        # Carga fresca (funciones leen disco en cada llamada, sin cache)
        experts = load_registry()
        assert [e.id for e in experts] == _BUILTIN_IDS + ["mistral-local"]
        nuevo = get_expert("mistral-local")
        assert nuevo.builtin is False
        assert nuevo.backend == "ollama"
        # El JSON solo contiene el custom, no los builtin sin cambios
        raw = json.loads(registry_path().read_text(encoding="utf-8"))
        assert [d["id"] for d in raw] == ["mistral-local"]

    def test_remove_custom_persistente(self):
        add_expert("temporal", "Temporal", "de prueba", "mistral", "ollama")
        assert get_expert("temporal") is not None
        quitado = remove_expert("temporal")
        assert quitado.id == "temporal"
        assert get_expert("temporal") is None
        assert [e.id for e in load_registry()] == _BUILTIN_IDS

    def test_remove_builtin_falla_limpio(self):
        """Los builtin no se quitan: ValueError claro y registro intacto."""
        with pytest.raises(ValueError, match="fabrica"):
            remove_expert("cerebro-principal")
        assert [e.id for e in load_registry()] == _BUILTIN_IDS

    def test_remove_inexistente_falla(self):
        with pytest.raises(ValueError, match="desconocido"):
            remove_expert("fantasma")

    def test_add_id_duplicado_falla(self):
        with pytest.raises(ValueError, match="ya existe"):
            add_expert("programador", "Otro", "x", "coder-14b", "gguf")

    def test_add_slug_invalido_falla(self):
        with pytest.raises(ValueError, match="id invalido"):
            add_expert("Con Espacios", "X", "x", "m", "ollama")

    def test_add_backend_invalido_falla(self):
        with pytest.raises(ValueError, match="backend invalido"):
            add_expert("nuevo", "X", "x", "m", "vllm")


class TestEnabled:
    def test_set_enabled_builtin_round_trip(self):
        """Desactivar un builtin persiste como override y se puede revertir."""
        set_enabled("portero-draft", False)
        e = get_expert("portero-draft")     # carga fresca desde disco
        assert e.enabled is False
        assert e.builtin is True            # el override sigue siendo builtin
        set_enabled("portero-draft", True)
        assert get_expert("portero-draft").enabled is True

    def test_set_enabled_custom(self):
        add_expert("aux", "Aux", "x", "mistral", "ollama")
        set_enabled("aux", False)
        assert get_expert("aux").enabled is False

    def test_set_enabled_desconocido_falla(self):
        with pytest.raises(ValueError, match="desconocido"):
            set_enabled("fantasma", True)


class TestRender:
    _FLEET = [
        {"key": "coder-0.5b", "presente": False, "gb": 0},
        {"key": "chat-7b",    "presente": True,  "gb": 4.68},
        {"key": "coder-14b",  "presente": False, "gb": 0},
    ]

    def test_contiene_nombres_y_modelos(self):
        out = render_modelos_table(load_registry(), self._FLEET)
        # Nombres en mayusculas + dedicacion
        assert "CEREBRO PRINCIPAL -- chat general del dia a dia" in out
        assert "PROGRAMADOR" in out
        assert "RAZONADOR LOGOS" in out
        # Modelos con estado segun fleet_status
        assert "-> modelo: chat-7b [OK 4.68 GB]" in out
        assert "-> modelo: coder-14b [FALTA]" in out
        assert "-> modelo: logos [shards]" in out

    def test_custom_agrupado_despues_de_builtin(self):
        add_expert("mio", "Mi experto", "cosas mias", "mistral", "ollama")
        out = render_modelos_table(load_registry(), self._FLEET)
        assert "-- Personalizados --" in out
        assert "-> modelo: mistral [ollama]" in out
        # Builtin primero, custom despues
        assert out.index("CEREBRO PRINCIPAL") < out.index("MI EXPERTO")
        assert out.index("-- Personalizados --") < out.index("MI EXPERTO")

    def test_desactivado_marcado(self):
        set_enabled("portero-draft", False)
        out = render_modelos_table(load_registry(), self._FLEET)
        assert "PORTERO DRAFT" in out
        assert "(desactivado)" in out

    def test_sin_fleet_status_no_explota(self):
        """fleet_status=None: los gguf quedan etiquetados por backend."""
        out = render_modelos_table(load_registry(), None)
        assert "-> modelo: chat-7b [gguf]" in out


class TestRobustez:
    def test_json_corrupto_degrada_a_builtins(self, experts_tmp):
        registry_path().parent.mkdir(parents=True, exist_ok=True)
        registry_path().write_text("{esto no es json", encoding="utf-8")
        assert [e.id for e in load_registry()] == _BUILTIN_IDS

    def test_builtin_defaults_no_mutan_entre_cargas(self):
        """load_registry devuelve copias: mutar una no toca BUILTIN_EXPERTS."""
        e = load_registry()[0]
        e.enabled = False
        assert BUILTIN_EXPERTS[0].enabled is True
        assert load_registry()[0].enabled is True
