# -*- coding: utf-8 -*-
"""
tests/test_harness_barra_estado.py
==================================
Regresion de la BARRA DE ESTADO INFERIOR y la BARRA DE ATAJOS (2026-08-12).

Falla sin cognia/harness/barra_estado.py (ImportError en la coleccion) y pasa
con el. Todo se prueba contra el modulo REAL: sin mocks, sin monkeypatch de la
logica; el unico "entorno" que se toca es el ancho, que es un argumento.

Lo que se protege, en orden de importancia:
 1. La linea mide EXACTAMENTE el ancho pedido y la derecha queda pegada al
    borde (si no, la barra "salta" en cada redibujado).
 2. La PRIORIDAD DE RECORTE documentada: tokens -> directorio -> rama -> modo,
    y el modelo y el contexto no se caen NUNCA.
 3. Nunca se pasa del ancho, con ningun ancho (incluidos los absurdos).
 4. Nada de emojis y todo escribible en la consola de Windows (cp1252), con
    fallback ASCII para las flechas.
 5. Los nombres de estilo existen DE VERDAD en los temas de cognia/cli.py.
 6. El callable de prompt_toolkit lo acepta un PromptSession REAL.
"""
from __future__ import annotations

import os

import pytest

from cognia.harness import barra_estado as B

HOME = os.path.expanduser("~").replace("\\", "/").rstrip("/")

# 'ctx 12.4k/128.0k (90% libre)' y '3.2k tok' con estos numeros: usado 12400
# sobre util = 128000 - 1024 de headroom = 126976 -> 10% usado, 90% libre.
DATOS = {
    "modelo": "qwythos-9b",
    "directorio": HOME + "/Desktop/cognia_v2",
    "rama": "main",
    "sucio": True,
    "ctx_usado": 12400,
    "ctx_total": 128000,
    "tokens_sesion": 3200,
    "modo": "ejecutar",
    "permiso": "automatico",
}
DATOS_PLAN = dict(DATOS, modo="plan")

# Glifos no-ASCII PERMITIDOS en toda la salida del modulo (los bloques de la
# mini-barra entraron el 2026-08-23; tienen fallback ASCII '#'/'.').
GLIFOS_OK = {"\u00b7", "\u2026", "\u2191", "\u2193", "\u2588", "\u2591"}


@pytest.fixture(autouse=True)
def umbrales_de_fabrica(monkeypatch):
    """Sin envs del footer ni de compactacion: los umbrales quedan en los de
    fabrica (aviso 80 = umbral de compactacion, critico 90) y la mini-barra
    de bloques en su default (encendida)."""
    for var in ("COGNIA_CTX_AVISO", "COGNIA_CTX_CRITICO",
                "COGNIA_BARRA_BLOQUES", "COGNIA_COMPACT_UMBRAL"):
        monkeypatch.delenv(var, raising=False)


# ---------------------------------------------------------------------------
# humano()
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("n,esperado", [
    (0, "0"),
    (999, "999"),
    (1000, "1.0k"),
    (1_250_000, "1.2M"),
])
def test_humano_casos_del_encargo(n, esperado):
    assert B.humano(n) == esperado


def test_humano_bordes_y_basura():
    assert B.humano(12_400) == "12.4k"
    assert B.humano(999_999) == "1.0M"      # nunca '1000.0k'
    assert B.humano(-1500) == "-1.5k"
    assert B.humano(None) == ""
    assert B.humano("no soy un numero") == ""
    assert B.humano(float("nan")) == ""


# ---------------------------------------------------------------------------
# barra_estado(): anclaje, contenido y ancho
# ---------------------------------------------------------------------------
def test_barra_mide_el_ancho_pedido_y_ancla_a_los_dos_bordes():
    linea = B.barra_estado(DATOS, 100, unicode_ok=True)
    assert len(linea) == 100
    assert linea.startswith("qwythos-9b")          # izquierda pegada
    assert linea.endswith("3.2k tok")              # derecha pegada al borde
    assert "  " in linea                           # relleno de espacios en medio


