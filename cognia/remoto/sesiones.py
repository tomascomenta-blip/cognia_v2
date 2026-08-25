"""
sesiones.py — el corazon del control remoto: REPLs reales como subprocesos.

Cada sesion es `python -m cognia` corriendo con cwd en la carpeta del
proyecto. Un hilo lector bombea stdout a la transcripcion (jsonl en disco,
sobrevive reinicios del servidor) y a las colas de los WebSockets suscritos.
Escribir un mensaje = escribir una linea al stdin del REPL — exactamente lo
que hace el teclado en la terminal, incluidas las respuestas a formularios
(un input() pendiente del REPL consume la siguiente linea).
"""

from __future__ import annotations

import json
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

RAIZ_DATOS = Path.home() / ".cognia" / "remoto"
RAIZ_DATOS.mkdir(parents=True, exist_ok=True)
FICHERO_PROYECTOS = RAIZ_DATOS / "proyectos.json"

# Lineas de ruido del arranque que no aportan en el movil.
_RUIDO = ("[OK]", "[WARN]", "[cognia_embedding]", "[>>]",
          "Warning: You are sending unauthenticated", "Loading weights:")

# Escapes ANSI (el REPL colorea el prompt aunque NO_COLOR) y el propio
# "cognia>" que en el movil es redundante. Las dos flechas: el REPL con consola
# usa 'cognia➤' (marco verde) y el fallback sin consola 'cognia>'.
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
# Solo UN espacio tras el prompt (el que input("cognia> ") imprime), no \s*:
# el REPL escribe el prompt sin salto y lo primero que el renderer pinta en
# el turno cae en la MISMA linea ("cognia>   · pensando…"). Con \s* la
# sangria de dos espacios de las marcas del renderer desaparecia y la linea
# ya no se distinguia de una vineta "· " de la respuesta (hallazgo 2026-08-25:
# la clasificacion por marca exige la sangria EXACTA, ver _RE_MARCA_RENDERER).
_PROMPT = re.compile(r"^(cognia[>➤] ?)+")


def _limpiar(linea: str) -> str:
    linea = _ANSI.sub("", linea)
    linea = _PROMPT.sub("", linea)
    # lineas que son solo dibujo de caja del banner
    if linea and all(c in "─│┌┐└┘├┤┬┴╭╮╰╯═║ •·" for c in linea.strip()):
        return ""
    return linea.rstrip()


# ── Clasificacion: que es LOG (va al panel Registro) y que es CHAT ─────────
# El primer intento filtraba en el FRONTEND y solo las lineas de logger con
# timestamp: el banner, los tracebacks y los restos del arranque seguian
# inundando el chat (reporte del dueno, 2026-07-20). La clasificacion vive
# aqui, en el servidor, con estado para bloques multilinea.

_RE_LOG_TS = re.compile(
    r"^\d{4}-\d{2}-\d{2} .*\|\s*(INFO|WARNING|ERROR|DEBUG)\s*\|")
_ABRE_TRAZA = ("Traceback (most recent call last)", "--- Logging error ---",
               "Call stack:")
# La ultima linea de un traceback es "Tipo: mensaje". Medido en el e2e de
# la paridad (2026-08-25): "KeyboardInterrupt: interrumpido desde el remoto"
# no casaba con Error|Exception|Warning y entraba al CHAT como respuesta de
# Cognia. Interrupt/Exit cierran la familia (KeyboardInterrupt, SystemExit).
_SIGUE_TRAZA = re.compile(
    r"^(\s|File |Message:|Arguments:|Traceback|Call stack)"
    r"|^[A-Za-z_][A-Za-z0-9_.]*(Error|Exception|Warning|Interrupt|Exit)\b")
# arte del banner: braille, bloques, cajas — mas de un tercio de la linea
_ARTE = re.compile(r"[⠀-⣿─-╿█╗╝╔╚]")
_FRAGMENTOS_BANNER = (
    "Slash commands", "Sistema listo", "Historial]", "sem=0.40",
    "v3.2 · Fases", "/ayuda para", "Texto libre", "Tab autocompletar",
    "Escribe /ayuda", "cognitivo", "Cognia v3.2",
    # ruido de arranque que quedo GUARDADO en sesiones previas al filtrado
    "Loading weights:", "Warning: You are sending unauthenticated",
)
# restos ANSI guardados como texto literal en transcripciones viejas
_ANSI_LITERAL = re.compile(r"\[\d{1,3}m")
# Las lineas de ESTADO que el CLI imprime justo debajo del banner completo
# (modelo/modo/tema, sesion, continuidad). Su sitio es el Registro, igual que
# el resto del arranque: van aca porque el gate de arranque ahora cierra en el
# borde del panel y estas tres quedan del lado de fuera. Ver _FIN_ARRANQUE.
_RE_ESTADO_ARRANQUE = re.compile(
    r"^\s*(modelo .*\(:\d+\)|sin backend en |Sesion [0-9a-f]{6,} en "
    r"|Continuidad: \d+ mensajes)")

# ACTIVIDAD: lo que Cognia HACE (pasos del agente, acciones de herramientas,
# workflows de la oficina, pipeline de creacion). En el chat va como bloque
# plegable +/- — visible pero agrupado, nunca escondido como los logs.
_RE_ACTIVIDAD = re.compile(
    r"^\s*("
    r"paso \d+|ACCION\b|RESULTADO |\$ |Archivos escritos|Plan(?: de subtareas)?:"
    r"|\[detail\]|\[research\]|\[planner\]|\[generator\]|\[evaluator\]"
    r"|\[storage\]|\[vista\]|\[github\]|\[arxiv\]|\[hf\]|\[contra\]"
    r"|Correccion \d|Defectos vistos|Critico \(|Remate:|Sugerencia"
    r"|jefe planificando|directiva|\[trabajador|D\d+:|META:"
    r"|herramienta\(s\)|Presupuesto de pasos|hibrido:"
    # el modo sencillo imprime la herramienta a secas (medido en /hacer real)
    r"|escribir_archivo\b|leer_archivo\b|ejecutar\b|buscar\b|anotar\b"
    r"|generar_codigo\b|delegar_subtarea\b|kg_buscar\b|copiar_archivo\b"
    r"|apendar_archivo\b|Objetivo verificado"
    # instrumentacion del backend (stderr mergeado a stdout): "[backend]
    # via=generate..." llegaba al chat como si fuera Cognia hablando.
    # transcripcion() reclasifica al leer, asi que tambien limpia lo viejo.
    r"|\[backend\]|\[llama_backend\]|\[degradado\]"
    r"|\+ "      # lineas de diff al escribir (solo +: '- ' es vineta de respuesta)
    r")")

# Lineas con la MARCA del renderer (· pensando…, ⏺ tool, ✗ fallo, ⚠ aviso,
# → degradado, ∴ razonamiento) que llegan ANTES del primer evento tipado del
# turno: el de-dup de ecos solo actua con _con_eventos, y "  · pensando…" del
# fast-path entraba al chat como respuesta (e2e 2026-08-25). Son actividad.
# SOLO con la sangria EXACTA del renderer (cognia/ux/renderer.py: _SANGRIA =
# "  " para todas las marcas, tambien el "∴" del razonamiento — medido en el
# e2e 2026-08-25: "  ∴ Empty workspace…" y su continuacion a 4 espacios; y
# _SANGRIA_PENSAR = "    ∴ " para la prosa del pensar), anclada al inicio y
# sin \s*: la primera version aceptaba "[·⏺✗⚠→∴]\s" tras cualquier sangria y
# se tragaba lineas de la RESPUESTA FINAL ("→ primero calcula la media", "·
# un punto"), que bajo remoto _show_response imprime plana (sin sangria) —
# hallazgo rev2 2026-08-25. La respuesta final no tiene marcadores de
# inicio/fin: la sangria exacta es la unica frontera local entre marca y
# prosa.
# Los glifos de confianza (◐ ○ ● ✕, cli._confianza_previa) tambien: el aviso
# a priori se pinta como "  ◐ confianza a priori BAJA: …" sin otra marca; su
# de-dup real es el eco del evento Aviso (_casar_eco), esto es la red de
# abajo para que, si el eco no casa, vaya a actividad y no al chat.
_RE_MARCA_RENDERER = re.compile(r"^  [·⏺✗⚠→∴◐○●✕] \S|^    ∴ \S")
# El subconjunto que el de-dup por ECO descarta (sin "∴": el razonamiento no
# duplica ningun evento anotado, va a actividad con su bloque sangrado, ver
# _seguir_bloque_actividad).
_RE_ECO_RENDERER = re.compile(r"^  [·⏺✗⚠→] \S")


def _es_actividad(linea: str) -> bool:
    return bool(_RE_ACTIVIDAD.match(linea) or _RE_MARCA_RENDERER.match(linea))


def _es_log(linea: str) -> bool:
    """True si la linea pertenece al Registro, no al chat."""
    if _RE_LOG_TS.match(linea):
        return True
    t = linea.strip()
    if not t:
        return False
    # marcos puros del panel (┌───┐, └───┘): log siempre
    if t.startswith(("┌", "└", "├", "╭", "╰")):
        return True
    # "│ contenido │": los paneles rich envuelven TAMBIEN resultados y
    # respuestas del agente — se juzga el CONTENIDO, no el marco (medido:
    # "│ RESULTADO leer_archivo ... │" acababa en el Registro)
    if t.startswith("│"):
        interior = t.strip("│").strip()
        if not interior:
            return True
        return _es_log(interior)
    if any(f in t for f in _FRAGMENTOS_BANNER):
        return True
    if _RE_ESTADO_ARRANQUE.match(t):
        return True
    arte = len(_ARTE.findall(t))
    return arte >= 3 or arte >= max(1, len(t)) / 3


def reclasificar(quien: str, texto: str, en_traza: bool) -> tuple[str, bool]:
    """
    (quien_final, en_traza_siguiente). Con estado: un traceback abre el modo
    traza y sus lineas de continuacion siguen siendo log aunque una a una no
    lo parezcan.
    """
    if quien != "cognia":
        return quien, en_traza
    # limpiar restos ANSI literales de transcripciones viejas antes de juzgar
    texto = _ANSI_LITERAL.sub("", texto)
    texto = _PROMPT.sub("", texto)
    t = texto.strip()
    if any(t.startswith(a) for a in _ABRE_TRAZA):
        return "log", True
    if en_traza:
        if _SIGUE_TRAZA.match(texto):
            return "log", True
        en_traza = False
    if _es_log(texto):
        return "log", en_traza
    interior = t.strip("│").strip() if t.startswith("│") else texto
    if _es_actividad(interior):
        return "actividad", en_traza
    # panel Rich "│ ... │" que no es log ni una accion reconocida: sigue siendo
    # CHROME (ayuda, estado, tabla, "Recibido: N parte(s)"), nunca la respuesta
    # conversacional — Cognia no enmarca sus respuestas. Va a actividad
    # (plegable), no al chat. (Cazado 2026-07-20: paneles "│ local │" y
    # "│ Recibido: 1 parte(s) │" se colaban al chat y se renderizaban como md.)
    if t.startswith("│"):
        return "actividad", en_traza
    return "cognia", en_traza


# ── Eventos tipados (cognia/ux/events.py): el canal PRIMARIO desde 2026-08-09 ─
# La sesion lanza el REPL con COGNIA_EVENTS_JSONL=1: el bus de eventos escribe
# una linea "@EV {json}" por evento a stdout. Aqui se clasifica por TIPO, no
# por regex — el regex de arriba queda como fallback para la prosa del CLI
# (la respuesta final, avisos sueltos) y para REPLs viejos sin bus.

try:
    from cognia.ux.events import PREFIJO_STDOUT as _PREFIJO_EV
except Exception:                       # el remoto no muere si el bus cambia
    _PREFIJO_EV = "@EV "

