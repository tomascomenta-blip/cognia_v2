"""
cognia/ux/selector.py
=====================
Seleccion interactiva con flechas para el REPL (prompt_toolkit puro).

POR QUE existe: hasta 2026-08 toda seleccion del CLI era "lista impresa +
teclear texto" (/tema, /esfuerzo, /modo-permiso) y las confirmaciones eran
input() s/n. prompt_toolkit ya es dependencia DURA del paquete
(pyproject.toml: prompt_toolkit>=3.0), asi que un menu con flechas no suma
dependencias nuevas — questionary/InquirerPy NO se agregan a proposito
(InquirerPy esta muerta desde 2022 y questionary seria una dep extra para
lo que aca son ~60 lineas de Application).

API congelada (los callers de cli.py los cablea el orquestador aparte):
    hay_tty()                        -> bool
    elegir(titulo, opciones, ...)    -> valor elegido | None (Esc/Ctrl-C)
    confirmar(pregunta, ...)         -> bool
    elegir_varias(titulo, opc, ...)  -> [valores] | None (Esc/Ctrl-C)
    texto_libre(pregunta, ...)       -> str | None (Esc/Ctrl-C)

Las dos ultimas (2026-08-28) existen para las ENCUESTAS del mejorador de
prompts: hasta ahora el CLI solo sabia preguntar "una de estas" y "si o no",
y una encuesta que detecta que le falta informacion necesita ademas "varias
de estas" y "escribilo vos". Comparten el contrato de arriba entero — misma
degradacion sin tty, misma inyeccion de input_fn para tests, mismo aviso
visible al degradar. En las dos, None significa CANCELO y "" / [] significan
CONTESTO QUE NADA: quien las consume decide distinto en cada caso.

REGLA CRITICA (no negociable): JAMAS abrir el selector con un rich
Live/status activo. rich.Live y la Application de prompt_toolkit toman
control del cursor A LA VEZ y el terminal queda corrupto; el caller DEBE
parar su spinner/status ANTES de llamar a elegir()/confirmar(). (Mismo
motivo por el que el Renderer de ux/renderer.py para su status antes de
imprimir lineas.)

Contrato de degradacion (mismo espiritu que console/surveys.py):
- input_fn inyectada  -> SIEMPRE modo texto plano (tests deterministas,
  jamas prompt_toolkit): asi el camino de tests no depende de un tty.
- sin tty (pipes, CI, Windows sin consola Win32) -> lista numerada por
  print() + input(), aceptando numero o el valor/etiqueta textual.
- La Application interactiva se construye LAZY y solo con tty real: en CI
  no se instancia nada interactivo (no hay tty que la sostenga).
- Entrada invalida en el fallback: reintento acotado (3) y despues None,
  nunca un loop infinito colgando un pipe.
"""

from __future__ import annotations

import sys

# Reintentos del fallback texto antes de rendirse (mismo tope que surveys.py:
# un pipe con basura no debe colgar el turno).
_MAX_REINTENTOS = 3


def hay_tty() -> bool:
    """True si stdin Y stdout son tty reales y (en Windows) hay consola Win32.

    POR QUE ambos lados: stdout puede ser tty con stdin redirigido (pipes) y
    prompt_toolkit revienta con 'Stdin is not a terminal' — chequear solo un
    lado no basta. POR QUE el chequeo Win32 extra: hay procesos donde isatty()
    da True pero no existe consola real (subprocess, algunos IDEs) y
    prompt_toolkit muere con NoConsoleScreenBufferError al crear su salida;
    es el MISMO guard que la PromptSession del REPL (cli.py ~6569, que atrapa
    esa excepcion y cae a input() plano).
    """
    try:
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            return False
    except Exception:
        # un stdin/stdout reemplazado sin isatty() cuenta como "sin tty"
        return False
    if sys.platform == "win32":
        try:
            # create_output() toca la consola Win32 real: si no hay buffer de
            # consola lanza NoConsoleScreenBufferError. Sin efectos visibles.
            from prompt_toolkit.output.defaults import create_output
            create_output()
        except Exception:
            return False
    return True


