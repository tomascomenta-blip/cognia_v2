"""test_tui_jerarquia.py -- jerarquia visual de la TUI: scrollbar, seleccion,
modal y decision 17. Todo medido sobre el RENDER, no sobre el CSS fuente.

Que: arranca la app headless (app.run_test) igual que el arnes de capturas,
exporta el SVG de una escena y mide los hex REALES que quedaron pintados. Los
cuatro defectos que cubre estaban todos en el render y ninguno en el texto del
.tcss:

  1. la pista del scrollbar salia #000000 PURO (Textual la deriva de
     background-darken-1 y este fondo da negro): 27 celdas del color mas oscuro
     de la pantalla dentro de un panel claro, un agujero;
  2. la TUI tenia DOS idiomas para "seleccionado" -- bloque de neon en el menu y
     banda oliva en las tablas -- que se veian juntos en la misma pantalla;
  3. sobre la fila del cursor el color semantico de las celdas desaparecia (el
     'falta' rojo salia blanco con el cursor borroso y casi negro con el cursor
     enfocado), asi que el estado del modelo dejaba de leerse justo en la fila
     que el usuario esta mirando;
  4. el dialogo de confirmacion ponia su bloque de mas peso en el boton
     equivocado -- primero en 'No' (el que no hace nada), despues en 'Si', que
     es CERRAR LA APP y estaba pintado con el verde que en todo el resto del
     producto significa ok/Listo/success. Y encima nacia con ese boton ENFOCADO,
     porque `AUTO_FOCUS = None` no desactiva el auto-foco de Textual: lo delega
     en App.AUTO_FOCUS = "*".

Por que medir el render y no el CSS: los tres primeros son composiciones de
Textual (derivacion de tokens, prioridad css/renderable del cursor de la tabla)
que un assert sobre el texto del .tcss no ve. El intento de arreglar (3)
declarando `color:` en .datatable--cursor pinto la fila ENTERA de verde: se
detecto mirando el SVG exportado, no leyendo la hoja de estilos.

Convencion: codigo y nombres ASCII.
"""

from __future__ import annotations

import re

import pytest

from cognia.tui.app import CogniaTUI
from cognia.tui.theme import COLORS, cognia_theme
from cognia.tui.widgets.chat import _ROLE_COLOR
from cognia.ux import paleta

from .test_tui_paleta_verde import contraste  # misma formula WCAG, escrita una vez


# --- lectura del SVG exportado ----------------------------------------------


def _fills_de_rects(svg: str) -> dict[str, float]:
    """hex -> area en px2 de los rectangulos de FONDO del SVG exportado."""
    areas: dict[str, float] = {}
    for tag in re.findall(r"<rect[^>]*>", svg):
        fill = re.search(r'fill="(#[0-9a-fA-F]{6})"', tag)
        ancho = re.search(r'width="([\d.]+)"', tag)
        alto = re.search(r'height="([\d.]+)"', tag)
        if fill and ancho and alto:
            k = fill.group(1).lower()
            areas[k] = areas.get(k, 0.0) + float(ancho.group(1)) * float(alto.group(1))
    return areas


def _textos(svg: str) -> list[tuple[float, str, str]]:
    """(y, hex, texto plano) de cada run de texto del SVG exportado."""
    clases = dict(re.findall(r"\.terminal-\d+-(r\d+) \{ fill: (#[0-9a-fA-F]{6})", svg))
    salida: list[tuple[float, str, str]] = []
    for tag, cuerpo in re.findall(r"(<text[^>]*>)(.*?)</text>", svg, re.S):
        cls = re.search(r'class="terminal-\d+-(r\d+)"', tag)
        y = re.search(r'y="([\d.]+)"', tag)
        if not (cls and y):
            continue
        plano = re.sub(r"&#160;", " ", cuerpo).strip()
        salida.append((float(y.group(1)), (clases.get(cls.group(1)) or "").lower(), plano))
    return salida


def _rgb(hexa: str) -> tuple[int, int, int]:
    h = hexa.strip().lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _area_de(areas: dict[str, float], hexa: str, tolerancia: int = 2) -> float:
    """Area total pintada de un color, tolerando el redondeo de Textual.

    Textual no devuelve el hex tal cual se lo dieron (pasa por HSL en
    `lighten(0)` y pierde una unidad por canal), asi que el MISMO verde aparece
    en el SVG como #7ee62a en un sitio y #7de62a en otro. Comparar por igualdad
    exacta aca mediria ese redondeo y no la paleta.
    """
    objetivo = _rgb(hexa)
    return sum(
        area for k, area in areas.items()
        if all(abs(a - b) <= tolerancia for a, b in zip(_rgb(k), objetivo))
    )