# Tipos del contrato de ux/events.py. Una linea JSON PELADA (sin prefijo) solo
# se acepta como evento si su "tipo" esta aqui: el agente muestra JSON ajeno
# todo el tiempo y "tipo" es una clave comun en datos en espanol.
_TIPOS_EVENTO = {"TareaInicio", "PasoIntencion", "ToolInicio", "ToolFin",
                 "TokenTexto", "RazonamientoTick", "Aviso", "Degradado",
                 "TareaFin",
                 # tanda UI 2026-08-17: los eventos del motor de workflows
                 # (cognia/agent/workflows.py). Esta allowlist solo gobierna el
                 # JSON PELADO (la red por si el prefijo se pierde en un pipe):
                 # el camino primario "@EV {json}" acepta cualquier tipo, asi
                 # que anadirlos AMPLIA la red, no restringe nada.
                 "WorkflowInicio", "AgenteInicio", "AgenteFin", "WorkflowFin",
                 # control por agente 2026-08-17: sin estos dos el movil
                 # recibia el JSON crudo volcado como linea de actividad.
                 "MensajeAlAgente", "AgenteProgreso",
                 # paridad remoto 2026-08-24: el chip de confianza y el footer
                 # del turno viajan tipados (antes el remoto solo tenia el
                 # footer plano "Ns · N tokens" del renderer, que se descarta
                 # como eco, y la confianza no llegaba: _confianza_remoto).
                 "Confianza", "FooterTurno"}


# ── MULTILINEA: una entrada del REPL a partir de N lineas del textarea ──────
# MEDIDO 2026-08-24 leyendo cli.py: la continuacion oficial ("linea \" y la
# siguiente sigue) vivia SOLO en la rama con PromptSession (cli.py:
# `while line.endswith("\\"): ... line = line[:-1].rstrip() + " " + continuation`).
# Bajo el remoto stdin es un pipe, la PromptSession muere y el REPL cae a la
# rama input() pelado, que NO tenia ese bucle: cada "\n" del textarea era UNA
# entrada mas para el REPL (un mensaje de 3 lineas = 3 turnos, y una linea
# que empiece por "/" se despachaba como comando).
# Desde la paridad (cli._leer_con_continuacion, 2026-08-24) esa rama SI la
# soporta, y bajo COGNIA_REMOTO une con "\n" (los saltos son contenido: un
# bloque de codigo pegado en el movil no se aplasta). El servidor detecta el
# soporte leyendo la FUENTE de cli.py (sin importarlo: pesa) y elige:
#   "continuacion" (default si hay soporte): manda el protocolo crudo, una
#       linea por linea, las intermedias terminadas en " \"; el REPL las
#       lee como UNA entrada con sus saltos.
#   "unir" (fallback para un REPL sin soporte, y COGNIA_REMOTO_MULTILINEA=unir):
#       manda la MISMA cadena que la continuacion clasica del prompt rico
#       habria construido (unir_continuacion_oficial la replica y un test la
#       compara con la funcion real del REPL). Se pierden los saltos.
# Dos limites del protocolo, y como se cierran aqui (hallazgo 2026-08-25):
#   - LINEAS VACIAS: la primera version las descartaba ("el REPL las trataria
#     como entradas vacias") y un bloque de codigo pegado perdia sus lineas
#     en blanco (en Python o Markdown cambia el significado). Ahora viajan
#     como " \" (una linea de continuacion vacia). Que SOBREVIVAN depende de
#     cli._unir_continuacion: con `acumulado[:-1].rstrip()` el "\n" que las
#     precede se recorta junto con el espacio y la vacia se aplasta igual;
#     hace falta rstrip(" \t") en cli.py (test_B_las_lineas_vacias... lo mide
#     contra la funcion real y se marca xfail mientras cli.py no lo tenga).
#   - BARRA FINAL: una ultima linea que termina en "\" (una ruta Windows)
#     dejaba al REPL esperando continuacion y el siguiente mensaje se pegaba
#     a este. cerrar_barra_final() la manda como "<linea> \" seguida de una
#     linea vacia: el REPL consume la "\" anadida, conserva la del usuario
#     (el rstrip no toca una barra) y cierra la entrada con "" (input() la
#     devuelve; el strip posterior del REPL quita el "\n" sobrante).

def lineas_continuacion(texto: str) -> list[str]:
    """El texto multilinea en el protocolo de continuacion del REPL: cada
    linea salvo la ultima termina en ' \\'. Las vacias INTERIORES se
    conservan (" \\"); las del principio y el final no dicen nada y se
    quitan. Una ultima linea que termine en "\\" queda tal cual: la cierra
    cerrar_barra_final (entradas_para_repl), no esta funcion."""
    lineas = [l.rstrip() for l in texto.split("\n")]
    while lineas and not lineas[0].strip():
        lineas.pop(0)
    while lineas and not lineas[-1].strip():
        lineas.pop()
    if not lineas:
        return []
    return [l + " \\" for l in lineas[:-1]] + [lineas[-1]]


def cerrar_barra_final(entradas: list[str]) -> list[str]:
    """Si la ULTIMA linea que se va a escribir al REPL termina en "\\", el
    REPL esperaria continuacion: se le anade " \\" (la barra que el protocolo
    consume) y una linea vacia que cierra la entrada. La barra del usuario
    se conserva. Se mira con rstrip(): el REPL hace input().strip() y una
    barra seguida de espacios (lo que deja la union en modo "unir") tambien
    lo dejaria esperando. Idempotente sobre una lista ya cerrada."""
    if entradas and entradas[-1].rstrip().endswith("\\"):
        return entradas[:-1] + [entradas[-1].rstrip() + " \\", ""]
    return list(entradas)


def unir_continuacion_oficial(lineas: list[str]) -> str:
    """Lo que el bucle de continuacion de cli.py construye a partir de esas
    lineas: replica EXACTA de `line[:-1].rstrip() + " " + continuation` con
    los .strip() que el prompt aplica a cada entrada. Si cli.py cambia esa
    expresion, tests/test_remoto_paridad.py lo detecta."""
    if not lineas:
        return ""
    line = lineas[0].strip()
    resto = list(lineas[1:])
    while line.endswith("\\"):
        continuation = resto.pop(0).strip() if resto else ""
        line = line[:-1].rstrip() + " " + continuation
    return line


def a_entrada_repl(texto: str) -> str:
    """N lineas del textarea -> la UNICA entrada que el REPL debe leer (modo
    "unir"). La barra final se cierra ANTES de unir: la replica del bucle
    oficial se la comeria como marca de continuacion (igual que haria el
    prompt rico), y una ruta Windows perderia su ultima barra."""
    return unir_continuacion_oficial(
        cerrar_barra_final(lineas_continuacion(texto)))


# ── STREAMING al movil: agrupador de TokenTexto -> "delta" ─────────────────
# Bajo COGNIA_REMOTO el bus deja pasar TokenTexto (COGNIA_REMOTO_STREAM != "0")
# y el renderer no escribe prosa durante el stream (_sin_stream): aqui se
# agrupan los tokens en trozos y se emiten SOLO a los suscriptores del WS,
# nunca al jsonl — la transcripcion persistida sigue siendo la respuesta
# final (quien="cognia"), que el front usa para reemplazar la burbuja viva.
# Sin hilo de reloj: el trozo se cierra al llegar el token que cumple el
# umbral (chars o ms) o al llegar CUALQUIER otra cosa (evento, prosa, fin del
# proceso), asi que el orden con la respuesta final es el de stdout. El
# residuo se retrasa como mucho un intervalo entre tokens.

DELTA_MAX_CHARS = 80
DELTA_MAX_MS = 120


class AgrupadorDelta:
    """Junta TokenTexto en trozos. `emitir(texto)` recibe cada trozo;
    `reloj` es inyectable (tests sin dormir)."""

    def __init__(self, emitir, reloj=time.monotonic,
                 max_chars: int = DELTA_MAX_CHARS, max_ms: int = DELTA_MAX_MS):
        self._emitir = emitir
        self._reloj = reloj
        self.max_chars = max(1, int(max_chars))
        self.max_s = max(0.0, float(max_ms) / 1000.0)
        self._buf: list[str] = []
        self._chars = 0
        self._t0: float | None = None

    def token(self, texto: str) -> None:
        if not texto:
            return
        if self._t0 is None:
            self._t0 = self._reloj()
        self._buf.append(texto)
        self._chars += len(texto)
        if (self._chars >= self.max_chars
                or self._reloj() - self._t0 >= self.max_s):
            self.vaciar()

    def vaciar(self) -> None:
        if not self._buf:
            return
        trozo = "".join(self._buf)
        self._buf, self._chars, self._t0 = [], 0, None
        self._emitir(trozo)

    def pendiente(self) -> int:
        return self._chars


def extra_de_evento(d: dict) -> dict:
    """Campos que viajan en la anotacion ADEMAS de quien/texto (el movil
    pinta el chip de confianza con nivel y fuentes, y el footer con sus
    numeros). Vacio para el resto de tipos."""
    tipo = d.get("tipo", "")
    if tipo == "Confianza":
        fuentes = d.get("fuentes") or []
        return {"nivel": str(d.get("nivel") or ""),
                "glifo": str(d.get("glifo") or ""),
                "valor": d.get("valor"),
                "fuentes": [str(f) for f in fuentes][:20]}
    if tipo == "FooterTurno":
        return {"ok": bool(d.get("ok", True)),
                "segundos": float(d.get("segundos") or 0.0),
                "tokens": int(d.get("tokens") or 0),
                "ctx_libre_pct": d.get("ctx_libre_pct")}
    return {}


def _linea_footer(d: dict) -> str:
    """'✓ 14.6s · 312 tokens · ctx 95% libre' (o ✗ + motivo)."""
    partes = [f"{float(d.get('segundos') or 0.0):.1f}s"]
    tokens = int(d.get("tokens") or 0)
    if tokens:
        partes.append(f"{tokens} tokens")
    ctx = d.get("ctx_libre_pct")
    if ctx is not None:
        try:
            partes.append(f"ctx {float(ctx):.0f}% libre")
        except (TypeError, ValueError):
            # un ctx no numerico no es degradacion del remoto: se muestra tal
            # cual para que se vea que el emisor mando algo raro
            partes.append(f"ctx {ctx!r}")
    ok = bool(d.get("ok", True))
    linea = ("✓ " if ok else "✗ ") + " · ".join(partes)
    motivo = _cabeza(d.get("motivo", ""))
    if motivo and not ok:
        linea += f" — {motivo}"
    return linea


def parsear_evento(linea: str) -> dict | None:
    """Devuelve el dict del evento si la linea es una linea-evento, si no None.

    Dos formas aceptadas (pedido de la obra 2026-08-09): la prefijada
    "@EV {json}" (la que emite el sink stdout) y, como red, un JSON pelado
    cuyo "tipo" sea uno del contrato — por si el prefijo se pierde en un
    pipe intermedio."""
    if linea.startswith(_PREFIJO_EV):
        cuerpo = linea[len(_PREFIJO_EV):]
        try:
            d = json.loads(cuerpo)
        except Exception:
            return None
        return d if isinstance(d, dict) and d.get("tipo") else None
    if linea.startswith("{") and '"tipo"' in linea:
        try:
            d = json.loads(linea)
        except Exception:
            return None
        if isinstance(d, dict) and d.get("tipo") in _TIPOS_EVENTO:
            return d
    return None


def _cabeza(texto: str) -> str:
    """Primera linea no vacia, recortada (el movil muestra lineas cortas)."""
    for l in (texto or "").split("\n"):
        if l.strip():
            return l.strip()[:200]
    return ""


def _ref_agente(d: dict) -> str:
    """'agente 2/6 resume TLS' — la identidad legible, SIN estado: por eso
    AgenteFin repite indice/total/etiqueta. interpretar_evento() recibe un
    dict y devuelve una linea; si el Fin no trajera la identidad, el movil
    tendria que mantener un mapa de AgenteInicio vivos y ese mapa se pierde en
    cada reinicio del servidor."""
    n = d.get("total") or 0
    cab = f"agente {d.get('indice', 0)}" + (f"/{n}" if n else "")
    etiqueta = (d.get("etiqueta") or "").strip()
    return f"{cab} {etiqueta}".strip()