def test_barra_muestra_las_secciones_del_encargo():
    linea = B.barra_estado(DATOS_PLAN, 110, unicode_ok=True)
    assert "PLAN" in linea                         # insignia de modo
    assert "qwythos-9b" in linea                   # modelo
    assert "~/Desktop/cognia_v2" in linea          # directorio con ~
    assert "main*" in linea                        # rama + arbol sucio
    assert "ctx 12.4k/128.0k (90% libre)" in linea  # % LIBRE, cuenta abajo
    assert "\u2588" * 7 + "\u2591" in linea            # mini-barra: 7 de 8 LIBRES
    assert "3.2k tok" in linea                     # tokens de la sesion
    # 4 separadores DENTRO de los grupos; entre izquierda y derecha va el
    # relleno de espacios que ancla la derecha al borde.
    assert linea.count(" \u00b7 ") == 4
    assert linea.index("main*") < linea.index("ctx ")


def test_ruta_fuera_del_home_no_se_toca_y_el_modelo_pierde_el_path():
    datos = dict(DATOS, directorio="D:\\repos\\proyecto",
                 modelo="C:/modelos/Qwythos-9B.gguf")
    linea = B.barra_estado(datos, 120, unicode_ok=True)
    assert "D:/repos/proyecto" in linea
    assert "Qwythos-9B" in linea and ".gguf" not in linea


def test_arbol_limpio_no_lleva_asterisco():
    linea = B.barra_estado(dict(DATOS, sucio=False), 100, unicode_ok=True)
    assert "main" in linea and "main*" not in linea


# ---------------------------------------------------------------------------
# Prioridad de recorte (el corazon del encargo)
# ---------------------------------------------------------------------------
def _flags(linea):
    return {
        "tokens": " tok" in linea,
        "dir_largo": "/Desktop/" in linea,
        "dir": "cognia_v2" in linea,
        "rama": "main" in linea,
        "modo": "PLAN" in linea,
    }


def test_prioridad_de_recorte_documentada():
    """Al angostar: cae tokens, luego el directorio se acorta a su ultimo
    componente, luego la rama, luego el modo. Modelo y contexto SIEMPRE."""
    # 39 celdas es el escalon minimo sin truncar: 'qwythos-9b' (10) + 1 de
    # separacion + 'ctx 12.4k/128.0k (90% libre)' (28).
    vistos = set()
    previo = None
    for ancho in range(39, 130):
        linea = B.barra_estado(DATOS_PLAN, ancho, unicode_ok=True)
        assert len(linea) == ancho, (ancho, repr(linea))
        assert "qwythos-9b" in linea, (ancho, linea)      # nunca se cae
        assert "ctx 12.4k/128.0k" in linea, (ancho, linea)  # nunca se cae
        f = _flags(linea)
        # La escalera: cada escalon implica todos los anteriores.
        if not f["dir"]:
            assert not f["rama"] and not f["modo"] and not f["tokens"]
        if not f["modo"]:
            assert not f["rama"] and not f["tokens"] and not f["dir_largo"]
        if not f["rama"]:
            assert not f["tokens"] and not f["dir_largo"]
        if not f["dir_largo"]:
            assert not f["tokens"]
        # Monotonia: nada reaparece al ensanchar.
        if previo is not None:
            for k in f:
                assert f[k] >= previo[k], (ancho, k)
        previo = f
        vistos.add(tuple(sorted(f.items())))
    # Los escalones existen de verdad (no es una escalera teorica).
    assert len(vistos) >= 5


def test_escalones_concretos():
    lleno = B.barra_estado(DATOS_PLAN, 120, unicode_ok=True)
    assert " tok" in lleno and "/Desktop/" in lleno
    sin_tokens = B.barra_estado(DATOS_PLAN, 60, unicode_ok=True)
    assert " tok" not in sin_tokens and "cognia_v2" in sin_tokens
    minimo = B.barra_estado(DATOS_PLAN, 39, unicode_ok=True)
    assert minimo == "qwythos-9b ctx 12.4k/128.0k (90% libre)"
    # Un ancho ridiculo trunca, pero el modelo sobrevive como prefijo legible.
    apretado = B.barra_estado(DATOS_PLAN, 20, unicode_ok=True)
    assert len(apretado) <= 20 and apretado.startswith("qwythos-9b ")
    assert apretado.endswith("\u2026")


@pytest.mark.parametrize("ancho", list(range(1, 200)))
def test_nunca_se_pasa_del_ancho(ancho):
    for datos in (DATOS, DATOS_PLAN, {}, {"modelo": "m" * 200}):
        linea = B.barra_estado(datos, ancho, unicode_ok=True)
        assert len(linea) <= ancho, (ancho, repr(linea))


