# -*- coding: utf-8 -*-
"""
tests/test_cli_banner_layout.py
===============================
Regresion del banner de arranque a 100 columnas (juicio visual 2026-08-24).

QUE PROTEGE: a 100 columnas (media pantalla, el ancho mas comun) el grid de
_print_banner_completo repartia por RATIO 3:2 y la columna del arte quedaba
en ~56 para un logo COGNIA de 63: cada fila del logo envolvia y la 'A' caia
sola a la linea siguiente (10 lineas para un logo de 5). A 80 y a 120 entraba.
La regla nueva vive en harness/banner_adaptativo.cabe_dos_columnas: dos
columnas SOLO si arte ENTERO + guia ENTERA caben; si no, apilado.

Snapshot REAL: se pinta con la Console de rich del CLI (tema real) a un ancho
fijo y se comprueba que las 5 filas del logo salen ENTERAS y que ninguna
linea supera el ancho. Sin mocks del layout.
"""
from __future__ import annotations

import io
import re

import pytest

rich_console = pytest.importorskip("rich.console")

import cognia.cli as cli  # noqa: E402
from cognia.harness.banner_adaptativo import ancho_visible  # noqa: E402


def _filas_logo() -> list:
    """Las 5 filas del logo COGNIA en bloques, tal cual viven en _BANNER_RAW."""
    filas = [l.rstrip() for l in cli._BANNER_RAW.split("\n")
             if "█" in l or "╗" in l]
    assert len(filas) == 5, filas
    return filas


def _pintar(ancho: int, monkeypatch, variante: str = "completo",
            alto: int = 60) -> str:
    monkeypatch.setenv("COGNIA_BANNER", variante)
    buf = io.StringIO()
    # legacy_windows=False: con la deteccion automatica rich resta 1 columna
    # sobre un StringIO en Windows y el snapshot no seria el de una terminal
    # moderna (Windows Terminal), que es donde el juez lo vio.
    con = rich_console.Console(
        file=buf, width=ancho, height=alto,
        theme=cli._THEMES[cli._THEME_ORDER[cli._theme_idx]],
        highlight=False, force_terminal=False, legacy_windows=False)
    monkeypatch.setattr(cli, "_console", con)
    cli._print_banner_completo()
    return buf.getvalue()


@pytest.mark.parametrize("ancho", [80, 100, 104, 112, 120, 160])
def test_el_logo_sale_entero_y_nada_desborda(ancho, monkeypatch):
    salida = _pintar(ancho, monkeypatch)
    lineas = salida.splitlines()
    for fila in _filas_logo():
        # Cada fila del logo tiene que estar ENTERA en una sola linea pintada
        # (a 100 columnas la 'A' final caia sola a la linea de abajo).
        assert any(fila.strip() in l for l in lineas), (
            f"a {ancho} columnas la fila del logo se parte: {fila.strip()!r}")
    con_bloques = [l for l in lineas if "█" in l or "╗" in l]
    assert len(con_bloques) == 5, (
        f"a {ancho} columnas el logo ocupa {len(con_bloques)} lineas, no 5")
    for l in lineas:
        assert ancho_visible(l) <= ancho, (ancho, ancho_visible(l), l)


def test_a_100_columnas_se_apila_y_a_120_va_a_dos_columnas(monkeypatch):
    """La guia 'Para empezar' se pone AL LADO del arte solo cuando cabe."""
    s100 = _pintar(100, monkeypatch).splitlines()
    s120 = _pintar(120, monkeypatch).splitlines()
    braille = re.compile("[⠀-⣿]")
    # A 120: hay lineas con arte Braille Y texto de la guia a la vez.
    assert any(braille.search(l) and "/hacer" in l for l in s120)
    # A 100: ninguna linea mezcla arte y guia (apilado), y la guia esta.
    assert not any(braille.search(l) and "/hacer" in l for l in s100)
    assert any("/hacer" in l for l in s100)
    # Y en ninguno de los dos anchos la linea de atajos se parte.
    for lineas in (s100, s120):
        assert any("Tab" in l and "/ayuda" in l and "todo" in l for l in lineas)


