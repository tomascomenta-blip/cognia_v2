"""
cognia/ux/renderer.py
=====================
El consumidor de eventos que PINTA el turno (2026-08-09).

POR QUE EXISTE: el loop del agente imprimia crudo ("paso N: <raw[:120]>",
"[backend] via=...", logs INFO en medio) y el resultado final quedaba perdido
entre el ruido (evidencia baseline 2026-08-09). Este modulo es la otra mitad
del contrato de ux/events.py: los productores emiten eventos tipados y AQUI se
decide que se ve y como. Una tool corriendo es "· Leyendo motor.py…", una tool
terminada es "⏺ Leyendo motor.py — 42 lineas", la respuesta final es markdown
renderizado con un footer honesto (tokens REALES del backend, no len//4).

Reglas de la casa que este modulo hereda:
- NO-LANZANTE: emitir() ya traga excepciones de suscriptores, pero ademas cada
  handler esta guardado — el adorno jamas rompe un turno.
- Degradable: sin rich cae a print() plano; sin terminal, a lineas quietas.
- El vocabulario visual viene de ux/estilo.py (GERUNDIOS, FlujoSuave, marcas):
  este modulo ORQUESTA, estilo.py da la forma.
"""
from __future__ import annotations

import os
import re
import time

from . import events
from .estilo import FlujoSuave, respirar, respuesta, verbo_de, objeto_de

_SANGRIA = "  "
_MARCA_ACTIVIDAD = "·"
_MARCA_HECHO = "⏺"
_MARCA_ERROR = "✗"
_MARCA_AVISO = "⚠"
# Marca EXCLUSIVA del razonamiento en vivo: no colisiona con las marcas
# semi-contrato del de-dup remoto (⏺ · ✗ ⚠ →) y ademas ese flujo jamas se
# emite bajo COGNIA_REMOTO.
_MARCA_PENSAR = "∴"
_SANGRIA_PENSAR = "    " + _MARCA_PENSAR + " "

# Tope de lineas del resumen de una tool: el modelo ve el output completo por
# su canal; el humano solo necesita saber QUE paso (estilo Claude Code: la
# linea compacta, no el volcado).
_MAX_LINEAS_RESUMEN = 3

# Tope de lineas del preview de escritura (lo que la tool dejo en el archivo).
_MAX_LINEAS_PREVIEW = 3

# El productor (agent/loop.py) trunca ev.args a [:120]: si llega con ese largo
# el payload quedo cortado y el preview lo dice con un '…' honesto.
_TOPE_ARGS_PRODUCTOR = 120


