# -*- coding: utf-8 -*-
"""REGRESION 2026-08-01 (auditoria A8): el fallback a Ollama estaba muerto por
construccion: el sondeo era un 200 en /api/tags (sin leer el JSON), el modelo
default 'llama3.2' no coincidia con lo instalado ('llama3.2:3b') y cada
/api/generate daba 404 que el llamador veia como None mudo. Ahora:
- detectar_backend lee el JSON de tags y elige un modelo INSTALADO;
- tags vacio = SIN backend;
- /api/generate que no genera deja sin_backend en el audit.
"""
import pytest

import cognia.llm_local as llm_local
import cognia.backend_activo as backend_activo


@pytest.fixture(autouse=True)
def _aislar(monkeypatch, tmp_path):
    # cache del backend limpio en cada test y audit fuera de ~/.cognia
    monkeypatch.setattr(llm_local, "_backend", None)
    monkeypatch.setattr(backend_activo, "AUDIT", tmp_path / "backend_audit.jsonl")
    monkeypatch.delenv("COGNIA_LLM_URL", raising=False)
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)


def test_tags_vacio_no_es_backend(monkeypatch):
    # El caso viejo: /api/tags responde 200 (sondeo OK) pero sin modelos.
    monkeypatch.setattr(llm_local, "_sondear",
                        lambda url, ruta: ruta == "/api/tags")
    monkeypatch.setattr(llm_local, "_modelos_ollama", lambda url: [])
    assert llm_local.detectar_backend(forzar=True) is None


def test_elige_modelo_instalado_por_prefijo(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.2")   # el pedido NO instalado
    monkeypatch.setattr(llm_local, "_sondear", lambda url, ruta: False)
    monkeypatch.setattr(llm_local, "_modelos_ollama",
                        lambda url: ["llama3.2:3b", "qwen2:0.5b"])
    b = llm_local.detectar_backend(forzar=True)
    assert b["tipo"] == "ollama"
    assert b["modelo"] == "llama3.2:3b"   # el instalado con el mismo base


def test_sin_preferencia_toma_el_primero_instalado(monkeypatch):
    monkeypatch.setattr(llm_local, "_sondear", lambda url, ruta: False)
    monkeypatch.setattr(llm_local, "_modelos_ollama", lambda url: ["mistral:7b"])
    b = llm_local.detectar_backend(forzar=True)
    assert b["modelo"] == "mistral:7b"


def test_generate_404_audita_sin_backend(monkeypatch):
    monkeypatch.setattr(llm_local, "_backend",
                        {"tipo": "ollama", "url": "http://localhost:11434",
                         "modelo": "llama3.2:3b"})
    llamadas = []
    monkeypatch.setattr(backend_activo, "registrar",
                        lambda via, url, **kw: {})   # sin sondear /props real
    monkeypatch.setattr(backend_activo, "sin_backend",
                        lambda via, detalle="": llamadas.append((via, detalle)))
    monkeypatch.setattr(llm_local, "_post", lambda url, payload, timeout=120: None)
    assert llm_local.generar("hola", via="test") is None
    assert len(llamadas) == 1
    assert "/api/generate" in llamadas[0][1]
