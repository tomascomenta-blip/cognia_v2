# -*- coding: utf-8 -*-
"""Arnes de verificacion A MANO del carril de fondo (T4) -- para Windows Terminal.

QUE ES: el REPL de verdad, sin el modelo. Usa las funciones REALES de
cognia/cli.py (_lanzar_en_fondo, _esperar_corrida, _abrir_vista_agentes,
_confirmar_accion) y la vista REAL (cognia/tui/agentes.PantallaAgentes), pero el
"trabajo" es un hilo que emite eventos de workflow sinteticos. Asi la corrida
dura lo que uno diga y no depende de :8080 ni de un GGUF.

POR QUE EXISTE: el spike midio el mecanismo con un ConPTY propio y una App de
Textual sintetica. Tres cosas NO las puede firmar un ConPTY:
  * que Windows Terminal de verdad se comporte igual,
  * que Ctrl-C con ENABLE_PROCESSED_INPUT propague (o no) SIGINT,
  * que el shimmer de la vista no parpadee A OJO.
Este arnes las pone delante del dueno en menos de un minuto por caso.

USO (ver VERIFICAR_T4_A_MANO.md):
    venv312\\Scripts\\python.exe scripts\\verificar_t4_manual.py --caso base
    venv312\\Scripts\\python.exe scripts\\verificar_t4_manual.py --caso permiso
    venv312\\Scripts\\python.exe scripts\\verificar_t4_manual.py --caso vista

Al terminar imprime un VEREDICTO leido de GetConsoleMode/GetConsoleCursorInfo
(no de la vista): los modos de consola de antes y de despues tienen que ser los
mismos, el cursor visible y el eco encendido.

Convencion del repo: comentarios en espanol SIN acentos.
"""

import argparse
import ctypes
import os
import sys
import time

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RAIZ not in sys.path:
    sys.path.insert(0, _RAIZ)


# ---------------------------------------------------------------------------
# Sondas de consola (las mismas del spike, leidas en ESTE proceso)
# ---------------------------------------------------------------------------
_K32 = ctypes.windll.kernel32 if os.name == "nt" else None
_ENABLE_ECHO_INPUT = 0x0004
_ENABLE_LINE_INPUT = 0x0002


class _CURSOR(ctypes.Structure):
    _fields_ = [("dwSize", ctypes.c_ulong), ("bVisible", ctypes.c_int)]


def _sonda(fase):
    """in_mode / out_mode / eco / cursor visible. Todo None fuera de Windows."""
    d = {"fase": fase, "in_mode": None, "out_mode": None, "eco": None,
         "cursor_visible": None}
    if _K32 is None:
        return d
    try:
        hin = _K32.GetStdHandle(-10)
        hout = _K32.GetStdHandle(-11)
        m = ctypes.c_ulong()
        if _K32.GetConsoleMode(hin, ctypes.byref(m)):
            d["in_mode"] = m.value
            d["eco"] = bool(m.value & _ENABLE_ECHO_INPUT)
        m2 = ctypes.c_ulong()
        if _K32.GetConsoleMode(hout, ctypes.byref(m2)):
            d["out_mode"] = m2.value
        ci = _CURSOR()
        if _K32.GetConsoleCursorInfo(hout, ctypes.byref(ci)):
            d["cursor_visible"] = bool(ci.bVisible)
    except Exception:
        pass
    return d


# ---------------------------------------------------------------------------
# El trabajo sintetico: eventos de workflow reales, sin modelo
# ---------------------------------------------------------------------------
_TEXTO = ("Escribiendo la respuesta del agente para que el panel tenga algo "
          "que mostrar y el shimmer tenga sobre que correr. ")


