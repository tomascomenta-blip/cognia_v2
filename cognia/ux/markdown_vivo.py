"""
cognia/ux/markdown_vivo.py
==========================
Markdown en STREAMING sin flicker para la respuesta del agente (2026-08-23).

MECANISMO (la maquina de Aider + el reloj de CodeWhale, leidos de sus fuentes):
- Aider (aider/mdstream.py): ventana viva de N lineas al fondo. En cada update
  se renderiza TODO el markdown acumulado a un buffer (rich Console sobre
  StringIO + Markdown), se hace splitlines, y las lineas que SALIERON de la
  ventana se consideran ESTABLES: se comitean al scrollback imprimiendolas UNA
  sola vez; solo la cola de N lineas se repinta. Throttle adaptativo:
  retraso = clamp(tiempo_de_render * 10, RELOJ, RETRASO_MAX).
- CodeWhale (streaming/mod.rs): los deltas del modelo son INPUT, no timing.
  Los tokens se acumulan y se repinta con reloj fijo (~30 ms); si el backlog
  envejece (> CATCHUP_S) se vuelca ya. Nunca se comitea la linea parcial
  final, y una linea estable DENTRO de un fence abierto se RETIENE: un bloque
  de codigo jamas se parte al commitearlo.
- REGLA DEL BLOQUE ABIERTO (revision adversarial 2026-08-24): solo se
  comitean lineas de bloques CERRADOS. rich calcula los anchos de una tabla
  sobre TODAS sus filas y la sangria de una lista ordenada sobre su ULTIMO
  numero, asi que las primeras filas de una tabla (o los items 1..9 de una
  lista de 10+) commiteadas con la ventana de 6 salian con un ancho distinto
  al del render final: tabla partida en dos anchos en el transcript (medido:
  11 de 12 lineas commiteadas distintas). Lo mismo un parrafo seguido de un
  subrayado setext ('---'): se convierte en titulo. Por eso el tope de commit
  es el inicio del ultimo bloque abierto (fence, tabla, lista ordenada —que
  sigue abierta tras una linea en blanco—, parrafo hasta su linea en blanco).
- TOPE DE ALTURA (mismo dia): la cola viva nunca supera la altura de la
  terminal. CUU ('ESC[nA') se clampa en la fila 0 y ESC[J solo borra la
  pantalla visible: un fence de 60 lineas en una terminal de 30 filas dejaba
  30 lineas NUEVAS en el scrollback por repintado (N copias parciales del
  bloque encima de la definitiva). Si el bloque abierto no cabe, se comitea
  su cabeza aunque pueda reflowear: mejor un ancho distinto que N copias.

POR QUE cursor-up ANSI y no rich Live para la cola:
- rich reserva UN slot de Live por Console y console.status (el spinner vivo
  del renderer) ya lo ocupa. Con rich <= 13 un Live anidado levantaba
  LiveError si el spinner pisaba la llegada del primer token (carrera real:
  _parar_status corre dentro del handler, en el hilo del emisor); rich 15
  APILA la Live anidada en vez de lanzar (medido 2026-08-24, P8), pero dos
  Lives apiladas siguen siendo dos escritores sobre la misma zona. El
  spinner animado de P8 (glow.LineaViva) va DENTRO del status, no en otra
  Live; y esta cola sigue por cursor-up.
- prompt_toolkit solo es dueno de la terminal MIENTRAS pide input; durante el
  streaming no hay prompt activo y los escapes crudos no chocan con nada.
- el repintado por escapes se captura tal cual en un StringIO: la estabilidad
  del commit se testea bit a bit sin terminal ni hilos.
En consolas sin cursor (sin tty, conhost legacy) NO se anima: las estables se
comitean al vuelo y la cola se pinta entera al cerrar — el transcript queda
limpio, sin basura de repintado.

DEGRADACION: cualquier fallo interno avisa por _aviso_degradado('markdown',
motivo) — el canal unico del repo — y cae al flujo plano (FlujoSuave) EN ESE
TURNO, re-imprimiendo el texto crudo acumulado (mejor re-impreso visible que
cola perdida). escribir()/cerrar() NO lanzan jamas: el adorno no rompe turnos.

Config (a CALL-TIME, patron spinner_vivo.config):
- clave 'markdown_stream' on|off (default on; OFF automatico sin tty)
- clave 'markdown_tema': tema pygments de los bloques de codigo (default
  'monokai', el de Aider) -> /markdown tema <t>
- env COGNIA_MARKDOWN=0|1 gana a la config (0 apaga, 1 fuerza aun sin tty);
  COGNIA_CODE_THEME gana a 'markdown_tema'; COGNIA_REMOTO=1 apaga SIEMPRE:
  el clasificador del movil depende de las marcas del camino viejo.
"""
from __future__ import annotations

