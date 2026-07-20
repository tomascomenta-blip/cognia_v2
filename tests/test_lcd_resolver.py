# -*- coding: utf-8 -*-
"""Regresión de los gaps cazados por eval_lcd_gap 2026-07-09: acentos en el
planner de reglas + resolución de nombres es/en en editar/consultar."""
from cognia.agent.tools import run_tool
import cognia.lcd.tools_lcd  # noqa: F401  (registra las tools)
from cognia.lcd.planner import _tokens, plan


def test_tokens_foldea_acentos():
    assert _tokens("un pájaro azul sobre un árbol verde") == \
        ["un", "pajaro", "azul", "sobre", "un", "arbol", "verde"]


def test_plan_reconoce_con_tildes():
    scene = plan("un pájaro azul sobre un árbol verde")
    nombres = {o.name for o in scene.objects}
    assert "pajaro" in nombres and "arbol" in nombres


def test_editar_resuelve_nombre_en_ingles():
    ctx = {}
    run_tool("escena_crear", "una taza roja sobre una mesa marron", ctx)
    r = run_tool("escena_editar", "cup | color=green", ctx)
    assert "ERROR" not in r and "aplicado" in r


def test_editar_resuelve_tilde():
    ctx = {}
    run_tool("escena_crear", "un pájaro azul sobre un árbol verde", ctx)
    r = run_tool("escena_editar", "pájaro | color=red", ctx)
    assert "ERROR" not in r


def test_consultar_resuelve_nombre_en_ingles():
    ctx = {}
    run_tool("escena_crear", "una taza roja sobre una mesa marron", ctx)
    r = run_tool("escena_consultar", "cup", ctx)
    assert "ERROR" not in r and "forma=" in r


def test_objeto_inexistente_sigue_dando_error():
    ctx = {}
    run_tool("escena_crear", "una taza roja sobre una mesa marron", ctx)
    assert "ERROR" in run_tool("escena_editar", "dragon | color=red", ctx)
    assert "ERROR" in run_tool("escena_consultar", "dragon", ctx)
