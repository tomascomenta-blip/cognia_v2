# -*- coding: utf-8 -*-
"""Regresion 2026-09-01: los tool calls PARCIALES tambien se rescatan.

Cuando llama-server devuelve HTTP 500 "Failed to parse tool call arguments as
JSON", el fichero a medio escribir viaja DENTRO de la peticion cortada. Antes de
este fix:
  - `chat_client` tiraba esos tool calls acumulados en los dos `except`, y
  - `loop._hay_parcial_rescatable` solo miraba `resp.tool_calls`,
asi que el rescate que existe (`_rescatar_escritura`) no podia verlos nunca y el
turno cerraba tirando los KB ya pagados.

Lo que NO debe cambiar: un turno que corto el USUARIO (finish_reason
'cancelado') no se rescata jamas. chat_client vacia `.tool_calls` a proposito en
ese caso para que nada aguas abajo escriba ficheros despues del Esc; leer los
parciales sin mirar el motivo reabriria esa puerta.
"""
from __future__ import annotations

import json

from cognia.agent.loop import _hay_parcial_rescatable, _tool_calls_con_parciales


class _TC:
    def __init__(self, nombre, crudo, rotos=True):
        self.nombre = nombre
        self.argumentos_crudos = crudo
        self.argumentos_rotos = rotos
        self.argumentos = {}


class _Resp:
    def __init__(self, tool_calls=(), parciales=(), finish_reason="", ok=False):
        self.tool_calls = list(tool_calls)
        self.tool_calls_parciales = list(parciales)
        self.finish_reason = finish_reason
        self.ok = ok


def _crudo_cortado():
    """Argumentos de escribir_archivo cortados a media cadena, como el 500."""
    entero = json.dumps({"ruta": "juego.js", "contenido": "const x = 1;\n" * 40})
    return entero[: int(len(entero) * 0.8)]


def test_parcial_de_un_500_es_rescatable():
    resp = _Resp(tool_calls=(),
                 parciales=(_TC("escribir_archivo", _crudo_cortado()),),
                 finish_reason="", ok=False)
    assert _hay_parcial_rescatable(resp) is True


def test_el_turno_cancelado_por_el_usuario_no_se_rescata():
    resp = _Resp(tool_calls=(),
                 parciales=(_TC("escribir_archivo", _crudo_cortado()),),
                 finish_reason="cancelado", ok=False)
    assert _tool_calls_con_parciales(resp) == []
    assert _hay_parcial_rescatable(resp) is False


def test_un_turno_sano_no_toca_los_parciales():
    tc = _TC("escribir_archivo", '{"ruta":"a.js","contenido":"x"}', rotos=False)
    resp = _Resp(tool_calls=(tc,), parciales=(), finish_reason="tool_calls", ok=True)
    assert _tool_calls_con_parciales(resp) == [tc]
    assert _hay_parcial_rescatable(resp) is False


def test_la_union_no_pierde_los_buenos():
    bueno = _TC("escribir_archivo", '{"ruta":"a.js","contenido":"x"}', rotos=False)
    roto = _TC("escribir_archivo", _crudo_cortado())
    resp = _Resp(tool_calls=(bueno,), parciales=(roto,), finish_reason="", ok=False)
    assert _tool_calls_con_parciales(resp) == [bueno, roto]
