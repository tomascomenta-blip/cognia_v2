"""
tests/test_diff_render.py
=========================
Diff delta-style (plan B3): render_diff colorea el unified y resalta los
spans cambiados intra-linea; resumen_diff da la linea compacta '+N -M'.

Todo es funcion pura sin terminal: se inspeccionan los Text/Group devueltos
(spans y estilos) y el export de una Console(record=True). Sin GPU.
"""

import pytest

from cognia.console import diff_render as dr
from cognia.console.diff_render import render_diff, resumen_diff

rich = pytest.importorskip("rich")
from rich.console import Console  # noqa: E402


# ── helpers ────────────────────────────────────────────────────────────────

def _partes(grupo):
    """Los Text hijos del Group devuelto por render_diff."""
    return list(grupo.renderables)


def _spans_con_estilo(parte, estilo):
    """[(texto_del_span, estilo)] de los spans de un Text con ese estilo."""
    plain = parte.plain
    return [plain[s.start:s.end] for s in parte.spans if s.style == estilo]


def _export(grupo, width=100):
    con = Console(record=True, width=width, force_terminal=False)
    con.print(grupo)
    return con.export_text()


# ── render_diff ────────────────────────────────────────────────────────────

def test_cambio_intra_linea_marca_spans():
    # el par reemplazado adyacente debe resaltar SOLO la palabra que cambio
    viejo = "x = calcular(a, b)\notra linea\n"
    nuevo = "x = calcular(a, c)\notra linea\n"
    g = render_diff(viejo, nuevo, ruta="mod.py")
    assert g is not None
    partes = _partes(g)
    fuertes_menos = []
    fuertes_mas = []
    for p in partes:
        fuertes_menos += _spans_con_estilo(p, dr._ST_MENOS_INTRA)
        fuertes_mas += _spans_con_estilo(p, dr._ST_MAS_INTRA)
    # 'b)' marcado en la linea vieja, 'c)' en la nueva; lo igual NO se marca
    assert any("b)" in s for s in fuertes_menos), fuertes_menos
    assert any("c)" in s for s in fuertes_mas), fuertes_mas
    assert not any("calcular" in s for s in fuertes_menos + fuertes_mas)
    # y el contenido completo sigue presente en el export
    texto = _export(g)
    assert "-x = calcular(a, b)" in texto
    assert "+x = calcular(a, c)" in texto
    assert "mod.py" in texto  # cabeceras a/mod.py b/mod.py


def test_insercion_pura_solo_verdes():
    viejo = "a\nb\n"
    nuevo = "a\nb\nc\n"
    g = render_diff(viejo, nuevo)
    assert g is not None
    cuerpo = _partes(g)[2:]  # saltar cabeceras ---/+++
    con_menos = [p for p in cuerpo
                 if p.style == dr._ST_MENOS
                 or _spans_con_estilo(p, dr._ST_MENOS_INTRA)]
    assert con_menos == []
    verdes = [p for p in cuerpo if p.style == dr._ST_MAS]
    assert len(verdes) == 1 and verdes[0].plain == "+c"


def test_borrado_puro_solo_rojos():
    viejo = "a\nb\nc\n"
    nuevo = "a\nc\n"
    g = render_diff(viejo, nuevo)
    assert g is not None
    cuerpo = _partes(g)[2:]
    con_mas = [p for p in cuerpo
               if p.style == dr._ST_MAS
               or _spans_con_estilo(p, dr._ST_MAS_INTRA)]
    assert con_mas == []
    rojos = [p for p in cuerpo if p.style == dr._ST_MENOS]
    assert len(rojos) == 1 and rojos[0].plain == "-b"


def test_identicos_devuelve_none():
    txt = "una\ndos\ntres\n"
    assert render_diff(txt, txt, ruta="igual.py") is None


def test_lineas_disjuntas_sin_resaltado_intra():
    # par -/+ casi sin nada en comun: resaltar todo seria ruido -> va plano
    viejo = "aaaa bbbb cccc\n"
    nuevo = "xxxx yyyy zzzz\n"
    g = render_diff(viejo, nuevo)
    assert g is not None
    for p in _partes(g):
        assert _spans_con_estilo(p, dr._ST_MENOS_INTRA) == []
        assert _spans_con_estilo(p, dr._ST_MAS_INTRA) == []


def test_console_param_se_acepta():
    # la firma acepta console= (reservado); no debe explotar ni usarse
    g = render_diff("a\n", "b\n", console=object())
    assert g is not None


# ── resumen_diff ───────────────────────────────────────────────────────────

def test_resumen_cuenta_bien():
    viejo = "uno\ndos\ntres\n"
    nuevo = "uno\nDOS\ntres\ncuatro\ncinco\n"
    # dos->DOS es -1/+1; cuatro y cinco son +2 => +3 -1
    assert resumen_diff(viejo, nuevo) == "+3 \u22121"


def test_resumen_sin_cambios_vacio():
    txt = "igual\n"
    assert resumen_diff(txt, txt) == ""


def test_resumen_no_cuenta_cabeceras_ni_hunks():
    # una linea agregada que empieza con '+' no debe confundirse con '+++'
    viejo = "a\n"
    nuevo = "a\n++ raro\n"
    assert resumen_diff(viejo, nuevo) == "+1 \u22120"


# ── degradacion sin rich ───────────────────────────────────────────────────

def test_sin_rich_degrada_a_none(monkeypatch):
    monkeypatch.setattr(dr, "_HAS_RICH", False)
    assert render_diff("a\n", "b\n") is None
    # resumen_diff no depende de rich: sigue contando igual
    assert resumen_diff("a\n", "b\n") == "+1 \u22121"