def test_datos_basura_no_revientan():
    assert B.barra_estado({}, 80) == ""
    feo = {"modelo": None, "directorio": 12, "rama": object(), "sucio": "si",
           "ctx_usado": "x", "ctx_total": None, "tokens_sesion": [],
           "modo": 3, "permiso": None}
    B.barra_estado(feo, 80)                     # no lanza
    B.barra_estado(DATOS, "ochenta")            # ancho invalido: no lanza
    B.barra_estado(DATOS, 0)


@pytest.mark.parametrize("bicho", [float("inf"), float("-inf"), 10 ** 400])
def test_infinitos_y_enteros_gigantes_no_revientan(bicho):
    """REGRESION: `int(float(x))` lanza OverflowError (que NO es ValueError)
    con infinito y con enteros que no entran en un float. La barra tiene
    contrato de no lanzar NUNCA, y esto la reventaba por tres puertas."""
    assert B.humano(bicho) == ""
    for clave in ("ctx_usado", "ctx_total", "tokens_sesion"):
        B.barra_estado(dict(DATOS, **{clave: bicho}), 80, unicode_ok=True)
    # Tambien como ANCHO: ademas del cast, el relleno de espacios reventaba
    # ('int' too large) cuando el ancho era un entero gigante que SI casteaba.
    linea = B.barra_estado(DATOS, bicho, unicode_ok=True)
    assert len(linea) <= B._ANCHO_MAX


def test_un_solo_dato_no_desaparece_por_un_escalon_vacio():
    """REGRESION: la barra devolvia "" en cuanto UN escalon quedaba sin
    secciones, aunque escalones anteriores si tuvieran contenido que entraba.
    Con solo 'modo', el escalon 'sin_modo' esta vacio y borraba la barra."""
    assert B.barra_estado({"modo": "plan"}, 4, unicode_ok=True) == "PLAN"
    assert B.barra_estado({"modo": "plan"}, 3, unicode_ok=True) == "PL…"
    # Solo el grupo DERECHO: no hay izquierda de la que separarse, asi que no
    # hace falta reservar un espacio y '3.2k tok' entra justo en 8 celdas.
    assert B.barra_estado({"tokens_sesion": 3200}, 8, unicode_ok=True) == \
        "3.2k tok"


def test_no_hay_elipsis_cuando_no_se_corto_nada():
    """REGRESION: por debajo del ancho minimo se truncaba SIEMPRE, y la
    elipsis aparecia aunque el texto entrase entero ('ab' en 7 -> 'ab…')."""
    assert B.barra_estado({"modelo": "ab"}, 7, unicode_ok=True) == "ab"
    assert B.barra_estado({"modelo": "ab"}, 2, unicode_ok=True) == "ab"
    assert B.barra_estado({"modelo": "abcd"}, 3, unicode_ok=True) == "ab…"


def test_secciones_sin_dato_simplemente_no_existen():
    sin_rama = B.barra_estado(dict(DATOS, rama="", sucio=False), 100,
                              unicode_ok=True)
    assert "main" not in sin_rama and "qwythos-9b" in sin_rama
    sin_total = B.barra_estado(dict(DATOS, ctx_total=0), 100, unicode_ok=True)
    assert "ctx 12.4k" in sin_total and "%" not in sin_total


# ---------------------------------------------------------------------------
# Footer de contexto honesto (2026-08-23): % libre, headroom, umbrales
# acoplados a compactacion, mini-barra de bloques
# ---------------------------------------------------------------------------
def test_headroom_restado_del_total():
    """El % se calcula sobre n_ctx - 1024 (headroom fijo, receta CodeWhale):
    50000 de 101024 es EXACTO 50% del util; sin headroom seria 49%."""
    datos = dict(DATOS, ctx_usado=50_000, ctx_total=101_024)
    linea = B.barra_estado(datos, 99, unicode_ok=True)
    assert "(50% libre)" in linea
    nc = B.nivel_contexto(50_000, 101_024)
    assert (nc["pct_usado"], nc["libre"], nc["headroom"]) == (50, 50, 1024)


def test_sin_backend_ctx_interrogante():
    """Flota apagada (sin n_ctx y sin ocupacion): 'ctx ?' tenue, JAMAS un %
    inventado. Con ocupacion real pero sin ventana: el numero pelado sin %."""
    linea = B.barra_estado({"ctx_usado": 0, "ctx_total": 0}, 80,
                           unicode_ok=True)
    assert "ctx ?" in linea and "%" not in linea
    partes = B.barra_estado_partes({"ctx_usado": 0, "ctx_total": 0}, 80,
                                   unicode_ok=True)
    assert [(t, e) for t, e in partes if t.strip()] == [("ctx ?", B.EST_CTX)]
    assert B.nivel_contexto(0, 0)["pct_usado"] is None


