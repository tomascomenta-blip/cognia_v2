"""
test_events_sink_tui.py -- El sink stdout del bus tiene que seguir hablando
cuando Textual toma la pantalla.

POR QUE ESTE TEST (medido 2026-08-17 sobre textual 8.2.8):

Con una App de Textual corriendo, ``sys.stdout`` deja de ser el stdout real y
pasa a ser ``textual.app._PrintCapture``. Su ``write()`` va a
``App._print()``, que en textual/app.py:2097-2105 hace SOLO dos cosas con el
texto:

    if self.is_headless:                      # <- cortesia del arnes de tests
        target_stream = self._original_stdout
        target_stream.write(text)
    for target in self._capture_print: ...    # <- widgets que pidieron capturar

En la app REAL ``is_headless`` es False y ningun widget de Cognia llama a
``begin_capture_print``: el texto se DESCARTA. Y ``_PrintCapture.flush()`` ni
siquiera llega al stream real (App._flush solo avisa a devtools), asi que el
flush por linea que el remoto necesita tambien se perdia.

Quien lo paga: ``cognia/remoto/sesiones.py`` lanza el REPL con
COGNIA_EVENTS_JSONL=1 y lee ese stdout LINEA A LINEA -- es su UNICO canal. Con
la vista de agentes abierta, el telefono se quedaba ciego.

TRAMPA DEL ARNES: ``app.run_test()`` fuerza headless, o sea que el reenvio de
cortesia de arriba tapa el bug. Un test que solo abra la App headless PASA HOY
y no protege de nada. Por eso el test de regresion neutraliza
``app._original_stdout`` (usado UNICAMENTE en ese reenvio, grep en textual:
app.py:800/2099), que es exactamente la situacion de produccion.
"""

from __future__ import annotations

import io
import json
import sys
import threading

import pytest

from cognia.ux import events


class _Nulo:
    """Stream que traga todo: reproduce el _print de la app NO headless."""

    def write(self, text: str) -> None:
        pass

    def flush(self) -> None:
        pass


@pytest.fixture
def bus_limpio():
    """El bus es modulo-global: se guarda y se restaura entero."""
    with events._lock:
        previos = list(events._suscriptores)
        events._suscriptores.clear()
    sink_previo = events._sink_jsonl
    events._sink_jsonl = None
    yield
    with events._lock:
        events._suscriptores.clear()
        events._suscriptores.extend(previos)
    events._sink_jsonl = sink_previo


def _emitir_desde_hilo(n: int) -> None:
    """Los eventos del motor de workflows salen del hilo worker, no del de la
    UI: se emite desde un hilo para medir la condicion real."""
    def _cuerpo():
        for i in range(n):
            events.emitir(events.Aviso(texto=f"evento-{i}", origen="test_sink_tui"))

    h = threading.Thread(target=_cuerpo)
    h.start()
    h.join(timeout=10)
    assert not h.is_alive(), "el hilo emisor se colgo"


def _lineas_ev(texto: str) -> list[dict]:
    out = []
    for linea in texto.splitlines():
        if linea.startswith(events.PREFIJO_STDOUT):
            out.append(json.loads(linea[len(events.PREFIJO_STDOUT):]))
    return out


@pytest.mark.asyncio
async def test_sink_stdout_habla_con_app_de_textual_abierta(bus_limpio, monkeypatch):
    """LA REGRESION: 3 eventos emitidos desde un hilo con la App abierta tienen
    que dar 3 lineas '@EV' en el stdout REAL. Antes del fix: 0 de 3."""
    from cognia.tui.app import CogniaTUI

    real = io.StringIO()
    # El "stdout real" del proceso para este test. El fix escribe aca; el print
    # de antes escribia al sys.stdout del momento (el _PrintCapture de Textual).
    monkeypatch.setattr(sys, "__stdout__", real)

    events.activar_sink_jsonl("1")

    app = CogniaTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        # Con la App abierta, sys.stdout YA NO es el stdout real: esa es la
        # condicion que rompia el canal del movil.
        assert sys.stdout is not sys.__stdout__
        assert type(sys.stdout).__name__ == "_PrintCapture"
        # Se apaga el reenvio de cortesia del modo headless: sin esto el test
        # pasaria hoy y no vigilaria nada (ver el docstring del modulo).
        app._original_stdout = _Nulo()

        _emitir_desde_hilo(3)
        await pilot.pause()

    eventos = _lineas_ev(real.getvalue())
    assert len(eventos) == 3, f"llegaron {len(eventos)} de 3 al stdout real"
    assert [e["texto"] for e in eventos] == ["evento-0", "evento-1", "evento-2"]
    assert all(e["tipo"] == "Aviso" for e in eventos)


