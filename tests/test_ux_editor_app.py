# -*- coding: utf-8 -*-
"""EditorApp (cognia/ux/editor_app.py), la Application full-screen del
editor /estilo (P11) sobre el modelo puro de P10: se corre ENTERA sobre
PipeInput + Vt100_Output (DEPTH_24_BIT), sin consola.

Lo que fija (seccion 5 y enmiendas E3/E12 del diseno):
- la app pinta los tres paneles + pie con las filas del modelo y entra y
  sale del alt-screen (ESC[?1049h / l);
- las teclas de la tabla del modelo llegan a modelo.tecla(): el recorrido
  down x7, enter, enter, backspace x6, 'jarvis', enter, c-s, esc cambia
  prompt.etiqueta.texto, escribe estilo.json (tmp_path) y cierra;
- refresh_interval() es 0 sin animacion y 1/fps con animacion (E3), y con
  animacion la preview usa el reloj REAL (frames distintos a t distintos);
- guardas (E12): con una Application corriendo, sin tty, con COGNIA_REMOTO,
  con corrida de fondo o status vivo abrir_editor devuelve ('no_abrible', motivo);
- Esc con cambios muestra la confirmacion en un Float; 'd' descarta;
- el estilo del editor contrasta >= PISO_TEXTO en las 3 variantes;
- ningun binding de cli.py abre el editor (nunca anidar).
"""
from __future__ import annotations

import asyncio
import io
import json
import re
import sys
from pathlib import Path

import pytest

pytest.importorskip("rich")
pytest.importorskip("prompt_toolkit")

from prompt_toolkit.application.current import get_app_or_none, set_app  # noqa: E402
from prompt_toolkit.application.dummy import DummyApplication  # noqa: E402
from prompt_toolkit.data_structures import Size  # noqa: E402
from prompt_toolkit.input import create_pipe_input  # noqa: E402
from prompt_toolkit.keys import Keys  # noqa: E402
from prompt_toolkit.output import ColorDepth  # noqa: E402
from prompt_toolkit.output.vt100 import Vt100_Output  # noqa: E402

from cognia.ux import aspecto as A  # noqa: E402
from cognia.ux import glow as G  # noqa: E402
from cognia.ux import paleta  # noqa: E402
from cognia.ux import editor_app as EA  # noqa: E402
from cognia.ux.editor_aspecto import EditorModelo, abrir_editor as abrir_desde_modelo  # noqa: E402
from cognia.ux.editor_app import EditorApp, abrir_editor, clases_editor, motivo_no_abrible  # noqa: E402

DOWN, ENTER, BS, ESC, TAB, CS = "\x1b[B", "\r", "\x7f", "\x1b", "\t", "\x13"
_RE_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


@pytest.fixture(autouse=True)
def _limpio(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "DIR_COGNIA", tmp_path)
    monkeypatch.setattr(A, "RUTA_ESTILO", tmp_path / "estilo.json")
    monkeypatch.setattr(A, "DIR_PRESETS", tmp_path / "estilos")
    for k in ("COGNIA_REMOTO", "COGNIA_THEME", "COGNIA_ASCII", "COGNIA_ANIMACION", "NO_COLOR"):
        monkeypatch.delenv(k, raising=False)
    A.reset()
    G.vaciar_memo()
    yield
    A.reset()


def _salida(columnas=100, filas=30):
    buf = io.StringIO()
    out = Vt100_Output(buf, lambda: Size(rows=filas, columns=columnas), term="xterm-256color",
                       default_color_depth=ColorDepth.DEPTH_24_BIT, enable_cpr=False)
    return buf, out


def _correr(modelo: EditorModelo, trozos: list, *, pausa: float = 0.3, cerrar_pipe: bool = True):
    """Corre la app alimentando la entrada por trozos DESDE el loop (asi
    cada trozo ve la pantalla anterior pintada y un Esc suelto se vacia solo:
    la pausa supera app.ttimeoutlen = 0,2 s). Devuelve (resultado, crudo, plano)."""
    buf, out = _salida()
    with create_pipe_input() as inp:
        app = EditorApp(modelo, input=inp, output=out)

        async def alimentar():
            for t in trozos:
                await asyncio.sleep(pausa)
                inp.send_text(t)
            await asyncio.sleep(pausa)
            if cerrar_pipe and not modelo.cerrado:
                inp.close()

        resultado = app.run(pre_run=lambda: app.app.create_background_task(alimentar()))
    crudo = buf.getvalue()
    return resultado, crudo, _RE_ANSI.sub("", crudo)