import io
import os
import re
import shutil
import sys
import time

from .estilo import ANCHO_MAX, FlujoSuave

# Ventana viva: las ultimas N lineas renderizadas se repintan; lo anterior se
# comitea. 6 es el numero de Aider (cubre el reflow tipico de una lista o un
# parrafo que sigue creciendo).
VENTANA = 6
# Reloj fijo de drenado (CodeWhale usa 16-33 ms): piso del throttle.
RELOJ = 0.03
# Techo del throttle adaptativo de Aider (render_time * 10, capado).
RETRASO_MAX = 2.0
# Catch-up de CodeWhale: el backlog nunca envejece mas que esto aunque el
# render sea lento — se vuelca ya.
CATCHUP_S = 1.2
# Tema pygments default de los bloques de codigo (el mismo default de Aider).
TEMA_DEFAULT = "monokai"

_SANGRIA = "  "

# Un fence de CommonMark: hasta 3 espacios de sangria + ``` o ~~~ (3 o mas).
_RE_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
# Item de lista ORDENADA (la que reflowea por el ancho del ultimo numero).
_RE_ITEM_ORDENADO = re.compile(r"^ {0,3}\d{1,9}[.)](\s|$)")
# Titulo ATX: bloque de UNA linea, cerrado al terminar la linea.
_RE_ATX = re.compile(r"^ {0,3}#{1,6}(\s|$)")
# Margen de filas que se deja libre bajo la cola viva (prompt, spinner).
_MARGEN_ALTO = 2


def _avisar(motivo: str) -> None:
    """Degradacion VISIBLE por el canal unico del repo (_aviso_degradado del
    CLI, que de-duplica por turno y motivo). Sin cli cargado (tests, scripts)
    el aviso sale por stderr — jamas se calla."""
    try:
        _cli = sys.modules.get("cognia.cli")
        if _cli is not None:
            _cli._aviso_degradado("markdown", motivo)
            return
    except Exception:
        pass
    try:
        print(f"{_SANGRIA}degradado — markdown: {motivo}", file=sys.stderr)
    except Exception:
        pass


def config() -> tuple:
    """(activo, tema) a CALL-TIME.

    COGNIA_MARKDOWN manda ('0' apaga, '1' fuerza aun sin tty); sin la env
    decide la config persistida del CLI (claves 'markdown_stream' y
    'markdown_tema', se cambian con /markdown) y la interactividad real de
    stdout (sin tty el repintado ensuciaria pipes y logs: off automatico).
    COGNIA_REMOTO=1 apaga SIEMPRE, gane quien gane: el clasificador del movil
    reconoce las marcas del camino viejo y la prosa nueva lo romperia. Se mira
    sys.modules y NO se importa cli (mismo patron que spinner_vivo.config)."""
    activo, tema = True, TEMA_DEFAULT
    try:
        _cli = sys.modules.get("cognia.cli")
        if _cli is not None:
            cfg = _cli._load_config()
            activo = (str(cfg.get("markdown_stream", "on")).strip().lower()
                      not in ("off", "0", "false", "no"))
            t = str(cfg.get("markdown_tema", "")).strip()
            if t:
                tema = t
    except Exception:
        activo, tema = True, TEMA_DEFAULT
    env_tema = (os.environ.get("COGNIA_CODE_THEME") or "").strip()
    if env_tema:
        tema = env_tema
    if (os.environ.get("COGNIA_REMOTO") or "").strip() == "1":
        return False, tema
    v = (os.environ.get("COGNIA_MARKDOWN") or "").strip().lower()
    if v in ("0", "false", "no", "off"):
        return False, tema
    if v in ("1", "true", "si", "on"):
        return True, tema
    if activo:
        try:
            activo = bool(sys.stdout.isatty())
        except Exception:
            activo = False
    return activo, tema


def activo() -> bool:
    return config()[0]


def retraso_adaptativo(render_s: float) -> float:
    """El throttle de Aider: 10x lo que costo el ULTIMO render, con piso en
    el reloj fijo y techo en RETRASO_MAX. Un render caro (doc largo, terminal
    lenta) espacia los repintados solo; uno barato drena a ~30 ms."""
    return min(max(float(render_s) * 10.0, RELOJ), RETRASO_MAX)


