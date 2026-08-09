"""Regresion de cognia/simple_mode.py (modo sencillo default ON, version comercial).

2026-08-09 (obra "nivel SOTA", A5): el recorte paso de denylist
(HIDDEN_IN_SIMPLE, jubilada) a ALLOWLIST (CORE_TOOLS de cognia.agent.tools):
con denylist cada tool nueva engordaba el catalogo default en silencio."""
from cognia.simple_mode import is_simple, should_show_detail, visible_tools


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


def test_core_incluye_esenciales():
    from cognia.agent.tools import CORE_TOOLS
    for esencial in ("leer_archivo", "escribir_archivo", "editar_archivo",
                     "generar_codigo", "ejecutar", "tests", "buscar",
                     "calcular", "recordar", "borrar_archivo"):
        assert esencial in CORE_TOOLS


def test_core_es_chico():
    # El A/B del 2026-07-25 midio que el catalogo grande degrada al agente:
    # el default tiene que quedarse en ~12 tools, no volver a crecer en
    # silencio. Si esto falla, alguien agrego una tool al CORE: que lo mida.
    from cognia.agent.tools import CORE_TOOLS
    assert len(CORE_TOOLS) <= 14


def test_optin_activo_entra_al_catalogo_sencillo(monkeypatch):
    # una familia opt-in con su flag activo se anuncia aunque el modo sea
    # sencillo (el opt-in explicito del dueno gana al recorte de UX)
    monkeypatch.setenv("COGNIA_LCD", "1")
    vis = visible_tools({"escena_crear", "escena_editar", "leer_archivo",
                         "git_diff"}, override="sencillo")
    assert "escena_crear" in vis and "escena_editar" in vis
    assert "leer_archivo" in vis
    assert "git_diff" not in vis
    monkeypatch.delenv("COGNIA_LCD")
    vis = visible_tools({"escena_crear", "leer_archivo"}, override="sencillo")
    assert "escena_crear" not in vis