# ---------------------------------------------------------------------------
# Pantalla y recorrido
# ---------------------------------------------------------------------------

def test_pinta_los_tres_paneles_y_el_pie_y_entra_y_sale_del_alt_screen():
    m = EditorModelo(ancho=60)
    resultado, crudo, plano = _correr(m, [ESC])
    assert resultado == "cerrado" and m.cerrado
    assert "\x1b[?1049h" in crudo and "\x1b[?1049l" in crudo, "alt-screen: entrar y salir"
    assert crudo.index("\x1b[?1049h") < crudo.index("\x1b[?1049l")
    for fila in ("ELEMENTOS", "PROPIEDADES: banner.arte", "VISTA PREVIA (v: variante oscuro)",
                 "banner", "arte", "prompt", "glow.intensidad", "Tab panel  Enter editar",
                 "sin guardar · 0 elementos con cambios"):
        assert fila in plano, f"falta '{fila}' en el render"
    assert "38;2;" in crudo, "DEPTH_24_BIT: la preview lleva truecolor (E5)"


def test_recorrido_por_teclas_cambia_la_etiqueta_guarda_y_sale():
    m = EditorModelo(ancho=60)
    trozos = [DOWN * 7, ENTER, ENTER, BS * 6 + "jarvis", ENTER, CS, ESC]
    resultado, crudo, plano = _correr(m, trozos, cerrar_pipe=False)
    assert m.elemento_id == "prompt.etiqueta"
    assert A.texto("prompt.etiqueta") == "jarvis"
    assert resultado == "cerrado" and m.resultado == "cerrado" and not m.sucio
    doc = json.loads(A.RUTA_ESTILO.read_text(encoding="utf-8"))
    assert doc["elementos"]["prompt.etiqueta"]["texto"] == "jarvis"
    assert "PROPIEDADES: prompt.etiqueta" in plano
    assert "jarvis" in plano and "guardado" in plano
    assert "\x1b[?1049l" in crudo


def test_el_buffer_de_texto_se_ve_en_el_flotante_y_esc_cancela():
    m = EditorModelo(ancho=60, elemento_inicial="prompt.etiqueta")
    m.panel = "propiedades"
    _, _, plano = _correr(m, [ENTER, "xyz", ESC, ESC])
    assert "texto (Enter confirma, Esc cancela)" in plano
    # PT pinta por DIFERENCIAS: primero 'cognia▏', luego solo 'xyz▏' encima
    assert "cognia▏" in plano and "xyz▏" in plano
    assert A.texto("prompt.etiqueta") == "cognia"
    assert m.cerrado


def test_esc_con_cambios_muestra_la_confirmacion_y_d_descarta():
    m = EditorModelo(ancho=60, elemento_inicial="prompt.etiqueta")
    m.panel = "propiedades"
    estados = []
    trozos = [ENTER, "!", ENTER, ESC, "d"]
    buf, out = _salida()
    with create_pipe_input() as inp:
        app = EditorApp(m, input=inp, output=out)

        async def alimentar():
            for t in trozos:
                await asyncio.sleep(0.3)
                estados.append((m.modo, m.sucio))
                inp.send_text(t)
        resultado = app.run(pre_run=lambda: app.app.create_background_task(alimentar()))
    plano = _RE_ANSI.sub("", buf.getvalue())
    assert estados[-1] == ("confirmar_salir", True), estados
    assert "Hay cambios sin guardar: [g]uardar / [d]escartar / [v]olver" in plano
    assert "[d] descartar los cambios y salir" in plano
    assert resultado == "descartado" and m.resultado == "descartado"
    assert not A.tiene_override("prompt.etiqueta"), "Descartar restaura la instantanea de apertura"
    assert not A.RUTA_ESTILO.exists()


