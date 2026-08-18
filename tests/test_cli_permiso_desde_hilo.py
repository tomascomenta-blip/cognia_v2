"""
tests/test_cli_permiso_desde_hilo.py
====================================
El PERMISO pedido DESDE EL HILO de la corrida (carril de fondo del REPL).

Por que este fichero existe: desde 2026-08-18 /hacer y /workflow corren en un
hilo daemon (cli._lanzar_en_fondo) y el gate de permisos (_confirmar_accion,
que es el ctx['confirm'] del agente) es un input() BLOQUEANTE. Un hilo NO puede
preguntar: esta medido que abrir una Application de prompt_toolkit desde un
hilo no vuelve NUNCA (ni con la vista de Textual abierta ni con solo el prompt
del REPL). Por eso _preguntar_desde_hilo delega en el dueno de la consola. Es
el camino de mayor riesgo del diseno y no tenia ni un test: un fallo aca es un
hilo colgado 600 s, mudo, sosteniendo una tool a medias.

Se ejercitan los cuatro momentos, con el carril de fondo REAL (PromptSession de
prompt_toolkit sobre un pipe, dentro de un app_session con DummyOutput) y la
vista REAL de Textual headless. Lo unico simulado es el teclado (el pipe) y la
respuesta final del humano (input(), que es el fallback textual documentado de
_preguntar_en_consola).

Numeros MEDIDOS en esta maquina el 2026-08-18 (Windows 11, venv312):
  (a) vista cerrada, prompt de espera abierto .... 1,1 ms hasta la respuesta
  (b) vista abierta ............................. modal a los 10,3 ms, 10,8 ms
  (c) la vista se cierra con el modal arriba .... rescatado por el prompt, 270 ms
  (c') ni prompt ni vista (el principal ocupado)  4.181,7 ms (2 pasadas de
       _despertar_prompt a 2 s cada una) y despues DENY si hay tty
  (d) nadie contesta ............................ DENY al vencer _ESPERA_PERMISO_S

REGRESION (bug real cazado por estos tests, arreglado el 2026-08-18): si el
centinela _FONDO_PERMISO se PIERDE (el usuario aprieta Enter o F2 en el mismo
instante en que el hilo llama a app.exit: 'Return value already set' y el
prompt devuelve la linea tecleada), el pedido quedaba HUERFANO — el hilo
esperaba el tope entero (600 s) con el dueno de la consola sentado en el prompt
de espera, y terminaba denegando. Medido con el tope bajado a 3 s: 3.021,9 ms y
0 preguntas en consola. Con el fix (_esperar_corrida comprueba c.pedido en cada
ciclo, no solo cuando llega el centinela): 7,7 ms y 1 pregunta.
"""
from __future__ import annotations

import builtins
import contextlib
import os
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prompt_toolkit import PromptSession                       # noqa: E402
from prompt_toolkit.application import create_app_session      # noqa: E402
from prompt_toolkit.input import create_pipe_input             # noqa: E402
from prompt_toolkit.output import DummyOutput                  # noqa: E402

import cognia.cli as cli                                       # noqa: E402
import cognia.console.permissions as perms                     # noqa: E402
import cognia.ux.selector as selector                          # noqa: E402


# ---------------------------------------------------------------------------
# Andamio
# ---------------------------------------------------------------------------
class _BaseCarril(unittest.TestCase):
    """Deja el modulo cli como estaba: son TODO globales de modulo."""

    def setUp(self):
        self._env = os.environ.get("COGNIA_SIN_FONDO")
        os.environ.pop("COGNIA_SIN_FONDO", None)
        self._guardado = {
            "_sesion_prompt": cli._sesion_prompt,
            "_CORRIDA": cli._CORRIDA,
            "_vista": cli._VISTA.get("app"),
            "_espera": cli._ESPERA_PERMISO_S,
            "needs": perms.needs_confirmation,
            "tty": selector.hay_tty,
            "input": builtins.input,
        }
        cli._COLA_ENTRADA.clear()
        cli._AVISOS_VISTOS.clear()
        # El gate SIEMPRE pregunta; la consola nunca abre prompt_toolkit (el
        # selector con flechas exige tty real, aca contesta el input()).
        perms.needs_confirmation = lambda kind, detalle: True
        selector.hay_tty = lambda: False
        self.consola = {"veces": 0, "valor": "s", "boom": None, "espera": 0.0,
                        "prompts": []}
        builtins.input = self._input_falso

    def tearDown(self):
        cli._sesion_prompt = self._guardado["_sesion_prompt"]
        cli._CORRIDA = self._guardado["_CORRIDA"]
        cli._VISTA["app"] = self._guardado["_vista"]
        cli._ESPERA_PERMISO_S = self._guardado["_espera"]
        perms.needs_confirmation = self._guardado["needs"]
        selector.hay_tty = self._guardado["tty"]
        builtins.input = self._guardado["input"]
        cli._COLA_ENTRADA.clear()
        cli._AVISOS_VISTOS.clear()
        if self._env is not None:
            os.environ["COGNIA_SIN_FONDO"] = self._env

    def _input_falso(self, prompt=""):
        self.consola["veces"] += 1
        self.consola["prompts"].append(prompt)
        if self.consola["boom"] is not None:
            exc = self.consola["boom"]
            self.consola["boom"] = None
            raise exc
        if self.consola["espera"]:
            time.sleep(self.consola["espera"])
        return self.consola["valor"]

    @contextlib.contextmanager
    def carril(self):
        """Un carril de fondo de verdad: PromptSession sobre un pipe."""
        with create_pipe_input() as pipe:
            with create_app_session(input=pipe, output=DummyOutput()):
                cli._sesion_prompt = PromptSession()
                try:
                    yield pipe
                finally:
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