def fence_abierto(texto: str):
    """Offset en chars del INICIO de la linea que abrio el fence todavia
    abierto, o None si no hay. CommonMark basico: cierra solo la MISMA
    familia (` o ~), con largo >= al de apertura y sin texto tras la marca
    ('```python' abre; '```' cierra; '~~~' dentro de ``` es contenido)."""
    abierto = None
    off = 0
    for linea in texto.split("\n"):
        m = _RE_FENCE.match(linea)
        if m:
            if abierto is None:
                abierto = (off, m.group(1))
            elif (m.group(1)[0] == abierto[1][0]
                  and len(m.group(1)) >= len(abierto[1])
                  and not m.group(2).strip()):
                abierto = None
        off += len(linea) + 1
    return None if abierto is None else abierto[0]


def bloque_abierto(texto: str):
    """Offset en chars del INICIO del ultimo bloque markdown todavia ABIERTO
    (el que puede cambiar de forma cuando llegue mas texto), o None si el
    texto termina en un bloque cerrado. Bloques y su cierre:
      - fence: hasta su marca de cierre (regla de fence_abierto);
      - tabla ('|' al inicio): hasta una linea en blanco o una que no sea fila;
      - lista ordenada: hasta una linea en blanco seguida de algo que NO es
        item ni continuacion sangrada (una lista 'loose' sigue siendo una);
      - titulo ATX: una sola linea, cerrado;
      - cualquier otra cosa (parrafo, lista con vinetas, cita): hasta una
        linea en blanco (un '---' pegado debajo lo vuelve titulo setext).
    """
    tipo = None
    inicio = None
    fence = None
    tras_blanco = False
    off = 0
    lineas = texto.split("\n")
    if lineas and lineas[-1] == "":
        # el texto termina en '\n': la linea siguiente NO empezo todavia; no
        # es una linea en blanco (eso seria '\n\n') y no cierra nada
        lineas.pop()
    for linea in lineas:
        m = _RE_FENCE.match(linea)
        if fence is not None:
            if (m and m.group(1)[0] == fence[0]
                    and len(m.group(1)) >= len(fence)
                    and not m.group(2).strip()):
                fence, tipo, inicio = None, None, None
        elif m:
            fence, tipo, inicio = m.group(1), "fence", off
        elif not linea.strip():
            if tipo == "lista":
                tras_blanco = True
            else:
                tipo, inicio = None, None
        else:
            es_item = bool(_RE_ITEM_ORDENADO.match(linea))
            es_fila = linea.lstrip().startswith("|")
            if tipo == "lista":
                if tras_blanco and not (es_item or linea.startswith("  ")
                                        or linea.startswith("\t")):
                    tipo = None
                else:
                    tras_blanco = False
            elif tipo == "tabla" and not es_fila:
                tipo = None
            if tipo is None:
                inicio = off
                if es_item:
                    tipo, tras_blanco = "lista", False
                elif es_fila:
                    tipo = "tabla"
                elif _RE_ATX.match(linea):
                    inicio = None            # una linea: ya esta cerrado
                else:
                    tipo = "parrafo"
        off += len(linea) + 1
    return inicio if tipo is not None else None


