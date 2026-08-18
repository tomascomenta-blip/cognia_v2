"""
tests/test_cli_carril_fondo.py
==============================
EL CARRIL DE FONDO del REPL: la corrida larga en un hilo, la consola arbitrada
por el hilo PRINCIPAL (cognia/cli.py, T4 2026-08-18).

Por que este fichero existe: el carril entro al arbol verificado A MANO dentro
de un ConPTY (modos de consola, SGR intactos, F2, Ctrl-C, el sink del movil) y
con CERO tests. Todo lo que lo defendia era la memoria de una persona: ningun
fichero de tests/ mencionaba _lanzar_en_fondo, _esperar_corrida, _vista_con_corte,
_abrir_vista_agentes, _volcar_lineas_tragadas, _ctrlc_seguidos_idle ni
COGNIA_SIN_FONDO. Aca se cubre pieza por pieza, con el carril REAL.

QUE ES REAL Y QUE NO
--------------------
REAL: la PromptSession de prompt_toolkit (sobre un pipe, con PlainTextOutput a
un StringIO — asi se puede LEER lo que el usuario habria visto: el marco del
prompt de espera, las lineas del hilo y los avisos), _lanzar_en_fondo /
_esperar_corrida / _cancelar_corrida de verdad, hilos de verdad, y la vista de
Textual REAL (cognia.tui.agentes.PantallaAgentes en headless, con su CSS).
SIMULADO: solo el teclado (se empuja texto por el pipe, incluido "\\x03" para
el Ctrl-C) y, en el test del hueco, la excepcion que el ConPTY del spike no
sabe entregar (ver TestElHuecoDelCtrlC).

LO QUE NO SE DUPLICA AQUI
-------------------------
* El SINK de eventos (mundo pipe = el movil ve @EV / mundo consola = no se
  pinta sobre la pantalla alterna) ya esta cubierto, y mejor, en
  tests/test_events_sink_tui.py:
    - test_mundo_pipe_el_movil_ve_los_eventos
    - test_mundo_consola_el_evento_no_pisa_la_pantalla
    - test_la_vista_del_repl_recoge_los_eventos_del_mundo_consola
      (usa cli._vista_con_corte y begin_capture_print, que es la pieza del
       carril que hace que el mundo consola no se pierda nada)
* El PERMISO pedido desde el hilo: tests/test_cli_permiso_desde_hilo.py.

MEDIDO en esta maquina el 2026-08-18 (Windows 11, venv312) mientras se escribia
este fichero:
  * Ctrl-C por el pipe con una corrida viva -> c.cancelada en 11,3 ms.
  * el marco del prompt de espera sale tal cual: "workflow 0s  F2 agentes ·
    Ctrl-C corta la corrida".
  * el hueco del Ctrl-C (KeyboardInterrupt FUERA del prompt) ESCAPABA de
    _lanzar_en_fondo antes del fix de hoy y ahora no.
"""
from __future__ import annotations

import contextlib
import io
import os
import re
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prompt_toolkit import PromptSession                       # noqa: E402
from prompt_toolkit.application import create_app_session      # noqa: E402
from prompt_toolkit.input import create_pipe_input             # noqa: E402
from prompt_toolkit.output.plain_text import PlainTextOutput   # noqa: E402

import cognia.cli as cli                                       # noqa: E402
from cognia.harness import barra_estado as B                   # noqa: E402


# ---------------------------------------------------------------------------
# Andamio
# ---------------------------------------------------------------------------
class _BaseCarril(unittest.TestCase):
    """Deja el modulo cli como estaba: el carril son TODO globales de modulo."""

    def setUp(self):
        self._env = os.environ.get("COGNIA_SIN_FONDO")
        self._spin = os.environ.get("COGNIA_SPINNER")
        os.environ.pop("COGNIA_SIN_FONDO", None)
        self._guardado = {
            "_sesion_prompt": cli._sesion_prompt,
            "_CORRIDA": cli._CORRIDA,
            "_vista": cli._VISTA.get("app"),
            "_ultimo_ctrlc": cli._ULTIMO_CTRLC[0],
        }
        cli._COLA_ENTRADA.clear()
        cli._AVISOS_VISTOS.clear()
        cli._ULTIMO_CTRLC[0] = 0.0
        self.pantalla = io.StringIO()

    def tearDown(self):
        cli._sesion_prompt = self._guardado["_sesion_prompt"]
        cli._CORRIDA = self._guardado["_CORRIDA"]
        cli._VISTA["app"] = self._guardado["_vista"]
        cli._ULTIMO_CTRLC[0] = self._guardado["_ultimo_ctrlc"]
        cli._COLA_ENTRADA.clear()
        cli._AVISOS_VISTOS.clear()
        for var, valor in (("COGNIA_SIN_FONDO", self._env),
                           ("COGNIA_SPINNER", self._spin)):
            if valor is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = valor

    @contextlib.contextmanager
    def carril(self):
        """Un carril de fondo de verdad, y con la pantalla LEGIBLE.

        PlainTextOutput y no DummyOutput: con DummyOutput, patch_stdout manda
        lo que imprime el hilo al output de la app_session y se DESCARTA
        (medido: 0 caracteres), asi que no habria forma de comprobar que el
        resultado se imprimio ni cuantas veces."""
        with create_pipe_input() as pipe:
            with create_app_session(input=pipe,
                                    output=PlainTextOutput(self.pantalla)):
                cli._sesion_prompt = PromptSession()
                _stdout = sys.stdout
                sys.stdout = self.pantalla
                try:
                    yield pipe
                finally:
                    sys.stdout = _stdout
                    cli._sesion_prompt = None

    @staticmethod
    def esperar_prompt(timeout=10.0) -> bool:
        """True cuando el prompt de espera esta bloqueado y escuchando."""
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < timeout:
            app = getattr(cli._sesion_prompt, "app", None)
            if app is not None and getattr(app, "is_running", False):
                return True
            time.sleep(0.005)
        return False

    def visto(self) -> str:
        """Lo que el usuario habria visto (prompt incluido)."""
        return self.pantalla.getvalue()