def test_sufijo_compactar_solo_en_aviso():
    tranquila = B.barra_estado(DATOS, 120, unicode_ok=True)
    assert "/compactar" not in tranquila
    alta = B.barra_estado(dict(DATOS, ctx_usado=105_000), 120,
                          unicode_ok=True)
    assert "/compactar" in alta


def test_umbral_amarillo_acoplado_al_de_compactacion(monkeypatch):
    """REGRESION: el amarillo tiene que moverse con /compactar umbral
    (COGNIA_COMPACT_UMBRAL); un segundo umbral hardcodeado mentiria. La env
    del footer COGNIA_CTX_AVISO gana cuando el dueno fija uno aparte."""
    datos = dict(DATOS, ctx_usado=83_000)          # 65% del util
    def estilo_ctx(d):
        partes = B.barra_estado_partes(d, 99, unicode_ok=True)
        return [e for t, e in partes if t.startswith("ctx ")][0]
    assert estilo_ctx(datos) == B.EST_CTX          # 65 < 80: normal
    monkeypatch.setenv("COGNIA_COMPACT_UMBRAL", "0.6")
    assert estilo_ctx(datos) == B.EST_CTX_ALTO     # el umbral bajo a 60
    monkeypatch.setenv("COGNIA_CTX_AVISO", "70")
    assert estilo_ctx(datos) == B.EST_CTX          # la env del footer gana


def test_bloques_solo_con_terminal_ancha_y_config(monkeypatch):
    """La mini-barra sale a >= 100 columnas; en angosto cae ELLA primero y
    el % queda; COGNIA_BARRA_BLOQUES=off la apaga del todo."""
    ancha = B.barra_estado(DATOS, 120, unicode_ok=True)
    # 10% usado = 90% libre = 7 celdas llenas de 8 (la barra cuenta lo LIBRE,
    # en la misma direccion que el '(90% libre)' de al lado)
    assert "\u2588" * 7 + "\u2591" in ancha
    angosta = B.barra_estado(DATOS, 99, unicode_ok=True)
    assert "\u2588" not in angosta and "% libre" in angosta
    monkeypatch.setenv("COGNIA_BARRA_BLOQUES", "off")
    apagada = B.barra_estado(DATOS, 120, unicode_ok=True)
    assert "\u2588" not in apagada and "% libre" in apagada


def test_bloques_caen_antes_que_los_tokens():
    """Escalon 'sin_bloques': con >= 100 cols pero sin sitio para la
    mini-barra, se sacrifica ELLA y los tokens de sesion quedan."""
    datos = dict(DATOS, modelo="qwythos-9b-extra-larga")   # +12 celdas
    # A 100 columnas la linea completa mide exactamente 100 y el espacio
    # minimo entre grupos ya no entra: cae el escalon 'sin_bloques'.
    justa = B.barra_estado(datos, 100, unicode_ok=True)
    assert "\u2588" not in justa and " tok" in justa
    assert "% libre" in justa
    holgada = B.barra_estado(datos, 110, unicode_ok=True)
    assert "\u2588" in holgada and " tok" in holgada


def test_ocupacion_estimada_lleva_virgulilla():
    """El camino de chat solo tiene chars/4: la barra antepone '~' al usado
    (y al numero pelado sin ventana); con usage real no hay tilde."""
    est = B.barra_estado(dict(DATOS, ctx_estimado=True), 99, unicode_ok=True)
    assert "ctx ~12.4k/128.0k (90% libre)" in est
    assert "ctx ~12.4k" in B.barra_estado(
        {"ctx_usado": 12_400, "ctx_total": None, "ctx_estimado": True}, 80,
        unicode_ok=True)
    assert "ctx ~" not in B.barra_estado(DATOS, 99, unicode_ok=True)


def test_llenado_de_la_mini_barra():
    g = B._glifos(True)
    # lleno = LIBRE (indicador que se vacia al gastar contexto)
    assert B._bloques(0, g) == "\u2588" * 8
    assert B._bloques(50, g) == "\u2588" * 4 + "\u2591" * 4
    assert B._bloques(100, g) == "\u2591" * 8
    assert B._bloques(83, g) == "\u2588" * 1 + "\u2591" * 7


