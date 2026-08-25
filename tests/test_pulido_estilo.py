# -*- coding: utf-8 -*-
"""Pulido visual del sistema /estilo y del editor (2026-08-24, revision a
120 columnas tecleando de verdad). Cada test es UNA pieza del juicio visual:

  1. la barra de atajos del editor cabe en 80/100/120/160 columnas y '?' y
     'Esc' (las dos salidas) se ven siempre; antes eran 192 celdas fijas y a
     120 se cortaba en "^L previ"
  2. los avisos de "/estilo cargar", de cada set y la ayuda no llevan la
     jerga de pasos del plan ("(P9)", "paso P6")
  3. "/estilo lista" no rompe filas: a 120 columnas ninguna pasa de 119
  4. las filas del selector de color caben en el panel flotante (40 y 60)
  5. un elemento GRAFICO a 3,0:1 es 'decorativo', no 'ok'
  6. ningun preset del paquete deja una animacion infinita (repetir=0)
"""
from __future__ import annotations

import json
import re
from types import SimpleNamespace

import pytest

import cognia.cli as cli
from cognia.ux import aspecto as A
from cognia.ux import editor_aspecto as E
from cognia.ux import glow as G
from cognia.ux.editor_aspecto import EditorModelo

_RE_PASO = re.compile(r"\(P\d")


@pytest.fixture(autouse=True)
def _limpio(tmp_path, monkeypatch):
    """Como en test_ux_editor_aspecto: el estilo.json del DUENO no se toca
    (el selector de color aplica al mover y A.poner escribe el fichero)."""
    monkeypatch.setattr(A, "DIR_COGNIA", tmp_path)
    monkeypatch.setattr(A, "RUTA_ESTILO", tmp_path / "estilo.json")
    monkeypatch.setattr(A, "DIR_PRESETS", tmp_path / "estilos")
    for k in ("COGNIA_REMOTO", "COGNIA_THEME", "COGNIA_ASCII", "COGNIA_ANIMACION", "NO_COLOR"):
        monkeypatch.delenv(k, raising=False)
    A.reset()
    G.vaciar_memo()
    yield
    A.reset()


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    """Como el de test_cli_estilo: la salida del CLI capturada como texto
    (markup de rich sin renderizar) y la config del CLI en tmp_path."""
    monkeypatch.setattr(cli, "_CONFIG_PATH", tmp_path / "cfg.json")
    for k in ("COGNIA_ANIMACION", "NO_COLOR", "COGNIA_ESTILO"):
        monkeypatch.delenv(k, raising=False)
    salida, avisos = [], []
    monkeypatch.setattr(cli, "_print_line", lambda t: salida.append(str(t)))
    monkeypatch.setattr(cli, "_aviso_degradado", lambda via, det="": avisos.append((via, det)))
    monkeypatch.setattr(cli, "_theme_idx", 0)
    monkeypatch.setattr(cli, "_persist_setting", lambda k, v: None)
    yield SimpleNamespace(salida=salida, avisos=avisos, tmp=tmp_path,
                          texto=lambda: "\n".join(salida))


def _plano(markup: str) -> str:
    """Quita las etiquetas [tag]...[/tag] del markup de rich: lo que se ve."""
    return re.sub(r"\[/?[a-z_]+\]", "", markup)


# ---------------------------------------------------------------------------
# 1. barra de atajos del editor
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("columnas", [80, 100, 120, 160])
def test_barra_de_atajos_cabe_y_conserva_ayuda_y_salir(columnas):
    # abrir_editor pasa columns-2 como ancho del modelo
    m = EditorModelo(ancho=columnas - 2)
    teclas, _, estado = m.estado_pie().partition("\n")
    assert E._ancho_visual(teclas) <= columnas - 2, (columnas, len(teclas), teclas)
    assert "? ayuda" in teclas and "Esc salir" in teclas
    assert teclas.endswith("Esc salir"), "las salidas van al final, como antes"
    # lo mas usado nunca se cae a 80: editar, guardar
    assert "Enter editar" in teclas and "^S guardar" in teclas


