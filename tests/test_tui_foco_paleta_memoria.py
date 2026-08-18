"""test_tui_foco_paleta_memoria.py -- los tres defectos del juicio visual de
2026-08-17 que no eran de color sino de ESTADO: donde esta el foco, que dice la
paleta de comandos, y por que los resultados de memoria salian centrados.

Todo se mide sobre el RENDER (SVG exportado por app.run_test), igual que
test_tui_jerarquia.py, porque los tres son composiciones de Textual que un
assert sobre el .tcss o sobre el Python no ve:

  4. EL FOCO. `:focus` matchea SOLO al widget enfocado y los contenedores de las
     vistas no son focusables, asi que con la tabla de modelos enfocada NINGUN
     borde de la pantalla era de acento: el unico aviso de "donde estoy" era el
     panel pasando de #161b22 a #20252c (1.12:1). Se arregla con `:focus-within`
     y se verifica leyendo el color de la ESQUINA de cada panel en el SVG.

  6. LOS RESULTADOS DE MEMORIA. #memory-output nacia con la clase `empty-state`
     (memory_view.py, compose) y no habia un solo remove_class en el modulo;
     app.tcss le da `content-align: center middle`, asi que los resultados
     reales salian centrados y desalineados con su encabezado. Nadie lo vio en
     meses porque el arnes llamaba a _show_results() a mano; aca se busca por el
     camino real (Input.Submitted -> worker -> _show_results) y se mide la
     COLUMNA en la que arranca cada linea.

  9. LA PALETA DE COMANDOS. Mezclaba los comandos de Cognia en espanol con los
     de Textual en ingles (Keys / Quit / Theme / Screenshot), tenia DOS "Salir"
     con comportamiento distinto (el de Cognia confirma, el de Textual no) y era
     la unica superficie sin acento y con negro puro (la lupa es `color: #000`
     en el DEFAULT_CSS de Textual y los separadores son `hkey black`).

Convencion: codigo y nombres ASCII.
"""

from __future__ import annotations

import re

import pytest
from textual.widgets import Input, Static

from cognia.tui.app import CogniaTUI
from cognia.tui.commands import CogniaCommands
from cognia.tui.theme import COLORS
from cognia.tui.widgets.memory_view import MemoryView

from .test_tui_jerarquia import _rgb, _textos


# --- utilidades de lectura del render ---------------------------------------


def _corner_por_panel(svg: str) -> dict[str, str]:
    """Titulo de panel -> hex de la esquina '/' del marco de ESE panel.

    La fila de los titulos trae los dos paneles: '╭', '─', ' Menu ', ... y luego
    otra vez '╭', '─', ' <Vista> '. Se recorre en orden de x y se le asigna a
    cada titulo la ultima esquina vista antes de el, que es la de su marco.
    """
    filas: dict[float, list[tuple[float, str, str]]] = {}
    for tag, cuerpo in re.findall(r"(<text[^>]*>)(.*?)</text>", svg, re.S):
        clase = re.search(r'class="terminal-\d+-(r\d+)"', tag)
        y = re.search(r'y="([\d.]+)"', tag)
        x = re.search(r'x="([\d.]+)"', tag)
        if not (clase and y and x):
            continue
        filas.setdefault(float(y.group(1)), []).append(
            (float(x.group(1)), clase.group(1), re.sub(r"&#160;", " ", cuerpo)))
    clases = dict(re.findall(r"\.terminal-\d+-(r\d+) \{ fill: (#[0-9a-fA-F]{6})", svg))
    for y in sorted(filas):
        runs = sorted(filas[y])
        if not any(t.strip().startswith("╭") for _x, _c, t in runs):
            continue
        salida: dict[str, str] = {}
        esquina = ""
        for _x, clase, texto in runs:
            if texto.strip().startswith("╭"):
                esquina = (clases.get(clase) or "").lower()
            elif esquina and re.search(r"[A-Za-z]", texto):
                salida[texto.strip()] = esquina
        return salida
    return {}


def _es_acento(hexa: str, tolerancia: int = 2) -> bool:
    """El acento con la deriva de +-1 por canal que mete Textual (ver paleta)."""
    if not hexa:
        return False
    return all(abs(a - b) <= tolerancia
               for a, b in zip(_rgb(hexa), _rgb(COLORS["accent"])))