class _Sonda:
    """Cuenta ejecuciones y anota EN QUE HILO corrio cada una."""

    def __init__(self, imprime: str = "", boom: BaseException | None = None):
        self.veces = 0
        self.hilos: list = []
        self.args: list = []
        self._imprime = imprime
        self._boom = boom

    def __call__(self, *a, **kw):
        self.veces += 1
        self.hilos.append(threading.current_thread() is threading.main_thread())
        self.args.append((a, kw))
        if self._imprime:
            print(self._imprime)
        if self._boom is not None:
            raise self._boom

    @property
    def en_el_principal(self) -> bool:
        return all(self.hilos)


def _dispatch(etiqueta, fn, *a):
    """La forma EXACTA de los tres call sites del REPL (cli.py 7840/9068/9087).

    Es lo que hace que "el carril devolvio False" signifique "se ejecuta
    inline" y no "no se ejecuta": si _lanzar_en_fondo se equivoca en el
    booleano, el turno se corre DOS veces o NINGUNA."""
    if not cli._lanzar_en_fondo(etiqueta, fn, *a):
        fn(*a)


# ---------------------------------------------------------------------------
# 1. El interruptor: COGNIA_SIN_FONDO=1 y el default
# ---------------------------------------------------------------------------
class TestInterruptor(_BaseCarril):

    def test_sin_fondo_1_devuelve_el_camino_de_siempre(self):
        """COGNIA_SIN_FONDO=1 es la salida de emergencia: nada de hilos, el
        turno corre INLINE en el hilo principal, una sola vez."""
        os.environ["COGNIA_SIN_FONDO"] = "1"
        sonda = _Sonda()
        with self.carril():
            self.assertTrue(cli._sin_carril())
            _dispatch("workflow", sonda, " demo")
        self.assertEqual(sonda.veces, 1, "el turno no se ejecuto exactamente 1 vez")
        self.assertTrue(sonda.en_el_principal, "con el interruptor NO hay hilo")
        self.assertEqual(sonda.args[0][0], (" demo",), "se perdio el argumento")
        self.assertIsNone(cli._CORRIDA, "se monto una corrida con el carril apagado")

    def test_por_defecto_manda_el_carril(self):
        """El default es el carril: el turno corre en un hilo, una sola vez."""
        sonda = _Sonda()
        with self.carril():
            self.assertFalse(cli._sin_carril())
            _dispatch("workflow", sonda, " demo")
        self.assertEqual(sonda.veces, 1)
        self.assertFalse(sonda.en_el_principal,
                         "el turno corrio en el hilo principal: no hubo carril")

    def test_sin_promptsession_no_hay_carril(self):
        """Pipes, CI, subprocess: sin PromptSession nadie puede esperar con el
        teclado vivo, asi que el carril se aparta y el caller ejecuta inline."""
        cli._sesion_prompt = None
        sonda = _Sonda()
        _dispatch("hacer", sonda)
        self.assertFalse(cli._lanzar_en_fondo("hacer", sonda))
        self.assertEqual(sonda.veces, 1)
        self.assertTrue(sonda.en_el_principal)

    def test_el_interruptor_se_lee_en_CADA_llamada(self):
        """Se lee del entorno a call-time (no cacheado en un import): el e2e
        compara los dos brazos en el mismo proceso."""
        os.environ["COGNIA_SIN_FONDO"] = "1"
        self.assertTrue(cli._sin_carril())
        os.environ["COGNIA_SIN_FONDO"] = "0"
        self.assertFalse(cli._sin_carril(), "solo '1' apaga el carril")
        os.environ.pop("COGNIA_SIN_FONDO")
        self.assertFalse(cli._sin_carril())

    def test_una_sola_corrida_por_vez_y_sin_doble_ejecucion(self):
        """El carril es EXCLUSIVO. El segundo /workflow avisa y devuelve True:
        si devolviera False el caller lo correria INLINE, con dos turnos
        peleandose _history, el cwd y el unico slot de :8080."""
        segunda = _Sonda()
        res = {}

        def primera():
            res["lanzada"] = cli._lanzar_en_fondo("workflow", segunda)

        with self.carril():
            cli._lanzar_en_fondo("hacer", primera)
        self.assertIs(res.get("lanzada"), True,
                      "la 2a corrida devolvio False: el REPL la correria inline")
        self.assertEqual(segunda.veces, 0, "arrancaron DOS corridas a la vez")
        self.assertIn("Ya hay una corrida en curso", self.visto())