def _luminancia(hexa: str) -> float:
    def canal(v: int) -> float:
        s = v / 255.0
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = (canal(c) for c in _rgb(hexa))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _masas_de_color(areas: dict[str, float], minimo_px2: float = 2000.0) -> list[tuple[str, float]]:
    """Bloques GRANDES de color vivo: (hex, area), de mayor a menor.

    Un "bloque de color" es un fondo saturado y luminoso -- lo que el ojo lee
    como una masa, no como una superficie. Es la unidad en la que se mide la
    jerarquia de un dialogo: cuantas masas compiten y cual es la mas grande.
    """
    masas = []
    for hexa, area in areas.items():
        r, g, b = _rgb(hexa)
        if area >= minimo_px2 and _luminancia(hexa) >= 0.15 and max(r, g, b) - min(r, g, b) >= 60:
            masas.append((hexa, area))
    return sorted(masas, key=lambda kv: -kv[1])


_TECLA_DE_VISTA = {"chat": "1", "entrenamiento": "2", "memoria": "3",
                   "modelos": "4", "logs": "5", "ayuda": "6"}


async def _escena(vista: str, enfocar: str | None = None) -> str:
    """SVG de una vista de la app REAL (misma medida que el arnes de capturas)."""
    app = CogniaTUI()
    async with app.run_test(size=(120, 38)) as pilot:
        await pilot.pause()
        await pilot.press(_TECLA_DE_VISTA[vista])
        # Tres pausas: con una sola, el ContentSwitcher exporta a veces la vista
        # todavia sin layout (sale una caja de tres filas vacia).
        for _ in range(3):
            await pilot.pause()
        if enfocar:
            app.query_one(enfocar).focus()
            for _ in range(3):
                await pilot.pause()
        return app.export_screenshot()


# --- 1. El scrollbar ya no es un agujero negro -------------------------------


def test_la_pista_del_scrollbar_no_la_deriva_textual():
    """La pista esta declarada en el tema; sin eso Textual la calcula = #000000."""
    variables = cognia_theme().variables
    for clave in ("scrollbar-background", "scrollbar-background-hover",
                  "scrollbar-background-active", "scrollbar-corner-color"):
        assert variables[clave] == COLORS["border"], clave


def test_contraste_de_la_pista_y_del_pulgar():
    """Pista visible sobre el panel y pulgar claramente visible sobre la pista.

    El derivado que traia Textual daba 2.67:1 de pulgar contra pista, con una
    pista mas oscura que el fondo de la app: un agujero, no un control.
    """
    variables = cognia_theme().variables
    pista = variables["scrollbar-background"]
    assert contraste(pista, COLORS["panel"]) >= 1.3, "la pista se pierde en el panel"
    assert contraste(pista, COLORS["bg"]) > contraste("#000000", COLORS["bg"]), (
        "la pista sigue siendo mas oscura que el fondo de la app"
    )
    for clave in ("scrollbar", "scrollbar-hover", "scrollbar-active"):
        ratio = contraste(variables[clave], pista)
        assert ratio >= 3.0, f"${clave}: {ratio:.2f}:1 sobre la pista"


@pytest.mark.asyncio
async def test_en_el_render_de_logs_no_queda_ni_un_pixel_negro():
    """La vista Logs pintaba 27 celdas de #000000 puro (la pista del scrollbar)."""
    svg = await _escena("logs")
    areas = _fills_de_rects(svg)
    assert areas.get("#000000", 0.0) == 0.0, (
        f"volvio el agujero negro: {areas.get('#000000')} px2 de #000000"
    )


# --- 2. UN solo idioma de "seleccionado" -------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("enfocar", [None, "#models-table"])
async def test_menu_y_tabla_seleccionan_con_la_misma_banda(enfocar):
    """El item resaltado del menu y la fila del cursor de la tabla comparten hex.

    Antes: el menu con foco pintaba un bloque #7DE62A y la tabla una banda oliva
    (#345724 / #3E4F3B segun la franja del zebra). Dos lenguajes para el mismo
    estado, visibles a la vez en la vista Modelos.
    """
    banda = COLORS["sel"].lower()
    svg = await _escena("modelos", enfocar=enfocar)
    areas = _fills_de_rects(svg)
    assert _area_de(areas, banda) > 0.0, f"no hay banda de seleccion (foco={enfocar})"
    assert _area_de(areas, paleta.VERDE["prompt"]) == 0.0, (
        f"quedo un BLOQUE de acento pintado (foco={enfocar}): "
        "el idioma de seleccion volvio a ser el neon"
    )


# --- 3. La fila del cursor conserva el color semantico de sus celdas ---------


