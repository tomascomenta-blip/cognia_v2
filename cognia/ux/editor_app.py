# -*- coding: utf-8 -*-
"""
cognia/ux/editor_app.py -- la Application FULL-SCREEN del editor /estilo
(paso P11 del sistema de estilos por elemento, 2026-08-24).

QUE: `EditorApp(modelo)` es la capa FINA de prompt_toolkit sobre el modelo
puro `editor_aspecto.EditorModelo` (P10): KeyBindings que traducen cada
tecla a `modelo.tecla(nombre)` + `app.invalidate()`, y Windows que pintan
`filas_elementos()` / `filas_propiedades()` / `preview_pt()` /
`filas_flotante()` / `estado_pie()` / `mensaje()`. No decide nada: todo
estado vive en el modelo, que ya tiene 62 tests sin consola.

PANTALLA (seccion 5.4 del diseno):
  ELEMENTOS (28 col) | PROPIEDADES: <id> (<nombre>)
  VISTA PREVIA (v: variante <x>)            <- preview_pt(t)
  <teclas del contexto>                     <- estado_pie() linea 1
  <guardado · N con cambios · variante>     <- estado_pie() linea 2
  <mensaje()>                               <- ultimo aviso/error/exito
  + un Float (Frame con titulo_flotante()) cuando modelo.modo != 'normal':
    selector de color, glifos, presets, ayuda, confirmaciones, buffers.

ANIMACION (E3, vinculante): la preview anima SOLO si el elemento
seleccionado tiene animacion activa (y es vivo, y el interruptor global
esta en on): `refresh_interval()` devuelve 1/fps en ese caso y 0 si no. PT
lee `Application.refresh_interval` UNA vez al arrancar, asi que el tic es
propio (`_tic`): duerme `refresh_interval()` y solo entonces invalida; sin
animacion duerme 0,1 s sin repintar (chequeo barato). Cuando anima, la preview se calcula
con el reloj REAL (`glow.RELOJ.t()`); si no, con el `t_preview` fijo del
modelo (frame determinista, el de los tests).

GUARDAS (E12, vinculante) en `abrir_editor`:
  1. `get_app_or_none() is None`: NUNCA anidar (app.run() dentro de un
     binding se cuelga >60 s, medido por el critico). Se abre desde
     `_slash_estilo('')`, DESPUES de que session.prompt() devolvio.
  2. COGNIA_REMOTO != 1.
  3. sin corrida de fondo y sin status vivo del renderer (cli.py los pasa
     por parametro: este modulo no importa cli).
  4. tty real (selector.hay_tty: stdin+stdout tty y consola Win32).
  Si una falla devuelve ('no_abrible', motivo) y el llamador imprime la
  ayuda textual (/estilo lista). Jamas lanza hacia el REPL.

ESTILO PT de la app: `A.clases_pt(variante)` (el mismo dict del prompt, sin
la clave '' para que el editor no herede el color del texto del prompt) +
`clases_editor(variante)` (grupo/elemento/prop .activo/.cursor/.atenuada,
flotante, pie, mensaje, frame) con contraste >= PISO_TEXTO contra el fondo
de la variante (test_ux_editor_app lo mide). Se rehace cuando cambia la
variante de la preview ('v') o la version del registro (DynamicStyle).

DEGRADACION: un fallo al calcular la preview NO tumba el editor: la fila
muestra 'preview: <Tipo>: <detalle>' y se avisa por _aviso_degradado
('estilo.editor', ...) via sys.modules.get('cognia.cli') a call-time (sin
cli cargado: stderr una vez por motivo). Nunca except: pass.
"""
from __future__ import annotations

import os
import shutil
import sys

from . import aspecto as A
from . import glow as G
from . import paleta
from .editor_aspecto import EditorModelo

ANCHO_ELEMENTOS = 28
ALTO_FLOTANTE_MAX = 18
# tecla PT -> nombre de la tabla del modelo (los demas coinciden)
_TRADUCCION = {"escape": "esc", "c-c": "esc"}
_TECLAS_NOMBRADAS = ("up", "down", "pageup", "pagedown", "home", "end", "left", "right",
                     "tab", "s-tab", "enter", "backspace", "delete", "escape", "f1",
                     "c-u", "c-z", "c-y", "c-s", "c-p", "c-l", "c-n", "c-e", "c-g", "c-c")