# ---------------------------------------------------------------------------
# (a) vista CERRADA, el usuario en el prompt de espera
# ---------------------------------------------------------------------------
class TestPermisoConVistaCerrada(_BaseCarril):

    def _correr(self, respuesta: str):
        res = {}

        def tarea():
            self.assertTrue(self.esperar_prompt(), "el prompt no abrio")
            t0 = time.perf_counter()
            res["ok"] = cli._confirmar_accion("shell_exec", "rm -rf C:/tmp/nada")
            res["ms"] = (time.perf_counter() - t0) * 1000

        with self.carril():
            self.consola["valor"] = respuesta
            self.assertTrue(cli._lanzar_en_fondo("hacer", tarea))
        return res

    def test_el_hilo_recibe_el_si_del_dueno_de_la_consola(self):
        res = self._correr("s")
        self.assertIs(res.get("ok"), True)
        self.assertEqual(self.consola["veces"], 1,
                         "la consola tiene que preguntar exactamente una vez")
        self.assertIn("[permiso]", self.consola["prompts"][0],
                      "el texto '[permiso] ... (s/n) >' es contrato con los pipes")
        self.assertLess(res["ms"], 5000, f"tardo {res['ms']:.1f} ms")

    def test_el_no_tambien_viaja_al_hilo(self):
        res = self._correr("n")
        self.assertIs(res.get("ok"), False)
        self.assertEqual(self.consola["veces"], 1)

    def test_el_hilo_no_pregunta_por_su_cuenta(self):
        """Si el hilo abriera el selector NO VOLVERIA (medido). El unico que
        puede llamar a _preguntar_en_consola es el hilo principal."""
        vistos = []
        real = cli._preguntar_en_consola

        def espia(kind, detalle):
            vistos.append(threading.current_thread() is threading.main_thread())
            return real(kind, detalle)

        cli._preguntar_en_consola = espia
        try:
            self._correr("s")
        finally:
            cli._preguntar_en_consola = real
        self.assertEqual(vistos, [True],
                         "el permiso se contesto fuera del hilo principal")

    def test_la_linea_a_medias_sobrevive_al_permiso(self):
        """El centinela ARRASTRA el buffer: app.exit() lo descarta y volveria
        a aparecer vacio. Se teclea 'medi', llega el permiso, y al terminar la
        linea sigue ahi para completarla."""
        def tarea():
            self.assertTrue(self.esperar_prompt())
            pipe.send_text("medi")
            time.sleep(0.05)
            cli._confirmar_accion("shell_exec", "rm -rf C:/tmp/nada")
            self.assertTrue(self.esperar_prompt())
            pipe.send_text("tando\r")
            time.sleep(0.15)

        with self.carril() as pipe:
            cli._lanzar_en_fondo("hacer", tarea)
        self.assertEqual(cli._COLA_ENTRADA, ["meditando"],
                         "el prompt perdio lo que el usuario tenia escrito")


# ---------------------------------------------------------------------------
# (b) y (c) con la VISTA de Textual
# ---------------------------------------------------------------------------
try:
    from textual.app import App as _TxApp, ComposeResult
    from textual.widgets import Static
    from cognia.tui.permiso import PantallaPermiso
    _HAY_TEXTUAL = True
except Exception as _exc_tx:                              # pragma: no cover
    _HAY_TEXTUAL = False
    _MOTIVO_TX = f"{type(_exc_tx).__name__}: {_exc_tx}"