# ---------------------------------------------------------------------------
# 2. Un workflow al fondo: hilo, prompt de espera, y el resultado UNA vez
# ---------------------------------------------------------------------------
class TestCorridaEnFondo(_BaseCarril):

    def test_el_hilo_corre_el_prompt_espera_y_el_resultado_sale_una_vez(self):
        marca = "RESULTADO-DEL-WORKFLOW"
        vio_prompt = {}

        def trabajo(arg):
            # El prompt de espera tiene que estar ABIERTO mientras el hilo
            # trabaja: eso es el carril. Si no abre, el REPL esta bloqueado.
            vio_prompt["abierto"] = self.esperar_prompt()
            vio_prompt["corrida"] = cli.corrida_en_curso()
            vio_prompt["control"] = cli.control_de_la_corrida()
            print(marca)

        sonda = _Sonda()

        def fn(arg):
            sonda(arg)
            trabajo(arg)

        with self.carril():
            _dispatch("workflow", fn, " demo")

        pantalla = self.visto()
        self.assertTrue(vio_prompt.get("abierto"), "el prompt de espera no abrio")
        self.assertTrue(vio_prompt.get("corrida"),
                        "corrida_en_curso() dijo False con el hilo trabajando")
        self.assertEqual(vio_prompt["control"]["etiqueta"], "workflow")
        self.assertEqual(sonda.veces, 1)
        self.assertFalse(sonda.en_el_principal)
        self.assertEqual(pantalla.count(marca), 1,
                         f"el resultado se imprimio {pantalla.count(marca)} veces")
        # El marco del prompt de espera, tal cual lo ve el usuario.
        self.assertIn("workflow", pantalla)
        self.assertIn("F2 agentes", pantalla)
        self.assertIn("Ctrl-C corta la corrida", pantalla)
        # Y al terminar no queda nada colgado.
        self.assertIsNone(cli._CORRIDA)
        self.assertFalse(cli.corrida_en_curso())
        self.assertFalse(cli.control_de_la_corrida()["activa"])

    def test_el_spinner_se_apaga_durante_la_corrida_y_se_restaura(self):
        """El Live de rich y el prompt no pueden compartir la consola: medido,
        un status() de 3 s dejo 14 lineas 'pensando…' en el scrollback."""
        os.environ["COGNIA_SPINNER"] = "1"
        visto = {}

        def fn():
            visto["dentro"] = os.environ.get("COGNIA_SPINNER")

        with self.carril():
            cli._lanzar_en_fondo("hacer", fn)
        self.assertEqual(visto.get("dentro"), "0", "el spinner siguio encendido")
        self.assertEqual(os.environ.get("COGNIA_SPINNER"), "1",
                         "no se restauro el valor del usuario")

    def test_una_excepcion_del_hilo_se_ve_y_no_mata_el_repl(self):
        """El hilo no muere mudo: la excepcion vuelve al principal y se pinta.
        Sin esto un /hacer que revienta se veria como un turno que 'no dijo
        nada' — el fallo silencioso que este repo persigue."""
        sonda = _Sonda(boom=RuntimeError("se rompio el motor"))
        with self.carril():
            self.assertTrue(cli._lanzar_en_fondo("hacer", sonda))
        pantalla = self.visto()
        self.assertIn("RuntimeError", pantalla)
        self.assertIn("se rompio el motor", pantalla)
        self.assertIsNone(cli._CORRIDA)


# ---------------------------------------------------------------------------
# 3. Las lineas que la vista se trago se vuelcan al cerrar
# ---------------------------------------------------------------------------
try:
    from cognia.tui import agentes as _agentes
    _HAY_VISTA = True
except Exception as _exc_vista:                            # pragma: no cover
    _HAY_VISTA = False
    _MOTIVO_VISTA = f"{type(_exc_vista).__name__}: {_exc_vista}"


class _AppFalsa:
    def __init__(self, lineas):
        self.lineas_tragadas = list(lineas)


class TestVolcadoDeLineasTragadas(_BaseCarril):

    def _volcar(self, app) -> str:
        _stdout = sys.stdout
        sys.stdout = self.pantalla
        try:
            cli._volcar_lineas_tragadas(app)
        finally:
            sys.stdout = _stdout
        return self.visto()

    def test_se_vuelcan_en_orden_y_sin_duplicar(self):
        lineas = [f"linea-{i}\n" for i in range(6)]
        salida = self._volcar(_AppFalsa(lineas))
        for l in lineas:
            self.assertEqual(salida.count(l.strip()), 1,
                             f"{l.strip()} salio {salida.count(l.strip())} veces")
        posiciones = [salida.index(l.strip()) for l in lineas]
        self.assertEqual(posiciones, sorted(posiciones), "se volcaron desordenadas")
        self.assertIn("6 linea(s) que la vista habia tragado", salida)

    def test_sin_lineas_no_ensucia_nada(self):
        self.assertEqual(self._volcar(_AppFalsa([])), "")
        self.assertEqual(self._volcar(object()), "",
                         "una app sin el atributo no puede romper el cierre")

    def test_la_ultima_linea_sin_salto_no_se_pega_al_prompt(self):
        salida = self._volcar(_AppFalsa(["a\n", "sin-salto"]))
        self.assertTrue(salida.endswith("sin-salto\n"))

    def test_de_punta_a_punta_con_la_vista_real(self):
        """La vista REAL de Textual (headless) traga los print del hilo con
        begin_capture_print y el REPL los devuelve al cerrar. Medido en el
        spike: sin la captura se PERDIAN 6 de 18."""
        if not _HAY_VISTA:
            self.fail(f"cognia.tui.agentes no importa: {_MOTIVO_VISTA}")
        clase = cli._vista_con_corte(_agentes.PantallaAgentes)
        app = clase()
        esperando = threading.Event()

        async def piloto(pilot):
            await pilot.pause()
            # El reenvio de cortesia del modo headless mandaria los print al
            # stdout real; se apaga para vigilar SOLO lo que traga la vista.
            app._original_stdout = io.StringIO()
            hilo = threading.Thread(
                target=lambda: [print(f"del-hilo-{i}") for i in range(5)],
                daemon=True)
            hilo.start()
            hilo.join(10)
            await pilot.pause()
            await pilot.pause()
            esperando.set()
            app.exit()

        app.run(headless=True, auto_pilot=piloto)
        self.assertTrue(esperando.is_set(), "la vista no llego a correr")
        tragadas = "".join(app.lineas_tragadas)
        self.assertEqual([l for l in tragadas.splitlines() if l.strip()],
                         [f"del-hilo-{i}" for i in range(5)],
                         f"la vista recogio {tragadas!r}")
        salida = self._volcar(app)
        for i in range(5):
            self.assertEqual(salida.count(f"del-hilo-{i}"), 1)
        self.assertIn("que la vista habia tragado", salida)


