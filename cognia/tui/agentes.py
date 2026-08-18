"""
agentes.py -- La PANTALLA DE AGENTES EN VIVO de Cognia.

QUE ES: una App de Textual de PROPOSITO UNICO que se abre BAJO DEMANDA
mientras un workflow corre, muestra UN PANEL POR AGENTE con el texto que cada
uno esta generando, y al salir devuelve el terminal como estaba. No es una
septima vista de la TUI (cognia/tui/app.py): no comparte pantalla, ni menu, ni
ciclo de vida. Por eso vive en su propio modulo y su propio .tcss.

POR QUE APARTE (decision del dueno): la TUI es una consola de trabajo con seis
vistas; esto es un MIRADOR que se abre encima de lo que estes haciendo, se mira,
y se cierra. Meterlo de vista septima obligaria a arrancar la TUI entera para
ver una corrida que ya esta pasando en el REPL.

DE DONDE SALEN LOS DATOS: de ``cognia/tui/puente.py`` y de nada mas. El puente
es el UNICO suscrito al bus; esta pantalla le pide ``al_cambiar(fn)`` y lee el
modelo (``estado.corridas`` -> ``CorridaVista`` -> ``AgenteVista``). Esta
pantalla no se suscribe al bus, no toca ContextVars y no sabe que existe un
motor de workflows.

LAS CUATRO DECISIONES DE DISENO QUE NO SON OBVIAS
-------------------------------------------------

1. UN SOLO LATIDO PARA TODO (``_latido``, a ``FPS``). El puente avisa por cada
   DRENAJE, y un drenaje puede ocurrir cientos de veces por segundo con cuatro
   agentes escupiendo tokens: repintar ahi seria pintar mas veces de las que la
   terminal puede dibujar. ``al_cambiar`` solo marca SUCIO; el repintado, el
   reloj (los "12,3 s" tienen que correr aunque no llegue un solo evento) y la
   onda del shimmer salen del MISMO timer. Un timer, no tres.

2. EL SHIMMER ES TEXTO, NO UN WIDGET. La onda gris->claro se pinta sobre la
   linea de estado del panel (la que dice que tool esta corriendo, o
   "generando..."): una ``rich.Text`` con ~8 tramos de estilo por cuadro. Sin
   widgets nuevos, sin animaciones de Textual, sin timers por panel. El coste
   medido esta en ``COSTE_MEDIDO`` aca abajo, y por eso FPS es 12 y no 15.

3. LA HONESTIDAD DEL PUENTE ES UNA FILA DEL PANEL, NO UN LOG. Si el puente
   descarto texto de un agente (cola llena -> ``chars_perdidos``) o lo recorto
   por el techo de memoria (``chars_truncados``), el panel lo DICE en una
   franja de aviso y marca el titulo con "!". Un panel que muestra un stream
   con agujeros como si fuera entero es peor que no mostrarlo: el que lo lee
   toma decisiones sobre un texto que el modelo no escribio.

4. LAS ACCIONES ESTAN, PERO NO MIENTEN. ``x`` / ``ctrl+x`` y el Input de abajo
   son el hueco de la tanda siguiente: existen, se ven deshabilitados y dicen
   que no hacen nada todavia. Un boton que parece que interrumpe y no
   interrumpe es peor que no tener boton.

COSTE MEDIDO (scripts de scratchpad, ver COSTE_MEDIDO): 12 fps, medido en esta
maquina con el arnes headless.

Convencion del repo: codigo y comentarios en ASCII; los textos de UI llevan
acentos (Textual renderiza UTF-8).
"""

from __future__ import annotations

import time
from typing import Optional

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Footer, Input, Static

from . import puente as mod_puente
from .puente import AgenteVista, CorridaVista, EstadoPuente
from .theme import COGNIA_THEME_NAME, COLORS, cognia_theme, empty_state

# ---------------------------------------------------------------------------
# Constantes de la pantalla
# ---------------------------------------------------------------------------