# ── AGRUPACION POR AGENTE (tanda UI 2026-08-18) ────────────────────────────
# El movil metia TODA la actividad en un unico bloque plegable y adivinaba de
# quien era cada linea con un regex sobre el texto (expertoDeLinea). Con 6
# agentes eso es una lista plana y el regex adivina mal: los eventos YA traen
# la identidad (ux/events.py sella agente_id en el contexto, asi que hasta un
# ToolFin de dentro de un agente lo lleva). Aqui se extrae y viaja en la propia
# anotacion (clave "ag" del jsonl); el regex del cliente queda de RESPALDO para
# las transcripciones viejas, que no tienen el campo.

# Estados que el movil pinta en la cabecera del bloque de cada agente.
EST_AG_VIVO, EST_AG_OK, EST_AG_FALLO = "vivo", "ok", "fallo"


def agente_de_evento(d: dict) -> dict:
    """Campos de agrupacion del evento, o {} si no pertenece a ningun agente.

    Siempre lleva "id" (la clave de agrupacion, estable: el agente_id del
    motor). Los eventos de ciclo de vida agregan lo que la cabecera muestra:
    "ref" legible, "estado", "tokens", "seg". Un latido agrega "chars".
    """
    tipo = d.get("tipo", "")
    if tipo == "MensajeAlAgente":
        # El agente_id HEREDADO sella al EMISOR (normalmente "": lo llama la
        # UI); el agente del que habla la linea es el DESTINO. Agrupar por el
        # emisor mandaria el eco del usuario al bloque equivocado.
        destino = (d.get("destino") or "").strip()
        return {"id": destino} if destino else {}
    if tipo == "AgenteInicio":
        ag = {"id": d.get("agente_id") or "", "ref": _ref_agente(d),
              "estado": EST_AG_VIVO}
        if d.get("fase"):
            ag["fase"] = d["fase"]
        return ag if ag["id"] else {}
    if tipo == "AgenteFin":
        ag = {"id": d.get("agente_id") or "", "ref": _ref_agente(d),
              "estado": EST_AG_OK if d.get("ok", True) else EST_AG_FALLO,
              "tokens": int(d.get("tokens") or 0),
              "seg": round(float(d.get("duracion_s") or 0.0), 1)}
        if d.get("cache_hit"):
            ag["cache"] = True
        if d.get("tardio"):
            # huerfano de paralelo(): su bloque no cuelga de un workflow abierto
            ag["tardio"] = True
        return ag if ag["id"] else {}
    if tipo == "AgenteProgreso":
        aid = d.get("agente_id") or ""
        return {"id": aid, "chars": int(d.get("chars") or 0)} if aid else {}
    aid = d.get("agente_id") or ""
    return {"id": aid} if aid else {}


def interpretar_evento(d: dict) -> tuple[str | None, str, list[str]]:
    """Evento tipado -> (quien, texto, ecos) para la transcripcion.

    - quien None = el evento no se anota (streaming, eco del usuario).
    - "actividad" = plegable en el movil (la actividad de tools, pedida asi
      por el dueno 2026-07-20); "sistema" = visible en el chat (degradados:
      la degradacion silenciosa es el modo de fallo historico de Cognia).
    - ecos: lineas que el RENDERER del CLI va a imprimir por el mismo evento
      (la intencion del paso, el resumen de una tool) y que el bombeo debe
      saltarse para no duplicar en el movil lo que el evento ya dijo."""
    tipo = d.get("tipo", "")
    if tipo in ("TareaInicio", "TokenTexto", "RazonamientoTick"):
        # TareaInicio es eco de lo que el usuario acaba de escribir; el
        # streaming llega entero como prosa de la respuesta final.
        return None, "", []
    if tipo == "PasoIntencion":
        intencion = _cabeza(d.get("intencion", ""))
        return ("actividad", intencion, [intencion]) if intencion else (None, "", [])
    if tipo == "ToolInicio":
        etiqueta = f"{d.get('tool', '?')} {d.get('args', '')}".strip()
        return "actividad", f"· {etiqueta}…", []
    if tipo == "ToolFin":
        etiqueta = f"{d.get('tool', '?')} {d.get('args', '')}".strip()
        resumen = d.get("resumen", "") or ""
        cab = _cabeza(resumen)
        # el renderer imprime las lineas 2-3 del resumen sangradas y sin
        # marca: van a ecos para que el fallback no las cuele como chat
        ecos = [l.strip() for l in resumen.split("\n")[1:3] if l.strip()]
        if d.get("ok", True):
            texto = f"⏺ {etiqueta}" + (f" — {cab}" if cab else "")
        else:
            texto = f"✗ {etiqueta} — fallo" + (f": {cab}" if cab else "")
        return "actividad", texto, ecos
    if tipo == "Aviso":
        t = _cabeza(d.get("texto", ""))
        # eco: el renderer imprime el aviso como "  {texto}" SIN marca — sin
        # registrarlo, la linea pintada entraba al chat como prosa (e2e
        # 2026-08-09: el "backend: ..." salio duplicado)
        eco = (d.get("texto", "") or "").strip().split("\n")[0].strip()
        return ("actividad", f"⚠ {t}", [eco]) if t else (None, "", [])
    if tipo == "Degradado":
        texto = f"degradado — {d.get('donde', '?')}"
        if d.get("motivo"):
            texto += f": {d['motivo']}"
        if d.get("accion_sugerida"):
            texto += f" → {d['accion_sugerida']}"
        return "sistema", texto, []
    if tipo == "TareaFin":
        partes = []
        if d.get("pasos"):
            partes.append(f"{d['pasos']} paso" + ("s" if d["pasos"] != 1 else ""))
        if d.get("duracion_s"):
            partes.append(f"{d['duracion_s']:.1f}s")
        if d.get("tokens_predichos"):
            partes.append(f"{d['tokens_predichos']} tokens")
        detalle = " · ".join(partes)
        if d.get("ok", True):
            # la respuesta final ya llega como prosa (cli.py la imprime plana
            # bajo COGNIA_REMOTO): aqui solo el cierre compacto de actividad
            return "actividad", ("✓ tarea terminada" +
                                 (f" · {detalle}" if detalle else "")), []
        cab = _cabeza(d.get("resumen", ""))
        return "actividad", ("✗ tarea sin exito" +
                             (f" — {cab}" if cab else "") +
                             (f" · {detalle}" if detalle else "")), []
    # ── motor de workflows (tanda UI 2026-08-17) ──
    # Los cuatro caen en "actividad": el bloque plegable que el movil ya
    # renderiza desde 2026-07-20, asi que el frontend no cambia. Y los cuatro
    # van con ecos VACIOS: la linea que el renderer pinta por el mismo evento
    # empieza por ⏺/·/✗ y la caza es_eco_renderer en el paso 3 de
    # _procesar_linea — sin esa marca el movil mostraria cada agente dos veces.
    if tipo == "WorkflowInicio":
        n = d.get("total_agentes") or 0
        texto = f"· workflow «{d.get('nombre', '?')}»"
        if n:
            texto += f" — {n} agentes"
        if d.get("cache_precargada"):
            texto += f" · {d['cache_precargada']} de cache"
        return "actividad", texto, []
    if tipo == "AgenteInicio":
        return "actividad", f"· {_ref_agente(d)}…", []
    if tipo == "AgenteFin":
        ref = _ref_agente(d)
        if not d.get("ok", True):
            return "actividad", f"✗ {ref} — fallo: {_cabeza(d.get('motivo', ''))}", []
        if d.get("cache_hit"):
            # un fin en 0 ms no es un bug: ya estaba pagado
            return "actividad", f"⏺ {ref} — de cache", []
        cola = f" ({d.get('duracion_s', 0.0):.1f}s · {d.get('tokens', 0)} tok)"
        cab = _cabeza(d.get("resumen", ""))
        return "actividad", f"⏺ {ref}" + (f" — {cab}" if cab else "") + cola, []
    if tipo == "MensajeAlAgente":
        # DOS DESTINOS distintos a proposito (defecto #6, 2026-08-17). El
        # aceptado es actividad (plegable): es el eco de algo que el usuario
        # acaba de escribir y ya vio. El RECHAZADO va a "sistema", visible en
        # el chat, porque es la unica noticia de que su mensaje no se va a
        # atender — el mismo invariante que ux/events.py enuncia para el bus
        # ("un mensaje descartado en silencio es peor que uno rechazado a la
        # vista") vale del lado del movil o no vale.
        texto = _cabeza(d.get("texto", ""))
        if d.get("aceptado"):
            n = d.get("pendientes") or 0
            cola = f" ({n} en cola)" if n > 1 else ""
            return "actividad", f"· le dijiste «{texto}»{cola}", []
        estado = d.get("estado") or "rechazado"
        return "sistema", (f"⚠ tu mensaje «{texto}» NO se entrego: "
                           f"{estado}"), []
    if tipo == "AgenteProgreso":
        # LATIDO. Sale throttleado del motor (250 ms / 400 chars) y su trabajo
        # es que el movil sepa que hay algo VIVO que se puede interrumpir; sin
        # esto salia como el JSON entero, una linea por latido igual de
        # frecuente pero ilegible. Va a actividad, que el movil ya pliega.
        partes = [f"{d.get('chars', 0)} chars"]
        if d.get("chars_razonamiento"):
            partes.append(f"{d['chars_razonamiento']} de razonamiento")
        if (d.get("intento") or 0) > 1:
            partes.append(f"intento {d['intento']}")
        return "actividad", "· generando… " + " · ".join(partes), []
    if tipo == "WorkflowFin":
        nombre = f"workflow «{d.get('nombre', '?')}»"
        if not d.get("ok", True):
            return "actividad", (f"✗ {nombre} — fallo: "
                                 f"{_cabeza(d.get('resumen', ''))}"), []
        partes = []
        agentes = d.get("agentes") or 0
        if agentes:
            partes.append(f"{agentes - (d.get('fallidos') or 0)} de {agentes}")
        if d.get("tokens"):
            partes.append(f"{d['tokens']} tokens")
        if d.get("duracion_s"):
            partes.append(f"{d['duracion_s']:.1f}s")
        return "actividad", (f"⏺ {nombre}" +
                             (" — " + " · ".join(partes) if partes else "")), []
    # ── paridad remoto 2026-08-24: confianza y footer del turno ──
    if tipo == "Confianza":
        glifo = str(d.get("glifo") or "").strip()
        nivel = str(d.get("nivel") or "").strip()
        texto = _cabeza(d.get("texto", "")) or (
            f"{glifo} confianza {nivel}".strip())
        # eco: si el renderer local pinta la misma linea (hoy no la pinta bajo
        # remoto: _confianza_remoto), no debe entrar al chat dos veces
        return "confianza", texto, [texto]
    if tipo == "FooterTurno":
        # el footer plano del renderer ("14.6s · 312 tokens") ya se descarta
        # por _RE_FOOTER_RENDERER; este es el tipado, con ctx y motivo
        return "footer", _linea_footer(d), []
    # tipo desconocido (el contrato crecio): se anota crudo en actividad para
    # no perderlo en silencio — perderlo era el bug historico del remoto
    return "actividad", f"{tipo}: {json.dumps(d, ensure_ascii=False)[:300]}", []


# ── Fin del ARRANQUE: cuando dejar de tirar lineas ─────────────────────────
# MEDIDO 2026-08-18 con un REPL real: el gate no cerraba NUNCA hasta el tope de
# 200 lineas. El unico marcador vivo era el del panel COMPACTO ("/ayuda para
# comandos") y hoy el REPL arranca con el banner COMPLETO, que imprime
# "/ayuda para TODOS los comandos" y ya no dice "Sistema listo". Consecuencia
# real, reproducida: en un /workflow llegaban los eventos tipados (se juzgan
# ANTES del gate) y se perdian en silencio las ~50 lineas de prosa del CLI —
# el panel con el resultado de los pasos y el "corrida … · N tokens".
# El marcador nuevo es el BORDE INFERIOR del panel del banner, que las dos
# variantes con banner imprimen; las tres lineas de estado que quedan debajo
# (modelo/sesion/continuidad) las recoge _RE_ESTADO_ARRANQUE como Registro.
_FIN_ARRANQUE = ("Sistema listo",            # banner full legacy
                 "/ayuda para comandos")     # panel compacto (obra 2026-08-09)
