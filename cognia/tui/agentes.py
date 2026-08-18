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

LAS SEIS DECISIONES DE DISENO QUE NO SON OBVIAS
-----------------------------------------------
(decia "CUATRO" y la lista tiene SEIS desde que se agregaron el scroll por
teclado y la vista desconectada: mismo defecto D8 que los "doce cuadros por
segundo" de mas abajo, un numero de otra version que sobrevivio al cambio.)

1. UN SOLO LATIDO PARA TODO (``_latido``, a ``FPS``). El puente avisa por cada
   DRENAJE, y un drenaje puede ocurrir cientos de veces por segundo con cuatro
   agentes escupiendo tokens: repintar ahi seria pintar mas veces de las que la
   terminal puede dibujar. ``al_cambiar`` solo marca SUCIO; el repintado, el
   reloj (los "12,3 s" tienen que correr aunque no llegue un solo evento) y la
   onda del shimmer salen del MISMO timer. Un timer, no tres.

2. EL SHIMMER ES TEXTO, NO UN WIDGET. La onda gris->claro se pinta sobre la
   linea de estado del panel (la que dice que tool esta corriendo, o
   "generando..."): una ``rich.Text`` con ~7 tramos de estilo por cuadro (uno
   por escalon de ``RAMPA_ONDA``). Sin widgets nuevos, sin animaciones de
   Textual, sin timers por panel. Y se APAGA sola: un panel que termino no
   vuelve a tocar su linea.

   CORRECCION 2026-08-18 (esto lo decia mal y la medicion vieja quedo
   invalidada). Hasta hoy la frase era "la corrida entera cerrada cuesta lo
   mismo que una pantalla quieta", y era FALSO: la rama del agente terminado
   era la unica de las cinco ``_sincronizar_*`` sin guarda de firma, y
   ``_pintar_cabecera`` / ``_pintar_plan`` llamaban ``update(layout=True)``
   cada cuadro sin comparar nada. MEDIDO con todo cerrado antes del arreglo:
   49 cuadros -> 245 ``update()`` reales (5 widgets x 49); la pantalla VACIA,
   35 cuadros -> 35 ``update()`` de la cabecera. Como el brazo "congelado" de
   la medicion vieja seguia repintando, NO era el piso, y el "+4,8 pts" que se
   le atribuia al shimmer media contra un suelo falso. Ahora las CINCO ramas
   tienen guarda y el control honesto es "timer parado vs timer vivo sin nada
   que cambiar": ver ``COSTE_MEDIDO`` aca abajo.

3. LA HONESTIDAD DEL PUENTE ES UNA FILA DEL PANEL, NO UN LOG. Si el puente
   descarto texto de un agente (cola llena -> ``chars_perdidos``) o lo recorto
   por el techo de memoria (``chars_truncados``), el panel lo DICE en una
   franja de aviso y marca el titulo con "!". Un panel que muestra un stream
   con agujeros como si fuera entero es peor que no mostrarlo: el que lo lee
   toma decisiones sobre un texto que el modelo no escribio.

4. LAS ACCIONES MANDAN DE VERDAD, Y NO TRADUCEN LA RESPUESTA (2026-08-18).
   ``x`` llama a ``workflows.cancelar_agente(agente_id)``, ``ctrl+x`` a
   ``cancelar_corrida(run_id)`` con confirmacion, y el Input a
   ``workflows.decirle(agente_id, texto)``. Hasta hoy eran una maqueta que
   avisaba "en la tanda siguiente"; ahora el envelope del motor se pinta TAL
   CUAL en la fila ``#respuesta``: su ``estado`` del conjunto cerrado
   (aceptado | ya_cancelado | ya_termino | desconocido_agente | corrida_cerrada
   | desconocido_corrida | texto_vacio | buzon_lleno), su ``detalle`` y sus
   tres contadores. La vista NO decide si "salio bien": ese envelope se diseno
   justo para que la UI no invente, y tragarse un ``ya_termino`` o un
   ``buzon_lleno`` seria inventar.

   Las cuatro decisiones de esta parte:

   * EL BOTON SE LLAMA "INTERRUMPIR Y DECIR", no "enviar" (decision del dueno).
     La semantica real es que CORTA la generacion en curso, apendea el texto
     como turno del usuario y vuelve a llamar: se tira lo generado y cuesta una
     llamada mas de presupuesto. El placeholder del Input lo dice con esas
     palabras, porque un "enviar" haria pensar en un chat que no interrumpe
     nada.
   * ``ctrl+x`` MANDA EL run_id QUE SE ESTA VIENDO, nunca el "" que en el motor
     significa PANICO GLOBAL (corta todas las corridas vivas del proceso). Una
     pantalla que muestra una corrida no tiene por que cortar las que no
     muestra. Sin corrida en pantalla, ni siquiera abre el modal: lo dice.
   * LO QUE LA VISTA RECHAZA POR SU CUENTA SE DISTINGUE. Un aviso de la vista
     ("no hay ningun panel seleccionado") empieza con "⚠" y no trae la palabra
     del conjunto cerrado; una respuesta del motor va prefijada con "motor:" y
     esa palabra es literal. Asi no se confunde una excusa de la UI con un
     veredicto del motor.
   * EL DESTINO ES EL PANEL SELECCIONADO, y sigue seleccionado mientras se
     escribe. Con el foco dentro del Input NINGUN panel tiene ``:focus``, asi
     que "el agente enfocado" dejaria de existir justo al escribirle: se
     recuerda el ultimo panel enfocado (clase ``seleccionado``) y su nombre va
     en el placeholder, para que nunca haya duda de a quien se le habla.

5. EL TEXTO SE LEE SIN RATON. El cuerpo de cada panel scrollea con
   arriba/abajo, RePag/AvPag e Inicio/Fin cuando el panel tiene el foco, y el
   ``#pista`` lo DICE. No alcanza con que el VerticalScroll exista: es
   ``can_focus = False`` (si no, tab se quedaba adentro del panel), y las
   bindings de scroll de Textual viven en el scrollable ENFOCADO -- o sea que
   sin estas acciones el teclado no movia nada y 275 de 300 filas solo se
   alcanzaban con la rueda (medido). Regla del dueno: el clic nunca puede ser
   la unica via. Ademas, desplazarse a mano SUELTA la cola: la vista deja de
   saltar al final mientras estas leyendo arriba, y ``Fin`` la reengancha.

6. UNA VISTA DESCONECTADA LO DICE. El puente es unico por proceso; si se abre
   una SEGUNDA pantalla, ``conectar_puente()`` desconecta el puente de la
   primera y crea uno nuevo (puente.py: compara ``p.app is not app``). La
   primera quedaba montada, con su timer a 15 fps, mostrando datos congelados
   y sin un solo suscriptor en el bus -- en silencio. Ahora ``_latido`` mira
   ``conectado`` / ``app`` y pinta la franja ``#desconectada``, y ademas
   CONGELA el resto del cuadro (una vista que no recibe nada no tiene por que
   animar). Y al salir se desconecta con ``solo_de=self``: el
   ``desconectar_puente()`` pelado es GLOBAL y apagaba el puente de otra
   pantalla viva.

COSTE MEDIDO (arnes headless de este repo, ver ``COSTE_MEDIDO``): la tabla se
RE-MIDIO el 2026-08-18 con el control honesto -- el timer PARADO -- y con UNO,
TRES y OCHO paneles, despues de poner guarda de firma en las cinco ramas. Los
numeros que importan: con la corrida cerrada el latido ya casi no se paga
(+0,43 / +0,27 / +0,62 pts con 1/3/8 paneles, dentro del grano del contador;
lo exacto es el conteo, que es 0 repintados en 120 cuadros en los tres
tamanos); con paneles VIVOS la pantalla gasta 4,2% / 5,9% / 9,2% de un core,
de los que **+1,7 / +1,8 / +2,7 pts** son el shimmer (15/15 tomas del mismo
signo) y no los +4,8 que decia la tabla de antes del arreglo, medidos contra un
control que tambien repintaba. Bajar a 12 fps se probo y no cambia el numero.

UN NUMERO QUE NO SE REPLICO, y va dicho: la tanda anterior declaro que con UN
panel el shimmer "cambia de signo y no se despega del ruido". Con 5 tomas
apareadas dio +1,68 y las cinco positivas. No cambio el codigo entremedio:
cambio el ruido de la medicion (aquel brazo congelado de un panel daba una
banda de 3 puntos para la escena que aca dio 0,8). Ver COSTE_MEDIDO.

Convencion del repo: codigo y comentarios en ASCII; los textos de UI llevan
acentos (Textual renderiza UTF-8).
"""

from __future__ import annotations

from typing import Optional

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Footer, Input, Static

from . import puente as mod_puente
from .puente import AgenteVista, CorridaVista, EstadoPuente
from .theme import COGNIA_THEME_NAME, COLORS, cognia_theme, empty_state
from .widgets.modals import ConfirmModal


def motor():
    """``cognia.agent.workflows``, importado la PRIMERA vez que se manda algo.

    Perezoso por dos razones medidas, no por gusto: importarlo arriba le suma
    0,20 s al import de esta pantalla (medido en esta maquina) para un modulo
    que solo hace falta si el usuario aprieta una tecla, y ata el mirador al
    motor -- hoy la pantalla se puede importar y abrir sin que exista ninguna
    corrida. El puente sigue siendo la UNICA fuente de datos: de aca solo salen
    ORDENES (cancelar / decir), nunca estado para pintar.

    No se cachea a mano: sys.modules ya es el cache, y una variable de modulo
    seria un segundo estado que los tests tendrian que limpiar."""
    from cognia.agent import workflows
    return workflows

# ---------------------------------------------------------------------------
# Constantes de la pantalla
# ---------------------------------------------------------------------------

# Cuadros por segundo del latido unico (repintado + reloj + shimmer).
#
# 15 FPS, Y ESTA MEDIDO (scratchpad/medir_shimmer.py, esta maquina, textual
# 8.2.8, headless 120x38, ventanas de 15 s x3). Se probo bajar a 12 y NO SE
# PAGA: el proceso entero gasta 12,8-13,7% de un core a 12 fps y 12,2-13,4% a
# 15 con ocho paneles animando, o sea lo mismo dentro del ruido. Bajar un
# parametro por una diferencia que no supera el ruido es justo lo que este
# repo tiene prohibido. Si un terminal lento lo pide, el knob existe:
# PantallaAgentes(fps=...).
FPS = 15

# Cuanto texto de un agente se PINTA. El puente guarda 32k chars por agente;
# volcar eso en un Static y re-renderizarlo QUINCE veces por segundo (= FPS;
# aca decia "doce" de cuando el knob valia 12, y ademas ubicaba a FPS "ocho
# lineas mas arriba" cuando estaba a tres: una referencia POSICIONAL es un
# numero que se pudre solo, asi que se nombra la constante y listo) es pagar
# 32k de layout por 600 chars visibles. Se pinta la COLA (que es lo que el
# usuario mira) y, si se recorto, el panel lo DICE: el recorte de la vista es
# tan declarable como el del puente.
CAP_VISTA = 8000

# Ancho de la onda del shimmer, en celdas, y cuantas celdas avanza por cuadro.
ANCHO_ONDA = 14
PASO_ONDA = 3

# EL COSTE, MEDIDO (ver el docstring de arriba).
#
# QUE PASO CON LA COLUMNA "en-cuadro". La tabla vieja daba dos numeros por
# escena: "en-cuadro" (perf_counter acumulado DENTRO de _latido) y "proceso"
# (psutil user+system del proceso entero). Se quedo solo el segundo: el
# "en-cuadro" es mas estable (+-0,02 pts entre corridas) pero NO incluye el
# repintado que Textual agenda DESPUES del refresh, que es justo donde estaba
# el bug que motivo esta re-medicion -- un contador que no ve el repintado
# fantasma no puede ser el que lo desmienta. El de proceso lo incluye todo, y
# se paga con grano: en Windows el contador tiene 15,6 ms, por eso van rangos
# de varias tomas y no un numero solo. (time.process_time() se descarto por lo
# mismo: con esa granularidad devolvia 0,00 en las escenas de un panel.)
#
# EL CONTROL, RE-HECHO (2026-08-18). El brazo de control de la medicion vieja
# era "linea congelada": ocho agentes TERMINADOS, o sea cero shimmer. Se creia
# que eso era el piso y NO LO ERA -- con todo cerrado la pantalla seguia
# llamando update() cinco veces por cuadro (medido: 49 cuadros -> 245 updates),
# asi que el "+4,8 pts" que se le cobraba al shimmer incluia el repintado
# fantasma del propio control. El numero viejo esta REEMPLAZADO, no defendido.
#
# El control honesto de ahora son DOS brazos, no uno:
#   * "timer parado": el latido no corre. Es el piso absoluto del proceso
#     (Textual quieto en su loop) y da el cero contra el que se resta todo.
#   * "timer vivo, nada que cambiar": la corrida CERRADA con las guardas
#     puestas. Mide lo que cuesta el latido en si -- leer el estado, comparar
#     firmas y no pintar. Es el brazo que la version vieja no tenia.
# La diferencia animando - "timer vivo, nada que cambiar" es el shimmer LIMPIO.
# RE-MEDIDO 2026-08-18 (scratchpad/t5b_arreglos/p5_coste.py + p5_driver.py):
# textual 8.2.8, headless 120x38, UN PROCESO POR BRAZO Y POR TOMA, ventanas de
# 10 s, brazos INTERCALADOS (toma 1 de todos, despues toma 2...) para que una
# racha de la maquina no le caiga entera a un solo brazo. La metrica es psutil
# user+system del proceso entero en % de UN core; en Windows ese contador tiene
# 15,6 ms de grano, por eso va el rango de las tomas y nunca un numero solo.
#
# DOS CORRIDAS DE 6 TOMAS, y se declaran las dos: la varianza ENTRE corridas es
# real (el shimmer con 8 paneles dio +2,13 en una y +3,02 en la otra) y esconder
# una atras de la otra seria repetir el error que motivo esta re-medicion. Los
# rangos de abajo son min-max de las 12 tomas.
#
# Las RESTAS son APAREADAS por toma (mismo par, misma vuelta): restar el min de
# un rango contra el max de otro le suma el ruido de la maquina, que es comun a
# los dos brazos.
COSTE_MEDIDO: dict[str, str] = {
    # -- EL CONTROL HONESTO: el timer PARADO, con 1, 3 y 8 paneles -----------
    "piso: 1 panel,   TIMER PARADO":  "0,00-0,00% (media 0,00); 0 cuadros, 0 repintados",
    "piso: 3 paneles, TIMER PARADO":  "0,00-0,39% (media 0,20); 0 cuadros, 0 repintados",
    "piso: 8 paneles, TIMER PARADO":  "0,00-0,58% (media 0,19); 0 cuadros, 0 repintados",
    # -- el latido vivo sin nada que cambiar (la corrida CERRADA) ------------
    "corrida CERRADA, timer vivo, 1 panel":
        "0,00-0,78% (media 0,43); 120 cuadros y 0 REPINTADOS",
    "corrida CERRADA, timer vivo, 3 paneles":
        "0,20-0,98% (media 0,47); 120 cuadros y 0 REPINTADOS",
    "corrida CERRADA, timer vivo, 8 paneles":
        "0,20-1,37% (media 0,82); 120 cuadros y 0 REPINTADOS",
    "pantalla VACIA, timer vivo":
        "0,00-1,36% (media 0,51); 120 cuadros y 0 REPINTADOS",
    # -- paneles VIVOS, con la linea congelada y animando --------------------
    # Los 80 repintados de 150 (de 120) de la fila congelada son el RELOJ, que
    # cambia 10 veces por segundo; no el shimmer.
    "1 panel VIVO, linea congelada":   "2,14-2,93% (media 2,54);  80/120 repintados",
    "1 panel VIVO, animando":          "3,71-5,26% (media 4,21); 120/120 repintados",
    "3 paneles VIVOS, linea congelada": "3,70-4,69% (media 4,14);  80/120 repintados",
    "3 paneles VIVOS, animando":        "4,87-6,43% (media 5,89); 120/120 repintados",
    "8 paneles VIVOS, linea congelada": "5,66-7,40% (media 6,55);  80/120 repintados",
    "8 paneles VIVOS, animando":        "8,78-9,76% (media 9,21); 120/120 repintados",
    # -- las restas, APAREADAS por toma --------------------------------------
    "lo que cuesta EL LATIDO con las guardas (cerrada - timer parado)":
        "+0,43 / +0,27 / +0,62 pts con 1 / 3 / 8 paneles, y con 1 y 3 CAMBIA DE"
        " SIGNO entre tomas: esta en el grano del contador (15,6 ms). Lo que SI"
        " es exacto porque es un conteo y no un reloj: 0 repintados en 120"
        " cuadros, en los tres tamanos.",
    "lo que cuesta el SHIMMER (animando - congelada)":
        "+1,68 (1 panel) / +1,75 (3) / +2,66 (8) pts de media; 15/15 tomas del"
        " MISMO signo. REEMPLAZA al '+4,8 pts' de la tabla de antes del"
        " arreglo, que se restaba contra un control que tambien repintaba.",
    "OJO -- LO QUE ESTA TABLA CORRIGE DE LA ANTERIOR (1 panel)":
        "la tanda de arreglos declaro que con UN panel el shimmer 'cambia de"
        " signo y no se despega del ruido' (+0,59 y -0,31). NO SE REPLICA: con"
        " 5 tomas apareadas dio +1,68 de media y las CINCO positivas (+0,98 a"
        " +2,72). El brazo congelado de aquella tanda daba 1,87-4,99% con 1"
        " panel -- una banda de 3 puntos para una escena que aca dio 2,14-2,93"
        " --, asi que lo que cambio es el RUIDO de la medicion, no el codigo"
        " (no se toco nada del shimmer entremedio). Se declara la contradiccion"
        " en vez de elegir la corrida que quedaba mejor.",
    "lo que cuesta tener los agentes VIVOS (animando - timer parado)":
        "+4,21 (1 panel) / +5,69 (3) / +9,01 (8) pts, 15/15 tomas del mismo"
        " signo. De esos, 1,7 / 1,8 / 2,7 son el shimmer y el resto es el reloj"
        " y el texto entrando.",
    "8 paneles @12fps (probado y descartado, medicion anterior)":
        "indistinguible de 15 fps; no se re-midio porque el arreglo no toca el"
        " knob y esa conclusion no dependia del control roto",
    "COMO SE MIDIO":
        "scratchpad/t5b_final/r7_coste.py + r7_driver.py, 2026-08-18: textual"
        " 8.2.8, headless 120x38, UN PROCESO POR BRAZO Y POR TOMA, ventanas de"
        " 8 s, 13 brazos x 5 tomas INTERCALADAS, psutil user+system del proceso"
        " entero en % de UN core (grano de 15,6 ms en Windows: por eso rangos y"
        " restas apareadas, nunca un numero solo).",
}


# La pista del pie: la ANCHA y la COMPACTA. Las DOS nombran las tres familias
# de teclas -- mover el foco, LEER el texto y MANDAR -- porque una tecla que
# corta un agente y no esta escrita en ningun lado se descubre por accidente.
#
# NINGUNA DE LAS DOS SE RECORTA. Con las teclas de accion la version larga pasa
# de 71 a 116 celdas y la compacta mide 95: en una terminal de 80 (o de 60) no
# hay version de una fila que diga las tres cosas sin mentir por omision, asi
# que la compacta se deja ENVOLVER en dos filas (`#pista` es height: auto y
# `_pintar_pista` le pasa no_wrap=False). Es la misma decision que la franja de
# desconexion: una linea cuyo trabajo es DECIR las vias no puede tapar una.
# Largos MEDIDOS (`len` + 2 por el padding 0 1 de #acciones): 116+2 y 95+2.
PISTA_ANCHA = ("tab · 1..9 · clic  panel    ↑↓ · RePág/AvPág · Inicio/Fin  leer"
               "    x  interrumpir · ctrl+x  corrida · enter  decirle")
PISTA_COMPACTA = ("tab/1-9 panel · ↑↓ RePág/AvPág Inicio/Fin leer · "
                  "x interrumpir · ctrl+x corrida · enter decirle")


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
# LA ARITMETICA DEL ANCHO, EN UN SOLO SITIO
# ---------------------------------------------------------------------------
# Un panel de ancho EXTERIOR W tiene DOS anchos utiles distintos, y confundirlos
# fue el mismo bug tres veces: el titulo cortado sin marca, la linea de estado
# cortada sin marca y el badge de descarte cortado justo en el numero de chars
# perdidos. Por eso las dos cuentas viven aca y NADIE las escribe a mano.
#
#   +-- W celdas exteriores ------------------------------+
#   | ╭─ titulo ────────────────────────────────────────╮ |  <- W-6 para el titulo
#   | │ contenido del panel                             │ |  <- W-4 para el cuerpo
#
# MEDIDO (scratchpad/t5b_arreglos/p1_ancho.py, textual 8.2.8, panel de 58
# exteriores, leyendo el compositor y no el SVG):
#   * border-title de 52 chars -> se pinta ENTERO; de 53 -> 51 chars + "…".
#     O sea 52 = W-6. La cuenta anterior era W-4 = 54 y por eso un titulo que
#     "entraba" segun el codigo se pintaba con elipsis: la marca de que hay
#     texto perdido era JUSTO lo que se perdia.
#   * un Static dentro del panel entra en 54 = W-4, y de ahi en adelante se
#     corta EN SECO -- no_wrap recorta y no avisa. Por eso la linea de estado
#     se recorta con corto() ANTES de darsela al widget: la elipsis la tiene
#     que poner el codigo, porque el renderer no la pone.
MARCO_BORDE = 4      # borde (2) + padding 0 1 (2): exterior -> contenido
MARCO_TITULO = 6     # "╭─ " + titulo + " ─╮": exterior -> celdas del titulo


def ancho_contenido(exterior: int, minimo: int = 20) -> int:
    """Celdas utiles DENTRO del panel (donde vive la linea de estado)."""
    return max(minimo, int(exterior or 58) - MARCO_BORDE)


def ancho_titulo(exterior: int, minimo: int = 18) -> int:
    """Celdas utiles del border-title de un panel de ancho exterior dado."""
    return max(minimo, int(exterior or 58) - MARCO_TITULO)


# CUANDO DEJAN DE CABER DOS COLUMNAS (2026-08-18, defecto encontrado al
# re-verificar D11: "los NUMEROS no se sacrifican").
#
# La escalera de degradacion del titulo tiene un ULTIMO peldano: "[N] i/total"
# mas los numeros. Ese peldano mide 30 celdas en su peor caso realista
# ("[8] 8/8 · 12.345 tok · 123,4 s"), y por debajo de eso ya no hay nada que
# soltar: lo que sobra lo corta el renderer, y lo que corta el renderer es la
# COLA, o sea el reloj y parte de los tokens. MEDIDO con la terminal
# redimensionada de verdad (scratchpad/t5b_final/r2_trece.py, 84 titulos
# PINTADOS entre 56 y 164 columnas): a 56, 60 y 64 columnas los tres paneles
# salian como "[1] 1/3 · 1.204 tok…" -- el reloj perdido, con elipsis pero
# perdido. La promesa era que los numeros no se sacrifican nunca.
#
# El arreglo NO es otro peldano (no queda nada prescindible): es no partir la
# pantalla en dos cuando cada mitad no da. Con #rejilla en `padding: 0 1` a
# cada lado y `grid-gutter: 1`, un panel de dos columnas mide (W-3)//2, asi que
# el peldano de 30 celdas necesita (W-3)//2 >= 30+MARCO_TITULO = 36, o sea
# W >= 75. Se toma 76 (par, y con una celda de aire). Debajo de eso: UNA
# columna, donde el mismo peldano entra desde 38 columnas de terminal. La tabla
# entera esta en scratchpad/t5b_final/r3_umbral.py.
ANCHO_MIN_2COL = 76


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
    caracter: son como mucho len(RAMPA_ONDA)+1 = 8 spans por cuadro y por panel
    (el comentario decia "~9" y la rampa tiene 7 entradas), contra ~60 si fuera
    celda a celda. La diferencia se nota con 8 paneles."""
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

    # LEER EL TEXTO SIN RATON. Estas bindings viven en el PANEL y no en el
    # VerticalScroll de adentro a proposito: el cuerpo es can_focus = False
    # (si no, tab se quedaba dentro del panel en vez de pasar al siguiente) y
    # las bindings de scroll que trae Textual de fabrica solo disparan en el
    # scrollable ENFOCADO. Sin esto, el teclado no movia una fila: medido con
    # 300 lineas, up/down/pageup/pagedown/home/end dejaban scroll_y en 0 y las
    # 275 filas de arriba solo se alcanzaban con la rueda del raton.
    BINDINGS = [
        # TAB VIVE ACA Y NO EN LA APP, Y ES UN BUG ENCONTRADO AL CABLEAR
        # (2026-08-18). La App declaraba `tab -> panel(1)` y esa binding NUNCA
        # DISPARABA: Screen trae de fabrica `tab -> app.focus_next` y la
        # pantalla se resuelve ANTES que la App. Funcionaba de casualidad
        # porque los unicos widgets focusables eran los paneles, asi que
        # focus_next los recorria igual; al habilitar el Input, `tab` desde el
        # ultimo panel se iba al campo de texto (medido: foco tras tab -> input
        # True, action_panel llamado -> []). En el WIDGET ENFOCADO la binding
        # gana, y "app.panel" despacha a la App.
        Binding("tab", "app.panel(1)", "Panel sig."),
        Binding("shift+tab", "app.panel(-1)", "Panel ant.", show=False),
        Binding("up", "desplazar(-1)", "Subir", show=False),
        Binding("down", "desplazar(1)", "Bajar", show=False),
        Binding("pageup", "desplazar_pagina(-1)", "Página arriba", show=False),
        Binding("pagedown", "desplazar_pagina(1)", "Página abajo", show=False),
        Binding("home", "ir_al_principio", "Principio", show=False),
        Binding("end", "ir_al_final", "Final", show=False),
    ]

    def __init__(self, agente_id: str, orden: int) -> None:
        super().__init__(classes="panel-agente est-corriendo")
        self.agente_id = agente_id
        self.orden = orden           # 1..9: la tecla que lo enfoca
        # Como se llama este agente EN CRIOLLO, para nombrarlo fuera del panel
        # (el placeholder del Input y la fila de respuesta dicen a quien se le
        # habla). Arranca con el id porque hasta el primer sincronizar() es lo
        # unico que se sabe de el.
        self.etiqueta = agente_id
        self._estado_css = "est-corriendo"
        self._firma_cab: tuple = ()
        self._firma_aviso: tuple = ()
        self._firma_linea: tuple = ()
        self._chars_pintados = -1
        self._corriendo = True
        # Mientras el agente genera, la vista sigue la COLA. En cuanto el
        # usuario se desplaza a mano deja de seguirla: saltarle al final a
        # alguien que esta leyendo arriba es pelearse con el. `Fin` reengancha.
        self._seguir_cola = True
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
        # El cuerpo NO es focusable: un VerticalScroll de Textual lo es por
        # defecto y tab se paraba DENTRO del panel en vez de pasar al
        # siguiente. El scroll con rueda y el :focus-within siguen andando.
        self._cuerpo.can_focus = False
        # El titulo va aca y no en on_mount: mount() es asincrono, asi que el
        # on_mount llegaba DESPUES del primer sincronizar y le pisaba la
        # cabecera con el placeholder. El agente que ya habia cerrado se
        # quedaba para siempre con su agente_id crudo de titulo (medido).
        self.border_title = f"[{orden}] {corto(agente_id, 40)}"

    def compose(self) -> ComposeResult:
        yield self._linea
        yield self._aviso
        yield self._cuerpo

    def on_click(self) -> None:
        """Clic = enfocar. NUNCA es la unica via: la tecla 1..9 hace lo mismo
        (y tab recorre), porque en una terminal el raton puede no existir."""
        self.focus()

    def on_focus(self, event=None) -> None:
        """Enfocar tambien SELECCIONA, y la seleccion sobrevive al foco.

        Las acciones (x / ctrl+x / el Input) necesitan un destino, y mientras
        se escribe en el Input NINGUN panel tiene el foco: si el destino fuera
        `has_focus`, al empezar a tipear el agente destinatario dejaria de
        existir. La App recuerda el ultimo enfocado y le pone la clase
        `seleccionado` (ver el .tcss) para que se vea a quien se le va a
        hablar."""
        app = self.app
        recordar = getattr(app, "_recordar_seleccion", None)
        if recordar is not None:
            recordar(self.agente_id)

    # -- leer el texto con el teclado ---------------------------------------

    def action_desplazar(self, paso: int) -> None:
        self._seguir_cola = False
        self._cuerpo.scroll_relative(y=paso, animate=False)

    def action_desplazar_pagina(self, paso: int) -> None:
        self._seguir_cola = False
        alto = max(1, self._cuerpo.size.height - 1)
        self._cuerpo.scroll_relative(y=paso * alto, animate=False)

    def action_ir_al_principio(self) -> None:
        self._seguir_cola = False
        self._cuerpo.scroll_home(animate=False)

    def action_ir_al_final(self) -> None:
        """Fin REENGANCHA la cola: es la unica forma de decirle a la pantalla
        'segui vos' despues de haber leido para arriba."""
        self._seguir_cola = True
        self._cuerpo.scroll_end(animate=False)

    def on_mouse_scroll_up(self, event) -> None:
        """Subir con la rueda suelta la cola igual que subir con el teclado (el
        evento sube burbujeando desde el cuerpo; no se consume)."""
        self._seguir_cola = False

    # -- sincronizacion con el modelo del puente ----------------------------

    def sincronizar(self, a: AgenteVista, fase: int) -> bool:
        """Refleja la ``AgenteVista``. Cada trozo se reescribe SOLO si cambio:
        con ocho paneles a 15 fps, reescribir lo que no cambio se paga quince
        veces por segundo y por panel.

        Devuelve si TOCO algo. Lo devuelve porque ``metricas_vista()`` decia
        "repintados" y contaba cuadros: sumaba uno por latido con corrida,
        pintara o no (medido: cuadros=36, repintados=35 con todo cerrado). Una
        metrica que existe para medir sin adivinar no puede ser un alias de
        otra."""
        self._corriendo = a.viva
        self.etiqueta = a.etiqueta or a.fase or a.agente_id
        toco = self._sincronizar_estado_css(a)
        toco = self._sincronizar_cabecera(a) or toco
        toco = self._sincronizar_linea(a, fase) or toco
        toco = self._sincronizar_aviso(a) or toco
        toco = self._sincronizar_texto(a) or toco
        return toco

    def _sincronizar_estado_css(self, a: AgenteVista) -> bool:
        clase = f"est-{a.estado}"
        if clase == self._estado_css:
            return False
        self.remove_class(self._estado_css)
        self.add_class(clase)
        self._estado_css = clase
        return True

    def _sincronizar_cabecera(self, a: AgenteVista) -> bool:
        """'2/6 - critica - <<resume TLS>> - worker - 1.204 tok - 12,3 s'."""
        tokens, estimado = tokens_de(a)
        # El ancho util del border-title NO es el del contenido: son W-6, no
        # W-4. La cuenta esta en ancho_titulo() con su medicion; el comentario
        # que habia aca decia W-4 y por eso los titulos de 53 y 54 celdas
        # "entraban" segun el codigo y se pintaban con elipsis -- y lo que la
        # elipsis se comia era la cola, o sea los tokens y el reloj (D11: los
        # NUMEROS no se sacrifican) o el " !" de honestidad (D1: la marca de
        # que falta texto era justo lo que se perdia).
        ancho = ancho_titulo(self.outer_size.width)
        firma = (a.indice, a.total, a.fase, a.etiqueta, a.rol, tokens,
                 round(a.segundos, 1), a.sintetico, a.completo, a.estado, ancho)
        if firma == self._firma_cab:
            return False
        self._firma_cab = firma
        marca = "" if a.completo else " !"
        # Se arma para el ANCHO REAL del panel, no para 120 columnas: con dos
        # columnas el titulo entra en ~54 celdas y Textual lo corta por el
        # final -- o sea que lo primero que desaparecia eran los tokens y el
        # reloj, que son lo unico que cambia. Se sacrifica en este orden: el
        # largo de la etiqueta, el rol, la fase. Los NUMEROS no se sacrifican.
        #
        # Y ESA PROMESA TIENE UN PISO, que la escalera sola no puede sostener:
        # el ultimo peldano mide 30 celdas y por debajo de eso corta el
        # renderer. Lo que lo sostiene es ANCHO_MIN_2COL (no partir la pantalla
        # en dos cuando cada mitad no da); con UNA columna el peldano entra
        # desde 38 columnas de terminal. Medido en r2_trece.py / r3_umbral.py.
        cola = f"{'~' if estimado else ''}{miles(tokens)} tok · {segundos(a.segundos)}"
        cabeza = f"[{self.orden}] "
        if a.indice:
            cabeza += f"{a.indice}/{a.total or a.indice} · "
        # La escalera de degradacion. El peldano (10, False, True) se agrego el
        # 2026-08-18: sin el, el salto de (14,False,True) a (10,False,False)
        # tiraba la FASE y recortaba la etiqueta EN EL MISMO paso, o sea que la
        # fase se perdia antes de que la etiqueta terminara de encogerse --
        # justo al reves del orden declarado (etiqueta -> rol -> fase). Medido:
        # panel de 58, "[1] 1/3 · pasos · «leer hand…» · 1.204 tok · 12,3 s"
        # mide 51 y entraba en 52, y aun asi salia sin "pasos".
        for recorte, con_rol, con_fase in ((22, True, True), (14, True, True),
                                           (14, False, True), (10, False, True),
                                           (10, False, False), (0, False, False)):
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
        return True

    def _sincronizar_linea(self, a: AgenteVista, fase: int) -> bool:
        """La linea de estado: shimmer mientras genera, resumen cuando cierra."""
        widget = self._linea
        ancho = ancho_contenido(self.outer_size.width)
        if a.viva:
            if a.tool_actual:
                desc = descripcion_tool(a.tool_actual)
                base = f"⚙ {a.tool_actual}"
                if desc:
                    base += f" — {desc}"
            else:
                paso = f"paso {a.paso} · " if a.paso else ""
                base = f"• {paso}generando…"
                if a.chars_razonamiento:
                    base += f" (razonando: {miles(a.chars_razonamiento)} chars)"
            # Recorte contra el ancho REAL del panel, no contra un 70 fijo: el
            # Static corta en seco y sin elipsis (medido: 54 celdas y el resto
            # desaparece), asi que la elipsis la tiene que poner corto().
            # El shimmer SOLO aca: es la unica pieza que se repinta por cuadro.
            # layout=False: la linea mide 1 fila por CSS y no cambia nunca.
            # El default de Static.update es layout=True, o sea un relayout del
            # panel entero quince veces por segundo y por panel, por un texto
            # que ya se sabe que mide lo mismo.
            self._firma_linea = ()
            widget.update(onda(corto(base, ancho), fase), layout=False)
            return True
        # Terminado: color semantico, CERO animacion y GUARDA DE FIRMA. Esta
        # rama era la unica de las cinco sin guarda: con la corrida cerrada
        # seguia llamando update() quince veces por segundo y por panel con un
        # texto identico, y por eso el brazo "congelado" de la medicion vieja
        # no era el piso que decia ser.
        detalle = a.motivo if a.estado != "ok" else a.resumen
        if a.cache_hit:
            detalle = "cache-hit · " + (detalle or "no se pago nada")
        firma = (a.estado, detalle, ancho)
        if firma == self._firma_linea:
            return False
        self._firma_linea = firma
        color = {"ok": COLORS["ok"], "fallo": COLORS["err"],
                 "cancelado": COLORS["warn"]}.get(a.estado, COLORS["muted"])
        glifo, palabra = _ESTADOS.get(a.estado, ("?", a.estado))
        cabeza = f"{glifo} {palabra}"
        linea = Text(no_wrap=True)
        linea.append(cabeza, style=f"bold {color}")
        if detalle:
            # AHI VIVE EL MOTIVO DEL FALLO. Antes se recortaba a 74 chars, un
            # numero sin relacion con el panel: con dos columnas el panel mide
            # 54 utiles y un motivo de 103 se pintaba como "x fallo ·
            # RuntimeError: backend caido (connection" -- 29 celdas perdidas,
            # sin elipsis y sin ninguna marca.
            resto = ancho - len(cabeza) - 3      # los 3 son " · "
            if resto >= 2:
                linea.append(" · ", style=COLORS["muted"])
                linea.append(corto(detalle, resto), style=COLORS["muted"])
            else:
                # No entra ni un pedazo util: se dice que HAY motivo y no cabe,
                # en vez de pintar medio caracter o de callarlo.
                linea.append(" …", style=COLORS["muted"])
        widget.update(linea, layout=False)
        return True

    def _sincronizar_aviso(self, a: AgenteVista) -> bool:
        """La franja de HONESTIDAD. Si el texto no esta entero, se dice cuanto
        falta y POR QUE, separando las dos causas: el descarte por cola llena
        deja AGUJEROS EN MEDIO (el texto es irreconstruible) y el techo de
        memoria se come la CABEZA (el final si es fiel).

        TERCERA CAUSA, desde que el Input manda de verdad (2026-08-18): TUS
        INTERRUPCIONES. "Interrumpir y decir" corta la generacion y TIRA lo
        generado -- el modelo no lo ve nunca mas--, pero el panel lo sigue
        mostrando pegado a lo que vino despues, sin costura. MEDIDO en la
        corrida real contra :8080 (p2_real.py): el journal anota corte
        causa='mensaje' con 460 chars descartados y el panel pintaba
        "...actualizadaLISTO" como si fuera un solo turno. El texto de arriba
        es cierto (el modelo lo escribio), lo que no es cierto es que sea UNA
        respuesta: se dice cuantas veces se lo interrumpio y cuanto se tiro."""
        ancho = ancho_contenido(self.outer_size.width)
        recorte_vista = max(0, a.chars_texto - a.chars_truncados - CAP_VISTA)
        firma = (a.chars_perdidos, a.chars_truncados, recorte_vista > 0,
                 a.mensajes_aceptados, a.descartado_chars, ancho)
        if firma == self._firma_aviso:
            return False
        self._firma_aviso = firma
        widget = self._aviso
        partes: list[str] = []
        if a.mensajes_aceptados:
            # `descartado_chars` lo declara el AgenteFin, o sea que mientras el
            # agente vive todavia no esta: se dice lo que se sabe y nada mas.
            cuanto = (f" ({miles(a.descartado_chars)} chars tirados)"
                      if a.descartado_chars else "")
            veces = ("1 vez" if a.mensajes_aceptados == 1
                     else f"{a.mensajes_aceptados} veces")
            partes.append(f"interrumpido {veces}{cuanto}: lo descartado el "
                          f"modelo ya no lo ve, y acá sigue pegado a lo de "
                          f"después")
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
            return True
        self.add_class("incompleto")
        widget.styles.display = "block"
        aviso = Text(no_wrap=False)
        aviso.append(" ! ", style=f"bold {COLORS['err']}")
        # LA FRANJA TAMPOCO PUEDE CORTARSE EN SECO (2026-08-18). El .tcss le
        # pone `max-height: 2` para que no se coma el texto del agente, y hasta
        # hoy lo que no entraba DESAPARECIA sin marca -- el mismo D2 que se
        # arreglo en la linea de estado, en la franja que existe para declarar
        # que falta algo. Se cayo con la causa nueva (la interrupcion), que es
        # la mas larga: a dos columnas el panel da 54 celdas y el aviso se
        # pintaba solo hasta la mitad (medido en 06_decirle_aceptado.png).
        # El presupuesto son las DOS filas menos el " ! " y menos un margen de
        # 6 celdas: el wrap corta por PALABRA y la primera fila casi nunca se
        # llena entera, asi que contar 2x54 exacto todavia desborda.
        cupo = max(20, ancho * 2 - len(" ! ") - 6)
        aviso.append(corto(" · ".join(partes), cupo), style=COLORS["warn"])
        widget.update(aviso)
        return True

    def _sincronizar_texto(self, a: AgenteVista) -> bool:
        if a.chars_texto == self._chars_pintados:
            return False
        self._chars_pintados = a.chars_texto
        texto = a.texto
        if len(texto) > CAP_VISTA:
            texto = texto[-CAP_VISTA:]
        self._texto.update(texto)
        if a.viva and self._seguir_cola and self._cuerpo.is_mounted:
            # Seguir la cola solo mientras genera Y mientras el usuario no se
            # haya ido a leer para arriba con el teclado o la rueda: si el
            # agente termino, o si alguien esta leyendo el principio, saltarle
            # al final es pelearse con el.
            self._cuerpo.scroll_end(animate=False, immediate=False)
        return True


# ---------------------------------------------------------------------------
# La App
# ---------------------------------------------------------------------------

class PantallaAgentes(App):
    """El mirador de agentes en vivo. App de proposito unico."""

    CSS_PATH = "agentes.tcss"
    TITLE = "Cognia · agentes en vivo"

    # NADIE ARRANCA CON EL FOCO, Y ESO ES DELIBERADO (2026-08-18).
    #
    # App.AUTO_FOCUS es "*", o sea que la pantalla enfoca el primer widget
    # focusable al montarse. Mientras el Input estuvo deshabilitado eso no
    # enfocaba nada; al cablearlo, el Input pasa a ser focusable y se quedaba
    # con el foco de arranque: `2` escribia un "2" en el campo en vez de
    # enfocar el panel 2 y `x` tipeaba una equis en vez de interrumpir (lo
    # cazaron tres tests de teclado que ya existian). La cadena vacia es falsy
    # y corta el `if auto_focus` de Screen -- misma tecnica y misma razon que
    # el AUTO_FOCUS del ConfirmModal.
    #
    # Y NO se enfoca un panel "para que algo tenga foco": el primer panel
    # quedaria de destinatario de `x` sin que el usuario lo eligiera nunca.
    # Sin seleccion, `x` contesta que no hay a quien cortar.
    AUTO_FOCUS = ""

    BINDINGS = [
        Binding("escape", "salir", "Salir"),
        Binding("q", "salir", "Salir", show=False),
        # tab / shift+tab NO estan aca: viven en PanelAgente.BINDINGS porque
        # Screen ya trae `tab -> app.focus_next` y una binding de App pierde
        # contra la de la pantalla (ver el comentario del panel). Declararla
        # aca era codigo muerto que parecia funcionar.
        # LAS ACCIONES, CABLEADAS AL MOTOR (2026-08-18). Antes eran
        # `action_pendiente`, que avisaba "en la tanda siguiente".
        #
        # `x` no pide confirmacion y `ctrl+x` si: cortar UN agente es
        # reversible en el sentido que importa (los demas siguen y el usuario
        # puede volver a lanzarlo), y cortar la CORRIDA se lleva puesto todo lo
        # que esta en vuelo. Un modal por cada `x` entrenaria a confirmar sin
        # leer, que es como se pierde el modal que si importa.
        #
        # `enter` NO manda: lleva el foco al Input. Mandar con enter desde el
        # panel exigiria un campo de texto invisible, y la tecla que manda
        # tiene que estar donde se escribe. El clic tambien enfoca el Input,
        # pero la regla del dueno es que el clic nunca sea la unica via.
        Binding("x", "interrumpir", "Interrumpir agente"),
        Binding("ctrl+x", "cancelar_corrida", "Cancelar corrida"),
        Binding("enter", "hablar", "Interrumpir y decir"),
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
        self._repintados = 0         # cuadros que PINTARON algo (D7)
        self._timer = None
        # Firmas de lo que ya esta pintado. Sin ellas, cabecera y plan hacian
        # update(layout=True) en cada cuadro aunque no cambiara un caracter.
        self._firma_cabecera: tuple = ()
        self._firma_plan: tuple = ()
        self._vacio_pintado: Optional[bool] = None
        self._motivo_desconexion: Optional[str] = None
        self._pista_nivel: Optional[int] = None
        # (columnas, clase de altura) ya aplicadas a #rejilla: la guarda que
        # deja llamar a _repartir_rejilla() por cuadro sin tocar el DOM.
        self._reparto: tuple = ()
        # A QUIEN le hablan las acciones: el ultimo panel ENFOCADO, no el que
        # tiene el foco ahora (mientras se escribe en el Input, el foco es del
        # Input y ningun panel lo tiene). "" = nadie seleccionado todavia.
        self._seleccionado = ""
        self._placeholder_de: Optional[tuple] = None  # guarda del placeholder
        # La ULTIMA respuesta del motor, cruda y sin interpretar, para el test
        # y para metricas_vista(). None = todavia no se mando nada.
        self._ultimo_envelope: Optional[dict] = None

    # -- composicion ---------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Static("", id="cabecera", markup=False)
        # La franja de "esta vista ya no recibe nada". Arranca oculta por CSS.
        yield Static("", id="desconectada", markup=False)
        yield Static("", id="plan", markup=False)
        rejilla = VerticalScroll(id="rejilla")
        rejilla.can_focus = False       # ver el comentario de _cuerpo
        yield rejilla
        yield Static(empty_state("○", "Sin corrida en curso",
                                 "Esta pantalla se abre encima de lo que estés "
                                 "haciendo y muestra los agentes mientras corren."),
                     id="vacio")
        # La pista va en su PROPIA fila, no al lado del Input. Cuando la pista
        # crecio para nombrar las teclas de lectura (D10) le comio el ancho al
        # Input y el placeholder se pintaba cortado justo en "(no cableado)":
        # dos declaraciones de honestidad peleandose por la misma fila, y la
        # que perdia era la que dice que el campo no hace nada.
        with Vertical(id="acciones"):
            # El texto real lo pone _pintar_pista() (depende del ancho).
            yield Static("", id="pista", markup=False)
            # LA RESPUESTA DEL MOTOR, TAL CUAL. Fila propia y PERSISTENTE, no
            # un toast: un `ya_termino` o un `buzon_lleno` que se desvanece a
            # los 4 segundos es lo mismo que tragarselo, y ademas no sale en
            # una captura. Dice "motor:" delante de la palabra del conjunto
            # cerrado para que no se confunda con un aviso de la vista.
            yield Static("", id="respuesta", markup=False)
            # El texto real lo pone _pintar_placeholder() (depende de a quien
            # se le hable). Ya NO esta deshabilitado: manda de verdad.
            yield Input(id="hablar")
        yield Footer()

    def get_theme_variable_defaults(self) -> dict[str, str]:
        """Igual que CogniaTUI: agentes.tcss usa variables PROPIAS del tema y se
        parsea ANTES de que on_mount lo registre."""
        return dict(cognia_theme().variables)

    def on_mount(self) -> None:
        self.register_theme(cognia_theme())
        self.theme = COGNIA_THEME_NAME
        # El puente es UNICO por proceso. OJO con la letra chica (el comentario
        # que habia aca decia que conectar_puente() "devuelve el que ya existe"
        # y eso solo vale para la MISMA App): con dos Apps distintas,
        # puente.py compara `p.app is not app`, desconecta el viejo y crea uno
        # nuevo. O sea que abrir una segunda pantalla DEJA A ESTA SIN PUENTE.
        # No se puede evitar desde aca -- lo que si se puede es no mentir: el
        # _latido lo detecta y lo pinta (ver _revisar_puente).
        self._puente = mod_puente.conectar_puente(self)
        self._puente.al_cambiar(self._marcar_sucio)
        self._pintar_pista()
        self._pintar_placeholder()
        self._latido()
        self._timer = self.set_interval(1.0 / self._fps, self._latido)

    def on_resize(self, event=None) -> None:
        # EL ANCHO SALE DEL EVENTO, NO DE self.size (2026-08-18). Cuando esta
        # funcion corre, `App.size` TODAVIA es el de antes: medido con un espia
        # (scratchpad/t5b_final/probe_resize.py) sobre 120 -> 60 -> 100, la App
        # vio [120, 120, 120, 60] con la terminal ya en 100. O sea que la pista
        # se recalculaba con el ancho VIEJO y quedaba un nivel atrasada para
        # siempre (nivel 0 -- el de dos filas -- en una terminal de 100). El
        # latido lo cubre igual, pero desde aca la respuesta es inmediata.
        ancho = getattr(getattr(event, "size", None), "width", 0) or None
        self._pintar_pista(ancho)
        # Y RE-REPARTIR LA REJILLA: el numero de columnas depende del ancho
        # (ANCHO_MIN_2COL) y hasta hoy se decidia una sola vez, al montar los
        # paneles. Encoger la terminal dejaba dos columnas de panel angosto con
        # el reloj recortado; agrandarla dejaba una sola columna con medio
        # ancho de aire.
        self._repartir_rejilla(ancho)

    def _pintar_pista(self, ancho: Optional[int] = None) -> bool:
        """La pista de abajo. Dice como SELECCIONAR, como LEER y como MANDAR.

        Las tres cosas y no dos: la version anterior solo decia como
        seleccionar (la unica via documentada para el texto largo era la rueda
        del raton, D10) y las teclas de accion no estaban porque no hacian
        nada. Ahora hacen.

        Tres niveles de ancho para DOS textos: ancho / compacto en una fila /
        el mismo compacto ENVUELTO en dos. El tercero existe porque por debajo
        de ~97 columnas no hay forma de decir las tres familias de teclas en
        una sola fila, y la salida no puede ser callarse una."""
        ancho = ancho or self.size.width or 120
        # 118 = las 116 celdas MEDIDAS de PISTA_ANCHA + el padding 0 1 de
        # #acciones; 97 = 95 + 2 de la compacta.
        nivel = 2 if ancho >= 118 else (1 if ancho >= 97 else 0)
        if nivel == self._pista_nivel:
            return False
        self._pista_nivel = nivel
        texto = PISTA_ANCHA if nivel == 2 else PISTA_COMPACTA
        try:
            self.query_one("#pista", Static).update(
                Text(texto, style=COLORS["muted"], no_wrap=(nivel > 0)))
        except Exception:
            return False
        return True

    def on_unmount(self) -> None:
        """Cerrar el mirador NO cancela nada: el workflow sigue corriendo.

        Lo que si se corta es el espejo. Dejar el puente suscrito con una App
        muerta seria una fuga: cada evento intenta postear a un loop que ya no
        existe y la cola estructural crece hasta su techo. Por eso, por defecto,
        se desconecta -- lo unico que se pierde es el HISTORIAL de la vista."""
        # PRIMERO el timer. Un tick que llega con el DOM ya desarmado revienta
        # con NoMatches y Textual lo escupe como traceback al salir: la ultima
        # impresion de la pantalla era un stack trace (medido en la corrida de
        # medicion). El guard de _latido lo cubre igual, pero lo correcto es
        # que el latido no exista despues del unmount.
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        p, self._puente = self._puente, None
        if p is None:
            return
        p.al_cambiar(None)
        if self._desconectar_al_salir:
            # solo_de=self: desconectar_puente() pelado es GLOBAL y apagaba el
            # puente de QUIEN SEA que lo tuviera. Con dos pantallas abiertas,
            # cerrar la primera (que ya ni estaba conectada) dejaba muda a la
            # segunda, que seguia viva y sin enterarse.
            mod_puente.desconectar_puente(solo_de=self)

    # -- acciones ------------------------------------------------------------

    def action_salir(self) -> None:
        """esc cierra la pantalla... salvo escribiendo, que devuelve el foco.

        El Input de Textual NO consume escape, asi que escape mientras se
        escribe llegaba hasta aca y CERRABA LA PANTALLA con el mensaje a medio
        tipear. Es el mismo error que arreglar q/x (esos si los come el Input
        como texto) y olvidarse del unico que se escapa."""
        if self._escribiendo():
            self._volver_a_la_rejilla()
            self._mostrar_aviso("cancelado: seguís en la pantalla; "
                                "esc otra vez para salir")
            return
        self.exit()

    def action_foco_panel(self, n: int) -> None:
        for panel in self._paneles.values():
            if panel.orden == n:
                panel.focus()
                return

    # -- a quien le hablan las acciones --------------------------------------

    def _recordar_seleccion(self, agente_id: str) -> None:
        """Lo llama PanelAgente.on_focus. La seleccion SOBREVIVE al foco: sin
        esto, escribir en el Input dejaba a las acciones sin destinatario."""
        if agente_id == self._seleccionado:
            return
        self._seleccionado = agente_id
        for aid, panel in self._paneles.items():
            panel.set_class(aid == agente_id, "seleccionado")
        self._pintar_placeholder()

    def _panel_destino(self) -> Optional[PanelAgente]:
        """El panel al que le hablan x y el Input, o None.

        None y no "el primero": adivinar el destinatario de un corte es
        exactamente el tipo de invento que esta pantalla no hace. Si el panel
        seleccionado ya no existe (corrida nueva), tampoco hay destino."""
        return self._paneles.get(self._seleccionado)

    def _escribiendo(self) -> bool:
        try:
            return bool(self.query_one("#hablar", Input).has_focus)
        except Exception:
            return False

    def _volver_a_la_rejilla(self) -> None:
        """El foco vuelve a los paneles (a la rejilla, que no es focusable, no
        se puede: `can_focus = False` para que tab recorra paneles)."""
        panel = self._panel_destino() or next(iter(self._paneles.values()), None)
        if panel is not None:
            panel.focus()
        else:
            self.set_focus(None)

    def _pintar_placeholder(self) -> bool:
        """El placeholder DICE A QUIEN se le habla y QUE hace enter.

        "interrumpir y decir", no "enviar" (decision del dueno): la accion
        CORTA la generacion en curso, tira lo generado y cuesta una llamada
        mas de presupuesto. Un "enviar" haria pensar en un chat que se encola
        sin molestar a nadie."""
        panel = self._panel_destino()
        # La clave lleva la ETIQUETA y no solo el id: el nombre en criollo
        # llega con el AgenteInicio, o sea DESPUES de que el panel existe. Con
        # la clave por id, un panel seleccionado antes de su AgenteInicio se
        # quedaba nombrado con el agente_id crudo para siempre.
        clave = (panel.agente_id, panel.etiqueta) if panel is not None else ()
        if clave == self._placeholder_de:
            return False
        self._placeholder_de = clave
        if panel is None:
            texto = "elegí un panel (tab · 1..9 · clic) para poder hablarle"
        else:
            texto = (f"[{panel.orden}] {corto(panel.etiqueta, 24)}  ·  "
                     f"enter INTERRUMPE lo que está generando y le dice esto")
        try:
            self.query_one("#hablar", Input).placeholder = texto
        except Exception:
            return False
        return True

    def action_panel(self, paso: int) -> None:
        """tab / shift+tab: el ciclo es sobre los PANELES.

        No se usa focus_next: los contenedores scrollables de Textual son
        focusables por defecto, asi que tab se metia dentro del panel (o en la
        rejilla) y el pie mentia -- decia "Panel sig." y no cambiaba de panel.

        QUIEN LA LLAMA es la binding de PanelAgente ("app.panel(1)"), no una de
        esta App: Screen trae `tab -> app.focus_next` de fabrica y le gana a la
        de App, asi que mientras la binding estuvo declarada aca esta funcion
        NO SE EJECUTABA NUNCA (medido al cablear el Input, 2026-08-18). Lo que
        se veia funcionar era focus_next recorriendo los unicos focusables que
        habia, que eran justo los paneles."""
        paneles = list(self._paneles.values())
        if not paneles:
            return
        actual = next((i for i, p in enumerate(paneles) if p.has_focus), None)
        siguiente = 0 if actual is None else (actual + paso) % len(paneles)
        paneles[siguiente].focus()

    # -- MANDAR: las tres acciones contra el motor ---------------------------
    #
    # Las tres siguen el MISMO libreto, y por eso se leen igual:
    #   1. la vista decide si tiene con que mandar (destinatario / corrida) y,
    #      si no, lo dice con "⚠ ..." y NO llama al motor;
    #   2. llama a workflows.<lo que sea> y recibe el envelope de forma fija;
    #   3. pinta el envelope TAL CUAL: la palabra del conjunto cerrado, el
    #      detalle y los contadores que no sean cero.
    # El paso 3 nunca decide nada. Un `ya_termino` con ok=False no se convierte
    # en "no se pudo": se muestra con su palabra y su detalle, que es para lo
    # que el motor los devuelve.

    def action_interrumpir(self) -> None:
        """`x`: corta EL AGENTE seleccionado. Sin modal (ver el BINDINGS)."""
        panel = self._panel_destino()
        if panel is None:
            self._mostrar_aviso("no hay ningún panel seleccionado: elegí uno "
                                "con tab o 1..9 y volvé a apretar x")
            return
        env = motor().cancelar_agente(
            panel.agente_id, motivo="el usuario cortó desde la pantalla de agentes")
        self._mostrar_envelope(f"x  interrumpir [{panel.orden}]", env)

    def action_cancelar_corrida(self) -> None:
        """`ctrl+x`: corta LA CORRIDA que se esta viendo, con confirmacion.

        El run_id es el de la corrida PINTADA. `cancelar_corrida("")` existe y
        significa panico global (todas las corridas vivas del proceso): esta
        pantalla no lo manda nunca, porque cortar corridas que no se estan
        mirando no es lo que el usuario pidio al apretar la tecla."""
        run_id = self._run_pintada
        if not run_id:
            self._mostrar_aviso("no hay ninguna corrida en pantalla que "
                                "cancelar")
            return
        # VIVOS, no paneles: con 3 paneles de los que 2 ya cerraron, "se corta
        # lo que estan generando sus 3 agentes" es falso, y el numero de un
        # dialogo de confirmacion es lo unico que el usuario tiene para medir
        # el destrozo. Si no queda ninguno vivo se dice eso mismo.
        vivos = sum(1 for p in self._paneles.values() if p._corriendo)
        que_pasa = (f"Se corta lo que {'está' if vivos == 1 else 'están'} "
                    f"generando {vivos} "
                    f"{'agente' if vivos == 1 else 'agentes'} y se pierde lo "
                    f"generado." if vivos else
                    "En la vista no queda ningún agente generando; puede que "
                    "la corrida ya haya cerrado.")
        # "Cortar" y no "Cancelar la corrida": el boton lleva el NOMBRE de la
        # accion (convencion de ConfirmModal) y ademas #confirm-box mide 48
        # celdas fijas -- con la etiqueta larga, el boton "No" se pintaba
        # cortado en "No  (" (medido en 08_modal_confirmar).
        self.push_screen(
            ConfirmModal(f"¿Cancelar la corrida {run_corto(run_id, 24)}?\n"
                         f"{que_pasa}", confirmar="Cortar"),
            callback=lambda si: self._resolver_cancelar_corrida(run_id, si))

    def _resolver_cancelar_corrida(self, run_id: str, si: object) -> None:
        """La respuesta del modal. `si` puede ser None si la pantalla se cerro
        sin elegir: solo el True explicito manda el corte."""
        if si is not True:
            self._mostrar_aviso(f"no se canceló nada: la corrida "
                                f"{run_corto(run_id, 24)} sigue")
            return
        env = motor().cancelar_corrida(
            run_id, motivo="el usuario cortó desde la pantalla de agentes")
        self._mostrar_envelope("ctrl+x  cancelar corrida", env)

    def action_hablar(self) -> None:
        """`enter` desde un panel: lleva el foco al campo. No manda nada."""
        try:
            self.query_one("#hablar", Input).focus()
        except Exception:
            pass

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """`enter` en el campo: INTERRUMPIR Y DECIR, y el foco vuelve.

        El texto vacio se manda igual al motor a proposito: `texto_vacio` es
        una de las ocho palabras del conjunto cerrado, y filtrarlo aca seria la
        vista inventando un rechazo que ya existe (y que podria dejar de
        coincidir el dia que el motor cambie de opinion).

        El campo se limpia SOLO si el motor acepto. Si contesto buzon_lleno o
        ya_termino, lo escrito sigue ahi: se perdio el mensaje, no hace falta
        perder tambien el texto."""
        if event.input.id != "hablar":
            return
        texto = event.value
        panel = self._panel_destino()
        if panel is None:
            self._mostrar_aviso("no hay ningún panel seleccionado: elegí uno "
                                "con tab o 1..9 y escribí de nuevo")
            self._volver_a_la_rejilla()
            return
        env = motor().decirle(panel.agente_id, texto)
        self._mostrar_envelope(f"enter  interrumpir y decir [{panel.orden}]", env)
        if env.get("ok"):
            event.input.value = ""
        self._volver_a_la_rejilla()

    # -- la fila de respuesta -------------------------------------------------

    def _mostrar_envelope(self, accion: str, env: dict) -> None:
        """El envelope del motor, PALABRA POR PALABRA.

        Se pinta el `estado` del conjunto cerrado (prefijado con "motor:" para
        que se vea de quien es la palabra), el `detalle` y los contadores que
        no sean cero. Nada se traduce ni se resume: el envelope de workflows.py
        tiene forma fija justo para que una UI no tenga que interpretarlo, y la
        forma de arruinar eso es "mejorar" el texto."""
        self._ultimo_envelope = dict(env or {})
        ok = bool(env.get("ok"))
        color = COLORS["ok"] if ok else COLORS["err"]
        piezas = [f"motor: {env.get('estado', '(sin estado)')}"]
        detalle = str(env.get("detalle") or "")
        if detalle:
            piezas.append(detalle)
        # Los TRES contadores tienen significados distintos (por eso son tres
        # claves y no una): solo se nombra el que trae algo.
        for clave, singular, plural in (
                ("pendientes", "mensaje en cola", "mensajes en cola"),
                ("agentes", "agente alcanzado", "agentes alcanzados"),
                ("corridas", "corrida alcanzada", "corridas alcanzadas")):
            n = int(env.get(clave) or 0)
            if n:
                piezas.append(f"{n} {singular if n == 1 else plural}")
        self._pintar_respuesta("✓" if ok else "✗", accion, " · ".join(piezas),
                               color)

    def _mostrar_aviso(self, texto: str) -> None:
        """Lo que rechaza LA VISTA, y se distingue de lo que dice el motor.

        Sin "motor:" y sin ninguna de las ocho palabras del conjunto cerrado:
        que la excusa de la UI se pueda confundir con un veredicto del motor
        es exactamente la mentira que el envelope existe para evitar."""
        self._ultimo_envelope = None
        self._pintar_respuesta("⚠", "", texto, COLORS["warn"])

    def _pintar_respuesta(self, glifo: str, accion: str, cuerpo: str,
                          color: str) -> None:
        """La fila #respuesta. PERSISTE hasta la proxima accion: es la ultima
        respuesta, no el estado de ahora, y por eso lleva la tecla que la
        provoco. Recorte con corto() -- el Static corta en seco y sin elipsis
        (D2), y el motivo de un rechazo vive justo al final de la frase."""
        # #respuesta tiene el padding 0 1 de #acciones: las columnas menos 2.
        ancho = max(20, (self.size.width or 120) - 2)
        linea = Text(no_wrap=True)
        linea.append(f"{glifo} ", style=f"bold {color}")
        usado = len(glifo) + 1
        if accion:
            linea.append(accion, style=f"bold {COLORS['text']}")
            linea.append(" · ", style=COLORS["muted"])
            usado += len(accion) + 3
        linea.append(corto(cuerpo, max(4, ancho - usado)), style=color)
        try:
            widget = self.query_one("#respuesta", Static)
        except Exception:
            return
        # Arranca OCULTA (display:none en el .tcss) y se enciende con la
        # primera respuesta: una fila en blanco permanente le come una linea a
        # la rejilla, y en una terminal de 20 filas eso es una linea de texto
        # de un agente. Una vez encendida se queda: la ultima respuesta del
        # motor no se borra sola.
        widget.styles.display = "block"
        widget.update(linea, layout=False)

    # -- el latido unico -----------------------------------------------------

    def _marcar_sucio(self, estado: EstadoPuente) -> None:
        """Callback del puente: CORRE EN EL HILO DE LA UI (el puente ya lo
        garantiza). Lo unico que hace es marcar: repintar aca seria repintar
        una vez por drenaje, o sea cientos de veces por segundo."""
        self._sucio = True

    def _latido(self) -> None:
        """Un cuadro: onda + reloj + (si hubo eventos) resincronizacion."""
        if not self.is_running or self._timer is None and self._cuadros:
            # Cinturon ademas del tirante (el timer se para en on_unmount): un
            # tick en vuelo no puede tumbar la salida de la pantalla.
            return
        self._cuadros += 1
        p = self._puente
        if p is None:
            return
        # UNA VISTA SIN PUENTE NO ANIMA Y LO DICE. Antes esto no se miraba:
        # abrir una segunda pantalla dejaba a esta con el timer a 15 fps
        # pintando datos congelados y cero suscriptores en el bus, en silencio.
        if self._revisar_puente(p):
            return
        self._fase += 1
        # LO QUE DEPENDE DEL ANCHO SE RE-DECIDE ACA, y no solo en on_resize:
        # el on_resize de la App corre con `self.size` TODAVIA vieja (medido:
        # 120 -> 60 -> 100 y la App leyendo [120,120,120,60]), asi que por si
        # solo deja la pista y la rejilla un paso atras. Las dos funciones
        # tienen guarda de firma y devuelven False cuando no cambia nada, que
        # es lo que permite llamarlas quince veces por segundo sin repintar
        # (el conteo de repintados con la corrida cerrada sigue en 0).
        redimensiono = self._pintar_pista()
        redimensiono = self._repartir_rejilla() or redimensiono
        estado = p.estado
        c = estado.ultima_corrida
        if c is None:
            if self._modo_vacio(True) or redimensiono:
                self._repintados += 1
            self._sucio = False
            return
        toco = self._modo_vacio(False) or redimensiono
        if self._sucio:
            self._sincronizar_paneles(c)
            self._sucio = False
            toco = True
        toco = self._pintar_cabecera(estado, c) or toco
        toco = self._pintar_plan(c) or toco
        for aid, panel in self._paneles.items():
            a = estado.agente(aid)
            if a is None:
                continue
            # Los terminados se sincronizan igual (baratos: sus firmas no
            # cambian y cada _sincronizar_* sale por el if), pero no animan.
            toco = panel.sincronizar(a, self._fase) or toco
        # DESPUES de sincronizar: el nombre en criollo del agente llega con su
        # AgenteInicio, o sea despues de que el panel existe, y el placeholder
        # tiene que decir a QUIEN se le habla. Con guarda de firma, igual que
        # todo lo demas: con la corrida cerrada devuelve False y no pinta.
        toco = self._pintar_placeholder() or toco
        # "repintados" cuenta CUADROS QUE PINTARON. Antes sumaba uno por latido
        # con corrida, pintara o no: con todo cerrado daba cuadros=36 /
        # repintados=35, o sea era un alias de "cuadros" disfrazado de medicion.
        if toco:
            self._repintados += 1

    # -- el puente puede haberse ido -----------------------------------------

    def _motivo_perdida(self, p) -> str:
        """Por que esta vista ya no recibe eventos. "" = todo bien."""
        if not p.conectado:
            return "otra pantalla tomó el puente del proceso"
        if p.app is not None and p.app is not self:
            return "el puente está sirviendo a otra pantalla"
        return ""

    def _revisar_puente(self, p) -> bool:
        """Pinta (o borra) la franja de desconexion. Devuelve True si la vista
        esta desconectada, y en ese caso el latido no hace nada mas: una vista
        que no recibe eventos no tiene por que animar.

        NO se reconecta sola a proposito: dos pantallas abiertas se robarian el
        puente en ping-pong y ninguna de las dos veria una corrida entera. Se
        cierra una y se reabre la otra."""
        motivo = self._motivo_perdida(p)
        if motivo == self._motivo_desconexion:
            return bool(motivo)
        self._motivo_desconexion = motivo
        try:
            franja = self.query_one("#desconectada", Static)
        except Exception:
            return bool(motivo)
        if not motivo:
            franja.styles.display = "none"
            franja.update("")
            return False
        franja.styles.display = "block"
        # WRAP, no elipsis: esta franja es la que dice que todo lo de abajo es
        # mentira; que se corte a si misma seria el mismo bug que arregla. La
        # altura la pone el CSS (auto, hasta 2 filas) y el texto esta contado
        # para entrar en UNA a 120 columnas (117 celdas).
        aviso = Text(no_wrap=False)
        aviso.append("⚠ vista DESCONECTADA ", style=f"bold {COLORS['err']}")
        aviso.append(f"· {motivo} · lo que ves está CONGELADO: "
                     f"no llegan eventos nuevos", style=COLORS["warn"])
        franja.update(aviso)
        self._repintados += 1
        return True

    def _modo_vacio(self, vacio: bool) -> bool:
        if vacio == self._vacio_pintado:
            return False
        try:
            self.query_one("#vacio").styles.display = "block" if vacio else "none"
            self.query_one("#rejilla").styles.display = "none" if vacio else "block"
            self.query_one("#plan").styles.display = "none" if vacio else "block"
        except Exception:
            return False
        self._vacio_pintado = vacio
        if vacio:
            # Con guarda: la pantalla vacia repintaba esta misma linea una vez
            # por cuadro (medido: 35 cuadros -> 35 update()) para decir siempre
            # exactamente lo mismo.
            self.query_one("#cabecera", Static).update(
                Text("Sin corrida  ·  esperando eventos del bus…",
                     style=COLORS["muted"]))
            self._firma_cabecera = ()
        return True

    # -- paneles: alta y baja dinamicas --------------------------------------

    def _sincronizar_paneles(self, c: CorridaVista) -> None:
        """Monta los paneles nuevos y tira los de una corrida anterior."""
        rejilla = self.query_one("#rejilla", VerticalScroll)
        if c.run_id != self._run_pintada:
            for panel in self._paneles.values():
                panel.remove()
            self._paneles.clear()
            self._run_pintada = c.run_id
            # La seleccion muere con los paneles: si no, `x` seguiria apuntando
            # a un agente de la corrida ANTERIOR (el motor contestaria
            # desconocido_corrida o corrida_cerrada, pero el usuario habria
            # apretado creyendo que cortaba lo que esta viendo).
            self._seleccionado = ""
        for aid in c.agentes_vista:
            if aid in self._paneles:
                continue
            # `orden` es la tecla que lo enfoca. Del 10 en adelante no hay
            # tecla (no existe una decima cifra): a esos se llega con tab o con
            # el raton, y el numero sigue puesto en el titulo para poder
            # nombrarlos. Ocho paneles ya llenan dos pantallas de alto.
            panel = PanelAgente(aid, orden=len(self._paneles) + 1)
            self._paneles[aid] = panel
            rejilla.mount(panel)
        self._repartir_rejilla()

    def _repartir_rejilla(self, ancho: Optional[int] = None) -> bool:
        """Cuantas columnas y de que alto. Lo llaman el alta de paneles, el
        resize Y el latido: la reparticion depende del ANCHO, y hasta hoy solo
        se decidia al montar -- una terminal que se encogia se quedaba con dos
        columnas de panel angosto (ver ANCHO_MIN_2COL).

        Con GUARDA de firma, como todo lo demas: devuelve False si la
        reparticion ya era esa, para poder llamarla por cuadro sin repintar."""
        n = len(self._paneles)
        # Una columna con un solo agente (un panel de 58 celdas al lado de un
        # hueco se lee como que falta algo); dos a partir de dos, Y SOLO si la
        # terminal da para que cada mitad conserve los numeros del titulo.
        ancho = ancho or self.size.width or 120
        columnas = 1 if (n <= 1 or ancho < ANCHO_MIN_2COL) else 2
        # Y la altura de fila segun cuantas filas hacen falta: mientras entren,
        # se reparten la pantalla; cuando no, alto fijo y scroll (ver el .tcss).
        filas = -(-n // columnas) if n else 1
        clase = "filas-1" if filas <= 1 else ("filas-2" if filas == 2
                                              else "filas-fijas")
        if (columnas, clase) == self._reparto:
            return False
        try:
            rejilla = self.query_one("#rejilla", VerticalScroll)
        except Exception:
            return False
        self._reparto = (columnas, clase)
        rejilla.styles.grid_size_columns = columnas
        for otra in ("filas-1", "filas-2", "filas-fijas"):
            rejilla.set_class(otra == clase, otra)
        return True

    # -- cabecera y plan -----------------------------------------------------

    def _pintar_cabecera(self, estado: EstadoPuente, c: CorridaVista) -> bool:
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

        # LAS PIEZAS DE LA CABECERA: (texto, estilo, prioridad, separador).
        #
        # Los separadores NO son piezas sueltas. Cada pieza trae el separador
        # que va DELANTE de ella y solo se pinta si la pieza sobrevive: con
        # separadores independientes quedaban " · " colgados cada vez que
        # caia su vecino (se llego a ver "◉ revisar el handshake TLS en… ·   !
        # puente: ..."), y cada parche puntual abria el agujero siguiente.
        #
        # La prioridad dice EN QUE ORDEN se cae lo que no entra, de lo que
        # sobra primero a lo que no se va nunca:
        #   5 el run_id | 4 "(N vivos)" y "corrida cerrada" | 3 tok y reloj
        #   2 el nombre de la corrida y "N/M agentes" | 0 el BADGE de descarte
        # El nombre esta por ENCIMA de los numeros a proposito: los tokens y el
        # reloj tambien estan en cada panel; el nombre de la corrida, en ningun
        # otro lado.
        #
        # POR QUE ASI. Antes habia un booleano "prescindible" de dos niveles y
        # el badge iba al final de un Text con overflow="ellipsis": cuando la
        # linea no entraba se cortaba justo el numero de chars perdidos, o sea
        # el unico dato que dice que la vista miente. MEDIDO a 80 columnas
        # ANTES del arreglo: 107 chars de contenido en 78 celdas y lo pintado
        # terminaba en "… 1,3 s  !" -- el badge decapitado en el signo.
        d = estado.descartes
        piezas: list[tuple[str, str, int, str]] = [
            (corto(c.nombre or "(sin nombre)", 28), f"bold {COLORS['text']}",
             2, ""),
            (f"run {run_corto(c.run_id)}", COLORS["muted"], 5, " · "),
            (f"{len(c.agentes_vista)}/{total} agentes", COLORS["text"], 2, " · "),
        ]
        if vivos:
            piezas.append((f"({vivos} vivos)", COLORS["accent"], 4, " "))
        piezas += [
            (f"{'~' if estimado else ''}{miles(tokens)} tok", COLORS["text"],
             3, " · "),
            (segundos(c.segundos), COLORS["text"], 3, " · "),
        ]
        if not c.abierta:
            piezas.append(("corrida cerrada",
                           COLORS["ok"] if c.ok else COLORS["err"], 4, " · "))
        if d.hubo:
            # El descarte GLOBAL va en la cabecera ademas de en el panel del
            # agente: si la UI se quedo atras, el numero tiene que estar donde
            # se mira primero.
            piezas.append((f"! puente: {miles(d.total)} desc · {miles(d.chars)} chars",
                           f"bold {COLORS['err']}", 0, "  "))

        # #cabecera tiene padding 0 1: el contenido son las columnas menos 2.
        ancho = max(20, (self.size.width or 120) - 2)
        firma = (tuple(piezas), ancho)
        if firma == self._firma_cabecera:
            return False
        self._firma_cabecera = firma

        glifo = ("◉ ", f"bold {COLORS['accent']}")

        def largo(ps) -> int:
            # El separador de la PRIMERA pieza no se pinta (va pegado al glifo).
            return len(glifo[0]) + sum(len(t) + (len(sep) if i else 0)
                                       for i, (t, _, _, sep) in enumerate(ps))

        # Se cae POR LA DERECHA dentro de cada nivel: entre dos piezas igual de
        # prescindibles se sacrifica la de mas atras, porque lo primero que se
        # lee es lo que identifica la corrida. Cayendo por la izquierda, a 80
        # columnas desaparecia el NOMBRE para salvar un "(1 vivos)" de diez
        # celdas (medido).
        for nivel in (5, 4, 3, 2):
            while largo(piezas) > ancho:
                fuera = next((i for i in range(len(piezas) - 1, -1, -1)
                              if piezas[i][2] >= nivel), None)
                if fuera is None:
                    break
                piezas.pop(fuera)
        if d.hubo and largo(piezas) > ancho:
            # Ultimo recurso ANTES de que corte el renderer: el badge compacto.
            # Sigue trayendo los DOS numeros, que es lo que no se negocia.
            t, e, pr, sep = piezas[-1]
            piezas[-1] = (f"! {miles(d.total)}d/{miles(d.chars)}c", e, pr, sep)

        linea = Text(no_wrap=True, overflow="ellipsis")
        linea.append(*glifo)
        for i, (texto, estilo, _pr, sep) in enumerate(piezas):
            if i:
                linea.append(sep, style=COLORS["muted"])
            linea.append(texto, style=estilo)
        self.query_one("#cabecera", Static).update(linea, layout=False)
        return True

    def _pintar_plan(self, c: CorridaVista) -> bool:
        """El plan de la corrida como casillas, marcandose en vivo.

        El plan NO se inventa: es la lista de agentes que el motor declaro (su
        etiqueta), en orden de aparicion. Un agente que todavia no arranco no
        esta -- y por eso la cabecera dice '3/6': el denominador es lo que la
        corrida prometio, el plan es lo que ya se vio.

        Si no entran todos, se dice CUANTOS faltan. Con ocho agentes la linea
        se cortaba por elipsis y la ultima tarea aparecia como una casilla sin
        nombre (medido en 08_ocho_agentes.png): una tarea escondida en una
        pantalla que existe para que no se escondan."""
        ancho = max(20, (self.size.width or 120) - 2)
        items: list[tuple[str, str, str]] = []      # (casilla, texto, color)
        for a in c.agentes_vista.values():
            if a.estado == "ok":
                casilla, color = CASILLA_OK, COLORS["ok"]
            elif a.estado in ("fallo", "cancelado"):
                casilla, color = CASILLA_FALLO, (
                    COLORS["err"] if a.estado == "fallo" else COLORS["warn"])
            else:
                casilla, color = CASILLA_PENDIENTE, COLORS["accent"]
            texto = corto(a.etiqueta or a.fase or a.agente_id, 18)
            # El color es el SEMANTICO, punto. Antes era `color if a.viva else
            # COLORS["text"]` y `viva` es True SOLO en "corriendo": o sea que
            # ok, fallo y cancelado -- los tres estados que ya se sabe como
            # salieron -- caian todos al gris claro y el plan dejaba de decir
            # que fallo justo cuando la corrida cerraba. Los COLORS["ok"] /
            # ["err"] / ["warn"] calculados tres lineas arriba eran codigo
            # muerto (verificado en el SVG: los tres items con el mismo fill).
            items.append((casilla, texto, color))

        firma = (tuple(items), ancho)
        if firma == self._firma_plan:
            return False
        self._firma_plan = firma
        plan = Text(no_wrap=True, overflow="ellipsis")
        plan.append("plan  ", style=f"bold {COLORS['muted']}")
        usado = 6
        for i, (casilla, texto, color) in enumerate(items):
            trozo = len(casilla) + 1 + len(texto) + 3
            # La cola que dice CUANTAS FALTAN hay que reservarla solo si
            # DESPUES de este item queda algo. Antes se reservaba tambien para
            # el ultimo (faltan=1), asi que una tarea que entraba se cambiaba
            # por un cartel de seis celdas: la pantalla escondia el nombre de
            # una tarea para hacerle lugar al cartel que avisa que hay tareas
            # escondidas.
            resto = len(items) - i - 1
            cola = len(f"+{resto} más") if resto else 0
            if usado + trozo + cola > ancho:
                plan.append(f"+{len(items) - i} más", style=f"bold {COLORS['muted']}")
                break
            plan.append(f"{casilla} ", style=f"bold {color}")
            plan.append(texto + "   ", style=color)
            usado += trozo
        self.query_one("#plan", Static).update(plan, layout=False)
        return True

    # -- para los tests y el informe ----------------------------------------

    def metricas_vista(self) -> dict:
        """Lo que hizo la PANTALLA (no el puente): cuadros, repintados,
        paneles. Sirve para medir el coste sin adivinar.

        "repintados" cuenta los cuadros que PINTARON algo -- no los cuadros a
        secas, como hacia hasta 2026-08-18 (sumaba uno al final de cada latido
        con corrida, pintara o no: medido cuadros=36 / repintados=35 con todo
        cerrado). Con la corrida cerrada y sin eventos ahora tiene que quedarse
        clavado, y eso es exactamente lo que verifica el test."""
        return {"cuadros": self._cuadros, "repintados": self._repintados,
                "paneles": len(self._paneles), "fps": self._fps,
                "desconectada": bool(self._motivo_desconexion),
                "vivos": sum(1 for p in self._paneles.values() if p._corriendo),
                # A quien le hablan las acciones y que contesto el motor la
                # ultima vez. El envelope va CRUDO (o None si la ultima
                # respuesta fue un aviso de la vista, que no es del motor):
                # un test que compare contra un texto renderizado estaria
                # verificando el formato, no lo que el motor dijo.
                "seleccionado": self._seleccionado,
                "ultimo_envelope": (dict(self._ultimo_envelope)
                                    if self._ultimo_envelope else None)}


def abrir_pantalla_agentes(*, fps: int = FPS,
                           desconectar_al_salir: bool = True) -> None:
    """Abre el mirador (bloquea hasta que se cierra con esc/q).

    Textual entra y sale de la pantalla alternativa: al volver, el terminal
    queda como estaba (es lo que verifica el test del ciclo de vida).

    ``desconectar_al_salir`` existe en el __init__ y esta documentado en
    on_unmount como decision de diseno (al cerrar se pierde el HISTORIAL de la
    vista); no exponerlo aca hacia que la decision no se pudiera tomar desde el
    unico punto de entrada publico del modulo."""
    PantallaAgentes(fps=fps, desconectar_al_salir=desconectar_al_salir).run()


if __name__ == "__main__":     # pragma: no cover
    abrir_pantalla_agentes()
