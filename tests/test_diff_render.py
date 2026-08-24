"""
tests/test_diff_render.py
=========================
Diff delta-style (plan B3) + decision 12 del dueno (2026-08-17): render_diff
pinta la linea ENTERA con fondo verde/rojo a todo el ancho, con el + o el -
al margen, y resalta los spans cambiados intra-linea con un fondo mas fuerte
del mismo tono (ya no 'reverse'). resumen_diff da la linea compacta '+N -M'.

PUNTOS 2 y 3 DEL JUICIO VISUAL (2026-08-17), lo que se agrego aqui:
  * `render_bloque` — la mitad que pinta, sin cabeceras de unified, para que el
    preview del agente (ux/renderer.py) use EL MISMO lenguaje visual en vez de
    su '+ linea' de texto pelado. Un solo sitio que sabe pintar un diff.
  * las bandas y las marcas salen del TEMA por variante, no de una mezcla local
    sobre #0d1117: con '/tema claro' el diff era una isla negra en una terminal
    blanca. `variante_activa` decide cual toca.
  * la asimetria: '+' y '-' medidos sobre SU banda, en las tres variantes.

Todo es funcion pura sin terminal: se inspeccionan los renderables devueltos
(Padding con estilo de fondo, Text con spans) y los SEGMENTOS que produce una
Console de ancho fijo. El contraste WCAG se MIDE aqui, no se declara. Sin GPU.
"""

import importlib.util
import io
from pathlib import Path

import pytest

from cognia.console import diff_render as dr
from cognia.console.diff_render import (render_bloque, render_diff,
                                        resumen_diff, variante_activa)
from cognia.ux import paleta

rich = pytest.importorskip("rich")
from rich.console import Console  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
VARIANTES = ["oscuro", "claro", "alto_contraste"]


@pytest.fixture(autouse=True)
def _sin_tema_heredado(monkeypatch):
    """COGNIA_THEME manda sobre la variante del diff: los tests que no lo
    fijan tienen que medir el tema por defecto, no el que tenga puesto la
    maquina que corre la suite."""
    monkeypatch.delenv("COGNIA_THEME", raising=False)


def _medidor():
    """scripts/contraste_tema.py — el MISMO instrumento de la entrega, que
    sabe resolver 'default'/'red' con la tabla ANSI de cada variante."""
    ruta = REPO / "scripts" / "contraste_tema.py"
    spec = importlib.util.spec_from_file_location("contraste_tema", ruta)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── helpers ────────────────────────────────────────────────────────────────

def _partes(grupo):
    """Los renderables hijos del Group devuelto por render_diff."""
    return list(grupo.renderables)


def _texto(parte):
    """El Text de dentro: las lineas -/+ vienen envueltas en un Padding."""
    return getattr(parte, "renderable", parte)


def _fondo(parte):
    """El estilo de fondo del Padding, o None si es un Text pelado."""
    if not hasattr(parte, "renderable"):
        return None
    return getattr(parte, "style", None)


def _spans_con_estilo(parte, estilo):
    """[texto_del_span] de los spans de un Text con ese estilo."""
    t = _texto(parte)
    plain = t.plain
    return [plain[s.start:s.end] for s in t.spans if s.style == estilo]


def _export(grupo, width=100):
    con = Console(record=True, width=width, force_terminal=False)
    con.print(grupo)
    return con.export_text()


def _lineas_segmentadas(grupo, width=100):
    """[[Segment, ...], ...] tal y como se pintarian a `width` columnas."""
    con = Console(width=width, force_terminal=True, color_system="truecolor",
                  legacy_windows=False, file=io.StringIO())
    return con.render_lines(grupo, con.options.update(width=width), pad=False)


def _relativa(hexa: str) -> float:
    def canal(v):
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    h = hexa.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * canal(r) + 0.7152 * canal(g) + 0.0722 * canal(b)