_AVISOS_STDERR: set = set()


def _avisar(motivo: str) -> None:
    """Degradacion VISIBLE por _aviso_degradado('selector', motivo) del CLI;
    sin cli cargado (tests, scripts) sale por stderr una vez por motivo.
    Jamas se calla (regla del repo): que el selector caiga a sus literales
    de siempre no puede verse igual que "el registro no existe"."""
    try:
        _cli = sys.modules.get("cognia.cli")
        if _cli is not None:
            _cli._aviso_degradado("selector", motivo)
            return
    except Exception:
        pass
    if motivo in _AVISOS_STDERR:
        return
    _AVISOS_STDERR.add(motivo)
    try:
        print(f"  degradado — selector: {motivo}", file=sys.stderr)
    except Exception:
        pass


def _puntero() -> str:
    """El glifo de la fila activa: 'menu.selector' del registro de estilos
    (P5; /estilo menu.selector glifo >), que ya cae a '>' si stdout no
    codifica el Unicode (cp1252 mordio antes). Si el registro falla, el
    literal de siempre con la misma prueba de encoding, y se avisa."""
    try:
        from cognia.ux import aspecto as _A
        return _A.glifo("menu.selector") or ">"
    except Exception as exc:
        _avisar(f"puntero desde aspecto fallo: {type(exc).__name__}: {exc}")
    enc = getattr(sys.stdout, "encoding", "") or "utf-8"
    try:
        "❯".encode(enc)   # ❯
        return "❯"
    except Exception:
        return ">"


# Los style strings crudos que este modulo usaba como literales (titulo en
# negrita, fila activa en video inverso, descripcion tenue en ANSI de 16
# colores para adaptarse al tema del terminal). Son el respaldo si el
# registro no responde; con el registro sin override son IDENTICOS.
_CLASES_DEFECTO = {"titulo": "bold", "activo": "reverse",
                   "descripcion": "fg:ansibrightblack"}


def _clases() -> dict:
    """{'titulo', 'activo', 'descripcion'} -> style string de prompt_toolkit,
    desde 'menu.selector' del registro (P5). Se lee UNA vez al abrir cada
    selector: el menu vive medio segundo, no necesita hot reload."""
    try:
        from cognia.ux import aspecto as _A
        c = dict(_CLASES_DEFECTO)
        c.update(_A.clases_selector())
        return c
    except Exception as exc:
        _avisar(f"clases desde aspecto fallaron: {type(exc).__name__}: {exc}")
        return dict(_CLASES_DEFECTO)


# ---------------------------------------------------------------------------
# elegir(): menu de una eleccion
# ---------------------------------------------------------------------------

def elegir(titulo: str, opciones: list, default: int = 0, input_fn=None):
    """Menu de UNA eleccion. Devuelve el valor elegido o None (cancelado).

    opciones: lista de tuplas (valor, etiqueta, descripcion_corta). Con tty
    real y sin input_fn: mini Application de prompt_toolkit (flechas
    arriba/abajo + Enter; Esc/Ctrl-C -> None; sin pantalla completa, tope
    len(opciones)+2 lineas, fila activa en video inverso con puntero,
    descripcion tenue a la derecha). Con input_fn o sin tty: lista numerada
    por print() + input() aceptando numero, valor o etiqueta; vacio ->
    default; invalido -> reintento acotado y despues None.

    Casos borde: opciones vacias -> None; UNA sola opcion -> su valor
    directo sin preguntar (no hay nada que elegir).

    REGLA CRITICA: no llamar con un rich Live/status activo (ver docstring
    del modulo) — el caller para su spinner primero.
    """
    opciones = list(opciones or [])
    if not opciones:
        return None
    if not (0 <= default < len(opciones)):
        default = 0
    if len(opciones) == 1:
        return opciones[0][0]
    if input_fn is not None or not hay_tty():
        return _elegir_texto(titulo, opciones, default, input_fn or input)
    try:
        return _elegir_flechas(titulo, opciones, default)
    except Exception:
        # Terminal raro (TERM exotico, consola a medias): degradar al texto,
        # jamas romper el turno por un adorno interactivo.
        return _elegir_texto(titulo, opciones, default, input)