# ---------------------------------------------------------------------------
# 4. Lo tecleado durante la corrida se encola y se ejecuta DESPUES
# ---------------------------------------------------------------------------
class TestColaDeEntrada(_BaseCarril):

    def test_se_encolan_en_orden_y_no_se_ejecutan_durante_la_corrida(self):
        sonda = _Sonda()

        def fn():
            for linea in ("/modelos", "hola que tal", "/salir-no"):
                self.assertTrue(self.esperar_prompt(), "el prompt no volvio a abrir")
                pipe.send_text(linea + "\r")
                # se espera a VER el acuse: es la prueba de que el principal
                # la proceso y no la ejecuto.
                t0 = time.perf_counter()
                while (linea not in cli._COLA_ENTRADA
                       and time.perf_counter() - t0 < 10):
                    time.sleep(0.005)
            sonda()

        with self.carril() as pipe:
            cli._lanzar_en_fondo("workflow", fn)

        self.assertEqual(cli._COLA_ENTRADA,
                         ["/modelos", "hola que tal", "/salir-no"],
                         "la cola perdio el orden o perdio lineas")
        pantalla = self.visto()
        self.assertIn("anotado (1 en cola)", pantalla)
        self.assertIn("anotado (3 en cola)", pantalla)
        self.assertIn("se ejecuta cuando termine workflow", pantalla)
        self.assertEqual(sonda.veces, 1)

    def test_la_linea_vacia_no_se_encola(self):
        def fn():
            self.assertTrue(self.esperar_prompt())
            pipe.send_text("   \r")
            time.sleep(0.15)

        with self.carril() as pipe:
            cli._lanzar_en_fondo("hacer", fn)
        self.assertEqual(cli._COLA_ENTRADA, [],
                         "un Enter a secas encolo un turno fantasma")

    def test_el_repl_drena_ESA_cola_y_por_el_frente(self):
        """El 'se ejecuta DESPUES' lo cierra el REPL: _get_input devuelve lo
        encolado antes de pedir teclado, y saca por el FRENTE (FIFO).

        Se comprueba sobre el codigo de repl() porque la funcion tiene 1.500
        lineas y no hay forma de instanciar su closure: lo que se defiende es
        que nadie vuelva a poner `_inyectadas: list = []` (una lista NUEVA),
        que es como estaba antes del carril — el carril encolaria en
        _COLA_ENTRADA y el REPL leeria de otra lista, y las lineas tecleadas
        durante la corrida se perderian en silencio."""
        fuente = Path(cli.__file__).read_text(encoding="utf-8")
        cuerpo = fuente[fuente.index("def repl():"):]
        self.assertIn("_inyectadas: list = _COLA_ENTRADA", cuerpo,
                      "el REPL ya no drena la cola del carril de fondo")
        self.assertIn("_inyectadas.pop(0)", cuerpo,
                      "la cola dejo de ser FIFO")
        self.assertIn("_COLA_ENTRADA.clear()", cuerpo,
                      "un repl() reentrante heredaria lineas viejas")