async def _svg_modelos(enfocar_tabla: bool) -> str:
    app = CogniaTUI()
    async with app.run_test(size=(120, 38)) as pilot:
        await pilot.pause()
        await pilot.press("4")
        for _ in range(3):
            await pilot.pause()
        if enfocar_tabla:
            app.query_one("#models-table").focus()
            for _ in range(3):
                await pilot.pause()
        app.clear_notifications()
        await pilot.pause()
        return app.export_screenshot()


# --- 4. DONDE ESTOY: el borde de acento sigue al foco ------------------------


@pytest.mark.asyncio
async def test_con_el_menu_enfocado_el_acento_esta_en_el_menu():
    esquinas = _corner_por_panel(await _svg_modelos(enfocar_tabla=False))
    assert _es_acento(esquinas.get("Menu", "")), f"el menu perdio el foco: {esquinas}"
    assert not _es_acento(esquinas.get("Modelos", "")), (
        f"la vista sin foco esta marcada como enfocada: {esquinas}"
    )


@pytest.mark.asyncio
async def test_con_la_tabla_enfocada_el_acento_pasa_al_PANEL_de_la_tabla():
    """El defecto original: aca no habia UN SOLO borde de acento en pantalla."""
    esquinas = _corner_por_panel(await _svg_modelos(enfocar_tabla=True))
    assert _es_acento(esquinas.get("Modelos", "")), (
        f"el panel que contiene el foco no esta marcado: {esquinas}"
    )
    assert not _es_acento(esquinas.get("Menu", "")), (
        f"el menu sigue marcado como enfocado: {esquinas}"
    )


@pytest.mark.asyncio
async def test_el_indicador_de_foco_es_UNO_solo():
    """Nunca dos paneles de acento a la vez: si hay dos, no indica nada."""
    for enfocar in (False, True):
        esquinas = _corner_por_panel(await _svg_modelos(enfocar_tabla=enfocar))
        marcados = [t for t, h in esquinas.items() if _es_acento(h)]
        assert len(marcados) == 1, f"foco={enfocar}: paneles marcados {marcados}"


@pytest.mark.asyncio
async def test_el_foco_en_un_hijo_no_le_saca_el_color_a_las_celdas():
    """No-regresion: el arreglo del foco no puede pisar lo que se gano antes.

    El 'falta' rojo tiene que seguir siendo rojo con la tabla enfocada (era la
    conquista de la pasada anterior; el borde de acento no lo toca).
    """
    svg = await _svg_modelos(enfocar_tabla=True)
    faltas = [h for _y, h, t in _textos(svg) if t == "falta"]
    assert faltas, "la tabla no dibujo ninguna fila"
    for hexa in faltas:
        assert all(abs(a - b) <= 2 for a, b in zip(_rgb(hexa), _rgb(COLORS["err"]))), (
            f"'falta' dejo de ser rojo con el panel enfocado: {hexa}"
        )


# --- 6. Los resultados de memoria NO son un empty-state ----------------------


class _BackendCorto:
    """Resultados CORTOS a proposito: con lineas largas el centrado no se nota."""

    def stats(self) -> dict:
        return {"projects": [("cognia", 2)], "total_pointers": 2}

    def search(self, query: str, limit: int = 20):
        return [
            {"score": 0.91, "project": "cognia", "source_kind": "nota",
             "text": "el coste se mide", "source_ref": "mem:1"},
            {"score": 0.44, "project": "cognia", "source_kind": "nota",
             "text": "la banda es 3,83x", "source_ref": "mem:2"},
        ]


async def _memoria_con_resultados(pilot, app, query: str = "coste"):
    """Busca por el CAMINO REAL: escribir en el Input y mandar Enter."""
    vista = app.query_one(MemoryView)
    vista._backend = _BackendCorto()
    vista._stats_loaded = True   # no tocar la DB del usuario
    await pilot.press("3")
    for _ in range(3):
        await pilot.pause()
    entrada = app.query_one("#memory-input", Input)
    entrada.focus()
    await pilot.pause()
    entrada.value = query
    await pilot.press("enter")
    await app.workers.wait_for_complete()
    for _ in range(3):
        await pilot.pause()
    return vista