# ---------------------------------------------------------------------------
# Partes con estilo logico
# ---------------------------------------------------------------------------
def test_partes_reconstruyen_el_texto_y_usan_estilos_conocidos():
    partes = B.barra_estado_partes(DATOS_PLAN, 100, unicode_ok=True)
    assert "".join(t for t, _ in partes) == B.barra_estado(
        DATOS_PLAN, 100, unicode_ok=True)
    for texto, estilo in partes:
        assert estilo in B.ESTILOS, (texto, estilo)
    # La rama es el UNICO acento de la barra.
    acentos = [t for t, e in partes if e == B.EST_RAMA]
    assert acentos == ["main"]


@pytest.mark.parametrize("usado,estilo", [
    (12_400, B.EST_CTX),
    (105_000, B.EST_CTX_ALTO),       # 83% del util (aviso al 80)
    (125_000, B.EST_CTX_CRITICO),    # 98% del util (critico al 90)
])
def test_el_contexto_avisa_cuando_se_llena(usado, estilo):
    partes = B.barra_estado_partes(dict(DATOS, ctx_usado=usado), 100,
                                   unicode_ok=True)
    ctx = [(t, e) for t, e in partes if t.startswith("ctx ")]
    assert len(ctx) == 1 and ctx[0][1] == estilo


def test_los_estilos_existen_en_los_temas_reales_del_cli():
    """Un nombre de estilo inventado sale SIN COLOR y nadie lo nota (paso ya
    con [ok_cl]).

    2026-08-17: antes esto parseaba el bloque `"oscuro": Theme({...})` del
    fuente de cognia/cli.py. Ese bloque ya no existe: los tres temas se derivan
    de cognia/ux/paleta.py. Se valida contra LOS TRES temas resueltos, que es
    mas fuerte que el scan de texto (un token puede faltar en una sola
    variante)."""
    from cognia.ux import paleta
    faltantes = {v: (B.ESTILOS - {""}) - set(paleta.tema_cli(v))
                 for v in paleta.ORDEN_VARIANTES}
    assert not any(faltantes.values()), faltantes


# ---------------------------------------------------------------------------
# Glifos: nada de emojis, cp1252 y fallback ASCII
# ---------------------------------------------------------------------------
def test_sin_emojis_y_escribible_en_la_consola_de_windows():
    salidas = [B.barra_estado(DATOS_PLAN, 100, unicode_ok=True)]
    salidas += [B.barra_atajos(c, unicode_ok=True) for c in B.CONTEXTOS]
    for s in salidas:
        for ch in s:
            assert ord(ch) < 128 or ch in GLIFOS_OK, (hex(ord(ch)), s)
            assert ord(ch) < 0x1F000                 # cero emojis
    # La barra de estado SIN mini-barra entra entera en cp1252 (consola por
    # defecto); los bloques (>= 100 cols) NO son cp1252, por eso el juego de
    # glifos los autodetecta POR GLIFO y aqui se pide el fallback '#'.
    B.barra_estado(DATOS_PLAN, 99, unicode_ok=True).encode("cp1252")
    assert "#" in B.barra_estado(DATOS_PLAN, 100, unicode_ok=False)


def test_fallback_ascii_completo():
    linea = B.barra_estado(DATOS_PLAN, 100, unicode_ok=False)
    linea.encode("ascii")
    assert " | " in linea and "\u00b7" not in linea
    atajos = B.barra_atajos("repl", unicode_ok=False)
    atajos.encode("ascii")
    assert "arriba/abajo historial" in atajos
    assert "\u2191" not in atajos


# ---------------------------------------------------------------------------
# barra_atajos()
# ---------------------------------------------------------------------------
def test_atajos_textos_exactos_del_encargo():
    assert B.barra_atajos("generando", unicode_ok=True) == \
        "esc interrumpe \u00b7 ctrl+c corta"
    # 'f2 agentes' se agrego el 2026-08-18 (carril de fondo): el prompt de
    # espera nombraba F2 en su marco y esta barra no, asi que la unica forma
    # de descubrir la vista de agentes era lanzar una corrida.
    assert B.barra_atajos("repl", unicode_ok=True) == \
        ("tab completa \u00b7 \u2191\u2193 historial \u00b7 @ archivo \u00b7 "
         "/ comandos \u00b7 f2 agentes")


