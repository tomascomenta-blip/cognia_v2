# -*- coding: utf-8 -*-
"""EL PISO DE CONTRASTE, POR VARIANTE (2026-08-17).

Por que existe este archivo aparte de test_contraste_paleta.py: ese mide los
TOKENS del tema de rich, y el bloqueante del juicio visual estaba justo en lo
que NO pasa por el tema. El marco del prompt, el 'cognia>', el texto que el
dueno escribe, la barra de estado y los dos extremos del degradado del banner
los pintan prompt_toolkit y el banner con hex propios; mientras esos hex fueron
UNA sola rampa fija, '/tema claro' no era un tema alternativo sino la misma
pantalla con el prompt borrado:

    sobre #fbfbfa, antes           despues
    lo que se ESCRIBE   1,19:1  ->  10,96:1
    'cognia>'           1,53:1  ->   8,20:1
    marco del prompt    1,96:1  ->   4,60:1
    barra de estado     2,07:1  ->   5,67:1
    cierre del banner   1,32:1  ->  13,05:1

Una leccion en prosa no impide nada: esto es el chequeo que corre. Cualquiera
que agregue una variante, mueva un escalon de la rampa o toque una banda del
diff tiene que pasar por aca CON el numero.

La medicion la hace scripts/contraste_tema.py, el mismo instrumento de la
entrega (no una copia).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from cognia.ux import paleta

REPO = Path(__file__).resolve().parent.parent

# Piso WCAG 2.1 AA para texto normal.
AA = 4.5
# Piso WCAG 1.4.11 para elementos GRAFICOS (una regla no es texto).
GRAFICO = 3.0
# Una banda de diff que se despega mas que esto del fondo del tema deja de ser
# un realce y vuelve a ser una isla (el sintoma del punto 3: en terminal blanca
# el diff era un bloque negro).
BANDA_MAX = 2.0


def _medidor():
    pytest.importorskip("rich")
    ruta = REPO / "scripts" / "contraste_tema.py"
    spec = importlib.util.spec_from_file_location("contraste_tema", ruta)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Escalon de la rampa -> piso que tiene que cumplir contra el fondo de SU
# variante. 'profundo' es el arranque del degradado del banner: la decision 18
# del dueno lo fija en ~3:1 (visible, no legible) y aca solo se defiende ese
# piso, sea la variante clara u oscura.
PISO = {
    "texto":    AA,        # lo que el dueno esta escribiendo
    "prompt":   AA,        # 'cognia>'
    "estado":   AA,        # la barra de estado bajo el marco
    "solido":   AA,        # el verde de 'ok'
    "matrix":   AA,        # el cierre del degradado (el logotipo COGNIA)
    "marco":    GRAFICO,   # las reglas que encuadran la escritura
    "profundo": 2.9,       # el arranque del degradado (decision 18)
}


@pytest.mark.parametrize("variante", ["oscuro", "claro", "alto_contraste"])
def test_la_rampa_de_identidad_se_LEE_sobre_el_fondo_de_su_variante(variante):
    m = _medidor()
    fondo = paleta.FONDO_VARIANTE[variante]
    verde = paleta.rampa(variante)
    flojos = []
    for escalon, piso in PISO.items():
        c = m.contraste(verde[escalon], fondo)
        if c < piso:
            flojos.append(f"{escalon}={verde[escalon]} {c:.2f}:1 (piso {piso})")
    assert not flojos, f"{variante} sobre {fondo}: " + "; ".join(flojos)


@pytest.mark.parametrize("variante", ["oscuro", "claro", "alto_contraste"])
def test_la_rampa_sigue_siendo_VERDE_y_no_se_volvio_gris(variante):
    """El pedido del dueno al arreglar el tema claro: que se lea sobre blanco
    SIN convertirlo en gris. Un verde de marca tiene el canal G por encima de
    los otros dos y saturacion real; bajar la luminancia hasta que R==G==B es
    la forma facil (y equivocada) de ganar contraste."""
    for escalon, hexa in paleta.rampa(variante).items():
        r, g, b = (int(hexa[i:i + 2], 16) for i in (1, 3, 5))
        assert g > r and g > b, f"{variante}.{escalon} ({hexa}) no es verde"
        saturacion = (g - min(r, b)) / g if g else 0.0
        assert saturacion >= 0.45, (
            f"{variante}.{escalon} ({hexa}) esta desaturado ({saturacion:.2f}): "
            f"se lee gris verdoso, no como la marca")


@pytest.mark.parametrize("variante", ["oscuro", "claro", "alto_contraste"])
def test_la_rampa_no_tiene_dos_tonos_CASI_iguales(variante):
    """Punto 10, del lado que la paleta SI controla: dos escalones que difieren
    en unas pocas unidades por canal no son dos escalones, son un bug esperando
    a que alguien escriba un assert por igualdad."""
    verde = paleta.rampa(variante)
    claves = list(verde)
    for i, a in enumerate(claves):
        for b in claves[i + 1:]:
            ra = [int(verde[a][j:j + 2], 16) for j in (1, 3, 5)]
            rb = [int(verde[b][j:j + 2], 16) for j in (1, 3, 5)]
            d = sum((x - y) ** 2 for x, y in zip(ra, rb)) ** 0.5
            assert d > 4 * paleta.DERIVA_TEXTUAL, (
                f"{variante}: {a}={verde[a]} y {b}={verde[b]} estan a {d:.1f} "
                f"unidades RGB -- son el mismo color con otro nombre")


def test_mismo_color_absorbe_la_deriva_del_render_y_nada_mas():
    """La comparacion que hay que usar contra un render (ver ACENTO_HEX): el
    #7de62a que devuelve Textual ES el lima de Cognia; #7ee62b tambien; un
    verde distinto NO."""
    assert paleta.mismo_color(paleta.ACENTO_HEX, "#7de62a")
    assert paleta.mismo_color(paleta.ACENTO_HEX, paleta.ACENTO_HEX)
    assert not paleta.mismo_color(paleta.ACENTO_HEX, "#4fd010")
    assert not paleta.mismo_color(paleta.ACENTO_HEX, "#7ee62a".replace("2a", "3a"))


@pytest.mark.parametrize("variante", ["oscuro", "claro", "alto_contraste"])
def test_las_bandas_del_diff_no_son_una_isla(variante):
    """Punto 3. Dos puertas, las dos medidas:
      * la banda de LINEA a menos de 2:1 del fondo del tema (si se despega mas,
        es el bloque de mas peso de la pantalla: eso era el diff negro en una
        terminal blanca, 13,23:1 y 14,92:1 contra #fbfbfa);
      * el texto de encima por encima de AA -- y el texto es el de la VARIANTE
        (el token 'respuesta'), no SEMANTICO['texto'], que sobre la banda clara
        da 1,05:1.
    Las dos '_intra' son el realce del span cambiado: tienen que despegarse de
    su propia linea, asi que ahi solo aplica la puerta del texto."""
    m = _medidor()
    fondo = paleta.FONDO_VARIANTE[variante]
    texto = m.resolver(paleta.tema_cli(variante)["respuesta"], variante)
    bandas = paleta.diff_fondos(variante)
    for nombre, banda in bandas.items():
        c_texto = m.contraste(texto, banda)
        assert c_texto >= AA, (
            f"{variante}.{nombre} ({banda}): el texto {texto} da "
            f"{c_texto:.2f}:1")
        if "intra" not in nombre:
            c_banda = m.contraste(banda, fondo)
            assert c_banda < BANDA_MAX, (
                f"{variante}.{nombre} ({banda}) se despega {c_banda:.2f}:1 del "
                f"fondo {fondo}: es una isla, no un realce")
    # y el realce intra tiene que DESPEGARSE de su linea, o no realza nada
    for lado in ("mas", "menos"):
        salto = m.contraste(bandas[f"{lado}_intra"], bandas[lado])
        assert salto >= 1.25, (
            f"{variante}: el realce intra '{lado}' esta a {salto:.2f}:1 de su "
            f"propia linea, no se ve")


@pytest.mark.parametrize("variante", ["oscuro", "claro", "alto_contraste"])
def test_las_bandas_del_diff_van_del_lado_del_fondo(variante):
    """En oscuro bandas oscuras, en claro bandas claras. Una banda mas clara
    que el fondo en un tema oscuro (o al reves) es la isla del punto 3 aunque
    pase el 2:1."""
    m = _medidor()
    fondo = paleta.FONDO_VARIANTE[variante]
    claro = m.luminancia(fondo) > 0.5
    for nombre, banda in paleta.diff_fondos(variante).items():
        if claro:
            assert m.luminancia(banda) < m.luminancia(fondo), (
                f"{variante}.{nombre} ({banda}) es mas claro que la terminal")
        else:
            assert m.luminancia(banda) > m.luminancia(fondo), (
                f"{variante}.{nombre} ({banda}) es mas oscuro que la terminal")


def test_el_pie_y_los_metadatos_pasan_AA_pero_siguen_siendo_lo_mas_apagado():
    """Punto 8: info_dim (3,15) y footer (2,38) eran las dos ultimas cosas del
    tema por defecto por debajo del rojo que motivo todo el trabajo. Suben
    sobre AA, pero el arreglo no puede ser volverlos gritones: tienen que
    seguir siendo lo mas tenue de su tema."""
    m = _medidor()
    for variante in paleta.ORDEN_VARIANTES:
        tema = paleta.tema_cli(variante)
        fondo = paleta.FONDO_VARIANTE[variante]
        medidos = {t: m.contraste(m.resolver(e, variante), fondo)
                   for t, e in tema.items()}
        for token in ("info_dim", "footer"):
            assert medidos[token] >= AA, (
                f"{variante}.{token} = {tema[token]} da {medidos[token]:.2f}:1")
        # el pie nunca por encima de los metadatos, y ninguno de los dos por
        # encima del texto que el modelo contesta
        assert medidos["footer"] <= medidos["info_dim"] + 0.01, (
            f"{variante}: el footer ({medidos['footer']:.2f}) grita mas que "
            f"los metadatos ({medidos['info_dim']:.2f})")
        assert medidos["info_dim"] < medidos["respuesta"], (
            f"{variante}: los metadatos ({medidos['info_dim']:.2f}) pesan mas "
            f"que la respuesta ({medidos['respuesta']:.2f})")


def test_el_fondo_de_cada_variante_lo_declara_LA_PALETA():
    """El piso por variante no se puede medir contra un fondo que la paleta no
    conoce: vivia duplicado en scripts/contraste_tema.py."""
    m = _medidor()
    assert set(paleta.FONDO_VARIANTE) == set(paleta.ORDEN_VARIANTES)
    assert m.FONDO == paleta.FONDO_VARIANTE
    assert paleta.FONDO_VARIANTE["oscuro"] == paleta.SUPERFICIE["fondo"]