def _elegir_texto(titulo, opciones, default, input_fn):
    """Fallback sin tty: lista numerada + input(). Acepta numero o texto."""
    print(titulo)
    for i, (_valor, etiqueta, desc) in enumerate(opciones, start=1):
        marca = "*" if (i - 1) == default else " "
        linea = f" {marca}{i}) {etiqueta}"
        if desc:
            linea += f"  - {desc}"
        print(linea)
    for _ in range(_MAX_REINTENTOS):
        try:
            raw = input_fn(f"Eleccion (1-{len(opciones)}, Enter={default + 1}): ")
        except (EOFError, KeyboardInterrupt, StopIteration):
            return None
        raw = (raw or "").strip()
        if not raw:
            return opciones[default][0]
        if raw.isdigit():
            idx = int(raw)
            if 1 <= idx <= len(opciones):
                return opciones[idx - 1][0]
        else:
            # valor textual: matchea valor o etiqueta, case-insensitive
            for valor, etiqueta, _desc in opciones:
                if raw.lower() in (str(valor).lower(), str(etiqueta).lower()):
                    return valor
        print(f"Entrada invalida. Proba un numero 1-{len(opciones)} o el nombre de la opcion.")
    return None


def _elegir_flechas(titulo, opciones, default):
    """Camino interactivo: mini Application (LAZY, solo se importa con tty)."""
    from prompt_toolkit.application import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import HSplit, Layout, Window
    from prompt_toolkit.layout.controls import FormattedTextControl

    idx = [default]
    puntero = _puntero()
    clases = _clases()

    def _fragmentos():
        frags = [(clases["titulo"], titulo + "\n")]
        for i, (_valor, etiqueta, desc) in enumerate(opciones):
            if i == idx[0]:
                frags.append((clases["activo"], f" {puntero} {etiqueta} "))
            else:
                frags.append(("", f"   {etiqueta} "))
            if desc:
                # por defecto ansibrightblack ~ 'dim': se adapta al tema del
                # terminal (16 colores ANSI, nunca hex fijo)
                frags.append((clases["descripcion"], f"  {desc}"))
            frags.append(("", "\n"))
        return frags

    kb = KeyBindings()

    @kb.add("up")
    def _arriba(event):
        idx[0] = (idx[0] - 1) % len(opciones)

    @kb.add("down")
    def _abajo(event):
        idx[0] = (idx[0] + 1) % len(opciones)

    @kb.add("enter")
    def _aceptar(event):
        event.app.exit(result=opciones[idx[0]][0])

    # eager: que Esc no espere la secuencia de escape compuesta
    @kb.add("escape", eager=True)
    @kb.add("c-c")
    def _cancelar(event):
        event.app.exit(result=None)

    ventana = Window(
        content=FormattedTextControl(_fragmentos, focusable=True),
        # titulo + una fila por opcion; queda bajo el tope len(opciones)+2
        height=len(opciones) + 1,
        always_hide_cursor=True,
    )
    app = Application(
        layout=Layout(HSplit([ventana])),
        key_bindings=kb,
        full_screen=False,       # inline: no toma la pantalla entera
        erase_when_done=True,    # el menu desaparece; el caller imprime el resultado
        mouse_support=False,
    )
    return app.run()


# ---------------------------------------------------------------------------
# confirmar(): si/no
# ---------------------------------------------------------------------------