@pytest.mark.parametrize("ancho", [80, 100, 120])
def test_la_variante_medio_recorta_el_gato_y_conserva_el_logo(ancho, monkeypatch):
    """A 40 filas (variante 'medio') el recorte por altura se comia el logo
    COGNIA: el bloque entero (gato + logo) se recortaba simetricamente. El
    logo es identidad y sale ENTERO; lo que cede altura es el gato."""
    lineas = _pintar(ancho, monkeypatch, variante="medio", alto=40).splitlines()
    con_bloques = [l for l in lineas if "█" in l or "╗" in l]
    assert len(con_bloques) == 5, (ancho, len(con_bloques))
    for fila in _filas_logo():
        assert any(fila.strip() in l for l in lineas), (ancho, fila.strip())
    # Y sigue cabiendo: el banner medio nunca pinta mas que la terminal
    # menos el aire del prompt.
    assert len(lineas) <= 40 - 3, (ancho, len(lineas))


# ---------------------------------------------------------------------------
# P7 (2026-08-24): el banner lee el registro de estilos (cognia/ux/aspecto.py)
# y el motor (cognia/ux/glow.py). Regla numero uno: sin fichero de estilo la
# salida es BYTE-IDENTICA (goldens de tests/golden/aspecto a 80 y 120).
# ---------------------------------------------------------------------------
import importlib.util  # noqa: E402
from pathlib import Path  # noqa: E402

from cognia.ux import aspecto as A  # noqa: E402
from cognia.ux import glow as G  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
BRAILLE = re.compile("[⠁-⣿]")     # arte (no el blanco Braille U+2800)
CURSOR_UP = re.compile(r"\x1b\[\d*A")
TRUECOLOR = re.compile(r"38;2;\d+;\d+;\d+")


def _snapshots():
    """scripts/aspecto_snapshots.py por ruta (scripts/ no es paquete)."""
    ruta = REPO / "scripts" / "aspecto_snapshots.py"
    spec = importlib.util.spec_from_file_location("aspecto_snapshots_banner", ruta)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


S = _snapshots()


@pytest.fixture(autouse=True)
def _aspecto_y_motor_limpios(monkeypatch):
    for k in ("COGNIA_THEME", "COGNIA_REMOTO", "COGNIA_ASCII", "COGNIA_ANIMACION",
              "COGNIA_BANNER", "NO_COLOR"):
        monkeypatch.delenv(k, raising=False)
    A.reset()
    G.forzar_capacidades(None)
    G.vaciar_memo()
    yield
    A.reset()
    G.forzar_capacidades(None)
    G.vaciar_memo()


def _poner(id, prop, valor):
    avisos = A.poner(id, prop, valor)
    assert not [a for a in avisos if a.nivel == "error"], avisos


def _pintar_crudo(ancho: int, monkeypatch, alto: int = 60, caps=None,
                  variante: str = "completo") -> str:
    """Como _pintar, pero con la Console truecolor FORZADA (force_terminal):
    lo que ve una terminal moderna, escapes incluidos."""
    monkeypatch.setenv("COGNIA_BANNER", variante)
    con = rich_console.Console(
        file=io.StringIO(), width=ancho, height=alto, force_terminal=True,
        color_system="truecolor", legacy_windows=False,
        theme=cli._THEMES[cli._THEME_ORDER[cli._theme_idx]], highlight=False)
    monkeypatch.setattr(cli, "_console", con)
    G.forzar_capacidades(caps)
    G.vaciar_memo()
    cli._print_banner_completo()
    return con.file.getvalue()


def _cabecera_completa(ancho: int) -> str:
    """_print_startup_panel entera (banner + linea del modelo) con el entorno
    fijo del snapshot (modelo/puerto/version/terminal fijos)."""
    with S.entorno_fijo(ancho) as C:
        con = S.consola(ancho)
        C._console = con
        G.vaciar_memo()
        C._print_startup_panel()
        return con.file.getvalue()


def _lineas_de_arte(salida: str) -> list:
    return [l for l in S.limpiar_ansi(salida).splitlines() if BRAILLE.search(l)]


def _colores_por_linea_de_arte(salida: str) -> list:
    return [len(set(TRUECOLOR.findall(l))) for l in salida.split("\n") if BRAILLE.search(l)]