# ---------------------------------------------------------------------------
# 5. Ctrl-C
# ---------------------------------------------------------------------------
class TestCtrlC(_BaseCarril):

    def test_con_corrida_viva_corta_la_corrida_y_el_repl_sigue(self):
        """E2E por el pipe: "\\x03" es el Ctrl-C que prompt_toolkit entrega
        como KeyboardInterrupt desde prompt(). Medido: la corrida quedo
        cancelada en 11,3 ms y el bucle de espera siguio vivo."""
        visto = {}

        def fn():
            self.assertTrue(self.esperar_prompt())
            pipe.send_text("\x03")
            t0 = time.perf_counter()
            while time.perf_counter() - t0 < 10:
                if cli._corte_pedido():
                    visto["ms"] = (time.perf_counter() - t0) * 1000
                    break
                time.sleep(0.005)
            # el REPL sigue esperando: el prompt vuelve a abrir y acepta texto
            self.assertTrue(self.esperar_prompt())
            pipe.send_text("sigo-vivo\r")
            t0 = time.perf_counter()
            while ("sigo-vivo" not in cli._COLA_ENTRADA
                   and time.perf_counter() - t0 < 10):
                time.sleep(0.005)

        with self.carril() as pipe:
            self.assertTrue(cli._lanzar_en_fondo("workflow", fn))

        self.assertIn("ms", visto, "Ctrl-C no llego a cancelar la corrida")
        self.assertLess(visto["ms"], 5000, f"tardo {visto['ms']:.1f} ms")
        self.assertEqual(cli._COLA_ENTRADA, ["sigo-vivo"],
                         "el REPL murio con el Ctrl-C en vez de seguir")
        pantalla = self.visto()
        self.assertIn("corte pedido", pantalla)
        self.assertIn("El REPL sigue vivo", pantalla)
        self.assertIsNone(cli._CORRIDA)

    def test_sin_corrida_el_ctrlc_solo_cancela_la_linea(self):
        """En el prompt IDLE el Ctrl-C sale como KeyboardInterrupt de prompt()
        (la linea se descarta) y el REPL decide con _ctrlc_seguidos_idle: el
        PRIMERO no sale."""
        with self.carril() as pipe:
            pipe.send_text("a medio escribir\x03")
            with self.assertRaises(KeyboardInterrupt):
                cli._sesion_prompt.prompt("> ")
        self.assertFalse(cli._ctrlc_seguidos_idle(),
                         "el primer Ctrl-C del idle no puede matar la sesion")

    def test_dos_ctrlc_seguidos_salen_y_uno_solo_no(self):
        """UNIDAD (el e2e del bucle principal no es viable en pytest: exige
        repl() entero con una consola de verdad). El primero siempre False;
        el segundo dentro de _VENTANA_CTRLC_S, True; pasada la ventana, no."""
        self.assertFalse(cli._ctrlc_seguidos_idle())
        self.assertTrue(cli._ctrlc_seguidos_idle(),
                        "dos Ctrl-C seguidos tienen que salir")
        cli._ULTIMO_CTRLC[0] = time.monotonic() - cli._VENTANA_CTRLC_S - 0.01
        self.assertFalse(cli._ctrlc_seguidos_idle(),
                         "fuera de la ventana vuelve a ser 'cancela la linea'")
        self.assertGreater(cli._VENTANA_CTRLC_S, 0.5)

    def test_el_bucle_del_repl_no_sale_al_primer_ctrlc(self):
        """El otro extremo de la unidad de arriba: que el bucle principal la
        USE. Hasta 2026-08-18 era `except (EOFError, KeyboardInterrupt): break`
        y un solo Ctrl-C mataba la sesion con corridas vivas."""
        fuente = Path(cli.__file__).read_text(encoding="utf-8")
        cuerpo = fuente[fuente.index("def repl():"):]
        m = re.search(r"\n        except KeyboardInterrupt:\n((?:.*\n)+?)\n",
                      cuerpo)
        self.assertIsNotNone(m, "el bucle del REPL ya no atrapa KeyboardInterrupt")
        bloque = m.group(1)
        self.assertIn("_ctrlc_seguidos_idle()", bloque)
        self.assertIn("linea cancelada", bloque)
        # El regreso del bug seria juntar otra vez las dos salidas en un solo
        # except que rompe el bucle. Los `except (EOFError, KeyboardInterrupt)`
        # que quedan en repl() son confirmaciones locales que responden "n";
        # ninguno puede terminar en `break`.
        for m2 in re.finditer(
                r"except \(EOFError, KeyboardInterrupt\):\n(.*)\n", cuerpo):
            self.assertNotIn("break", m2.group(1),
                             "volvio el 'un Ctrl-C mata el REPL'")

    def test_cancelar_sin_corrida_no_revienta(self):
        self.assertEqual(cli._cancelar_corrida(None), "no hay corrida que cortar")
        self.assertFalse(cli._corte_pedido())


