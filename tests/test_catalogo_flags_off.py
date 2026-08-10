# -*- coding: utf-8 -*-
"""Gate de la ola 2: con TODOS los flags multimodales apagados, el catalogo
del camino feliz queda IDENTICO a antes de la integracion.

POR QUE es el gate de salida: el A/B medido del repo (2026-07-25, camino
feliz 4.25/5 -> 2.5/5 con tools default-ON) prohibe que una familia nueva
se cuele en el catalogo por defecto. Las familias voz/musica/3d/vlm son
opt-in DURO: sin su flag, ni build_tools_doc() ni schemas_para(None) deben
mencionarlas — la unica huella permitida es el mensaje DESHABILITADA de
run_tool (tabla _OPTIN_PREFIJOS), que es justamente lo que evita el bug A5.

Los flags se evaluan a IMPORT-time de tools.py (reiniciar proceso para
encender): la suite corre sin ellos, asi que el registry importado aqui es
el catalogo por defecto real.
"""
from __future__ import annotations

import os

# Las 6 tools nuevas de la flota multimodal (ola 1) y sus flags (ola 2).
_TOOLS_NUEVAS = ("voz_decir", "voz_escuchar", "voz_clonar",
                 "musica_orquestar", "tresd_generar", "vlm_mirar")
_FLAGS_NUEVOS = ("COGNIA_VOZ_TOOLS", "COGNIA_MUSICA_TOOLS",
                 "COGNIA_3D_TOOLS", "COGNIA_VLM_TOOLS")


def test_flags_apagados_en_la_suite():
    """Precondicion del gate: la suite corre con los flags nuevos apagados.
    Si alguien los enciende globalmente, el resto de asserts mediria otra
    cosa — mejor que reviente aca con causa visible."""
    for flag in _FLAGS_NUEVOS:
        assert os.environ.get(flag) != "1", (
            f"{flag}=1 en el entorno de la suite: este gate exige el "
            "catalogo por defecto (flags multimodales apagados)")


def test_tools_nuevas_ausentes_del_registry_y_del_doc():
    from cognia.agent.tools import TOOLS, build_tools_doc
    doc = build_tools_doc()
    for name in _TOOLS_NUEVAS:
        assert name not in TOOLS, (
            f"{name} registrada con el flag apagado: rompe el catalogo del "
            "camino feliz (A/B 2026-07-25)")
        assert name not in doc, f"{name} aparece en build_tools_doc()"


def test_tools_nuevas_ausentes_de_los_schemas():
    """schemas_para(None) lista solo tools REGISTRADAS: las entradas nuevas
    de _TIPADAS no deben filtrarse al catalogo nativo con el flag apagado."""
    from cognia.agent.tool_schemas import schemas_para
    nombres = {s["function"]["name"] for s in schemas_para(None)}
    for name in _TOOLS_NUEVAS:
        assert name not in nombres, (
            f"{name} aparece en schemas_para(None) con el flag apagado")


def test_tools_nuevas_ausentes_de_role_tools():
    from cognia.agent.tools import ROLE_TOOLS
    for rol, tools_del_rol in ROLE_TOOLS.items():
        for name in _TOOLS_NUEVAS:
            assert name not in tools_del_rol, (
                f"{name} en ROLE_TOOLS[{rol!r}] con el flag apagado")


def test_optin_prefijos_cubren_las_familias_nuevas():
    """La cara (a) del gate A5: apagadas, las tools nuevas responden
    'DESHABILITADA — activala con <FLAG>=1' via flag_de_optin, en vez de
    'tool desconocida' (que empuja al researcher a sintetizar duplicados)."""
    from cognia.agent.tools import flag_de_optin
    esperado = {
        "voz_decir": "COGNIA_VOZ_TOOLS",
        "voz_escuchar": "COGNIA_VOZ_TOOLS",
        "voz_clonar": "COGNIA_VOZ_TOOLS",
        "musica_orquestar": "COGNIA_MUSICA_TOOLS",
        "tresd_generar": "COGNIA_3D_TOOLS",
        "vlm_mirar": "COGNIA_VLM_TOOLS",
    }
    for name, flag in esperado.items():
        assert flag_de_optin(name) == flag


def test_run_tool_apagada_responde_deshabilitada():
    """El mensaje uniforme del gate, end-to-end por run_tool (no solo la
    tabla): la respuesta DESHABILITADA trae el flag que la enciende."""
    from cognia.agent.tools import run_tool
    out = run_tool("vlm_mirar", "foto.png", {})
    assert "DESHABILITADA" in out
    assert "COGNIA_VLM_TOOLS=1" in out