class Renderer:
    """Suscriptor del bus de ux/events.py que renderiza el turno en terminal.

    Mantiene el poco estado que la presentacion necesita: el spinner activo,
    el flujo de streaming, y los avisos/degradados ya mostrados (UNA linea por
    motivo y por tarea; la telemetria jsonl del bus guarda TODAS las
    repeticiones, aca solo se protege la pantalla)."""

    def __init__(self, console=None):
        self._console = console          # rich Console del CLI, o None
        self._flujo: FlujoSuave | None = None
        self._flujo_pensar: FlujoSuave | None = None   # razonamiento en vivo
        self._status = None              # rich status (spinner) activo, o None
        self._avisos_vistos: set = set()
        self._pensando_desde: float = 0.0
        self._t0: float = 0.0
        # Bajo el control remoto la prosa NO se streamea: el contrato con el
        # clasificador del movil es que la respuesta final llega ENTERA y
        # plana via _show_response, y streamearla ademas la pegaba duplicada
        # en una linea del chat ("¡Hola! ¿En que puedo ¡Hola!...") — cazado
        # por el e2e de WP5 2026-08-09.
        self._sin_stream = os.environ.get("COGNIA_REMOTO", "").strip() == "1"

    # -- despacho -----------------------------------------------------------

    def __call__(self, ev: events.Evento) -> None:
        # emitir() ya es no-lanzante, pero el guard local evita que un evento
        # malformado deje un spinner huerfano girando sobre la respuesta.
        try:
            handler = self._HANDLERS.get(type(ev).__name__)
            if handler is not None:
                handler(self, ev)
        except Exception:
            self._parar_status()

    # -- utilidades ---------------------------------------------------------

    def _print(self, texto: str, style: str = "") -> None:
        if self._console is not None:
            try:
                self._console.print(texto, style=style or None,
                                    markup=False, highlight=False)
                return
            except Exception:
                pass
        try:
            print(texto, flush=True)
        except Exception:
            pass

    def _parar_status(self) -> None:
        if self._status is not None:
            try:
                self._status.stop()
            except Exception:
                pass
            self._status = None
        self._pensando_desde = 0.0

    def _arrancar_status(self, etiqueta: str, estilo: str = "spinner") -> None:
        """Spinner efimero con rich; linea quieta sin el (consola no
        interactiva o sin rich). Nunca dos a la vez.

        ``estilo``: clave del tema para el texto del status. Las tools siguen
        con 'spinner'; 'pensando…' usa 'pensar' (verde por pedido del dueno,
        2026-08-10)."""
        self._parar_status()
        if self._console is not None:
            try:
                self._status = self._console.status(
                    f"[{estilo}]{_MARCA_ACTIVIDAD} {etiqueta}[/{estilo}]",
                    spinner="dots")
                self._status.start()
                return
            except Exception:
                self._status = None
        self._print(f"{_SANGRIA}{_MARCA_ACTIVIDAD} {etiqueta}")

    def _cerrar_flujo(self) -> None:
        if self._flujo is not None:
            # cerrar() vacia el buffer; el print() termina la linea a medias
            # (el stream rara vez acaba en \n) para que lo siguiente — footer,
            # aviso, prompt — no se pegue a la prosa.
            en_linea = True
            try:
                self._flujo.cerrar()
                en_linea = not self._flujo._al_inicio_de_linea
            except Exception:
                pass
            self._flujo = None
            if en_linea:
                self._print("")

    # -- razonamiento en vivo (COGNIA_PENSAR=ver) ---------------------------

    def _pensar_en_vivo(self) -> bool:
        """El razonamiento streameado es opt-in y se decide a CALL-TIME (asi
        /pensar aplica en el mismo proceso sin re-crear el renderer). JAMAS
        bajo COGNIA_REMOTO: el clasificador del movil no conoce la prosa ∴ y
        la pegaria al chat como respuesta."""
        if self._sin_stream or os.environ.get("COGNIA_REMOTO", "").strip() == "1":
            return False
        return os.environ.get("COGNIA_PENSAR", "").strip().lower() == "ver"

    def _estilo_pensar_stream(self):
        """Estilo de la prosa del razonamiento: 'pensar' del tema + tenue e
        italica. Se COMBINA aqui como Style porque rich no resuelve nombres de
        tema dentro de un string compuesto ('dim italic pensar' revienta);
        fallback: verde plano, y sin rich el estilo ni se usa."""
        if self._console is not None:
            try:
                from rich.style import Style
                return self._console.get_style("pensar") + Style.parse("dim italic")
            except Exception:
                pass
            try:
                from rich.style import Style
                return Style.parse("dim italic green")
            except Exception:
                pass
        return "pensar"

    def _cerrar_flujo_pensar(self) -> None:
        """Cierra la prosa del razonamiento con una linea en blanco: separa el
        pensamiento (tenue) de lo que sigue (prosa real o tool)."""
        if self._flujo_pensar is None:
            return
        en_linea = True
        try:
            self._flujo_pensar.cerrar()
            en_linea = not self._flujo_pensar._al_inicio_de_linea
        except Exception:
            pass
        self._flujo_pensar = None
        if en_linea:
            self._print("")
        self._print("")

    # -- handlers -----------------------------------------------------------

    def _on_tarea_inicio(self, ev: events.TareaInicio) -> None:
        # Estado fresco por tarea: los avisos vuelven a poder salir una vez.
        self._parar_status()
        self._cerrar_flujo()
        self._avisos_vistos.clear()
        self._t0 = ev.ts
        # Nada que imprimir: el usuario acaba de teclear la tarea; repetirsela
        # es eco. El modelo que respondera se ve en el footer si hace falta.

    def _on_paso_intencion(self, ev: events.PasoIntencion) -> None:
        self._parar_status()
        self._cerrar_flujo()
        self._cerrar_flujo_pensar()
        intencion = (ev.intencion or "").strip().split("\n")[0]
        if intencion:
            # italic: la intencion es un pensamiento del agente, no un hecho
            self._print(f"{_SANGRIA}{intencion}", style="intencion")

    def _on_tool_inicio(self, ev: events.ToolInicio) -> None:
        self._cerrar_flujo()
        self._cerrar_flujo_pensar()
        verbo, obj = verbo_de(ev.tool), objeto_de(ev.args)
        etiqueta = f"{verbo} {obj}…".replace("  ", " ").strip()
        self._arrancar_status(etiqueta)

    def _print_tool_fin_rico(self, ok: bool, verbo: str, obj: str,
                             cabeza: str) -> bool:
        """La linea de ToolFin pintada POR PARTES (marca/verbo/objeto/cabeza,
        cada uno con su estilo del tema). El TEXTO resultante es IDENTICO al
        plano de siempre — la marca ⏺/✗ y el ' — ' son semi-contrato del
        de-dup del remoto (es_eco_renderer) — aca solo cambia el color.
        Devuelve False si no pudo (sin rich / assemble fallo): el caller
        imprime la linea plana de hoy."""
        if self._console is None:
            return False
        try:
            from rich.text import Text
            partes = [(_SANGRIA, ""),
                      (_MARCA_HECHO if ok else _MARCA_ERROR,
                       "ok_cl" if ok else "err_cl"),
                      (" ", ""),
                      (verbo, "tool_verbo")]
            if obj:
                partes += [(" ", ""), (obj, "tool_obj")]
            if ok:
                if cabeza:
                    partes += [(f" — {cabeza}", "info_dim")]
            else:
                partes += [(" — fallo", "err_cl")]
                if cabeza:
                    partes += [(": ", "err_cl"), (cabeza, "info_dim")]
            self._console.print(Text.assemble(*partes), highlight=False)
            return True
        except Exception:
            return False

    def _preview_edicion(self, payload: str, cortado: bool) -> None:
        """1 linea '- <buscar>' y 1 linea '+ <reemplazar>' del bloque
        SEARCH/REPLACE de editar_archivo (cabezas de cada seccion)."""
        cuerpo = re.split(r"<{4,}\s*SEARCH[^\n]*\n?", payload, maxsplit=1)
        if len(cuerpo) != 2:
            return
        partes = re.split(r"\n={4,}[^\n]*\n?", cuerpo[1], maxsplit=1)
        buscar = partes[0]
        reemplazar = partes[1] if len(partes) == 2 else ""
        reemplazar = re.split(r"\n?>{4,}", reemplazar, maxsplit=1)[0]
        b_head = next((l.strip() for l in buscar.split("\n") if l.strip()), "")
        r_head = next((l.strip() for l in reemplazar.split("\n") if l.strip()), "")
        if b_head:
            suf = "…" if cortado and not r_head else ""
            self._print(f"{_SANGRIA * 3}- {b_head}{suf}", style="borrado")
        if r_head:
            suf = "…" if cortado else ""
            self._print(f"{_SANGRIA * 3}+ {r_head}{suf}", style="escrito")

    def _preview_escritura(self, ev: events.ToolFin) -> None:
        """PREVIEW de lo escrito (pedido del dueno 2026-08-10): ver de verdad
        las lineas que la tool dejo en el archivo, no solo el 'OK (N chars)'.
        Best-effort sobre ev.args, que el productor (loop.py) trunca a ~120
        chars: se muestra lo que haya y un '…' honesto si quedo cortado.
        Bajo remoto NO se emite: son lineas nuevas que es_eco_renderer no
        conoce y llegarian al chat del movil como prosa."""
        if self._sin_stream:
            return
        if ev.tool not in ("escribir_archivo", "apendar_archivo",
                           "editar_archivo"):
            return
        args = ev.args or ""
        if "|" not in args:
            return
        payload = args.split("|", 1)[1]
        cortado = len(args) >= _TOPE_ARGS_PRODUCTOR
        if ev.tool == "editar_archivo":
            self._preview_edicion(payload, cortado)
            return
        lineas = [l for l in payload.strip("\n").split("\n") if l.strip()]
        if not lineas:
            return
        vistas = lineas[:_MAX_LINEAS_PREVIEW]
        hay_mas = cortado or len(lineas) > len(vistas)
        for i, l in enumerate(vistas):
            suf = "…" if hay_mas and i == len(vistas) - 1 else ""
            self._print(f"{_SANGRIA * 3}+ {l.strip()}{suf}", style="escrito")

    def _on_tool_fin(self, ev: events.ToolFin) -> None:
        self._parar_status()
        verbo, obj = verbo_de(ev.tool), objeto_de(ev.args)
        etiqueta = f"{verbo} {obj}".replace("  ", " ").strip()
        lineas = [l for l in (ev.resumen or "").strip().split("\n") if l.strip()]
        cabeza = lineas[0].strip() if lineas else ""
        if ev.ok:
            if not self._print_tool_fin_rico(True, verbo, obj, cabeza):
                linea = f"{_SANGRIA}{_MARCA_HECHO} {etiqueta}"
                if cabeza:
                    linea += f" — {cabeza}"
                self._print(linea, style="info_dim")
            # el resto del resumen (2-3 lineas max), sangrado bajo la marca
            for extra in lineas[1:_MAX_LINEAS_RESUMEN]:
                self._print(f"{_SANGRIA}  {extra.strip()}", style="info_dim")
            self._preview_escritura(ev)
        else:
            # el error se VE: es la diferencia entre "no hizo nada" y "fallo
            # aqui por esto" (la degradacion silenciosa es el enemigo).
            if not self._print_tool_fin_rico(False, verbo, obj, cabeza):
                linea = f"{_SANGRIA}{_MARCA_ERROR} {etiqueta} — fallo"
                if cabeza:
                    linea += f": {cabeza}"
                self._print(linea, style="warn_cl")
            for extra in lineas[1:_MAX_LINEAS_RESUMEN]:
                self._print(f"{_SANGRIA}  {extra.strip()}", style="warn_cl")

    def _on_razonamiento_tick(self, ev: events.RazonamientoTick) -> None:
        # "pensando… (Ns)": el aire muerto del razonador se vuelve senal. El
        # primer tick arranca el reloj; los siguientes solo actualizan el
        # texto del spinner (sin rich la linea quieta ya quedo impresa).
        # El estilo es 'pensar' (verde en los 3 temas, pedido del dueno):
        # pensar SIEMPRE se ve verde, tambien en el spinner.
        # En modo VER el spinner NO corre: la prosa ∴ ES el indicador, y el
        # status compitiendo con el stream entrelazaba '· pensando… (0s)'
        # dentro de las frases (cazado MIRANDO la escena pensar_visible).
        if self._pensar_en_vivo():
            # _parar_status resetea el reloj: pararlo PRIMERO y fijar despues.
            arranque = self._pensando_desde
            self._parar_status()
            self._pensando_desde = arranque or ev.ts or time.time()
        elif self._pensando_desde <= 0:
            self._pensando_desde = ev.ts or time.time()
            self._arrancar_status("pensando…", estilo="pensar")
            # _arrancar_status resetea _pensando_desde via _parar_status
            self._pensando_desde = ev.ts or time.time()
        elif self._status is not None:
            segs = int((ev.ts or time.time()) - self._pensando_desde)
            try:
                self._status.update(
                    f"[pensar]{_MARCA_ACTIVIDAD} pensando… ({segs}s)[/pensar]")
            except Exception:
                pass
        # RAZONAMIENTO OPCIONAL EN VIVO (COGNIA_PENSAR=ver, leido a call-time):
        # ademas del spinner, el fragmento se streamea como prosa tenue verde
        # italica con la marca '∴' al inicio de cada linea. TokenTexto o
        # ToolInicio cierran este flujo con una linea en blanco.
        if self._pensar_en_vivo() and (ev.fragmento or ""):
            if self._flujo_pensar is None:
                self._flujo_pensar = FlujoSuave(
                    console=self._console, style=self._estilo_pensar_stream(),
                    sangria=_SANGRIA_PENSAR)
            self._flujo_pensar.escribir(ev.fragmento)

    def _on_token_texto(self, ev: events.TokenTexto) -> None:
        # un token vacio no abre el flujo: si lo abriera, TareaFin creeria que
        # la respuesta ya se streameo y se tragaria el resumen final
        if not ev.texto:
            return
        if self._sin_stream:
            return    # remoto: la respuesta final llega entera via _show_response
        self._cerrar_flujo_pensar()
        if self._flujo is None:
            # empieza la prosa: el spinner sobra y la respuesta respira arriba
            self._parar_status()
            respirar(self._console)
            self._flujo = FlujoSuave(console=self._console, style="cyan")
        self._flujo.escribir(ev.texto)

    def _on_aviso(self, ev: events.Aviso) -> None:
        # De-dup por texto: "[backend] via=..." salia 10+ veces por turno en
        # la evidencia baseline. Una vez informa; diez tapan la respuesta.
        clave = ("aviso", ev.texto)
        if not ev.texto or clave in self._avisos_vistos:
            return
        self._avisos_vistos.add(clave)
        # si llega en medio del streaming, terminar la linea de prosa primero
        # (sin esto el aviso se incrustaba dentro de una frase a medias)
        self._cerrar_flujo()
        self._print(f"{_SANGRIA}{ev.texto}", style="info_dim")

    def _on_degradado(self, ev: events.Degradado) -> None:
        clave = ("degradado", ev.donde, ev.motivo)
        if clave in self._avisos_vistos:
            return
        self._avisos_vistos.add(clave)
        self._parar_status()
        self._cerrar_flujo()
        linea = f"{_SANGRIA}{_MARCA_AVISO} degradado — {ev.donde}"
        if ev.motivo:
            linea += f": {ev.motivo}"
        self._print(linea, style="warn_cl")
        if ev.accion_sugerida:
            self._print(f"{_SANGRIA}  → {ev.accion_sugerida}", style="warn_cl")

    def _on_tarea_fin(self, ev: events.TareaFin) -> None:
        self._parar_status()
        self._cerrar_flujo_pensar()
        if self._flujo is not None:
            # la respuesta ya se streameo: no re-imprimirla, solo cerrar
            self._cerrar_flujo()
        # El resumen del evento NO se imprime aqui (cazado en el e2e
        # 2026-08-09): TareaFin se emite ANTES del post-procesado de cli.py
        # (adjuntos de rutas, 2a pasada), asi que el texto del evento esta
        # incompleto y ademas el handler de /hacer muestra la respuesta
        # enriquecida — imprimirla aqui la duplicaba. El resumen queda en el
        # evento para el sink JSONL/remoto; en pantalla va solo el footer.
        self._footer(ev)

    # -- respuesta final y footer ------------------------------------------

    def _respuesta_final(self, texto: str, ok: bool = True) -> None:
        """Markdown renderizado si hay rich (titulos, listas, codigo con
        sintaxis); sin rich cae a estilo.respuesta (prosa envuelta plana)."""
        if self._console is not None:
            try:
                from rich.markdown import Markdown
                from rich.padding import Padding
                respirar(self._console)
                self._console.print(
                    Padding(Markdown(texto), (0, 2)),
                    style=None if ok else "warn_cl")
                respirar(self._console)
                return
            except Exception:
                pass
        respuesta(texto, console=self._console,
                  color="cyan" if ok else "yellow")

    def _footer(self, ev: events.TareaFin) -> None:
        """Footer HONESTO: solo datos reales del evento. Sin usage del
        backend no se inventan tokens (el len//4 historico mentia).

        El glifo ✓/✗ delante es SOLO local: bajo COGNIA_REMOTO el footer debe
        seguir matcheando _RE_FOOTER_RENDERER del de-dup de sesiones.py
        ('^\\d+(\\.\\d+)?s...'), y un prefijo lo rompe — ahi va plano como hoy."""
        dur = ev.duracion_s or (ev.ts - self._t0 if self._t0 else 0.0)
        if dur < 1.0:
            return
        partes = [f"{dur:.1f}s"]
        if ev.tokens_predichos > 0:
            partes.append(f"{ev.tokens_predichos} tokens")
        if ev.pasos > 0:
            partes.append(f"{ev.pasos} paso" + ("s" if ev.pasos != 1 else ""))
        resto = " · ".join(partes)
        remoto = (self._sin_stream
                  or os.environ.get("COGNIA_REMOTO", "").strip() == "1")
        if not remoto and self._console is not None:
            try:
                from rich.text import Text
                glifo, est = ("✓", "ok_cl") if ev.ok else ("✗", "err_cl")
                self._console.print(
                    Text.assemble((_SANGRIA, ""), (glifo, est), (" ", ""),
                                  (resto, "footer")),
                    highlight=False)
                return
            except Exception:
                pass
        self._print(f"{_SANGRIA}{resto}", style="footer")

    _HANDLERS = {
        "TareaInicio":      _on_tarea_inicio,
        "PasoIntencion":    _on_paso_intencion,
        "ToolInicio":       _on_tool_inicio,
        "ToolFin":          _on_tool_fin,
        "RazonamientoTick": _on_razonamiento_tick,
        "TokenTexto":       _on_token_texto,
        "Aviso":            _on_aviso,
        "Degradado":        _on_degradado,
        "TareaFin":         _on_tarea_fin,
    }


# ---------------------------------------------------------------------------
# Singleton del CLI: un solo renderer suscrito por proceso.
# ---------------------------------------------------------------------------
_renderer: Renderer | None = None


def activar(console=None) -> Renderer:
    """Crea (una vez) y suscribe el renderer al bus. Idempotente: suscribir()
    ya de-duplica, y re-llamar con otra console actualiza la referencia (el
    CLI puede cambiar de tema y reconstruir su Console)."""
    global _renderer
    if _renderer is None:
        _renderer = Renderer(console)
    elif console is not None:
        _renderer._console = console
    events.suscribir(_renderer)
    return _renderer


def desactivar() -> None:
    global _renderer
    if _renderer is not None:
        events.desuscribir(_renderer)
        _renderer._parar_status()
        _renderer = None