@pytest.mark.parametrize("nombre", ["banner_80", "banner_120"])
def test_default_es_byte_identico_al_golden(nombre):
    """El contrafactual de P7: con el registro sin overrides, el banner (arte
    con gradiente, marco, guia apilada a 80 / al lado a 120, linea del modelo)
    produce los MISMOS bytes que antes de existir aspecto/glow."""
    esperado, obtenido = S.leer(nombre), S.generar(nombre)
    assert obtenido == esperado, S.describir_diferencia(nombre, esperado, obtenido)


def test_los_textos_renombrados_salen_en_el_banner():
    _poner("banner.marco", "texto.titulo", "JARVIS")
    _poner("banner.marco", "texto.subtitulo", "mayordomo local")
    _poner("banner.guia", "texto.cabecera", "Arranca por aqui")
    _poner("banner.guia", "texto.hacer", "<tarea> manos a la obra")
    _poner("banner.linea_modelo", "texto.modelo", "cerebro")
    _poner("banner.linea_modelo", "texto.tema", "look")
    limpio = S.limpiar_ansi(_cabecera_completa(120))
    assert "JARVIS v" in limpio and "COGNIA v" not in limpio
    assert "mayordomo local" in limpio and "sistema cognitivo local" not in limpio
    assert "Arranca por aqui" in limpio and "Para empezar" not in limpio
    assert "/hacer      <tarea> manos a la obra" in limpio
    assert re.search(r"^  cerebro \S+ \(:\d+\)   modo \w+   look oscuro", limpio, re.M), limpio[-300:]
    # el logo COGNIA en bloques sigue siendo el arte: no lo toca el titulo
    assert "█" in limpio


def test_alineacion_centro_y_derecha(monkeypatch):
    izq = S.limpiar_ansi(_pintar_crudo(100, monkeypatch)).splitlines()
    _poner("banner.arte", "alineacion", "centro")
    cen = S.limpiar_ansi(_pintar_crudo(100, monkeypatch)).splitlines()
    # a la izquierda el marco arranca en la columna 0 y llena el ancho; al
    # centro deja el mismo aire a los dos lados y es mas angosto
    assert izq[0].startswith("╭") and ancho_visible(izq[0].rstrip()) == 100
    margen = len(cen[0]) - len(cen[0].lstrip(" "))
    assert margen >= 10, cen[0]
    assert abs(margen - (100 - ancho_visible(cen[0].strip()) - margen)) <= 1, cen[0]
    assert ancho_visible(cen[0].strip()) < 100
    # el logo sigue entero
    assert len([l for l in cen if "█" in l or "╗" in l]) == 5
    # derecha a 120: la guia toma la columna izquierda y el arte va a la derecha
    _poner("banner.arte", "alineacion", "derecha")
    der = S.limpiar_ansi(_pintar_crudo(120, monkeypatch)).splitlines()
    mezcla = [l for l in der if "/hacer" in l and BRAILLE.search(l)]
    assert mezcla, "a 120 el arte y la guia comparten fila"
    assert mezcla[0].index("/hacer") < BRAILLE.search(mezcla[0]).start()


def test_banner_oculto_imprime_la_cabecera_minima_con_aviso_de_identidad():
    _poner("banner.marco", "visible", False)
    limpio = S.limpiar_ansi(_cabecera_completa(120))
    assert "banner oculto por /estilo (identidad: /estilo banner.marco visible on lo devuelve)" in limpio
    assert not BRAILLE.search(limpio) and "█" not in limpio
    assert limpio.startswith("cognia v") and "/ayuda para comandos" in limpio
    # y el DEFAULT nunca lo esconde ni avisa (identidad)
    A.reset()
    limpio = S.limpiar_ansi(_cabecera_completa(120))
    assert "oculto por /estilo" not in limpio and BRAILLE.search(limpio)


def test_arte_oculto_conserva_marco_y_guia_y_avisa():
    _poner("banner.arte", "visible", False)
    limpio = S.limpiar_ansi(_cabecera_completa(120))
    assert not BRAILLE.search(limpio) and "█" not in limpio
    assert "COGNIA v" in limpio and "Para empezar" in limpio and "/hacer" in limpio
    assert ("arte del banner oculto por /estilo (identidad: /estilo banner.arte visible on "
            "lo devuelve)") in limpio