@pytest.mark.asyncio
async def test_el_formato_de_linea_no_cambia_con_la_app_abierta(bus_limpio, monkeypatch):
    """El formato es un CONTRATO con remoto/sesiones.py: prefijo '@EV ', un
    JSON por linea y un unico '\\n' al final. Se compara byte a byte la linea
    emitida sin App contra la emitida con la App abierta."""
    from cognia.tui.app import CogniaTUI

    real = io.StringIO()
    monkeypatch.setattr(sys, "__stdout__", real)
    events.activar_sink_jsonl("1")

    ev = events.Aviso(texto="misma cosa", origen="test_sink_tui")
    events.emitir(ev)
    sin_app = real.getvalue()

    real.seek(0)
    real.truncate(0)
    app = CogniaTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        app._original_stdout = _Nulo()
        events.emitir(ev)
        await pilot.pause()
    con_app = real.getvalue()

    assert con_app == sin_app != ""
    assert con_app.startswith(events.PREFIJO_STDOUT)
    assert con_app.endswith("\n") and con_app.count("\n") == 1


def test_sink_stdout_no_revienta_si_no_hay_stdout_real(bus_limpio, monkeypatch):
    """sys.__stdout__ es None en pythonw y en algunos empaquetados. DECISION:
    se cae a sys.stdout (que es lo que se hacia antes del fix: nunca peor que
    hoy); si tampoco hay, no se escribe y NO se lanza."""
    monkeypatch.setattr(sys, "__stdout__", None)
    suplente = io.StringIO()
    monkeypatch.setattr(sys, "stdout", suplente)
    events.activar_sink_jsonl("1")

    events.emitir(events.Aviso(texto="sin stdout real", origen="test_sink_tui"))
    assert len(_lineas_ev(suplente.getvalue())) == 1

    # Los dos en None: el turno sigue vivo (emitir es no-lanzante por contrato,
    # pero el sink tampoco debe depender de ese paraguas).
    monkeypatch.setattr(sys, "stdout", None)
    events._escribir_stdout_real("{}")   # llamada DIRECTA: sin el try de emitir
    events.emitir(events.Aviso(texto="nada", origen="test_sink_tui"))


def test_un_solo_write_por_evento(bus_limpio, monkeypatch):
    """print() hace DOS write() (texto y salto de linea) y dos hilos pueden
    colarse entre medias. El sink hace UNO solo, bajo candado."""
    escrituras: list[str] = []

    class _Contador:
        def write(self, text: str) -> None:
            escrituras.append(text)

        def flush(self) -> None:
            pass

    monkeypatch.setattr(sys, "__stdout__", _Contador())
    events.activar_sink_jsonl("1")
    events.emitir(events.Aviso(texto="una sola", origen="test_sink_tui"))

    assert len(escrituras) == 1
    assert escrituras[0].startswith(events.PREFIJO_STDOUT)
    assert escrituras[0].endswith("\n")


# ── El OTRO canal que Textual no intercepta: el handler de consola del logger ─
#
# logger_config.py construye su handler de consola en el IMPORT con
# logging.StreamHandler(sys.stderr): se queda con el OBJETO stderr real. Cuando
# Textual arranca cambia sys.stderr por su _PrintCapture, pero el handler ya
# tiene la referencia vieja y le escribe igual -> ANSI crudo encima de la
# pantalla alterna. Medido en el repro: con la App abierta,
# `_CONSOLE_HANDLER.stream is sys.__stderr__` -> True y el WARNING salio.
#
# No se pierde el log: el archivo (~/.cognia/logs/cognia.log) lo recibe siempre
# y la TUI lo pinta en la vista Logs via TuiLogHandler.

import logging                                   # noqa: E402

from cognia import logger_config                 # noqa: E402


@pytest.mark.asyncio
async def test_el_handler_de_consola_no_ve_el_stderr_de_textual():
    """La premisa del problema. El handler se quedo con el stderr que habia en
    el import, y Textual cambia sys.stderr DESPUES: el handler no se entera y
    escribe fuera de la TUI.

    OJO con el arnes: bajo pytest, sys.stderr ya esta reemplazado por la
    captura ANTES del import, asi que aca el stream NO es sys.__stderr__ sino
    el fichero temporal de pytest. En el proceso real si lo es (medido en el
    repro: `_CONSOLE_HANDLER.stream is sys.__stderr__` -> True). Lo que se
    afirma aca es lo que vale en los dos mundos: el stream del handler NO es
    el sys.stderr que instala Textual."""
    from cognia.tui.app import CogniaTUI

    h = logger_config._CONSOLE_HANDLER
    assert h is not None
    app = CogniaTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert type(sys.stderr).__name__ == "_PrintCapture"
        assert h.stream is not sys.stderr