def test_atajos_permiso_y_selector():
    permiso = B.barra_atajos("permiso", unicode_ok=True)
    assert "esc cancela" in permiso and "permite siempre" in permiso
    selector = B.barra_atajos("selector", unicode_ok=True)
    assert "navega" in selector and "enter elige" in selector


@pytest.mark.parametrize("contexto", ["", None, "no-existe", "REPL "])
def test_atajos_contexto_desconocido_o_vacio(contexto):
    salida = B.barra_atajos(contexto, unicode_ok=True)
    if str(contexto or "").strip().lower() in B.CONTEXTOS:
        assert salida                       # 'REPL ' normaliza a 'repl'
    else:
        assert salida == ""


def test_atajos_se_recortan_por_la_derecha():
    for ancho in (5, 12, 20, 30, 40):
        linea = B.barra_atajos("repl", ancho=ancho, unicode_ok=False)
        assert len(linea) <= ancho, (ancho, linea)
    corta = B.barra_atajos("repl", ancho=20, unicode_ok=False)
    assert corta.startswith("tab completa")
    assert "comandos" not in corta          # cae lo ultimo, no lo primero


def test_atajos_partes_reconstruyen_el_texto():
    partes = B.barra_atajos_partes("permiso", unicode_ok=True)
    assert "".join(t for t, _ in partes) == B.barra_atajos(
        "permiso", unicode_ok=True)
    assert all(e in B.ESTILOS for _, e in partes)


# ---------------------------------------------------------------------------
# indicador_modo()
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("modo,permiso,esperado", [
    ("ejecutar", "automatico", ""),          # el caso normal: NADA que destacar
    ("plan", "automatico", "PLAN"),
    ("plan", "manual", "PLAN"),              # el modo manda sobre el permiso
    ("ejecutar", "bypass", "auto"),
    ("ejecutar", "manual", "manual"),
    ("", "", ""),
    (None, None, ""),
    ("ejecutar", "loquesea", ""),
])
def test_indicador_modo(modo, permiso, esperado):
    texto, estilo = B.indicador_modo(modo, permiso)
    assert texto == esperado
    assert estilo in B.ESTILOS
    assert (estilo == "") == (texto == "")


# ---------------------------------------------------------------------------
# Enganche con prompt_toolkit
# ---------------------------------------------------------------------------
def test_toolbar_es_callable_sin_argumentos():
    fn = B.toolbar_prompt_toolkit(lambda: DATOS, ancho=90, unicode_ok=True)
    salida = fn()
    assert isinstance(salida, str) and len(salida) == 90
    assert "qwythos-9b" in salida


def test_toolbar_tolera_que_el_proveedor_lance_o_devuelva_basura():
    def explota():
        raise RuntimeError("el proveedor se cayo")
    assert B.toolbar_prompt_toolkit(explota)() == ""
    assert B.toolbar_prompt_toolkit(lambda: None)() == ""
    assert B.toolbar_prompt_toolkit(lambda: "no soy un dict")() == ""
    assert B.toolbar_prompt_toolkit(None)() == ""


def test_toolbar_con_segunda_linea_de_atajos():
    fn = B.toolbar_prompt_toolkit(lambda: DATOS, ancho=90,
                                  contexto_atajos="repl", unicode_ok=True)
    lineas = fn().split("\n")
    assert len(lineas) == 2
    assert "qwythos-9b" in lineas[0] and "tab completa" in lineas[1]


def test_prompt_session_real_acepta_el_toolbar():
    """Sin mocks: un PromptSession de verdad (entrada por pipe y DummyOutput)
    recibe el callable y prompt_toolkit convierte su salida a texto formateado.
    """
    pytest.importorskip("prompt_toolkit")
    from prompt_toolkit.formatted_text import to_formatted_text
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput
    from prompt_toolkit.shortcuts import PromptSession

    fn = B.toolbar_prompt_toolkit(lambda: DATOS, ancho=80, unicode_ok=True)
    with create_pipe_input() as inp:
        sesion = PromptSession(input=inp, output=DummyOutput(),
                               bottom_toolbar=fn)
        assert sesion.bottom_toolbar is fn
        formateado = to_formatted_text(sesion.bottom_toolbar())
        assert "qwythos-9b" in "".join(t for _, t in formateado)