def _grabar_live(monkeypatch) -> list:
    from rich import live as rich_live
    abiertas = []
    original = rich_live.Live.start

    def _start(self, *a, **k):
        abiertas.append(self)
        return original(self, *a, **k)
    monkeypatch.setattr(rich_live.Live, "start", _start)
    return abiertas


def test_sin_tty_la_animacion_no_abre_live_y_el_frame_es_estatico_con_glow(monkeypatch):
    """Pipe / captura / COGNIA_REMOTO: capacidades().animar es False, asi que
    el banner sale de una vez (0 cursor-up, 0 Live) pero CON el glow estatico
    (varios colores por linea del arte) y el gradiente."""
    _poner("banner.arte", "animacion.activa", True)
    _poner("banner.arte", "animacion.solo_al_llegar", True)
    _poner("banner.arte", "glow.intensidad", 2)
    abiertas = _grabar_live(monkeypatch)
    assert G.capacidades().animar is False, G.capacidades()   # pytest: sin tty
    salida = _pintar_crudo(120, monkeypatch)
    assert not CURSOR_UP.search(salida) and not abiertas
    assert "\x1b[?25l" not in salida                            # Live esconde el cursor
    colores = _colores_por_linea_de_arte(salida)
    assert colores and max(colores) >= 2, colores
    assert len(_lineas_de_arte(salida)) == len(_lineas_de_arte(_pintar_crudo(120, monkeypatch)))


def test_consola_chica_no_abre_live_y_pinta_el_frame_estatico_entero(monkeypatch):
    """E7: menos filas que el banner -> nada de Live (rich no puede repintar lo
    que ya scrolleo); el frame estatico, entero, con glow."""
    _poner("banner.arte", "animacion.activa", True)
    _poner("banner.arte", "animacion.velocidad", 5)
    _poner("banner.arte", "glow.intensidad", 1)
    abiertas = _grabar_live(monkeypatch)
    salida = _pintar_crudo(120, monkeypatch, alto=20, caps=G.Caps("truecolor", True, ""))
    assert not CURSOR_UP.search(salida) and not abiertas
    assert len([l for l in S.limpiar_ansi(salida).splitlines() if "█" in l or "╗" in l]) == 5
    assert len(_lineas_de_arte(salida)) >= 20


def test_con_capacidades_el_barrido_da_frames_distintos_y_termina_quieto(monkeypatch):
    """Caps forzadas (truecolor + animar) y reloj explicito: el banner abre la
    Live, dos instantes del barrido pintan distinto (>= 2 colores truecolor en
    la misma linea del arte) y el frame final es estatico e identico dos
    veces; la salida termina en ese frame (regla 4 de convivencia)."""
    _poner("banner.arte", "animacion.activa", True)
    _poner("banner.arte", "animacion.solo_al_llegar", True)
    _poner("banner.arte", "animacion.velocidad", 5)        # 0,6 s de barrido
    _poner("banner.arte", "glow.intensidad", 1)
    _poner("banner.marco", "texto.titulo", "JARVIS")
    instancias = []
    _Orig = G.BannerVivo

    class _BV(_Orig):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            instancias.append(self)
    monkeypatch.setattr(G, "BannerVivo", _BV)
    abiertas = _grabar_live(monkeypatch)
    salida = _pintar_crudo(120, monkeypatch, alto=60, caps=G.Caps("truecolor", True, ""))
    assert len(abiertas) == 1 and len(instancias) == 1
    bv = instancias[0]
    assert bv.frames >= 2 and CURSOR_UP.search(salida)

    def _render(renderable) -> str:
        con = S.consola(120)
        con.print(renderable)
        return con.file.getvalue()
    a, b = _render(bv.frame(t=0.1)), _render(bv.frame(t=0.3))
    assert a != b
    for cuadro in (a, b):
        assert max(_colores_por_linea_de_arte(cuadro)) >= 2
        assert "JARVIS" in S.limpiar_ansi(cuadro)
    final = _render(bv.frame_final())
    assert final == _render(bv.frame_final())
    assert final not in (a, b)
    cola = salida.replace("\x1b[?25l", "").replace("\x1b[?25h", "").rstrip()
    assert cola.endswith(final.rstrip()[-400:]), "la salida no termina en el frame estatico"
