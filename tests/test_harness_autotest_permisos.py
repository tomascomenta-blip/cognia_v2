# -*- coding: utf-8 -*-
"""Contrato de `cognia/harness/autotest_permisos.py` (lección del allowlist
nunca cargado de Hermes, 2026-09-04): con el gate sano no hay problemas; con
el sentinel apagado o clasificando mal, se dice; y `resumen()` es legible."""
from __future__ import annotations

from cognia.harness import autotest_permisos as ap


def test_gate_sano_sin_problemas(monkeypatch):
    monkeypatch.delenv("COGNIA_SENTINEL", raising=False)
    monkeypatch.delenv("COGNIA_INTERACTIVOS", raising=False)
    assert ap.autotest() == []
    assert ap.resumen().startswith("gate de permisos: OK")


def test_sentinel_apagado_se_ve(monkeypatch):
    monkeypatch.setenv("COGNIA_SENTINEL", "0")
    p = ap.autotest()
    assert any("APAGADO" in x for x in p)


def test_un_clasificador_roto_se_ve(monkeypatch):
    from cognia.agent import sentinel
    monkeypatch.setattr(sentinel, "clasificar_shell", lambda cmd, *a, **k: ("allow", "todo bien"))
    p = ap.autotest()
    assert any("NO bloquea 'rm -rf /'" in x for x in p)
    assert "problemas" in ap.resumen()


def test_lista_de_interactivos_apagada_no_es_problema(monkeypatch):
    monkeypatch.setenv("COGNIA_INTERACTIVOS", "0")
    assert not any("interactivos" in x for x in ap.autotest())
