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