@pytest.mark.asyncio
@pytest.mark.parametrize("enfocar", [None, "#models-table"])
async def test_el_estado_rojo_sobrevive_en_la_fila_del_cursor(enfocar):
    """'falta' se escribe en ROJO en todas las filas, tambien en la del cursor.

    Con la prioridad "css" que trae DataTable, el color del cursor se aplica
    DESPUES del contenido: el 'falta' de la fila 0 salia #e6edf3 (cursor
    borroso) o #101d05 (cursor enfocado). Medido en el SVG, no deducido.
    """
    svg = await _escena("modelos", enfocar=enfocar)
    rojo = paleta.SEMANTICO["error"].lower()
    faltas = [(y, hexa) for y, hexa, txt in _textos(svg) if txt == "falta"]
    assert len(faltas) >= 2, f"la tabla no dibujo las dos filas: {faltas}"
    fuera = [f for f in faltas if f[1] != rojo]
    assert not fuera, f"'falta' dejo de ser rojo en alguna fila: {fuera}"


def test_el_rojo_sobre_la_banda_de_seleccion_supera_3_a_1():
    """Regresion medida por el dueno: habia caido a 2.58:1 sobre el oliva."""
    ratio = contraste(paleta.SEMANTICO["error"], COLORS["sel"])
    assert ratio >= 3.0, f"'falta' sobre la fila del cursor: {ratio:.2f}:1"


@pytest.mark.parametrize("rol", ["ok", "err", "warn", "info", "text", "muted", "accent"])
def test_todo_lo_que_puede_caer_en_una_fila_seleccionada_sigue_legible(rol):
    """Ningun color semantico baja de 3:1 sobre la banda: por eso es GRIS."""
    ratio = contraste(COLORS[rol], COLORS["sel"])
    assert ratio >= 3.0, f"{rol} sobre la banda de seleccion: {ratio:.2f}:1"


# --- 4. El modal: NINGUNA masa de color, y el destructivo se lee como tal ----
#
# Tercera vuelta sobre el mismo dialogo. Historia medida:
#   * v1: 'No' era un bloque #7DE62A de 10.826 px2 y 'Si' un bloque rojo de
#     8.120 -- dos masas, la mas grande en el boton que no hace nada;
#   * v2: una sola masa, verde, mudada a 'Si'. Legible, pero el verde es el
#     color de ok/Listo/success en TODO el producto y 'Si' significa CERRAR LA
#     APP: colision semantica, senalada por el dueno;
#   * v3 (esta): cero masas. El unico color del dialogo es el $error del boton
#     destructivo, en el TEXTO y el contorno, y el boton dice "Salir", no "Si".


@pytest.mark.asyncio
async def test_ningun_boton_del_dialogo_es_un_bloque_de_color():
    """Los dos botones son `default`: el color va en el texto, no en un bloque."""
    app = CogniaTUI()
    async with app.run_test(size=(120, 38)) as pilot:
        await pilot.pause()
        app.action_request_quit()
        for _ in range(3):
            await pilot.pause()
        si = app.screen.query_one("#confirm-yes")
        no = app.screen.query_one("#confirm-no")
        assert si.variant == "default", (
            f"el destructivo volvio a ser un bloque de color ({si.variant})"
        )
        assert no.variant == "default", (
            f"'No' volvio a ser un bloque de color ({no.variant})"
        )
        await pilot.press("n")
        await pilot.pause()


@pytest.mark.asyncio
async def test_el_boton_destructivo_dice_lo_que_hace_y_va_en_rojo():
    """'Salir', no 'Si'; y escrito en $error, no en el verde de identidad.

    Medido en el SVG: el run del boton tiene que salir con el hex de
    SEMANTICO['error'] (Textual puede devolverlo con +-1 por canal, ver
    _area_de) y ninguna letra del dialogo puede ser el acento.
    """
    app = CogniaTUI()
    async with app.run_test(size=(120, 38)) as pilot:
        await pilot.pause()
        app.action_request_quit()
        for _ in range(3):
            await pilot.pause()
        etiqueta = str(app.screen.query_one("#confirm-yes").label)
        svg = app.export_screenshot()
        await pilot.press("n")
        await pilot.pause()
    assert "Salir" in etiqueta, f"el boton destructivo sigue siendo generico: {etiqueta!r}"
    runs = [(h, t.strip()) for _y, h, t in _textos(svg) if "Salir" in t and "(y)" in t]
    assert runs, "no se encontro el run del boton destructivo en el render"
    for hexa, texto in runs:
        assert all(abs(a - b) <= 2 for a, b in
                   zip(_rgb(hexa), _rgb(paleta.SEMANTICO["error"]))), (
            f"el boton destructivo no esta en rojo: {hexa} {texto!r}"
        )