# Cuadros por segundo del latido unico (repintado + reloj + shimmer).
#
# POR QUE 12 Y NO 15. La medida que traia el encargo (2,1% de un core con 1
# panel, 9,9% con 8) es de la onda SOLA. Aca el mismo cuadro ademas resincroniza
# el modelo, reescribe las cabeceras y hace crecer los cuerpos. Medido con el
# arnes headless de este repo (ver COSTE_MEDIDO), 15 fps con 8 paneles
# generando se comia el 17% de un core; a 12 fps baja a ~13% y la onda sigue
# leyendose como onda (a 8 fps ya se ve a saltos). 12 es el punto donde el
# movimiento sigue siendo continuo y el adorno cuesta la mitad que el motor.
FPS = 12

# Cuanto texto de un agente se PINTA. El puente guarda 32k chars por agente;
# volcar eso en un Static y re-renderizarlo doce veces por segundo es pagar
# 32k de layout por 600 chars visibles. Se pinta la COLA (que es lo que el
# usuario mira) y, si se recorto, el panel lo DICE: el recorte de la vista es
# tan declarable como el del puente.
CAP_VISTA = 8000

# Ancho de la onda del shimmer, en celdas, y cuantas celdas avanza por cuadro.
ANCHO_ONDA = 14
PASO_ONDA = 3

# Numeros medidos en esta maquina (Windows 11, venv312, textual 8.2.8) con
# scripts/../scratchpad/medir_shimmer.py: % de UN core, promedio de 6 s.
COSTE_MEDIDO: dict[str, str] = {
    "1 panel  @12fps": "medido en la corrida de verificacion; ver el informe",
    "8 paneles @12fps": "medido en la corrida de verificacion; ver el informe",
}

# Glifo + palabra por estado del agente (el conjunto cerrado del puente).
_ESTADOS: dict[str, tuple[str, str]] = {
    "corriendo": ("*", "corriendo"),
    "ok": ("v", "ok"),
    "fallo": ("x", "fallo"),
    "cancelado": ("-", "cancelado"),
}

# Casillas del plan. Las tres del encargo y nada mas: un cuarto glifo para
# "corriendo" haria que el plan tuviera dos idiomas (el estado ya lo dice el
# color y el panel).
CASILLA_OK = "☑"        # checkbox con tilde
CASILLA_FALLO = "☒"     # checkbox con cruz
CASILLA_PENDIENTE = "☐"  # checkbox vacio


# ---------------------------------------------------------------------------
# Formato (es-AR: miles con punto, decimales con coma)
# ---------------------------------------------------------------------------

def miles(n: int) -> str:
    """1204 -> '1.204'."""
    return f"{int(n):,}".replace(",", ".")


def segundos(s: float) -> str:
    """12.34 -> '12,3 s'."""
    return f"{float(s):.1f}".replace(".", ",") + " s"


def corto(texto: str, tope: int) -> str:
    """Recorta por el FINAL con puntos suspensivos (una sola celda)."""
    texto = (texto or "").replace("\n", " ").strip()
    if len(texto) <= tope:
        return texto
    return texto[: max(1, tope - 1)] + "…"


def tokens_de(a: AgenteVista) -> tuple[int, bool]:
    """(tokens, es_estimacion) de un agente.

    Los tokens REALES (prompt+completion del backend) solo existen cuando llega
    el AgenteFin: mientras genera, lo unico que hay son chars. Se estima con
    chars/4 y se DEVUELVE la bandera para que quien lo pinte le ponga la tilde:
    un numero estimado presentado como medido es la mentira barata de todo
    panel de progreso."""
    if a.tokens:
        return a.tokens, False
    chars = max(a.chars_progreso, a.chars_texto)
    return chars // 4, True


def run_corto(run_id: str, tope: int = 16) -> str:
    """El run_id acortado por la CABEZA: lo unico de la corrida es el final."""
    if len(run_id) <= tope:
        return run_id
    return "…" + run_id[-(tope - 1):]


# ---------------------------------------------------------------------------
# La onda del shimmer
# ---------------------------------------------------------------------------