def _trabajo(dur, permiso_a_los, imprimir):
    """Emite una corrida de 3 agentes durante `dur` segundos.

    Los eventos son los MISMOS que emite cognia/agent/workflows.py, asi que la
    vista (que solo lee del puente) no distingue esto de una corrida real.
    """
    from cognia.ux import events as ev
    from cognia import cli

    run_id = "verif-t4-%d" % int(time.time())
    ev.emitir(ev.WorkflowInicio(run_id=run_id, nombre="verificar-t4",
                                total_agentes=3, interactivo=True))
    t_fin = time.time() + dur
    t0 = time.time()
    pedido_hecho = False
    agentes = [("%s#pasos.%d@%d" % (run_id, i, i), i,
                "paso %d: sintetico, sin modelo" % i) for i in (1, 2, 3)]
    for aid, idx, etiqueta in agentes:
        ev.emitir(ev.AgenteInicio(run_id=run_id, agente_id=aid, indice=idx,
                                  total=3, fase="pasos", etiqueta=etiqueta))
    chars = {aid: 0 for aid, _, _ in agentes}
    n = 0
    while time.time() < t_fin:
        # Corte cooperativo, igual que el bucle del agente (cli.py): el Ctrl-C
        # del prompt de espera o de la vista marca `cancelada` y el trabajo
        # cierra entre trozos. Sin esto, el corte se ve pero no hace nada y el
        # guion no distinguiria "corto" de "siguio hasta el final".
        c_viva = cli._corrida_viva()
        if c_viva is not None and c_viva.cancelada:
            imprimir("[warn_cl]el trabajo vio el corte y cierra.[/warn_cl]")
            break
        aid = agentes[n % 3][0]
        tok = ev.marcar_agente(aid)
        try:
            trozo = _TEXTO[(n * 7) % len(_TEXTO):][:40] or _TEXTO[:40]
            chars[aid] += len(trozo)
            ev.emitir(ev.TokenTexto(texto=trozo))
            ev.emitir(ev.AgenteProgreso(run_id=run_id, chars=chars[aid],
                                        intento=1))
        finally:
            ev.desmarcar_agente(tok)
        # Una linea de rich cada ~2 s: es lo que tiene que NO romper la linea
        # que el dueno esta tecleando, y lo que la vista tiene que TRAGARSE
        # (begin_capture_print) en vez de pintar sobre la pantalla alterna.
        if n % 20 == 0:
            imprimir("[detail]trabajo: %d s, %d trozos emitidos[/detail]"
                     % (int(time.time() - t0), n))
        if (permiso_a_los and not pedido_hecho
                and time.time() - t0 >= permiso_a_los):
            pedido_hecho = True
            _pedir_permiso(imprimir)
        n += 1
        time.sleep(0.1)
    for aid, idx, etiqueta in agentes:
        ev.emitir(ev.AgenteFin(run_id=run_id, agente_id=aid, indice=idx,
                               total=3, fase="pasos", etiqueta=etiqueta,
                               ok=True, tokens=chars[aid] // 4, intentos=1,
                               duracion_s=time.time() - t0,
                               resumen="sintetico"))
    ev.emitir(ev.WorkflowFin(run_id=run_id, nombre="verificar-t4", ok=True,
                             agentes=3, fallidos=0))
    imprimir("[detail]trabajo terminado.[/detail]")


def _pedir_permiso(imprimir):
    """El gate REAL, pedido DESDE EL HILO. Este era el cuelgue de M5."""
    from cognia import cli
    imprimir("[warn_cl]el hilo pide permiso (gate real). Contesta s o n."
             "[/warn_cl]")
    t = time.time()
    r = cli._confirmar_accion("shell", "echo verificacion-t4-a-mano")
    imprimir("[detail]el hilo recibio la respuesta %r en %.1f s[/detail]"
             % (r, time.time() - t))


# ---------------------------------------------------------------------------
# El REPL minimo: prompt REAL + carril de fondo REAL
# ---------------------------------------------------------------------------
def _sesion():
    """Una PromptSession con el MISMO keybinding de F2 que el REPL."""
    from prompt_toolkit import PromptSession
    from prompt_toolkit.key_binding import KeyBindings
    from cognia import cli

    kb = KeyBindings()

    @kb.add("f2")
    def _f2(event):
        event.app.exit(result=cli._FONDO_F2 + event.app.current_buffer.text)

    try:
        estilo = cli._estilo_prompt()
    except Exception:
        estilo = None
    return PromptSession(key_bindings=kb, style=estilo)


def _humo():
    """Caso SIN consola: prueba el arnes antes de la prueba a mano.

    No toca prompt_toolkit ni Textual (los dos exigen una consola de verdad):
    solo comprueba que el trabajo sintetico emite la corrida entera por el bus.
    Sirve para no descubrir un arnes roto en medio del guion del dueno, y corre
    igual por un pipe (CI, este mismo repo).
    """
    from cognia.ux import events as ev

    # Con COGNIA_EVENTS_JSONL=1 esto ademas escupe las lineas "@EV {...}" del
    # canal del movil: por un PIPE tienen que salir TODAS (mundo pipe).
    try:
        ev.activar_sink_jsonl()
    except Exception:
        pass

    vistos = []

    def _oir(e):
        vistos.append(type(e).__name__)

    ev.suscribir(_oir)
    try:
        _trabajo(2.0, 0.0, lambda s: None)
    finally:
        ev.desuscribir(_oir)
    cuenta = {t: vistos.count(t) for t in sorted(set(vistos))}
    esperado = {"WorkflowInicio": 1, "AgenteInicio": 3, "AgenteFin": 3,
                "WorkflowFin": 1}
    ok = all(cuenta.get(k) == v for k, v in esperado.items())
    ok = ok and cuenta.get("TokenTexto", 0) > 0
    print(" eventos emitidos: %s" % cuenta)
    print(" HUMO: %s" % ("PASA" if ok else "FALLA"))
    return 0 if ok else 1