if _HAY_TEXTUAL:
    class _VistaMinima(_TxApp):
        """Lo minimo que _permiso_en_vista necesita: una App viva.

        NO se usa cognia/tui/agentes.py a proposito: la vista real la construye
        otra tanda y este test defiende el ENRUTADO del permiso, que no depende
        de que widgets tenga la pantalla."""
        def compose(self) -> ComposeResult:
            yield Static("vista")


class TestPermisoConLaVista(_BaseCarril):

    def setUp(self):
        if not _HAY_TEXTUAL:
            self.fail(f"textual/PantallaPermiso no importan: {_MOTIVO_TX}")
        super().setUp()
        self.app = None
        self.hilo_app = None

    def tearDown(self):
        self._cerrar_vista()
        super().tearDown()

    def _abrir_vista(self):
        self.app = _VistaMinima()
        self.hilo_app = threading.Thread(
            target=lambda: self.app.run(headless=True), daemon=True)
        self.hilo_app.start()
        t0 = time.perf_counter()
        while not getattr(self.app, "is_running", False):
            if time.perf_counter() - t0 > 20:
                self.fail("la vista de Textual no arranco")
            time.sleep(0.01)
        cli._VISTA["app"] = self.app
        return self.app

    def _cerrar_vista(self):
        if self.app is not None:
            with contextlib.suppress(Exception):
                self.app.call_from_thread(self.app.exit)
            if self.hilo_app is not None:
                self.hilo_app.join(10)
            self.app = None
        cli._VISTA["app"] = None

    def _esperar_modal(self, timeout=15.0):
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < timeout:
            if isinstance(getattr(self.app, "screen", None), PantallaPermiso):
                return (time.perf_counter() - t0) * 1000
            time.sleep(0.01)
        return None

    def test_b_con_la_vista_abierta_pregunta_el_modal_no_la_consola(self):
        app = self._abrir_vista()
        c = cli._Corrida("hacer")
        cli._CORRIDA = c
        res = {}

        def tarea():
            t0 = time.perf_counter()
            res["ok"] = cli._confirmar_accion("shell_exec", "rm -rf C:/tmp/nada")
            res["ms"] = (time.perf_counter() - t0) * 1000

        w = threading.Thread(target=tarea, daemon=True)
        w.start()
        try:
            ms = self._esperar_modal()
            self.assertIsNotNone(ms, "el modal de permiso nunca aparecio")
            # lo mismo que hace la tecla 's' del binding de PantallaPermiso
            app.call_from_thread(app.screen.action_responder, True)
            w.join(20)
        finally:
            c.fin.set()
            cli._CORRIDA = None
        self.assertFalse(w.is_alive(), "el hilo quedo colgado en el modal")
        self.assertIs(res.get("ok"), True)
        self.assertEqual(self.consola["veces"], 0,
                         "con la vista abierta la consola NO se toca")
        self.assertLess(res["ms"], 5000, f"tardo {res['ms']:.1f} ms")

    def test_c_cerrar_la_vista_no_pierde_el_permiso(self):
        """El modal muere con la App y el callback no llega nunca. El pedido
        tiene que RESCATARSE por el prompt de espera, no colgarse 600 s."""
        cli._ESPERA_PERMISO_S = 20.0
        res = {}

        def tarea():
            t0 = time.perf_counter()
            res["ok"] = cli._confirmar_accion("shell_exec", "rm -rf C:/tmp/nada")
            res["ms"] = (time.perf_counter() - t0) * 1000

        def cerrar_cuando_haya_modal():
            self._esperar_modal()
            self._cerrar_vista()

        with self.carril():
            self._abrir_vista()
            threading.Thread(target=cerrar_cuando_haya_modal,
                             daemon=True).start()
            cli._lanzar_en_fondo("hacer", tarea)
        self.assertIs(res.get("ok"), True,
                      "el permiso se perdio al cerrar la vista")
        self.assertEqual(self.consola["veces"], 1,
                         "tenia que rescatarlo el prompt de espera")
        self.assertLess(res["ms"], 15000, f"tardo {res['ms']:.1f} ms")