def test_silenciar_y_restaurar_la_consola():
    previo = logger_config._CONSOLE_HANDLER.level
    devuelto = logger_config.silenciar_consola()
    assert devuelto == previo
    assert logger_config._CONSOLE_HANDLER.level > logging.CRITICAL
    logger_config.restaurar_consola(devuelto)
    assert logger_config._CONSOLE_HANDLER.level == previo
    # None = "no lo silencie yo": no toca nada.
    logger_config.restaurar_consola(None)
    assert logger_config._CONSOLE_HANDLER.level == previo


@pytest.mark.asyncio
async def test_un_log_con_la_tui_abierta_no_ensucia_la_pantalla(monkeypatch):
    """Con la TUI abierta el WARNING va al panel y NO al stderr; al cerrar,
    la consola vuelve a hablar."""
    from cognia.tui.app import CogniaTUI
    from cognia.tui.widgets.logspanel import LogsPanel

    consola = logger_config._CONSOLE_HANDLER
    espia = io.StringIO()
    nivel_original = consola.level
    monkeypatch.setattr(consola, "stream", espia)

    app = CogniaTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("5")            # vista Logs, para que el RichLog mida
        await pilot.pause()
        logging.getLogger("cognia.tui.prueba_sink").warning("no me pintes la pantalla")
        await pilot.pause()

        assert espia.getvalue() == "", "el log se escribio sobre la pantalla alterna"
        # ...pero NO se perdio: se callo el handler de CONSOLA, no el logger.
        # El de ARCHIVO (~/.cognia/logs/cognia.log) sigue enganchado y con su
        # nivel intacto, que es la otra mitad de "no se pierde nada".
        archivos = [h for h in logging.getLogger("cognia").handlers
                    if isinstance(h, logging.FileHandler)]
        assert archivos, "el handler de archivo desaparecio"
        assert all(h.level <= logging.WARNING for h in archivos)
        panel = app.query_one(LogsPanel)
        texto = "\n".join(s.text for s in panel.lines)
        for diferido in getattr(panel, "_deferred_renders", []):
            c = getattr(diferido, "content", "")
            texto += "\n" + (c.plain if hasattr(c, "plain") else str(c))
        assert "no me pintes la pantalla" in texto, "el log tampoco llego al panel"

    # Cerrada la app, el nivel de consola vuelve a ser el de antes y escribe.
    assert consola.level == nivel_original
    logging.getLogger("cognia.tui.prueba_sink").warning("ahora si")
    assert "ahora si" in espia.getvalue()


# ── El OTRO agujero del mismo bug: contextlib.redirect_stdout ────────────────

def test_el_sink_escapa_de_un_redirect_stdout(bus_limpio, monkeypatch):
    """cli.py:1558 corre CADA comando del REPL dentro de
    `contextlib.redirect_stdout(captured)` para que los print() internos no
    ensucien el spinner. Con el sink viejo (print) los eventos emitidos ahi
    dentro caian en ese StringIO y el movil no los veia NUNCA — el mismo bug
    que la App de Textual, otra tapadera.

    Medido antes del fix: 1 linea al buffer, 0 al stdout real. Despues: 0 y 1,
    y la linea es BYTE A BYTE la misma."""
    import contextlib

    real = io.StringIO()
    monkeypatch.setattr(sys, "__stdout__", real)
    events.activar_sink_jsonl("1")

    tragadas = io.StringIO()
    with contextlib.redirect_stdout(tragadas):
        events.emitir(events.Aviso(texto="dentro-del-redirect", origen="test_sink_tui"))

    assert "@EV" not in tragadas.getvalue(), "el evento se lo trago el redirect"
    assert len(_lineas_ev(real.getvalue())) == 1

    # Y no se rompe el eco: la prosa que el CLI SI queria capturar sigue ahi.
    with contextlib.redirect_stdout(tragadas):
        print("prosa interna del comando")
    assert "prosa interna del comando" in tragadas.getvalue()


# ── T4 (2026-08-18): LOS DOS MUNDOS DEL SINK ────────────────────────────────
#
# El T3 escribia SIEMPRE a sys.__stdout__ y eso choca con el carril de fondo
# del REPL: con la vista de agentes abierta, esas lineas "@EV {...}" se pintan
# crudas ENCIMA de la pantalla alterna (el spike T4 midio 6 lineas de
# suciedad). Escribir a sys.stdout arregla la pantalla y deja CIEGO al
# telefono, que es una restriccion dura.
#
# No se elige: se MIDE. Los dos mundos son distinguibles por una razon FISICA,
# comprobada el 2026-08-18 con el mismo ConPTY del spike:
#
#     mundo PIPE (el del movil) ... sys.__stdout__.isatty() -> False
#                                   (remoto/sesiones.py:712, stdout=PIPE)
#     mundo CONSOLA (el humano) ... sys.__stdout__.isatty() -> True
#                                   (ConPTY = la maquinaria de Windows Terminal)
#
# Y la implicacion va en las dos direcciones: donde hay pantalla alterna NO hay
# telefono escuchando, y donde hay telefono NO hay pantalla alterna. Un test
# por mundo.