class MarkdownVivo:
    """Render markdown en streaming con commit de lineas estables.

    Uso (misma interfaz que FlujoSuave, intercambiables en el renderer y en
    el fast-path del CLI):
        mv = MarkdownVivo(console=_console)
        for tok in stream: mv.escribir(tok)
        mv.cerrar()     # render final: comitea todo y resetea (reusable)
    """

    def __init__(self, console=None, tema: str | None = None,
                 ventana: int = VENTANA, ancho: int | None = None,
                 salida=None, reloj=None, alto: int | None = None):
        # ``salida``/``reloj``/``alto`` inyectables para tests (StringIO /
        # reloj fake / filas de la terminal).
        self._console = console
        self._tema = tema or config()[1]
        self._ventana = max(1, int(ventana))
        self._salida = salida if salida is not None else (
            getattr(console, "file", None) or sys.stdout)
        self._reloj = reloj or time.monotonic
        self._sangria = _SANGRIA
        if ancho is None:
            try:
                w = (getattr(console, "width", None)
                     or shutil.get_terminal_size().columns)
            except Exception:
                w = 80
            ancho = max(40, min(int(w) - len(_SANGRIA) * 2, ANCHO_MAX))
        self._ancho = max(20, int(ancho))
        # tope de la cola viva: las filas de la terminal menos un margen; por
        # debajo de la ventana no tiene sentido (la ventana ya es el minimo).
        if alto is None:
            try:
                alto = (getattr(console, "height", None)
                        or shutil.get_terminal_size().lines) - _MARGEN_ALTO
            except Exception:
                alto = 24 - _MARGEN_ALTO
        self._alto = max(self._ventana, int(alto))
        # color: solo si la Console real lo pinta (FORCE_COLOR incluido via
        # is_terminal de rich); sin color el render interno sale plano.
        self._color = bool(console is not None
                           and getattr(console, "is_terminal", False)
                           and not getattr(console, "no_color", False))
        # animar = mover el cursor con escapes. Solo con un tty DE VERDAD al
        # otro lado (el fd, no rich: FORCE_COLOR miente sobre is_terminal a
        # proposito — la leccion de _consola_interactiva del renderer) y
        # nunca en conhost legacy (rich pinta ahi via win32, los escapes
        # saldrian literales). Sin animar: modo solo-commit — las estables
        # salen al vuelo y la cola entera al cerrar; el transcript queda
        # limpio (asi COGNIA_MARKDOWN=1 sirve sobre un pipe).
        self._animar = (self._es_tty()
                        and not getattr(console, "legacy_windows", False))
        # compat con renderer._cerrar_flujo: tras cada repintado el cursor
        # queda en columna 0 (toda linea pintada termina en '\n').
        self._al_inicio_de_linea = True
        self._reset()

    def _reset(self) -> None:
        self._texto = ""
        self._estables = 0            # lineas renderizadas YA commiteadas
        self._commiteadas: list = []  # su texto pintado (invariante testeable)
        self._cola_altura = 0         # lineas de la cola viva en pantalla
        self._ultimo = 0.0            # ts del ultimo repintado
        self._retraso = RELOJ         # throttle adaptativo vigente
        self._cache_bloque = None     # (offset_bloque, tope) — ver _tope_bloque
        self._plano = None            # FlujoSuave del turno degradado, o None

    def _es_tty(self) -> bool:
        try:
            return bool(self._salida.isatty())
        except Exception:
            return False

    def texto_crudo(self) -> str:
        """Lo acumulado sin renderizar (para el fallback plano del caller)."""
        return self._texto

    # -- render -------------------------------------------------------------

    def _render(self, texto: str) -> list:
        """TODO el markdown a lineas ya pintadas (con ANSI si hay color), al
        ancho fijo del turno. Console fresca por llamada: sin estado."""
        from rich.console import Console
        from rich.markdown import Markdown
        buf = io.StringIO()
        c = Console(file=buf, width=self._ancho, highlight=False,
                    force_terminal=self._color, no_color=not self._color,
                    theme=tema_del_cli())
        c.print(Markdown(texto or "", code_theme=self._tema))
        return buf.getvalue().splitlines()

    def _tope_bloque(self):
        """Tope de commit cuando hay un bloque ABIERTO (ver bloque_abierto):
        el numero de lineas renderizadas ANTES de el. Un fence no se parte
        (regla CodeWhale) y una tabla/lista/parrafo no se comitea con una
        forma que el render final va a cambiar. None = sin bloque abierto.
        El render del prefijo se cachea por offset del bloque: no cambia
        mientras el mismo siga abierto."""
        off = bloque_abierto(self._texto)
        if off is None:
            self._cache_bloque = None
            return None
        if self._cache_bloque is not None and self._cache_bloque[0] == off:
            return self._cache_bloque[1]
        lineas = self._render(self._texto[:off])
        while lineas and not lineas[-1].strip():
            lineas.pop()
        self._cache_bloque = (off, len(lineas))
        return len(lineas)

    def _repintar(self, final: bool) -> None:
        t0 = time.perf_counter()
        lineas = self._render(self._texto)
        self._retraso = retraso_adaptativo(time.perf_counter() - t0)
        if final:
            nuevo = len(lineas)
        else:
            nuevo = max(0, len(lineas) - self._ventana)
            tope = self._tope_bloque()
            if tope is not None:
                nuevo = min(nuevo, tope)
            if self._animar and len(lineas) - nuevo > self._alto:
                # La cola no cabe en la pantalla: repintarla duplicaria en el
                # scrollback lo que ya scrolleo (CUU se clampa en la fila 0).
                # Se comitea la cabeza del bloque abierto aunque reflowee.
                nuevo = len(lineas) - self._alto
        # el commit NUNCA retrocede: lo impreso al scrollback ya es historia
        nuevo = max(nuevo, self._estables)
        frescas = lineas[self._estables:nuevo]
        cola = [] if final else lineas[nuevo:]
        out = []
        if self._animar and self._cola_altura:
            # subir al inicio de la cola vieja y borrar de ahi para abajo
            out.append(f"\x1b[{self._cola_altura}A\r\x1b[J")
        for l in frescas:
            out.append(self._sangria + l + "\n")
        if self._animar:
            for l in cola:
                out.append(self._sangria + l + "\n")
            self._cola_altura = len(cola)
        # sin animar la cola NO se pinta (se pintara commiteada): un pipe no
        # tiene cursor que subir y repetirla seria la basura de repintado
        if out:
            self._salida.write("".join(out))
            try:
                self._salida.flush()
            except Exception:
                pass  # flush cosmetico: el write ya salio o ya lanzo
        self._commiteadas.extend(frescas)
        self._estables = nuevo

    # -- degradacion ----------------------------------------------------------

    def _degradar(self, motivo: str) -> None:
        """El render vivo fallo: avisar (canal unico) y caer al flujo plano
        EN ESTE TURNO, re-imprimiendo el texto crudo acumulado — en pantalla
        puede quedar el markdown a medias arriba, pero la respuesta COMPLETA
        queda visible en plano. Mejor duplicado honesto que cola perdida."""
        _avisar(motivo)
        try:
            self._salida.write("\n")
        except Exception:
            pass  # la salida rota es justo lo que acabamos de avisar
        self._plano = FlujoSuave(console=self._console)
        if self._texto:
            try:
                self._plano.escribir(self._texto)
            except Exception as exc:
                _avisar(f"fallback plano: {type(exc).__name__}: {exc}")

    # -- interfaz FlujoSuave --------------------------------------------------

    def escribir(self, token: str) -> None:
        if self._plano is not None:
            try:
                self._plano.escribir(token or "")
            except Exception as exc:
                _avisar(f"fallback plano: {type(exc).__name__}: {exc}")
            return
        self._texto += token or ""
        ahora = self._reloj()
        # throttle de Aider con el techo de catch-up de CodeWhale: aunque el
        # render sea lento, el backlog nunca envejece mas de CATCHUP_S
        espera = min(self._retraso, CATCHUP_S)
        if ahora - self._ultimo < espera:
            return
        try:
            self._repintar(final=False)
            self._ultimo = ahora
        except Exception as exc:
            self._degradar(f"{type(exc).__name__}: {exc}")

    def cerrar(self) -> None:
        """Render final: comitea TODO (la cola incluida) y resetea — el
        objeto queda reusable (el reintento por truncado del fast-path
        re-streamea la respuesta entera sobre el mismo flujo)."""
        if self._plano is not None:
            try:
                self._plano.cerrar()
                self._al_inicio_de_linea = self._plano._al_inicio_de_linea
            except Exception as exc:
                _avisar(f"fallback plano: {type(exc).__name__}: {exc}")
            self._reset()
            return
        try:
            if self._texto:
                self._repintar(final=True)
                self._al_inicio_de_linea = True
        except Exception as exc:
            self._degradar(f"{type(exc).__name__}: {exc}")
            if self._plano is not None:
                try:
                    self._plano.cerrar()
                    self._al_inicio_de_linea = self._plano._al_inicio_de_linea
                except Exception as exc2:
                    _avisar(f"fallback plano: {type(exc2).__name__}: {exc2}")
        self._reset()


