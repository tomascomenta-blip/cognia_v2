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
_PROMPT = re.compile(r"^(cognia[>➤]\s*)+")


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
_SIGUE_TRAZA = re.compile(
    r"^(\s|File |Message:|Arguments:|Traceback|Call stack)"
    r"|^[A-Za-z_][A-Za-z0-9_.]*(Error|Exception|Warning)\b")
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


def _es_actividad(linea: str) -> bool:
    return bool(_RE_ACTIVIDAD.match(linea))


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
                 "MensajeAlAgente", "AgenteProgreso"}


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
    # tipo desconocido (el contrato crecio): se anota crudo en actividad para
    # no perderlo en silencio — perderlo era el bug historico del remoto
    return "actividad", f"{tipo}: {json.dumps(d, ensure_ascii=False)[:300]}", []


# El renderer del CLI pinta los MISMOS eventos como lineas con marca
# (⏺ · ✗ ⚠ →) y un footer "3.2s · 500 tokens · 2 pasos". Cuando el stream de
# eventos esta activo, esas lineas son duplicados y se saltan.
_RE_FOOTER_RENDERER = re.compile(
    r"^\d+(\.\d+)?s( · \d+ (tokens|pasos?))*$")


def es_eco_renderer(linea: str) -> bool:
    t = linea.strip()
    if t[:1] in ("⏺", "·", "✗", "⚠", "→"):
        return True
    return bool(_RE_FOOTER_RENDERER.match(t))


def _python_cognia() -> list[str]:
    """El interprete que corre el REPL: el mismo venv del servidor."""
    return [sys.executable, "-m", "cognia"]


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
    # hilo lector: se guarda para poder join() en parar() — sin eso, su
    # anotar("sesion terminada") final corria DESPUES de mover/borrar el
    # jsonl y recreaba la carpeta de la sesion recien dada de baja
    _bomba: threading.Thread | None = None

    # ── persistencia ──
    @property
    def fichero(self) -> Path:
        d = RAIZ_DATOS / self.proyecto_id
        d.mkdir(exist_ok=True)
        return d / f"{self.id}.jsonl"

    def anotar(self, quien: str, texto: str) -> dict:
        evento = {"t": time.strftime("%H:%M:%S"), "quien": quien,
                  "texto": texto}
        with self.fichero.open("a", encoding="utf-8") as f:
            f.write(json.dumps(evento, ensure_ascii=False) + "\n")
        with self.lock:
            for q in list(self.suscriptores):
                try:
                    q.put_nowait(evento)
                except Exception:
                    pass
        return evento

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
        env = self._entorno()
        self.proc = subprocess.Popen(
            _python_cognia(), cwd=self.ruta_proyecto,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8",
            errors="replace", bufsize=1, env=env)
        self._bomba = threading.Thread(target=self._bombear, daemon=True,
                                       name=f"remoto-{self.id}")
        self._bomba.start()
        self.anotar("sistema", f"sesion arrancada en {self.ruta_proyecto}")

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
            quien, texto, ecos = interpretar_evento(d)
            for eco in ecos:
                self._ecos_pendientes.append(eco)
            if quien is not None and texto:
                self.anotar(quien, texto)
            if resto_prosa.strip():
                self._procesar_linea(resto_prosa)
            return
        # 2) banner/panel de arranque: se descarta de la transcripcion pero se
        # GUARDA — si el REPL muere aqui, el buffer es el traceback perdido.
        # Fin del arranque: la ultima linea del panel compacto ("/ayuda para
        # comandos"), el marcador del banner full legacy, o el tope. OJO: el
        # compacto ya NO imprime "Sistema listo" (obra 2026-08-09) — con solo
        # ese marcador, el gate se comia las primeras 200 lineas de CADA
        # sesion, respuesta del modelo incluida.
        if self._arrancando:
            self._lineas_arranque += 1
            self._buffer_arranque.append(linea)
            if ("Sistema listo" in linea or "/ayuda para comandos" in linea
                    or self._lineas_arranque > 200):
                self._arrancando = False
            return
        # 3) con eventos activos, los adornos del renderer (⏺/·/✗/⚠, footer)
        # y los ecos ya anotados via evento son duplicados: se saltan
        if self._con_eventos:
            if es_eco_renderer(linea):
                return
            t = linea.strip()
            if t and t in self._ecos_pendientes:
                self._ecos_pendientes.remove(t)
                return
        # 4) fallback: la prosa del CLI (respuesta final incluida), por regex
        quien, self._en_traza = reclasificar("cognia", linea, self._en_traza)
        self.anotar(quien, linea)

    def _bombear(self) -> None:
        """Hilo lector: stdout del REPL -> transcripcion + suscriptores."""
        try:
            for linea in self.proc.stdout:      # type: ignore[union-attr]
                linea = _limpiar(linea.rstrip("\n"))
                if not linea.strip():
                    continue
                if any(linea.startswith(r) for r in _RUIDO):
                    continue
                self._procesar_linea(linea)
        except Exception:
            pass
        finally:
            # exit code REAL del REPL: distingue "/salir" (0) de un reventon
            rc = None
            try:
                if self.proc is not None:
                    rc = self.proc.wait(timeout=5)
            except Exception:
                pass
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
        self.anotar("usuario", texto)
        try:
            self.proc.stdin.write(texto + "\n")   # type: ignore[union-attr]
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

    def crear(self, proyecto: dict, titulo: str = "",
              acceso: str = "total") -> Sesion:
        sid = time.strftime("%Y%m%d-%H%M%S")
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
                       if s.proyecto_id == proyecto_id]
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
                    for s in self._sesiones.values() if s.viva()]