class _Tty(io.StringIO):
    """Un stream que dice ser un terminal. El mundo CONSOLA."""

    def isatty(self) -> bool:
        return True


class _Pipe(io.StringIO):
    """Un stream que dice NO ser un terminal. El mundo PIPE (el del movil)."""

    def isatty(self) -> bool:
        return False


def test_mundo_pipe_el_movil_ve_los_eventos(bus_limpio, monkeypatch):
    """MUNDO PIPE: el stdout real no es un tty -> se escribe AHI, pase lo que
    pase con sys.stdout. Es el canal unico de remoto/sesiones.py y la
    restriccion dura: el movil no se rompe."""
    real = _Pipe()
    tapadera = io.StringIO()          # lo que Textual / redirect_stdout pondria
    monkeypatch.setattr(sys, "__stdout__", real)
    monkeypatch.setattr(sys, "stdout", tapadera)
    events.activar_sink_jsonl("1")

    events.emitir(events.Aviso(texto="para-el-movil", origen="test_sink_tui"))

    assert [e["texto"] for e in _lineas_ev(real.getvalue())] == ["para-el-movil"]
    assert "@EV" not in tapadera.getvalue(), "el evento se lo trago la tapadera"


def test_mundo_consola_el_evento_no_pisa_la_pantalla(bus_limpio, monkeypatch):
    """MUNDO CONSOLA: el stdout real ES un tty -> se escribe al sys.stdout DEL
    MOMENTO. Sin Textual eso es el mismo terminal (nadie nota nada); con
    Textual es su _PrintCapture, y ahi la vista lo recoge en vez de dejar que
    se pinte sobre la pantalla alterna."""
    real = _Tty()
    events.activar_sink_jsonl("1")

    # (a) mundo consola SIN Textual: sys.stdout es el terminal -> llega igual.
    monkeypatch.setattr(sys, "__stdout__", real)
    monkeypatch.setattr(sys, "stdout", real)
    events.emitir(events.Aviso(texto="sin-textual", origen="test_sink_tui"))
    assert [e["texto"] for e in _lineas_ev(real.getvalue())] == ["sin-textual"]

    # (b) mundo consola CON algo interceptando stdout (lo que hace Textual):
    #     la linea va al interceptor y NO se pinta sobre la pantalla alterna.
    interceptor = io.StringIO()
    monkeypatch.setattr(sys, "stdout", interceptor)
    events.emitir(events.Aviso(texto="con-textual", origen="test_sink_tui"))
    assert [e["texto"] for e in _lineas_ev(interceptor.getvalue())] == ["con-textual"]
    assert "con-textual" not in real.getvalue(), \
        "la linea-evento se pinto sobre la pantalla alterna"


@pytest.mark.asyncio
async def test_la_vista_del_repl_recoge_los_eventos_del_mundo_consola(
        bus_limpio, monkeypatch):
    """LA INTEGRACION de los dos arreglos, en el mundo consola.

    La subclase que abre el REPL (cli._vista_con_corte) llama a
    begin_capture_print en on_mount porque Textual TRAGA lo que el hilo
    imprime y sin eso lo DESCARTA (medido en el spike T4: 6 de 18 lineas
    desaparecidas). Con el corte por tty, las lineas "@EV" del mundo consola
    caen justo en esa captura: ni ensucian la pantalla ni se pierden."""
    from cognia import cli
    from cognia.tui.agentes import PantallaAgentes

    real = _Tty()
    monkeypatch.setattr(sys, "__stdout__", real)
    events.activar_sink_jsonl("1")

    app = cli._vista_con_corte(PantallaAgentes)()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert type(sys.stdout).__name__ == "_PrintCapture"
        # Se apaga el reenvio de cortesia del modo headless (ver el docstring
        # del modulo): sin esto el test no vigilaria nada.
        app._original_stdout = _Nulo()
        _emitir_desde_hilo(3)
        await pilot.pause()
        tragadas = "".join(app.lineas_tragadas)

    assert [e["texto"] for e in _lineas_ev(tragadas)] == \
        ["evento-0", "evento-1", "evento-2"], \
        f"la vista recogio {tragadas!r}"
    assert "@EV" not in real.getvalue(), \
        "las lineas-evento se pintaron sobre la pantalla alterna"