@pytest.mark.asyncio
async def test_el_dialogo_no_pinta_NINGUNA_masa_de_color():
    """Cero bloques saturados: el verde de identidad no toca 'cerrar la app'."""
    app = CogniaTUI()
    async with app.run_test(size=(120, 38)) as pilot:
        await pilot.pause()
        app.action_request_quit()
        for _ in range(3):
            await pilot.pause()
        svg = app.export_screenshot()
        await pilot.press("n")
        await pilot.pause()
    # El fondo del dialogo tapa la pantalla de abajo, asi que las masas que
    # queden son SUYAS. El menu de atras no cuenta: no pinta bloques.
    masas = _masas_de_color(_fills_de_rects(svg))
    assert masas == [], f"el dialogo volvio a pintar masas de color: {masas}"


@pytest.mark.asyncio
async def test_el_dialogo_no_nace_con_el_boton_destructivo_ENFOCADO():
    """AUTO_FOCUS = None NO desactiva el auto-foco en Textual: lo DELEGA.

    screen.py:1493 hace `app.AUTO_FOCUS if self.AUTO_FOCUS is None else ...` y
    App.AUTO_FOCUS es "*", asi que con None la pantalla enfocaba el PRIMER boton
    -- el destructivo -- y Button:focus le sumaba `background-tint: $foreground
    5%`: el boton de salir salia con 12.631 px2 de #262d39 y el otro plano. O
    sea, peso visual Y preseleccion en la accion peligrosa. La cadena vacia si
    lo desactiva.
    """
    app = CogniaTUI()
    async with app.run_test(size=(120, 38)) as pilot:
        await pilot.pause()
        app.action_request_quit()
        for _ in range(3):
            await pilot.pause()
        enfocado = app.screen.focused
        await pilot.press("n")
        await pilot.pause()
    assert enfocado is None, (
        f"el dialogo enfoco un boton solo: {enfocado!r} (AUTO_FOCUS delegado)"
    )


@pytest.mark.asyncio
async def test_el_dialogo_DICE_que_hace_enter():
    """El default no se marca con peso, pero tiene que estar ESCRITO.

    Las tres pasadas anteriores llegaron a la decision correcta -- ningun boton
    preseleccionado, porque marcar uno mentiria sobre lo que hace el teclado --
    y dejaron el agujero: 'enter' confirma y nada en pantalla lo decia, en un
    dialogo cuya accion es CERRAR LA APP. Se mide sobre el render (no sobre el
    compose) porque lo que importa es que el usuario lo LEA, y ademas se exige
    que 'enter' siga estando en BINDINGS: una pista que nombra una tecla que ya
    no existe es peor que no tener pista."""
    from cognia.tui.widgets.modals import ConfirmModal
    confirman = {b.key for b in ConfirmModal.BINDINGS if b.action == "confirm"}
    assert "enter" in confirman, "la pista nombraria una tecla que ya no confirma"
    app = CogniaTUI()
    async with app.run_test(size=(120, 38)) as pilot:
        await pilot.pause()
        app.action_request_quit()
        for _ in range(3):
            await pilot.pause()
        svg = app.export_screenshot()
        await pilot.press("n")
        await pilot.pause()
    pantalla = " ".join(t for _y, _h, t in _textos(svg))
    assert "enter" in pantalla, (
        "el dialogo no dice que hace enter: " + pantalla[-200:])


def test_los_dos_colores_del_dialogo_pasan_AA_sobre_su_fondo():
    """El rojo del destructivo y el texto del seguro, sobre el fondo del dialogo."""
    fondo = COLORS["panel_alt"]  # $panel: el fondo de #confirm-box y de los botones
    rojo = contraste(paleta.SEMANTICO["error"], fondo)
    texto = contraste(COLORS["text"], fondo)
    assert rojo >= 4.5, f"el destructivo no llega a AA: {rojo:.2f}:1"
    assert texto >= 4.5, f"el boton seguro no llega a AA: {texto:.2f}:1"


# --- 5. Decision 17: la respuesta del modelo va en color de texto normal -----


def test_la_etiqueta_del_asistente_no_lleva_color_de_identidad():
    """En la TUI el asistente se escribe en $foreground, como en el REPL."""
    assert _ROLE_COLOR["assistant"] == COLORS["text"]
    assert _ROLE_COLOR["assistant"] != COLORS["accent"]
    # Los otros dos roles NO son la respuesta del modelo: conservan su color.
    assert _ROLE_COLOR["user"] == COLORS["info"]
    assert _ROLE_COLOR["system"] == COLORS["warn"]