def test_barra_entera_cuando_hay_sitio_y_minima_cuando_no():
    entera = E.barra_atajos_normal(0)
    assert entera.startswith("Tab panel") and entera.endswith("? ayuda  Esc salir")
    assert E.barra_atajos_normal(10_000) == entera
    # ancho ridiculo: solo los fijos, enteros (mejor rebasar que esconder la salida)
    assert E.barra_atajos_normal(5) == "? ayuda  Esc salir"
    # se recorta por atajos ENTEROS: ningun trozo de palabra
    for w in range(20, 200):
        b = E.barra_atajos_normal(w)
        for trozo in b.split("  "):
            assert trozo in [t for t, _ in E._ATAJOS_NORMAL], (w, trozo)


# ---------------------------------------------------------------------------
# 2. sin jerga de pasos
# ---------------------------------------------------------------------------

def test_cargar_preset_avisa_en_castellano_sin_pasos(entorno):
    cli._slash_estilo("cargar neon")
    t = entorno.texto()
    assert "'neon' cargado" in t
    assert "1 propiedad aun sin efecto en esta version (barra.modo.glow)" in t
    assert not _RE_PASO.search(t), t
    assert "enganchado" not in t


def test_set_en_no_enganchado_avisa_sin_pasos(entorno):
    cli._slash_estilo("agentes.texto color #ff00ff")
    t = entorno.texto()
    assert "(guardado)" in t
    assert "1 propiedad aun sin efecto en esta version (agentes.texto.color)" in t
    assert not _RE_PASO.search(t), t


def test_lista_ver_y_ayuda_sin_pasos(entorno):
    cli._slash_estilo("lista")
    cli._slash_estilo("ver agentes.texto")
    cli._slash_estilo("ayuda")
    t = entorno.texto()
    assert "sin efecto" in t
    assert not _RE_PASO.search(t), [l for l in t.splitlines() if _RE_PASO.search(l)]
    assert not _RE_PASO.search(cli._CMD_DETAILS["/estilo"])
    assert "paso P" not in t


def test_sin_efecto_cuenta_en_plural():
    assert cli._estilo_sin_efecto(["b.x"]) == "1 propiedad aun sin efecto en esta version (b.x)"
    assert cli._estilo_sin_efecto(["b.y", "a.x", "a.x"]) == \
        "2 propiedades aun sin efecto en esta version (a.x, b.y)"


# ---------------------------------------------------------------------------
# 3. /estilo lista a 120 columnas
# ---------------------------------------------------------------------------

def test_lista_no_rompe_filas_a_120_columnas(entorno, monkeypatch):
    monkeypatch.setenv("COLUMNS", "120")
    monkeypatch.setenv("LINES", "40")
    cli._slash_estilo("cargar neon")     # con marcas ('*', 'mod') encima
    entorno.salida.clear()
    cli._slash_estilo("lista")
    filas = [_plano(l) for l in entorno.salida]
    assert len(filas) > len(A.REGISTRO)
    largas = [f for f in filas if len(f) > 119]
    assert not largas, largas
    # la fila de un elemento con muchas caps se corto con elipsis, no se partio
    assert any("…" in f for f in filas), "ninguna fila se recorto: el test no mide nada"
    for id in A.REGISTRO:
        assert any(f.startswith(f"  {id:<24} ") for f in filas), id


def test_lista_a_80_columnas_tampoco_rompe(entorno, monkeypatch):
    monkeypatch.setenv("COLUMNS", "80")
    monkeypatch.setenv("LINES", "40")
    cli._slash_estilo("lista")
    filas = [_plano(l) for l in entorno.salida]
    assert not [f for f in filas if len(f) > 79]


