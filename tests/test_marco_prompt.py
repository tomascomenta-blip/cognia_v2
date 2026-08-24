"""
El area donde se escribe va ENCUADRADA en verde (pedido del dueno, 2026-08-17).

Antes el prompt era una linea suelta amarilla ('cognia> ') que se confundia con
el scrollback de la conversacion. Ahora hay una regla verde arriba, 'cognia➤'
en el medio, otra regla abajo y la barra de estado colgando debajo:

    ─────────────────────────────────────────────
     cognia➤ lo que escribe el usuario
    ─────────────────────────────────────────────
    qwythos-9b · ctx 12.4k · chat
    tab completa · ↑↓ historial · @ archivo · / comandos

Estos tests miran el RENDER de verdad (una PromptSession sobre un pipe, leyendo
los ANSI que saldrian por la terminal), no solo el texto del fuente: el marco
puede desaparecer sin que cambie una sola linea de cli.py — basta que
prompt_toolkit pinte el pie en video inverso o que la barra de estado lance.
"""

import re
import threading

import pytest

import cognia.cli as C

pt = pytest.importorskip("prompt_toolkit")


DATOS = {"modelo": "qwythos-9b", "tokens": 12400, "ventana": 131072,
         "modo": "chat"}


def _render(mensaje, pie, columnas=100, teclas="hola\r"):
    """Lo que la terminal recibiria, sin escapes de posicionamiento."""
    import io
    from prompt_toolkit import PromptSession
    from prompt_toolkit.data_structures import Size
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output.vt100 import Vt100_Output

    buf = io.StringIO()
    out = Vt100_Output(buf, lambda: Size(rows=30, columns=columnas),
                       term="xterm-256color")
    with create_pipe_input() as inp:
        inp.send_text(teclas)
        s = PromptSession(input=inp, output=out, bottom_toolbar=pie,
                          style=C._estilo_prompt())

        def _pre():
            # Sobre un pipe no llega la respuesta CPR, el renderer no sabe su
            # altura y prompt_toolkit ESCONDE el bottom_toolbar. Se la damos.
            s.app.renderer._min_available_height = 6

        s.prompt(mensaje, pre_run=_pre)
    crudo = buf.getvalue()
    filas = [f.split("\r")[0].rstrip()
             for f in re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", crudo).split("\r\n")]
    return crudo, filas


class TestElMarcoEncuadraLaEntrada:

    def test_la_regla_va_arriba_y_abajo_del_prompt(self):
        _, filas = _render(C._mensaje_prompt, C._pie_prompt())
        reglas = [i for i, f in enumerate(filas) if f.strip("─-") == ""
                  and f.strip()]
        prompt = next(i for i, f in enumerate(filas) if "cognia" in f)
        assert reglas, f"ninguna regla en el render: {filas[:6]}"
        assert any(i < prompt for i in reglas), "falta la regla de ARRIBA"
        assert any(i > prompt for i in reglas), "falta la regla de ABAJO"

    def test_la_barra_de_estado_sigue_colgando_bajo_el_marco(self):
        from cognia.harness.barra_estado import toolbar_prompt_toolkit
        pie = C._pie_prompt(toolbar_prompt_toolkit(lambda: DATOS,
                                                   contexto_atajos="repl"))
        _, filas = _render(C._mensaje_prompt, pie)
        texto = "\n".join(filas)
        assert "qwythos-9b" in texto, "el marco se comio la barra de estado"
        assert "tab completa" in texto, "el marco se comio los atajos"

    def test_el_prompt_y_el_marco_salen_en_VERDE(self):
        crudo, _ = _render(C._mensaje_prompt, C._pie_prompt())
        # xterm-256color: los tres verdes de la paleta caen en 76/112/155.
        sgr = set(re.findall(r"\x1b\[([0-9;]*)m", crudo))
        verdes = {c for c in sgr if re.match(r"0;38;5;(7[0-9]|1[01][0-9]|15[0-9]);1", c)}
        assert len(verdes) >= 2, f"el marco no salio verde, SGR usados: {sgr}"
        assert not any(";7" == c[-2:] for c in sgr), "video inverso en el pie"

    def test_el_pie_no_va_en_video_inverso(self):
        """Sin 'noreverse' prompt_toolkit pinta una barra clara y el marco
        verde se corta justo ahi (es el default de bottom-toolbar)."""
        estilo = C._estilo_prompt().style_rules
        reglas = dict(estilo)
        assert "noreverse" in reglas.get("bottom-toolbar", "")
        assert "noreverse" in reglas.get("bottom-toolbar.text", "")


class TestLasPiezasDelMarco:

    def test_la_regla_mide_una_celda_menos_que_el_terminal(self, monkeypatch):
        """Una regla de EXACTAMENTE `columns` celdas envuelve y regala una
        fila en blanco bajo el prompt."""
        import shutil
        monkeypatch.setattr(shutil, "get_terminal_size",
                            lambda *a: __import__("os").terminal_size((120, 30)))
        assert C._ancho_marco() == 119

    def test_una_terminal_absurda_no_rompe_el_prompt(self, monkeypatch):
        import shutil
        monkeypatch.setattr(shutil, "get_terminal_size",
                            lambda *a: __import__("os").terminal_size((2, 1)))
        assert C._ancho_marco() == 8
        monkeypatch.setattr(shutil, "get_terminal_size",
                            lambda *a: (_ for _ in ()).throw(OSError("sin tty")))
        assert C._ancho_marco() == 79

    def test_el_mensaje_lleva_regla_nombre_y_flecha(self):
        partes = list(C._mensaje_prompt())
        clases = [c for c, _ in partes]
        assert clases == ["class:marco", "class:cognia", "class:flecha"]
        assert partes[0][1].endswith("\n")
        assert partes[1][1].strip() == "cognia"
        assert partes[2][1] == C._FLECHA


class TestElMarcoNoDependeDeLaBarra:

    def test_sin_barra_la_regla_igual_se_dibuja(self):
        partes = list(C._pie_prompt(None)())
        assert len(partes) == 1
        assert set(partes[0][1]) == {C._REGLA}

    def test_una_barra_que_LANZA_no_borra_el_marco(self):
        def _rota():
            raise RuntimeError("modelo no disponible")
        partes = list(C._pie_prompt(_rota)())
        assert len(partes) == 1 and set(partes[0][1]) == {C._REGLA}

    def test_la_barra_va_en_su_propia_linea(self):
        partes = list(C._pie_prompt(lambda: "qwythos-9b · chat")())
        assert len(partes) == 2
        assert partes[1][1].startswith("\n")


class TestElReplUsaElMarco:
    """Que las piezas existan no alcanza: el REPL tiene que enchufarlas."""

    def test_el_repl_pide_el_mensaje_y_el_pie(self):
        import inspect
        fuente = inspect.getsource(C.repl)
        assert "session.prompt(_mensaje_prompt)" in fuente
        assert "_pie_prompt(" in fuente
        assert "_estilo_prompt()" in fuente


# ---------------------------------------------------------------------------
# P5 (2026-08-24): el marco lo compone el registro de estilos (ux/aspecto.py)
# ---------------------------------------------------------------------------
# Lo que /estilo cambia del prompt, la barra y los menus se ve en el prompt
# siguiente. Todo aqui se mide sobre el RENDER (24 bits, E5): un texto que
# cambia en el fuente y no llega a la terminal no cuenta.

from cognia.ux import aspecto as A


def _render24(mensaje, pie, columnas=100, teclas="hola\r", salir_a=None,
              historia=None):
    """Como _render pero en 24 bits (E5: distingue hexes vecinos). `salir_a`
    (segundos) cierra el prompt desde el loop: para mirar un estado que no
    termina solo (la busqueda Ctrl-R)."""
    import asyncio
    import io
    from prompt_toolkit import PromptSession
    from prompt_toolkit.data_structures import Size
    from prompt_toolkit.history import InMemoryHistory
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output.color_depth import ColorDepth
    from prompt_toolkit.output.vt100 import Vt100_Output

    buf = io.StringIO()
    out = Vt100_Output(buf, lambda: Size(rows=30, columns=columnas),
                       term="xterm-256color",
                       default_color_depth=ColorDepth.DEPTH_24_BIT)
    with create_pipe_input() as inp:
        inp.send_text(teclas)
        h = InMemoryHistory()
        for linea in (historia or []):
            h.append_string(linea)
        s = PromptSession(input=inp, output=out, bottom_toolbar=pie,
                          style=C._estilo_prompt(), history=h)

        def _pre():
            s.app.renderer._min_available_height = 6
            if salir_a is not None:
                asyncio.get_running_loop().call_later(
                    salir_a, lambda: s.app.exit(result=""))

        s.prompt(mensaje, pre_run=_pre)
    crudo = buf.getvalue()
    filas = [f.split("\r")[0].rstrip()
             for f in re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", crudo).split("\r\n")]
    return crudo, filas


def _rgb(hexs):
    return "38;2;{};{};{}".format(int(hexs[1:3], 16), int(hexs[3:5], 16), int(hexs[5:7], 16))


@pytest.fixture
def registro(tmp_path, monkeypatch):
    """El registro de estilos limpio y sin tocar el HOME; los overrides van
    en memoria (A.poner) y se descartan al salir."""
    monkeypatch.setattr(A, "RUTA_ESTILO", tmp_path / "estilo.json")
    for k in ("COGNIA_THEME", "COGNIA_REMOTO", "COGNIA_ASCII", "NO_COLOR"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(C, "_theme_idx", 0)
    A.reset()
    C._MEMO_FRAG.clear()
    yield A
    A.reset()
    C._MEMO_FRAG.clear()


def _pie_con_barra(datos=None, ancho=100):
    from cognia.harness.barra_estado import toolbar_partes
    return C._pie_prompt(toolbar_partes(lambda: dict(datos or DATOS), ancho=ancho,
                                        contexto_atajos="repl", unicode_ok=True,
                                        opciones=C._opciones_barra))


DATOS_CTX_ALTO = dict(DATOS, ctx_usado=110000, ctx_total=131072)


class TestElMarcoSaleDelRegistro:

    def test_sin_fichero_los_fragmentos_son_los_de_siempre(self, registro):
        assert [c for c, _ in C._mensaje_prompt()] == ["class:marco", "class:cognia", "class:flecha"]
        assert list(C._mensaje_prompt())[1][1] == " cognia"
        pie = list(_pie_con_barra()())
        assert [c for c, _ in pie] == ["class:marco", "class:estado"], pie
        assert pie[1][1].startswith("\nqwythos-9b")

    def test_el_render_es_el_verde_de_la_rampa_en_24_bits(self, registro):
        from cognia.ux import paleta
        crudo, _ = _render24(C._mensaje_prompt, C._pie_prompt())
        verde = paleta.rampa("oscuro")
        for escalon in ("marco", "prompt", "texto"):
            assert _rgb(verde[escalon]) in crudo, f"falta el {escalon} {verde[escalon]}"

    def test_la_etiqueta_renombrada_aparece_en_el_prompt(self, registro):
        A.poner("prompt.etiqueta", "texto", "jarvis")
        _, filas = _render24(C._mensaje_prompt, C._pie_prompt())
        assert any("jarvis" in f and "➤" in f for f in filas), filas[:5]
        assert not any("cognia" in f for f in filas)

    def test_la_flecha_cambia_de_glifo_y_puede_esconderse(self, registro):
        A.poner("prompt.flecha", "glifo", ">> ")
        partes = list(C._mensaje_prompt())
        assert partes[-1] == ("class:flecha", ">> ")
        A.poner("prompt.flecha", "visible", False)
        assert [c for c, _ in C._mensaje_prompt()] == ["class:marco", "class:cognia"]

    def test_el_color_del_dueno_llega_al_render(self, registro):
        A.poner("prompt.etiqueta", "color", "#ff00ff")
        crudo, _ = _render24(C._mensaje_prompt, C._pie_prompt())
        assert _rgb("#ff00ff") in crudo


class TestPosicionesDelMarco:

    def _reglas(self, filas):
        return [i for i, f in enumerate(filas) if f.strip() and f.strip("─-") == ""]

    def _prompt(self, filas):
        return next(i for i, f in enumerate(filas) if "cognia" in f)

    def test_arriba_quita_la_regla_inferior(self, registro):
        A.poner("prompt.marco", "posicion", "arriba")
        _, filas = _render24(C._mensaje_prompt, _pie_con_barra()())
        reglas, p = self._reglas(filas), self._prompt(filas)
        assert reglas and all(i < p for i in reglas), (reglas, p)
        assert any("qwythos-9b" in f for f in filas), "la barra sigue colgando"

    def test_abajo_quita_la_regla_superior(self, registro):
        A.poner("prompt.marco", "posicion", "abajo")
        _, filas = _render24(C._mensaje_prompt, _pie_con_barra()())
        reglas, p = self._reglas(filas), self._prompt(filas)
        assert reglas and all(i > p for i in reglas), (reglas, p)

    def test_ninguno_o_invisible_quita_las_dos(self, registro):
        A.poner("prompt.marco", "posicion", "ninguno")
        _, filas = _render24(C._mensaje_prompt, _pie_con_barra()())
        assert not self._reglas(filas)
        A.reset("prompt.marco")
        A.poner("prompt.marco", "visible", False)
        assert [c for c, _ in C._mensaje_prompt()] == ["class:cognia", "class:flecha"]

    def test_la_regla_cambia_de_glifo(self, registro):
        A.poner("prompt.marco", "glifo", "=")
        _, filas = _render24(C._mensaje_prompt, C._pie_prompt())
        assert sum(1 for f in filas if f.strip() and set(f.strip()) == {"="}) == 2

    def test_la_etiqueta_arriba_va_dentro_de_la_regla(self, registro):
        A.poner("prompt.etiqueta", "posicion", "arriba")
        partes = list(C._mensaje_prompt())
        assert [c for c, _ in partes] == ["class:marco", "class:cognia", "class:marco", "class:flecha"]
        assert partes[0][1] == "── " and partes[1][1] == "cognia"
        _, filas = _render24(C._mensaje_prompt, C._pie_prompt())
        f = next(f for f in filas if "cognia" in f)
        assert f.startswith("── cognia ─") and len(f) == C._ancho_marco()
        assert any(f.startswith("➤") for f in filas), "la flecha queda sola en la linea de entrada"


class TestLaBarraPorSecciones:

    def test_arriba_la_barra_pasa_sobre_el_marco_y_el_pie_queda_con_la_regla(self, registro):
        A.poner("barra.estado", "posicion", "arriba")
        pie = _pie_con_barra()
        _, filas = _render24(C._mensaje_prompt, pie)
        barra = next(i for i, f in enumerate(filas) if "qwythos-9b" in f)
        atajos = next(i for i, f in enumerate(filas) if "tab completa" in f)
        p = next(i for i, f in enumerate(filas) if "cognia" in f)
        assert barra < atajos < p, (barra, atajos, p)
        assert [c for c, _ in pie()] == ["class:marco"]

    def test_sin_override_la_barra_es_de_UN_solo_color(self, registro):
        crudo, filas = _render24(C._mensaje_prompt, _pie_con_barra(DATOS_CTX_ALTO)())
        linea = next(f for f in crudo.split("\r\n") if "qwythos-9b" in f)
        colores = set(re.findall(r"38;2;\d+;\d+;\d+", linea))
        assert len(colores) == 1, colores
        assert not A.tiene_override("barra.estado.secciones")

    def test_con_override_el_ctx_alto_sale_en_su_color(self, registro):
        A.poner("barra.estado.secciones", "estados.ctx_alto.color", "#ffaa00")
        pie = _pie_con_barra(DATOS_CTX_ALTO)
        clases = [c for c, _ in pie()]
        assert "class:estado.ctx-alto" in clases and "class:estado.modelo" in clases
        crudo, _ = _render24(C._mensaje_prompt, pie)
        linea = next(f for f in crudo.split("\r\n") if "qwythos-9b" in f)
        assert _rgb("#ffaa00") in linea
        assert len(set(re.findall(r"38;2;\d+;\d+;\d+", linea))) >= 2

    def test_el_preset_barra_color_pinta_secciones_en_ambas_posiciones(self, registro, tmp_path):
        A.cargar_preset("barra-color")
        for pos in ("abajo", "arriba"):
            A.poner("barra.estado", "posicion", pos)
            crudo, _ = _render24(C._mensaje_prompt, _pie_con_barra(DATOS_CTX_ALTO))
            linea = next(f for f in crudo.split("\r\n") if "qwythos-9b" in f)
            # warn_cl es ansiyellow: prompt_toolkit lo emite como '33' (16
            # colores) aunque la salida sea de 24 bits; el modelo (detail)
            # y el relleno siguen en hex: tres SGR distintos como minimo
            sgr = set(re.findall(r"\x1b\[[0-9;]*m", linea))
            assert any(";33" in s or "[33" in s for s in sgr), (pos, sgr)
            assert len(sgr) >= 3, (pos, sgr)

    def test_separador_visible_y_etiquetas_de_la_insignia(self, registro):
        A.poner("barra.estado", "separador", " | ")
        A.poner("barra.modo", "texto.plan", "PLANIFICANDO")
        texto = "".join(t for _, t in _pie_con_barra(dict(DATOS, modo="plan"))())
        assert " | " in texto and "PLANIFICANDO" in texto
        A.poner("barra.estado", "visible", False)
        texto = "".join(t for _, t in _pie_con_barra()())
        assert "qwythos-9b" not in texto and "tab completa" in texto
        A.poner("barra.atajos", "visible", False)
        assert [c for c, _ in _pie_con_barra()()] == ["class:marco"]


class TestBusquedaYSeleccionE2:
    """E2: la busqueda inversa Ctrl-R (prompt.busqueda) y la seleccion
    (prompt.seleccion) no tenian id; por defecto salen con el default de
    prompt_toolkit y con override, con el color del dueno."""

    def test_ctrl_r_por_defecto_no_lleva_color_propio(self, registro):
        crudo, filas = _render24(C._mensaje_prompt, C._pie_prompt(), teclas="\x12ho",
                                 salir_a=0.3, historia=["hola gato"])
        assert any("reverse-i-search" in f for f in filas), filas[:6]
        assert _rgb("#ff00ff") not in crudo
        reglas = dict(C._estilo_prompt().style_rules)
        assert reglas["prompt.search"] == "noinherit" and reglas["selected"] == "reverse"

    def test_ctrl_r_con_override_sale_en_el_color_del_dueno(self, registro):
        A.poner("prompt.busqueda", "color", "#ff00ff")
        A.poner("prompt.seleccion", "fondo", "#004466")
        reglas = dict(C._estilo_prompt().style_rules)
        assert reglas["prompt.search"] == "noinherit fg:#ff00ff"
        assert reglas["selected"] == "bg:#004466"
        crudo, filas = _render24(C._mensaje_prompt, C._pie_prompt(), teclas="\x12ho",
                                 salir_a=0.3, historia=["hola gato"])
        assert any("reverse-i-search" in f for f in filas), filas[:6]
        assert _rgb("#ff00ff") in crudo


class TestLasOtrasPiezas:

    def test_la_continuacion_y_la_espera_toman_su_texto_del_registro(self, registro):
        assert list(C._mensaje_continuacion()) == [("class:flecha", "   ")]
        A.poner("prompt.continuacion", "texto", " … ")
        # con override la clase heredada se completa con el estilo propio
        (clase, texto), = list(C._mensaje_continuacion())
        assert clase.startswith("class:flecha") and texto == " … "

        class _Corrida:
            etiqueta, t0 = "corrida", 0.0

        partes = list(C._mensaje_espera(_Corrida())())
        assert [c for c, _ in partes] == ["class:marco", "class:cognia", "class:estado", "class:flecha"]
        assert partes[2][1] == "  F2 agentes · Ctrl-C corta la corrida"
        A.poner("prompt.espera", "texto", "F2 ver agentes")
        assert list(C._mensaje_espera(_Corrida())())[2][1] == "  F2 ver agentes"

    def test_el_glow_estatico_pinta_por_caracter(self, registro, monkeypatch):
        from cognia.ux import glow as G
        G.forzar_capacidades(G.Caps("truecolor", False, ""))
        try:
            A.poner("prompt.etiqueta", "glow.intensidad", 2)
            A.conectar_glow()
            partes = list(C._mensaje_prompt())
            etiqueta = [p for p in partes if p[0] != "class:marco" and p[0] != "class:flecha"]
            assert len(etiqueta) > 1 and all(p[0].startswith("fg:#") for p in etiqueta), partes
            assert "".join(t for _, t in etiqueta) == " cognia"
        finally:
            G.forzar_capacidades(None)

    def test_el_repl_usa_la_barra_por_secciones_y_la_continuacion(self):
        import inspect
        fuente = inspect.getsource(C.repl)
        assert "toolbar_partes(_datos_barra_estado" in fuente
        assert "opciones=_opciones_barra" in fuente
        assert "session.prompt(\n                        _mensaje_continuacion" in fuente or \
            "_mensaje_continuacion, default=_sig" in fuente
        assert "toolbar_prompt_toolkit" not in fuente

    def test_los_ids_del_prompt_estan_enganchados(self):
        for id in ("prompt.marco", "prompt.etiqueta", "prompt.flecha", "prompt.texto",
                   "prompt.continuacion", "prompt.espera", "prompt.busqueda",
                   "prompt.seleccion", "barra.estado", "barra.estado.secciones",
                   "barra.atajos", "barra.modo", "menu.completado", "menu.selector"):
            assert A.REGISTRO[id].enganchado, id
            assert A.paso_pendiente(id, "color") == ""
        assert A.paso_pendiente("prompt.etiqueta", "animacion.activa") == ""   # P9
        assert A.paso_pendiente("prompt.espera", "animacion.activa") == ""
        assert A.paso_pendiente("barra.estado", "animacion.activa") == "P9"
        assert A.paso_pendiente("barra.estado", "glow.intensidad") == "P9"
        assert A.paso_pendiente("prompt.marco", "glow.intensidad") == ""


# ---------------------------------------------------------------------------
# P9: el pulso del prompt (seccion 3.3, E3). Determinista: capacidades
# forzadas, RELOJ fijado entre renders y el hilo del pulso con una app falsa.
# ---------------------------------------------------------------------------
from cognia.ux import glow as G


class _AppFalsa:
    def __init__(self):
        self.n = 0

    def invalidate(self):
        self.n += 1


@pytest.fixture
def animado(registro, monkeypatch):
    """prompt.etiqueta con barrido + glow 2 y la terminal forzada a animar."""
    G.forzar_capacidades(G.Caps("truecolor", True, ""))
    assert A.poner("prompt.etiqueta", "animacion.activa", True) == []
    assert A.poner("prompt.etiqueta", "glow.intensidad", 2) == []
    A.conectar_glow()
    C._MEMO_FRAG.clear()
    yield G
    G.parar_pulso()
    G.forzar_capacidades(None)
    G.RELOJ.reiniciar()
    C._MEMO_FRAG.clear()


def _truecolors(crudo):
    return set(re.findall(r"38;2;\d+;\d+;\d+", crudo))


class TestPulsoDelPromptP9:

    def test_dos_renders_distintos_durante_el_pulso_y_quieto_despues(self, animado):
        app = _AppFalsa()
        assert C._arrancar_pulso_prompt(app) is True
        assert G.animando()
        # (a t=0,3 el barrido pasa justo por la forma de la campana estatica:
        # se miran 0,6 y 0,9, que difieren de ella y entre si)
        G.RELOJ.fijar(G.RELOJ.t() + 0.6)
        crudo1, filas1 = _render24(C._mensaje_prompt, C._pie_prompt())
        G.RELOJ.fijar(G.RELOJ.t() + 0.3)
        crudo2, filas2 = _render24(C._mensaje_prompt, C._pie_prompt())
        assert filas1 == filas2, "el TEXTO no cambia, solo el color"
        assert crudo1 != crudo2, "dos cuadros del barrido tienen que pintar distinto"
        assert len(_truecolors(crudo1)) >= 2 and len(_truecolors(crudo2)) >= 2
        # el pulso termina (aqui: cortado) y el frame es el ESTATICO, memoizado
        G.parar_pulso()
        assert not G.animando()
        crudo3, _ = _render24(C._mensaje_prompt, C._pie_prompt())
        crudo4, _ = _render24(C._mensaje_prompt, C._pie_prompt())
        assert crudo3 == crudo4
        assert crudo3 != crudo1 and crudo3 != crudo2
        assert len(_truecolors(crudo3)) >= 2, "el glow fijo sigue por caracter"
        assert "cognia-pulso-prompt" not in [h.name for h in threading.enumerate()]

    def test_el_pulso_termina_solo_y_no_deja_hilos(self, animado):
        app = _AppFalsa()
        assert G.pulso_prompt(app, 0.25, 20) is True
        hilo = G._PULSO["hilo"]
        hilo.join(3.0)
        assert not hilo.is_alive()
        assert not G.animando()
        assert app.n >= 3, app.n     # ~5 invalidates + el ultimo (frame estatico)
        assert "cognia-pulso-prompt" not in [h.name for h in threading.enumerate()]
        # con el pulso muerto, el mismo prompt vuelve a arrancar uno
        assert C._arrancar_pulso_prompt(app) is True
        G.parar_pulso()

    def test_sin_animacion_no_hay_pulso_y_el_render_es_el_de_siempre(self, registro, monkeypatch):
        G.forzar_capacidades(G.Caps("truecolor", True, ""))
        try:
            antes, _ = _render24(C._mensaje_prompt, C._pie_prompt())
            app = _AppFalsa()
            assert C._arrancar_pulso_prompt(app) is False
            assert C._arrancar_pulso_prompt(app, C._IDS_PULSO_ESPERA) is False
            assert app.n == 0
            # aunque alguien deje el pulso "vivo", sin animacion las piezas
            # siguen siendo las clases de siempre (byte-identico)
            monkeypatch.setitem(G._PULSO, "activo", True)
            assert [c for c, _ in C._mensaje_prompt()] == ["class:marco", "class:cognia", "class:flecha"]
            despues, _ = _render24(C._mensaje_prompt, C._pie_prompt())
            assert antes == despues
        finally:
            G.forzar_capacidades(None)

    def test_sin_capacidad_de_animar_no_arranca(self, animado):
        G.forzar_capacidades(G.Caps("truecolor", False, "sin tty"))
        app = _AppFalsa()
        assert C._arrancar_pulso_prompt(app) is False
        assert not G.animando()

    def test_prompt_espera_anima_con_el_mismo_pulso(self, animado):
        assert A.poner("prompt.espera", "animacion.activa", True) == []
        assert A.poner("prompt.espera", "glow.intensidad", 2) == []
        A.conectar_glow()
        C._MEMO_FRAG.clear()

        import time

        class _Corrida:
            etiqueta, t0 = "corrida", time.time()

        app = _AppFalsa()
        assert C._arrancar_pulso_prompt(app, C._IDS_PULSO_ESPERA) is True
        assert C._PULSO_PROMPT["ids"] == C._IDS_PULSO_ESPERA
        G.RELOJ.fijar(G.RELOJ.t() + 0.6)   # 0,3-0,4 coincide con la campana
        vivo = list(C._mensaje_espera(_Corrida())())
        G.parar_pulso()
        quieto = list(C._mensaje_espera(_Corrida())())
        assert quieto == list(C._mensaje_espera(_Corrida())())
        assert vivo != quieto
        texto = "".join(t for _, t in vivo)
        assert texto == "".join(t for _, t in quieto)
        assert "corrida 0s" in texto and "F2 agentes" in texto
        assert sum(1 for c, _ in vivo if c.startswith("fg:#")) > 3

    def test_cada_s_rearma_desde_el_redibujado_y_respeta_repetir(self, animado):
        import time
        assert A.poner("prompt.etiqueta", "animacion.cada_s", 1.0) == []
        assert A.poner("prompt.etiqueta", "animacion.repetir", 2) == []
        A.conectar_glow()
        app = _AppFalsa()
        assert C._arrancar_pulso_prompt(app) is True
        assert C._PULSO_PROMPT["vueltas"] == 1 and C._PULSO_PROMPT["cada_s"] == 1.0
        assert C._rearmar_pulso_prompt(app) is False, "con el pulso vivo no rearma"
        G.parar_pulso()
        assert C._rearmar_pulso_prompt(app) is False, "la pausa cada_s no paso"
        C._PULSO_PROMPT["t_fin"] = time.monotonic() - 2.0
        assert C._rearmar_pulso_prompt(app) is True
        assert C._PULSO_PROMPT["vueltas"] == 2
        G.parar_pulso()
        C._PULSO_PROMPT["t_fin"] = time.monotonic() - 2.0
        assert C._rearmar_pulso_prompt(app) is False, "repetir=2 agotado"
        # el toolbar es quien rearma en el prompt idle: sin cada_s es un no-op
        assert A.poner("prompt.etiqueta", "animacion.cada_s", 0.0) == []
        A.conectar_glow()
        assert C._arrancar_pulso_prompt(app) is True
        G.parar_pulso()
        C._PULSO_PROMPT["t_fin"] = time.monotonic() - 2.0
        assert C._rearmar_pulso_prompt(app) is False, "sin cada_s no hay CPU permanente (E3)"

    def test_el_repl_y_la_espera_rodean_el_prompt_con_el_pulso(self):
        import inspect
        fuente = inspect.getsource(C.repl)
        i = fuente.index("_arrancar_pulso_prompt(session.app)")
        j = fuente.index("session.prompt(_mensaje_prompt, default=_pre)")
        k = fuente.index("_cerrar_pulso_prompt()")
        assert i < j < k
        espera = inspect.getsource(C._esperar_corrida)
        assert "_arrancar_pulso_prompt(app, _IDS_PULSO_ESPERA)" in espera
        assert "refresh_interval=1.0" in espera and "1 / " not in espera and "1.0 / " not in espera
        assert "_rearmar_pulso_prompt" in inspect.getsource(C._pie_prompt)
        assert "_rearmar_pulso_prompt" in inspect.getsource(C._mensaje_espera)