_RE_FIN_BANNER = re.compile(r"[└╰][─═]{3,}.*sistema cognitivo local")


# El renderer del CLI pinta los MISMOS eventos como lineas con marca
# (⏺ · ✗ ⚠ →) y un footer "3.2s · 500 tokens · 2 pasos". Cuando el stream de
# eventos esta activo, esas lineas son duplicados y se saltan.
# La marca cuenta SOLO con la sangria exacta del renderer ("  ⏺ "): antes se
# juzgaba sobre linea.strip() y una linea de la respuesta final que empezara
# por "→ " o "· " (una enumeracion del modelo) se DESCARTABA como eco — ni al
# chat ni a actividad (misma raiz que _RE_MARCA_RENDERER, 2026-08-25). Los
# tests con el Renderer real (test_remoto_eventos/agrupado) vigilan que lo
# que el renderer imprime siga cayendo aqui.
_RE_FOOTER_RENDERER = re.compile(
    r"^\d+(\.\d+)?s( · \d+ (tokens|pasos?))*$")


def es_eco_renderer(linea: str) -> bool:
    if _RE_ECO_RENDERER.match(linea):
        return True
    return bool(_RE_FOOTER_RENDERER.match(linea.strip()))


# ── La COLA de un eco ENVUELTO ─────────────────────────────────────────────
# es_eco_renderer clasifica por la marca inicial, y eso vale para UNA linea.
# El renderer imprime con rich sobre un pipe (ancho 80) y un AgenteFin con
# resumen largo sale ENVUELTO: solo la primera linea lleva ⏺, las siguientes
# son prosa pelada que se colaba al chat duplicando lo que el evento ya dijo.
# Medido con el REPL real (2026-08-18, /workflow contra :8080):
#     "  ⏺ agente 1/2 di solo ALFA — I'm sorry, but your message…"   (75)
#     "Could you please provide more context or clarify what you…"   (75)
#     "(1.3s · 77 tok)"                                              (15)
# Regla: tras un eco LARGO (rich solo parte lineas que llenan el ancho) las
# siguientes son cola hasta que una salga corta. Con TRES frenos, porque
# comerse prosa de verdad es peor que duplicar una linea: tope de lineas,
# nada que empiece como OTRA cosa (panel rich, marco, linea de logger,
# evento), y NINGUNA cola sobrevive a una linea-evento (ver _procesar_linea).
#
# ── El ANCHO del renderer bajo el remoto ──────────────────────────────────
# El REPL escribe a un pipe: rich no tiene terminal y cae a 80 columnas, y
# cada linea logica del renderer (un Aviso, un "⏺ tool — resumen") salia en
# 2-3 lineas FISICAS que este clasificador tenia que volver a juntar por
# heuristica. Medido en el e2e 2026-08-25 (verificador tras los arreglos):
#   - el aviso a priori de confianza (127 chars, sin marca) entraba al chat
#     como DOS burbujas cognia y se persistia en el jsonl;
#   - "  · filtrando https://kirainet.com/tokio-…-paris/…" (85) salia en
#     tres lineas ("  · filtrando" / la URL plegada a 80 / "/…") y las dos
#     ultimas iban al chat;
#   - y con _ANCHO_ECO = 60 un eco de 60-79 chars (URL de 46-65) se daba por
#     ENVUELTO sin estarlo y la RESPUESTA FINAL que venia detras se tragaba
#     entera como su cola: ni chat ni jsonl (sesion 20260825-100400).
# rich y shutil honran COLUMNS tambien sobre un pipe (verificado con el venv:
# 240 chars sin partir con COLUMNS=100000), asi que _entorno() fija el ancho
# y aqui se SABE cuanto mide: solo una linea que llega a ese ancho puede venir
# envuelta. No es infinito a proposito: los paneles rich se estiran al ancho
# entero y a 100000 el banner de arranque son 60 lineas de 100 KB (medido).
# 300 deja intactas las lineas logicas reales (_cabeza recorta a 200) y el
# banner en 60 x 300 bytes.
ANCHO_COLUMNAS_REMOTO = 300
# Margen para "llena el ancho": rich parte en el ULTIMO espacio que cabe, asi
# que la primera linea fisica de una logica envuelta mide al menos ancho -
# (palabra mas larga + 1); 40 cubre cualquier palabra de prosa. Las palabras
# mas largas que el ancho (URLs) se PLIEGAN exactamente al ancho.
_ANCHO_ECO = ANCHO_COLUMNAS_REMOTO - 40
_MAX_COLA_ECO = 4
_RE_NO_ES_COLA = re.compile(r"^\s*[│┌└├┤╭╰@]|^\d{4}-\d{2}-\d{2} ")
# Ancho MINIMO con el que un plegado de palabra (URL) es creible: ninguna
# terminal util baja de 40 columnas; por debajo, un prefijo a mitad de
# palabra es coincidencia, no envoltorio (ver _corte_de_envoltorio).
_ANCHO_MIN_PLEGADO = 40


def _corte_de_envoltorio(logica: str, fisica: str) -> bool:
    """¿`fisica` (linea fisica ya sin espacios a los lados) es el primer
    TROZO de la linea logica `logica`, cortada como corta rich? rich parte en
    un espacio (lo que sigue empieza por espacio) o pliega una palabra mas
    larga que el ancho justo al ancho (la fisica es larga). Un prefijo a
    mitad de palabra y corto no es un envoltorio: es otra linea."""
    if not fisica or not logica.startswith(fisica):
        return False
    if len(fisica) == len(logica):
        return True
    return logica[len(fisica)] == " " or len(fisica) >= _ANCHO_MIN_PLEGADO

# ── BLOQUES de actividad envueltos (e2e real 2026-08-25) ──────────────────
# Dos salidas del renderer llegan en VARIAS lineas y solo la primera lleva la
# marca que el regex de actividad reconoce:
#   diff de escribir_archivo: "+ El Imperio Romano no nacio como un imperio."
#       y despues, envueltas a 80 columnas SIN el "+", las 3-12 lineas del
#       parrafo; y un "+" solo para las lineas vacias del fichero. Medido:
#       un ensayo de 3000 palabras entro al chat como 150 "respuestas".
#   razonamiento "∴ ...": la continuacion va sangrada con 4 espacios.
# El bloque diff dura hasta la siguiente linea-evento o linea con marca (el
# ToolFin "⏺ escribir_archivo … RESULTADO" cierra siempre); el de sangria
# dura mientras las lineas vengan sangradas.
_RE_ABRE_DIFF = re.compile(r"^\+( |$)")
_RE_SANGRADA = re.compile(r"^ {4,}\S")


# ── Cola por WebSocket, CON TECHO ──────────────────────────────────────────
# Cada WS suscrito tenia una queue.Queue() sin maxsize. Un movil que se va 30 s
# en mitad de un workflow de 6 agentes (o simplemente con la red atascada: el
# servidor solo detecta la baja al ENVIAR) dejaba la cola creciendo sin limite
# — cada latido de AgenteProgreso, cada tool de cada agente. Con techo, lo que
# se tira son los eventos MAS VIEJOS (el movil quiere el estado de AHORA) y el
# descarte se CUENTA para anunciarlo: perder lineas en silencio es el modo de
# fallo historico del remoto, y una cola muda lo reintroduciria por la puerta
# de atras.

TOPE_COLA_WS = 500          # eventos por suscriptor


class ColaSuscriptor:
    """Cola FIFO con tope. Misma API que usa Sesion.anotar (put_nowait) y el
    WS (get), mas tomar_descartadas() para que el cliente vea el agujero."""

    def __init__(self, tope: int | None = None, al_poner=None):
        # el default se lee EN LA CONSTRUCCION, no al definir la clase: asi
        # TOPE_COLA_WS es ajustable (y verificable) sin tocar los llamadores
        self.tope = max(1, int(TOPE_COLA_WS if tope is None else tope))
        self._q: queue.Queue = queue.Queue()
        self._descartadas = 0
        self._lock = threading.Lock()
        # al_poner(): se llama DESPUES de encolar (fuera del lock). Es como el
        # WS del servidor se entera sin clavar un hilo del pool en get(): el
        # endpoint le pasa un call_soon_threadsafe sobre un asyncio.Event.
        # Si revienta (loop ya cerrado al apagar), la excepcion sube al
        # productor, que descarta la cola y lo deja en stderr — no es mudo.
        self._al_poner = al_poner

    def put_nowait(self, evento: dict) -> None:
        with self._lock:
            while self._q.qsize() >= self.tope:
                try:
                    self._q.get_nowait()
                except queue.Empty:
                    break
                self._descartadas += 1
            self._q.put_nowait(evento)
        if self._al_poner is not None:
            self._al_poner()

    def get(self, timeout: float | None = None):
        return self._q.get(timeout=timeout)

    def get_nowait(self):
        return self._q.get_nowait()

    def tomar_descartadas(self) -> int:
        """Cuantas se tiraron desde la ultima vez (y resetea). El WS lo llama
        antes de cada envio: el aviso viaja PEGADO al primer evento que si
        llega, en el mismo orden en que el usuario lo va a leer."""
        with self._lock:
            n, self._descartadas = self._descartadas, 0
            return n

    def __len__(self) -> int:
        return self._q.qsize()


def _python_cognia() -> list[str]:
    """El interprete que corre el REPL: el mismo venv del servidor."""
    return [sys.executable, "-m", "cognia"]


def _flags_grupo_propio() -> dict:
    """kwargs de Popen para que el hijo tenga grupo de proceso propio.
    Windows: CREATE_NEW_PROCESS_GROUP (unico modo de dirigirle un
    CTRL_BREAK_EVENT a EL y no a toda la consola); POSIX: sesion nueva."""
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


# La senal de interrupcion que entiende el hijo. En Windows CTRL_C_EVENT no
# se puede dirigir a un grupo distinto del propio (y CREATE_NEW_PROCESS_GROUP
# deshabilita Ctrl-C en el hijo): queda CTRL_BREAK, que Python entrega como
# SIGBREAK. En POSIX, SIGINT = el Ctrl-C de toda la vida.
_SENAL_INTERRUPCION = (signal.CTRL_BREAK_EVENT if os.name == "nt"
                       else signal.SIGINT)

# Lo que devuelve /interrumpir cuando la senal salio: el front lo pinta tal
# cual (test_remoto_front lo busca), por eso es una constante compartida.
MOTIVO_INTERRUPCION_ENVIADA = ("senal enviada; se aplica al terminar la "
                               "llamada en curso (una llamada bloqueada "
                               "esperando al modelo no se despierta antes)")


_SOPORTE_CONTINUACION: list = []      # cache: [bool]


def repl_soporta_continuacion() -> bool:
    """True si el cli.py que va a correr (el de este mismo paquete: el REPL
    hijo se lanza con PYTHONPATH al repo) tiene _leer_con_continuacion. Se
    mira la fuente, no se importa cognia.cli (17k lineas y medio Cognia)."""
    if not _SOPORTE_CONTINUACION:
        try:
            fuente = (Path(__file__).resolve().parent.parent / "cli.py"
                      ).read_text(encoding="utf-8", errors="replace")
            _SOPORTE_CONTINUACION.append("def _leer_con_continuacion(" in fuente)
        except OSError:
            _SOPORTE_CONTINUACION.append(False)
    return _SOPORTE_CONTINUACION[0]


def modo_multilinea() -> str:
    """'continuacion' | 'unir' (ver el bloque MULTILINEA). El env manda; sin
    env, continuacion si el REPL la soporta."""
    pedido = os.environ.get("COGNIA_REMOTO_MULTILINEA", "").strip().lower()
    if pedido in ("continuacion", "unir"):
        return pedido
    return "continuacion" if repl_soporta_continuacion() else "unir"


