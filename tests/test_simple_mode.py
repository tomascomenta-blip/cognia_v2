"""Regresion de cognia/simple_mode.py (modo sencillo default ON, version comercial)."""
from cognia.simple_mode import (
    HIDDEN_IN_SIMPLE, is_simple, should_show_detail, visible_tools,
)


def test_default_es_sencillo():
    # sin override ni pref -> arranca sencillo (la version comercializable)
    assert is_simple(override="") is True
    assert is_simple(override="sencillo") is True


def test_avanzado_desactiva_sencillo():
    assert is_simple(override="avanzado") is False


def test_detail_se_suprime_en_sencillo_pero_no_resultados():
    # [detail] se oculta; ok/warn/err siempre pasan
    assert should_show_detail("[detail]paso 3: leyendo...", override="sencillo") is False
    assert should_show_detail("[ok_cl]listo[/ok_cl]", override="sencillo") is True
    assert should_show_detail("[warn_cl]cuidado[/warn_cl]", override="sencillo") is True
    assert should_show_detail("[err_cl]fallo[/err_cl]", override="sencillo") is True


def test_detail_se_muestra_en_avanzado():
    assert should_show_detail("[detail]paso 3", override="avanzado") is True


def test_visible_tools_recorta_en_sencillo():
    todas = {"leer_archivo", "escribir_archivo", "generar_codigo", "git_diff",
             "kg_buscar", "py_validar", "crear_herramienta", "buscar"}
    vis = visible_tools(todas, override="sencillo")
    # utiles quedan
    assert "leer_archivo" in vis and "generar_codigo" in vis and "buscar" in vis
    # introspeccion/dev se ocultan
    assert "git_diff" not in vis and "kg_buscar" not in vis
    assert "py_validar" not in vis and "crear_herramienta" not in vis


def test_visible_tools_todas_en_avanzado():
    todas = {"leer_archivo", "git_diff", "kg_buscar", "crear_herramienta"}
    assert visible_tools(todas, override="avanzado") == todas


def test_hidden_set_no_incluye_esenciales():
    for esencial in ("leer_archivo", "escribir_archivo", "generar_codigo",
                     "ejecutar", "tests", "buscar", "calcular", "recordar"):
        assert esencial not in HIDDEN_IN_SIMPLE
