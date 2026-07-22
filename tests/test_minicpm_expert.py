# -*- coding: utf-8 -*-
"""Tests del experto de tooling MiniCPM5-1B (partes CPU/sin-GPU).

La generación real (el 1B en GPU) se verifica end-to-end en venv312gpu, fuera de
la suite. Aquí se prueba el plumbing determinista: kill-switch, disponibilidad y
el parser del formato XML de tool-calls (puro texto, sin torch). Los imports de
torch/transformers son perezosos, así que este módulo importa en CPU."""
import importlib

me = importlib.import_module("cognia.agent.minicpm_expert")


def test_import_no_arrastra_torch():
    assert hasattr(me, "generar")
    assert hasattr(me, "tool_call")
    assert hasattr(me, "expert_disponible")


def test_killswitch(monkeypatch):
    monkeypatch.setenv("COGNIA_FLEET_GPU", "0")
    ok, motivo = me.expert_disponible()
    assert ok is False
    assert "COGNIA_FLEET_GPU=0" in motivo


def test_disponible_devuelve_tupla(monkeypatch):
    monkeypatch.delenv("COGNIA_FLEET_GPU", raising=False)
    r = me.expert_disponible()
    assert isinstance(r, tuple) and len(r) == 2 and isinstance(r[0], bool)


def test_parsear_una_llamada():
    # formato REAL emitido por MiniCPM5-1B (capturado en la verificacion GPU)
    txt = ('<function name="generar_asset"><param name="prompt">Girasol, estilo '
           'Plants vs Zombies</param><param name="estilo">pixel</param></function>')
    calls = me._parsear_tool_calls(txt)
    assert len(calls) == 1
    assert calls[0]["name"] == "generar_asset"
    assert calls[0]["arguments"]["prompt"] == "Girasol, estilo Plants vs Zombies"
    assert calls[0]["arguments"]["estilo"] == "pixel"


def test_parsear_varias_llamadas():
    txt = ('<function name="a"><param name="x">1</param></function>'
           'texto entre medias'
           '<function name="b"><param name="y">2</param></function>')
    calls = me._parsear_tool_calls(txt)
    assert [c["name"] for c in calls] == ["a", "b"]
    assert calls[1]["arguments"]["y"] == "2"


def test_parsear_cdata():
    txt = ('<function name="f"><param name="code"><![CDATA[if a < b & c:\n  x]]>'
           '</param></function>')
    calls = me._parsear_tool_calls(txt)
    assert calls[0]["arguments"]["code"] == "if a < b & c:\n  x"


def test_parsear_sin_llamada():
    assert me._parsear_tool_calls("solo texto, sin funcion") == []
    assert me._parsear_tool_calls("") == []


def test_parsear_funcion_sin_params():
    txt = '<function name="ping"></function>'
    calls = me._parsear_tool_calls(txt)
    assert calls == [{"name": "ping", "arguments": {}}]


def test_quitar_think():
    assert me._quitar_think("<think>\nrazono\n</think>\nRespuesta") == "Respuesta"
    assert me._quitar_think("Sin think") == "Sin think"
    # think con contenido multilinea
    assert me._quitar_think("<think>a\nb</think>  hola ") == "hola"