def _contraste(a: str, b: str) -> float:
    la, lb = _relativa(a), _relativa(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


# ── render_diff: lo de siempre (delta-style) ───────────────────────────────

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
    con_menos = [p for p in cuerpo if _fondo(p) == dr._ST_LINEA_MENOS]
    assert con_menos == []
    verdes = [p for p in cuerpo if _fondo(p) == dr._ST_LINEA_MAS]
    assert len(verdes) == 1 and _texto(verdes[0]).plain == "+c"


def test_borrado_puro_solo_rojos():
    viejo = "a\nb\nc\n"
    nuevo = "a\nc\n"
    g = render_diff(viejo, nuevo)
    assert g is not None
    cuerpo = _partes(g)[2:]
    con_mas = [p for p in cuerpo if _fondo(p) == dr._ST_LINEA_MAS]
    assert con_mas == []
    rojos = [p for p in cuerpo if _fondo(p) == dr._ST_LINEA_MENOS]
    assert len(rojos) == 1 and _texto(rojos[0]).plain == "-b"


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
    # pero el fondo de la linea SI se pinta (el fondo no depende del intra)
    fondos = {_fondo(p) for p in _partes(g)[2:]}
    assert dr._ST_LINEA_MAS in fondos and dr._ST_LINEA_MENOS in fondos


def test_console_param_se_acepta():
    # la firma acepta console= (reservado); no debe explotar ni usarse
    g = render_diff("a\n", "b\n", console=object())
    assert g is not None


# ── decision 12: FONDO a todo el ancho ─────────────────────────────────────

def test_los_dos_fondos_son_distintos_y_salen_del_TEMA():
    from cognia.ux.paleta import SUPERFICIE
    assert dr._FONDO_MAS != dr._FONDO_MENOS
    # ya no hay mezcla alfa local: las cuatro bandas son las del tema, asi que
    # no hay forma de que el diff se desincronice de '/tema' (punto 3)
    banda = paleta.diff_fondos("oscuro")
    assert dr._FONDO_MAS == banda["mas"]
    assert dr._FONDO_MENOS == banda["menos"]
    assert dr._FONDO_MAS_INTRA == banda["mas_intra"]
    assert dr._FONDO_MENOS_INTRA == banda["menos_intra"]
    # el fondo tiene que ser TENUE: si se acercara al semantico pleno el
    # codigo de encima seria ilegible en un diff largo
    assert _contraste(dr._FONDO_MAS, SUPERFICIE["fondo"]) < 2.0
    assert _contraste(dr._FONDO_MENOS, SUPERFICIE["fondo"]) < 2.0


def test_las_bandas_oscuras_son_LAS_HISTORICAS():
    """El tema por defecto no puede cambiar NI UN PIXEL al mover las bandas a
    la paleta: los cuatro hex de 'oscuro' tienen que seguir siendo la mezcla
    alfa que este modulo calculaba (ok al 20%/45%, error al 18%/45% sobre
    #0d1117). Sin esto, "no cambia nada en oscuro" es una afirmacion sin
    verificador."""
    from cognia.ux.paleta import SEMANTICO, SUPERFICIE

    def mezcla(frente, fondo, alfa):
        f, d = frente.lstrip("#"), fondo.lstrip("#")
        return "#" + "".join(
            f"{round(int(f[i:i+2], 16) * alfa + int(d[i:i+2], 16) * (1-alfa)):02x}"
            for i in (0, 2, 4))

    fondo = SUPERFICIE["fondo"]
    banda = paleta.diff_fondos("oscuro")
    assert banda["mas"] == mezcla(SEMANTICO["ok"], fondo, 0.20)
    assert banda["menos"] == mezcla(SEMANTICO["error"], fondo, 0.18)
    assert banda["mas_intra"] == mezcla(SEMANTICO["ok"], fondo, 0.45)
    assert banda["menos_intra"] == mezcla(SEMANTICO["error"], fondo, 0.45)


@pytest.mark.parametrize("variante", VARIANTES)
def test_contraste_minimo_45_de_todo_lo_que_se_pinta(variante):
    """Requisito 1, EN LAS TRES VARIANTES: la marca del margen y el contenido
    pasan 4,5:1 sobre la banda que tienen debajo.

    El contenido se mide como lo ve la terminal: el token 'respuesta' resuelto
    con la tabla ANSI de la variante ('default' es #cccccc en Campbell y
    #22221f en una terminal clara). Medirlo con SEMANTICO['texto'] era el bug:
    sobre la banda clara ese gris da 1,05:1."""
    m = _medidor()
    est = dr.estilos(variante)
    banda = paleta.diff_fondos(variante)
    contenido = m.resolver(est["contenido"], variante)
    casos = [
        ("marca +", m.resolver(est["marca_mas"], variante), banda["mas"]),
        ("marca -", m.resolver(est["marca_menos"], variante), banda["menos"]),
        ("contenido sobre +", contenido, banda["mas"]),
        ("contenido sobre -", contenido, banda["menos"]),
        ("contenido sobre intra +", contenido, banda["mas_intra"]),
        ("contenido sobre intra -", contenido, banda["menos_intra"]),
    ]
    flojos = [(n, fg, bg, round(_contraste(fg, bg), 2))
              for n, fg, bg in casos if _contraste(fg, bg) < 4.5]
    assert flojos == [], flojos


@pytest.mark.parametrize("variante", VARIANTES)
def test_la_marca_mas_y_la_menos_miden_PARECIDO(variante):
    """PUNTO 2 del juicio visual. El preview del agente daba '+' a 9,34:1 y
    '-' a 4,92:1 sobre el fondo del tema: el DOBLE de contraste para lo
    agregado, cuando las dos son la mitad de la misma informacion. El diff
    unificado tiene que repartir parejo en las tres variantes."""
    m = _medidor()
    est = dr.estilos(variante)
    banda = paleta.diff_fondos(variante)
    c_mas = _contraste(m.resolver(est["marca_mas"], variante), banda["mas"])
    c_menos = _contraste(m.resolver(est["marca_menos"], variante),
                         banda["menos"])
    razon = max(c_mas, c_menos) / min(c_mas, c_menos)
    assert razon <= 1.3, (
        f"{variante}: '+' {c_mas:.2f}:1 contra '-' {c_menos:.2f}:1 "
        f"(razon {razon:.2f}): vuelve la asimetria del punto 2")


def test_las_tres_variantes_tienen_bandas_DISTINTAS():
    """Si dos variantes compartieran las bandas de linea, '/tema' no estaria
    haciendo nada en el diff (que es exactamente el sintoma del punto 3)."""
    lineas = {v: (dr.estilos(v)["linea_mas"], dr.estilos(v)["linea_menos"])
              for v in VARIANTES}
    assert lineas["oscuro"] != lineas["claro"]
    assert lineas["alto_contraste"] != lineas["claro"]
    # y el contenido de 'claro' NO puede ser el gris de la paleta oscura
    assert dr.estilos("claro")["contenido"] != paleta.SEMANTICO["texto"]


def test_estilos_de_variante_desconocida_no_revientan():
    # el adorno jamas rompe un turno: variante rara -> la de defecto
    assert dr.estilos("no_existe") == dr.estilos(dr.VARIANTE_DEFECTO)


def test_intra_se_distingue_del_fondo_de_su_linea():
    """Requisito 2: el resaltado intra ya no usa 'reverse' — usa un fondo mas
    fuerte del mismo tono, y tiene que despegarse del fondo de la linea."""
    assert "reverse" not in dr._ST_MAS_INTRA
    assert "reverse" not in dr._ST_MENOS_INTRA
    assert dr._FONDO_MAS_INTRA in dr._ST_MAS_INTRA
    assert dr._FONDO_MENOS_INTRA in dr._ST_MENOS_INTRA
    assert _contraste(dr._FONDO_MAS_INTRA, dr._FONDO_MAS) >= 1.5
    assert _contraste(dr._FONDO_MENOS_INTRA, dr._FONDO_MENOS) >= 1.5


@pytest.mark.parametrize("ancho", [40, 80, 100, 200])
def test_el_fondo_llega_al_borde_derecho(ancho):
    """Requisito 3: cada renglon de una linea -/+ ocupa el ancho COMPLETO y
    todos sus segmentos llevan el mismo fondo."""
    g = render_diff("uno\ndos\n", "uno\nDOS\n", ruta="x.py")
    esperados = {dr._FONDO_MAS.lower(), dr._FONDO_MENOS.lower()}
    pintadas = 0
    for segs in _lineas_segmentadas(g, ancho):
        fondos = {s.style.bgcolor.triplet.hex.lower()
                  for s in segs if s.style is not None and s.style.bgcolor}
        if not fondos & esperados:
            continue           # cabeceras, @@ y contexto van sin fondo
        pintadas += 1
        # un solo tono por renglon (el intra usa el fuerte, que tambien cuenta)
        assert len(fondos) <= 2, fondos
        # y no queda ni una celda del renglon sin pintar
        assert all(s.style is not None and s.style.bgcolor for s in segs), segs
        assert sum(len(s.text) for s in segs) == ancho
    assert pintadas == 2, pintadas


def test_linea_mas_larga_que_la_terminal_se_pliega_y_sigue_pintada():
    """Requisito 3: pliega, NO recorta — y los renglones de continuacion
    tambien llevan el fondo (asi se ve que son la misma linea logica)."""
    largo = "resultado = " + "z" * 300
    g = render_diff(largo + "\n", largo + "!\n", ruta="x.py")
    segs_por_linea = _lineas_segmentadas(g, 60)
    pintadas = [l for l in segs_por_linea
                if any(s.style is not None and s.style.bgcolor for s in l)]
    # 312 y 313 chars a 60 columnas -> muchos renglones, no 2
    assert len(pintadas) > 8, len(pintadas)
    for l in pintadas:
        assert sum(len(s.text) for s in l) == 60
        assert all(s.style is not None and s.style.bgcolor for s in l)
    # nada recortado: el contenido entero sobrevive en el texto plano
    plano = "".join(s.text for l in segs_por_linea for s in l)
    assert "z" * 300 in plano.replace(" ", "")


def test_marca_solo_en_el_primer_renglon_de_la_linea_plegada():
    largo = "a" * 200
    g = render_diff("x\n", largo + "\n", ruta="x.py")
    lineas = ["".join(s.text for s in l).rstrip()
              for l in _lineas_segmentadas(g, 50)][2:]  # sin cabeceras ---/+++
    conmarca = [l for l in lineas if l.startswith("+")]
    assert len(conmarca) == 1, conmarca


# ── requisito 4: el movil no se rompe (prefijo intacto) ────────────────────

def test_prefijo_intacto_para_el_clasificador_del_movil():
    """cognia/remoto/sesiones.py clasifica por prefijo: '+ ' es ACTIVIDAD y
    '- ' seria vineta de respuesta. El render no puede meter un espacio ni
    cambiar el signo. Se comprueba contra las funciones REALES."""
    from cognia.remoto.sesiones import _es_actividad, _limpiar
    viejo = "def f():\n    return 1\n"
    nuevo = "def f():\n    return 2\n"
    g = render_diff(viejo, nuevo, ruta="ej.py")
    con = Console(record=True, width=100, force_terminal=True,
                  color_system="truecolor", legacy_windows=False)
    con.print(g)
    limpias = [_limpiar(l) for l in con.export_text(styles=True).split("\n")]
    limpias = [l for l in limpias if l]
    # _limpiar quita el ANSI y el relleno de la derecha: queda el unified plano
    assert "-    return 1" in limpias
    assert "+    return 2" in limpias
    assert not any("\x1b" in l for l in limpias)
    assert not any(l != l.rstrip() for l in limpias)
    # y la clasificacion es la MISMA que la del texto plano de difflib
    import difflib
    ref = list(difflib.unified_diff(viejo.splitlines(), nuevo.splitlines(),
                                    fromfile="a/ej.py", tofile="b/ej.py",
                                    lineterm="", n=2))
    assert ([_es_actividad(l) for l in limpias]
            == [_es_actividad(l) for l in ref])


def test_las_lineas_borradas_no_parecen_vineta_markdown():
    # '- ' al principio seria una vineta en el chat del movil: el render usa
    # '-contenido' pegado, igual que el unified diff de siempre
    g = render_diff("uno\n", "dos\n", ruta="x.py")
    plana = [_texto(p).plain for p in _partes(g)[2:]]
    assert "-uno" in plana and "+dos" in plana
    assert not any(p.startswith("- ") or p.startswith("+ ") for p in plana)


# ── punto 3: el diff OBEDECE a /tema ───────────────────────────────────────

def test_variante_activa_lee_cognia_theme(monkeypatch):
    # '/tema claro' escribe COGNIA_THEME en os.environ (first_run.
    # set_config_value): es la unica fuente que cambia EN CALIENTE
    for v in VARIANTES:
        monkeypatch.setenv("COGNIA_THEME", v)
        assert variante_activa() == v


def test_variante_activa_ignora_basura_igual_que_el_cli(monkeypatch):
    monkeypatch.setenv("COGNIA_THEME", "violeta")
    assert variante_activa() == "oscuro"
    monkeypatch.setenv("COGNIA_THEME", "")
    assert variante_activa() == "oscuro"


@pytest.mark.parametrize("variante", VARIANTES)
def test_variante_activa_desde_la_console(monkeypatch, variante):
    """Sin COGNIA_THEME, la Console que se pasa desempata: se sondea el token
    'marca', cuyo hex es distinto en las tres variantes."""
    monkeypatch.delenv("COGNIA_THEME", raising=False)
    from rich.theme import Theme
    con = Console(theme=Theme(paleta.tema_cli(variante)), file=io.StringIO())
    assert variante_activa(con) == variante


def test_variante_activa_console_sin_tema_no_revienta(monkeypatch):
    monkeypatch.delenv("COGNIA_THEME", raising=False)
    assert variante_activa(Console(file=io.StringIO())) == "oscuro"
    assert variante_activa(object()) == "oscuro"


def test_render_diff_cambia_de_banda_con_el_tema(monkeypatch):
    """El sintoma del punto 3: en terminal blanca el diff era una isla negra.
    Ahora el MISMO diff pintado con '/tema claro' trae las bandas claras."""
    def fondos(variante):
        monkeypatch.setenv("COGNIA_THEME", variante)
        g = render_diff("uno\n", "dos\n", ruta="x.py")
        return {_fondo(p) for p in _partes(g)[2:] if _fondo(p)}

    oscuro, claro = fondos("oscuro"), fondos("claro")
    assert oscuro == {f"on {paleta.DIFF_FONDO['oscuro']['mas']}",
                      f"on {paleta.DIFF_FONDO['oscuro']['menos']}"}
    assert claro == {f"on {paleta.DIFF_FONDO['claro']['mas']}",
                     f"on {paleta.DIFF_FONDO['claro']['menos']}"}
    assert oscuro.isdisjoint(claro)


# ── render_bloque: el preview del agente, mismo lenguaje visual ────────────

def test_render_bloque_pinta_bandas_sin_cabeceras():
    g = render_bloque(["viejo()"], ["nuevo()"])
    assert g is not None
    partes = _partes(g)
    assert len(partes) == 2                      # sin ---/+++ ni @@
    assert _fondo(partes[0]) == dr._ST_LINEA_MENOS
    assert _fondo(partes[1]) == dr._ST_LINEA_MAS
    assert [_texto(p).plain for p in partes] == ["-viejo()", "+nuevo()"]


def test_render_bloque_resalta_el_span_cambiado_como_el_unified():
    g = render_bloque(["x = calcular(a, b)"], ["x = calcular(a, c)"])
    fuertes_menos, fuertes_mas = [], []
    for p in _partes(g):
        fuertes_menos += _spans_con_estilo(p, dr._ST_MENOS_INTRA)
        fuertes_mas += _spans_con_estilo(p, dr._ST_MAS_INTRA)
    assert any("b)" in s for s in fuertes_menos), fuertes_menos
    assert any("c)" in s for s in fuertes_mas), fuertes_mas
    assert not any("calcular" in s for s in fuertes_menos + fuertes_mas)


def test_render_bloque_solo_agregados():
    g = render_bloque([], ["uno", "dos"])
    partes = _partes(g)
    assert len(partes) == 2
    assert all(_fondo(p) == dr._ST_LINEA_MAS for p in partes)


def test_render_bloque_vacio_es_none():
    assert render_bloque([], []) is None
    assert render_bloque(None, None) is None


def test_render_bloque_sangria_no_pinta_el_margen_izquierdo():
    """La sangria sangra el bloque sin pintar el margen: el preview cuelga
    debajo de la linea de la tool y la banda sigue llegando al borde."""
    g = render_bloque([], ["uno"], sangria=6, separador=" ")
    segs = _lineas_segmentadas(g, 40)[0]
    assert segs[0].text == "      "
    assert segs[0].style is None or segs[0].style.bgcolor is None
    pintado = [s for s in segs if s.style is not None and s.style.bgcolor]
    assert "".join(s.text for s in pintado).startswith("+ uno")
    # la banda llega al borde: 40 columnas menos los 6 de sangria
    assert sum(len(s.text) for s in pintado) == 34


def test_render_bloque_sin_rich_devuelve_none(monkeypatch):
    monkeypatch.setattr(dr, "_HAS_RICH", False)
    assert render_bloque([], ["uno"]) is None


# ── requisito 5: sin color, el signo sigue distinguiendo ───────────────────

def test_sin_color_el_signo_distingue_agregado_de_borrado(monkeypatch):
    """NO_COLOR / terminal sin color: rich tira las bandas y las marcas, y lo
    unico que queda es el canal no-cromatico. Tiene que bastar (WCAG 1.4.1).

    Se miran los BYTES que la Console escribe de verdad (no export_text, que
    re-renderiza con su propio tema y volveria a meter el color)."""
    monkeypatch.setenv("NO_COLOR", "1")
    g = render_diff("uno\n", "dos\n", ruta="x.py")
    buf = io.StringIO()
    con = Console(width=60, force_terminal=True, file=buf)
    assert con.no_color, "rich tiene que respetar NO_COLOR por su cuenta"
    con.print(g)
    crudo = buf.getvalue()
    assert "38;2;" not in crudo and "48;2;" not in crudo, crudo
    # el signo sobrevive: sin fondo, '-uno' y '+dos' siguen siendo distintos.
    # Se limpia con la MISMA funcion del remoto, que es la que quita ANSI.
    from cognia.remoto.sesiones import _limpiar
    lineas = [_limpiar(l) for l in crudo.split("\n")]
    assert "-uno" in lineas and "+dos" in lineas, lineas
    # lo unico que queda del enfasis intra es el 'bold': el canal no-cromatico
    assert "\x1b[1m" in crudo


# ── contenido dificil: acentos y tabulaciones ──────────────────────────────

def test_acentos_sobreviven_al_pintado():
    viejo = "titulo = 'Migracion'\n"
    nuevo = "titulo = 'Migraci\u00f3n a\u00fan m\u00e1s'\n"
    g = render_diff(viejo, nuevo, ruta="acentos.py")
    texto = _export(g)
    assert "Migraci\u00f3n a\u00fan m\u00e1s" in texto
    # y el span resaltado es la parte que cambio, con los acentos dentro
    fuertes = []
    for p in _partes(g):
        fuertes += _spans_con_estilo(p, dr._ST_MAS_INTRA)
    assert any("\u00f3" in s for s in fuertes), fuertes


def test_tabulaciones_no_rompen_el_relleno():
    # rich expande los tabs al renderizar (tab_size=8); el relleno del fondo
    # tiene que contar las celdas EXPANDIDAS, no los chars del string
    g = render_diff("if x:\n\tfoo(1)\n", "if x:\n\tfoo(2)\n", ruta="tabs.py")
    for segs in _lineas_segmentadas(g, 70):
        if any(s.style is not None and s.style.bgcolor for s in segs):
            assert sum(len(s.text) for s in segs) == 70
            assert "\t" not in "".join(s.text for s in segs)


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


# ---------------------------------------------------------------------------
# P6 (2026-08-24): diff.mas / diff.menos del registro de estilos
# ---------------------------------------------------------------------------

def test_estilos_del_diff_siguen_al_registro_y_vuelven_al_default():
    from cognia.ux import aspecto as A
    A.reset()
    try:
        base = dict(dr.estilos("oscuro"))
        assert base["linea_mas"] == "on #173322" and base["marca_mas"] == "bold #3fb950"
        assert not A.errores(A.poner("diff.mas", "fondo", "#123456"))
        assert not A.errores(A.poner("diff.menos", "estados.marca.color", "#ff00ff"))
        assert not A.errores(A.poner("diff.mas", "estados.intra.fondo", "#224466"))
        est = dr.estilos("oscuro")
        assert est["linea_mas"] == "on #123456"
        assert est["marca_menos"] == "bold #ff00ff"
        assert est["mas_intra"] == "bold default on #224466"
        # lo no tocado sigue igual
        assert est["linea_menos"] == base["linea_menos"]
        assert est["marca_mas"] == base["marca_mas"]
        A.reset()
        assert dr.estilos("oscuro") == base, "sin override, byte-identico"
    finally:
        A.reset()


def test_render_bloque_pinta_el_fondo_del_registro():
    from cognia.ux import aspecto as A
    A.reset()
    try:
        assert not A.errores(A.poner("diff.mas", "fondo", "#123456"))
        buf = io.StringIO()
        con = Console(file=buf, force_terminal=True, color_system="truecolor",
                      legacy_windows=False, width=80)
        con.print(dr.render_bloque([], ["nuevo"], variante="oscuro"))
        assert "48;2;18;52;86" in buf.getvalue()
    finally:
        A.reset()