@pytest.mark.parametrize("columnas", [80, 100, 120])
def test_lista_recorta_las_caps_en_un_separador_no_a_mitad_de_palabra(entorno, monkeypatch, columnas):
    """Regresion (revision 2026-08-25): a 80 columnas 'agentes.acento' salia
    'color, f… sin efecto' porque caps[:cupo-1] cortaba por celdas. Ahora se
    corta en el ultimo ', ' que cabe: todo lo que precede a la elipsis son
    caps COMPLETAS."""
    monkeypatch.setenv("COLUMNS", str(columnas))
    monkeypatch.setenv("LINES", "40")
    cli._slash_estilo("lista")
    filas = [_plano(l) for l in entorno.salida]
    validas = {c.value for c in A.Cap}
    recortes = []
    for f in filas:
        # las caps van tras DOS espacios, en minusculas, y terminan en '…'
        for trozo in re.findall(r"  ([a-z, ]+)…", f):
            recortes.append((f, trozo))
            for cap in trozo.split(", "):
                assert cap in validas, f"cap partida {cap!r} en: {f}"
    assert recortes, "ninguna fila recorto sus caps: el test no mide nada"
    assert not [f for f in filas if len(f) > columnas - 1]


# ---------------------------------------------------------------------------
# 4. selector de color: filas dentro del panel
# ---------------------------------------------------------------------------

def _abrir_color(id: str, ancho_flotante: int, **kw) -> EditorModelo:
    m = EditorModelo(ancho=ancho_flotante + 4, **kw)
    assert m.ancho_flotante == ancho_flotante
    m.ir_a(id)
    m.panel = "propiedades"
    m.cursor_props = next(i for i, p in enumerate(m.props()) if p.ruta == "color")
    m.tecla("enter")
    assert m.modo == "color"
    return m


@pytest.mark.parametrize("panel", [40, 60])
@pytest.mark.parametrize("id", ["prompt.etiqueta", "banner.arte", "tool.ok"])
def test_filas_del_selector_de_color_caben_en_el_panel(panel, id):
    m = _abrir_color(id, panel)
    for _ in range(3):                         # refs, mi, hex
        filas = m.filas_flotante()
        assert filas
        for texto, _c, _s in filas:
            assert E._ancho_visual(texto) <= panel, (panel, m.color.get("pestana"), texto)
        m.tecla("tab")
    # y en la pestana hex con un color valido tecleado
    for _ in range(4):
        if m.color.get("pestana") == "hex":
            break
        m.tecla("tab")
    assert m.color.get("pestana") == "hex"
    m.color["buffer"] = ""
    for ch in "#3fb950":
        m.tecla(ch)
    for texto, _c, _s in m.filas_flotante():
        assert E._ancho_visual(texto) <= panel, texto
        assert "ok" in texto or "!" in texto or "decorativo" in texto, "el veredicto no se cae"


def test_a_60_el_veredicto_de_contraste_se_ve_entero():
    m = _abrir_color("prompt.etiqueta", 60)
    filas = [t for t, _c, _s in m.filas_flotante() if "@rampa.prompt" in t]
    assert filas and filas[0].rstrip().endswith("ok"), filas
    assert ":1" in filas[0], "al menos un ratio visible"


def test_ratios_recorta_variantes_pero_conserva_el_veredicto():
    m = EditorModelo(ancho=80)
    m.ir_a("prompt.etiqueta")
    m.variante_preview = "oscuro"
    entero = m._ratios("@rampa.prompt")           # pasa en las 3 variantes
    assert entero.count(":1") == 3 and entero.endswith("  ok"), entero
    corto = m._ratios("@rampa.prompt", 20)
    assert corto.endswith("ok") and corto.count(":1") == 1, corto
    assert "oscuro" in corto, "sin '!' se queda la variante previsualizada"
    assert m._ratios("@rampa.prompt", 2) == "ok"
    # con '!' se queda la variante que SUSPENDE (#3fb950 falla en claro: 2,5:1)
    flojo = m._ratios("#3fb950", 20)
    assert flojo.endswith("!") and "claro" in flojo and "oscuro" not in flojo, flojo


def test_ancho_flotante_se_deriva_del_ancho_o_se_impone():
    assert EditorModelo(ancho=78).ancho_flotante == 74
    assert EditorModelo(ancho=10).ancho_flotante == 20, "piso 20: menos no es un panel"
    assert EditorModelo(ancho=78, ancho_flotante=50).ancho_flotante == 50


# ---------------------------------------------------------------------------
# 5. decorativo a 3,0:1
# ---------------------------------------------------------------------------