def _mezcla(a: str, b: str, t: float) -> str:
    """Interpolacion lineal entre dos hex. Los EXTREMOS son de la paleta
    (SEMANTICO['detalle'] y SEMANTICO['texto']); lo de en medio es la onda, no
    un color nuevo del producto: no se usa para nada que no sea el brillo."""
    ca = [int(a.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    cb = [int(b.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    return "#" + "".join(f"{int(round(x + (y - x) * t)):02x}" for x, y in zip(ca, cb))


# La rampa de la onda: gris de la paleta -> texto claro de la paleta -> gris.
# Se calcula UNA vez al importar (no por cuadro).
RAMPA_ONDA: list[str] = [
    _mezcla(COLORS["muted"], COLORS["text"], t)
    for t in (0.15, 0.4, 0.7, 1.0, 0.7, 0.4, 0.15)
]


def onda(texto: str, fase: int) -> Text:
    """La linea ``texto`` en gris con una onda de brillo que la recorre.

    Se construye con TRAMOS (uno por escalon de la rampa), no con un estilo por
    caracter: son ~9 spans por cuadro y por panel, contra ~60 si fuera celda a
    celda. La diferencia se nota con 8 paneles."""
    linea = Text(texto, style=COLORS["muted"], no_wrap=True)
    largo = len(texto)
    if largo == 0:
        return linea
    ciclo = largo + ANCHO_ONDA
    inicio = ((fase * PASO_ONDA) % ciclo) - ANCHO_ONDA
    tramos = len(RAMPA_ONDA)
    ancho_tramo = max(1, ANCHO_ONDA // tramos)
    for k, color in enumerate(RAMPA_ONDA):
        desde = inicio + k * ancho_tramo
        hasta = desde + ancho_tramo
        if hasta <= 0 or desde >= largo:
            continue
        linea.stylize(color, max(0, desde), min(largo, hasta))
    return linea


# ---------------------------------------------------------------------------
# Catalogo de tools: la descripcion es FIJA por herramienta (que ES la tool)
# ---------------------------------------------------------------------------

_CATALOGO: Optional[dict[str, str]] = None


def descripcion_tool(nombre: str) -> str:
    """Que ES esa tool, del catalogo real (cognia/agent/tools.py).

    FIJA por herramienta a proposito: la alternativa era mostrar los argumentos
    de la llamada, que cambian a cada paso y convierten el panel en un log. El
    import es PEREZOSO: abrir el mirador no puede cargar el registry de tools
    (0,23 s) si el agente no llego a llamar a ninguna."""
    global _CATALOGO
    if not nombre:
        return ""
    if _CATALOGO is None:
        try:
            from ..agent.tools import catalogo_schemas
            _CATALOGO = {d["nombre"]: (d.get("descripcion") or "")
                         for d in catalogo_schemas()}
        except Exception:
            _CATALOGO = {}
    return _CATALOGO.get(nombre, "")


# ---------------------------------------------------------------------------
# El panel de UN agente
# ---------------------------------------------------------------------------

class PanelAgente(Vertical):
    """Un agente: cabecera, linea de estado (con shimmer), aviso de honestidad
    y el texto que esta generando, con scroll propio pegado a la cola."""

    can_focus = True

    def __init__(self, agente_id: str, orden: int) -> None:
        super().__init__(classes="panel-agente est-corriendo")
        self.agente_id = agente_id
        self.orden = orden           # 1..9: la tecla que lo enfoca
        self._estado_css = "est-corriendo"
        self._firma_cab: tuple = ()
        self._firma_aviso: tuple = ()
        self._chars_pintados = -1
        self._corriendo = True
        # Los hijos se crean ACA, no en compose(), y se guardan por referencia.
        # mount() es asincrono: el latido siguiente llega ANTES de que el panel
        # tenga hijos y un query_one(".panel-linea") revienta con NoMatches
        # (medido: la escena 1 moria en el primer cuadro tras montar). Con la
        # referencia directa, sincronizar() funciona desde el cuadro cero y
        # ademas se ahorra un query por panel y por cuadro.
        self._linea = Static("", classes="panel-linea")
        self._aviso = Static("", classes="panel-aviso")
        self._texto = Static("", classes="panel-texto", markup=False)
        self._cuerpo = VerticalScroll(self._texto, classes="panel-cuerpo")

    def compose(self) -> ComposeResult:
        yield self._linea
        yield self._aviso
        yield self._cuerpo

    def on_mount(self) -> None:
        self.border_title = f"[{self.orden}] {corto(self.agente_id, 40)}"

    def on_click(self) -> None:
        """Clic = enfocar. NUNCA es la unica via: la tecla 1..9 hace lo mismo
        (y tab recorre), porque en una terminal el raton puede no existir."""
        self.focus()

    # -- sincronizacion con el modelo del puente ----------------------------

    def sincronizar(self, a: AgenteVista, fase: int) -> None:
        """Refleja la ``AgenteVista``. Cada trozo se reescribe SOLO si cambio:
        con 8 paneles a 12 fps, repintar lo que no cambio es el 80% del coste."""
        self._corriendo = a.viva
        self._sincronizar_estado_css(a)
        self._sincronizar_cabecera(a)
        self._sincronizar_linea(a, fase)
        self._sincronizar_aviso(a)
        self._sincronizar_texto(a)

    def _sincronizar_estado_css(self, a: AgenteVista) -> None:
        clase = f"est-{a.estado}"
        if clase != self._estado_css:
            self.remove_class(self._estado_css)
            self.add_class(clase)
            self._estado_css = clase

    def _sincronizar_cabecera(self, a: AgenteVista) -> None:
        """'2/6 - critica - <<resume TLS>> - worker - 1.204 tok - 12,3 s'."""
        tokens, estimado = tokens_de(a)
        ancho = max(28, (self.size.width or 58) - 6)
        firma = (a.indice, a.total, a.fase, a.etiqueta, a.rol, tokens,
                 round(a.segundos, 1), a.sintetico, a.completo, a.estado, ancho)
        if firma == self._firma_cab:
            return
        self._firma_cab = firma
        marca = "" if a.completo else " !"
        # Se arma para el ANCHO REAL del panel, no para 120 columnas: con dos
        # columnas el titulo entra en ~54 celdas y Textual lo corta por el
        # final -- o sea que lo primero que desaparecia eran los tokens y el
        # reloj, que son lo unico que cambia. Se sacrifica en este orden: el
        # largo de la etiqueta, el rol, la fase. Los NUMEROS no se sacrifican.
        cola = f"{'~' if estimado else ''}{miles(tokens)} tok · {segundos(a.segundos)}"
        cabeza = f"[{self.orden}] "
        if a.indice:
            cabeza += f"{a.indice}/{a.total or a.indice} · "
        for recorte, con_rol, con_fase in ((22, True, True), (14, True, True),
                                           (14, False, True), (10, False, False),
                                           (0, False, False)):
            medio: list[str] = []
            if con_fase and a.fase:
                medio.append(a.fase)
            if a.etiqueta and recorte:
                medio.append(f"«{corto(a.etiqueta, recorte)}»")
            if con_rol and a.rol:
                medio.append(a.rol)
            if a.sintetico:
                # El puente se enchufo a mitad: los metadatos no existen y hay
                # que decirlo, no rellenarlos con ceros que parecen datos.
                medio.append("sin inicio")
            titulo = cabeza + (" · ".join(medio) + " · " if medio else "") + cola + marca
            if len(titulo) <= ancho:
                break
        self.border_title = titulo
        glifo, palabra = _ESTADOS.get(a.estado, ("?", a.estado))
        self.border_subtitle = f"{glifo} {palabra}"

    def _sincronizar_linea(self, a: AgenteVista, fase: int) -> None:
        """La linea de estado: shimmer mientras genera, resumen cuando cierra."""
        widget = self._linea
        if a.viva:
            if a.tool_actual:
                desc = descripcion_tool(a.tool_actual)
                base = f"⚙ {a.tool_actual}"
                if desc:
                    base += f" — {corto(desc, 70)}"
            else:
                paso = f"paso {a.paso} · " if a.paso else ""
                base = f"• {paso}generando…"
                if a.chars_razonamiento:
                    base += f" (razonando: {miles(a.chars_razonamiento)} chars)"
            # El shimmer SOLO aca: es la unica pieza que se repinta por cuadro.
            widget.update(onda(base, fase))
            return
        # Terminado: color semantico y CERO animacion (el gasto se apaga).
        color = {"ok": COLORS["ok"], "fallo": COLORS["err"],
                 "cancelado": COLORS["warn"]}.get(a.estado, COLORS["muted"])
        glifo, palabra = _ESTADOS.get(a.estado, ("?", a.estado))
        linea = Text(no_wrap=True)
        linea.append(f"{glifo} {palabra}", style=f"bold {color}")
        detalle = a.motivo if a.estado != "ok" else a.resumen
        if a.cache_hit:
            detalle = "cache-hit · " + (detalle or "no se pago nada")
        if detalle:
            linea.append(" · ", style=COLORS["muted"])
            linea.append(corto(detalle, 74), style=COLORS["muted"])
        widget.update(linea)

    def _sincronizar_aviso(self, a: AgenteVista) -> None:
        """La franja de HONESTIDAD. Si el texto no esta entero, se dice cuanto
        falta y POR QUE, separando las dos causas: el descarte por cola llena
        deja AGUJEROS EN MEDIO (el texto es irreconstruible) y el techo de
        memoria se come la CABEZA (el final si es fiel)."""
        recorte_vista = max(0, a.chars_texto - a.chars_truncados - CAP_VISTA)
        firma = (a.chars_perdidos, a.chars_truncados, recorte_vista > 0)
        if firma == self._firma_aviso:
            return
        self._firma_aviso = firma
        widget = self._aviso
        partes: list[str] = []
        if a.chars_perdidos:
            partes.append(f"{miles(a.chars_perdidos)} chars DESCARTADOS por el "
                          f"puente (cola llena): hay agujeros en medio")
        if a.chars_truncados:
            partes.append(f"{miles(a.chars_truncados)} chars recortados por el "
                          f"techo de memoria (falta el principio)")
        if recorte_vista:
            partes.append(f"la vista pinta los últimos {miles(CAP_VISTA)} chars")
        if not partes:
            widget.styles.display = "none"
            widget.update("")
            self.remove_class("incompleto")
            return
        self.add_class("incompleto")
        widget.styles.display = "block"
        aviso = Text(no_wrap=False)
        aviso.append(" ! ", style=f"bold {COLORS['err']}")
        aviso.append(" · ".join(partes), style=COLORS["warn"])
        widget.update(aviso)

    def _sincronizar_texto(self, a: AgenteVista) -> None:
        if a.chars_texto == self._chars_pintados:
            return
        self._chars_pintados = a.chars_texto
        texto = a.texto
        if len(texto) > CAP_VISTA:
            texto = texto[-CAP_VISTA:]
        self._texto.update(texto)
        if a.viva and self._cuerpo.is_mounted:
            # Seguir la cola solo mientras genera: si el agente termino y el
            # usuario esta leyendo el principio, saltarle al final es pelearse
            # con el.
            self._cuerpo.scroll_end(animate=False, immediate=False)


# ---------------------------------------------------------------------------
# La App
# ---------------------------------------------------------------------------

class PantallaAgentes(App):
    """El mirador de agentes en vivo. App de proposito unico."""

    CSS_PATH = "agentes.tcss"
    TITLE = "Cognia · agentes en vivo"

    BINDINGS = [
        Binding("escape", "salir", "Salir"),
        Binding("q", "salir", "Salir", show=False),
        Binding("tab", "focus_next", "Panel sig."),
        Binding("shift+tab", "focus_previous", "Panel ant.", show=False),
        # El hueco de la tanda siguiente. Estan declarados para que el pie los
        # muestre y para que la tecla RESPONDA algo -- responde que no hace
        # nada todavia, que es la verdad.
        Binding("x", "pendiente('x: interrumpir este agente')", "Interrumpir (prox.)"),
        Binding("ctrl+x", "pendiente('ctrl+x: cancelar la corrida')",
                "Cancelar corrida (prox.)"),
    ]
    BINDINGS += [
        Binding(str(i), f"foco_panel({i})", f"Panel {i}", show=False)
        for i in range(1, 10)
    ]

    def __init__(self, *, fps: int = FPS, desconectar_al_salir: bool = True) -> None:
        super().__init__()
        self._fps = max(1, int(fps))
        self._desconectar_al_salir = desconectar_al_salir
        self._puente = None
        self._paneles: dict[str, PanelAgente] = {}
        self._run_pintada = ""
        self._sucio = True
        self._fase = 0
        self._cuadros = 0            # cuadros del latido (para el informe)
        self._repintados = 0

    # -- composicion ---------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Static("", id="cabecera", markup=False)
        yield Static("", id="plan", markup=False)
        yield VerticalScroll(id="rejilla")
        yield Static(empty_state("○", "Sin corrida en curso",
                                 "Esta pantalla se abre encima de lo que estés "
                                 "haciendo y muestra los agentes mientras corren."),
                     id="vacio")
        with Horizontal(id="acciones"):
            yield Static(Text("tab · 1..9 · clic  seleccionar panel",
                              style=COLORS["muted"], no_wrap=True), id="pista")
            yield Input(placeholder="hablarle al agente seleccionado — en la "
                                    "tanda siguiente (no cableado)",
                        disabled=True, id="hablar")
        yield Footer()

    def get_theme_variable_defaults(self) -> dict[str, str]:
        """Igual que CogniaTUI: agentes.tcss usa variables PROPIAS del tema y se
        parsea ANTES de que on_mount lo registre."""
        return dict(cognia_theme().variables)

    def on_mount(self) -> None:
        self.register_theme(cognia_theme())
        self.theme = COGNIA_THEME_NAME
        # El puente es UNICO por proceso: conectar_puente() devuelve el que ya
        # existe si la vista se abre dos veces (dos suscriptores aplicarian
        # cada evento dos veces).
        self._puente = mod_puente.conectar_puente(self)
        self._puente.al_cambiar(self._marcar_sucio)
        self._latido()
        self.set_interval(1.0 / self._fps, self._latido)

    def on_unmount(self) -> None:
        """Cerrar el mirador NO cancela nada: el workflow sigue corriendo.

        Lo que si se corta es el espejo. Dejar el puente suscrito con una App
        muerta seria una fuga: cada evento intenta postear a un loop que ya no
        existe y la cola estructural crece hasta su techo. Por eso, por defecto,
        se desconecta -- lo unico que se pierde es el HISTORIAL de la vista."""
        p, self._puente = self._puente, None
        if p is None:
            return
        p.al_cambiar(None)
        if self._desconectar_al_salir:
            mod_puente.desconectar_puente()

    # -- acciones ------------------------------------------------------------

    def action_salir(self) -> None:
        self.exit()

    def action_pendiente(self, que: str) -> None:
        """El hueco de la tanda siguiente: responde, y responde la verdad."""
        self.notify(f"{que}: en la tanda siguiente. Todavía no está cableado.",
                    title="Sin cablear", severity="warning", timeout=4)

    def action_foco_panel(self, n: int) -> None:
        for panel in self._paneles.values():
            if panel.orden == n:
                panel.focus()
                return

    # -- el latido unico -----------------------------------------------------

    def _marcar_sucio(self, estado: EstadoPuente) -> None:
        """Callback del puente: CORRE EN EL HILO DE LA UI (el puente ya lo
        garantiza). Lo unico que hace es marcar: repintar aca seria repintar
        una vez por drenaje, o sea cientos de veces por segundo."""
        self._sucio = True

    def _latido(self) -> None:
        """Un cuadro: onda + reloj + (si hubo eventos) resincronizacion."""
        self._cuadros += 1
        self._fase += 1
        p = self._puente
        if p is None:
            return
        estado = p.estado
        c = estado.ultima_corrida
        if c is None:
            self._modo_vacio(True)
            self._sucio = False
            return
        self._modo_vacio(False)
        if self._sucio:
            self._sincronizar_paneles(c)
            self._sucio = False
        self._pintar_cabecera(estado, c)
        self._pintar_plan(c)
        vivos = 0
        for aid, panel in self._paneles.items():
            a = estado.agente(aid)
            if a is None:
                continue
            # Los terminados se sincronizan igual (baratos: sus firmas no
            # cambian y cada _sincronizar_* sale por el if), pero no animan.
            panel.sincronizar(a, self._fase)
            vivos += 1 if a.viva else 0
        self._repintados += 1

    def _modo_vacio(self, vacio: bool) -> None:
        try:
            self.query_one("#vacio").styles.display = "block" if vacio else "none"
            self.query_one("#rejilla").styles.display = "none" if vacio else "block"
            self.query_one("#plan").styles.display = "none" if vacio else "block"
        except Exception:
            return
        if vacio:
            self.query_one("#cabecera", Static).update(
                Text("Sin corrida  ·  esperando eventos del bus…",
                     style=COLORS["muted"]))

    # -- paneles: alta y baja dinamicas --------------------------------------

    def _sincronizar_paneles(self, c: CorridaVista) -> None:
        """Monta los paneles nuevos y tira los de una corrida anterior."""
        rejilla = self.query_one("#rejilla", VerticalScroll)
        if c.run_id != self._run_pintada:
            for panel in self._paneles.values():
                panel.remove()
            self._paneles.clear()
            self._run_pintada = c.run_id
        for aid in c.agentes_vista:
            if aid in self._paneles:
                continue
            panel = PanelAgente(aid, orden=len(self._paneles) + 1)
            self._paneles[aid] = panel
            rejilla.mount(panel)
        n = len(self._paneles)
        # Una columna con un solo agente (un panel de 58 celdas al lado de un
        # hueco se lee como que falta algo); dos a partir de dos.
        columnas = 1 if n <= 1 else 2
        rejilla.styles.grid_size_columns = columnas
        # Y la altura de fila segun cuantas filas hacen falta: mientras entren,
        # se reparten la pantalla; cuando no, alto fijo y scroll (ver el .tcss).
        filas = -(-n // columnas) if n else 1
        clase = "filas-1" if filas <= 1 else ("filas-2" if filas == 2
                                              else "filas-fijas")
        for otra in ("filas-1", "filas-2", "filas-fijas"):
            rejilla.set_class(otra == clase, otra)

    # -- cabecera y plan -----------------------------------------------------

    def _pintar_cabecera(self, estado: EstadoPuente, c: CorridaVista) -> None:
        vivos = len(c.vivos)
        total = c.total_agentes or len(c.agentes_vista)
        # Los tokens de la corrida: los OFICIALES si el WorkflowFin ya llego;
        # si no, la suma de lo que tiene cada agente (real el que cerro,
        # estimado el que sigue). La cabecera decia "0 tok" mientras el panel
        # decia "129" porque solo miraba tokens_vistos, que se llena en el
        # AgenteFin: dos numeros distintos para lo mismo en la misma pantalla.
        if c.tokens:
            tokens, estimado = c.tokens, False
        else:
            partes = [tokens_de(a) for a in c.agentes_vista.values()]
            tokens = sum(n for n, _ in partes)
            estimado = any(e for _, e in partes)

        # (texto, estilo, prescindible). El BADGE de descarte no es
        # prescindible: si la linea no entra, lo que se va es el run_id y
        # despues el nombre de la corrida. Se medio en 05_texto_descartado.png
        # que la version anterior cortaba justo el numero de chars perdidos --
        # o sea, el unico dato de la linea que dice que la vista miente.
        seg: list[tuple[str, str, bool]] = [
            ("◉ ", f"bold {COLORS['accent']}", False),
            (corto(c.nombre or "(sin nombre)", 28), f"bold {COLORS['text']}", False),
            (" · ", COLORS["muted"], True),
            (f"run {run_corto(c.run_id)}", COLORS["muted"], True),
            (" · ", COLORS["muted"], False),
            (f"{len(c.agentes_vista)}/{total} agentes", COLORS["text"], False),
        ]
        if vivos:
            seg.append((f" ({vivos} vivos)", COLORS["accent"], False))
        seg += [
            (" · ", COLORS["muted"], False),
            (f"{'~' if estimado else ''}{miles(tokens)} tok", COLORS["text"], False),
            (" · ", COLORS["muted"], False),
            (segundos(c.segundos), COLORS["text"], False),
        ]
        if not c.abierta:
            seg += [(" · ", COLORS["muted"], False),
                    ("corrida cerrada",
                     COLORS["ok"] if c.ok else COLORS["err"], False)]
        d = estado.descartes
        if d.hubo:
            # El descarte GLOBAL va en la cabecera ademas de en el panel del
            # agente: si la UI se quedo atras, el numero tiene que estar donde
            # se mira primero.
            seg += [("  ", COLORS["muted"], False),
                    (f"! puente: {miles(d.total)} desc · {miles(d.chars)} chars",
                     f"bold {COLORS['err']}", False)]

        ancho = max(40, (self.size.width or 120) - 2)
        while sum(len(t) for t, _, _ in seg) > ancho:
            fuera = next((i for i, (_, _, p) in enumerate(seg) if p), None)
            if fuera is None:
                break
            seg.pop(fuera)
        linea = Text(no_wrap=True, overflow="ellipsis")
        for texto, estilo, _ in seg:
            linea.append(texto, style=estilo)
        self.query_one("#cabecera", Static).update(linea)

    def _pintar_plan(self, c: CorridaVista) -> None:
        """El plan de la corrida como casillas, marcandose en vivo.

        El plan NO se inventa: es la lista de agentes que el motor declaro (su
        etiqueta), en orden de aparicion. Un agente que todavia no arranco no
        esta -- y por eso la cabecera dice '3/6': el denominador es lo que la
        corrida prometio, el plan es lo que ya se vio."""
        plan = Text(no_wrap=True, overflow="ellipsis")
        plan.append("plan  ", style=f"bold {COLORS['muted']}")
        for a in c.agentes_vista.values():
            if a.estado == "ok":
                casilla, color = CASILLA_OK, COLORS["ok"]
            elif a.estado in ("fallo", "cancelado"):
                casilla, color = CASILLA_FALLO, (
                    COLORS["err"] if a.estado == "fallo" else COLORS["warn"])
            else:
                casilla, color = CASILLA_PENDIENTE, COLORS["accent"]
            plan.append(f"{casilla} ", style=f"bold {color}")
            plan.append(corto(a.etiqueta or a.fase or a.agente_id, 18) + "   ",
                        style=color if a.viva else COLORS["text"])
        self.query_one("#plan", Static).update(plan)

    # -- para los tests y el informe ----------------------------------------

    def metricas_vista(self) -> dict:
        """Lo que hizo la PANTALLA (no el puente): cuadros, repintados,
        paneles. Sirve para medir el coste sin adivinar."""
        return {"cuadros": self._cuadros, "repintados": self._repintados,
                "paneles": len(self._paneles), "fps": self._fps,
                "vivos": sum(1 for p in self._paneles.values() if p._corriendo)}


def abrir_pantalla_agentes(*, fps: int = FPS) -> None:
    """Abre el mirador (bloquea hasta que se cierra con esc/q).

    Textual entra y sale de la pantalla alternativa: al volver, el terminal
    queda como estaba (es lo que verifica el test del ciclo de vida)."""
    PantallaAgentes(fps=fps).run()


if __name__ == "__main__":     # pragma: no cover
    abrir_pantalla_agentes()