def test_selector_de_color_en_el_flotante_con_ratios():
    m = EditorModelo(ancho=60, elemento_inicial="prompt.etiqueta")
    m.panel = "propiedades"
    m.cursor_props = next(i for i, p in enumerate(m.props()) if p.ruta == "color")
    _, _, plano = _correr(m, [ENTER, DOWN, ESC, ESC])
    assert "COLOR: color [*refs | mi | hex]" in plano
    assert "@rampa.texto" in plano and ":1 oscuro" in plano
    assert "color: sin cambios" in plano
    assert not A.tiene_override("prompt.etiqueta")


def test_ayuda_y_variante_repintan_el_titulo_de_la_preview():
    m = EditorModelo(ancho=60)
    _, _, plano = _correr(m, ["?", "x", "v", ESC])
    assert "AYUDA" in plano and "^S               guardar" in plano
    assert "VISTA PREVIA (v: variante claro)" in plano
    assert m.variante_preview == "claro"


def test_eof_de_la_entrada_cierra_como_cerrado_sin_perder_la_memoria():
    m = EditorModelo(ancho=60, elemento_inicial="prompt.etiqueta")
    m.panel = "propiedades"
    resultado, _, _ = _correr(m, [ENTER, "!", ENTER])   # el pipe se cierra sin Esc
    assert resultado == "cerrado" and m.cerrado and m.resultado == "cerrado"
    assert A.texto("prompt.etiqueta") == "cognia!" and m.sucio


# ---------------------------------------------------------------------------
# Teclas: la tabla entera del modelo esta enlazada
# ---------------------------------------------------------------------------

def test_todas_las_teclas_de_la_tabla_del_modelo_tienen_binding():
    _, out = _salida()
    with create_pipe_input() as inp:
        app = EditorApp(EditorModelo(ancho=60), input=inp, output=out)
    claves = {tuple(getattr(k, "value", k) for k in b.keys) for b in app.app.key_bindings.bindings}
    # PT normaliza: enter = c-m, tab = c-i, backspace = c-h
    for tecla in ("up", "down", "pageup", "pagedown", "home", "end", "left", "right", "c-i", "s-tab",
                  "c-m", "c-h", "delete", "escape", "f1", "c-u", "c-z", "c-y", "c-s", "c-p",
                  "c-l", "c-n", "c-e", "c-g", "c-c", " "):
        assert (tecla,) in claves, f"sin binding para {tecla!r}"
    assert (Keys.Any.value,) in claves, "los caracteres (j k g G a A v r R q ? + - / t) van por Keys.Any"


def test_las_teclas_llegan_al_modelo_con_los_nombres_de_la_tabla(monkeypatch):
    m = EditorModelo(ancho=60)
    vistas = []
    original = m.tecla

    def espia(nombre):
        vistas.append(nombre)
        original(nombre)
    monkeypatch.setattr(m, "tecla", espia)
    _correr(m, [DOWN, "\x1b[A", TAB, "\x1b[Z", "\x1b[5~", "\x1b[6~", "\x1b[H", "\x1b[F",
                " ", "j", "+", "-", "\x1a", "\x19", "\x1bOP", "x", ESC])
    assert vistas == ["down", "up", "tab", "s-tab", "pageup", "pagedown", "home", "end",
                      "space", "j", "+", "-", "c-z", "c-y", "f1", "x", "esc"], vistas


# ---------------------------------------------------------------------------
# Animacion (E3)
# ---------------------------------------------------------------------------

def _app_sin_correr(m):
    _, out = _salida()
    with create_pipe_input() as inp:
        return EditorApp(m, input=inp, output=out)


def test_refresh_interval_0_sin_animacion_y_1_fps_con_animacion():
    m = EditorModelo(ancho=60, elemento_inicial="prompt.etiqueta")
    app = _app_sin_correr(m)
    assert app.refresh_interval() == 0.0 and not app.animando()
    assert not A.errores(A.poner("prompt.etiqueta", "animacion.activa", True))
    assert app.animando()
    assert app.refresh_interval() == pytest.approx(1.0 / G.FPS)
    assert app.app.refresh_interval is None, "el tic es propio y condicional; PT no repinta solo"