# ---------------------------------------------------------------------------
# (d) nadie contesta
# ---------------------------------------------------------------------------
class TestPermisoSinRespuesta(_BaseCarril):

    def test_al_vencer_el_tope_se_deniega_con_aviso(self):
        cli._ESPERA_PERMISO_S = 1.0
        self.consola["espera"] = 4.0          # el humano no contesta
        res = {}

        def tarea():
            self.assertTrue(self.esperar_prompt())
            t0 = time.perf_counter()
            res["ok"] = cli._confirmar_accion("shell_exec", "rm -rf C:/tmp/nada")
            res["ms"] = (time.perf_counter() - t0) * 1000

        avisos = []
        real_aviso = cli._aviso_degradado
        cli._aviso_degradado = lambda via, detalle="": avisos.append(via)
        try:
            with self.carril():
                cli._lanzar_en_fondo("hacer", tarea)
        finally:
            cli._aviso_degradado = real_aviso
        self.assertIs(res.get("ok"), False, "un permiso vencido DEBE denegar")
        self.assertGreaterEqual(res["ms"], 950,
                                "no espero el tope antes de denegar")
        self.assertLess(res["ms"], 3500, f"tardo {res['ms']:.1f} ms de mas")
        self.assertIn("cli.permiso.timeout_prompt", avisos,
                      f"el timeout fue silencioso: {avisos}")

    def test_la_respuesta_tardia_no_se_traga_en_silencio(self):
        """El usuario contesta DESPUES del tope: el hilo ya denego. Decirlo,
        o el usuario cree que autorizo algo que no se hizo."""
        cli._ESPERA_PERMISO_S = 0.4
        self.consola["espera"] = 1.2
        lineas = []
        real_print = cli._print_line
        cli._print_line = lambda t, *a, **k: lineas.append(str(t))
        try:
            c = cli._Corrida("hacer")
            p = {"kind": "shell_exec", "detalle": "rm -rf x",
                 "listo": threading.Event(), "resp": False, "vencido": True}
            c.pedido = p
            cli._atender_permiso(c)
        finally:
            cli._print_line = real_print
        self.assertTrue(p["listo"].is_set())
        self.assertTrue(any("tarde" in l for l in lineas),
                        f"no se aviso de la respuesta tardia: {lineas}")


# ---------------------------------------------------------------------------
# El bug del pedido HUERFANO (regresion)
# ---------------------------------------------------------------------------
class TestPedidoHuerfano(_BaseCarril):

    def test_si_se_pierde_el_centinela_el_permiso_se_atiende_igual(self):
        """El wake se pierde (lo gana una tecla del usuario) y el prompt cicla
        por otro motivo. Sin el fix: el hilo espera _ESPERA_PERMISO_S ENTERO y
        deniega, con la consola libre. Con el fix: lo atiende en el ciclo
        siguiente."""
        cli._ESPERA_PERMISO_S = 6.0
        res = {}
        real_despertar = cli._despertar_prompt

        with self.carril() as pipe:
            def despertar_perdido(centinela, intentos=200):
                if centinela == cli._FONDO_PERMISO:
                    # el centinela se descarta; en su lugar el prompt devuelve
                    # la linea que el usuario acababa de teclear
                    pipe.send_text("otra cosa\r")
                    return True
                return real_despertar(centinela, intentos)

            def tarea():
                self.assertTrue(self.esperar_prompt())
                t0 = time.perf_counter()
                res["ok"] = cli._confirmar_accion("shell_exec", "rm -rf C:/tmp/nada")
                res["ms"] = (time.perf_counter() - t0) * 1000

            cli._despertar_prompt = despertar_perdido
            try:
                cli._lanzar_en_fondo("hacer", tarea)
            finally:
                cli._despertar_prompt = real_despertar

        self.assertIs(res.get("ok"), True,
                      "el pedido quedo huerfano hasta el timeout")
        self.assertEqual(self.consola["veces"], 1)
        self.assertLess(res["ms"], 4000,
                        f"espero {res['ms']:.1f} ms: sigue esperando el tope")
        self.assertEqual(cli._COLA_ENTRADA, ["otra cosa"],
                         "la linea tecleada tiene que quedar en la cola")

    def test_el_que_pregunta_es_el_unico_dueno_del_pedido(self):
        """_tomar_pedido y _retirar_pedido no pueden pisarse: si el principal
        ya se llevo el pedido, el hilo NO puede retirarlo (y montar un segundo
        pedido preguntaria dos veces lo mismo)."""
        c = cli._Corrida("hacer")
        p = {"kind": "shell_exec", "detalle": "x",
             "listo": threading.Event(), "resp": False}
        c.pedido = p
        self.assertIs(cli._tomar_pedido(c), p)
        self.assertIsNone(c.pedido)
        self.assertIsNone(cli._tomar_pedido(c))
        self.assertFalse(cli._retirar_pedido(c, p),
                         "retiro un pedido que ya se habia llevado el principal")
        c.pedido = p
        self.assertTrue(cli._retirar_pedido(c, p))
        self.assertIsNone(c.pedido)


