# -*- coding: utf-8 -*-
"""
tests/test_fleet_nativo.py — experto_nativo() y la clave nativo_compatible
==========================================================================
Plan LoRA Qwythos 2026-08-09 (ola 1, agente E). Sin GPU, sin server: los
impl se construyen con object.__new__ (el __init__ real pingea puertos).

POR QUE estos tests: el guard A3 de cli.py (ola 2) va a activar en regimen
nativo SOLO el adapter que el manifest marque nativo_compatible: true. Un
manifest viejo sin la clave tiene que comportarse EXACTO como hoy (ningun
experto en nativo) — la regresion peligrosa seria activar el experto
'accion' del 3B (entrenado contra el marco ACCION) en el camino nativo.
"""
from __future__ import annotations

import json

import pytest

from node.llama_backend import (LlamaBackend, _LlamaServerBackend,
                                _fleet_manifest, experto_del_guard)


# ── infraestructura ──────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _aisla_loras_dir(tmp_path_factory, monkeypatch):
    """Sin esto, _fleet_manifest caeria al adapters.json REAL del usuario en
    ~/.cognia/loras y el resultado dependeria de la maquina, no del test."""
    vacio = tmp_path_factory.mktemp("loras_vacio")
    monkeypatch.setenv("COGNIA_LORAS_DIR", str(vacio))
    monkeypatch.delenv("LLAMA_LORA_PATH", raising=False)


def _prepara(tmp_path, entradas):
    """Escribe un gguf falso + adapters.json con `entradas` al lado.

    Cada entrada: {"name": str, ...claves extra tal cual (nativo_compatible,
    etc.)}. Crea el archivo del adapter salvo que "sin_archivo" sea True.
    Devuelve la ruta del gguf (lo que _fleet_manifest recibe).
    """
    gguf = tmp_path / "modelo.gguf"
    gguf.write_bytes(b"GGUF-fake")
    lista = []
    for e in entradas:
        nombre = e["name"]
        archivo = tmp_path / f"{nombre}.gguf"
        if not e.get("sin_archivo"):
            archivo.write_bytes(b"lora-fake")
        item = {"name": nombre, "file": archivo.name}
        for k, v in e.items():
            if k not in ("name", "sin_archivo"):
                item[k] = v
        lista.append(item)
    (tmp_path / "adapters.json").write_text(
        json.dumps({"adapters": lista}), encoding="utf-8")
    return gguf


def _impl(fleet_names, gguf):
    b = object.__new__(_LlamaServerBackend)
    b._fleet_names = list(fleet_names)
    b._gguf_path = gguf
    return b


# ── _fleet_manifest: la clave nueva y la retrocompatibilidad ────────────────

def test_manifest_expone_nativo_compatible(tmp_path):
    gguf = _prepara(tmp_path, [{"name": "accion"},
                               {"name": "tools", "nativo_compatible": True}])
    m = _fleet_manifest(gguf)
    assert [a["name"] for a in m] == ["accion", "tools"]
    assert m[0]["nativo_compatible"] is False
    assert m[1]["nativo_compatible"] is True


def test_manifest_viejo_intacto(tmp_path):
    """Un adapters.json pre-2026-08-09 (solo name/file) sigue parseando igual
    y NINGUNA entrada queda marcada como nativa."""
    gguf = _prepara(tmp_path, [{"name": "accion"}])
    m = _fleet_manifest(gguf)
    assert len(m) == 1
    assert m[0]["name"] == "accion"
    assert m[0]["path"].is_file()
    assert m[0]["nativo_compatible"] is False


def test_manifest_nativo_solo_true_literal(tmp_path):
    """Solo el booleano true marca: "si"/1/"true" NO (opt-in estricto — un
    manifest editado a mano con un valor raro no debe activar nada)."""
    gguf = _prepara(tmp_path, [{"name": "a", "nativo_compatible": "true"},
                               {"name": "b", "nativo_compatible": 1},
                               {"name": "c", "nativo_compatible": False}])
    assert all(a["nativo_compatible"] is False for a in _fleet_manifest(gguf))