# ---------------------------------------------------------------------------
# 6. F2 sin corrida
# ---------------------------------------------------------------------------
class TestF2SinCorrida(_BaseCarril):

    def setUp(self):
        if not _HAY_VISTA:
            self.fail(f"cognia.tui.agentes no importa: {_MOTIVO_VISTA}")
        super().setUp()
        self._run_real = _agentes.PantallaAgentes.run
        self.abiertas: list = []

    def tearDown(self):
        _agentes.PantallaAgentes.run = self._run_real
        super().tearDown()

    def _parchear_run_headless(self):
        """La App real, pero en headless y cerrandose sola.

        Se parchea run() en la clase BASE (y no se subclasea aca) a proposito:
        _vista_con_corte resuelve CSS_PATH contra el fichero del modulo de la
        base, asi que una base definida en tests/ buscaria tests/agentes.tcss."""
        real, abiertas = self._run_real, self.abiertas

        def _run(self, *a, **kw):
            abiertas.append(self)

            async def piloto(pilot):
                await pilot.pause()
                self.visto_vacio = self.query_one("#vacio").display
                self.visto_pie = [(b.key, b.description)
                                  for b in self._bindings.shown_keys]
                self.exit()

            kw.pop("headless", None)
            kw.pop("auto_pilot", None)
            return real(self, headless=True, auto_pilot=piloto, **kw)

        _agentes.PantallaAgentes.run = _run

    def test_f2_sin_corrida_abre_la_vista_y_vuelve_limpio(self):
        self._parchear_run_headless()
        _stdout = sys.stdout
        sys.stdout = self.pantalla
        try:
            cli._abrir_vista_agentes()          # no puede lanzar NADA
        finally:
            sys.stdout = _stdout
        self.assertEqual(len(self.abiertas), 1, "no se abrio la vista")
        app = self.abiertas[0]
        self.assertIsInstance(app, _agentes.PantallaAgentes)
        self.assertTrue(app.visto_vacio,
                        "sin corrida tiene que verse el estado vacio")
        self.assertIsNone(cli._VISTA["app"], "la vista quedo registrada al salir")
        self.assertEqual(app.lineas_tragadas, [])
        self.assertNotIn("no esta disponible", self.visto())

    def test_f2_registra_la_vista_mientras_esta_abierta(self):
        """_VISTA['app'] es lo que hace que un permiso pedido desde el hilo
        vaya al MODAL en vez de a la consola: si no se registra, el enrutado
        del permiso se cae al camino lento."""
        real, visto = self._run_real, {}

        def _run(self, *a, **kw):
            async def piloto(pilot):
                await pilot.pause()
                visto["registrada"] = cli._VISTA.get("app") is self
                self.exit()
            return real(self, headless=True, auto_pilot=piloto)

        _agentes.PantallaAgentes.run = _run
        cli._abrir_vista_agentes()
        self.assertIs(visto.get("registrada"), True)
        self.assertIsNone(cli._VISTA["app"])

    def test_si_la_vista_no_existe_degrada_con_aviso(self):
        """La vista la construye otra tanda: F2 tiene que avisar, no reventar
        el REPL con un traceback."""
        import builtins
        real_import = builtins.__import__

        def _import(nombre, *a, **kw):
            if nombre == "cognia.tui.agentes":
                raise ImportError("simulado: la vista no esta")
            return real_import(nombre, *a, **kw)

        _stdout = sys.stdout
        sys.stdout = self.pantalla
        builtins.__import__ = _import
        try:
            cli._abrir_vista_agentes()
        finally:
            builtins.__import__ = real_import
            sys.stdout = _stdout
        pantalla = self.visto()
        self.assertIn("La vista de agentes no esta disponible", pantalla)
        self.assertIn("La corrida sigue", pantalla)
        self.assertIsNone(cli._VISTA["app"])


# ---------------------------------------------------------------------------
# 7. El sink (mundo pipe / mundo consola)
# ---------------------------------------------------------------------------
class TestSinkYaCubierto(unittest.TestCase):
    """NO se duplica: vive en tests/test_events_sink_tui.py. Este test solo
    impide que esa cobertura desaparezca sin que nadie se entere."""

    def test_los_tests_del_sink_siguen_existiendo(self):
        fuente = (Path(__file__).with_name("test_events_sink_tui.py")
                  .read_text(encoding="utf-8"))
        for nombre in ("def test_mundo_pipe_el_movil_ve_los_eventos",
                       "def test_mundo_consola_el_evento_no_pisa_la_pantalla",
                       "def test_la_vista_del_repl_recoge_los_eventos_"
                       "del_mundo_consola"):
            self.assertIn(nombre, fuente, f"falta {nombre}")
        self.assertIn("_vista_con_corte", fuente,
                      "el test del mundo consola dejo de usar la vista del REPL")