def entradas_para_repl(texto: str) -> list[str]:
    """Las lineas que se escriben al stdin del REPL por UN mensaje del movil.
    Un mensaje sin saltos es una linea. Con saltos, segun modo_multilinea():
    el protocolo de continuacion (N lineas = UNA entrada con "\n") o una
    sola linea unida con espacios."""
    if "\n" not in texto:
        return cerrar_barra_final([texto])
    if modo_multilinea() == "continuacion":
        return cerrar_barra_final(lineas_continuacion(texto))
    unida = a_entrada_repl(texto)
    return cerrar_barra_final([unida]) if unida else []


def ruta_pid(proyecto_id: str, sid: str) -> Path:
    d = RAIZ_DATOS / proyecto_id
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{sid}.pid"


def _proceso_vivo(pid: int):
    """El psutil.Process si el PID existe y es un python; None si no hay
    nadie o el PID lo tiene otro programa. Que ademas sea NUESTRO (un
    `python -m cognia` nacido antes del .pid) lo decide es_repl_cognia: un
    python cualquiera no basta, ver el hallazgo en reconciliar_huerfanos."""
    try:
        import psutil
    except ImportError as e:
        # sin psutil no hay reconciliacion segura (no se puede distinguir un
        # PID reciclado): se dice en stderr y NO se mata a ciegas
        print(f"[remoto] sin psutil ({e}): no reconcilio huerfanos",
              file=sys.stderr, flush=True)
        return None
    try:
        pr = psutil.Process(pid)
        if not pr.is_running() or pr.status() == psutil.STATUS_ZOMBIE:
            return None
        if not pr.name().lower().startswith("python"):
            return None            # PID reciclado: no es nuestro REPL
        return pr
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return None


# Holgura entre el create_time del proceso y el mtime del .pid: el .pid se
# escribe justo DESPUES del Popen (create_time < mtime por milisegundos), pero
# los dos relojes no son el mismo (kernel vs sistema de ficheros) y en
# Windows el create_time se redondea. Un PID reciclado nace segundos, minutos
# o dias despues del .pid: 5 s los separa de sobra.
HOLGURA_CREATE_TIME_S = 5.0


def cmdline_es_cognia(cmdline: list[str] | None, modulo: str = "cognia") -> bool:
    """True si la linea de comandos es `python -m cognia[.algo] ...`: el
    token que sigue a "-m" es exactamente `modulo` o empieza por `modulo.`.
    Por TOKEN y no por subcadena: "-m cognia_prueba" no es Cognia, y una
    ruta de script que contenga "cognia" tampoco (el REPL siempre nace como
    `-m cognia`, ver _python_cognia)."""
    if not cmdline:
        return False
    for i, tok in enumerate(cmdline[:-1]):
        if tok == "-m":
            sig = cmdline[i + 1]
            if sig == modulo or sig.startswith(modulo + "."):
                return True
    return False


def es_repl_cognia(pr, mtime_pid: float | None) -> tuple[bool, str]:
    """(es_nuestro, motivo): el proceso `pr` (psutil.Process vivo) es el REPL
    que este .pid describe. Dos pruebas, las dos obligatorias:
      1. la cmdline contiene `-m cognia` (el REPL nace asi; un jupyter, un
         script o un `python -c` que hereden el PID reciclado no);
      2. nacio ANTES de que se escribiera el .pid (mas HOLGURA): un PID
         reciclado nace despues.
    Sin cmdline legible (AccessDenied) no se mata: la duda no es evidencia."""
    try:
        cmd = pr.cmdline()
    except Exception as e:                    # AccessDenied, NoSuchProcess
        return False, f"cmdline ilegible ({type(e).__name__})"
    if not cmdline_es_cognia(cmd):
        return False, "no es un `python -m cognia` (" + " ".join(cmd)[:80] + ")"
    if mtime_pid is not None:
        try:
            nacido = float(pr.create_time())
        except Exception as e:
            return False, f"create_time ilegible ({type(e).__name__})"
        if nacido > mtime_pid + HOLGURA_CREATE_TIME_S:
            return False, (f"nacio {nacido - mtime_pid:.0f} s DESPUES del .pid: "
                           "PID reciclado")
    return True, "ok"


def reconciliar_huerfanos(raiz: Path | None = None,
                          es_nuestro=es_repl_cognia) -> list[dict]:
    """Al ARRANCAR el servidor: los .pid que quedaron de un servidor anterior
    son REPLs huerfanos (el gestor vive en memoria; el stdout de un proceso
    ajeno no se puede readoptar). Se MATAN y se anota en su jsonl. Devuelve
    [{"proyecto", "sesion", "pid", "accion"}] para imprimirlo en el arranque.
    Se llama desde main(), NUNCA desde crear_app(): los tests crean apps con
    la RAIZ_DATOS real y no deben tocar los REPLs de un servidor vivo.

    QUE se mata (hallazgos rev1/rev2 2026-08-25, los dos reproducidos):
      - solo un proceso que `es_nuestro(pr, mtime_del_pid)` acepte: por
        defecto es_repl_cognia (cmdline `-m cognia` + nacido antes del
        .pid). La primera version mataba CUALQUIER python cuyo PID
        coincidiera (Windows recicla PIDs con ganas: un jupyter o un REPL
        local del dueno moria con todos sus hijos y el jsonl decia
        "terminado"). Un .pid que no pasa la prueba se BORRA (esta rancio)
        y se dice, sin matar.
      - y nada de esto si hay OTRO servidor vivo: eso lo decide main() con
        leer_pid_servidor ANTES de llamar aqui (los .pid de un servidor vivo
        son indistinguibles de los de uno muerto; arrancar un segundo
        servidor mataba las sesiones del primero, medido con dos reales).
    `es_nuestro` es parametro para probar el predicado y el bucle por
    separado (un hijo real `-m cognia` de mentira vs un `python -c`)."""
    raiz = raiz or RAIZ_DATOS
    salida = []
    for f in sorted(raiz.glob("*/*.pid")):
        try:
            pid = int(f.read_text(encoding="utf-8").strip())
            mtime = f.stat().st_mtime
        except (OSError, ValueError) as e:
            salida.append({"proyecto": f.parent.name, "sesion": f.stem,
                           "pid": None, "accion": f"pid ilegible ({e}); borrado"})
            f.unlink(missing_ok=True)
            continue
        pr = _proceso_vivo(pid)
        nuestro, motivo = (False, "") if pr is None else es_nuestro(pr, mtime)
        if pr is None:
            accion = "ya no corria"
        elif not nuestro:
            # vivo pero NO es el REPL de este .pid: el PID se reciclo. Se
            # deja en paz y el .pid rancio se retira (anotando el motivo).
            accion = f"vivo pero no es nuestro REPL ({motivo}): no lo toco"
        else:
            # psutil ya importo bien (pr viene de _proceso_vivo); el nombre
            # hace falta AQUI: sin este import, un hijo que no se dejaba
            # matar daba NameError en el except (tapado por el Exception de
            # abajo como "no pude terminarlo: NameError") — cazado 2026-08-25
            import psutil
            try:
                # los nietos (tools lanzadas por el REPL) tambien: sin esto
                # quedaban vivos colgando de nadie. Uno que ya murio no es
                # error; uno que no se deja se CUENTA en la accion.
                hijos_vivos = 0
                for hijo in pr.children(recursive=True):
                    try:
                        hijo.kill()
                    except psutil.NoSuchProcess:
                        continue
                    except psutil.Error:
                        hijos_vivos += 1
                pr.kill()
                pr.wait(timeout=5)
                accion = "terminado" + (f" ({hijos_vivos} hijos no se dejaron)"
                                        if hijos_vivos else "")
            except Exception as e:
                accion = f"no pude terminarlo: {type(e).__name__}: {e}"
        jsonl = f.with_suffix(".jsonl")
        try:
            with jsonl.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(
                    {"t": time.strftime("%H:%M:%S"), "quien": "sistema",
                     "texto": "sesion anterior terminada al reiniciar el "
                              f"servidor (pid {pid}: {accion})"},
                    ensure_ascii=False) + "\n")
        except OSError as e:
            accion += f"; sin anotar en el jsonl ({e})"
        f.unlink(missing_ok=True)
        salida.append({"proyecto": f.parent.name, "sesion": f.stem,
                       "pid": pid, "accion": accion})
    return salida


# ── servidor.pid: UN formato (JSON) y una sola lectura para todos ──────────
# Escrito por servidor.main() como {"pid", "host", "port"}. Lo leen el propio
# servidor al arrancar (¿hay otro vivo? -> no reconciliar ni pisar) y el CLI
# (/remoto estado|parar, via leer_pid_servidor). Hasta 2026-08-25 el CLI
# escribia str(pid), el servidor lo pisaba con JSON y el CLI leia int(): el
# servidor arrancado desde /remoto arrancar era invisible para /remoto parar.
# Ademas el fichero solo se borraba en salida limpia: tras un kill
# (TerminateProcess, lo que hace /remoto parar) quedaba rancio. Un fichero
# rancio no se puede evitar del todo (TerminateProcess no da ocasion de
# borrar nada): por eso la LECTURA comprueba que el PID este vivo y sea un
# servidor de Cognia, y trata el resto como rancio diciendolo.

FICHERO_PID_SERVIDOR = "servidor.pid"


def ruta_pid_servidor(raiz: Path | None = None) -> Path:
    return (raiz or RAIZ_DATOS) / FICHERO_PID_SERVIDOR


def _escucha_en(pr, port) -> bool | None:
    """True si el proceso tiene un socket LISTEN en `port` (cualquier IP);
    False si no; None si no se pudo mirar (AccessDenied: el proceso es de
    otro usuario o el sistema no deja) — la duda se devuelve como duda, el
    llamador decide (para no matar sesiones no se resuelve como False)."""
    try:
        port = int(port)
    except (TypeError, ValueError):
        return False
    try:
        try:
            conexiones = pr.net_connections(kind="inet")
        except AttributeError:                # psutil < 6
            conexiones = pr.connections(kind="inet")
    except Exception as e:
        import logging
        logging.getLogger("cognia.remoto").warning(
            "no pude leer las conexiones del pid %s: %s", pr.pid, e)
        return None
    return any(c.status == "LISTEN" and c.laddr and c.laddr.port == port
               for c in conexiones)


def es_servidor_cognia(pr, info: dict) -> tuple[bool, str]:
    """(es_servidor, motivo): `pr` (psutil.Process vivo) es un servidor del
    remoto. Vale UNA de dos pruebas: la cmdline es `-m cognia.remoto` (o
    `-m cognia` a secas: el CLI lo lanza asi) O el proceso ESCUCHA en el
    puerto que el propio fichero declara. La segunda cubre a un servidor
    arrancado en proceso con crear_app() (tests, e2e: cmdline `python
    script.py`), que un PID reciclado no puede imitar: tendria que estar
    escuchando justo en ese puerto."""
    try:
        cmd = pr.cmdline()
    except Exception:
        cmd = None
    if cmdline_es_cognia(cmd):
        return True, "cmdline -m cognia"
    escucha = _escucha_en(pr, info.get("port"))
    if escucha:
        return True, f"escucha en :{info.get('port')}"
    if escucha is None:
        # inconcluso: un python vivo cuyo puerto no se puede mirar. Se da
        # por servidor POR PRUDENCIA (el coste de equivocarse al reves es
        # reconciliar y matar los REPLs de un servidor vivo) y se dice.
        return True, (f"python vivo; no pude comprobar si escucha en "
                      f":{info.get('port')} — lo doy por servidor por prudencia")
    return False, ("no es `-m cognia` ni escucha en :" + str(info.get("port"))
                   + " (" + " ".join(cmd or ["?"])[:80] + ")")


