# PLAN T4 — el runner: la corrida al hilo, el teclado vivo, F2 y la vuelta entera

**Fecha:** 2026-08-18 · **Estado:** propuesta, NO aplicada (`cognia/cli.py` está reservado por otra tanda)
**Alcance:** el parche exacto para `cognia/cli.py` + un fichero nuevo (`cognia/tui/permiso.py`).
**Este documento no edita nada.** Todo lo medido vive en
`…\scratchpad\spike_t4\` (`t4b_hijo.py`, `t4b_correr.py`, `t4b_*.jsonl`, `t4b_resultados.json`).

---

## 0. Resumen ejecutable

El camino directo **sirve**: la corrida va a un hilo, el hilo principal se queda en
`session.prompt()` con el teclado vivo, F2 abre la App de Textual y al salir el terminal vuelve
entero. El spike T4 ya lo había medido para el terminal; esta tanda midió los **tres mecanismos
nuevos** de los que depende el parche y encontró **un fallo grave del diseño obvio**:

> **Un hilo que abre una `Application` de prompt_toolkit no vuelve NUNCA.**
> `_confirmar_accion` (el `ctx['confirm']` del agente) hace exactamente eso.
> Medido dos veces, en los dos escenarios posibles, y en los dos se colgó para siempre.

Por eso el parche no es "lanzar un hilo": es **lanzar un hilo y arbitrar la consola**. El hilo
nunca pregunta; delega en quien sea dueño de la consola en ese momento (la App, si está abierta;
el hilo principal, si está en el prompt). Las dos vías están medidas y funcionan.

---

## 1. Lo que leí del REPL de hoy (con líneas)

| Pieza | Dónde | Lo que importa |
|---|---|---|
| Imports de prompt_toolkit | `cli.py:102-111` | **no** se importa `patch_stdout` |
| `_confirmar_accion` | `cli.py:792-838` | `needs_confirmation` → `selector.confirmar()` (Application de pt) → `input()`. Inyectado como `ctx['confirm']` en `cli.py:10340` |
| `_slash_workflow` | `cli.py:6767-6811` | síncrono; `_wf.ejecutar(...)` bloquea hasta el final; imprime resultado + `run_id` |
| Construcción del prompt | `cli.py:6931-6989` | `KeyBindings` con un solo binding (`tab`, 6936), `PromptSession(...)` (6967), `globals()["_sesion_prompt"] = session` (6971) |
| `_inyectadas` | `cli.py:6999` | lista local; el enrutador por inferencia encola en 9387 |
| `_get_input` | `cli.py:7002-7018` | `session.prompt(_mensaje_prompt)` + continuación con `\` |
| Lectura del bucle | `cli.py:7041-7048` | `raw = _strip_input_bom(_get_input())`; `except (EOFError, KeyboardInterrupt): print("\nHasta luego."); break` |
| Despacho `/workflow` | `cli.py:7089-7090` | inline |
| Despacho `/hacer` | `cli.py:8272-8323` | inline: `_run_agent_task` → `_show_response` → `_session_log.append` |
| Bucle de pasos del agente | `cli.py:10673` | `while not _bon_ok and total_steps < AGENT_HARD_CAP:` — **no hay ningún hook de cancelación** |
| Fast-path de streaming | `cli.py:9403-9830` | ya tiene su `except KeyboardInterrupt` que corta el turno y no el REPL (9770) |
| Spinner | `cognia/ux/renderer.py:177-204` | `console.status()` (rich Live); se apaga con `COGNIA_SPINNER=0`, leído **a call-time** (`renderer.py:72`) |
| Cancelación de workflows | `harness/workflows_adapter.py:548` | `cancelar_corrida(run_id="")` = botón de pánico sobre todas las corridas vivas |
| La vista | `cognia/tui/agentes.py:418` | `PantallaAgentes(App)`; `ctrl+x` ya está declarado como `action_pendiente` (otra tanda) |

---

## 2. Lo que medí en esta tanda (y que el spike T4 no cubría)

Mismo instrumento que el spike: ConPTY por ctypes + `bootstrap.enganchar()` + sondas
`GetConsoleMode`/`GetConsoleCursorInfo` **leídas desde adentro del hijo**. Ejecutable:

```
cd …\scratchpad\spike_t4
venv312\Scripts\python.exe t4b_correr.py            # los 5 casos
```

### M1 — despertar el prompt desde el hilo: **funciona**
`app.loop.call_soon_threadsafe(functools.partial(app.exit, result=CENTINELA))`.

| | valor |
|---|---|
| prompt devolvió el centinela | **sí** (`'\x00__fin_corrida__'`) |
| bloqueado | 2001,7 ms para una corrida de 2,0 s → despertó **al primer intento** (0 reintentos) |
| modos de consola antes / después / salida | `in=503 out=7 cursor=1` en las tres sondas |
| `ESC[?1049h/l` | 0/0 (no hubo App: es el caso puro) |
| prompt normal después | aceptó y devolvió `probando 1 2 3` |

### M2 — la carrera (el hilo termina ANTES de que el prompt exista): **cubierta por el reintento**
El hilo intenta despertar y no hay prompt. Con el bucle de reintento de 10 ms: `ok=True` tras
**30 intentos** y el prompt quedó bloqueado **11,6 ms**. Sin el bucle, el usuario se queda mirando
un prompt que ya nadie va a despertar.

### M3 — la línea a medio escribir: **se pierde, y se puede rescatar**
En M1 el usuario tenía tecleado `hola mun` cuando el hilo terminó: **desapareció**
(`app.exit()` descarta el buffer). Rescatándola desde el hilo (`session.app.current_buffer.text`)
y devolviéndola como `default=` del siguiente prompt: `'esto lo estaba escribiendo'` volvió
**entera** (caso `texto_perdido`).

### M4 — el spinner de rich con el prompt abierto: **hay que apagarlo**
`Console.status()` (Live) desde el hilo, con el prompt abierto bajo `patch_stdout(raw=True)`:

| | valor |
|---|---|
| líneas `pensando…` en el scrollback | **14 en 3,0 s** (~4,7 líneas/s) |
| `ESC[1A` / `ESC[2K` (reescritura en sitio) | **0 / 0** — el Live no reescribe: cada frame pasa por el redibujado de `patch_stdout` |
| la línea tecleada | intacta (17 redibujados), 0 pegada a prosa |

O sea: el terminal no se corrompe, pero un `/hacer` de 3 minutos deja **~850 líneas de basura**
en el scrollback. → `COGNIA_SPINNER=0` mientras dure el carril de fondo.

### M5 — el gate de permisos desde un hilo: **SE CUELGA PARA SIEMPRE** (los dos casos)
Llamando al `cognia.ux.selector.confirmar()` real desde un hilo:

| escenario | `hay_tty()` | resultado |
|---|---|---|
| con la App de Textual abierta | True | **NO VOLVIÓ** — ni al cerrar la App, ni un segundo después (`estado_al_cerrar_app: NO_VOLVIO`) |
| con solo el prompt del REPL abierto | True | **NO VOLVIÓ** — y la tecla `s` se la comió el prompt del REPL (devolvió `''`) |

Dos `Application` de prompt_toolkit sobre la misma consola: la segunda queda muda y ciega.
Con la App de Textual encima es peor todavía, porque `sys.stdout` es un `_PrintCapture` y su
dibujo se descarta. **Este es el fallo que mata el diseño ingenuo**: el agente queda colgado, sin
mensaje, sosteniendo una tool a medias, y el usuario no tiene forma de saberlo.

### M6 — las dos vías buenas: **funcionan las dos**

| vía | mecanismo | resultado | latencia |
|---|---|---|---|
| vista abierta | `app.call_from_thread(push_screen(Modal, cb))` + `threading.Event` | `True` | **1.229,5 ms** (= el sleep del guion) |
| prompt abierto | despertar con centinela `PERMISO` → **el hilo principal** llama a `selector.confirmar()` → `Event` | `True` | **1.032,9 ms** |

En los dos casos las sondas de consola dieron `in=503 out=7 cursor=1` a la entrada y a la salida,
y con la App: `?1049h`/`?1049l` **1/1**, `ESC[3J` **0**.

### M7 — Ctrl-C dentro de la vista: **es una tecla, y la subclase la captura**
Confirmado otra vez con un `BINDINGS` propio: `ctrl+c` disparó la acción, la App **siguió viva**,
`esc` la cerró después y los modos volvieron a 503/7.

---

## 3. EL PARCHE

Nueve hunks en `cli.py` + un fichero nuevo. Los números de línea son los del fichero de hoy
(11.300 líneas) y están dados como "insertar después de N" / "reemplazar N-M".

### Hunk 1 — imports (líneas 7-17 y 109)

```diff
@@ cli.py:7 @@
 import contextlib
 import datetime
+import functools
 import io
 import json
 import logging
 import os
 import re
 import shutil
 import subprocess
 import sys
+import threading
 import time
```

```diff
@@ cli.py:109 @@
     from prompt_toolkit.key_binding import KeyBindings
+    # patch_stdout con raw=True (OBLIGATORIO): sin raw, Vt100_Output.write()
+    # reemplaza cada ESC por '?' (prompt_toolkit/output/vt100.py:517; write_raw
+    # no lo hace) y TODO el color de rich sale mutilado. Medido en el spike T4:
+    # 10 secuencias '?[36m' y 0 intactas con raw=False; 0 mutiladas y 5
+    # intactas con raw=True. Cognia es un REPL entero de rich.
+    from prompt_toolkit.patch_stdout import patch_stdout
     from prompt_toolkit.shortcuts import CompleteStyle
```

> `threading` hoy solo se importa dentro de una función (`cli.py:2551`); subirlo al módulo es
> necesario porque el gate de permisos (que se ejecuta en el import path del agente) tiene que
> preguntar en qué hilo está.

---

### Hunk 2 — el carril de fondo (bloque NUEVO, insertar antes de `def _confirmar_accion`, o sea **después de la línea 790**)

```python
# ---------------------------------------------------------------------------
# CARRIL DE FONDO: la corrida larga en un hilo, la consola ARBITRADA
# ---------------------------------------------------------------------------
# POR QUE (T4, 2026-08-18): /workflow y /hacer se despachaban INLINE en el bucle
# del REPL, asi que mientras corrian NADIE leia el teclado: la vista de agentes
# (F2) no podia existir. Aca vive lo minimo para que la corrida viva en un hilo
# y el hilo PRINCIPAL siga siendo el UNICO dueno de la consola.
#
# LA REGLA QUE MANDA, Y ESTA MEDIDA (spike T4-b, ConPTY, 2026-08-18):
#   un hilo que abre una Application de prompt_toolkit NO VUELVE NUNCA.
#   Se midio cognia.ux.selector.confirmar() desde un hilo en los DOS escenarios
#   posibles y en los dos se colgo para siempre:
#     - con la App de Textual abierta ....... NO VOLVIO (ni al cerrar la App)
#     - con solo el prompt del REPL abierto . NO VOLVIO (la tecla se la comio el
#                                             prompt del REPL, que devolvio '')
#   Y estas dos SI funcionan:
#     - hilo -> modal de Textual (call_from_thread + push_screen) . True, 1229,5 ms
#     - hilo -> despertar el prompt y que conteste el principal ... True, 1032,9 ms
# Por eso el hilo NUNCA pregunta: delega en quien tenga la consola.

# Centinelas del prompt de espera. Empiezan con \x00 (imposible de teclear) y
# ARRASTRAN la linea que el usuario tenia a medio escribir: app.exit() DESCARTA
# el buffer (medido: 'hola mun' desaparecio), y devolverla como `default=` del
# proximo prompt la conserva entera (medido: volvio intacta).
_FONDO_F2      = "\x00@f2@"
_FONDO_FIN     = "\x00@fin@"
_FONDO_PERMISO = "\x00@permiso@"

# Tope del hilo esperando una respuesta de permiso. Vencido -> DENY, que es el
# default del gate, con aviso visible. Un hilo esperando para siempre es el
# fallo silencioso que este repo persigue.
_ESPERA_PERMISO_S = 600.0

# Lineas que el usuario tecleo MIENTRAS corria algo: se ejecutan cuando termina.
# Es una lista de modulo (y no la local de repl()) para que el carril de fondo,
# que vive aca afuera, pueda encolar en ella.
_COLA_ENTRADA: list = []

_VISTA = {"app": None}          # la App de agentes abierta, o None
_LOCK_FONDO = threading.RLock()
_CORRIDA = None                 # la _Corrida viva, o None


class _Corrida:
    """Una corrida de fondo. UNA por vez: el carril es exclusivo.

    Por que exclusivo: dos corridas comparten _history, _session_log, el cwd y
    el gate de permisos, y ademas el unico slot de :8080. El adaptador de
    workflows ya serializa con cap=2 adentro de UNA corrida; dos corridas
    encima seria pelearse por el mismo slot sin que nadie lo pidiera.
    """

    __slots__ = ("etiqueta", "hilo", "fin", "excepcion", "pedido",
                 "cancelada", "t0")

    def __init__(self, etiqueta: str):
        self.etiqueta = etiqueta
        self.hilo = None
        self.fin = threading.Event()
        self.excepcion = None
        self.pedido = None       # dict del permiso pendiente, o None
        self.cancelada = False
        self.t0 = time.time()


def _corrida_viva():
    """La corrida en curso, o None. Lo lee el gate de permisos y la vista."""
    c = _CORRIDA
    return c if (c is not None and not c.fin.is_set()) else None


def corrida_en_curso() -> bool:
    """Publica para quien necesite saberlo sin tocar el privado (tests, barra)."""
    return _corrida_viva() is not None


def _texto_a_medias() -> str:
    """Lo que el usuario tenia a medio escribir. '' ante cualquier duda."""
    try:
        return _sesion_prompt.app.current_buffer.text or ""
    except Exception:
        return ""


def _despertar_prompt(centinela: str, intentos: int = 200) -> bool:
    """Saca al prompt del bloqueo DESDE OTRO HILO. Nunca lanza.

    MEDIDO: app.exit() tiene que correr en el hilo del event loop de
    prompt_toolkit; llamarla derecho desde el hilo del workflow no despierta
    nada. La via es app.loop.call_soon_threadsafe (Application.loop se setea en
    run_async y vuelve a None al terminar).
      * con el prompt ya abierto: desperto al PRIMER intento y el prompt
        devolvio el centinela a los 2001,7 ms de una corrida de 2,0 s.
      * con el hilo terminando ANTES de que el prompt existiera: 30 intentos de
        10 ms lo cazaron y el prompt bloqueo 11,6 ms. SIN el bucle de reintento
        esa carrera deja al usuario esperando un prompt que ya no llega.
    """
    ses = _sesion_prompt
    if ses is None:
        return False
    for _ in range(max(1, intentos)):
        try:
            app = getattr(ses, "app", None)
            loop = getattr(app, "loop", None)
            if app is not None and loop is not None and app.is_running:
                loop.call_soon_threadsafe(
                    functools.partial(app.exit,
                                      result=centinela + _texto_a_medias()))
                return True
        except Exception:
            return False
        time.sleep(0.01)
    return False


def _mensaje_espera(c):
    """El prompt del carril de fondo: MISMO marco que el de siempre.

    Lo unico que cambia es la palabra, para que se vea que hay algo corriendo y
    cuales son las dos teclas. Se devuelve un callable porque prompt_toolkit lo
    reevalua en cada redibujado (igual que _mensaje_prompt)."""
    def _msg():
        return FormattedText([
            ("class:marco", _REGLA * _ancho_marco() + "\n"),
            ("class:cognia", f" {c.etiqueta} {int(time.time() - c.t0)}s"),
            ("class:estado", "  F2 agentes · Ctrl-C corta"),
            ("class:flecha", _FLECHA),
        ])
    return _msg


def _abrir_vista_agentes() -> None:
    """Abre la pantalla de agentes y vuelve al REPL al salir.

    MEDIDO (spike T4, 7 escenarios): Textual entra y sale de la pantalla alterna
    con ESC[?1049h/l balanceados 1/1, cero ESC[3J (el scrollback de antes sigue
    arriba) y devuelve los modos EXACTOS: in 503 -> 512 dentro de la App -> 503
    al salir, out 7 estable, cursor visible. El riesgo de terminal en raw mode
    no se materializo en ninguno de los 7.

    Se abre AFUERA del bucle de prompt_toolkit a proposito (el keybinding de F2
    solo sale con un centinela): anidar el event loop de Textual dentro del de
    prompt_toolkit es el modo de fallo que este diseno evita.
    """
    try:
        from cognia.tui.agentes import PantallaAgentes
    except Exception as exc:
        _print_line(f"[warn_cl]La vista de agentes no esta disponible: "
                    f"{_escape(str(exc))}[/warn_cl]")
        _aviso_degradado("cli.vista.import", f"{type(exc).__name__}: {exc}")
        return
    try:
        app = _vista_con_corte(PantallaAgentes)()
    except Exception as exc:
        _print_line(f"[warn_cl]No pude construir la vista: "
                    f"{_escape(str(exc))}[/warn_cl]")
        return
    _VISTA["app"] = app
    try:
        app.run()
    except Exception as exc:
        _aviso_degradado("cli.vista.run", f"{type(exc).__name__}: {exc}")
    finally:
        _VISTA["app"] = None


def _vista_con_corte(base):
    """PantallaAgentes + Ctrl-C = cortar LA CORRIDA (no el REPL).

    Es una SUBCLASE y no un parche a cognia/tui/agentes.py porque ese fichero es
    de otra tanda. Cuando alli se cablee ctrl+x ('cancelar corrida'), este
    envoltorio se borra y se usa el binding de alla.

    MEDIDO: dentro de una App de Textual el Ctrl-C llega como TECLA normal
    ('ctrl+c'), no como SIGINT — durante la App ENABLE_PROCESSED_INPUT esta
    apagado (in_mode=512) y conhost nunca genera CTRL_C_EVENT. Verificado: el
    binding se disparo, la App siguio viva, esc la cerro despues y los modos
    volvieron a 503/7.

    CSS_PATH ABSOLUTO a proposito: Textual resuelve un CSS_PATH relativo contra
    inspect.getfile(type(self)) (textual/_path.py:_make_path_object_relative),
    que en una subclase definida en cli.py daria 'cognia/agentes.tcss' — un
    fichero que no existe y una App que no arranca.
    """
    from textual.binding import Binding

    _tcss = Path(sys.modules[base.__module__].__file__).with_name("agentes.tcss")

    class _VistaAgentesREPL(base):
        # Textual fusiona BINDINGS por el MRO: aca solo va lo que se AGREGA.
        CSS_PATH = str(_tcss)
        BINDINGS = [Binding("ctrl+c", "cortar_corrida", "Cancelar la corrida")]

        def action_cortar_corrida(self) -> None:
            linea = _cancelar_corrida(_corrida_viva(), callado=True)
            self.notify(linea, title="Ctrl-C", severity="warning", timeout=5)

    return _VistaAgentesREPL


def _cancelar_corrida(c, callado: bool = False) -> str:
    """Ctrl-C = cortar LA CORRIDA, jamas el REPL. Devuelve la linea a mostrar.

    Limite HONESTO, declarado porque cambia lo que el usuario puede esperar:
      * /workflow SI se corta de verdad: el motor tiene cancelacion cooperativa
        por agente (workflows_adapter.cancelar_corrida -> Control.cancelar_todo)
        y el envelope vuelve con `cancelados`>0 y el texto YA PAGADO adentro.
      * /hacer se corta AL TERMINAR EL PASO EN CURSO (ver hunk 9): el bucle del
        agente no tenia ningun hook de cancelacion. Una tool larga (un build, un
        subprocess) NO se interrumpe: termina y ahi corta.
    Se usa cancelar_corrida("") = todas las corridas vivas, y es correcto porque
    el carril de fondo es EXCLUSIVO: solo hay una.
    """
    if c is None:
        return "no hay corrida que cortar"
    c.cancelada = True
    partes = []
    try:
        from cognia.harness import workflows_adapter as _wf
        env = _wf.cancelar_corrida("", "el usuario corto con Ctrl-C")
        partes.append(f"{int(env.get('agentes', 0) or 0)} agente(s) alcanzado(s)")
    except Exception as exc:
        partes.append(f"el motor de workflows no acepto el corte ({exc})")
    linea = ("corte pedido: " + "; ".join(partes)
             + ". El paso en curso termina antes de cerrar.")
    if not callado:
        _print_line(f"[warn_cl]Ctrl-C: {_escape(linea)} "
                    f"El REPL sigue vivo.[/warn_cl]")
    return linea


def _atender_permiso(c) -> None:
    """El hilo PRINCIPAL contesta el permiso que pidio el hilo de la corrida.

    Aca la consola es NUESTRA, asi que se llama al selector de siempre: el mismo
    menu con flechas, el mismo texto plano para los pipes, el mismo default."""
    p = c.pedido
    if not p:
        return
    try:
        p["resp"] = _preguntar_en_consola(p["kind"], p["detalle"])
    except Exception as exc:
        p["resp"] = False
        _aviso_degradado("cli.permiso.consola", f"{type(exc).__name__}: {exc}")
    finally:
        c.pedido = None
        p["listo"].set()


def _permiso_en_vista(app, kind: str, detalle: str):
    """El permiso preguntado DENTRO de la vista. None si no se pudo.

    MEDIDO: True en 1.229,5 ms, la App siguio sana y los modos volvieron a
    503/7. Se usa push_screen con callback (y NO push_screen_wait): el
    wait_for_dismiss exige un worker de Textual y este hilo es un
    threading.Thread pelado — pedirselo lanza NoActiveWorker."""
    try:
        from cognia.tui.permiso import PantallaPermiso
    except Exception as exc:
        _aviso_degradado("cli.permiso.modal", f"{type(exc).__name__}: {exc}")
        return None
    listo = threading.Event()
    caja = {}

    def _cb(valor):
        caja["v"] = bool(valor)
        listo.set()

    def _empujar():
        app.push_screen(PantallaPermiso(kind, detalle), _cb)

    try:
        app.call_from_thread(_empujar)
    except Exception as exc:
        _aviso_degradado("cli.permiso.post", f"{type(exc).__name__}: {exc}")
        return None
    # Espera CON pulso: si el usuario cierra la vista con el modal abierto, el
    # callback no llega nunca y quedarse 600 s seria colgar al agente igual que
    # el bug que este codigo viene a arreglar. Al morir la App se devuelve None
    # y el enrutador reintenta por el prompt.
    limite = time.time() + _ESPERA_PERMISO_S
    while time.time() < limite:
        if listo.wait(0.25):
            return caja.get("v", False)
        if not getattr(app, "is_running", False):
            return None
    _aviso_degradado("cli.permiso.timeout_vista",
                     f"{_ESPERA_PERMISO_S:.0f}s sin respuesta: se deniega")
    return False


def _preguntar_desde_hilo(kind: str, detalle: str):
    """La pregunta del hilo, contestada por el DUENO de la consola.

    True/False, o None si no hay a quien delegarla. Dos pasadas porque la vista
    se puede abrir o cerrar justo en el medio."""
    for _ in range(2):
        app = _VISTA.get("app")
        if app is not None and getattr(app, "is_running", False):
            r = _permiso_en_vista(app, kind, detalle)
            if r is not None:
                return r
        c = _corrida_viva()
        if c is None:
            return None
        p = {"kind": kind, "detalle": detalle,
             "listo": threading.Event(), "resp": False}
        c.pedido = p
        if not _despertar_prompt(_FONDO_PERMISO):
            c.pedido = None
            continue                       # ¿se abrio la vista? -> 2a pasada
        if not p["listo"].wait(_ESPERA_PERMISO_S):
            c.pedido = None
            _aviso_degradado("cli.permiso.timeout_prompt",
                             f"{_ESPERA_PERMISO_S:.0f}s sin respuesta: se deniega")
            return False
        return bool(p["resp"])
    return None


def _lanzar_en_fondo(etiqueta: str, fn, *args, **kw) -> bool:
    """Corre fn(*args) en un hilo y espera con el TECLADO VIVO.

    Devuelve False cuando no hay carril de fondo posible (sin PromptSession:
    pipes, CI, subprocess) y el caller tiene que seguir por el camino INLINE de
    siempre — ese camino queda BYTE-IDENTICO a hoy, que es el contrato.
    """
    global _CORRIDA
    if _sesion_prompt is None:
        return False
    with _LOCK_FONDO:
        if _corrida_viva() is not None:
            _print_line(f"[warn_cl]Ya hay una corrida en curso "
                        f"({_escape(_CORRIDA.etiqueta)}). F2 para verla, "
                        f"Ctrl-C para cortarla.[/warn_cl]")
            return True                    # atendido: NO ejecutar tambien inline
        c = _Corrida(etiqueta)
        _CORRIDA = c

    # El spinner de rich (Live) y el prompt no pueden compartir la consola.
    # MEDIDO con el prompt abierto: un status() de 3,0 s dejo 14 lineas
    # 'pensando…' en el scrollback (~4,7 lineas/s) y CERO secuencias ESC[1A /
    # ESC[2K — el Live no reescribe en sitio, cada frame pasa por el redibujado
    # de patch_stdout. En 3 minutos de /hacer son ~850 lineas de basura. En el
    # carril de fondo el spinner se apaga; la actividad se mira con F2.
    # renderer._consola_interactiva() lee COGNIA_SPINNER a CALL-TIME, asi que
    # esto surte efecto sin recargar nada, y se restaura al terminar.
    _spinner_antes = os.environ.get("COGNIA_SPINNER")
    os.environ["COGNIA_SPINNER"] = "0"

    def _correr():
        try:
            fn(*args, **kw)
        except BaseException as exc:       # noqa: BLE001 — el hilo no muere mudo
            c.excepcion = exc
        finally:
            c.fin.set()
            _despertar_prompt(_FONDO_FIN)

    c.hilo = threading.Thread(target=_correr, name=f"cognia-{etiqueta}",
                              daemon=True)
    c.hilo.start()
    try:
        _esperar_corrida(c)
    finally:
        with _LOCK_FONDO:
            _CORRIDA = None
        if _spinner_antes is None:
            os.environ.pop("COGNIA_SPINNER", None)
        else:
            os.environ["COGNIA_SPINNER"] = _spinner_antes
    if c.excepcion is not None:
        _print_line(f"[err_cl]{_escape(type(c.excepcion).__name__)}: "
                    f"{_escape(str(c.excepcion))}[/err_cl]")
        _aviso_degradado("cli.fondo",
                         f"{type(c.excepcion).__name__}: {c.excepcion}")
    return True


def _esperar_corrida(c) -> None:
    """El hilo PRINCIPAL mientras la corrida vive: teclado vivo, consola suya.

    Cada decision con su medicion:
      * patch_stdout(raw=True): sin raw, prompt_toolkit reemplaza cada ESC por
        '?' y todo el color de rich sale mutilado (10 de 10 secuencias rotas).
        Con raw=True: 0 rotas. Y con el, la linea a medio escribir se redibuja
        INTACTA cuando el hilo imprime (6 de 6); sin el, el texto del hilo se
        pega a la linea del usuario y la barra desaparece.
      * el prompt bloquea DE VERDAD: 0,00 % de CPU en 30 s de reposo (0,0 s de
        process_time). El brazo msvcrt costaba 0,47 % y 10x la latencia.
      * refresh_interval=1.0 es lo que hace correr el reloj del prompt. Cuesta
        ~1 % de un core mientras hay corrida (medido: 2,24 % con 0,5 s), y solo
        mientras hay corrida.
    """
    pendiente = ""
    while True:
        if c.fin.is_set() and c.pedido is None:
            return
        try:
            with patch_stdout(raw=True):
                r = _sesion_prompt.prompt(_mensaje_espera(c),
                                          default=pendiente,
                                          refresh_interval=1.0)
            pendiente = ""
        except KeyboardInterrupt:
            # Ctrl-C EN EL PROMPT: prompt_toolkit lo entrega como excepcion y
            # corta SOLO la linea (medido). Aca corta LA CORRIDA y sigue
            # esperando a que el hilo cierre: matar el REPL con trabajo vivo es
            # justo lo que este diseno viene a impedir.
            _cancelar_corrida(c)
            continue
        except EOFError:
            _cancelar_corrida(c)
            _print_line("[warn_cl]Ctrl-D con una corrida viva: se pidio el "
                        "corte y se espera a que cierre.[/warn_cl]")
            c.fin.wait()
            return
        except Exception as exc:
            # Sin consola no hay espera interactiva posible: se degrada a
            # bloquear seco, que es exactamente el comportamiento de hoy.
            _aviso_degradado("cli.fondo.espera", f"{type(exc).__name__}: {exc}")
            c.fin.wait()
            return

        if r.startswith(_FONDO_FIN):
            pendiente = r[len(_FONDO_FIN):]
            continue                       # el 'if' de arriba decide si cierra
        if r.startswith(_FONDO_PERMISO):
            pendiente = r[len(_FONDO_PERMISO):]
            _atender_permiso(c)
            continue
        if r.startswith(_FONDO_F2):
            pendiente = r[len(_FONDO_F2):]
            _abrir_vista_agentes()
            continue
        linea = (r or "").strip()
        if linea:
            # Se ANOTA, no se ejecuta: dos turnos a la vez comparten _history,
            # el cwd y el unico slot de :8080. El proximo _get_input la
            # devuelve y entra por el MISMO dispatch de siempre.
            _COLA_ENTRADA.append(linea)
            _print_line(f"[info_dim]anotado ({len(_COLA_ENTRADA)} en cola): se "
                        f"ejecuta cuando termine {_escape(c.etiqueta)}."
                        f"[/info_dim]")
```

---

### Hunk 3 — `_confirmar_accion` pasa a ser un ENRUTADOR (reemplaza 792-838)

El cuerpo de hoy no se toca: se le corta la cabeza (`needs_confirmation`, que decide **si** hay
que preguntar) del cuerpo (que decide **cómo**), y en el medio se mete el enrutado.

```diff
@@ cli.py:792 @@
 def _confirmar_accion(kind: str, detalle: str) -> bool:
-    """Gate central de permisos: True = proceder. Respeta el modo vigente."""
+    """Gate central de permisos: True = proceder. Respeta el modo vigente.
+
+    Desde 2026-08-18 es un ENRUTADOR: decide QUIEN contesta, no como. La
+    pregunta la responde SIEMPRE el dueno de la consola, porque un hilo que
+    abre una Application de prompt_toolkit no vuelve nunca (medido: colgado
+    para siempre con la vista abierta Y con solo el prompt abierto). Esta
+    funcion es el ctx['confirm'] del agente (cli.py:10340) y el agente ahora
+    puede correr en un hilo: sin este enrutado, la primera accion sensible de
+    un /hacer en segundo plano cuelga la corrida sin decir una palabra.
+    """
     try:
         from cognia.console.permissions import needs_confirmation
         if not needs_confirmation(kind, detalle):
             return True
     except Exception as exc:
         # DENY ante cualquier fallo del clasificador. [...comentario intacto...]
         logging.getLogger(__name__).warning(
             "Clasificador de permisos fallo (%s=%r): se deniega la accion "
             "por seguridad: %s", kind, detalle[:80], exc)
         return False
+    if threading.current_thread() is not threading.main_thread():
+        r = _preguntar_desde_hilo(kind, detalle)
+        if r is not None:
+            return r
+        # No habia a quien delegar. Con un tty de por medio, preguntar aca
+        # colgaria el hilo PARA SIEMPRE (medido), asi que se deniega — que es
+        # el default del gate — y se dice por que. Sin tty (pipes, CI) el
+        # input() de abajo funciona igual de bien desde un hilo: se sigue.
+        try:
+            from cognia.ux import selector as _sel
+            if _sel.hay_tty():
+                _aviso_degradado(
+                    "cli.permiso.hilo_sin_carril",
+                    f"{kind}: un hilo pidio permiso sin carril de fondo al que "
+                    f"delegar; se deniega (preguntar aca colgaria el hilo)")
+                return False
+        except Exception:
+            pass
+    return _preguntar_en_consola(kind, detalle)
+
+
+def _preguntar_en_consola(kind: str, detalle: str) -> bool:
+    """La pregunta EN la consola. Solo la llama quien es dueno de ella."""
     # Con tty real: confirmacion con flechas ([Si]/[No] + atajos s/n).
     # [...el resto del cuerpo de hoy, lineas 808-838, IDENTICO...]
```

**Lo que NO cambia:** el texto `[permiso] ... (s/n) >` (contrato con los pipes y el e2e), el
`default=False`, el DENY ante fallo del clasificador, y el parado del spinner antes de abrir el
selector.

---

### Hunk 4 — el keybinding de F2 (insertar después de la línea 6942, junto al de `tab`)

```diff
@@ cli.py:6942 @@
                 else:
                     buff.start_completion(select_first=True)

+            @_kb.add("f2")
+            def _ver_agentes(event):
+                # F2 NO abre la vista aca adentro: eso anidaria el event loop
+                # de Textual dentro del de prompt_toolkit. Sale con un
+                # centinela y quien mande la abre AFUERA. Medido: 0,52 ms de
+                # mediana desde la pulsacion hasta el handler (el brazo msvcrt
+                # daba 5,59 ms y 0,47 % de CPU en reposo contra 0,00 %).
+                # El centinela ARRASTRA la linea a medio escribir porque
+                # app.exit() descarta el buffer (medido).
+                event.app.exit(result=_FONDO_F2 + event.app.current_buffer.text)
+
```

---

### Hunk 5 — la cola de entrada y F2 en el prompt normal (reemplaza 6999-7018)

```diff
@@ cli.py:6999 @@
-    _inyectadas: list = []
+    # Misma cola de siempre + la del carril de fondo (lineas que el usuario
+    # tecleo mientras corria algo). Es la lista de MODULO para que el carril,
+    # que vive fuera de repl(), pueda encolar en ella.
+    _COLA_ENTRADA.clear()
+    _inyectadas: list = _COLA_ENTRADA

     if session is not None:
         def _get_input():
             if _inyectadas:
                 return _inyectadas.pop(0)
             # Aire antes del prompt: cada turno respira (estilo 2026-08-02).
             print()
-            line = session.prompt(_mensaje_prompt).strip()
+            _pre = ""
+            while True:
+                # patch_stdout(raw=True) tambien en el prompt normal: los
+                # monitores en background imprimen desde sus hilos y sin esto
+                # la linea del usuario se parte. raw=True es OBLIGATORIO (sin
+                # el, rich sale como '?[36m'). Con el prompt bloqueado y nadie
+                # imprimiendo, el coste medido es 0,00 % de CPU.
+                with patch_stdout(raw=True):
+                    line = (session.prompt(_mensaje_prompt, default=_pre) if _pre
+                            else session.prompt(_mensaje_prompt)).strip()
+                if not line.startswith(_FONDO_F2):
+                    break
+                # F2 sin corrida: la vista se abre igual y dice "sin corrida en
+                # curso". Se abre AFUERA del prompt (ya devolvio) y se vuelve
+                # con la linea a medio escribir intacta.
+                _pre = line[len(_FONDO_F2):]
+                _abrir_vista_agentes()
             while line.endswith("\\"):
                 continuation = session.prompt(
                     FormattedText([("class:flecha", "   ")])).strip()
                 line = line[:-1].rstrip() + " " + continuation
             return line
```

> El literal `session.prompt(_mensaje_prompt)` sigue presente: `tests/test_marco_prompt.py:150`
> lo exige tal cual. **Límite conocido:** F2 dentro de una continuación con `\` se trata como
> texto (el centinela entra en la línea). Es un caso de esquina; documentado, no cableado.

---

### Hunk 6 — despacho de `/workflow` al hilo (reemplaza 7089-7090)

```diff
@@ cli.py:7089 @@
         elif raw == "/workflow" or raw.startswith("/workflow "):
-            _slash_workflow(raw[len("/workflow"):])
+            # Al carril de fondo. _slash_workflow queda INTACTA (sigue siendo
+            # sincrona y sus tests la llaman derecho): lo unico que cambia es
+            # QUIEN la corre. Si no hay carril (sin PromptSession: pipes, CI),
+            # _lanzar_en_fondo devuelve False y se ejecuta inline, byte-identico
+            # a hoy.
+            if not _lanzar_en_fondo("workflow", _slash_workflow,
+                                    raw[len("/workflow"):]):
+                _slash_workflow(raw[len("/workflow"):])
```

**Si el usuario no aprieta nada, ¿qué ve?** Exactamente lo de hoy. El hilo llama a la MISMA
`_slash_workflow`, con el mismo `print_fn=_print_line`, así que las mismas líneas salen en el
mismo orden; el hilo principal está bloqueado en el prompt de espera, no imprime nada, y cuando
el hilo termina lo despierta y el REPL sigue. La única diferencia visible es el prompt de espera
(`workflow 12s  F2 agentes · Ctrl-C corta`) en lugar de una pantalla congelada — que es
justamente lo que se quería.

---

### Hunk 7 — despacho de `/hacer` al hilo (reemplaza 8315-8322)

```diff
@@ cli.py:8315 @@
             if _tarea:
                 _print_line("[detail]Iniciando agente...[/detail]")
-                _resp = _run_agent_task(ai, _tarea, _print_line)
-                if _resp:
-                    _show_response(_resp, _ACCENT, respuesta_final=True)
-                else:
-                    _print_line("[warn_cl]El agente no produjo respuesta.[/warn_cl]")
-                _session_log.append({"input": raw, "output": _resp, "elapsed": 0})
+                # El turno ENTERO (correr + mostrar + registrar) va al hilo: si
+                # el _show_response quedara en el principal, el resultado se
+                # imprimiria DESPUES del prompt siguiente y el orden de la
+                # pantalla cambiaria respecto de hoy.
+                def _turno_hacer(_t=_tarea, _raw=raw):
+                    _resp = _run_agent_task(ai, _t, _print_line)
+                    if _resp:
+                        _show_response(_resp, _ACCENT, respuesta_final=True)
+                    else:
+                        _print_line("[warn_cl]El agente no produjo respuesta.[/warn_cl]")
+                    _session_log.append({"input": _raw, "output": _resp,
+                                         "elapsed": 0})
+                if not _lanzar_en_fondo("hacer", _turno_hacer):
+                    _turno_hacer()
             else:
```

> El mismo envoltorio va en la rama `'/hacer retomar'` (8306-8313), que hoy duplica esas cuatro
> líneas y termina en `continue`.

---

### Hunk 8 — Ctrl-C en el prompt IDLE (reemplaza 7046-7048) — **OPCIONAL, decisión del dueño**

```diff
@@ cli.py:7046 @@
-        except (EOFError, KeyboardInterrupt):
+        except EOFError:
             print("\nHasta luego.")
             break
+        except KeyboardInterrupt:
+            # Hoy Ctrl-C en el prompt MATA el REPL entero. Con corridas en
+            # hilos eso pasa de molesto a destructivo, y ademas es incoherente:
+            # el fast-path (9770) y el articulado (9909) ya tratan Ctrl-C como
+            # "corta el turno, no la sesion". Dos seguidos con la linea vacia
+            # siguen saliendo, que es lo que hace todo REPL.
+            if _ctrlc_seguidos_idle():
+                print("\nHasta luego.")
+                break
+            _print_line("[info_dim]Ctrl-C otra vez para salir, o /salir."
+                        "[/info_dim]")
+            continue
```

Con un helper de módulo de 6 líneas (`_ctrlc_seguidos_idle()`: True si el anterior fue hace <2 s).
**Es un cambio de comportamiento observable**: va aparte para que se pueda aprobar o rechazar sin
tocar el resto.

---

### Hunk 9 — corte cooperativo del agente (insertar después de la línea 10673)

```diff
@@ cli.py:10673 @@
     while not _bon_ok and total_steps < AGENT_HARD_CAP:
+        # Corte pedido por el usuario (Ctrl-C en el prompt de espera o en la
+        # vista). El bucle del agente NO tenia ningun hook de cancelacion: sin
+        # esto, Ctrl-C sobre un /hacer en segundo plano no corta nada y el
+        # usuario mira un "corte pedido" que es mentira. Se comprueba ENTRE
+        # pasos: una tool larga (build, subprocess) termina antes de cerrar, y
+        # eso se dice en la linea que se imprime.
+        _c_corte = _corrida_viva()
+        if _c_corte is not None and _c_corte.cancelada:
+            _print_fn("[warn_cl]Corte pedido: el agente se detiene tras el "
+                      f"paso {total_steps}.[/warn_cl]")
+            break
```

---

### Fichero NUEVO — `cognia/tui/permiso.py`

Nadie lo tiene reservado (la otra tanda trabaja sobre `agentes.py`). Sin `.tcss` aparte a
propósito: es una pantalla de 40 líneas y un fichero de estilo más sería otra cosa que
sincronizar.

```python
"""
cognia/tui/permiso.py
=====================
El gate de permisos, preguntado DENTRO de la vista de agentes.

POR QUE EXISTE (medido, spike T4-b, 2026-08-18): con una App de Textual abierta,
el selector de prompt_toolkit (cognia/ux/selector.py) llamado desde el hilo de
la corrida NO VUELVE NUNCA — su dibujo se va al _PrintCapture de Textual (que lo
descarta) y sus teclas se las lleva el driver de Textual. El agente quedaba
colgado, mudo, sosteniendo una tool a medias.

La via que SI funciona (misma medicion): el hilo postea esta pantalla con
app.call_from_thread(app.push_screen, PantallaPermiso(...), callback) y se
bloquea en un threading.Event -> respuesta True en 1.229,5 ms, App sana, modos
de consola 503/7 al salir.

Se usa push_screen CON CALLBACK y no push_screen_wait: el wait exige un worker
de Textual (App.push_screen lanza NoActiveWorker si no lo hay) y quien pregunta
es un threading.Thread pelado.

Convencion del repo: comentarios en espanol sin acentos; solo stdlib + textual.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static


class PantallaPermiso(ModalScreen[bool]):
    """Si/No sobre la vista. El default es NO, igual que el gate de consola."""

    DEFAULT_CSS = """
    PantallaPermiso {
        align: center middle;
    }
    PantallaPermiso > Vertical {
        width: 70%;
        max-width: 90;
        height: auto;
        border: round $warning;
        background: $surface;
        padding: 1 2;
    }
    PantallaPermiso .titulo { color: $warning; text-style: bold; }
    PantallaPermiso .pista  { color: $text-muted; }
    """

    BINDINGS = [
        ("s", "responder(True)", "Si"),
        ("y", "responder(True)", "Si"),
        ("n", "responder(False)", "No"),
        ("escape", "responder(False)", "No"),
        ("enter", "responder(False)", "No (default)"),
    ]

    def __init__(self, kind: str, detalle: str) -> None:
        super().__init__()
        self._kind = kind or "accion"
        self._detalle = detalle or ""

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(f"PERMISO · {self._kind}", classes="titulo",
                         markup=False)
            # markup=False: el detalle es un comando del usuario y puede traer
            # corchetes; con markup rich se lo come o revienta el parser.
            yield Static(self._detalle[:400], markup=False)
            yield Static("s = ejecutar · n / esc / enter = NO", classes="pista",
                         markup=False)

    def action_responder(self, valor: bool) -> None:
        self.dismiss(bool(valor))
```

---

## 4. Las respuestas a las seis preguntas

| pregunta | respuesta | evidencia |
|---|---|---|
| **el workflow al hilo, con su control accesible** | Hunk 6/7 + `_Corrida`. El control por corrida ya existía: `workflows_adapter.cancelar_corrida/cancelar_agente/decirle`, y el `run_id` llega a la vista por el bus (`WorkflowInicio.run_id`), no por el envelope | `workflows_adapter.py:530-556` |
| **escuchar el teclado sin quemar CPU** | `session.prompt()` bloquea de verdad: **0,00 % de CPU en 30 s** (0,0 s de `process_time`). msvcrt costaba 0,47 % (sleep 10 ms) o 41,6 % (sleep 0) | spike T4 |
| **F2 abre la vista, esc vuelve** | Sí, 7/7 escenarios. Modos `503 → 512 → 503`, `out=7` estable, cursor visible, `?1049h/l` **1/1**, `ESC[3J` **0** | spike T4 + M6/M7 |
| **Ctrl-C en la vista corta la CORRIDA, no el REPL** | Sí. Llega como tecla (`in_mode=512`, sin `ENABLE_PROCESSED_INPUT` → conhost no genera `CTRL_C_EVENT`), la subclase la captura y llama a `cancelar_corrida("")`. Para `/hacer` hace falta el Hunk 9 | M7 |
| **si el usuario no aprieta nada** | Idéntico a hoy: mismas llamadas, mismo `print_fn`, mismo orden. El hilo principal no imprime; el resultado lo pinta el hilo que lo produjo. La única diferencia es el prompt de espera con el reloj | por construcción (Hunks 6/7) |
| **`_confirmar_accion` con la vista abierta: ¿se cuelga?** | **SE COLGABA, para siempre, y también con solo el prompt abierto.** Con el Hunk 3 no: modal en la vista (1.229,5 ms) o el principal contesta (1.032,9 ms); si no hay a quién delegar, DENY con aviso — nunca un cuelgue | M5, M6 |

---

## 5. Tests que hay que escribir

Fichero nuevo `tests/test_repl_carril_fondo.py` salvo donde se diga. Los marcados **[fuente]**
son regresión a nivel de fuente (mismo criterio que `test_fast_path_guard.py`: `repl()` no se
puede invocar de punta a punta); los demás son funcionales de verdad, con dobles.

**Funcionales del carril (sin consola, sin modelo):**

1. `test_sin_sesion_el_camino_es_inline` — `_sesion_prompt = None` → `_lanzar_en_fondo` devuelve
   `False` y **no** crea ningún hilo. Es el guard que garantiza "pipes y CI intactos".
2. `test_una_corrida_por_vez` — con una `_Corrida` viva, un segundo `_lanzar_en_fondo` avisa y
   devuelve `True` sin lanzar hilo (assert sobre `threading.active_count()`).
3. `test_la_excepcion_del_hilo_se_ve` — `fn` que lanza → línea de error impresa **y**
   `_aviso_degradado("cli.fondo", ...)` emitido. Un hilo que muere mudo es el fallo de siempre.
4. `test_el_spinner_se_apaga_y_se_restaura` — `COGNIA_SPINNER` vale `"0"` durante `fn` y vuelve a
   su valor previo (incluido "no existía") después, también si `fn` revienta.
5. `test_la_linea_tecleada_se_encola_no_se_ejecuta` — un `session` falso que devuelve `"/ayuda"`
   y después `_FONDO_FIN`: `_COLA_ENTRADA == ["/ayuda"]` y `/ayuda` no corrió.

**Funcionales del gate (el bug que se arregla):**

6. `test_el_hilo_no_pregunta_en_consola` — `_confirmar_accion` desde un hilo con
   `_preguntar_en_consola` monkeypatcheado a un `assert False`: no lo llama.
7. `test_el_hilo_sin_carril_deniega_con_tty` — sin corrida ni vista y con `hay_tty→True`:
   devuelve `False` y emite `cli.permiso.hilo_sin_carril`. **Sin tty devuelve por el `input()` de
   siempre** (los pipes y el e2e no cambian).
8. `test_el_principal_contesta_el_pedido` — hilo pide, se simula el despertar, `_atender_permiso`
   responde `True`, el hilo lo recibe y `c.pedido` queda en `None`.
9. `test_permiso_timeout_deniega` — con `_ESPERA_PERMISO_S` bajado: devuelve `False` y avisa. Que
   el default sea DENY es la mitad de la seguridad del gate.
10. `test_permiso_en_vista_muerta_devuelve_none` — App con `is_running=False` a mitad de espera →
    `None` (para que el enrutador reintente por el prompt), no un cuelgue de 600 s.
11. `test_confirmar_no_regresa_en_el_hilo_principal` — desde el principal el camino es
    **byte-idéntico** al de hoy (mismo `_preguntar_en_consola`, mismo texto `[permiso] ... (s/n) >`).

**De la vista:**

12. `test_la_subclase_hereda_el_css_absoluto` — `_vista_con_corte(PantallaAgentes).CSS_PATH`
    apunta a un fichero que **existe** (es el bug que un `CSS_PATH` relativo introduce en una
    subclase definida en otro módulo).
13. `test_ctrlc_en_la_vista_pide_el_corte` — la acción llama a
    `workflows_adapter.cancelar_corrida` (doble) y **no** lanza `KeyboardInterrupt`.
14. `test_sin_textual_la_vista_avisa_y_no_rompe` — import de `cognia.tui.agentes` forzado a
    fallar → línea visible y el REPL sigue.
15. `tests/test_tui_permiso.py::test_modal_devuelve_false_por_defecto` — con
    `App.run_test()`: `enter` y `escape` dan `False`, `s` da `True`.

**[fuente] en `tests/test_repl_carril_fondo.py`:**

16. `test_el_prompt_va_envuelto_en_patch_stdout_raw` — `"patch_stdout(raw=True)"` aparece en
    `getsource(repl)` **y** en `getsource(_esperar_corrida)`, y `"patch_stdout()"` (sin `raw`) no
    aparece en ningún lado. Es el guard del hallazgo con dientes: sin `raw=True` el prompt del
    dueño pierde todos los colores.
17. `test_f2_no_abre_la_app_dentro_del_keybinding` — en `getsource(repl)`, la posición de
    `@_kb.add("f2")` es anterior a `event.app.exit(result=_FONDO_F2` y `_abrir_vista_agentes`
    **no** aparece dentro del cuerpo del keybinding. Anidar los dos event loops es el modo de
    fallo que hay que dejar cerrado.
18. `test_el_despacho_de_workflow_y_hacer_tiene_fallback_inline` — las dos ramas conservan la
    llamada directa bajo `if not _lanzar_en_fondo(...)`.

**E2E manual (va al guion del dueño, punto 7):** no se automatiza — requiere Windows Terminal.

### Los ficheros que hacen `inspect.getsource` sobre el CLI: cuáles se rompen

Son **9** (fuera de los worktrees). Con el parche tal como está escrito, **se rompen 0**, pero
cuatro imponen literales que el parche NO puede tocar:

| fichero | qué mira | ¿se rompe? | el literal que hay que respetar |
|---|---|---|---|
| `tests/test_cli_input_bom.py:73` | `getsource(cli.repl)` | **no** | `_strip_input_bom(_get_input())` — intacto |
| `tests/test_marco_prompt.py:150` | `getsource(C.repl)` | **no, pero al filo** | exige `session.prompt(_mensaje_prompt)` **con el paréntesis de cierre**: el Hunk 5 conserva esa llamada en la rama `else` justo por esto. Si alguien la "simplifica" a una sola llamada con `default=_pre`, **este test cae** |
| `tests/test_repl_sin_consola.py` (5 asserts) | `getsource(C.repl)` | **no** | `try:` antes de `session = PromptSession`, `session = None`, `input(_g() + "cognia> "`, `Sin consola interactiva`, `autocompletado`, `session.prompt(`, `line.endswith("\\")` — todos intactos |
| `tests/test_effort_levels.py:110` | `getsource(cli_mod.repl)` | **no** | no se toca el fast-path |
| `tests/test_fast_path_guard.py` (6 tests) | `getsource(cli_mod.repl)` | **no** | son checks de **orden** dentro del fast-path (`i_guard < i_cascade`); los hunks están todos antes o fuera |
| `tests/test_cli_analisis_honesto.py:102` | `getsource(cli)` módulo | no | substring `raw in ("/ayuda", "/help")` |
| `tests/test_doctor_packaging.py:25` | `getsource(cli)` módulo | no | `cognia_doctor.py` no aparece |
| `tests/test_identity_prompt.py:45` | `getsource(cli)` módulo | no | substring |
| `tests/test_agent_step_budget.py:179` | `getsource(cli)` módulo | no | substring |

**Fuera de `getsource`, dos tests sí dependen del despacho** y por eso `_slash_workflow` se deja
intacta: `tests/test_workflow_texto_pagado.py:50,67` la llama **directo**
(`C._slash_workflow("uno; dos")`) y verifica lo impreso. Si el parche moviera el cuerpo al hilo en
vez del despacho, esos dos caerían. `tests/test_cli_cableado.py:79` solo exige que `/workflow`
salga en `/ayuda todo` (sale del dict, que no se toca).

---

## 6. El criterio de corte

Todo lo de arriba se midió bajo **un ConPTY que armé yo**: el mismo mecanismo que usa Windows
Terminal y fiel para modos de consola, VT y entrega de teclas, pero **no fiel para `CTRL_C_EVENT`
en modo cocido**, y con una App de Textual sintética, no con `PantallaAgentes`. Lo que decide es
esto, en la consola del dueño, en este orden:

**G0 (precondición, ya escrita):** correr `manual.py` del spike T4 → PASA. Si el terminal no
vuelve entero con la App sintética, nada de lo de abajo importa.

**G1 — la corrida no bloquea el teclado.** `/workflow a; b; c` real. A los ~5 s: F2 → se ven los
agentes → `esc`. Pasa si: (a) vuelve el prompt, (b) **el scrollback de antes sigue arriba**,
(c) `dir` se ve normal, (d) la línea que estaba tecleando volvió intacta, (e) al terminar, el
resultado impreso es **el mismo texto que hoy** (comparar con una corrida `COGNIA_SIN_FONDO=1`).

**G2 — Ctrl-C corta la corrida, no el REPL.** Ctrl-C dentro de la vista y Ctrl-C en el prompt de
espera. Pasa si en los dos casos el REPL sigue vivo y el envelope del workflow vuelve con
`cancelados >= 1`.

**G3 — EL CRITERIO DE CORTE DE VERDAD.** `/hacer <algo que dispare el gate>` (p. ej. una tarea que
ejecute un comando de shell), con la vista **abierta** en el momento en que el agente pide
permiso. Pasa si el modal aparece y la respuesta llega al agente en < 5 s. **Si G3 falla —el
modal no aparece, o aparece y la respuesta no vuelve— se va a Plan B**, porque ese fallo no es
cosmético: cuelga al agente en medio de una tarea y el usuario no tiene forma de enterarse. El
mismo `/hacer` con la vista **cerrada** (permiso contestado en el prompt de espera) es la segunda
mitad de G3.

**G4 — la pantalla no se ensucia.** Un `/hacer` de ≥ 3 minutos con el prompt de espera abierto.
Pasa si al terminar **no hay líneas `pensando…` repetidas** en el scrollback (verifica que
`COGNIA_SPINNER=0` surtió efecto: sin él son ~4,7 líneas por segundo, medido).

**Qué NO decide:** la latencia de F2 ni la CPU. Ya están medidas y el margen es enorme
(0,52 ms; 0,00 %).

### Plan B, si G3 falla

La vista pasa a ser **un proceso aparte** (`python -m cognia.tui.agentes <run_id>`) y el gate de
permisos deja de tener el problema por construcción: la consola del REPL nunca se comparte. Cuesta
las ~150-200 líneas de IPC ya estimadas, y **el resto de este plan sigue en pie tal cual**: el
hilo, el prompt de espera, `_despertar_prompt`, la cola de entrada y el corte cooperativo no
dependen de que la vista esté en el mismo proceso. Lo único que cambia es `_abrir_vista_agentes`
(lanza el subproceso y espera a que muera) y `_preguntar_desde_hilo`, que pierde la rama del
modal y se queda con la del prompt — **que es la que ya está medida en 1.032,9 ms**. El sink de
eventos tendría que ir por socket o por un JSONL que la vista sigue con tail; el stream de tokens
se pierde salvo que se cablee IPC.

---

## 7. Lo honesto que queda declarado

* Todo se midió con **una App de Textual sintética**, no con `PantallaAgentes` (que otra tanda
  está escribiendo). Lo que se midió de ella es que su `CSS_PATH` relativo **rompe** cualquier
  subclase definida fuera de `cognia/tui/` — de ahí el `CSS_PATH` absoluto del Hunk 2.
* **Nada se probó contra el modelo real ni contra :8080.** El comportamiento con un workflow de
  verdad (3 pasos, ~70 s cada uno) es G1.
* El corte de `/hacer` es **cooperativo entre pasos**: una tool larga no se interrumpe. Está dicho
  en la línea que se imprime, no escondido.
* `_despertar_prompt` usa `Application.loop`, que es atributo público pero no documentado como
  API estable de prompt_toolkit (3.0.52). Si desaparece, el síntoma es un prompt que no despierta
  solo — visible al instante en G1, y el fallback es que el usuario apriete Enter.
* El `refresh_interval=1.0` del prompt de espera cuesta ~1 % de un core **mientras hay corrida**
  (extrapolado del 2,24 % medido a 0,5 s). Es el precio del reloj; se quita poniéndolo en `None`.
* `_COLA_ENTRADA` sobrevive entre corridas dentro del mismo proceso: se limpia al arrancar
  `repl()` (Hunk 5) para que un `repl()` llamado dos veces no herede líneas viejas.