def confirmar(pregunta: str, default: bool = True, input_fn=None) -> bool:
    """Confirmacion si/no. Con tty: flechas izq/der entre [Si] [No] + Enter,
    atajos 's'/'n'. Sin tty (o con input_fn): input 's/n' como hoy —
    s/si/y/yes -> True, vacio -> default, resto -> False.

    Esc/Ctrl-C/EOF -> False SIEMPRE (deny-by-default: esta funcion respalda
    el gate de permisos y cancelar jamas puede significar "ejecutar").

    REGLA CRITICA: no llamar con un rich Live/status activo (ver docstring
    del modulo) — el caller para su spinner primero.
    """
    if input_fn is not None or not hay_tty():
        return _confirmar_texto(pregunta, default, input_fn or input)
    try:
        return _confirmar_flechas(pregunta, default)
    except Exception:
        # degradar al texto, jamas romper el turno
        return _confirmar_texto(pregunta, default, input)


def _confirmar_texto(pregunta, default, input_fn) -> bool:
    try:
        raw = input_fn(f"{pregunta} (s/n) > ")
    except (EOFError, KeyboardInterrupt, StopIteration):
        return False
    raw = (raw or "").strip().lower()
    if not raw:
        return default
    return raw in ("s", "si", "y", "yes")


def _confirmar_flechas(pregunta, default) -> bool:
    """Camino interactivo [Si] [No] (LAZY, solo se importa con tty)."""
    from prompt_toolkit.application import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import HSplit, Layout, Window
    from prompt_toolkit.layout.controls import FormattedTextControl

    sel = [0 if default else 1]   # 0 = Si, 1 = No
    clases = _clases()

    def _fragmentos():
        frags = [(clases["titulo"], pregunta + "  ")]
        for i, texto in enumerate(("Si", "No")):
            frags.append((clases["activo"] if i == sel[0] else "", f" [{texto}] "))
            frags.append(("", " "))
        return frags

    kb = KeyBindings()

    @kb.add("left")
    @kb.add("right")
    def _mover(event):
        # dos opciones: cualquier flecha lateral alterna
        sel[0] = 1 - sel[0]

    @kb.add("s")
    @kb.add("y")
    def _si(event):
        event.app.exit(result=True)

    @kb.add("n")
    def _no(event):
        event.app.exit(result=False)

    @kb.add("enter")
    def _aceptar(event):
        event.app.exit(result=(sel[0] == 0))

    @kb.add("escape", eager=True)
    @kb.add("c-c")
    def _cancelar(event):
        event.app.exit(result=False)

    ventana = Window(
        content=FormattedTextControl(_fragmentos, focusable=True),
        height=1,
        always_hide_cursor=True,
    )
    app = Application(
        layout=Layout(HSplit([ventana])),
        key_bindings=kb,
        full_screen=False,
        erase_when_done=True,
        mouse_support=False,
    )
    return bool(app.run())


# ---------------------------------------------------------------------------
# elegir_varias(): menu de seleccion MULTIPLE
# ---------------------------------------------------------------------------

def elegir_varias(titulo: str, opciones: list, marcadas=None,
                  input_fn=None, permitir_vacio: bool = True):
    """Menu de seleccion MULTIPLE. Devuelve la lista de valores marcados,
    o None si el usuario cancelo (Esc/Ctrl-C).

    OJO con la diferencia entre [] y None, que aca NO es cosmetica: [] es
    "el usuario miro las opciones y no quiere ninguna" (una respuesta) y
    None es "el usuario se fue sin contestar" (no hay respuesta). La
    encuesta que consume esto las trata distinto: la primera se incorpora
    al prompt como restriccion explicita, la segunda se omite. Confundirlas
    seria inventarle al usuario una decision que no tomo, que es justo el
    fallo que el mejorador de prompts tiene prohibido cometer.

    opciones: lista de tuplas (valor, etiqueta, descripcion_corta), igual
    que elegir(). `marcadas` es una lista de valores premarcados.

    Con tty real y sin input_fn: Application de prompt_toolkit — flechas
    para moverse, ESPACIO para marcar/desmarcar, Enter para confirmar,
    'a' marca todas, 'n' ninguna, Esc/Ctrl-C cancela. Sin tty o con
    input_fn: lista numerada + input() aceptando numeros separados por coma
    o espacio ("1,3" / "1 3"), nombres de opcion, "todas" o "ninguna".

    REGLA CRITICA: no llamar con un rich Live/status activo (ver docstring
    del modulo).
    """
    opciones = list(opciones or [])
    if not opciones:
        return None
    premarcadas = {v for v in (marcadas or [])}
    estado = [v in premarcadas for v, _e, _d in opciones]
    if input_fn is not None or not hay_tty():
        return _varias_texto(titulo, opciones, estado, input_fn or input,
                             permitir_vacio)
    try:
        return _varias_flechas(titulo, opciones, estado, permitir_vacio)
    except Exception as exc:
        _avisar(f"seleccion multiple interactiva fallo "
                f"({type(exc).__name__}: {exc}): caigo a texto")
        return _varias_texto(titulo, opciones, estado, input, permitir_vacio)