_GUION = {
    "base": """
  [1] Escribi algo SIN apretar Enter mientras salen las lineas del trabajo.
      -> la linea NO se tiene que romper ni pegarse al texto del trabajo.
  [2] F2 -> se abre la vista de agentes (3 paneles, shimmer corriendo).
      MIRA EL SHIMMER 10 s: tiene que ondular parejo, sin parpadeo.
  [3] esc -> volves. El scrollback de antes tiene que seguir ARRIBA y la
      linea que estabas tecleando tiene que volver ENTERA.
  [4] Ctrl-C en el prompt de espera -> corta LA CORRIDA, el REPL sigue vivo.
  [5] Cuando termine el trabajo, escribi 'salir' + Enter.
""",
    "permiso": """
  [1] Espera a que el hilo pida permiso (a los %(p)s s).
  [2] Con la vista CERRADA: aparece el prompt [permiso] ... (s/n). Contesta s.
      -> el hilo tiene que imprimir 'recibio la respuesta True' en < 5 s.
  [3] Volve a correr este caso y apreta F2 ANTES de los %(p)s s: el permiso
      tiene que salir como MODAL dentro de la vista. Contesta s ahi.
      -> mismo resultado, y la vista tiene que seguir viva.
""",
    "vista": """
  [1] F2 -> vista abierta. Dejala abierta 20 s mirando el shimmer.
  [2] Ctrl-C DENTRO de la vista -> aviso 'corte pedido', la vista NO se cierra
      y el proceso NO se muere.
  [3] esc -> volves al prompt. Nada de basura, scrollback intacto.
""",
    "ctrlc": """
  Este caso levanta un PROCESO HIJO de verdad (como el subprocess de una tool)
  y despues te pide un Ctrl-C. Eso es lo que el ConPTY del spike NO pudo
  firmar: si conhost genera CTRL_C_EVENT, el evento va a TODO el grupo.

  [1] Espera a ver dos o tres lineas 'hijo vivo Ns'.
  [2] Ctrl-C EN EL PROMPT DE ESPERA (una sola vez).
  [3] Mira: el proceso principal NO se puede morir. El veredicto de abajo dice
      si el hijo sobrevivio o no.
""",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--caso", choices=sorted(_GUION) + ["humo"],
                    default="base")
    ap.add_argument("--dur", type=float, default=0.0,
                    help="segundos de trabajo (0 = el default del caso)")
    ap.add_argument("--permiso", type=float, default=-1.0,
                    help="segundos hasta pedir permiso (-1 = default del caso)")
    a = ap.parse_args()

    if a.caso == "humo":
        return _humo()

    dur = a.dur or {"base": 60.0, "permiso": 45.0, "vista": 90.0,
                    "ctrlc": 40.0}[a.caso]
    permiso = a.permiso if a.permiso >= 0 else (8.0 if a.caso == "permiso"
                                                else 0.0)

    from cognia import cli

    # Mismo arranque del canal del movil que hace el REPL (_arranque_ux): con
    # COGNIA_EVENTS_JSONL=1 cada evento sale como una linea "@EV {...}". Es lo
    # que lee remoto/sesiones.py por su PIPE, y es la mitad del conflicto que
    # este arnes sirve para mirar: en CONSOLA esas lineas NO se tienen que
    # pintar encima de la pantalla alterna; por PIPE tienen que salir todas.
    try:
        from cognia.ux import events as _ev
        _ev.activar_sink_jsonl()
    except Exception:
        pass

    sondas = [_sonda("arranque")]
    print("=" * 68)
    print(" VERIFICAR T4 A MANO  |  caso=%s  dur=%ss  permiso=%ss"
          % (a.caso, int(dur), int(permiso) if permiso else "no"))
    print("=" * 68)
    print(_GUION[a.caso] % {"p": int(permiso)} if permiso
          else _GUION[a.caso])
    # Autochequeo: que el arnes no se caiga a la mitad del guion por un import.
    faltan = []
    for mod in ("prompt_toolkit", "textual", "cognia.tui.agentes",
                "cognia.tui.permiso"):
        try:
            __import__(mod)
        except Exception as exc:
            faltan.append("%s (%s)" % (mod, exc))
    print(" arnes: %s" % ("ok" if not faltan else "FALTA " + "; ".join(faltan)))
    print(" sonda de arranque: %s" % sondas[0])
    input(" Enter para arrancar... ")

    try:
        ses = _sesion()
    except Exception as exc:
        # Sin una consola de verdad (pipe, redireccion, CI) prompt_toolkit no
        # arranca. Es la mitad del punto de este arnes: decirlo claro en vez de
        # escupir un traceback de 20 lineas.
        print("\n Este caso necesita una CONSOLA de verdad (Windows Terminal, "
              "sin | ni >).\n %s: %s\n Para probar el arnes por un pipe: "
              "--caso humo" % (type(exc).__name__, exc))
        return 2
    cli._sesion_prompt = ses
    cli._COLA_ENTRADA.clear()

    # El hijo del caso 'ctrlc': un proceso de verdad, con la MISMA consola, que
    # es lo que hace cualquier tool que llama a subprocess. Si conhost genera
    # CTRL_C_EVENT, el evento va al grupo entero y este hijo tambien lo recibe.
    # El ConPTY del spike no podia firmarlo; aca se mira.
    hijo = None
    if a.caso == "ctrlc":
        import subprocess
        hijo = subprocess.Popen(
            [sys.executable, "-u", "-c",
             "import time\n"
             "for i in range(600):\n"
             "    print('    hijo vivo %ds' % i, flush=True)\n"
             "    time.sleep(1)\n"])

    sondas.append(_sonda("antes"))
    atendido = cli._lanzar_en_fondo("verif-t4", _trabajo, dur, permiso,
                                    cli._print_line)
    sondas.append(_sonda("despues"))

    hijo_vivo = None
    if hijo is not None:
        hijo_vivo = hijo.poll() is None
        print("\n HIJO: %s (rc=%s). Si murio, un Ctrl-C durante una tool mata "
              "tambien su subprocess: limite conocido, no bloqueante."
              % ("VIVO" if hijo_vivo else "MUERTO", hijo.poll()))
        try:
            hijo.kill()
        except Exception:
            pass

    # El prompt normal de despues: aca se comprueba que el terminal quedo sano
    # (eco, colores, F2 sin corrida) sin salir del proceso.
    print("\n La corrida termino. Probamos el prompt NORMAL (F2 sigue "
          "andando, 'salir' cierra).")
    while True:
        try:
            linea = ses.prompt("verif-t4> ")
        except KeyboardInterrupt:
            print(" Ctrl-C: corta la linea, no el proceso. (correcto)")
            continue
        except EOFError:
            break
        if linea.startswith(cli._FONDO_F2):
            cli._abrir_vista_agentes()
            continue
        if linea.strip() in ("salir", "/salir", "exit", "q"):
            break
        if linea.strip():
            print("  eco: %r" % linea)
    sondas.append(_sonda("salida"))

    ref = sondas[1]
    fin = sondas[-1]
    chequeos = [
        ("_lanzar_en_fondo tomo la corrida (no cayo a inline)", atendido),
        ("modo de ENTRADA restaurado", fin["in_mode"] == ref["in_mode"]),
        ("modo de SALIDA restaurado", fin["out_mode"] == ref["out_mode"]),
        ("eco encendido al salir", fin["eco"] is not False),
        ("cursor visible al salir", fin["cursor_visible"] is not False),
        # El carril es EXCLUSIVO: si _lanzar_en_fondo no lo libera en su
        # finally, la proxima corrida se rechaza con "ya hay una en curso" y el
        # REPL se queda inservible hasta reiniciarlo.
        ("el carril quedo libre para la proxima corrida",
         cli._corrida_viva() is None),
    ]
    print("\n" + "=" * 68)
    print(" VEREDICTO (GetConsoleMode / GetConsoleCursorInfo, no la vista)")
    print("=" * 68)
    ok_todo = True
    for nombre, ok in chequeos:
        ok_todo = ok_todo and bool(ok)
        print("  %-5s %s" % ("PASA" if ok else "FALLA", nombre))
    for s in sondas:
        print("  %-9s in=%-5s out=%-4s eco=%-5s cursor=%s"
              % (s["fase"], s["in_mode"], s["out_mode"], s["eco"],
                 s["cursor_visible"]))
    if cli._COLA_ENTRADA:
        print("  anotado mientras corria: %r" % (cli._COLA_ENTRADA,))
    print("\n TOTAL: %s" % ("PASA" if ok_todo else "FALLA"))
    print(" Ahora mira la consola A OJO: se ve el scrollback de antes? "
          "proba `dir` y que salga con colores.")
    return 0 if ok_todo else 1


if __name__ == "__main__":
    sys.exit(main())
