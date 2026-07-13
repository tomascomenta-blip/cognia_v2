# -*- coding: utf-8 -*-
"""Identidad visual del fleet para la oficina por departamentos."""
from cognia.oficina.identidad import (DEPARTAMENTOS, departamentos, identidad,
                                      roster)


def test_identidad_declarada():
    m = identidad("qwen35_4b")
    assert m["nombre"] == "Max"
    assert m["depto"] == "ingenieria"
    assert m["color"].startswith("#")
    assert m["depto_nombre"] == "Ingeniería"


def test_identidad_desconocida_no_rompe():
    m = identidad("modelo_futuro_xyz")
    assert m["nombre"] == "Modelo Futuro Xyz"   # derivado del key
    assert m["depto"] == "general"
    assert m["color"] == DEPARTAMENTOS["general"]["color"]


def test_roster_incluye_historicos_y_fleet():
    r = roster()
    keys = {m["key"] for m in r}
    # históricos
    assert {"3b", "portero", "7b"} <= keys
    # miembros del fleet30.json
    assert {"qwen35_4b", "qwen3_4b", "nextcoder7b"} <= keys
    # cada miembro tiene identidad completa
    for m in r:
        assert m["nombre"] and m["color"].startswith("#")
        assert m["depto"] in DEPARTAMENTOS
        assert m["rol_visual"] in ("mega_jefe", "jefe", "investigador",
                                   "implementador")


def test_colores_distintos_dentro_del_depto():
    # dos modelos del mismo depto no comparten color (se distinguen de un vistazo)
    ing = [m for m in roster() if m["depto"] == "ingenieria"]
    colores = [m["color"] for m in ing]
    assert len(colores) == len(set(colores)), "colores repetidos en Ingeniería"


def test_departamentos_agrupa_y_ordena():
    d = departamentos()
    nombres = [x["key"] for x in d]
    # Dirección/Ingeniería aparecen y en ese orden relativo
    assert "ingenieria" in nombres and "razonamiento" in nombres
    assert nombres.index("ingenieria") < nombres.index("datos")
    # cada depto trae miembros con su color
    for dep in d:
        assert dep["miembros"]
        assert dep["color"].startswith("#")


def test_roster_trae_metadatos_operativos():
    by = {m["key"]: m for m in roster()}
    assert by["qwen35_4b"]["port"] == 8097      # del fleet30.json
    assert by["3b"]["port"] == 8088             # histórico