def _varias_texto(titulo, opciones, estado, input_fn, permitir_vacio):
    """Fallback sin tty: lista numerada + input() con numeros multiples."""
    print(titulo)
    print("  (varias: numeros separados por coma; 'todas'; 'ninguna'; "
          "Enter deja lo marcado)")
    for i, (_valor, etiqueta, desc) in enumerate(opciones, start=1):
        marca = "x" if estado[i - 1] else " "
        linea = f"  [{marca}] {i}) {etiqueta}"
        if desc:
            linea += f"  - {desc}"
        print(linea)
    for _ in range(_MAX_REINTENTOS):
        try:
            raw = input_fn(f"Eleccion (1-{len(opciones)}, varias): ")
        except (EOFError, KeyboardInterrupt, StopIteration):
            return None
        raw = (raw or "").strip()
        if not raw:
            elegidas = [v for (v, _e, _d), on in zip(opciones, estado) if on]
            if elegidas or permitir_vacio:
                return elegidas
            print("Hay que marcar al menos una.")
            continue
        bajo = raw.lower()
        if bajo in ("todas", "todo", "all"):
            return [v for v, _e, _d in opciones]
        if bajo in ("ninguna", "nada", "none"):
            if permitir_vacio:
                return []
            # "ninguna" cuando hace falta al menos una NO es cancelar: es una
            # respuesta que no vale. Devolver None aca mezclaba las dos cosas
            # que este modulo existe para separar, y quien consume la encuesta
            # habria anotado "el usuario se fue" sobre alguien que sigue ahi.
            print("Hay que marcar al menos una.")
            continue
        elegidas, malo = [], False
        for trozo in raw.replace(",", " ").split():
            t = trozo.strip()
            if t.isdigit() and 1 <= int(t) <= len(opciones):
                valor = opciones[int(t) - 1][0]
                if valor not in elegidas:
                    elegidas.append(valor)
                continue
            hallado = False
            for valor, etiqueta, _desc in opciones:
                if t.lower() in (str(valor).lower(), str(etiqueta).lower()):
                    if valor not in elegidas:
                        elegidas.append(valor)
                    hallado = True
                    break
            if not hallado:
                malo = True
                break
        if malo:
            print(f"Entrada invalida. Numeros 1-{len(opciones)} separados "
                  f"por coma, o los nombres de las opciones.")
            continue
        if elegidas or permitir_vacio:
            return elegidas
        print("Hay que marcar al menos una.")
    return None


