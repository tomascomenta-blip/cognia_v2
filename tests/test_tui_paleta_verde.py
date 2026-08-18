"""
test_tui_paleta_verde.py -- La TUI hereda el VERDE del REPL y sigue legible.

Que: guardian de la decision del dueno (2026-08-17) "manda el verde del REPL, la
TUI lo hereda". No comprueba prosa: comprueba los valores RESUELTOS del tema de
Textual con la app corriendo headless, el contraste WCAG real de los pares que
importan, y que app.tcss no tenga colores propios.

Por que: la TUI ya se desincronizo una vez (era violeta #a371f7 mientras el CLI
era verde) y al abrir la pantalla de agentes parecia otra aplicacion. Una
leccion escrita no impide nada; esto si. Y el riesgo simetrico -- "pintarlo todo
de verde" -- tambien esta cubierto: hay tests que EXIGEN que el rojo de error,
el amarillo de aviso, el azul informativo y los grises sigan existiendo y sigan
siendo distinguibles del verde.

Convencion: codigo y nombres ASCII.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from cognia.tui.app import CogniaTUI
from cognia.tui.theme import COLORS, cognia_theme, empty_state, level_color
from cognia.ux import paleta

TCSS = Path(__file__).resolve().parents[1] / "cognia" / "tui" / "app.tcss"

VIOLETA_VIEJO = "#a371f7"


# --- utilidades de color (WCAG 2.1) -----------------------------------------


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.strip().lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _luminancia(hex_color: str) -> float:
    """Luminancia relativa WCAG de un hex."""
    def canal(v: int) -> float:
        s = v / 255.0
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = (canal(c) for c in _rgb(hex_color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contraste(a: str, b: str) -> float:
    """Ratio de contraste WCAG entre dos hex (1.0 = iguales, 21.0 = maximo)."""
    la, lb = _luminancia(a), _luminancia(b)
    claro, oscuro = max(la, lb), min(la, lb)
    return (claro + 0.05) / (oscuro + 0.05)


def _tono(hex_color: str) -> float:
    """Tono (grados 0..360) del color. Un gris devuelve -1."""
    r, g, b = (c / 255.0 for c in _rgb(hex_color))
    alto, bajo = max(r, g, b), min(r, g, b)
    if alto == bajo:
        return -1.0
    d = alto - bajo
    if alto == r:
        h = ((g - b) / d) % 6
    elif alto == g:
        h = (b - r) / d + 2
    else:
        h = (r - g) / d + 4
    return h * 60.0


def distancia_de_tono(a: str, b: str) -> float:
    """Separacion angular de tono entre dos colores (0..180 grados)."""
    d = abs(_tono(a) - _tono(b)) % 360
    return min(d, 360 - d)


def casi_igual(a: str, b: str, tolerancia: int = 2) -> bool:
    """True si dos hex son el mismo color salvo redondeo.

    Necesario porque Textual NO devuelve el hex tal cual se lo dieron: los
    valores base del tema salen de `color.lighten(0)`, que da la vuelta por HSL
    y pierde una unidad por canal (#f85149 -> #F75149, #7ee62a -> #7DE62A).
    Comprobado en textual 8.2.8; comparar con == aqui seria medir el redondeo
    de Textual, no la paleta de Cognia.
    """
    return all(abs(x - y) <= tolerancia for x, y in zip(_rgb(a), _rgb(b)))


async def _variables_reales() -> dict[str, str]:
    """Variables del tema de Textual RESUELTAS, con la app corriendo de verdad."""
    app = CogniaTUI()
    async with app.run_test(size=(120, 38)) as pilot:
        await pilot.pause()
        assert app.theme == "cognia", "la app no activo el tema de Cognia"
        return dict(app.get_css_variables())


# --- 1. La identidad: el verde llega hasta el render -------------------------


@pytest.mark.asyncio
async def test_el_acento_resuelto_es_el_verde_de_la_paleta():
    """primary/accent del tema REAL == VERDE['prompt'] (no una copia parecida)."""
    variables = await _variables_reales()
    verde = paleta.VERDE["prompt"]
    for clave in ("primary", "accent"):
        assert casi_igual(variables[clave], verde), (
            f"${clave} = {variables[clave]}, se esperaba el verde {verde}"
        )
    # Esta va por `variables=` del Theme: Textual la pasa TAL CUAL, sin redondeo.
    assert variables["footer-key-foreground"].lower() == verde.lower()


@pytest.mark.asyncio
async def test_ni_una_variable_del_tema_vuelve_al_violeta():
    """Ninguna variable resuelta es el violeta viejo ni un derivado suyo."""
    variables = await _variables_reales()
    culpables = [k for k, v in variables.items()
                 if isinstance(v, str) and VIOLETA_VIEJO in v.lower()]
    assert not culpables, f"la TUI volvio al violeta en: {culpables}"


def test_el_verde_de_exito_es_el_mismo_verde_del_cli():
    """'ok' de la TUI y el verde solido de la paleta son el MISMO hex."""
    assert COLORS["ok"] == paleta.VERDE["solido"]
    assert level_color("ok") == paleta.VERDE["solido"]
    assert level_color("error") == paleta.SEMANTICO["error"]


def test_colors_no_declara_hex_propios():
    """Todo COLORS sale de paleta.py; ningun hex nuevo inventado en theme.py."""
    de_la_paleta = set(paleta.SEMANTICO.values()) | set(paleta.SUPERFICIE.values())
    de_la_paleta |= set(paleta.VERDE.values())
    ajenos = {k: v for k, v in COLORS.items() if v not in de_la_paleta}
    assert not ajenos, f"theme.COLORS tiene hex que no estan en la paleta: {ajenos}"


def test_el_empty_state_pinta_el_icono_con_el_acento():
    """El icono de los empty-states usa el acento (verde), no un hex suelto."""
    texto = empty_state("[ ]", "Sin nada", "pista")
    estilos = [str(span.style) for span in texto.spans]
    assert any(COLORS["accent"] in e for e in estilos), estilos


# --- 2. app.tcss no tiene color propio: todo baja del tema -------------------


def test_el_tcss_no_tiene_ni_un_color_literal():
    """app.tcss solo usa $variables: un hex ahi es un color que puede diverger."""
    fuente = TCSS.read_text(encoding="utf-8")
    sin_comentarios = re.sub(r"/\*.*?\*/", "", fuente, flags=re.S)
    hexes = re.findall(r"#[0-9a-fA-F]{3,8}\b", sin_comentarios)
    # Los selectores de id (#header, #sidebar...) no son hex: solo cuentan los
    # que son hex validos de 3/6/8 digitos hexadecimales.
    literales = [h for h in hexes if re.fullmatch(r"#[0-9a-fA-F]{3}|#[0-9a-fA-F]{6}|#[0-9a-fA-F]{8}", h)]
    assert not literales, f"app.tcss tiene colores hardcodeados: {literales}"


def test_la_pista_de_las_barras_no_es_del_color_del_panel():
    """La regla que hace VISIBLE el tramo que falta de las barras sigue puesta.

    Textual pinta la pista sin llenar con el `background` del componente y por
    defecto es $surface -- el mismo color del panel que la contiene, o sea
    invisible. La regla la manda a $border.
    """
    fuente = TCSS.read_text(encoding="utf-8")
    bloque = re.search(r"#train-body Bar > \.bar--bar \{(.*?)\}", fuente, flags=re.S)
    assert bloque, "se fue la regla de la pista de las barras de progreso"
    assert "background: $border" in bloque.group(1)
    assert "color: $primary" in bloque.group(1)


# --- 3. NO es un monocromo: los otros colores siguen ahi y se distinguen -----


@pytest.mark.asyncio
async def test_los_estados_siguen_teniendo_color_propio():
    """error/warning/secondary del tema real NO son verdes ni iguales entre si."""
    variables = await _variables_reales()
    esperado = {
        "error": paleta.SEMANTICO["error"],
        "warning": paleta.SEMANTICO["aviso"],
        "secondary": paleta.SEMANTICO["info"],
        "success": paleta.SEMANTICO["ok"],
    }
    for clave, hexa in esperado.items():
        assert casi_igual(variables[clave], hexa), (
            f"${clave} = {variables[clave]}, se esperaba {hexa}"
        )
    distintos = {variables[k].lower() for k in esperado}
    assert len(distintos) == 4, f"dos estados colapsaron al mismo color: {distintos}"


def test_el_verde_se_distingue_del_rojo_del_amarillo_y_del_azul():
    """El acento y cada estado estan separados EN TONO, no solo en nombre.

    El criterio es el tono y no el contraste WCAG a proposito: el amarillo de
    aviso y el verde de identidad tienen casi la misma luminancia (1.59:1) y
    aun asi nadie los confunde, porque los separan 46 grados de tono. Medir
    esto con contraste daria un falso positivo de "colapsaron".
    """
    acento = COLORS["accent"]
    for clave, minimo in (("err", 90.0), ("warn", 40.0), ("info", 90.0)):
        grados = distancia_de_tono(acento, COLORS[clave])
        assert grados >= minimo, (
            f"{clave} ({COLORS[clave]}) esta a {grados:.0f} grados del acento "
            f"(minimo {minimo:.0f}): se confunden"
        )


def test_el_gris_secundario_sigue_siendo_gris():
    """'muted' no se volvio verde: sus tres canales estan a menos de 24 de rango."""
    r, g, b = _rgb(COLORS["muted"])
    assert max(r, g, b) - min(r, g, b) <= 24, f"muted {COLORS['muted']} dejo de ser gris"


# --- 4. Contraste real de los pares que se leen todo el tiempo ---------------


@pytest.mark.parametrize(
    "frente,fondo,minimo,que",
    [
        ("text", "bg", 7.0, "texto primario sobre el fondo"),
        ("text", "panel", 7.0, "texto primario sobre panel"),
        ("muted", "panel", 4.5, "texto secundario sobre panel"),
        ("accent", "panel", 4.5, "acento verde sobre panel"),
        ("accent", "bg", 4.5, "acento verde sobre el fondo"),
        ("ok", "panel", 3.0, "verde de exito sobre panel"),
        ("err", "panel", 4.5, "rojo de error sobre panel"),
        ("warn", "panel", 4.5, "amarillo de aviso sobre panel"),
        ("info", "panel", 4.5, "azul informativo sobre panel"),
        ("border", "panel", 1.15, "borde contra el panel que encuadra"),
    ],
)
def test_contraste_minimo(frente: str, fondo: str, minimo: float, que: str):
    ratio = contraste(COLORS[frente], COLORS[fondo])
    assert ratio >= minimo, f"{que}: {ratio:.2f}:1 < {minimo}:1"


@pytest.mark.asyncio
async def test_el_item_seleccionado_no_es_verde_sobre_verde():
    """El fondo del cursor de bloque es el verde: su texto tiene que ser AUTO.

    Con 'auto' Textual calcula el contraste (sale negro sobre el verde claro).
    Si alguien lo clava a un hex concreto, el item resaltado del menu puede
    quedar ilegible; este test lo impide.
    """
    variables = await _variables_reales()
    assert variables["block-cursor-background"].lower() == paleta.VERDE["prompt"].lower()
    assert variables["block-cursor-foreground"].startswith("auto")
    assert variables["button-color-foreground"].startswith("auto")


def test_el_tema_declara_el_fondo_oscuro():
    """dark=True y el fondo es REALMENTE oscuro (Textual deriva sombras de ahi)."""
    tema = cognia_theme()
    assert tema.dark is True
    assert _luminancia(COLORS["bg"]) < 0.05, "el fondo dejo de ser oscuro"
    assert _luminancia(COLORS["panel"]) > _luminancia(COLORS["bg"]), (
        "el panel tiene que despegarse del fondo, no hundirse"
    )