def _color_a_ratio(fondo: str, objetivo: float, tol: float = 0.05) -> str:
    """Un gris cuyo contraste sobre `fondo` esta a `objetivo` (+-tol)."""
    mejor, dist = None, 99.0
    for v in range(0, 256):
        h = f"#{v:02x}{v:02x}{v:02x}"
        d = abs(A.contraste(h, fondo) - objetivo)
        if d < dist:
            mejor, dist = h, d
    assert dist <= tol, (objetivo, mejor, dist)
    return mejor


def test_grafico_a_piso_grafico_es_decorativo_no_ok():
    m = EditorModelo(ancho=80)
    m.ir_a("banner.arte")
    assert A.REGISTRO["banner.arte"].grafico
    m.variante_preview = "oscuro"
    fondo = m._fondo_del_elemento("oscuro")
    gris = _color_a_ratio(fondo, 3.0)
    # el mismo gris en las tres variantes, para que ninguna caiga bajo 3,0
    valor = {"oscuro": gris, "claro": _color_a_ratio(m._fondo_del_elemento("claro"), 3.05),
             "alto_contraste": _color_a_ratio(m._fondo_del_elemento("alto_contraste"), 3.05)}
    r = m._ratios(valor)
    assert "decorativo" in r and not r.endswith("ok") and "!" not in r, r
    assert r.endswith("decorativo (3,0)")
    # bajo el piso grafico sigue siendo '!'
    assert m._ratios(_color_a_ratio(fondo, 2.0)).endswith("!")
    # y un grafico con contraste de texto (>= 4,5 en las 3 variantes) si es 'ok'
    assert m._ratios("@rampa.prompt").endswith("ok")


def test_texto_a_3_es_flojo_no_decorativo():
    m = EditorModelo(ancho=80)
    m.ir_a("prompt.etiqueta")
    assert not A.REGISTRO["prompt.etiqueta"].grafico
    gris = _color_a_ratio(m._fondo_del_elemento("oscuro"), 3.0)
    r = m._ratios(gris)
    assert r.endswith("!") and "decorativo" not in r, r


def test_la_fila_de_propiedad_color_tambien_dice_decorativo():
    m = EditorModelo(ancho=120)
    m.ir_a("banner.arte")
    gris = {v: _color_a_ratio(m._fondo_del_elemento(v), 3.05) for v in A.ORDEN_VARIANTES}
    A.poner("banner.arte", "color", gris)      # estilo.json en tmp (fixture autouse)
    m.panel = "propiedades"
    m.cursor_props = next(i for i, p in enumerate(m.props()) if p.ruta == "color")
    filas = [t for t, _c, _s in m.filas_propiedades()]
    assert any("decorativo" in f for f in filas), filas


# ---------------------------------------------------------------------------
# 6. presets del paquete: ninguna animacion infinita
# ---------------------------------------------------------------------------

def _animaciones(doc: dict):
    for id, props in (doc.get("elementos") or {}).items():
        a = props.get("animacion")
        if isinstance(a, dict):
            yield id, a
        for est, sub in (props.get("estados") or {}).items():
            if isinstance(sub, dict) and isinstance(sub.get("animacion"), dict):
                yield f"{id}.estados.{est}", sub["animacion"]


def test_ningun_preset_del_paquete_deja_una_animacion_infinita():
    vistas = 0
    for nombre in A.PRESETS_PAQUETE:
        doc = A.leer_doc(A.DIR_PRESETS_PAQUETE / f"{nombre}.json")
        for id, a in _animaciones(doc):
            if not a.get("activa"):
                continue
            vistas += 1
            assert a.get("repetir", 0) > 0, f"{nombre}: {id} anima para siempre (repetir 0)"
    assert vistas >= 5, "neon anima al menos 5 elementos; si no, el test no mide"


def test_neon_resuelto_no_repite_infinito_y_sigue_validando():
    A.cargar_preset("neon")
    assert not A.errores(A.ultimos_avisos()) and A.ultimos_avisos() == []
    for id in ("prompt.etiqueta", "spinner.pensar", "spinner.tool", "banner.arte", "prompt.marco"):
        a = A.estilo_de(id).animacion
        assert a is not None and a.activa and a.repetir == 3, (id, a)
    assert A.estilo_de("prompt.etiqueta").animacion.cada_s == 6
