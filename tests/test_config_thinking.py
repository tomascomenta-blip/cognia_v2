# -*- coding: utf-8 -*-
"""
tests/test_config_thinking.py
=============================
La config 'thinking' (auto|on|off) se SIEMBRA en COGNIA_THINKING al arrancar
(2026-09-08). Antes `/ventana pensamiento off` guardaba la clave y el proceso
siguiente volvia a pensar: la clave estaba muda. El default es off (medido en
el banco de tareas largas: 0,947 frente a 0,777).
"""
from __future__ import annotations

import pytest

from cognia import cli


@pytest.fixture(autouse=True)
def _limpio(monkeypatch):
    monkeypatch.delenv("COGNIA_THINKING", raising=False)


def test_default_es_off_y_se_siembra(monkeypatch):
    assert cli._CONFIG_DEFAULTS["thinking"] == "off"
    monkeypatch.setattr(cli, "_load_config", lambda: dict(cli._CONFIG_DEFAULTS))
    cli._aplicar_config_thinking()
    import os
    assert os.environ.get("COGNIA_THINKING") == "off"
    from cognia.harness import config_resuelta as cr
    assert cr.es_sembrada("COGNIA_THINKING")


def test_on_se_siembra_y_auto_no(monkeypatch):
    import os
    monkeypatch.setattr(cli, "_load_config", lambda: {"thinking": "on"})
    cli._aplicar_config_thinking()
    assert os.environ.get("COGNIA_THINKING") == "on"
    monkeypatch.delenv("COGNIA_THINKING", raising=False)
    monkeypatch.setattr(cli, "_load_config", lambda: {"thinking": "auto"})
    cli._aplicar_config_thinking()
    assert "COGNIA_THINKING" not in os.environ


def test_la_env_del_usuario_gana(monkeypatch):
    import os
    monkeypatch.setenv("COGNIA_THINKING", "on")
    monkeypatch.setattr(cli, "_load_config", lambda: {"thinking": "off"})
    cli._aplicar_config_thinking()
    assert os.environ["COGNIA_THINKING"] == "on"


def test_valor_invalido_avisa_y_no_siembra(monkeypatch):
    import os
    avisos = []
    monkeypatch.setattr(cli, "_aviso_degradado", lambda o, m: avisos.append((o, m)))
    monkeypatch.setattr(cli, "_load_config", lambda: {"thinking": "quizas"})
    cli._aplicar_config_thinking()
    assert "COGNIA_THINKING" not in os.environ and avisos and avisos[0][0] == "thinking"


def test_el_perfil_apaga_el_pensamiento_con_la_env(monkeypatch):
    from cognia.agent import model_profiles as mp
    monkeypatch.setenv("COGNIA_THINKING", "off")
    assert mp._kwargs_plantilla({"piensa": True}) == {mp._CLAVE_THINKING: False}
    monkeypatch.setenv("COGNIA_THINKING", "on")
    assert mp._kwargs_plantilla({"piensa": True}) == {mp._CLAVE_THINKING: True}