def estado_pid_servidor(raiz: Path | None = None) -> tuple[dict | None, str]:
    """(info, motivo). info = {"pid", "host", "port", "vivo": True} solo si el
    fichero existe, es JSON con "pid" y ese PID es un servidor de Cognia
    vivo; si no, None y el motivo legible ("no hay servidor.pid", "formato
    viejo (int) ...", "pid N muerto", "pid N no es un servidor ...")."""
    f = ruta_pid_servidor(raiz)
    try:
        crudo = f.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None, "no hay servidor.pid"
    except OSError as e:
        return None, f"servidor.pid ilegible: {e}"
    try:
        info = json.loads(crudo)
        if not isinstance(info, dict) or "pid" not in info:
            raise ValueError("sin clave pid")
        pid = int(info["pid"])
    except (ValueError, TypeError) as e:
        forma = "formato viejo (int)" if crudo.isdigit() else "no es JSON"
        return None, f"servidor.pid rancio: {forma} ({e}): {crudo[:60]!r}"
    pr = _proceso_vivo(pid)
    if pr is None:
        return None, f"servidor.pid rancio: pid {pid} muerto (o no es python)"
    ok, motivo = es_servidor_cognia(pr, info)
    if not ok:
        return None, f"servidor.pid rancio: pid {pid} vivo pero {motivo}"
    return ({"pid": pid, "host": info.get("host"), "port": info.get("port"),
             "vivo": True}, motivo)


def leer_pid_servidor(raiz: Path | None = None,
                      borrar_rancio: bool = True) -> dict | None:
    """El servidor del remoto VIVO segun servidor.pid, o None. Es la unica
    lectura del fichero (la usa el CLI: /remoto estado y /remoto parar).
    Un fichero rancio (pid muerto, reciclado, formato viejo) se anuncia por
    el logger y, con borrar_rancio, se retira para que no vuelva a confundir
    (un servidor que arranca lo reescribe)."""
    info, motivo = estado_pid_servidor(raiz)
    if info is None and motivo != "no hay servidor.pid":
        import logging
        logging.getLogger("cognia.remoto").warning("%s", motivo)
        if borrar_rancio:
            try:
                ruta_pid_servidor(raiz).unlink(missing_ok=True)
            except OSError as e:
                logging.getLogger("cognia.remoto").warning(
                    "no pude borrar el servidor.pid rancio: %s", e)
    return info


def carpetas_huerfanas(raiz: Path | None = None) -> list[Path]:
    """Carpetas de RAIZ_DATOS que no corresponden a ningun proyecto de
    proyectos.json (hoy 1154 medidas en ~/.cognia/remoto: tests que no
    parchearon RAIZ_DATOS). La papelera se respeta."""
    raiz = raiz or RAIZ_DATOS
    try:
        ids = {pr["id"] for pr in json.loads(
            (raiz / "proyectos.json").read_text(encoding="utf-8"))}
    except (OSError, ValueError, TypeError, KeyError):
        ids = set()
    return [d for d in sorted(raiz.iterdir())
            if d.is_dir() and d.name != "papelera" and d.name not in ids]


def limpiar_huerfanas(raiz: Path | None = None,
                      dry_run: bool = False) -> list[str]:
    """Borra (o lista, con dry_run) las carpetas huerfanas. Devuelve las
    rutas afectadas; un borrado fallido se devuelve con el motivo."""
    salida = []
    for d in carpetas_huerfanas(raiz):
        if dry_run:
            salida.append(str(d))
            continue
        try:
            shutil.rmtree(d)
            salida.append(str(d))
        except OSError as e:
            salida.append(f"{d} (NO borrada: {e})")
    return salida


# ── Proyectos: carpetas donde se abre el CLI ───────────────────────────────

def cargar_proyectos() -> list[dict]:
    try:
        return json.loads(FICHERO_PROYECTOS.read_text(encoding="utf-8"))
    except Exception:
        return []


def guardar_proyectos(proyectos: list[dict]) -> None:
    FICHERO_PROYECTOS.write_text(
        json.dumps(proyectos, indent=2, ensure_ascii=False), encoding="utf-8")


def registrar_proyecto(ruta: str) -> dict:
    """Alta (o reuso) de un proyecto por su carpeta. Nombre = la carpeta."""
    p = Path(ruta).expanduser().resolve()
    if not p.is_dir():
        raise ValueError(f"No es una carpeta: {p}")
    proyectos = cargar_proyectos()
    for pr in proyectos:
        if Path(pr["ruta"]).resolve() == p:
            return pr
    pr = {"id": uuid.uuid4().hex[:8], "nombre": p.name or str(p),
          "ruta": str(p), "creado": time.strftime("%Y-%m-%d %H:%M")}
    proyectos.append(pr)
    guardar_proyectos(proyectos)
    (RAIZ_DATOS / pr["id"]).mkdir(exist_ok=True)
    return pr


# ── Sesiones ───────────────────────────────────────────────────────────────

