# -*- coding: utf-8 -*-
"""Un servidor MCP que no conecta no se reintenta (2026-09-01).

Ronda de 20 min: tres llamadas seguidas a un servidor que no conectaba, tres
fallos identicos, y la racha de fallos cerro la tarea. Un fallo de CONEXION es
del entorno; repetirlo no lo arregla.
"""
from __future__ import annotations

import pytest

from cognia.agent import tools_mcp


@pytest.fixture(autouse=True)
def _limpio(monkeypatch):
    monkeypatch.setattr(tools_mcp, "_CAIDOS", {})
    yield


def test_fallo_de_conexion_descarta_el_servidor(monkeypatch):
    llamadas = []

    def _conectar_roto(nombre):
        llamadas.append(nombre)
        raise ConnectionError("no hay nadie en el puerto")

    monkeypatch.setattr(tools_mcp, "_conectar", _conectar_roto)
    r1 = tools_mcp._t_mcp("playwright | browser_navigate | {\"url\": \"x\"}", {})
    assert r1.startswith("RESULTADO mcp ERROR: no pude conectar")
    assert "no lo reintentes" in r1
    r2 = tools_mcp._t_mcp("playwright | browser_navigate | {\"url\": \"x\"}", {})
    assert "no esta disponible en esta tarea" in r2
    assert "el arnes la abre en un navegador" in r2
    assert llamadas == ["playwright"], "la segunda llamada no vuelve a conectar"


def test_servidor_no_configurado_sigue_diciendo_cuales_hay(monkeypatch):
    def _conectar_ausente(nombre):
        raise KeyError("servidor MCP 'x' no configurado. Hay: (ninguno)")

    monkeypatch.setattr(tools_mcp, "_conectar", _conectar_ausente)
    r = tools_mcp._t_mcp("x | y | {}", {})
    assert "no configurado" in r
    assert tools_mcp._CAIDOS == {}


def test_fallo_de_la_herramienta_no_descarta_el_servidor(monkeypatch):
    class _Cli:
        conectado = True

        def llamar(self, h, a):
            raise RuntimeError("argumento invalido")

    monkeypatch.setattr(tools_mcp, "_conectar", lambda n: _Cli())
    r = tools_mcp._t_mcp("srv | herr | {}", {})
    assert "fallo: RuntimeError" in r
    assert tools_mcp._CAIDOS == {}