_TEMA_CACHE: dict = {}


def tema_del_cli():
    """El Theme de rich de la variante ACTIVA (paleta.tema_cli), para que la
    Console fresca del render pinte los titulos, el codigo inline y los
    numeros de lista con la rampa del producto y no con los defaults de rich
    (magenta subrayado / cyan sobre negro; juez 2026-08-24). None si no se
    puede (rich sin Theme o paleta rota): rich usa sus defaults y se avisa
    UNA vez por el logger (que el REPL enruta a la interfaz)."""
    try:
        from rich.theme import Theme
        from cognia.ux import paleta
        from cognia.console.diff_render import variante_activa
        variante = variante_activa()
        if variante not in _TEMA_CACHE:
            _TEMA_CACHE[variante] = Theme(paleta.tema_cli(variante))
        return _TEMA_CACHE[variante]
    except Exception as exc:
        if not _TEMA_CACHE.get("_avisado"):
            _TEMA_CACHE["_avisado"] = True
            import logging
            logging.getLogger(__name__).warning(
                "markdown sin tema del CLI (defaults de rich): %s: %s",
                type(exc).__name__, exc)
        return None


def crear(console=None):
    """MarkdownVivo si la config lo activa; None si toca el camino viejo
    (FlujoSuave). NUNCA lanza: un fallo de creacion avisa y devuelve None —
    el punto de entrada unico para el renderer y el fast-path del CLI."""
    try:
        act, tema = config()
        if not act:
            return None
        return MarkdownVivo(console=console, tema=tema)
    except Exception as exc:
        _avisar(f"{type(exc).__name__}: {exc}")
        return None