@dataclass
class Sesion:
    id: str
    proyecto_id: str
    ruta_proyecto: str
    titulo: str
    # nivel de permiso del REPL: "total" (el historico: el dueno pilota SU
    # maquina desde el movil, acceso total + computer-use) o "restringido"
    # (sin COGNIA_ACCESO_TOTAL ni tools de pantalla — para sesiones que solo
    # conversan/leen). Default "total" para no romper el movil existente.
    acceso: str = "total"
    proc: subprocess.Popen | None = None
    suscriptores: list = field(default_factory=list)   # [queue.Queue]
    lock: threading.Lock = field(default_factory=threading.Lock)
    # estado del clasificador: dentro de un traceback multilinea
    _en_traza: bool = False
    # el banner/panel de arranque no llega ni al Registro: se descarta hasta
    # ver el final del arranque (compacto o banner full), con tope de lineas.
    # OJO: lo descartado se GUARDA en _buffer_arranque — si el REPL muere
    # arrancando, ese buffer es el traceback que antes se perdia y el movil
    # veia puro silencio (bug historico, fix 2026-08-09).
    _arrancando: bool = True
    _lineas_arranque: int = 0
    _buffer_arranque: list = field(default_factory=list)
    # True desde la primera linea-evento "@EV": a partir de ahi los eventos
    # tipados mandan y los adornos del renderer (duplicados) se saltan
    _con_eventos: bool = False
    # lineas que el renderer va a imprimir por eventos ya anotados (intencion,
    # resumen de tools): el bombeo las salta para no duplicar en el movil
    _ecos_pendientes: deque = field(default_factory=lambda: deque(maxlen=64))
    # cuantas lineas de COLA de un eco envuelto quedan por saltar (ver
    # _ANCHO_ECO): un AgenteFin con resumen largo sale en 2-3 lineas y solo la
    # primera lleva la marca ⏺
    _cola_eco: int = 0
    # lo que FALTA de un eco pendiente casado por su primer trozo (un Aviso
    # envuelto por rich): las siguientes lineas fisicas se casan contra esto,
    # exacto, sin heuristica de longitud (ver _casar_eco)
    _eco_resto: str = ""
    # hilo lector: se guarda para poder join() en parar() — sin eso, su
    # anotar("sesion terminada") final corria DESPUES de mover/borrar el
    # jsonl y recreaba la carpeta de la sesion recien dada de baja
    _bomba: threading.Thread | None = None
    # "" | "diff" | "sangria": dentro de un bloque de actividad envuelto (ver
    # _RE_ABRE_DIFF); sus lineas sin marca son actividad, no chat
    _bloque_actividad: str = ""
    # agrupador de TokenTexto -> "delta" (ver AgrupadorDelta): se crea en el
    # primer uso para que los tests construyan Sesion() sin mas ceremonia
    _delta: AgrupadorDelta | None = None

    # ── persistencia ──
    @property
    def fichero(self) -> Path:
        d = RAIZ_DATOS / self.proyecto_id
        d.mkdir(exist_ok=True)
        return d / f"{self.id}.jsonl"

    @property
    def fichero_pid(self) -> Path:
        """<RAIZ_DATOS>/<proyecto>/<sid>.pid: el PID del REPL hijo, para que un
        servidor que reinicia pueda RECONCILIAR (matar) al huerfano. Se borra
        cuando el hijo termina por las buenas."""
        return ruta_pid(self.proyecto_id, self.id)

    def anotar(self, quien: str, texto: str, ag: dict | None = None,
               extra: dict | None = None) -> dict:
        """`ag` = agrupacion por agente (ver agente_de_evento). Va al jsonl,
        no solo al WS: un workflow terminado se REABRE desde la transcripcion
        y el bloque por agente tiene que rearmarse igual que en vivo.
        `extra` = campos tipados del evento (nivel/fuentes de la confianza,
        numeros del footer) que el movil pinta ademas del texto."""
        evento = {"t": time.strftime("%H:%M:%S"), "quien": quien,
                  "texto": texto}
        if ag:
            evento["ag"] = ag
        if extra:
            for k, v in extra.items():
                evento.setdefault(k, v)
        with self.fichero.open("a", encoding="utf-8") as f:
            f.write(json.dumps(evento, ensure_ascii=False) + "\n")
        self._emitir_suscriptores(evento)
        return evento

    def _emitir_suscriptores(self, evento: dict) -> None:
        """Solo a las colas de los WS, SIN tocar el jsonl. Es el canal de los
        "delta" del streaming: efimeros por diseno (la transcripcion guarda la
        respuesta final, no sus trozos)."""
        with self.lock:
            for q in list(self.suscriptores):
                try:
                    q.put_nowait(evento)
                except Exception as e:
                    # una cola rota no puede tumbar el bombeo de las demas;
                    # pero tampoco se pierde en silencio: se saca del registro
                    # y se deja constancia en stderr del servidor
                    print(f"[remoto] suscriptor descartado ({type(e).__name__}: "
                          f"{e})", file=sys.stderr, flush=True)
                    try:
                        self.suscriptores.remove(q)
                    except ValueError:
                        continue      # ya la quito el WS al desconectar

    def _emitir_delta(self, trozo: str) -> None:
        self._emitir_suscriptores({"t": time.strftime("%H:%M:%S"),
                                   "quien": "delta", "texto": trozo})

    def _agrupador(self) -> AgrupadorDelta:
        if self._delta is None:
            self._delta = AgrupadorDelta(self._emitir_delta)
        return self._delta

    def transcripcion(self, limite: int = 400) -> list[dict]:
        try:
            lineas = self.fichero.read_text(encoding="utf-8").splitlines()
            eventos = [json.loads(l) for l in lineas[-limite:]]
        except Exception:
            return []
        # Reclasificar tambien lo VIEJO: las sesiones anteriores al filtrado
        # de servidor guardaron banner/tracebacks como "cognia"; al leerlas se
        # corrigen para que el chat quede limpio sin tocar el fichero.
        salida, en_traza = [], False
        for e in eventos:
            quien, en_traza = reclasificar(
                e.get("quien", ""), e.get("texto", ""), en_traza)
            salida.append({**e, "quien": quien})
        return salida

    # ── el subproceso REPL ──
    def viva(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def _entorno(self) -> dict:
        """El env del REPL. Separado de arrancar() para poder verificarlo en
        tests sin lanzar un proceso real."""
        # PYTHONPATH al repo: el cwd del REPL es la carpeta del PROYECTO, no
        # el repo, y en modo desarrollo `python -m cognia` no resolveria el
        # paquete (medido: "No module named cognia" en la primera sesion).
        raiz_repo = str(Path(__file__).resolve().parent.parent.parent)
        pp = os.environ.get("PYTHONPATH", "")
        env = dict(os.environ,
                   PYTHONUTF8="1", PYTHONIOENCODING="utf-8",
                   # sin esto, cualquier print() del REPL a este pipe queda
                   # block-buffered (8 KB) y el movil no lo ve hasta que se
                   # llene el buffer: el chat parece congelado
                   PYTHONUNBUFFERED="1",
                   NO_COLOR="1", TERM="dumb",
                   # ANCHO conocido: sin COLUMNS, rich sobre un pipe envuelve
                   # a 80 y cada linea logica del renderer llega partida en
                   # 2-3 fisicas que el clasificador no sabe volver a juntar
                   # (avisos al chat, respuesta final tragada como "cola" —
                   # e2e 2026-08-25). Ver ANCHO_COLUMNAS_REMOTO.
                   COLUMNS=str(ANCHO_COLUMNAS_REMOTO),
                   # "corres dentro del control remoto": el CLI deja de
                   # enmarcar la RESPUESTA FINAL del agente en un panel rich.
                   # El marco la mandaba a Actividad (plegada) y parecia que
                   # Cognia no habia contestado (sesion 2026-07-25).
                   COGNIA_REMOTO="1",
                   # eventos tipados por stdout ("@EV {json}"): el canal
                   # primario de esta sesion — se clasifica por TIPO, el
                   # regex queda de fallback para la prosa (obra 2026-08-09)
                   COGNIA_EVENTS_JSONL="1",
                   PYTHONPATH=(raiz_repo + (os.pathsep + pp if pp else "")))
        if self.acceso == "total":
            # ACCESO TOTAL en el control remoto: el dueño pilota SU maquina
            # desde el movil sin canal de confirmacion, asi Cognia puede
            # abrir apps/navegar/operar el equipo. El BLOCK duro del
            # Sentinel (rm -rf, format, shutdown, borrados recursivos...)
            # sigue activo como ultima red.
            env["COGNIA_ACCESO_TOTAL"] = "1"
            # computer-use completo: tools de pantalla (captura, click,
            # teclado) activas y sin confirmacion interactiva — el dueno
            # pidio acceso total a su equipo desde el movil. FAILSAFE de
            # pyautogui sigue: mover el mouse a una esquina ABORTA.
            env["COGNIA_SCREEN"] = "1"
            env["COGNIA_SCREEN_AUTO"] = "1"
        else:
            # "restringido": sin acceso total ni computer-use. Se LIMPIAN por
            # si el servidor mismo corre con esas vars en su entorno — heredar
            # seria un bypass silencioso del nivel de permiso.
            for var in ("COGNIA_ACCESO_TOTAL", "COGNIA_SCREEN",
                        "COGNIA_SCREEN_AUTO"):
                env.pop(var, None)
        return env

    def arrancar(self) -> None:
        if self.viva():
            return
        # estado del bombeo FRESCO por arranque: al re-abrir una sesion parada
        # (enviar() re-arranca) el gate del banner tiene que volver a actuar —
        # antes quedaba en False y el banner del segundo arranque iba al chat
        self._arrancando = True
        self._lineas_arranque = 0
        self._buffer_arranque = []
        self._con_eventos = False
        self._en_traza = False
        self._cola_eco = 0
        self._eco_resto = ""
        self._ecos_pendientes.clear()
        self._bloque_actividad = ""
        env = self._entorno()
        self.proc = subprocess.Popen(
            _python_cognia(), cwd=self.ruta_proyecto,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8",
            errors="replace", bufsize=1, env=env,
            # grupo de proceso PROPIO: es lo que permite interrumpir una
            # generacion desde el movil (interrumpir()) sin tocar al servidor
            # ni a las otras sesiones — ver _flags_grupo_propio
            **_flags_grupo_propio())
        try:
            self.fichero_pid.write_text(str(self.proc.pid), encoding="utf-8")
        except OSError as e:
            # sin .pid la sesion funciona igual; solo pierde la reconciliacion
            # al reiniciar el servidor. Se dice, no se calla.
            self.anotar("sistema", f"no pude persistir el PID del REPL: {e}")
        self._bomba = threading.Thread(target=self._bombear, daemon=True,
                                       name=f"remoto-{self.id}")
        self._bomba.start()
        self.anotar("sistema", f"sesion arrancada en {self.ruta_proyecto}")

    def interrumpir(self) -> dict:
        """Cortar la generacion en curso SIN matar el REPL: {"ok", "motivo"}.

        Mecanismo (contrato A, 2026-08-24): el hijo nacio en su propio grupo
        y recibe CTRL_BREAK_EVENT (Windows) / SIGINT (POSIX). El REPL, bajo
        COGNIA_REMOTO, instala un handler de SIGBREAK que lanza
        KeyboardInterrupt en el hilo principal y cae en los `except
        KeyboardInterrupt` del fast-path y del agente. MEDIDO 2026-08-24 con
        un hijo python real: la senal llega en <10 ms; el KeyboardInterrupt
        se dispara en el siguiente limite de bytecode, asi que corta un
        stream (un token cada pocos ms) pero NO despierta un sleep() ni un
        socket bloqueado sin datos — ahi espera al primer byte.
        SIN handler en el hijo, CTRL_BREAK lo MATA (default de Windows): por
        eso el REPL de Cognia lo instala y un `python -c` cualquiera no
        sobreviviria."""
        if not self.viva():
            return {"ok": False, "motivo": "la sesion no esta viva"}
        if self._arrancando:
            # antes de que cli.py instale el handler, CTRL_BREAK lo MATA
            # (medido en el test del endpoint: el REPL moria y enviar() lo
            # re-arrancaba en silencio). El handler se instala antes del
            # banner; el gate cierra con el banner: "arrancando" = sin handler.
            return {"ok": False, "motivo": "el REPL todavia esta arrancando; "
                                           "no hay nada que interrumpir"}
        try:
            self.proc.send_signal(_SENAL_INTERRUPCION)   # type: ignore[union-attr]
        except Exception as e:
            motivo = f"no pude enviar la senal: {type(e).__name__}: {e}"
            self.anotar("sistema", f"interrupcion fallida — {motivo}")
            return {"ok": False, "motivo": motivo}
        # El motivo dice el LIMITE, no solo el hecho: el handler del REPL
        # corre en el siguiente bytecode, asi que una llamada C bloqueada
        # (socket sin datos en el prefill del 27B, join) la retrasa hasta que
        # vuelve — medido 2026-08-25: senal a +0,5 s, KeyboardInterrupt a
        # +10 s (join) y a +128 s (urlopen del router). El movil muestra este
        # texto para que "Detener" no parezca muerto. La cancelacion
        # cooperativa (que el cliente HTTP consulte una bandera) es del REPL,
        # no de aqui.
        self.anotar("sistema", "interrupcion enviada al REPL desde el remoto")
        return {"ok": True, "motivo": MOTIVO_INTERRUPCION_ENVIADA}

    def _procesar_linea(self, linea: str) -> None:
        """Clasifica UNA linea ya limpia y la anota. Primero los eventos
        tipados (@EV {json}); el regex de siempre queda como fallback para la
        prosa del CLI y para REPLs sin bus de eventos."""
        # 1) linea-evento: clasificacion por TIPO, no por forma. Se juzga
        # ANTES del gate de arranque: un Degradado emitido durante el arranque
        # (backend caido) es senal, nunca banner.
        d = parsear_evento(linea)
        resto_prosa = ""
        if d is None:
            # evento pegado al FINAL de una prosa a medias: el renderer y el
            # sink comparten stdout y un print() del sink puede caer en una
            # linea que el streaming dejo sin \n (medido en el e2e 2026-08-09:
            # "¡Hola! ¿En qué puedo @EV {...}"). Se separan: el evento se
            # procesa PRIMERO (registra sus ecos) y la prosa sigue sola.
            idx = linea.find(_PREFIJO_EV)
            if idx > 0:
                d2 = parsear_evento(linea[idx:])
                if d2 is not None:
                    d, resto_prosa = d2, linea[:idx].rstrip()
        if d is not None:
            self._con_eventos = True
            self._bloque_actividad = ""     # un evento cierra todo bloque
            # ...y toda COLA de eco. El renderer imprime una linea logica
            # envuelta de una vez (un console.print bajo su lock), asi que
            # una linea-evento entre medias significa que la cola termino.
            # Sin esto, un "  · filtrando <url>" de 64 chars dejaba
            # _cola_eco=4 armada por encima de los TokenTexto y la RESPUESTA
            # FINAL ("89.8 mil suscriptores [4].") se tragaba como cola: ni
            # chat ni jsonl (e2e 2026-08-25, sesion 20260825-100400).
            self._cola_eco = 0
            self._eco_resto = ""
            if d.get("tipo") == "FooterTurno":
                # fin del turno: un eco que el renderer no pinto (bajo remoto
                # la linea de Confianza no se pinta; los Avisos repetidos los
                # de-duplica el renderer) ya no va a llegar. Se vacia para
                # que no case por prefijo prosa de otro turno.
                self._ecos_pendientes.clear()
            if d.get("tipo") == "TokenTexto":
                # streaming al movil: se agrupa y va SOLO a los suscriptores
                # (contrato C). No se anota: la respuesta final llega entera.
                if resto_prosa.strip():
                    self._procesar_linea(resto_prosa)
                self._agrupador().token(str(d.get("texto") or ""))
                return
            # cualquier otro evento cierra el trozo pendiente: el orden que
            # ve el movil es el de stdout
            self._agrupador().vaciar()
            quien, texto, ecos = interpretar_evento(d)
            for eco in ecos:
                self._ecos_pendientes.append(eco)
            if quien is not None and texto:
                self.anotar(quien, texto, agente_de_evento(d),
                            extra_de_evento(d))
            if resto_prosa.strip():
                self._procesar_linea(resto_prosa)
            return
        # prosa: lo que hubiera en el agrupador va ANTES que ella
        self._agrupador().vaciar()
        # 2) banner/panel de arranque: se descarta de la transcripcion pero se
        # GUARDA — si el REPL muere aqui, el buffer es el traceback perdido.
        # Fin del arranque: ver _FIN_ARRANQUE / _RE_FIN_BANNER, o el tope.
        if self._arrancando:
            self._lineas_arranque += 1
            self._buffer_arranque.append(linea)
            if (any(m in linea for m in _FIN_ARRANQUE)
                    or _RE_FIN_BANNER.search(linea)
                    or self._lineas_arranque > 200):
                self._arrancando = False
            return
        # 3) con eventos activos, los adornos del renderer (⏺/·/✗/⚠, footer)
        # y los ecos ya anotados via evento son duplicados: se saltan
        if self._con_eventos:
            # 3a) ecos de eventos ya anotados: la linea entera o, si rich la
            # envolvio, trozo a trozo (exacto, ver _casar_eco). Va ANTES de
            # la marca del renderer: el texto del evento es mas fiable que
            # la forma de la linea, y un Aviso ("  ◐ confianza a priori…")
            # no lleva marca ninguna.
            if self._casar_eco(linea.strip()):
                self._cola_eco = 0
                self._bloque_actividad = ""
                return
            if es_eco_renderer(linea):
                # un eco que llena el ancho viene ENVUELTO: lo que sigue es su
                # cola sin marca (ver _ANCHO_ECO)
                self._cola_eco = (_MAX_COLA_ECO
                                  if len(linea.rstrip()) >= _ANCHO_ECO else 0)
                self._bloque_actividad = ""
                return
            if self._cola_eco and not _RE_NO_ES_COLA.match(linea):
                self._cola_eco = (self._cola_eco - 1
                                  if len(linea.rstrip()) >= _ANCHO_ECO else 0)
                return
            self._cola_eco = 0
        # 4) fallback: la prosa del CLI (respuesta final incluida), por regex
        quien, self._en_traza = reclasificar("cognia", linea, self._en_traza)
        quien = self._seguir_bloque_actividad(quien, linea)
        self.anotar(quien, linea)

    def _casar_eco(self, t: str) -> bool:
        """¿Es `t` (linea fisica sin espacios a los lados) un eco pendiente
        entero, o un TROZO de uno que rich envolvio? Consume lo casado.

        Antes solo casaba la linea entera (`t in _ecos_pendientes`): el
        renderer pinta el Aviso como "  {texto}" y con el pipe a 80 columnas
        el aviso a priori de confianza salia en dos lineas fisicas que no
        casaban con nada y entraban al chat como burbujas cognia (e2e
        2026-08-25). Aqui la primera linea fisica casa por PREFIJO cortado
        como corta rich (_corte_de_envoltorio) y el resto queda en
        _eco_resto, contra el que se casan las siguientes — exacto, sin
        adivinar por longitud. Si una linea no sigue el resto, el resto se
        suelta: lo que venga es otra cosa y se clasifica normal."""
        if self._eco_resto:
            resto = self._eco_resto
            if _corte_de_envoltorio(resto, t):
                self._eco_resto = resto[len(t):].lstrip()
                return True
            self._eco_resto = ""
        if not t:
            return False
        for eco in self._ecos_pendientes:
            if eco == t:
                self._ecos_pendientes.remove(eco)
                return True
            if _corte_de_envoltorio(eco, t):
                self._ecos_pendientes.remove(eco)
                self._eco_resto = eco[len(t):].lstrip()
                return True
        return False

    def _seguir_bloque_actividad(self, quien: str, linea: str) -> str:
        """Estado de los bloques envueltos (ver _RE_ABRE_DIFF): devuelve el
        quien definitivo de esta linea y deja el bloque abierto o cerrado."""
        t = linea.rstrip()
        if quien == "actividad":
            if _RE_ABRE_DIFF.match(t):
                self._bloque_actividad = "diff"
            elif t.lstrip()[:1] == "∴":
                self._bloque_actividad = "sangria"
            else:
                self._bloque_actividad = ""
            return quien
        if quien != "cognia" or not t.strip():
            self._bloque_actividad = ""       # log, sistema, traza: cortan
            return quien
        if self._bloque_actividad == "diff":
            return "actividad"
        if self._bloque_actividad == "sangria" and _RE_SANGRADA.match(t):
            return "actividad"
        self._bloque_actividad = ""
        return quien

    def _bombear(self) -> None:
        """Hilo lector: stdout del REPL -> transcripcion + suscriptores."""
        # El lector NO puede morir mientras el REPL viva: si deja de leer,
        # el REPL se bloquea en cuanto llena el pipe (unos 64 KB) y el movil
        # ve "pensando…" para siempre. Antes un `except Exception: pass`
        # envolvia el bucle entero: un reventon del clasificador en UNA linea
        # mataba el hilo en silencio (hallazgo 2026-08-25, regla del repo:
        # prohibido el except mudo). Ahora el fallo es POR LINEA: se deja
        # constancia (stderr con traceback; las 3 primeras tambien al chat
        # como "sistema"), la linea va cruda al Registro y se sigue leyendo.
        fallos = 0
        try:
            for linea in self.proc.stdout:      # type: ignore[union-attr]
                linea = _limpiar(linea.rstrip("\n"))
                if not linea.strip():
                    continue
                if any(linea.startswith(r) for r in _RUIDO):
                    continue
                try:
                    self._procesar_linea(linea)
                except Exception as e:
                    fallos += 1
                    import traceback
                    print(f"[remoto] {self.proyecto_id}/{self.id}: el "
                          f"clasificador fallo en la linea {linea[:120]!r}",
                          file=sys.stderr, flush=True)
                    traceback.print_exc()
                    try:
                        if fallos <= 3:
                            self.anotar("sistema",
                                        f"el clasificador del remoto fallo "
                                        f"({type(e).__name__}: {e}); la linea "
                                        f"va cruda al Registro")
                        self.anotar("log", linea)
                    except Exception as e2:
                        # ni anotar funciona (disco lleno, jsonl bloqueado):
                        # se sigue LEYENDO igual, que es lo que mantiene vivo
                        # al REPL; el motivo queda en stderr del servidor
                        print(f"[remoto] {self.proyecto_id}/{self.id}: "
                              f"tampoco pude anotar el fallo: "
                              f"{type(e2).__name__}: {e2}",
                              file=sys.stderr, flush=True)
        except Exception as e:
            # el propio pipe fallo (cerrado bajo los pies, decode roto):
            # ya no hay nada que leer, pero no en silencio
            print(f"[remoto] {self.proyecto_id}/{self.id}: lector del REPL "
                  f"interrumpido: {type(e).__name__}: {e}",
                  file=sys.stderr, flush=True)
        finally:
            self._agrupador().vaciar()
            # exit code REAL del REPL: distingue "/salir" (0) de un reventon
            rc = None
            try:
                if self.proc is not None:
                    rc = self.proc.wait(timeout=5)
            except Exception:
                pass
            # el hijo termino: su .pid ya no describe a nadie (y un PID
            # reciclado por Windows no debe matarse en la reconciliacion)
            try:
                self.fichero_pid.unlink(missing_ok=True)
            except OSError as e:
                print(f"[remoto] no pude borrar {self.fichero_pid}: {e}",
                      file=sys.stderr, flush=True)
            if rc not in (0, None) and self._arrancando and self._buffer_arranque:
                # murio ANTES de terminar el arranque: el traceback esta en el
                # buffer descartado. Antes se perdia entero y el movil veia
                # puro silencio (sesiones.py 307-313 historico).
                cola = self._buffer_arranque[-30:]
                self.anotar("sistema",
                            f"el REPL murio al arrancar (exit {rc}) — "
                            f"ultima linea: {cola[-1][:200]}")
                for l in cola:
                    self.anotar("log", l)
            if rc not in (0, None):
                self.anotar("sistema", f"sesion terminada (exit {rc})")
            else:
                self.anotar("sistema", "sesion terminada")

    def enviar(self, texto: str) -> None:
        """Una linea al stdin del REPL: mensaje, /comando o respuesta a un
        formulario (input() pendiente) — igual que teclear en la terminal."""
        if not self.viva():
            self.arrancar()
            # darle un momento al arranque antes del primer mensaje
            time.sleep(1.0)
        # la transcripcion guarda el texto TAL CUAL lo escribio (con sus
        # saltos); lo que va al REPL es UNA entrada (ver lineas_continuacion)
        self.anotar("usuario", texto)
        # una barra final la cierra cerrar_barra_final (antes solo se
        # avisaba y el siguiente mensaje se pegaba a este)
        entradas = entradas_para_repl(texto)
        try:
            for linea in entradas:
                self.proc.stdin.write(linea + "\n")   # type: ignore[union-attr]
            self.proc.stdin.flush()               # type: ignore[union-attr]
        except Exception as e:
            self.anotar("sistema", f"no pude enviar: {e}")

    def parar(self) -> None:
        if self.viva():
            try:
                self.enviar("/salir")
                self.proc.wait(timeout=8)         # type: ignore[union-attr]
            except Exception:
                try:
                    self.proc.kill()              # type: ignore[union-attr]
                except Exception:
                    pass
        # esperar al hilo lector: garantiza que "sesion terminada" ya esta
        # en el jsonl antes de que el llamador mueva o borre el fichero
        if self._bomba is not None and self._bomba.is_alive():
            self._bomba.join(timeout=3)


class GestorSesiones:
    """Registro en memoria de sesiones vivas + indice en disco."""

    def __init__(self):
        self._sesiones: dict[str, Sesion] = {}
        self._lock = threading.Lock()

    def indice(self, proyecto_id: str) -> list[dict]:
        d = RAIZ_DATOS / proyecto_id
        salida = []
        if d.is_dir():
            for f in sorted(d.glob("*.jsonl"),
                            key=lambda p: p.stat().st_mtime, reverse=True):
                sid = f.stem
                s = self._sesiones.get(sid)
                titulo = sid
                try:
                    primera = json.loads(
                        f.read_text(encoding="utf-8").splitlines()[0])
                    titulo = primera.get("titulo") or sid
                except Exception:
                    pass
                salida.append({
                    "id": sid, "titulo": titulo,
                    "viva": bool(s and s.viva()),
                    "modificada": time.strftime(
                        "%Y-%m-%d %H:%M",
                        time.localtime(f.stat().st_mtime)),
                })
        return salida

    def _sid_libre(self, proyecto_id: str, base: str) -> str:
        """`base`, o `base-2`, `base-3`... si ya existe (en memoria o como
        jsonl en disco). Dos POST en el mismo segundo compartian sid y la
        segunda sesion ESCRIBIA en la transcripcion de la primera."""
        d = RAIZ_DATOS / proyecto_id
        sid, n = base, 1
        while sid in self._sesiones or (d / f"{sid}.jsonl").exists():
            n += 1
            sid = f"{base}-{n}"
        return sid

    def crear(self, proyecto: dict, titulo: str = "",
              acceso: str = "total") -> Sesion:
        with self._lock:
            sid = self._sid_libre(proyecto["id"],
                                  time.strftime("%Y%m%d-%H%M%S"))
            # reservar el nombre antes de soltar el lock (la Sesion se
            # sustituye abajo por la definitiva)
            self._sesiones[sid] = None   # type: ignore[assignment]
        # solo dos niveles hoy; cualquier valor raro cae al historico ("total")
        # — el movil existente no manda el campo y no debe cambiar de conducta
        if acceso not in ("total", "restringido"):
            acceso = "total"
        s = Sesion(id=sid, proyecto_id=proyecto["id"],
                   ruta_proyecto=proyecto["ruta"],
                   titulo=titulo or f"Sesion {sid}", acceso=acceso)
        with self._lock:
            self._sesiones[sid] = s
        # primera linea del jsonl lleva titulo y acceso (los lee el indice y
        # obtener(): una sesion restringida no puede REABRIRSE con acceso total)
        with s.fichero.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.strftime("%H:%M:%S"),
                                "quien": "meta", "texto": "",
                                "titulo": s.titulo, "acceso": s.acceso},
                               ensure_ascii=False) + "\n")
        s.arrancar()
        return s

    def obtener(self, proyecto: dict, sid: str) -> Sesion:
        with self._lock:
            s = self._sesiones.get(sid)
            if s is None:
                s = Sesion(id=sid, proyecto_id=proyecto["id"],
                           ruta_proyecto=proyecto["ruta"], titulo=sid,
                           acceso=self._acceso_guardado(proyecto["id"], sid))
                self._sesiones[sid] = s
        return s

    @staticmethod
    def _acceso_guardado(proyecto_id: str, sid: str) -> str:
        """El nivel de permiso con que NACIO la sesion (meta del jsonl).
        Sesiones anteriores al campo: "total" (su comportamiento historico)."""
        f = RAIZ_DATOS / proyecto_id / f"{sid}.jsonl"
        try:
            with f.open("r", encoding="utf-8") as fh:
                meta = json.loads(fh.readline())
            acceso = meta.get("acceso", "total")
            return acceso if acceso in ("total", "restringido") else "total"
        except Exception:
            return "total"

    def despertar_suscriptores(self, evento: dict) -> int:
        """Encola `evento` en TODAS las colas de WS de todas las sesiones,
        sin tocar ningun jsonl. Lo usa el apagado del servidor: un WS
        esperando eventos no se entera de que el servidor se va hasta que le
        llega algo, y un movil conectado retenia la salida 29 s (medido
        2026-08-25: uvicorn cancela a los 5 s, pero el hilo del pool seguia
        en q.get hasta su timeout de 30). Devuelve cuantas colas desperto."""
        with self._lock:
            sesiones = list(self._sesiones.values())
        n = 0
        for s in sesiones:
            with s.lock:
                n += len(s.suscriptores)
            s._emitir_suscriptores(evento)
        return n

    def parar_sesion(self, sid: str) -> bool:
        """Parar el REPL SIN tocar su transcripcion. True si estaba vivo."""
        with self._lock:
            s = self._sesiones.get(sid)
        if s is not None and s.viva():
            s.parar()
            return True
        return False

    def parar_proyecto(self, proyecto_id: str) -> int:
        """Parar todos los REPLs vivos de un proyecto (baja sin huerfanos)."""
        with self._lock:
            propias = [s for s in self._sesiones.values()
                       if s is not None and s.proyecto_id == proyecto_id]
        n = 0
        for s in propias:
            if s.viva():
                s.parar()
                n += 1
        return n

    def borrar(self, proyecto_id: str, sid: str) -> bool:
        with self._lock:
            s = self._sesiones.pop(sid, None)
        if s:
            s.parar()
        f = RAIZ_DATOS / proyecto_id / f"{sid}.jsonl"
        try:
            f.unlink(missing_ok=True)
            return True
        except Exception:
            return False

    def vivas(self) -> list[dict]:
        """Los 'monitores': que REPLs corren ahora mismo y donde."""
        with self._lock:
            return [{"sesion": s.id, "proyecto": s.proyecto_id,
                     "ruta": s.ruta_proyecto, "pid": s.proc.pid}
                    for s in self._sesiones.values()
                    if s is not None and s.viva()]

    def interrumpir(self, sid: str) -> dict:
        with self._lock:
            s = self._sesiones.get(sid)
        if s is None:
            return {"ok": False, "motivo": "sesion desconocida o no arrancada"}
        return s.interrumpir()