# ---------------------------------------------------------------------------
# 8. EL HUECO DEL CTRL-C: el que no se puede medir en el ConPTY
# ---------------------------------------------------------------------------
class TestElHuecoDelCtrlC(_BaseCarril):
    """El unico Ctrl-C que este repo NO pudo tocar con la tecla de verdad.

    Por que no se puede medir: el ConPTY del spike no entrega CTRL_C_EVENT en
    modo cocido, asi que el unico Ctrl-C observable es el que prompt_toolkit
    lee como TECLA dentro de prompt() (ese es el del test de arriba). El otro
    — el CTRL_C_EVENT de conhost, que CPython convierte en un
    KeyboardInterrupt lanzado en el hilo principal en CUALQUIER limite de
    bytecode — se razona y se reproduce inyectandolo donde caeria.

    Por que importa: el bucle principal del REPL NO atrapa KeyboardInterrupt
    en el dispatch (su except envuelve solo _get_input, cli.py ~7717), asi que
    una excepcion que se escape de _lanzar_en_fondo MATA EL REPL dejando el
    hilo daemon vivo. Reproducido antes del fix: ESCAPO KeyboardInterrupt.
    """

    def _correr_con_interrupcion(self, donde: str):
        """Mete un KeyboardInterrupt en un punto que corre DENTRO de
        _esperar_corrida pero FUERA del prompt (que es todo el hueco)."""
        libre = threading.Event()
        real = getattr(cli, donde)

        def _bomba(*a, **kw):
            raise KeyboardInterrupt()

        def fn():
            self.assertTrue(self.esperar_prompt())
            cli._despertar_prompt(cli._FONDO_F2)   # el prompt sale del bloqueo
            libre.wait(10)
            time.sleep(0.05)

        setattr(cli, donde, _bomba)
        escapo = None
        try:
            with self.carril():
                try:
                    cli._lanzar_en_fondo("workflow", fn)
                except BaseException as exc:       # noqa: BLE001
                    escapo = type(exc).__name__
                finally:
                    libre.set()
        finally:
            setattr(cli, donde, real)
        return escapo

    def test_un_ctrlc_fuera_del_prompt_no_se_escapa_ni_mata_el_repl(self):
        escapo = self._correr_con_interrupcion("_abrir_vista_agentes")
        self.assertIsNone(escapo,
                          f"el KeyboardInterrupt salio de _lanzar_en_fondo "
                          f"({escapo}): el REPL se muere con la corrida viva")
        # Y no se lo traga en silencio: se pide el corte, que es lo que el
        # usuario queria al apretar Ctrl-C.
        self.assertIn("corte pedido", self.visto())
        self.assertIsNone(cli._CORRIDA, "el estado global quedo sucio")

    def test_el_bucle_de_espera_reintenta_hasta_que_el_hilo_cierra(self):
        """Tras el corte NO se abandona: se vuelve a esperar. Abandonar
        dejaria el hilo daemon imprimiendo sobre el prompt del REPL."""
        estado = {}
        libre = threading.Event()
        real = cli._abrir_vista_agentes
        veces = {"n": 0}

        def _bomba():
            veces["n"] += 1
            raise KeyboardInterrupt()

        def fn():
            self.assertTrue(self.esperar_prompt())
            cli._despertar_prompt(cli._FONDO_F2)
            # el prompt tiene que VOLVER a abrir despues del interrupt
            estado["reabrio"] = self.esperar_prompt()
            libre.set()

        cli._abrir_vista_agentes = _bomba
        try:
            with self.carril():
                cli._lanzar_en_fondo("workflow", fn)
                libre.wait(10)
        finally:
            cli._abrir_vista_agentes = real
        self.assertEqual(veces["n"], 1)
        self.assertIs(estado.get("reabrio"), True,
                      "el prompt de espera no volvio tras el Ctrl-C del hueco")

    def test_el_fix_esta_en_el_sitio_y_explicado(self):
        """La proteccion es un bucle con el `if c.fin.is_set()` DENTRO del try:
        asi el unico bytecode desprotegido es el salto del while. Si alguien lo
        'simplifica' a `while not c.fin.is_set():` el hueco vuelve a abrirse en
        la comprobacion."""
        fuente = Path(cli.__file__).read_text(encoding="utf-8")
        cuerpo = fuente[fuente.index("def _lanzar_en_fondo("):
                        fuente.index("def _esperar_corrida(")]
        self.assertIn("EL HUECO DEL CTRL-C", cuerpo, "se borro el porque")
        self.assertIn("while True:", cuerpo)
        self.assertIn("if c.fin.is_set():", cuerpo)
        self.assertIn("except KeyboardInterrupt:", cuerpo)
        self.assertIn("_cancelar_corrida(c)", cuerpo)