# ---------------------------------------------------------------------------
# Bordes que NO pueden colgar el hilo
# ---------------------------------------------------------------------------
class TestBordesDelPermiso(_BaseCarril):

    def test_hilo_sin_carril_y_con_tty_deniega_en_vez_de_colgarse(self):
        """Sin corrida ni vista y con tty real, preguntar desde el hilo
        colgaria PARA SIEMPRE (medido). Se deniega y se avisa."""
        selector.hay_tty = lambda: True
        cli._CORRIDA = None
        cli._VISTA["app"] = None
        avisos = []
        real_aviso = cli._aviso_degradado
        cli._aviso_degradado = lambda via, detalle="": avisos.append(via)
        res = {}

        def tarea():
            t0 = time.perf_counter()
            res["ok"] = cli._confirmar_accion("shell_exec", "rm -rf C:/tmp/nada")
            res["ms"] = (time.perf_counter() - t0) * 1000

        h = threading.Thread(target=tarea, daemon=True)
        h.start()
        h.join(30)
        cli._aviso_degradado = real_aviso
        self.assertFalse(h.is_alive(), "el hilo se colgo sin carril")
        self.assertIs(res.get("ok"), False)
        self.assertEqual(self.consola["veces"], 0,
                         "abrio un input() desde el hilo con tty: eso cuelga")
        self.assertIn("cli.permiso.hilo_sin_carril", avisos)

    def test_sin_tty_el_hilo_si_puede_preguntar_solo(self):
        """En pipes/CI no hay Application que colgar: el input() desde el hilo
        es el camino de siempre y tiene que seguir funcionando."""
        cli._CORRIDA = None
        cli._VISTA["app"] = None
        res = {}
        h = threading.Thread(
            target=lambda: res.update(
                ok=cli._confirmar_accion("shell_exec", "rm -rf C:/tmp/nada")),
            daemon=True)
        h.start()
        h.join(30)
        self.assertFalse(h.is_alive())
        self.assertIs(res.get("ok"), True)
        self.assertEqual(self.consola["veces"], 1)

    def test_ctrlc_en_el_permiso_deniega_y_no_mata_el_repl(self):
        """Un Ctrl-C que caiga entre el centinela y el selector llega como
        KeyboardInterrupt. Si sube, se lleva puesto el REPL con la corrida
        viva (el except del bucle principal solo envuelve _get_input)."""
        c = cli._Corrida("hacer")
        p = {"kind": "shell_exec", "detalle": "rm -rf x",
             "listo": threading.Event(), "resp": True}
        c.pedido = p
        lineas = []
        real_print = cli._print_line
        real_preguntar = cli._preguntar_en_consola

        def _sigint(kind, detalle):
            raise KeyboardInterrupt

        cli._print_line = lambda t, *a, **k: lineas.append(str(t))
        cli._preguntar_en_consola = _sigint
        try:
            cli._atender_permiso(c)          # no debe propagar
        finally:
            cli._print_line = real_print
            cli._preguntar_en_consola = real_preguntar
        self.assertTrue(p["listo"].is_set(), "el hilo se quedaria esperando")
        self.assertIs(p["resp"], False, "Ctrl-C jamas puede significar 'ejecutar'")
        self.assertIsNone(c.pedido)
        self.assertTrue(any("Ctrl-C" in l for l in lineas), lineas)

    def test_ctrlc_tecleado_en_la_pregunta_ya_lo_traga_la_capa_de_abajo(self):
        """La otra mitad del contrato: el Ctrl-C que llega COMO TECLA (input()
        o el binding c-c del selector) se convierte en 'no' sin excepcion, y
        la corrida NO se corta por eso (para eso esta el Ctrl-C del prompt de
        espera)."""
        self.consola["boom"] = KeyboardInterrupt()
        c = cli._Corrida("hacer")
        p = {"kind": "shell_exec", "detalle": "rm -rf x",
             "listo": threading.Event(), "resp": True}
        c.pedido = p
        cli._atender_permiso(c)
        self.assertIs(p["resp"], False)
        self.assertFalse(c.cancelada,
                         "un Ctrl-C en la pregunta no corta la corrida")

    def test_el_hilo_principal_no_pasa_por_el_carril(self):
        """El camino de siempre (comando tecleado, sin corrida) queda intacto:
        _confirmar_accion en el hilo principal pregunta derecho."""
        visto = []
        real = cli._preguntar_desde_hilo
        cli._preguntar_desde_hilo = lambda k, d: visto.append((k, d))
        try:
            self.assertTrue(cli._confirmar_accion("shell_exec", "dir"))
        finally:
            cli._preguntar_desde_hilo = real
        self.assertEqual(visto, [], "el principal se fue por el carril del hilo")
        self.assertEqual(self.consola["veces"], 1)


if __name__ == "__main__":
    unittest.main()