def test_con_animacion_global_off_no_repinta(monkeypatch):
    monkeypatch.setenv("COGNIA_ANIMACION", "0")
    m = EditorModelo(ancho=60, elemento_inicial="prompt.etiqueta")
    A.poner("prompt.etiqueta", "animacion.activa", True)
    app = _app_sin_correr(m)
    assert not m.animacion_global
    assert app.refresh_interval() == 0.0


def test_con_animacion_la_preview_usa_el_reloj_real():
    m = EditorModelo(ancho=60, elemento_inicial="prompt.etiqueta")
    A.poner("prompt.etiqueta", "animacion.activa", True)
    A.poner("prompt.etiqueta", "animacion.velocidad", 5)
    app = _app_sin_correr(m)
    G.RELOJ.fijar(0.10)
    f1 = app._frags_preview()
    G.RELOJ.fijar(0.35)
    f2 = app._frags_preview()
    G.RELOJ.reiniciar()
    assert f1 != f2, "anima: el frame depende del reloj real"
    A.poner("prompt.etiqueta", "animacion.activa", False)
    G.RELOJ.fijar(0.10)
    f3 = app._frags_preview()
    G.RELOJ.fijar(0.35)
    f4 = app._frags_preview()
    G.RELOJ.reiniciar()
    assert f3 == f4, "sin animacion: t_preview fijo, frame determinista"


def test_el_tic_invalida_solo_cuando_anima():
    m = EditorModelo(ancho=60, elemento_inicial="prompt.etiqueta")
    app = _app_sin_correr(m)
    llamadas = []
    app.app.invalidate = lambda: llamadas.append(1)
    app.fps = 50

    async def prueba():
        tarea = asyncio.ensure_future(app._tic())
        await asyncio.sleep(0.4)
        sin = len(llamadas)
        A.poner("prompt.etiqueta", "animacion.activa", True)
        await asyncio.sleep(0.6)
        tarea.cancel()
        return sin, len(llamadas)
    sin, con = asyncio.run(prueba())
    assert sin == 0, "sin animacion el tic NO invalida"
    assert con >= 5, f"con animacion invalida a ~fps ({con} en 0,6 s a 50 fps; reloj de Windows ~16 ms)"


# ---------------------------------------------------------------------------
# Guardas (E12)
# ---------------------------------------------------------------------------

def test_guarda_app_anidada():
    assert get_app_or_none() is None
    with set_app(DummyApplication()):
        r = abrir_editor(hay_tty=True)
    assert r[0] == "no_abrible" and "no se anida" in r[1]


def test_guarda_sin_tty_por_defecto_y_explicita():
    r = abrir_editor()          # bajo pytest stdin/stdout no son tty
    assert r[0] == "no_abrible" and "sin tty" in r[1]
    r = abrir_editor(hay_tty=lambda: False)
    assert r[0] == "no_abrible" and "sin tty" in r[1]


def test_guarda_remoto_corrida_y_status(monkeypatch):
    monkeypatch.setenv("COGNIA_REMOTO", "1")
    assert "COGNIA_REMOTO" in motivo_no_abrible(hay_tty=True)
    monkeypatch.delenv("COGNIA_REMOTO")
    assert "corrida de fondo" in motivo_no_abrible(corrida_en_fondo=lambda: True, hay_tty=True)
    assert "status vivo" in motivo_no_abrible(status_activo=True, hay_tty=True)
    assert motivo_no_abrible(hay_tty=True) == ""


def test_la_puerta_de_editor_aspecto_delega_sin_importar_pt_al_cargar():
    r = abrir_desde_modelo(hay_tty=False)
    assert r == ("no_abrible", r[1]) and "sin tty" in r[1]
    fuente = Path(EA.__file__).with_name("editor_aspecto.py").read_text(encoding="utf-8")
    importa = [l for l in fuente.splitlines() if re.match(r"\s*(from|import)\s+prompt_toolkit", l)]
    assert not importa, f"el modelo sigue puro: prompt_toolkit solo dentro de editor_app: {importa}"
    assert "from .editor_app import abrir_editor" in fuente