def test_toolbar_sin_estado_no_deja_una_linea_en_blanco():
    """REGRESION: con dict vacio la barra de estado es "" y el pie salia como
    '\\n' + atajos, es decir una primera linea vacia bajo el prompt."""
    fn = B.toolbar_prompt_toolkit(lambda: {}, ancho=60,
                                  contexto_atajos="repl", unicode_ok=True)
    salida = fn()
    assert not salida.startswith("\n")
    assert salida == B.barra_atajos("repl", 60, unicode_ok=True)


def test_ancho_en_CELDAS_no_en_len_con_texto_ancho():
    """CJK cuenta 2 celdas: si alguien midiera con len() la barra se pasaria
    del borde. Se exige el ancho VISUAL exacto y un len() menor."""
    datos = dict(DATOS, modelo="龍龍龍-9b",
                 directorio="/home/テスト")
    for ancho in (40, 80, 200):
        linea = B.barra_estado(datos, ancho, unicode_ok=True)
        assert B._ancho_visual(linea) == ancho, (ancho, linea)
        assert len(linea) < ancho          # hay glifos de 2 celdas de verdad


def test_el_modulo_no_imprime_nada(capsys):
    B.barra_estado(DATOS_PLAN, 100)
    B.barra_atajos("repl")
    B.indicador_modo("plan", "manual")
    B.toolbar_prompt_toolkit(lambda: DATOS)()
    capturado = capsys.readouterr()
    assert capturado.out == "" and capturado.err == ""


# ---------------------------------------------------------------------------
# P5 (2026-08-24): la barra por SECCIONES para el sistema de estilos
# ---------------------------------------------------------------------------
# toolbar_partes da (texto, estilo, seccion) y cli._pie_prompt le pone a cada
# seccion su clase de prompt_toolkit. El contrato: el texto concatenado es
# EXACTAMENTE el string de toolbar_prompt_toolkit (que ahora se apoya en el),
# y con las opciones en None la salida es la de siempre.

SECCIONES_CONOCIDAS = {"modelo", "dir", "rama", "sucio", "ctx", "ctx_alto",
                       "ctx_critico", "tokens", "modo.plan", "modo.auto",
                       "modo.manual", "sep", "relleno", "elip", "salto",
                       "atajo_tecla", "atajo_accion"}


@pytest.mark.parametrize("datos", [DATOS, DATOS_PLAN, {}, dict(DATOS, permiso="bypass"),
                                   dict(DATOS, ctx_usado=120000)])
@pytest.mark.parametrize("ancho", [30, 60, 90, 140])
def test_toolbar_partes_reconstruye_el_string_de_toolbar_prompt_toolkit(datos, ancho):
    for ctx in ("", "repl"):
        partes = B.toolbar_partes(lambda: datos, ancho=ancho, contexto_atajos=ctx,
                                  unicode_ok=True)()
        texto = B.toolbar_prompt_toolkit(lambda: datos, ancho=ancho, contexto_atajos=ctx,
                                         unicode_ok=True)()
        assert "".join(p[0] for p in partes) == texto
        assert all(len(p) == 3 and p[2] in SECCIONES_CONOCIDAS for p in partes), partes
        assert all(p[1] in B.ESTILOS for p in partes)


def test_toolbar_partes_secciones_de_cada_dato():
    partes = B.toolbar_partes(lambda: DATOS_PLAN, ancho=120, contexto_atajos="repl",
                              unicode_ok=True)()
    por_seccion = {}
    for t, _, s in partes:
        por_seccion.setdefault(s, []).append(t)
    assert por_seccion["modo.plan"] == ["PLAN"]
    assert por_seccion["modelo"] == ["qwythos-9b"]
    assert por_seccion["rama"] == ["main"] and por_seccion["sucio"] == ["*"]
    assert por_seccion["ctx"][0].startswith("ctx ")
    assert por_seccion["tokens"] == ["3.2k tok"]
    assert por_seccion["salto"] == ["\n"]
    assert por_seccion["atajo_tecla"][0] == "tab" and por_seccion["atajo_accion"][0] == " completa"
    assert all(t == B._SEP_UNI for t in por_seccion["sep"])


def test_barra_estado_secciones_ctx_alto_y_critico():
    def seccion_ctx(usado):
        secs = B.barra_estado_secciones(dict(DATOS, ctx_usado=usado), 100, unicode_ok=True)
        return {s for t, _, s in secs if t.startswith("ctx ") or t == "/compactar"}
    assert seccion_ctx(12400) == {"ctx"}
    assert seccion_ctx(110000) == {"ctx_alto"}
    assert seccion_ctx(126000) == {"ctx_critico"}