_AVISOS_STDERR: set = set()


def _avisar(motivo: str) -> None:
    """Degradacion VISIBLE: cli._aviso_degradado('estilo.editor', ...) si el
    CLI esta cargado (de-duplica por turno); si no, stderr una vez."""
    _cli = sys.modules.get("cognia.cli")
    if _cli is not None:
        try:
            _cli._aviso_degradado("estilo.editor", motivo)
            return
        except Exception as exc:  # el aviso nunca tumba al editor
            motivo = f"{motivo} (y _aviso_degradado fallo: {type(exc).__name__}: {exc})"
    if motivo not in _AVISOS_STDERR:
        _AVISOS_STDERR.add(motivo)
        print(f"[degradado] estilo.editor: {motivo}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Estilo PT del editor
# ---------------------------------------------------------------------------
def _hex(ref: str, variante: str) -> str:
    h = A.hex_medible(ref, variante)
    if not h:
        raise ValueError(f"clases_editor: '{ref}' no resuelve a un hex en '{variante}'")
    return h


def _luminoso(hexa: str) -> bool:
    r, g, b = (int(hexa[i:i + 2], 16) for i in (1, 3, 5))
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255 > 0.5


def _legible(hexa: str, fondo: str, piso: float = A.PISO_TEXTO) -> str:
    """El hex tal cual si contrasta >= piso sobre `fondo`; si no, se acerca
    a negro (fondo claro) o blanco (fondo oscuro) de 10% en 10% hasta pasar:
    conserva el tono (la paleta semantica esta pensada para 'oscuro')."""
    objetivo = "#000000" if _luminoso(fondo) else "#ffffff"
    for i in range(11):
        c = A._mezclar(hexa, objetivo, i / 10)
        if A.contraste(c, fondo) >= piso:
            return c
    return objetivo


def clases_editor(variante: str | None = None) -> dict:
    """Las clases propias del editor, derivadas de la paleta de la variante.
    Cada valor es un style string de PT. Las de fondo propio (.activo/.activa,
    .cursor) llevan 'bg:'; las demas se miden contra FONDO_VARIANTE."""
    v = variante or A.variante_activa()
    if v not in A.ORDEN_VARIANTES:
        raise ValueError(f"variante desconocida '{v}' (opciones: {', '.join(A.ORDEN_VARIANTES)})")
    fondo = paleta.FONDO_VARIANTE[v]
    L = lambda ref: _legible(_hex(ref, v), fondo)  # noqa: E731
    texto, prompt, marco, estado = L("@semantico.texto"), L("@rampa.prompt"), L("@rampa.marco"), L("@rampa.estado")
    info, error, aviso = L("@semantico.info"), L("@semantico.error"), L("@semantico.aviso")
    act_bg, act_fg = _hex("@menu.fondo_activo", v), _legible(_hex("@menu.texto_activo", v), _hex("@menu.fondo_activo", v))
    cursor_bg = A._mezclar(fondo, texto, 0.18)
    atenuado = _legible(A._mezclar(texto, fondo, 0.40), fondo)
    return {
        "": "",
        "titulo": f"bold fg:{prompt}",
        "borde": f"fg:{marco}",
        "grupo": f"bold fg:{prompt}",
        "grupo.activo": f"bold bg:{act_bg} fg:{act_fg}",
        "elemento": f"fg:{texto}",
        "elemento.cursor": f"bold bg:{cursor_bg} fg:{texto}",
        "elemento.activo": f"bold bg:{act_bg} fg:{act_fg}",
        "elemento.atenuado": f"fg:{atenuado}",
        "prop": f"fg:{texto}",
        "prop.activa": f"bold bg:{act_bg} fg:{act_fg}",
        "prop.atenuada": f"fg:{atenuado}",
        "prop.atenuada.activa": f"bg:{act_bg} fg:{act_fg}",
        "flotante": f"fg:{texto}",
        "flotante.activo": f"bold bg:{act_bg} fg:{act_fg}",
        "flotante.buffer": f"bold fg:{prompt}",
        "pie": f"fg:{estado}",
        "pie.estado": f"fg:{atenuado}",
        "mensaje": f"fg:{info}",
        "mensaje.error": f"bold fg:{error}",
        "mensaje.aviso": f"fg:{aviso}",
        "frame.border": f"fg:{marco}",
        "frame.label": f"bold fg:{prompt}",
    }


def estilo_pt(variante: str | None = None) -> dict:
    """clases_pt(variante) sin la clave '' + clases_editor(variante)."""
    d = {k: val for k, val in A.clases_pt(variante).items() if k != ""}
    d.update(clases_editor(variante))
    return d


def _clase_mensaje(m: str) -> str:
    b = m.strip().lower()
    if b.startswith("error") or ": error" in b or "fallo" in b or b.startswith("no se pudo"):
        return "class:mensaje.error"
    if b.startswith("aviso") or "; aviso" in b or "no codificable" in b or "contraste" in b:
        return "class:mensaje.aviso"
    return "class:mensaje"


# ---------------------------------------------------------------------------
# La Application
# ---------------------------------------------------------------------------
class EditorApp:
    """Application full-screen sobre un EditorModelo. `input`/`output` son
    para tests (PipeInput + Vt100_Output); sin ellos PT crea los de la
    terminal real. `run()` devuelve modelo.resultado."""

    def __init__(self, modelo: EditorModelo, *, input=None, output=None, color_depth=None,
                 fps: int | None = None):
        from prompt_toolkit.application import Application
        from prompt_toolkit.filters import Condition
        from prompt_toolkit.layout import (ConditionalContainer, Dimension, Float, FloatContainer,
                                           FormattedTextControl, HSplit, Layout, ScrollOffsets,
                                           VSplit, Window)
        from prompt_toolkit.styles import DynamicStyle
        from prompt_toolkit.widgets import Frame

        self.modelo = modelo
        self.fps = int(fps or G.FPS)
        self._estilo_clave = None
        self._estilo = None
        self._ultimo_error_preview = ""

        def _win(get_text, get_cursor=None, **kw):
            ctl = FormattedTextControl(get_text, focusable=False, show_cursor=False,
                                       get_cursor_position=get_cursor)
            return Window(ctl, wrap_lines=False, **kw)

        # -- paneles --------------------------------------------------------
        self._w_elementos = _win(self._frags_elementos, self._cursor_elementos,
                                 scroll_offsets=ScrollOffsets(top=1, bottom=1))
        self._w_props = _win(self._frags_props, self._cursor_props,
                             scroll_offsets=ScrollOffsets(top=1, bottom=1))
        self._w_preview = _win(self._frags_preview, height=Dimension(min=3, preferred=8))
        self._w_pie = _win(self._frags_pie, height=Dimension.exact(3))
        borde_v = Window(width=1, char="│", style="class:borde")

        def regla(get_titulo):
            return Window(FormattedTextControl(lambda: [("class:borde", "─ "), ("class:titulo", get_titulo()),
                                                        ("class:borde", " ")]),
                          height=1, wrap_lines=False, char="─", style="class:borde")

        cuerpo = HSplit([
            VSplit([
                HSplit([regla(lambda: "ELEMENTOS"), self._w_elementos],
                       width=Dimension.exact(ANCHO_ELEMENTOS)),
                borde_v,
                HSplit([regla(modelo.titulo_propiedades), self._w_props]),
            ]),
            regla(lambda: f"VISTA PREVIA (v: variante {modelo.variante_preview})"),
            self._w_preview,
            Window(height=1, char="─", style="class:borde"),
            self._w_pie,
        ])

        # -- flotante -------------------------------------------------------
        self._w_flotante = _win(self._frags_flotante, self._cursor_flotante,
                                height=Dimension(min=1, max=ALTO_FLOTANTE_MAX),
                                scroll_offsets=ScrollOffsets(top=1, bottom=1))
        flotante = ConditionalContainer(
            Frame(self._w_flotante, title=modelo.titulo_flotante),
            filter=Condition(lambda: modelo.modo != "normal"))
        root = FloatContainer(cuerpo, floats=[Float(content=flotante, top=2, left=2, right=2)])

        self.app = Application(
            layout=Layout(root),
            key_bindings=self._teclas(),
            style=DynamicStyle(self._estilo_actual),
            full_screen=True,
            mouse_support=False,
            input=input,
            output=output,
            color_depth=color_depth,
            refresh_interval=None,   # el tic condicional es _tic (E3)
        )
        self.app.ttimeoutlen = 0.2   # Esc suelto llega en 0,2 s, no en 0,5

    # -- estilo -------------------------------------------------------------
    def _estilo_actual(self):
        from prompt_toolkit.styles import Style
        clave = (self.modelo.variante_preview, A.version())
        if clave != self._estilo_clave:
            self._estilo = Style.from_dict(estilo_pt(self.modelo.variante_preview))
            self._estilo_clave = clave
        return self._estilo

    # -- animacion (E3) -----------------------------------------------------
    def animando(self) -> bool:
        """True solo si el elemento seleccionado es vivo, tiene animacion
        activa y el interruptor global esta en on."""
        e = self.modelo.elemento
        if e is None or not e.vivo or not self.modelo.animacion_global:
            return False
        est = A.estilo_de(e.id)
        return bool(est.animacion and est.animacion.activa)

    def refresh_interval(self) -> float:
        return (1.0 / self.fps) if self.animando() else 0.0

    async def _tic(self) -> None:
        from asyncio import sleep
        while True:
            intervalo = self.refresh_interval()
            await sleep(intervalo or 0.1)
            if intervalo:
                self.app.invalidate()

    # -- fragmentos ---------------------------------------------------------
    @staticmethod
    def _frags(filas: list) -> list:
        out = []
        for texto, clase, _sel in filas:
            out.append((clase, texto))
            out.append(("", "\n"))
        return out[:-1] if out else [("", "")]

    @staticmethod
    def _punto(filas: list):
        from prompt_toolkit.data_structures import Point
        for i, (_t, _c, sel) in enumerate(filas):
            if sel:
                return Point(0, i)
        return Point(0, 0)

    def _frags_elementos(self):
        return self._frags(self.modelo.filas_elementos())

    def _cursor_elementos(self):
        return self._punto(self.modelo.filas_elementos())

    def _frags_props(self):
        return self._frags(self.modelo.filas_propiedades())

    def _cursor_props(self):
        return self._punto(self.modelo.filas_propiedades())

    def _frags_flotante(self):
        return self._frags(self.modelo.filas_flotante())

    def _cursor_flotante(self):
        return self._punto(self.modelo.filas_flotante())

    def _frags_preview(self):
        t = G.RELOJ.t() if self.animando() else None
        try:
            return self.modelo.preview_pt(t)
        except Exception as exc:
            motivo = f"preview de {self.modelo.elemento_id}: {type(exc).__name__}: {exc}"
            if motivo != self._ultimo_error_preview:
                self._ultimo_error_preview = motivo
                _avisar(motivo)
            return [("class:mensaje.error", motivo)]

    def _frags_pie(self):
        teclas, _, estado = self.modelo.estado_pie().partition("\n")
        m = self.modelo.mensaje()
        return [("class:pie", teclas), ("", "\n"), ("class:pie.estado", estado), ("", "\n"),
                (_clase_mensaje(m), m)]

    # -- teclas -------------------------------------------------------------
    def _aplicar(self, nombre: str) -> None:
        self.modelo.tecla(nombre)
        self.app.invalidate()
        if self.modelo.cerrado:
            self.app.exit(result=self.modelo.resultado)

    def _teclas(self):
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.keys import Keys
        kb = KeyBindings()
        for tecla in _TECLAS_NOMBRADAS:
            nombre = _TRADUCCION.get(tecla, tecla)

            def _h(event, _n=nombre):
                self._aplicar(_n)
            kb.add(tecla, eager=True)(_h)

        @kb.add(" ")
        def _space(event):
            self._aplicar("space")

        @kb.add(Keys.Any)
        def _cualquiera(event):
            for ch in event.data or "":
                if ch.isprintable():
                    self._aplicar(ch)
                    if self.modelo.cerrado:
                        return

        @kb.add(Keys.BracketedPaste)
        def _pegado(event):
            _cualquiera(event)

        return kb

    # -- ciclo de vida ------------------------------------------------------
    def run(self, *, pre_run=None) -> str:
        """Corre la Application (in_thread=False) y devuelve modelo.resultado
        ('guardado' | 'descartado' | 'cerrado'). Un EOF de la entrada cierra
        como 'cerrado' (sin perder nada: los cambios siguen en memoria).
        `pre_run` (tests) corre dentro del loop, antes del primer render."""
        def _pre():
            self.app.create_background_task(self._tic())
            if pre_run is not None:
                pre_run()
        try:
            resultado = self.app.run(pre_run=_pre, in_thread=False)
        except EOFError:
            resultado = None
        if not self.modelo.cerrado:
            self.modelo.cerrado = True
            self.modelo.resultado = self.modelo.resultado or "cerrado"
        return resultado or self.modelo.resultado or "cerrado"

    def resumen(self) -> str:
        """UNA linea para el REPL al volver: 'N elementos con cambios · guardado 12:03'."""
        n = len(A.documento().get("elementos") or {})
        partes = [f"{n} elemento{'s' if n != 1 else ''} con cambios"]
        r = self.modelo.resultado or "cerrado"
        if r == "guardado" or (self.modelo.guardado_en and not self.modelo.sucio):
            partes.append(f"guardado {self.modelo.guardado_en}".rstrip())
        elif r == "descartado":
            partes.append("cambios descartados")
        elif self.modelo.sucio:
            partes.append("SIN GUARDAR en memoria (Ctrl-S en el editor o /estilo guardar)")
        return " · ".join(partes)


# ---------------------------------------------------------------------------
# Guardas y puerta (E12)
# ---------------------------------------------------------------------------
def _bool(valor) -> bool:
    return bool(valor() if callable(valor) else valor)


def motivo_no_abrible(*, corrida_en_fondo=False, status_activo=False, hay_tty=None) -> str:
    """'' si el editor puede abrirse; si no, el motivo (texto para el REPL).
    Orden: app anidada > COGNIA_REMOTO > corrida de fondo > status vivo > tty."""
    from prompt_toolkit.application.current import get_app_or_none
    if get_app_or_none() is not None:
        return ("hay una Application de prompt_toolkit corriendo: el editor no se anida "
                "(se cuelga). Abre /estilo desde el prompt, no desde una tecla")
    if os.environ.get("COGNIA_REMOTO", "").strip() == "1":
        return "COGNIA_REMOTO=1: sin editor interactivo; usa /estilo lista y /estilo <id> <prop> <valor>"
    if _bool(corrida_en_fondo):
        return "hay una corrida de fondo: cierrala o usa /estilo <id> <prop> <valor>"
    if _bool(status_activo):
        return "el renderer tiene un status vivo: para el spinner antes de abrir el editor"
    if hay_tty is None:
        from . import selector
        hay_tty = selector.hay_tty
    if not _bool(hay_tty):
        return "sin tty (stdin/stdout no son una terminal): usa /estilo lista y /estilo <id> <prop> <valor>"
    return ""


def abrir_editor(*, guardar=None, aplicar=None, poner_config=None, variante=None,
                 elemento_inicial=None, corrida_en_fondo=False, status_activo=False,
                 hay_tty=None, ancho=None) -> tuple:
    """Abre el editor full-screen y devuelve (resultado, detalle):
    ('guardado'|'descartado'|'cerrado', resumen) o ('no_abrible', motivo).
    Callbacks: `guardar` (Ctrl-S; default aspecto.guardar), `aplicar` (tras
    guardar: aplicar en caliente), `poner_config(clave, valor)` (tecla 'a').
    `corrida_en_fondo` / `status_activo` / `hay_tty` aceptan bool o callable.
    Restaura la terminal al salir (PT sale del alt-screen): el prompt
    siguiente repinta solo."""
    motivo = motivo_no_abrible(corrida_en_fondo=corrida_en_fondo, status_activo=status_activo,
                               hay_tty=hay_tty)
    if motivo:
        return ("no_abrible", motivo)
    if ancho is None:
        try:
            ancho = shutil.get_terminal_size().columns - 2
        except (OSError, ValueError):
            ancho = 78
    modelo = EditorModelo(guardar=guardar, aplicar=aplicar, poner_config=poner_config,
                          variante=variante, ancho=max(40, int(ancho)), elemento_inicial=elemento_inicial)
    caps = G.capacidades()
    color_depth = _color_depth(caps.nivel)
    app = EditorApp(modelo, color_depth=color_depth)
    resultado = app.run()
    return (resultado, app.resumen())


def _color_depth(nivel: str):
    """Caps.nivel del motor (D8) -> ColorDepth de PT; None = que decida la salida."""
    from prompt_toolkit.output import ColorDepth
    return {"truecolor": ColorDepth.DEPTH_24_BIT, "256": ColorDepth.DEPTH_8_BIT,
            "16": ColorDepth.DEPTH_4_BIT, "none": ColorDepth.DEPTH_1_BIT}.get(nivel)