# ---------------------------------------------------------------------------
# El pie y la barra NO PUEDEN MENTIR
# ---------------------------------------------------------------------------
class TestAtajosQueNoMienten(unittest.TestCase):

    def setUp(self):
        if not _HAY_VISTA:
            self.fail(f"cognia.tui.agentes no importa: {_MOTIVO_VISTA}")

    def _bindings(self):
        app = cli._vista_con_corte(_agentes.PantallaAgentes)()
        return app._bindings

    def test_el_pie_de_la_vista_anuncia_ctrl_c(self):
        """^c es la tecla que SI corta la corrida (el prompt de espera la
        nombra) y el pie de la vista no la mencionaba."""
        bs = self._bindings().key_to_bindings.get("ctrl+c") or []
        self.assertEqual([b.action for b in bs], ["cortar_corrida"])
        self.assertTrue(bs[0].show, "^c no sale en el pie")
        self.assertIn("corrida", bs[0].description.lower())
        self.assertNotIn("prox", bs[0].description.lower())

    def test_el_pie_ya_no_promete_un_ctrl_x_que_no_hace_nada(self):
        """La base declara ctrl+x -> pendiente('...') con la etiqueta
        'Cancelar corrida (prox.)': el pie prometia cortar y no cortaba."""
        bs = self._bindings().key_to_bindings.get("ctrl+x") or []
        self.assertTrue(bs, "desaparecio ctrl+x de la vista del REPL")
        for b in bs:
            self.assertNotIn("pendiente", str(b.action),
                             "^x sigue siendo el placeholder en la vista del REPL")
        mostrados = " ".join(b.description.lower()
                             for b in self._bindings().shown_keys)
        self.assertNotIn("cancelar corrida (prox.)", mostrados,
                         "el pie sigue anunciando un corte que no ocurre")

    def test_no_se_pisa_el_ctrl_x_cuando_la_otra_tanda_lo_cablee(self):
        """Coordinacion: en cuanto cognia/tui/agentes.py cablee ctrl+x de
        verdad, la subclase del REPL tiene que APARTARSE (si no, le pisaria su
        binding para siempre)."""
        from textual.app import App
        from textual.binding import Binding

        class _BaseCableada(App):
            BINDINGS = [Binding("ctrl+x", "cancelar_de_verdad",
                                "Cancelar corrida")]

        clase = cli._vista_con_corte(_BaseCableada)
        claves = [getattr(b, "key", None) for b in clase.BINDINGS]
        self.assertNotIn("ctrl+x", claves,
                         "la subclase pisaria el ctrl+x real de la otra tanda")
        self.assertIn("ctrl+c", claves)

    def test_el_rotulo_de_ctrl_c_se_separa_del_ctrl_x_ya_cableado(self):
        """El cartel tambien se coordina, no solo la tecla.

        Con ctrl+x cableado (lo esta desde el 2026-08-18 03:11) las dos teclas
        cortan, pero NO igual: ^x va por el motor contra la corrida PINTADA y
        pregunta antes; ^c corta la del REPL y corta ya. Rotularlas igual es
        volver a mentir en el pie, con otro disfraz."""
        from textual.app import App
        from textual.binding import Binding

        class _BaseCableada(App):
            BINDINGS = [Binding("ctrl+x", "cancelar_corrida",
                                "Cancelar corrida")]

        class _BasePlaceholder(App):
            BINDINGS = [Binding("ctrl+x", "pendiente('ctrl+x: cancelar')",
                                "Cancelar corrida (prox.)")]

        def _rotulo(base, tecla):
            for b in cli._vista_con_corte(base).BINDINGS:
                if getattr(b, "key", None) == tecla:
                    return b.description
            return None

        self.assertNotEqual(_rotulo(_BaseCableada, "ctrl+c").lower(),
                            "cancelar corrida",
                            "^c y ^x quedarian con el MISMO cartel en el pie")
        self.assertIn("corrida", _rotulo(_BaseCableada, "ctrl+c").lower())
        # Y al reves: si la otra tanda revierte a placeholder, ^c vuelve a ser
        # el unico que corta y se queda con el cartel de siempre.
        self.assertEqual(_rotulo(_BasePlaceholder, "ctrl+c"), "Cancelar corrida")
        self.assertEqual(_rotulo(_BasePlaceholder, "ctrl+x"), "Cancelar corrida")

    def test_el_pie_QUE_SE_PINTA_nombra_ctrl_c_y_la_tecla_corta(self):
        """El test de verdad: no las BINDINGS de la clase sino lo que Textual
        PINTA, con la App corriendo.

        Cazado aqui (2026-08-18): con las BINDINGS bien puestas el pie SEGUIA
        sin nombrar ^c. La Screen por defecto de textual 8.2.8 trae su propio
        ctrl+c -> screen.copy_text y en Screen.active_bindings — el mapa del
        que come el Footer — gana el primero de la cadena salvo prioridad. La
        tecla cortaba y el pie callaba: media mentira sigue siendo mentira."""
        clase = cli._vista_con_corte(_agentes.PantallaAgentes)
        app = clase()
        c = cli._Corrida("workflow")
        visto: dict = {}

        async def piloto(pilot):
            await pilot.pause()
            visto["pie"] = [(k, b.binding.description)
                            for k, b in app.screen.active_bindings.items()
                            if b.binding.show]
            await pilot.press("ctrl+c")
            await pilot.pause()
            await pilot.pause()
            visto["corta"] = c.cancelada
            app.exit()

        guardada = cli._CORRIDA
        cli._CORRIDA = c
        try:
            app.run(headless=True, auto_pilot=piloto, size=(110, 24))
        finally:
            cli._CORRIDA = guardada
        pie = dict(visto.get("pie") or [])
        self.assertIn("ctrl+c", pie, f"el pie no nombra ^c: {visto.get('pie')}")
        self.assertIn("corrida", pie["ctrl+c"].lower())
        mostrado = " ".join(pie.values()).lower()
        self.assertNotIn("cancelar corrida (prox.)", mostrado,
                         "el pie sigue prometiendo un corte que no ocurre")
        self.assertIs(visto.get("corta"), True,
                      "^c no corto la corrida desde la vista")
        # DOS teclas con el MISMO cartel es la misma mentira por otra puerta:
        # el ^x de la otra tanda corta por el motor la corrida PINTADA y
        # PREGUNTA antes; el ^c de aca corta la del REPL y corta YA. Si los
        # dos dicen lo mismo, el usuario no puede elegir.
        etiquetas = [d.lower() for d in pie.values()]
        self.assertEqual(len(etiquetas), len(set(etiquetas)),
                         f"dos teclas del pie con el mismo cartel: {pie}")

    def test_ctrl_x_y_ctrl_c_cortan_la_corrida_de_verdad(self):
        """No basta con que el pie lo diga: la accion tiene que cortar."""
        clase = cli._vista_con_corte(_agentes.PantallaAgentes)
        app = clase()
        c = cli._Corrida("workflow")
        guardada = cli._CORRIDA
        cli._CORRIDA = c
        try:
            app.action_cortar_corrida()     # notify() sin App viva: se traga
        finally:
            cli._CORRIDA = guardada
        self.assertTrue(c.cancelada, "^c/^x no cortaron la corrida")

    def test_la_barra_del_prompt_nombra_f2(self):
        """Hasta hoy la UNICA forma de descubrir F2 era lanzar una corrida:
        el marco del prompt de espera lo nombra y la barra del prompt idle no."""
        repl = B.barra_atajos("repl", unicode_ok=True)
        self.assertIn("f2 agentes", repl)
        self.assertTrue(repl.startswith("tab completa"),
                        "F2 no puede desplazar a los atajos de siempre")
        for otro in ("permiso", "selector", "generando"):
            self.assertNotIn("f2", B.barra_atajos(otro, unicode_ok=True),
                             f"F2 no hace nada en el contexto {otro}")

    def test_f2_se_cae_el_primero_cuando_la_terminal_es_angosta(self):
        corta = B.barra_atajos("repl", ancho=40, unicode_ok=False)
        self.assertLessEqual(len(corta), 40)
        self.assertNotIn("f2", corta)
        self.assertTrue(corta.startswith("tab completa"))


if __name__ == "__main__":                                  # pragma: no cover
    unittest.main(verbosity=2)