@pytest.mark.asyncio
async def test_la_clase_empty_state_se_pone_y_se_QUITA():
    """Estaba puesta en compose y no habia un solo remove_class en el modulo."""
    app = CogniaTUI()
    async with app.run_test(size=(120, 38)) as pilot:
        await pilot.pause()
        salida = app.query_one("#memory-output", Static)
        assert salida.has_class("empty-state"), "el empty-state nace sin su clase"
        await _memoria_con_resultados(pilot, app)
        assert not salida.has_class("empty-state"), (
            "los resultados heredan el `content-align: center middle` del empty-state"
        )
        # Y vuelve a ponerse cuando no hay nada que listar.
        app.query_one(MemoryView)._show_results("zzz", [])
        await pilot.pause()
        assert salida.has_class("empty-state"), (
            "'sin resultados' es un mensaje de estado y tiene que ir centrado"
        )


@pytest.mark.asyncio
async def test_los_resultados_arrancan_en_la_misma_columna_que_su_encabezado():
    """Medido en el SVG: antes el bloque entero salia corrido a la derecha.

    Con dos resultados cortos, el panel de resultados empezaba en la columna 42
    de un panel que arranca en la 4 -- centrado, desalineado con la linea de
    stats de arriba, que si va pegada al borde.
    """
    app = CogniaTUI()
    async with app.run_test(size=(120, 38)) as pilot:
        await pilot.pause()
        await _memoria_con_resultados(pilot, app)
        app.clear_notifications()
        await pilot.pause()
        svg = app.export_screenshot()

    # Ancho de celda del SVG que exporta Textual: cada rect de fondo mide 12.2.
    CELDA = 12.2
    equis: dict[str, float] = {}
    for tag, cuerpo in re.findall(r"(<text[^>]*>)(.*?)</text>", svg, re.S):
        x = re.search(r'x="([\d.]+)"', tag)
        if not x:
            continue
        texto = re.sub(r"&#160;", " ", cuerpo).strip()
        for marca in ("Memoria", "2 resultados para", "el coste se mide",
                      "la banda es 3,83x"):
            if texto.startswith(marca):
                equis.setdefault(marca, float(x.group(1)))
    assert len(equis) == 4, f"no se encontraron las cuatro lineas: {equis}"
    encabezado = equis["Memoria"]
    # Con la clase puesta el bloque arrancaba 30 columnas a la derecha del
    # encabezado (366.0 -> 732.0, medido en esta misma escena); alineado, la
    # unica diferencia es el `padding: 0 1` del contenedor scrolleable.
    desvio = (equis["2 resultados para"] - encabezado) / CELDA
    assert 0 <= desvio <= 3, (
        f"el bloque de resultados arranca {desvio:.0f} columnas a la derecha de "
        f"su encabezado: sigue centrado"
    )
    # Las lineas de snippet arrancan en la MISMA columna que su encabezado (los
    # 4 espacios de sangria van dentro del run, no en la posicion del run).
    for marca in ("el coste se mide", "la banda es 3,83x"):
        desvio_snippet = abs(equis[marca] - equis["2 resultados para"]) / CELDA
        assert desvio_snippet <= 1, (
            f"'{marca}' no esta alineada con el resto del bloque: "
            f"{desvio_snippet:.0f} columnas"
        )


# --- 9. La paleta de comandos, en espanol y con acento -----------------------


# Lo que Textual pone en ingles y ahora se reemplaza (get_system_commands).
_INGLES = ("Keys", "Quit", "Theme", "Screenshot", "Maximize", "Minimize",
           "Show help for the focused widget", "Change the current theme",
           "Quit the application as soon as possible",
           "Save an SVG 'screenshot' of the current screen")


async def _comandos_de_la_paleta(app) -> list[tuple[str, str]]:
    """(nombre, ayuda) de TODO lo que la paleta ofrece: sistema + Cognia."""
    salida = [(c.title, c.help) for c in app.get_system_commands(app.screen)]
    proveedor = CogniaCommands(app.screen)
    salida += [(n, h) for n, h, _cb in proveedor._commands()]
    return salida