def _varias_flechas(titulo, opciones, estado, permitir_vacio):
    """Camino interactivo (LAZY, solo con tty): espacio marca, Enter cierra."""
    from prompt_toolkit.application import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import HSplit, Layout, Window
    from prompt_toolkit.layout.controls import FormattedTextControl

    idx = [0]
    puntero = _puntero()
    clases = _clases()
    # Las cajas se prueban contra el encoding de stdout igual que el puntero:
    # cp1252 no tiene U+2611 y un menu que sale como '?' no se puede leer.
    enc = getattr(sys.stdout, "encoding", "") or "utf-8"
    try:
        "☑☐".encode(enc)
        caja_on, caja_off = "☑", "☐"
    except Exception:
        caja_on, caja_off = "[x]", "[ ]"

    def _fragmentos():
        frags = [(clases["titulo"], titulo + "\n"),
                 (clases["descripcion"],
                  "  espacio marca - a todas - n ninguna - Enter confirma\n")]
        for i, (_valor, etiqueta, desc) in enumerate(opciones):
            caja = caja_on if estado[i] else caja_off
            if i == idx[0]:
                frags.append((clases["activo"], f" {puntero} {caja} {etiqueta} "))
            else:
                frags.append(("", f"   {caja} {etiqueta} "))
            if desc:
                frags.append((clases["descripcion"], f"  {desc}"))
            frags.append(("", "\n"))
        return frags

    kb = KeyBindings()

    @kb.add("up")
    def _arriba(event):
        idx[0] = (idx[0] - 1) % len(opciones)

    @kb.add("down")
    def _abajo(event):
        idx[0] = (idx[0] + 1) % len(opciones)

    @kb.add("space")
    def _marcar(event):
        estado[idx[0]] = not estado[idx[0]]

    @kb.add("a")
    def _todas(event):
        for i in range(len(estado)):
            estado[i] = True

    @kb.add("n")
    def _ninguna(event):
        for i in range(len(estado)):
            estado[i] = False

    @kb.add("enter")
    def _aceptar(event):
        elegidas = [v for (v, _e, _d), on in zip(opciones, estado) if on]
        if not elegidas and not permitir_vacio:
            return          # Enter no cierra si hace falta al menos una
        event.app.exit(result=elegidas)

    @kb.add("escape", eager=True)
    @kb.add("c-c")
    def _cancelar(event):
        event.app.exit(result=None)

    ventana = Window(
        content=FormattedTextControl(_fragmentos, focusable=True),
        height=len(opciones) + 2,      # titulo + ayuda + una fila por opcion
        always_hide_cursor=True,
    )
    app = Application(
        layout=Layout(HSplit([ventana])),
        key_bindings=kb,
        full_screen=False,
        erase_when_done=True,
        mouse_support=False,
    )
    return app.run()


# ---------------------------------------------------------------------------
# texto_libre(): respuesta abierta
# ---------------------------------------------------------------------------

def texto_libre(pregunta: str, default: str = "", pista: str = "",
                input_fn=None, multilinea: bool = False):
    """Pregunta de respuesta ABIERTA. Devuelve el texto, o None si cancelo.

    Devuelve "" cuando el usuario da Enter sin escribir y no hay default:
    igual que en elegir_varias(), "" (no quiso decir nada) y None (se fue)
    son respuestas distintas para quien consume la encuesta.

    Con tty y sin input_fn usa una PromptSession de prompt_toolkit, que es
    lo que ya usa el REPL: da edicion de linea y default precargado y
    EDITABLE (importa: una pregunta con sugerencia que no se puede corregir
    empuja a aceptarla tal cual). Sin tty cae a input() plano.

    multilinea=True cierra con Esc-Enter en vez de Enter, para las
    respuestas largas (una descripcion de estilo visual, por ejemplo).
    """
    etiqueta = pregunta.rstrip()
    if pista:
        etiqueta += f"  ({pista})"
    if input_fn is not None or not hay_tty():
        return _texto_plano(etiqueta, default, input_fn or input)
    try:
        from prompt_toolkit import PromptSession
        sesion = PromptSession()
        raw = sesion.prompt(etiqueta + "\n> ", default=default or "",
                            multiline=multilinea)
        return (raw or "").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    except Exception as exc:
        _avisar(f"prompt de texto libre fallo "
                f"({type(exc).__name__}: {exc}): caigo a input()")
        return _texto_plano(etiqueta, default, input)


def _texto_plano(etiqueta, default, input_fn):
    sufijo = f" [{default}]" if default else ""
    try:
        raw = input_fn(f"{etiqueta}{sufijo}: ")
    except (EOFError, KeyboardInterrupt, StopIteration):
        return None
    raw = (raw or "").strip()
    return raw if raw else (default or "")