# ── experto_nativo() del impl server ────────────────────────────────────────

def test_experto_nativo_devuelve_el_marcado(tmp_path):
    gguf = _prepara(tmp_path, [{"name": "accion"},
                               {"name": "tools", "nativo_compatible": True}])
    assert _impl(["accion", "tools"], gguf).experto_nativo() == "tools"


def test_experto_nativo_manifest_viejo_da_none(tmp_path):
    gguf = _prepara(tmp_path, [{"name": "accion"}])
    assert _impl(["accion"], gguf).experto_nativo() is None


def test_experto_nativo_primer_marcado_gana(tmp_path):
    gguf = _prepara(tmp_path, [{"name": "t1", "nativo_compatible": True},
                               {"name": "t2", "nativo_compatible": True}])
    assert _impl(["t1", "t2"], gguf).experto_nativo() == "t1"


def test_experto_nativo_sin_fleet_da_none(tmp_path):
    """Fleet OFF (server adoptado con mismatch, o sin adapters cargados):
    devolver un nombre que activate_expert rechazaria seria fallo silencioso
    aguas abajo."""
    gguf = _prepara(tmp_path, [{"name": "tools", "nativo_compatible": True}])
    assert _impl([], gguf).experto_nativo() is None


def test_experto_nativo_marcado_no_cargado_se_filtra(tmp_path):
    """Marcado en el manifest pero ausente del fleet vivo: se ignora (con
    warning) y se sigue buscando el siguiente marcado."""
    gguf = _prepara(tmp_path, [{"name": "fantasma", "nativo_compatible": True},
                               {"name": "tools", "nativo_compatible": True}])
    assert _impl(["tools"], gguf).experto_nativo() == "tools"
    assert _impl(["otro"], gguf).experto_nativo() is None


def test_experto_nativo_archivo_inexistente_salteado(tmp_path):
    """La entrada sin archivo ya la saltea _fleet_manifest: no puede volver
    como experto nativo aunque este marcada."""
    gguf = _prepara(tmp_path, [{"name": "roto", "nativo_compatible": True,
                                "sin_archivo": True}])
    assert _fleet_manifest(gguf) == []
    assert _impl(["roto"], gguf).experto_nativo() is None


def test_experto_nativo_sin_manifest_da_none(tmp_path):
    gguf = tmp_path / "solo.gguf"
    gguf.write_bytes(b"GGUF-fake")
    assert _impl(["accion"], gguf).experto_nativo() is None


# ── fachada LlamaBackend ─────────────────────────────────────────────────────

def test_facade_delega_en_el_impl(tmp_path):
    gguf = _prepara(tmp_path, [{"name": "tools", "nativo_compatible": True}])
    be = LlamaBackend(_impl(["tools"], gguf))
    assert be.experto_nativo() == "tools"
    assert be.fleet_experts == ["tools"]


def test_facade_impl_sin_soporte_da_none():
    """Impl in-process (llama-cpp-python) no tiene experto_nativo: la fachada
    devuelve None en vez de reventar (mismo criterio que activate_expert)."""
    class _ImplPelado:
        pass
    assert LlamaBackend(_ImplPelado()).experto_nativo() is None


# ── experto_del_guard: la logica pura del guard A3 de cli.py ────────────────

def test_guard_legacy_activa_accion():
    assert experto_del_guard(False, None) == "accion"
    # aunque haya un experto nativo marcado, legacy sigue en 'accion'
    assert experto_del_guard(False, "tools") == "accion"


def test_guard_nativo_activa_el_marcado():
    assert experto_del_guard(True, "tools") == "tools"


def test_guard_nativo_sin_marcado_no_activa_nada():
    """El comportamiento de HOY: en nativo, sin flag en el manifest, ningun
    experto se activa (el 'accion' del 3B queda bloqueado en nativo)."""
    assert experto_del_guard(True, None) is None
    assert experto_del_guard(True, "") is None
