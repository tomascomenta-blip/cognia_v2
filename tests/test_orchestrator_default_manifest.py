# -*- coding: utf-8 -*-
"""Regresión: Orchestrator() sin manifest usa el empaquetado (bug producto
instalado 2026-07-08: 4 call-sites del CLI lo crean pelado y fuera del repo
moría con ValueError → '(el agente no pudo iniciar el modelo)')."""
import os

from shattering.orchestrator import ShatteringOrchestrator


def test_sin_manifest_usa_el_empaquetado_desde_cualquier_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)   # cwd arbitrario, como el producto instalado
    orch = ShatteringOrchestrator(mode="local")
    assert orch._manifest is not None


def test_manifest_path_explicito_sigue_ganando():
    orch = ShatteringOrchestrator(
        manifest_path=os.path.join("shattering", "manifests", "cognia_desktop.json"),
        mode="local")
    assert orch._manifest is not None