@pytest.mark.asyncio
async def test_no_queda_ni_un_comando_en_ingles():
    app = CogniaTUI()
    async with app.run_test(size=(120, 38)) as pilot:
        await pilot.pause()
        comandos = await _comandos_de_la_paleta(app)
    plano = " | ".join(f"{n} :: {h}" for n, h in comandos)
    for literal in _INGLES:
        assert literal not in plano, f"quedo en ingles: {literal!r} en {plano}"
    assert len(comandos) >= 11, f"se perdieron comandos: {comandos}"


@pytest.mark.asyncio
async def test_no_hay_dos_comandos_con_el_mismo_nombre():
    """Habia DOS 'Salir': el de Cognia (confirma) y el Quit de Textual (no)."""
    app = CogniaTUI()
    async with app.run_test(size=(120, 38)) as pilot:
        await pilot.pause()
        nombres = [n for n, _h in await _comandos_de_la_paleta(app)]
    repetidos = {n for n in nombres if nombres.count(n) > 1}
    assert not repetidos, f"comandos duplicados en la paleta: {repetidos}"


@pytest.mark.asyncio
async def test_el_unico_Salir_de_la_paleta_pasa_por_la_confirmacion():
    """No alcanza con que no se repita: el que queda tiene que ser el que pregunta."""
    from cognia.tui.widgets.modals import ConfirmModal

    app = CogniaTUI()
    async with app.run_test(size=(120, 38)) as pilot:
        await pilot.pause()
        proveedor = CogniaCommands(app.screen)
        salir = [cb for n, _h, cb in proveedor._commands() if n == "Salir"]
        assert len(salir) == 1, "no hay un unico comando Salir de Cognia"
        salir[0]()
        for _ in range(3):
            await pilot.pause()
        assert isinstance(app.screen, ConfirmModal), (
            "Salir cerro sin preguntar (se colo el action_quit de Textual)"
        )
        await pilot.press("n")
        await pilot.pause()


async def _svg_paleta(escribir: str = "") -> str:
    app = CogniaTUI()
    async with app.run_test(size=(120, 38)) as pilot:
        await pilot.pause()
        await pilot.press("ctrl+p")
        for _ in range(4):
            await pilot.pause()
        if escribir:
            await pilot.press(*escribir)
        for inp in app.screen.query(Input):
            inp.cursor_blink = False
        for _ in range(5):
            await pilot.pause()
        app.clear_notifications()
        await pilot.pause()
        return app.export_screenshot()


@pytest.mark.asyncio
async def test_el_buscador_de_la_paleta_esta_en_espanol():
    svg = await _svg_paleta()
    # El cursor del Input parte el run en dos ("B" + "uscar comandos..."), asi
    # que se pegan sin separador antes de buscar.
    plano = "".join(t for _y, _h, t in _textos(svg))
    assert "Buscar comandos" in plano, f"placeholder en ingles: {plano[:400]}"
    assert "Search for commands" not in plano


@pytest.mark.asyncio
async def test_la_paleta_no_pinta_negro_puro():
    """La lupa es `color: #000` y los separadores `hkey black` en Textual.

    Medido: 241 glifos casi negros sobre el overlay (#000000 y #060910). Es el
    mismo agujero negro que se le habia sacado al scrollbar, en otra superficie.
    """
    svg = await _svg_paleta()
    # El cursor del Input pinta su letra con el $background de la app (texto
    # invertido): eso no es "negro puro", es el fondo del producto.
    negros = [(h, t.strip()) for _y, h, t in _textos(svg)
              if t.strip() and h and sum(_rgb(h)) < 60 and h != COLORS["bg"].lower()]
    assert not negros, f"volvio el negro puro a la paleta: {negros[:6]}"


@pytest.mark.asyncio
async def test_el_item_resaltado_de_la_paleta_lleva_el_acento():
    """CommandList nace con can_focus=False y caia siempre en el cursor BORROSO.

    Resultado: la lista que se esta navegando se veia igual que una lista en
    reposo, y la paleta quedaba sin un solo pixel de identidad.
    """
    svg = await _svg_paleta(escribir="mem")
    # El tramo que hizo match sale como run aparte ("Ir a" + "M"+"e"+"m" +
    # "oria"), asi que se pegan todos los runs de acento y se busca en el todo.
    acentos = "".join(t.strip() for _y, h, t in _textos(svg) if _es_acento(h))
    assert "Memoria" in acentos, (
        f"el comando resaltado no esta en el acento: {acentos!r}"
    )
