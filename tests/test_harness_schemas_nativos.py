# -*- coding: utf-8 -*-
"""El registry manda sobre el schema nativo, no una tabla hardcodeada.

Antes de 2026-08-12, `schemas_para` sólo tipaba las tools de su tabla `_TIPADAS`
y a todas las demás les publicaba un único string `args` con la línea de ayuda
dentro. Una tool que DECLARABA su firma con `@tool(params=[...])` acababa
llegando al modelo como una instrucción en prosa. Estos tests fijan que la
firma declarada se publica y que el puente inverso la deshace.
"""

from __future__ import annotations

import pytest

from cognia.agent.tool_schemas import _desde_params, args_legacy, schemas_para
from cognia.agent.tools import TOOLS

# Las tools del arnés son opt-in. Encenderlas con os.environ a nivel de módulo
# CONTAMINA la sesión entera de pytest: así se rompieron
# test_wp2_tools::test_visible_tools_default_es_el_core y el test del oráculo,
# que comprueban justamente que el catálogo por defecto NO crece. Con un
# fixture autouse el flag vive sólo dentro de estos tests.
FLAGS_ARNES = ("COGNIA_OFFLOAD", "COGNIA_ORACULO", "COGNIA_TOOLSEARCH",
               "COGNIA_UNDO_TOOL")


@pytest.fixture(autouse=True)
def _flags_del_arnes(monkeypatch):
    for flag in FLAGS_ARNES:
        monkeypatch.setenv(flag, "1")


def _fn(nombre: str) -> dict:
    for s in schemas_para({nombre}):
        if s["function"]["name"] == nombre:
            return s["function"]
    raise AssertionError(f"{nombre} no aparece en schemas_para")


# ── la conversión params -> JSON Schema ────────────────────────────────
def test_params_declarados_se_vuelven_propiedades_tipadas():
    esquema = _desde_params([
        {"nombre": "handle", "tipo": "string", "requerido": True, "descripcion": "el id"},
        {"nombre": "lineas", "tipo": "string", "requerido": False, "descripcion": "rango"},
    ])
    assert esquema["properties"]["handle"]["type"] == "string"
    assert esquema["properties"]["handle"]["description"] == "el id"
    assert esquema["required"] == ["handle"]


def test_tipos_en_espanol_se_traducen():
    esquema = _desde_params([{"nombre": "n", "tipo": "entero", "requerido": False}])
    assert esquema["properties"]["n"]["type"] == "integer"


def test_params_basura_no_revientan():
    assert _desde_params([None, {}, {"nombre": ""}, 42])["properties"] == {}
    assert _desde_params([])["properties"] == {}


# ── el registry gana al genérico ───────────────────────────────────────
@pytest.mark.parametrize("nombre", ["recuperar", "consultar_oraculo", "deshacer_edicion"])
def test_las_tools_del_arnes_publican_firma_real(nombre):
    props = _fn(nombre)["parameters"]["properties"]
    assert "args" not in props, (
        f"{nombre} sigue saliendo como un string generico: el modelo recibe "
        "una instruccion en prosa en vez de una firma")
    assert props, f"{nombre} no publica ninguna propiedad"


def test_recuperar_publica_sus_tres_argumentos():
    props = _fn("recuperar")["parameters"]["properties"]
    assert set(props) == {"handle", "lineas", "buscar"}
    assert _fn("recuperar")["parameters"]["required"] == ["handle"]


def test_una_tool_sin_params_sigue_con_el_generico():
    """El camino viejo no se toca: sin params declarados, string `args`.

    Hay que excluir las que la tabla `_TIPADAS` ya tipaba a mano: esas siguen
    mandando (son las medidas contra el modelo real) y no pasan por la rama
    nueva.
    """
    from cognia.agent.tool_schemas import _SIN_ARGS, _TIPADAS
    genericas = [n for n, s in TOOLS.items()
                 if not s.get("params") and n not in _TIPADAS and n not in _SIN_ARGS]
    assert genericas, "no queda ninguna tool generica: revisar este test"
    props = _fn(genericas[0])["parameters"]["properties"]
    assert set(props) == {"args"}, (
        f"{genericas[0]} no declara params: tenia que seguir con el string generico")


# ── el puente inverso ──────────────────────────────────────────────────
def test_args_legacy_reconstruye_el_protocolo_texto():
    assert args_legacy("recuperar", {"handle": "res:3f2a1b", "lineas": "200-260"}) == \
        "res:3f2a1b lineas=200-260"
    assert args_legacy("delegar_subtarea", {"rol": "investigador", "subtarea": "lee el README"}) == \
        "investigador | lee el README"


def test_argumentos_con_nombres_inventados_no_dan_llamada_vacia():
    """Si el modelo improvisa los nombres, algo tiene que llegar a la tool."""
    salida = args_legacy("borrar_archivo", {"fichero_a_borrar": "viejo.txt"})
    assert salida == "viejo.txt", (
        "una clave no reconocida dejaba la llamada sin argumentos y la tool no "
        "podia ni explicar que falto")


def test_dict_vacio_sigue_dando_cadena_vacia():
    assert args_legacy("borrar_archivo", {}) == ""