def test_cli_no_abre_el_editor_desde_un_binding():
    """E12: ningun @_kb.add(...) de cli.py llama a abrir_editor/EditorApp
    (app.run() dentro de un binding se cuelga). Estatico: vale antes y
    despues de que P4 conecte _slash_estilo."""
    ruta = Path(EA.__file__).resolve().parents[1] / "cli.py"
    lineas = ruta.read_text(encoding="utf-8", errors="replace").splitlines()
    ultimo_def = -1
    for i, linea in enumerate(lineas):
        if re.match(r"\s*(async\s+)?def\s+\w+", linea):
            ultimo_def = i
        if "abrir_editor(" in linea or "EditorApp(" in linea:
            contexto = "\n".join(lineas[max(0, ultimo_def - 6):ultimo_def + 1])
            assert "kb.add(" not in contexto, f"cli.py:{i + 1}: el editor se abre desde un binding"


# ---------------------------------------------------------------------------
# Estilo del editor
# ---------------------------------------------------------------------------

def _colores(s: str):
    fg = re.search(r"fg:(#[0-9a-f]{6})", s)
    bg = re.search(r"bg:(#[0-9a-f]{6})", s)
    return fg.group(1) if fg else None, bg.group(1) if bg else None


@pytest.mark.parametrize("variante", A.ORDEN_VARIANTES)
def test_clases_del_editor_contrastan_en_cada_variante(variante):
    d = clases_editor(variante)
    for clave in ("grupo", "grupo.activo", "elemento", "elemento.cursor", "elemento.activo",
                  "elemento.atenuado", "prop", "prop.activa", "prop.atenuada", "flotante",
                  "flotante.activo", "flotante.buffer", "pie", "pie.estado", "mensaje",
                  "mensaje.error", "mensaje.aviso", "titulo", "borde", "frame.border", "frame.label"):
        fg, bg = _colores(d[clave])
        assert fg, f"{clave} sin fg"
        r = A.contraste(fg, bg or paleta.FONDO_VARIANTE[variante])
        assert r >= A.PISO_TEXTO, f"{variante}/{clave}: {r:.2f}:1 < {A.PISO_TEXTO}"


def test_estilo_pt_lleva_las_clases_del_prompt_sin_la_base():
    d = EA.estilo_pt("oscuro")
    assert "" in d and d[""] == "", "la base del editor no hereda el color del texto del prompt"
    for k in ("marco", "cognia", "completion-menu.completion.current", "elemento.activo"):
        assert k in d
    with pytest.raises(ValueError):
        clases_editor("sepia")


def test_el_estilo_se_rehace_al_cambiar_variante_o_version():
    m = EditorModelo(ancho=60)
    app = _app_sin_correr(m)
    s1 = app._estilo_actual()
    assert app._estilo_actual() is s1
    m.tecla("v")
    s2 = app._estilo_actual()
    assert s2 is not s1
    A.poner("prompt.marco", "color", "#ff00ff")
    assert app._estilo_actual() is not s2


def test_preview_rota_degrada_visible(monkeypatch, capsys):
    # Sin cli cargado el aviso va a stderr; si otro test dejo cognia.cli en
    # sys.modules (test_ux_aspecto lo importa) iria a _aviso_degradado y el
    # test dependeria del ORDEN de la bateria.
    monkeypatch.delitem(sys.modules, "cognia.cli", raising=False)
    m = EditorModelo(ancho=60)
    app = _app_sin_correr(m)

    def rota(t=None):
        raise RuntimeError("boom")
    monkeypatch.setattr(m, "preview_pt", rota)
    frags = app._frags_preview()
    assert frags[0][0] == "class:mensaje.error" and "RuntimeError: boom" in frags[0][1]
    assert "[degradado] estilo.editor" in capsys.readouterr().err


def test_resumen_de_una_linea():
    m = EditorModelo(ancho=60, elemento_inicial="prompt.etiqueta")
    app = _app_sin_correr(m)
    assert app.resumen().startswith("0 elementos con cambios")
    A.poner("prompt.etiqueta", "texto", "jarvis")
    assert "SIN GUARDAR" in app.resumen()
    m.guardar()
    m.resultado = "guardado"
    assert re.search(r"1 elemento con cambios · guardado \d\d:\d\d", app.resumen())
