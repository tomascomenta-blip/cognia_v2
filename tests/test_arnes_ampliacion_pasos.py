# -*- coding: utf-8 -*-
"""
tests/test_arnes_ampliacion_pasos.py
====================================
El QUINTO corte de la corrida del 2026-08-30, el que solo aparecio CORRIENDO.

Con los cuatro arreglos de lectura la tarea del minecraft.html ya no moria por
'sin_arranque'... y moria igual: `(presupuesto de 8 pasos agotado sin cierre)`
a los 119 s con 0 bytes escritos. El presupuesto de pasos es un PRIOR sacado
del texto de la tarea ("arregla el juego" = 267 caracteres, dificultad 0,351
-> 8 pasos) y el texto no sabe que el fichero a arreglar pesa 32 KB.

Arreglo: el techo se AMPLIA mientras el gobernador de progreso diga que la
corrida esta sana, con una sola ampliacion de gracia antes del primer avance
y todas las demas pagadas con avances VERIFICADOS. Techo duro
AGENT_CAP_CON_PROGRESO.

Sin modelo: `completar` guionado, patron de test_deepagents_bucle.py.
"""
from __future__ import annotations

import json

import pytest

from cognia.agent import loop as loop_mod
from cognia.agent.chat_client import (RespuestaChat, ToolCall,
                                      mensaje_assistant, mensaje_tool)
from cognia.agent.tool_schemas import args_legacy, schemas_para


@pytest.fixture(autouse=True)
def _aislado(monkeypatch, tmp_path):
    for var in ("COGNIA_TRAZAS", "COGNIA_TRACE", "COGNIA_COMPACT",
                "COGNIA_ESPECULAR"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("COGNIA_ESTADO", "1")       # el gobernador es el sujeto
    monkeypatch.setenv("COGNIA_TAREAS_LARGAS", "1")
    monkeypatch.setenv("COGNIA_REVISION", "0")     # la revision EJECUTA cosas
    monkeypatch.setenv("COGNIA_HOME", str(tmp_path))


def _perfil():
    return {"nombre": "razonador_nativo", "modelo": "x.gguf",
            "url": "http://127.0.0.1:9", "tools": "nativo", "n_ctx": 16384,
            "temperature": 1.0, "top_p": 1.0, "max_tokens": 4096}


def _resp_tools(*calls):
    return RespuestaChat(
        texto="", finish_reason="tool_calls",
        usage={"completion_tokens": 20, "prompt_tokens": 100},
        tool_calls=[ToolCall(id=i, nombre=n, argumentos=a,
                             argumentos_crudos=json.dumps(a))
                    for i, n, a in calls])


def _resp_fin(texto="Listo."):
    return RespuestaChat(texto=texto, finish_reason="stop",
                         usage={"completion_tokens": 5, "prompt_tokens": 200})


def _correr(respuestas, run_tool, max_turns):
    it = iter(respuestas)

    def _completar(mensajes, tools=None, **kw):
        return next(it, _resp_fin())

    avisos = []
    out = loop_mod.bucle_nativo(
        "construi el fichero", "sos el agente", _completar, schemas_para(),
        args_legacy, mensaje_assistant, mensaje_tool, run_tool, {},
        _perfil(), ["TAREA: construi el fichero"], [],
        lambda m, *a, **k: avisos.append(str(m)), max_turns)
    return out, avisos


def test_el_techo_se_amplia_mientras_el_artefacto_crece(tmp_path):
    """12 apendices reales a un fichero con un presupuesto de 4 pasos: el
    techo se mueve porque CADA apendice deja un avance verificado."""
    destino = tmp_path / "juego.html"

    def _run_tool(name, args, ctx):
        previo = destino.read_text(encoding="utf-8") if destino.exists() else ""
        destino.write_text(previo + "x" * 800, encoding="utf-8")
        return f"RESULTADO {name} {destino}: OK"

    # La clave del esquema es `texto` (tool_schemas.py) y el contenido va
    # DISTINTO en cada apendice: `args_legacy` construye "path | texto", que es
    # lo que firma el guardia de bucles, y con la clave mal escrita la firma
    # seria "path | " en las 12 llamadas -> corte por repeticion a la 5a.
    calls = [(f"t{i}", "apendar_archivo",
              {"path": str(destino), "texto": ("b%03d" % i) * 200})
             for i in range(12)]
    out, avisos = _correr([_resp_tools(c) for c in calls] + [_resp_fin()] * 3,
                          _run_tool, max_turns=4)
    assert out["pasos"] > 4, out
    assert any("presupuesto ampliado" in a for a in avisos), avisos
    assert any("avances verificados" in a for a in avisos), avisos
    # y el artefacto existe de verdad, con lo que se le apendio
    assert destino.stat().st_size >= 800 * 5


def test_sin_avances_la_ampliacion_es_una_sola_y_luego_corta(tmp_path):
    """Una corrida que no produce NADA recibe una ampliacion de gracia (esta
    arrancando) y despues la corta el gobernador: no es barra libre."""
    def _run_tool(name, args, ctx):
        return f"RESULTADO {name}: OK"

    calls = [(f"t{i}", "ejecutar", {"cmd": f"echo {i}"}) for i in range(30)]
    out, avisos = _correr([_resp_tools(c) for c in calls] + [_resp_fin()] * 3,
                          _run_tool, max_turns=4)
    ampliaciones = [a for a in avisos if "presupuesto ampliado" in a]
    assert len(ampliaciones) == 1, ampliaciones
    assert "aun no ha podido producir su primer avance" in ampliaciones[0]
    # el techo se movio de 4 a 8, y de ahi no pasa sin evidencia
    assert out["pasos"] <= 8, out


def test_el_interruptor_apagado_no_amplia_nada(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIA_TAREAS_LARGAS", "0")
    destino = tmp_path / "juego.html"

    def _run_tool(name, args, ctx):
        previo = destino.read_text(encoding="utf-8") if destino.exists() else ""
        destino.write_text(previo + "x" * 800, encoding="utf-8")
        return f"RESULTADO {name} {destino}: OK"

    # La clave del esquema es `texto` (tool_schemas.py) y el contenido va
    # DISTINTO en cada apendice: `args_legacy` construye "path | texto", que es
    # lo que firma el guardia de bucles, y con la clave mal escrita la firma
    # seria "path | " en las 12 llamadas -> corte por repeticion a la 5a.
    calls = [(f"t{i}", "apendar_archivo",
              {"path": str(destino), "texto": ("b%03d" % i) * 200})
             for i in range(12)]
    out, avisos = _correr([_resp_tools(c) for c in calls] + [_resp_fin()] * 3,
                          _run_tool, max_turns=4)
    assert not any("presupuesto ampliado" in a for a in avisos), avisos
    assert out["pasos"] <= 4, out
