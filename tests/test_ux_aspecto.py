# -*- coding: utf-8 -*-
"""El sistema de estilos por elemento (cognia/ux/aspecto.py) y su regla
numero uno: el DEFAULT es byte-identico al aspecto actual.

P0 (2026-08-24): SOLO el golden. Los snapshots de tests/golden/aspecto/*.ansi
se tomaron con el repo sin tocar (scripts/aspecto_snapshots.py) y este test
los regenera con las MISMAS funciones y compara los bytes. Cualquier paso
posterior (P1-P13) que cambie un byte del aspecto por defecto cae aqui, y el
mensaje dice en que byte y si cambio el texto o solo el color.

Ademas (enmienda E5 del critico): el dict literal del PTStyle del prompt,
copiado tal cual de cli._estilo_prompt, para las tres variantes. Es mas fuerte
que el ANSI de prompt_toolkit (un hex vecino cae en la misma celda) y es lo
que A.clases_pt(v) tendra que reproducir en P1.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

pytest.importorskip("rich")
pytest.importorskip("prompt_toolkit")


def _snapshots():
    """Carga scripts/aspecto_snapshots.py por ruta (scripts/ no es paquete)."""
    ruta = REPO / "scripts" / "aspecto_snapshots.py"
    spec = importlib.util.spec_from_file_location("aspecto_snapshots", ruta)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


S = _snapshots()
NOMBRES = list(S.SNAPSHOTS)


# ---------------------------------------------------------------------------
# El contrafactual: los bytes de hoy
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("nombre", NOMBRES)
def test_default_es_byte_identico_al_aspecto_actual(nombre):
    esperado = S.leer(nombre)
    obtenido = S.generar(nombre)
    assert obtenido == esperado, S.describir_diferencia(nombre, esperado, obtenido)


def test_no_hay_golden_huerfano_ni_faltante():
    """Cada snapshot del script tiene su fichero y cada fichero tiene su
    generador: un .ansi sin generador es un golden que nadie compara."""
    en_disco = {p.stem for p in S.GOLDEN.glob("*.ansi")}
    assert en_disco == set(NOMBRES), (
        f"faltan: {set(NOMBRES) - en_disco}; huerfanos: {en_disco - set(NOMBRES)}")


def test_los_snapshots_cubren_las_capacidades_que_importan():
    """Sanidad del instrumento (leccion 'el test que pasa por el motivo
    equivocado'): el golden del prompt tiene que llevar color de 24 bits
    (E5) y el del banner a 120 columnas tiene que pintar la guia (E4)."""
    assert b"38;2;" in S.leer("prompt_marco_100"), "el prompt salio sin truecolor"
    banner_120 = S.limpiar_ansi(S.leer("banner_120").decode("utf-8"))
    assert "Para empezar" in banner_120
    # a 120 la guia va AL LADO del arte: '/hacer' comparte linea con el
    # gato (Braille en blanco U+2800); a 80 va DEBAJO
    assert any("/hacer" in l and "⠀" in l for l in banner_120.splitlines()), \
        "a 120 columnas la guia deberia ir a la derecha del gato"
    banner_80 = S.limpiar_ansi(S.leer("banner_80").decode("utf-8"))
    assert "Para empezar" in banner_80
    assert b"COGNIA" in S.leer("banner_80")


# ---------------------------------------------------------------------------
# E5: el dict literal del prompt, copiado de cli._estilo_prompt (2026-08-24)
# ---------------------------------------------------------------------------

def _clases_pt_literal(variante: str) -> dict:
    """COPIA LITERAL del dict de cli._estilo_prompt. No se importa de cli a
    proposito: si alguien cambia cli, este dict ya no coincide y se ve."""
    from cognia.ux import paleta
    verde = paleta.rampa(variante)
    _MENU = paleta.MENU_PROMPT
    return {
        "":                                        f"{verde['texto']} bold",
        "marco":                                   verde["marco"],
        "cognia":                                  f"{verde['prompt']} bold",
        "flecha":                                  f"{verde['texto']} bold",
        "bottom-toolbar":                          f"noreverse bg:default {verde['marco']}",
        "bottom-toolbar.text":                     f"noreverse bg:default {verde['marco']}",
        "estado":                                  f"noreverse bg:default {verde['estado']}",
        "completion-menu.completion":              f"bg:{_MENU['fondo']} fg:{_MENU['texto']}",
        "completion-menu.completion.current":      f"bg:{_MENU['fondo_activo']} fg:{_MENU['texto_activo']}",
        "completion-menu.meta.completion":         f"bg:{_MENU['fondo']} fg:{_MENU['meta']}",
        "completion-menu.meta.completion.current": f"bg:{_MENU['fondo_activo']} fg:{_MENU['meta_activo']}",
        "scrollbar.background":                    f"bg:{_MENU['scrollbar_fondo']}",
        "scrollbar.button":                        f"bg:{_MENU['scrollbar_boton']}",
    }


LITERAL_OSCURO = {
    "": "#a6ff4d bold",
    "marco": "#4fd010",
    "cognia": "#7ee62a bold",
    "flecha": "#a6ff4d bold",
    "bottom-toolbar": "noreverse bg:default #4fd010",
    "bottom-toolbar.text": "noreverse bg:default #4fd010",
    "estado": "noreverse bg:default #8fbf5f",
    "completion-menu.completion": "bg:#1c1c2e fg:#c8c8d8",
    "completion-menu.completion.current": "bg:#004466 fg:#ffffff",
    "completion-menu.meta.completion": "bg:#1c1c2e fg:#667788",
    "completion-menu.meta.completion.current": "bg:#004466 fg:#aaccdd",
    "scrollbar.background": "bg:#1c1c2e",
    "scrollbar.button": "bg:#334455",
}


@pytest.mark.parametrize("variante", ["oscuro", "claro", "alto_contraste"])
def test_las_reglas_del_prompt_son_el_literal_actual(variante):
    import cognia.cli as C
    reglas = list(C._estilo_prompt(variante).style_rules)
    assert reglas == list(_clases_pt_literal(variante).items())


def test_el_literal_oscuro_tiene_los_hex_de_hoy():
    """Con hex escritos a mano (no derivados de la paleta): si la rampa
    cambia, esto lo dice; el golden de arriba tambien, pero este nombra el
    hex."""
    assert _clases_pt_literal("oscuro") == LITERAL_OSCURO


# ===========================================================================
# P1: el registro (cognia/ux/aspecto.py)
# ===========================================================================
import io  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402

from cognia.ux import aspecto as A  # noqa: E402
from cognia.ux import paleta  # noqa: E402

VARIANTES = ["oscuro", "claro", "alto_contraste"]

# Los 43 ids de la tabla 1.3 del diseno, en su orden.
IDS_DISENO = [
    "banner.arte", "banner.marco", "banner.guia", "banner.linea_modelo",
    "prompt.marco", "prompt.etiqueta", "prompt.flecha", "prompt.texto",
    "prompt.continuacion", "prompt.espera",
    "barra.estado", "barra.estado.secciones", "barra.atajos", "barra.modo",
    "menu.completado", "menu.selector",
    "spinner.tool", "spinner.pensar", "spinner.comando",
    "tool.ok", "tool.error", "tool.curso", "tool.verbo", "tool.objeto",
    "tool.resultado", "tool.intencion",
    "respuesta.texto", "respuesta.markdown", "respuesta.codigo",
    "pensando.prosa", "pensando.plegado",
    "aviso.degradado", "aviso.info", "aviso.error",
    "footer.turno",
    "panel.borde", "panel.titulo", "panel.cuerpo",
    "diff.mas", "diff.menos",
    "separador.regla",
    "sistema.ok", "sistema.detalle",
]
# Las enmiendas VINCULANTES del critico: E2 (busqueda/seleccion), E9 (enlace)
# y E1 (la vista F2 de agentes).
IDS_ENMIENDAS = ["prompt.busqueda", "prompt.seleccion", "enlace",
                 "agentes.acento", "agentes.panel", "agentes.borde", "agentes.texto"]


@pytest.fixture(autouse=True)
def _aspecto_limpio(monkeypatch):
    """Cada test arranca sin overrides ni fichero y sin env que cambie la
    resolucion (tema, remoto, ascii)."""
    for k in ("COGNIA_THEME", "COGNIA_REMOTO", "COGNIA_ASCII", "COGNIA_ANIMACION"):
        monkeypatch.delenv(k, raising=False)
    A.reset()
    yield
    A.reset()


# -- completitud --------------------------------------------------------------

def test_el_registro_son_los_43_del_diseno_mas_las_7_enmiendas():
    assert len(IDS_DISENO) == 43
    assert set(A.REGISTRO) == set(IDS_DISENO) | set(IDS_ENMIENDAS), (
        f"sobran: {set(A.REGISTRO) - set(IDS_DISENO) - set(IDS_ENMIENDAS)}; "
        f"faltan: {(set(IDS_DISENO) | set(IDS_ENMIENDAS)) - set(A.REGISTRO)}")
    assert len(A.REGISTRO) == 50


def test_los_grupos_cubren_cada_id_una_vez_y_en_el_orden_del_registro():
    plano = [id for _, ids in A.GRUPOS for id in ids]
    assert plano == list(A.REGISTRO)
    assert [g for g, _ in A.GRUPOS] == ["banner", "prompt", "barra", "menu", "spinner", "tool",
                                        "respuesta", "pensando", "aviso", "footer", "panel",
                                        "diff", "separador", "sistema", "agentes"]
    for grupo, ids in A.GRUPOS:
        for id in ids:
            assert A.REGISTRO[id].grupo == grupo


def _campos_puestos(est: A.Estilo) -> set:
    return {c for c in A._CAMPOS_ESTILO if c != "estados" and getattr(est, c) is not None}


@pytest.mark.parametrize("id", list(A.REGISTRO))
def test_cada_id_tiene_capacidades_coherentes(id):
    e = A.REGISTRO[id]
    d = e.default
    caps = set(e.caps)
    # ningun default fuera de sus capacidades
    for campo in _campos_puestos(d):
        assert A._CAP_DE_CAMPO[campo] in caps, f"{id}: default '{campo}' sin la capacidad"
    # y un default para las capacidades que lo exigen
    if A.Cap.TEXTO in caps:
        assert d.texto is not None
    if A.Cap.COLOR in caps:
        assert d.color is not None
    if A.Cap.GLIFO in caps:
        assert d.glifo is not None
        if e.glifos:
            assert d.glifo in e.glifos
        else:
            assert d.glifo_ascii is not None or d.glifo.isascii(), f"{id}: glifo sin fallback ascii"
    if A.Cap.POSICION in caps:
        assert e.posiciones and d.posicion in e.posiciones
    if A.Cap.ALINEACION in caps:
        assert e.alineaciones and d.alineacion in e.alineaciones
    if A.Cap.VISIBLE in caps:
        assert d.visible is not None
    if A.Cap.SEPARADOR in caps:
        assert d.separador is not None
    if A.Cap.GRADIENTE in caps:
        assert d.gradiente is not None and len(d.gradiente) == 2
    if A.Cap.ANIMACION in caps:
        assert e.vivo, f"{id}: ANIMACION en un elemento que no esta vivo"
        assert d.animacion is not None and d.animacion.activa is False
    if A.Cap.GLOW in caps:
        assert d.glow is not None and d.glow.intensidad == 0
    # sub-estados: los del default estan declarados
    assert set(d.estados) <= set(e.estados), f"{id}: sub-estados sin declarar"
    assert e.nombre and e.grupo
    assert e.enganchado is False, "E8: nada esta enganchado hasta su paso"


def test_los_contratos_del_remoto_son_los_de_D7():
    contrato = {id for id, e in A.REGISTRO.items() if e.contrato_remoto}
    assert contrato == {"tool.ok", "tool.error", "tool.curso", "tool.resultado",
                        "pensando.prosa", "pensando.plegado", "aviso.degradado", "footer.turno"}


# -- byte-identico: las dos salidas de los consumidores ------------------------

@pytest.mark.parametrize("variante", VARIANTES)
def test_clases_pt_es_el_literal_actual_mas_E2(variante):
    esperado = dict(_clases_pt_literal(variante))
    esperado.update(A.PT_DEFAULTS_E2)
    mio = A.clases_pt(variante)
    assert mio == esperado
    # y en el MISMO orden que el literal (PTStyle respeta el orden)
    assert list(mio)[:len(_clases_pt_literal(variante))] == list(_clases_pt_literal(variante))


def test_E2_emite_los_strings_de_prompt_toolkit():
    from prompt_toolkit.styles.defaults import PROMPT_TOOLKIT_STYLE
    pt = dict(PROMPT_TOOLKIT_STYLE)
    for clase, valor in A.PT_DEFAULTS_E2.items():
        assert pt[clase] == valor, f"{clase}: prompt_toolkit dice {pt[clase]!r}"


@pytest.mark.parametrize("variante", VARIANTES)
def test_tema_rich_es_tema_cli(variante):
    assert A.tema_rich(variante) == paleta.tema_cli(variante)


def test_puerta_P1_prompt_etiqueta_da_el_hex_actual():
    assert A.estilo_resuelto("prompt.etiqueta", "oscuro").color == "#7ee62a"
    assert A.estilo_resuelto("prompt.etiqueta", "claro").color == "#1e5900"
    assert A.estilo_resuelto("prompt.etiqueta").negrita is True


# -- resolucion ---------------------------------------------------------------

@pytest.mark.parametrize("variante", VARIANTES)
def test_todos_los_defaults_resuelven(variante):
    for id in A.REGISTRO:
        r = A.estilo_resuelto(id, variante)
        assert r.variante == variante
        for c in (r.color, r.fondo):
            assert c == "" or c.startswith("#") or c.startswith("ansi"), (id, c)


def test_los_refs_siguen_a_la_variante():
    assert A.resolver_color("@rampa.marco", "oscuro") == paleta.RAMPA["oscuro"]["marco"]
    assert A.resolver_color("@rampa.marco", "claro") == paleta.RAMPA["claro"]["marco"]
    assert A.resolver_color("@menu.fondo", "claro") == paleta.MENU_PROMPT["fondo"]
    assert A.resolver_color("@diff.mas", "alto_contraste") == paleta.DIFF_FONDO["alto_contraste"]["mas"]
    assert A.resolver_color({"oscuro": "#111111", "claro": "#222222", "alto_contraste": "#333333"}, "claro") == "#222222"
    assert A.resolver_color("terminal") == ""
    assert A.resolver_color("@token.mod", "oscuro") == "ansicyan"       # 'bold cyan' -> PT
    assert A.color_rich("ansicyan") == "cyan" and A.color_rich("") == "default"


def test_dim_se_traduce_a_mezcla_hacia_el_fondo():
    """'dim white' (detail en oscuro) no existe en prompt_toolkit: sale como
    hex mezclado hacia el fondo de la variante, y el resuelto lo marca tenue."""
    r = A.estilo_resuelto("sistema.detalle", "oscuro")
    assert r.color.startswith("#") and r.tenue is True
    assert A.contraste(r.color, paleta.FONDO_VARIANTE["oscuro"]) < A.contraste("#c0c0c0", paleta.FONDO_VARIANTE["oscuro"])


def test_el_token_aporta_negrita_e_italica_si_el_elemento_no_dice_nada():
    assert A.estilo_resuelto("banner.marco").estados["titulo"].negrita is True   # marca_fuerte = bold
    assert A.estilo_resuelto("tool.intencion").italica is True
    assert A.estilo_resuelto("sistema.ok").negrita is False


def test_el_glow_derivado_va_hacia_negro_en_claro():
    osc = A.estilo_resuelto("prompt.etiqueta", "oscuro").glow_color
    cla = A.estilo_resuelto("prompt.etiqueta", "claro").glow_color
    assert A.contraste(osc, "#ffffff") < A.contraste(paleta.RAMPA["oscuro"]["prompt"], "#ffffff")
    assert A.contraste(cla, "#000000") < A.contraste(paleta.RAMPA["claro"]["prompt"], "#000000")


def test_el_gradiente_del_banner_resuelve_a_los_extremos_de_la_rampa():
    for v in VARIANTES:
        r = A.estilo_resuelto("banner.arte", v)
        assert r.gradiente == (paleta.RAMPA[v]["profundo"], paleta.RAMPA[v]["matrix"])


# Excepciones DECLARADAS del piso de contraste, con su numero y motivo:
#   menu.completado.meta: #667788 sobre su propio azul #1c1c2e = 3,63. Es la
#     META del completador (la descripcion corta), en el menu que ya existia.
#   menu.selector.descripcion: 'ansibrightblack' (4,17 en Campbell): se elige
#     a proposito un nombre de 16 colores para que lo resuelva la terminal.
#   agentes.borde: #30363d es el gris ESTRUCTURAL de los bordes de la TUI
#     (1,55): no es texto ni una regla que se lea.
BAJO_PISO_ACEPTADO = {
    ("menu.completado", "meta"), ("menu.selector", "descripcion"), ("agentes.borde", ""),
}


@pytest.mark.parametrize("variante", VARIANTES)
def test_los_defaults_pasan_el_piso_de_contraste(variante):
    flojos = []
    for id, e in A.REGISTRO.items():
        r = A.estilo_resuelto(id, variante)
        piso = A.PISO_GRAFICO if e.grafico else A.PISO_TEXTO
        for nombre, rr in [("", r)] + list(r.estados.items()):
            if (id, nombre) in BAJO_PISO_ACEPTADO:
                continue
            est = A.estilo_de(id) if not nombre else A.estilo_de(id).estados.get(nombre, A.Estilo())
            hexa = A.hex_medible(est.color, variante)
            if hexa is None:
                continue
            bg = rr.fondo if rr.fondo.startswith("#") else paleta.FONDO_VARIANTE[variante]
            c = A.contraste(hexa, bg)
            if c < piso:
                flojos.append(f"{id}{'.' + nombre if nombre else ''} {c:.2f} (piso {piso})")
    assert not flojos, f"{variante}: " + "; ".join(flojos)


# -- validacion ruidosa --------------------------------------------------------

def _textos(avisos, nivel=None):
    return [a.texto for a in avisos if nivel is None or a.nivel == nivel]


def test_validar_rechaza_id_desconocido_con_sugerencia():
    av = A.validar({"elementos": {"prompt.etiquta": {"texto": "x"}}})
    assert len(av) == 1 and av[0].nivel == "error"
    assert "prompt.etiqueta" in av[0].texto


def test_validar_rechaza_propiedad_no_soportada_y_lista_las_que_tiene():
    av = A.validar({"elementos": {"respuesta.texto": {"posicion": "arriba"}}})
    assert [a.nivel for a in av] == ["error"]
    assert "no tiene 'posicion'" in av[0].texto and "color" in av[0].texto


def test_validar_rechaza_propiedad_desconocida():
    av = A.validar({"elementos": {"prompt.etiqueta": {"colour": "#fff"}}})
    assert av and av[0].nivel == "error" and "desconocida" in av[0].texto


@pytest.mark.parametrize("color", ["#12345", "rojo", "@rampa.inexistente", "@nada.x", 7,
                                   {"oscuro": "#111111"}])
def test_validar_rechaza_colores_invalidos(color):
    av = A.validar({"elementos": {"prompt.etiqueta": {"color": color}}})
    assert any(a.nivel == "error" for a in av), av


@pytest.mark.parametrize("color", ["#7ee62a", "@rampa.prompt", "@token.ok_cl", "terminal",
                                   "ansibrightcyan", "cyan",
                                   {"oscuro": "#7ee62a", "claro": "#1e5900", "alto_contraste": "#a6ff4d"}])
def test_validar_acepta_colores_validos(color):
    assert not _textos(A.validar({"elementos": {"prompt.etiqueta": {"color": color}}}), "error")


def test_validar_enums_y_rangos():
    doc = {"elementos": {
        "prompt.marco": {"posicion": "diagonal"},
        "banner.arte": {"glow": {"intensidad": 4}, "alineacion": "centro",
                        "animacion": {"velocidad": 9, "ancho": 0, "tipo": "flash", "direccion": "arriba"}},
        "banner.marco": {"glifo": "hexagonal"},
    }}
    errores = _textos(A.validar(doc), "error")
    assert len(errores) == 8, errores
    assert any("ambos | arriba | abajo | ninguno" in t for t in errores)
    assert any("0..3" in t for t in errores)
    assert any("1..5" in t for t in errores)
    assert any("rounded | square" in t for t in errores)


def test_validar_avisa_animacion_en_elemento_no_vivo():
    av = A.validar({"elementos": {"tool.verbo": {"color": "@rampa.solido"}}})
    assert not av
    # tool.* no tiene ANIMACION: error de capacidad. Un vivo=False CON la
    # capacidad no existe en el registro (se comprueba arriba); la regla 5
    # se ejercita sobre un elemento del registro parcheado.
    import dataclasses
    e = A.REGISTRO["tool.verbo"]
    parche = dataclasses.replace(e, caps=e.caps | {A.Cap.ANIMACION})
    A.REGISTRO["tool.verbo"] = parche
    try:
        av = A.validar({"elementos": {"tool.verbo": {"animacion": {"activa": True}}}})
    finally:
        A.REGISTRO["tool.verbo"] = e
    assert [a.nivel for a in av] == ["aviso"] and "no animable" in av[0].texto


def test_validar_avisa_si_apagan_el_banner_pero_lo_acepta():
    av = A.validar({"elementos": {"banner.arte": {"visible": False}}})
    assert [a.nivel for a in av] == ["aviso"] and "identidad" in av[0].texto


def test_validar_avisa_glifo_no_codificable(monkeypatch):
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(io.BytesIO(), encoding="cp1252"))
    av = A.validar({"elementos": {"prompt.flecha": {"glifo": "➤ "}}})
    assert [a.nivel for a in av] == ["aviso"]
    assert "cp1252" in av[0].texto and "'> '" in av[0].texto
    # con un ascii propio en el mismo cambio, lo nombra
    av = A.validar({"elementos": {"prompt.flecha": {"glifo": "❯ ", "glifo_ascii": "$ "}}})
    assert "'$ '" in av[0].texto


def test_validar_avisa_contraste_bajo_con_el_ratio():
    av = A.validar({"elementos": {"sistema.ok": {"color": "#333333"}}})
    assert [a.nivel for a in av] == ["aviso"]
    assert "contraste" in av[0].texto and ":1 en oscuro" in av[0].texto and "4,5" in av[0].texto
    # una regla (grafico) tiene piso 3,0: el marco claro (4,60) pasa
    assert not A.validar({"elementos": {"prompt.marco": {"color": "@rampa.marco"}}})


def test_validar_mide_contra_el_fondo_propio_del_elemento():
    """Blanco sobre el fondo azul del menu pasa; ese mismo fondo como color
    de texto sobre la terminal no."""
    assert not A.validar({"elementos": {"menu.completado": {"color": "#ffffff"}}})
    av = A.validar({"elementos": {"menu.completado": {"color": "#1c1c2e", "fondo": "#1c1c2e"}}})
    assert [a.nivel for a in av] == ["aviso"]


def test_validar_version_mas_nueva_es_error_y_clave_desconocida_es_aviso():
    av = A.validar({"version": A.VERSION_FICHERO + 1})
    assert [a.nivel for a in av] == ["error"] and "actualiza cognia" in av[0].texto
    av = A.validar({"version": 1, "extra": 1})
    assert [a.nivel for a in av] == ["aviso"] and "se conserva" in av[0].texto
    assert _textos(A.validar({"version": "1"}), "error")


def test_validar_sub_estados_y_textos_multiples():
    av = A.validar({"elementos": {"menu.completado": {"estados": {"activo": {"fondo": "#004466"},
                                                                  "hover": {"fondo": "#000000"}}}}})
    assert [a.nivel for a in av] == ["error"] and "hover" in av[0].texto and "activo" in av[0].texto
    av = A.validar({"elementos": {"banner.marco": {"texto": "COGNIA"}}})
    assert [a.nivel for a in av] == ["error"] and "titulo" in av[0].texto
    assert not A.validar({"elementos": {"banner.marco": {"texto": {"titulo": "JARVIS"}}}})
    av = A.validar({"elementos": {"banner.marco": {"texto": {"lema": "x"}}}})
    assert [a.nivel for a in av] == ["error"]
    av = A.validar({"elementos": {"prompt.texto": {"estados": {"x": {}}}}})
    assert "no tiene sub-estados" in av[0].texto


def test_validar_paleta_local_y_global():
    doc = {"paleta": {"lima": "#c8ff7a", "mala": "verde", "1x": "#000000"},
           "global": {"fps": 99, "respuesta_sangria": 2, "glifos": "emoji", "otra": 1},
           "elementos": {"prompt.etiqueta": {"color": "@mi.lima"},
                         "prompt.flecha": {"color": "@mi.no_existe"}}}
    av = A.validar(doc)
    err = _textos(av, "error")
    assert any("paleta.mala" in t for t in err)
    assert any("paleta.1x" in t for t in err)
    assert any("global.fps" in t for t in err)
    assert any("global.glifos" in t for t in err)
    assert any("@mi.no_existe" in t for t in err)
    assert not any("@mi.lima" in t for t in err)
    assert any("global.otra" in t for t in _textos(av, "aviso"))
    # validar no deja la paleta local instalada
    assert A._estado["paleta_local"] == {}


# -- escritura en memoria, glifo, texto ---------------------------------------

def test_poner_escribe_convierte_y_sube_la_version():
    v0 = A.version()
    assert A.poner("prompt.etiqueta", "texto", "jarvis") == []
    assert A.texto("prompt.etiqueta") == "jarvis" and A.version() == v0 + 1
    assert A.poner("prompt.etiqueta", "glow.intensidad", "2") == []
    assert A.estilo_de("prompt.etiqueta").glow == A.Glow(color=None, intensidad=2)
    assert A.poner("prompt.marco", "animacion.activa", "on") == []
    assert A.estilo_de("prompt.marco").animacion.activa is True
    assert A.poner("prompt.marco", "animacion.cada_s", "1.5") == []
    assert A.estilo_de("prompt.marco").animacion.cada_s == 1.5
    assert A.poner("menu.completado", "estados.activo.fondo", "#004466") == []
    assert A.estilo_resuelto("menu.completado").estados["activo"].fondo == "#004466"
    assert A.poner("banner.marco", "texto.titulo", "JARVIS") == []
    assert A.texto("banner.marco", "titulo") == "JARVIS"
    assert A.texto("banner.marco", "subtitulo") == "sistema cognitivo local"
    assert A.cambios("prompt.etiqueta") == {"texto": "jarvis", "glow": {"intensidad": 2}}


def test_poner_con_error_no_escribe():
    v0 = A.version()
    av = A.poner("prompt.etiqueta", "color", "rojo")
    assert av and av[0].nivel == "error"
    assert A.version() == v0 and not A.tiene_override("prompt.etiqueta")
    av = A.poner("banner.marco", "texto", "X")
    assert av[0].nivel == "error" and "texto.<clave>" in av[0].texto
    with pytest.raises(KeyError, match="parecidos: prompt.etiqueta"):
        A.poner("prompt.etiquta", "texto", "x")


def test_reset_vuelve_al_default():
    A.poner("prompt.etiqueta", "texto", "jarvis")
    A.poner("prompt.flecha", "glifo", ">> ")
    A.reset("prompt.etiqueta")
    assert A.texto("prompt.etiqueta") == "cognia" and A.glifo("prompt.flecha") == ">> "
    A.reset()
    assert A.glifo("prompt.flecha") == "➤ "


def test_glifo_elige_por_encoding_y_env(monkeypatch):
    assert A.glifo("prompt.marco") == "─"
    assert A.glifo("footer.turno", "error") == "✗"
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(io.BytesIO(), encoding="cp1252"))
    assert A.glifo("prompt.marco") == "-"
    assert A.glifo("prompt.flecha") == "> "
    assert A.glifo("footer.turno", "error") == "x"
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(io.BytesIO(), encoding="utf-8"))
    monkeypatch.setenv("COGNIA_ASCII", "1")
    assert A.glifo("tool.ok") == "+"
    monkeypatch.setenv("COGNIA_ASCII", "0")
    assert A.glifo("tool.ok") == "●"
    assert A.separador("barra.estado") == " · "
    monkeypatch.setenv("COGNIA_ASCII", "1")
    assert A.separador("barra.estado") == " | "


def test_glifo_con_override_cae_a_su_ascii_si_no_codifica(monkeypatch):
    A.poner("prompt.flecha", "glifo", "❯ ")
    A.poner("prompt.flecha", "glifo_ascii", "$ ")
    assert A.glifo("prompt.flecha") == "❯ "
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(io.BytesIO(), encoding="cp1252"))
    assert A.glifo("prompt.flecha") == "$ "


def test_bajo_remoto_los_contratos_vuelven_al_default(monkeypatch):
    A.poner("tool.ok", "glifo", "✔")
    A.poner("aviso.degradado", "texto.degradado", "roto — ")
    A.poner("prompt.flecha", "glifo", ">> ")
    assert A.glifo("tool.ok") == "✔"
    monkeypatch.setenv("COGNIA_REMOTO", "1")
    assert A.glifo("tool.ok") == "●"                      # contrato: default
    assert A.texto("aviso.degradado", "degradado") == "degradado — "
    assert A.estilo_resuelto("tool.ok").glifo == "●"
    assert A.glifo("prompt.flecha") == ">> "                  # no es contrato: se respeta


def test_texto_exige_clave_en_los_multiples():
    with pytest.raises(KeyError, match="pide una clave"):
        A.texto("banner.guia")
    with pytest.raises(KeyError, match="clave de texto desconocida"):
        A.texto("banner.guia", "lema")
    assert A.texto("banner.guia", "cabecera") == "Para empezar"
    assert A.texto("prompt.continuacion") == "   "
    assert A.textos("prompt.etiqueta") == {"texto": "cognia"}
    assert A.textos("barra.modo") == {"plan": "PLAN", "auto": "auto", "manual": "manual"}
    assert A.visible("banner.arte") is True and A.visible("prompt.texto") is True


def test_elemento_desconocido_es_KeyError_con_parecidos():
    with pytest.raises(KeyError, match="ids parecidos: .*banner.marco"):
        A.elemento("banner.marcos")


# -- overrides llegan a las salidas -------------------------------------------

def test_clases_pt_refleja_overrides_y_agrega_clases_solo_si_las_hay():
    A.poner("prompt.etiqueta", "color", "#ff00ff")
    A.poner("prompt.etiqueta", "italica", True)
    A.poner("prompt.marco", "fondo", "#101010")
    d = A.clases_pt("oscuro")
    assert d["cognia"] == "#ff00ff bold italic"
    assert d["bottom-toolbar"] == "noreverse bg:#101010 #4fd010"
    assert "estado.ctx-alto" not in d
    A.poner("barra.estado.secciones", "estados.ctx_alto.color", "@token.warn_cl")
    d = A.clases_pt("oscuro")
    assert d["estado.ctx-alto"] == "noreverse bg:default ansiyellow"
    assert d["estado.modelo"] == "noreverse bg:default #8fbf5f"
    A.poner("prompt.busqueda", "color", "#ffffff")
    A.poner("prompt.seleccion", "fondo", "#004466")
    d = A.clases_pt("oscuro")
    assert d["prompt.search"] == "noinherit fg:#ffffff"
    assert d["selected"] == "bg:#004466"


def test_tema_rich_retine_el_token_del_elemento():
    A.poner("sistema.ok", "color", "#ff00ff")
    t = A.tema_rich("oscuro")
    assert t["ok_cl"] == "#ff00ff" and t["ok"] == "#ff00ff"
    assert t["detail"] == paleta.tema_cli("oscuro")["detail"]
    # un modificador sin tocar el color conserva el string del token (el
    # dim de 'italic dim white' no se re-mezcla)
    assert A.poner("tool.intencion", "negrita", True) == []
    assert A.tema_rich("oscuro")["intencion"] == "bold dim italic white"
    # markdown solo lo que se toco
    A.poner("respuesta.markdown", "estados.h1.color", "#ffaa00")
    t = A.tema_rich("oscuro")
    assert t["markdown.h1"] == "#ffaa00" and "markdown.h2" not in t
    # el resto del tema sigue intacto
    for k, v in paleta.tema_cli("oscuro").items():
        if k not in ("ok_cl", "ok", "intencion"):
            assert t[k] == v


def test_variante_activa_sigue_a_COGNIA_THEME(monkeypatch):
    assert A.variante_activa() in VARIANTES
    monkeypatch.setenv("COGNIA_THEME", "claro")
    assert A.variante_activa() == "claro"
    monkeypatch.setenv("COGNIA_THEME", "verde")
    assert A.variante_activa() in VARIANTES


def test_animacion_global_obedece_a_la_env(monkeypatch):
    monkeypatch.setenv("COGNIA_ANIMACION", "0")
    assert A.animacion_global() == (False, "COGNIA_ANIMACION=0")
    monkeypatch.delenv("COGNIA_ANIMACION")
    assert A.animacion_global()[0] is True


def test_el_modulo_no_arrastra_rich_ni_prompt_toolkit_al_importar():
    import subprocess
    codigo = ("import sys; import cognia.ux.aspecto; "
              "print(sorted(m for m in sys.modules if m.split('.')[0] in ('rich', 'prompt_toolkit')))")
    out = subprocess.run([sys.executable, "-c", codigo], capture_output=True, text=True,
                         cwd=str(REPO), env={**os.environ, "PYTHONUTF8": "1"})
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "[]", out.stdout