def test_separador_propio_en_barra_y_atajos():
    linea = B.barra_estado(DATOS, 100, unicode_ok=True, sep=" | ")
    assert " | " in linea and B._SEP_UNI not in linea
    assert len(linea) == 100
    atajos = B.barra_atajos("repl", 0, unicode_ok=True, sep=" / ")
    assert atajos.count(" / ") == 4 and B._SEP_UNI not in atajos
    # None = el de siempre
    assert B.barra_estado(DATOS, 100, unicode_ok=True, sep=None) == B.barra_estado(DATOS, 100, unicode_ok=True)


def test_etiquetas_de_la_insignia():
    assert B.indicador_modo("plan", "", {"plan": "PLANIFICANDO"}) == ("PLANIFICANDO", B.EST_PLAN)
    assert B.indicador_modo("plan", "", {"plan": ""}) == ("PLAN", B.EST_PLAN)
    assert B.indicador_modo("ejecutar", "bypass", {"auto": "AUTO"}) == ("AUTO", B.EST_PERMISO_AUTO)
    assert B.indicador_modo("ejecutar", "manual", "basura") == ("manual", B.EST_PERMISO_MANUAL)
    assert B.indicador_modo("ejecutar", "automatico", {"plan": "X"}) == ("", "")
    linea = B.barra_estado(DATOS_PLAN, 100, unicode_ok=True, etiquetas_modo={"plan": "PLANIFICANDO"})
    assert linea.startswith("PLANIFICANDO") and len(linea) == 100


def test_textos_de_los_atajos():
    textos = {"tab": "autocompleta", "historial": "atras", "f2": "vista"}
    atajos = B.barra_atajos("repl", 0, unicode_ok=True, textos=textos)
    assert atajos == ("tab autocompleta · ↑↓ atras · @ archivo · "
                      "/ comandos · f2 vista")
    assert B.barra_atajos("repl", 0, unicode_ok=True, textos={}) == B.barra_atajos("repl", 0, unicode_ok=True)


def test_alineacion_derecha_pega_todo_al_borde():
    izq = B.barra_estado(DATOS, 100, unicode_ok=True)
    der = B.barra_estado(DATOS, 100, unicode_ok=True, alineacion="derecha")
    assert len(der) == 100 and der.startswith(" ") and not der.endswith(" ")
    assert der.lstrip().startswith("qwythos-9b") and der.endswith("3.2k tok")
    assert izq != der
    for ancho in (20, 45, 80):
        assert B._ancho_visual(B.barra_estado(DATOS, ancho, unicode_ok=True, alineacion="derecha")) <= ancho


def test_opciones_del_toolbar_por_callable_y_apagados():
    op = {"sep": " | ", "etiquetas_modo": {"plan": "P"}, "textos_atajos": {"tab": "tabula"}}
    partes = B.toolbar_partes(lambda: DATOS_PLAN, ancho=100, contexto_atajos="repl",
                              unicode_ok=True, opciones=lambda: op)()
    texto = "".join(p[0] for p in partes)
    assert texto.startswith("P | qwythos-9b") and "tab tabula" in texto
    assert texto.split("\n")[1].count(B._SEP_UNI) == 4, "sep_atajos aparte del sep de la barra"
    solo_atajos = B.toolbar_partes(lambda: DATOS, ancho=100, contexto_atajos="repl",
                                   unicode_ok=True, opciones={"estado": False})()
    assert "".join(p[0] for p in solo_atajos) == B.barra_atajos("repl", 100, unicode_ok=True)
    solo_estado = B.toolbar_partes(lambda: DATOS, ancho=100, contexto_atajos="repl",
                                   unicode_ok=True, opciones={"atajos": False})()
    assert "".join(p[0] for p in solo_estado) == B.barra_estado(DATOS, 100, unicode_ok=True)
    assert B.toolbar_partes(lambda: DATOS, ancho=100, opciones={"estado": False, "atajos": False})() == []


def test_opciones_que_lanzan_no_rompen_el_prompt():
    def explota():
        raise RuntimeError("registro roto")
    assert B.toolbar_partes(lambda: DATOS, ancho=100, opciones=explota)() == []
    assert B.toolbar_partes(lambda: DATOS, ancho=100, opciones=lambda: "basura")() != []
    assert B.toolbar_partes(explota, ancho=100)() == []
