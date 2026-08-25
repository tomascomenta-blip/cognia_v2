"""
cognia/bots/registro.py
=======================
Perfil de un bot en disco + su identidad en el prompt + contexto(bot).

Que es un bot (Hermes Bot Mode, docs/user-guide/bot-mode): un PERFIL AISLADO
en disco -- config, identidad (SOUL.md, aqui ALMA.md), memoria, sesiones,
skills, cron -- bajo ~/.hermes/profiles/<bot>/. Aqui: dir_bots()/<nombre>/.
Todo se LEE del disco en cada llamada (sin cache de modulo): el REPL y el
daemon headless (cognia.bots.__main__) comparten estado por el filesystem,
igual que cognia.hermes.rutinas y cognia.experts.registry.

Identidad en el prompt (regla MEDIDA, no opinion):
  - Carril CEREBRO (chat): el ALMA reemplaza al prompt de usuario, exactamente
    como system_prompt.build_system_prompt hace con ~/.cognia/system_prompt.md
    (slot 1 del system, como el SOUL.md de Hermes). Si es el chat canonico se
    suma protocolo_mensajeria(): Hermes inyecta el protocolo desde el SISTEMA
    y no desde el SOUL, porque un SOUL custom lo borraba.
  - Carril AGENTE (tools): SOLO un sufijo corto y estructurado (<= 300 chars).
    A/B 2026-07-23 (system_prompt.py:329): prompt largo en el agente baja el
    gate de 10/10 a 1/4. El agente NUNCA ve el ALMA entero.

Aislamiento por entorno: entorno(bot) devuelve las variables que redirigen
los almacenes existentes (COGNIA_DB_PATH, COGNIA_RUTINAS_DIR, ...) al
directorio del bot; contexto(bot) las aplica sobre os.environ y RESTAURA
SOLO ESAS CLAVES al salir (delta, no snapshot entero: un `clear()` +
snapshot borraba LLAMA_SERVER_PATH y todo lo que apply_config() hubiera
puesto DURANTE el turno, y el segundo turno iba a simulacion).

LO QUE COGNIA_DB_PATH NO AISLA (honesto, medido 2026-08-25): cognia.config
lee COGNIA_DB_PATH en el IMPORT (config.py:20) y fija DB_PATH/_DB_DIR para
todo el proceso. En el daemon (python -m cognia.bots) cognia.config ya esta
importado antes del primer contexto(bot), y en el REPL desde el arranque.
Por eso la MEMORIA PRINCIPAL del bot la aisla ejecutor.instancia(bot)
pasando db_path=<bot>/memoria/cognia_memory.db a Cognia() (eso si funciona,
tambien en el REPL: _turno_bot usa esa instancia, no el `ai` del dueno).
Pero todo lo que lea cognia.config.DB_PATH en mitad del turno (agent/
agent_status.py, agent/background_research.py, varios sitios de cli.py)
escribe en la base GLOBAL del dueno, no en la del bot. contexto() aisla de
verdad lo que lee la env en cada llamada: rutinas, monitores, tareas,
permisos, el prompt de usuario y el cwd (workdir).

os.environ ES GLOBAL AL PROCESO (revision adversarial 2026-08-25, hallazgo
reproducido): dos turnos en hilos (remoto/bots_api corre cada POST en un
hilo; el carril de rutinas del REPL tickea cada 60 s) se pisaban las
variables y, al restaurar un snapshot entero, el ultimo en salir dejaba
COGNIA_BOT/COGNIA_ACCESO_TOTAL/COGNIA_PERMISSION_MODE del OTRO bot pegados
para siempre. Por eso:
  - CANDADO_TURNO serializa los turnos de bot de todo el proceso: mientras
    un bot esta en contexto, ningun otro entra (espera; y el carril de
    rutinas del REPL, que no puede esperar, consulta bot_en_turno() y se
    salta el tick).
  - La identidad del turno viaja ADEMAS por una ContextVar (_BOT_CTX) que
    bot_activo() consulta ANTES que COGNIA_BOT: aunque otro hilo pisara la
    env, la tool mensaje_bot firma como el bot de SU hilo. Los hilos hijos
    del turno la heredan si se arrancan con contextvars.copy_context()
    (hermes/rutinas.llamar_agente lo hace); un hijo sin herencia cae a la
    env, que bajo el candado es la correcta.
  - Un hilo HIJO del mismo turno (hermes/rutinas.llamar_agente corre el
    agente en un hilo aparte con timeout por inactividad) reconoce que el
    bot ya esta en contexto (_BOT_CTX heredada o _PILA) y NO vuelve a
    aplicar ni a bloquear: sin esto el tick se abrazaria a si mismo.
  - Las LECTURAS del almacen de rutinas (roster, /api/bots, estado) usan
    entorno_lectura(): un cambio de COGNIA_RUTINAS_DIR de milisegundos bajo
    _CANDADO_ENV, sin esperar a que termine un turno de minutos.
  - El cwd es igual de global que la env: si el bot tiene workdir,
    entorno_aplicado hace os.chdir(workdir) bajo el mismo candado y vuelve
    al cwd anterior al salir (las tools de fichero/shell del agente
    resuelven rutas relativas contra os.getcwd()).

MODELO PINNEADO (bot.modelo): el orquestador no acepta modelo por llamada y
/modelo recarga el llama-server entero, asi que un bot NO puede cambiar el
modelo servido en su turno. Lo que si se hace: guardar() rechaza con
ValueError un modelo que no este servido (backend_activo.estado()['modelo'])
ni sea de la flota (cognia.flota.CEREBROS), y contexto() avisa en cada turno
(Contexto.avisos + Contexto.modelo_servido) cuando el pinneado no coincide
con el servido: el turno corre con el global y SE DICE, no se finge.
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from pathlib import Path

from cognia.logger_config import get_logger

logger = get_logger(__name__)

# Nombre: minusculas/digitos, guion y guion bajo, 2..32 chars, empieza
# alfanumerico. Es a la vez nombre de directorio y handle de @mencion; por
# eso NO admite '.', '/', espacios ni mayusculas (borrar() confia en esto
# para no salirse jamas de dir_bots()).
RE_NOMBRE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,31}$")
NOMBRES_RESERVADOS = frozenset({"default"})

# Paleta determinista: 8 colores ANSI basicos (nombre -> codigo SGR). Se
# guarda el NOMBRE en bot.json para que el JSON sea legible y el CLI elija
# el escape (o nada bajo NO_COLOR).
COLORES_ANSI = {
    "rojo": "31", "verde": "32", "amarillo": "33", "azul": "34",
    "magenta": "35", "cian": "36", "blanco": "37", "gris": "90",
}
_COLORES = tuple(COLORES_ANSI)
# Glifos: set fijo, todos en el BMP y presentes en las fuentes de consola
# habituales (el banner de Cognia ya usa Braille; esto es mas conservador).
GLIFOS = ("◆", "●", "▲", "■", "★", "◈", "✦", "❖")

# Dentro del bot: el DIRECTORIO de la memoria. Se llama 'memoria' y no
# 'memoria.db' porque cognia/config.py:20 hace `Path(COGNIA_DB_PATH).mkdir()`
# y pone el sqlite en <dir>/cognia_memory.db: COGNIA_DB_PATH es un directorio
# para todo el repo, y un directorio llamado '.db' confundiria a cualquiera.
DIR_MEMORIA = "memoria"
FICHERO_CANON = ("sesiones", "canon.jsonl")

ALMA_POR_DEFECTO = """\
# {nombre}

Sos {nombre}{coma_titulo}. {descripcion}

Hablas en primera persona, con criterio propio y sin rodeos. Cuando te
escribe un companero (un mensaje que empieza por "Mensaje de 🤖 ..."), le
respondes a el, no al usuario.
"""


# ---------------------------------------------------------------------------
# Ubicacion
# ---------------------------------------------------------------------------

def _home() -> Path:
    """~/.cognia o COGNIA_HOME (misma convencion que arranque._home y
    monitores.nucleo._home: sin esto ningun test podria aislar el home)."""
    crudo = os.environ.get("COGNIA_HOME", "").strip()
    return Path(crudo).expanduser() if crudo else Path.home() / ".cognia"


def dir_bots() -> Path:
    """Raiz de los bots; COGNIA_BOTS_DIR la redirige entera (tests, daemon).
    Se lee en CADA llamada, como COGNIA_RUTINAS_DIR en hermes/rutinas."""
    crudo = os.environ.get("COGNIA_BOTS_DIR", "").strip()
    return Path(crudo).expanduser() if crudo else _home() / "bots"


def validar_nombre(nombre: str) -> str:
    """Devuelve el nombre normalizado o lanza ValueError ruidoso (que dice
    QUE regla fallo, para que el CLI lo repita tal cual)."""
    n = (nombre or "").strip().lstrip("@")
    if not RE_NOMBRE.match(n):
        raise ValueError(
            f"nombre de bot invalido: {nombre!r} (minusculas, digitos, '-' o "
            f"'_', 2 a 32 caracteres, empieza con letra o digito)")
    if n in NOMBRES_RESERVADOS:
        raise ValueError(f"nombre de bot reservado: {n!r}")
    return n


# ---------------------------------------------------------------------------
# El perfil
# ---------------------------------------------------------------------------

@dataclass
class Bot:
    """Un bot: perfil serializable a bot.json. Los campos vacios HEREDAN
    (modelo="" = el modelo global; skills=[] = todas; tools=[] = ROLE_TOOLS
    del implementador; modo_permiso="" = el modo global)."""
    nombre:       str
    titulo:       str = ""          # job title (Grok Bot): "Analista de datos"
    descripcion:  str = ""          # una linea; va al roster de los demas
    modelo:       str = ""          # modelo pinneado (vacio = hereda)
    skills:       list = field(default_factory=list)
    tools:        list = field(default_factory=list)
    modo_permiso: str = ""          # automatico|manual|bypass ("" = global)
    acceso_total: bool = False
    workdir:      str = ""
    oculto:       bool = False      # fuera del roster y de /bots (no borrado)
    creado:       str = ""          # ISO segundos
    color:        str = ""          # una clave de COLORES_ANSI (determinista)
    glifo:        str = ""          # uno de GLIFOS (determinista)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Bot":
        # Solo los campos conocidos: un bot.json escrito por una version mas
        # nueva (con campos extra) sigue cargando en esta.
        campos = {f for f in cls.__dataclass_fields__}
        limpio = {k: v for k, v in (d or {}).items() if k in campos}
        b = cls(**limpio)
        b.skills = list(b.skills or [])
        b.tools = list(b.tools or [])
        return b


def color_de(nombre: str) -> str:
    """Color determinista por sha1 del nombre: el mismo bot se ve igual en el
    REPL, el daemon y el remoto sin guardar nada extra."""
    h = hashlib.sha1(nombre.encode("utf-8")).digest()
    return _COLORES[h[0] % len(_COLORES)]


def glifo_de(nombre: str) -> str:
    """Glifo determinista; usa OTRO byte del hash para que color y glifo no
    vayan siempre emparejados (8x8 combinaciones, no 8)."""
    h = hashlib.sha1(nombre.encode("utf-8")).digest()
    return GLIFOS[h[1] % len(GLIFOS)]


def ruta(bot, *partes: str) -> Path:
    """Ruta dentro del directorio del bot. `bot` puede ser Bot o nombre."""
    nombre = bot.nombre if isinstance(bot, Bot) else validar_nombre(str(bot))
    return dir_bots().joinpath(nombre, *partes)


def _fichero_perfil(nombre: str) -> Path:
    return dir_bots() / nombre / "bot.json"


def _escribir_atomico(path: Path, texto: str) -> None:
    """tmp + fsync + os.replace (mismo patron que hermes/rutinas): un corte a
    mitad deja el fichero ANTERIOR, nunca un JSON truncado. Aqui SI lanza:
    guardar un perfil que no se pudo guardar es un fallo que el llamador
    tiene que ver, no un False que se pierde."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".bot_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(texto)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError as e:
            logger.warning("bots: no pude limpiar el temporal %s: %s", tmp, e)
        raise


def guardar(bot: Bot) -> Path:
    """Escribe bot.json (atomico). Rellena color/glifo/creado si faltan.
    Un modelo pinneado NUEVO o CAMBIADO pasa por validar_modelo() (ValueError
    ruidoso si no esta servido ni es de la flota); uno que ya estaba en disco
    no se revalida, para que ocultar/renombrar un bot no falle porque hoy el
    backend sirve otro modelo (el aviso por turno lo da contexto())."""
    bot.nombre = validar_nombre(bot.nombre)
    if not bot.color:
        bot.color = color_de(bot.nombre)
    if not bot.glifo:
        bot.glifo = glifo_de(bot.nombre)
    if not bot.creado:
        bot.creado = time.strftime("%Y-%m-%dT%H:%M:%S")
    if bot.modo_permiso and bot.modo_permiso not in ("automatico", "manual", "bypass"):
        raise ValueError(
            f"modo_permiso invalido: {bot.modo_permiso!r} (automatico|manual|bypass)")
    bot.modelo = (bot.modelo or "").strip()
    if bot.modelo:
        previo = obtener(bot.nombre)
        if previo is None or previo.modelo != bot.modelo:
            validar_modelo(bot.modelo)
    destino = _fichero_perfil(bot.nombre)
    _escribir_atomico(destino, json.dumps(bot.to_dict(), ensure_ascii=False,
                                          indent=2) + "\n")
    return destino


def obtener(nombre: str) -> Bot | None:
    """El bot por nombre exacto, o None si no existe. Un bot.json corrupto
    devuelve None Y deja un warning (no es lo mismo 'no existe' que 'no se
    pudo leer', pero la firma del contrato es Bot|None: el log lo distingue)."""
    try:
        n = validar_nombre(nombre)
    except ValueError:
        return None
    f = _fichero_perfil(n)
    if not f.is_file():
        return None
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
        b = Bot.from_dict(d)
        b.nombre = n            # el directorio manda, no el campo del JSON
        return b
    except (OSError, ValueError, TypeError) as e:
        logger.warning("bots: bot.json ilegible en %s: %s", f, e)
        return None


def listar(incluir_ocultos: bool = True) -> list[Bot]:
    """Todos los bots (orden por nombre). Directorios sin bot.json valido se
    saltan con warning."""
    raiz = dir_bots()
    if not raiz.is_dir():
        return []
    salida = []
    for d in sorted(raiz.iterdir()):
        if not d.is_dir() or not RE_NOMBRE.match(d.name):
            continue
        b = obtener(d.name)
        if b is None:
            if (d / "bot.json").exists():
                logger.warning("bots: %s tiene bot.json pero no carga", d)
            continue
        if b.oculto and not incluir_ocultos:
            continue
        salida.append(b)
    return salida


def _slug(texto: str) -> str:
    """'Analista de Datos' -> 'analista-de-datos' (para resolver por titulo)."""
    import unicodedata
    t = unicodedata.normalize("NFKD", texto or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return t


def resolver(texto: str) -> Bot | None:
    """Bot por nombre, por slug del titulo o por titulo literal; case-
    insensitive; admite '@nombre'. Es lo que usa la @mencion del chat y
    mensajeria.enviar para validar el destino contra el roster."""
    t = (texto or "").strip().lstrip("@").strip()
    if not t:
        return None
    directo = obtener(t.lower())
    if directo is not None:
        return directo
    objetivo = _slug(t)
    if not objetivo:
        return None
    for b in listar():
        if _slug(b.titulo) == objetivo or b.titulo.strip().lower() == t.lower():
            return b
    return None


def crear(nombre: str, titulo: str = "", descripcion: str = "", modelo: str = "",
          clonar: str | None = None, alma: str | None = None) -> Bot:
    """Crea el perfil en disco. ValueError ruidoso si el nombre es invalido,
    reservado o ya existe. `clonar` copia bot.json (menos nombre/creado/
    color/glifo), ALMA.md, skills/ y permisos.json del origen -- NUNCA la
    memoria ni las sesiones (Hermes: un bot clonado nace sin historia)."""
    n = validar_nombre(nombre)
    if _fichero_perfil(n).exists():
        raise ValueError(f"el bot {n!r} ya existe en {dir_bots()}")

    origen = None
    if clonar:
        origen = obtener(clonar)
        if origen is None:
            raise ValueError(f"no existe el bot a clonar: {clonar!r}")

    if origen is not None:
        d = origen.to_dict()
        for k in ("nombre", "creado", "color", "glifo"):
            d.pop(k, None)
        bot = Bot(nombre=n, **d)
        if titulo:
            bot.titulo = titulo
        if descripcion:
            bot.descripcion = descripcion
        if modelo:
            bot.modelo = modelo
    else:
        bot = Bot(nombre=n, titulo=titulo.strip(), descripcion=descripcion.strip(),
                  modelo=modelo.strip())

    base = dir_bots() / n
    for sub in ("skills", "rutinas", "sesiones", DIR_MEMORIA):
        (base / sub).mkdir(parents=True, exist_ok=True)
    guardar(bot)

    if origen is not None:
        raiz_o = dir_bots() / origen.nombre
        if (raiz_o / "skills").is_dir():
            shutil.copytree(raiz_o / "skills", base / "skills", dirs_exist_ok=True)
        if (raiz_o / "permisos.json").is_file():
            shutil.copy2(raiz_o / "permisos.json", base / "permisos.json")

    if alma is not None:
        texto_alma = alma
    elif origen is not None and (dir_bots() / origen.nombre / "ALMA.md").is_file():
        texto_alma = alma_de(origen)
    else:
        texto_alma = ALMA_POR_DEFECTO.format(
            nombre=n, coma_titulo=(f", {bot.titulo}" if bot.titulo else ""),
            descripcion=bot.descripcion or "Ayudas en lo que te pidan.")
    escribir_alma(bot, texto_alma)
    return bot


def borrar(nombre: str) -> None:
    """Borra el directorio entero del bot. ValueError si no existe. NUNCA
    borra fuera de dir_bots(): el nombre pasa por RE_NOMBRE (sin '.', '/',
    '\\') y ademas se comprueba que la ruta resuelta cuelgue de la raiz."""
    n = validar_nombre(nombre)        # '..', 'a/b', 'C:\\x' mueren aqui
    raiz = dir_bots().resolve()
    destino = (dir_bots() / n).resolve()
    if destino.parent != raiz:
        raise ValueError(f"me niego a borrar fuera de {raiz}: {destino}")
    if not _fichero_perfil(n).exists():
        raise ValueError(f"no existe el bot {n!r}")
    shutil.rmtree(destino)


# ---------------------------------------------------------------------------
# ALMA (identidad)
# ---------------------------------------------------------------------------

# Escaneo de inyeccion del ALMA. Se REUSAN las listas de patrones del sentinel
# (evaluar_contenido_web) en vez de llamar a la funcion: esa funcion BLOQUEA,
# audita en ~/.cognia/sentinel_audit.jsonl y emite al bus, y esta pensada para
# texto de la web, no para un fichero que escribio el dueno. Aqui el resultado
# es un AVISO: el dueno tiene derecho a escribir su ALMA como quiera (Hermes
# tambien escanea el SOUL y avisa), pero tiene que ver que su texto se parece a
# una inyeccion, porque ese ALMA va al slot 1 del system prompt de un bot que
# ademas recibe mensajes de OTROS bots.
_PATRONES_PROPIOS = [
    re.compile(r"ignor\w*\s+(?:todas?\s+)?(?:tus|las)\s+instrucciones", re.I),
    re.compile(r"\beres\s+ahora\b|\bsos\s+ahora\b|\byou\s+are\s+now\b", re.I),
    re.compile(r"system\s*prompt|prompt\s+del?\s+sistema", re.I),
]


def escanear_alma(texto: str) -> list[str]:
    """Avisos (lista de str, vacia = limpio) de patrones de inyeccion en el
    texto de un ALMA. Puro: no escribe, no audita, no lanza."""
    avisos: list[str] = []
    crudo = texto or ""
    try:
        from cognia.agent import sentinel as S
        subs = list(getattr(S, "_WEB_INJ_SUB", []))
        regs = list(getattr(S, "_WEB_INJ_RE", []))
        invis = getattr(S, "_WEB_INVISIBLES", None)
    except Exception as e:                       # sentinel roto: se ve y se sigue
        logger.warning("bots: sentinel no disponible para escanear el ALMA: %s", e)
        subs, regs, invis = [], [], None
    if invis is not None:
        n_invis = len(invis.findall(crudo))
        if n_invis > 5:
            avisos.append(f"exceso de caracteres invisibles/bidi ({n_invis})")
        limpio = invis.sub("", crudo)
    else:
        limpio = crudo
    norm = re.sub(r"[ \t]+", " ", limpio.lower())
    for s in subs:
        if s in norm:
            avisos.append(f"patron de inyeccion: {s!r}")
    for rx in list(regs) + _PATRONES_PROPIOS:
        m = rx.search(limpio)
        if m:
            avisos.append(f"patron de inyeccion: {m.group(0)[:60]!r}")
    # sin duplicados, orden estable
    vistos, salida = set(), []
    for a in avisos:
        if a not in vistos:
            vistos.add(a)
            salida.append(a)
    return salida


def alma_de(bot) -> str:
    """El texto del ALMA.md ("" si no hay). Errores de disco -> "" + warning."""
    f = ruta(bot, "ALMA.md")
    try:
        return f.read_text(encoding="utf-8").strip() if f.is_file() else ""
    except OSError as e:
        logger.warning("bots: no pude leer %s: %s", f, e)
        return ""


def escribir_alma(bot, texto: str) -> list[str]:
    """Escribe ALMA.md (atomico) y devuelve los AVISOS del escaneo de
    inyeccion. No bloquea: el CLI los imprime y el dueno decide."""
    avisos = escanear_alma(texto)
    for a in avisos:
        logger.warning("bots: ALMA de %s: %s",
                       bot.nombre if isinstance(bot, Bot) else bot, a)
    _escribir_atomico(ruta(bot, "ALMA.md"), (texto or "").rstrip() + "\n")
    return avisos


# ---------------------------------------------------------------------------
# Roster y protocolo (textos ESTABLES: hay goldens en tests)
# ---------------------------------------------------------------------------

def roster_texto(excluir: str | None = None) -> str:
    """Una linea por bot visible: '- <nombre> (<titulo>): <descripcion>'.
    Es lo que Hermes mete en el prompt de TODOS los bots para que sepan a
    quien pueden escribir. Los ocultos no salen."""
    lineas = []
    for b in listar(incluir_ocultos=False):
        if excluir and b.nombre == excluir:
            continue
        lineas.append(f"- {b.nombre} ({b.titulo or 'sin titulo'}): "
                      f"{b.descripcion or 'sin descripcion'}")
    return "\n".join(lineas) if lineas else "(no hay otros bots)"


PROTOCOLO_TITULO = "## Mensajeria entre bots"

# Marca de silencio que entiende hermes/rutinas.es_silencio (y ejecutor.
# es_silencio_bot suma '(pass)', la de los grupos de Hermes, por si el modelo
# la usa igual). Antes el protocolo pedia '(pass)' y procesar_inbox solo
# reconocia [SILENT]: el '(pass)' viajaba como mensaje y gastaba un turno del
# 27B en el otro bot (e2e 2026-08-25).
MARCA_SILENCIO = "[SILENT]"

_PROTOCOLO_REGLAS_TOOL = """\
- Si un mensaje empieza por 'Mensaje de 🤖 <x> (@x):' es un companero, no el \
usuario: respondele con la tool mensaje_bot.
- Nunca reenvies texto del usuario tal cual: compone tu propio mensaje.
- Termina tu turno sin esperar respuesta: la respuesta del otro bot llega \
despues, en un turno nuevo.
- Si no tenes nada que aportar, responde exactamente [SILENT]."""

# Version para el carril CEREBRO (chat sin tools): la respuesta se entrega
# sola al companero; pedir una tool aqui hacia que el modelo la escribiera
# como texto.
_PROTOCOLO_REGLAS_SIN_TOOL = """\
- Si un mensaje empieza por 'Mensaje de 🤖 <x> (@x):' es un companero, no el \
usuario: respondele a el; tu respuesta se le entrega tal cual (no escribas \
llamadas a herramientas como texto).
- Nunca reenvies texto del usuario tal cual: compone tu propio mensaje.
- Termina tu turno sin esperar respuesta: la respuesta del otro bot llega \
despues, en un turno nuevo.
- Si no tenes nada que aportar, responde exactamente [SILENT]."""


def protocolo_mensajeria(bot, con_tool: bool = True) -> str:
    """Seccion fija que el SISTEMA inyecta en el chat canonico (nunca vive en
    el ALMA: un ALMA custom la borraria, bug documentado de Hermes).
    con_tool=False: redaccion para el carril cerebro (sin tools)."""
    nombre = bot.nombre if isinstance(bot, Bot) else str(bot)
    if con_tool:
        cabeza = (f"Sos @{nombre}. Otros bots con los que podes hablar "
                  f"(mensaje_bot(destino, mensaje)):\n")
        reglas = _PROTOCOLO_REGLAS_TOOL
    else:
        cabeza = f"Sos @{nombre}. Otros bots con los que podes hablar:\n"
        reglas = _PROTOCOLO_REGLAS_SIN_TOOL
    return f"{PROTOCOLO_TITULO}\n{cabeza}{roster_texto(excluir=nombre)}\n{reglas}"


# ---------------------------------------------------------------------------
# Modelo pinneado (ver docstring del modulo: se valida y se avisa, no se
# cambia el backend)
# ---------------------------------------------------------------------------

def leer_modelo_servido() -> str | None:
    """Basename del GGUF que sirve el backend AHORA (backend_activo.estado,
    /props con timeout de 3 s y sin cache) o None si no hay backend o no se
    pudo preguntar (queda en el log: 'no hay backend' y 'no pude preguntar'
    no son lo mismo, pero para decidir un aviso equivalen)."""
    try:
        from cognia import backend_activo
        return backend_activo.estado().get("modelo") or None
    except Exception as e:                       # red/import: se ve y se sigue
        logger.warning("bots: no pude leer el modelo servido: %s", e)
        return None


def modelos_de_flota() -> list[str]:
    """Los nombres (fragmentos) de cerebro que la flota sabe arrancar
    (cognia.flota.CEREBROS), ordenados. [] si el modulo no carga."""
    try:
        from cognia.flota import CEREBROS
        return sorted(CEREBROS)
    except Exception as e:
        logger.warning("bots: cognia.flota no disponible: %s", e)
        return []


def modelo_coincide(pinneado: str, servido: str | None) -> bool:
    """True si el modelo pinneado ES el servido: iguales sin distinguir
    mayusculas, o uno contenido en el otro ('qwythos' casa con
    'Qwythos-9B-Q4_K_M.gguf'; 'Qwythos-9B-Q4_K_M.gguf' casa con
    'qwythos'). Vacio nunca casa."""
    p = (pinneado or "").strip().lower()
    s = (servido or "").strip().lower()
    if not p or not s:
        return False
    return p == s or p in s or s in p


def modelo_valido(nombre: str) -> tuple[bool, str]:
    """(ok, detalle). ok si `nombre` coincide con el modelo servido o con un
    cerebro de la flota (cognia.flota.combo_de_modelo lo reconoce). El
    detalle dice contra que se comparo, para el mensaje del CLI."""
    n = (nombre or "").strip()
    servido = leer_modelo_servido()
    if modelo_coincide(n, servido):
        return True, f"servido ahora: {servido}"
    try:
        from cognia.flota import combo_de_modelo
        combo = combo_de_modelo(n)
    except Exception as e:
        logger.warning("bots: cognia.flota no disponible: %s", e)
        combo = None
    if combo:
        return True, f"cerebro de la flota (combo {combo})"
    flota = ", ".join(modelos_de_flota()) or "ninguno"
    return False, (f"no esta servido (servido: {servido or 'ninguno'}) ni es un "
                   f"cerebro de la flota ({flota})")


def validar_modelo(nombre: str) -> str:
    """Devuelve el nombre normalizado o lanza ValueError ruidoso con el
    detalle de modelo_valido(). Es lo que guardar() aplica a un modelo
    pinneado nuevo (y lo que /bots modelo deberia repetir tal cual)."""
    n = (nombre or "").strip()
    if not n:
        return ""
    ok, detalle = modelo_valido(n)
    if not ok:
        raise ValueError(f"modelo pinneado {n!r} {detalle}")
    return n


def aviso_modelo(bot: Bot, servido: str | None = None) -> str | None:
    """El aviso del turno si el modelo pinneado NO es el servido (None si
    coincide o el bot hereda). `servido` evita una segunda consulta."""
    if not bot.modelo:
        return None
    if servido is None:
        servido = leer_modelo_servido()
    if modelo_coincide(bot.modelo, servido):
        return None
    return (f"modelo pinneado {bot.modelo!r} no esta servido: el turno corre "
            f"con {servido or 'el modelo global (sin backend vivo)'}")


# ---------------------------------------------------------------------------
# Entorno y contexto
# ---------------------------------------------------------------------------

def entorno(bot: Bot) -> dict:
    """Variables de entorno que aislan los almacenes del bot. SOLO las que el
    bot define: si modo_permiso esta vacio no toca COGNIA_PERMISSION_MODE
    (queda lo que el usuario tenga), y COGNIA_ACCESO_TOTAL solo se fija si
    acceso_total. COGNIA_PROMPT_USUARIO=0 va siempre: el ALMA reemplaza al
    prompt de usuario, y un bot sin ALMA usa la identidad integrada, no la
    personal del dueno. COGNIA_DB_PATH se exporta para lo que lo lea en cada
    llamada, pero cognia.config lo leyo en el import: la memoria principal
    la aisla ejecutor.instancia(bot) con db_path (ver docstring del modulo).
    COGNIA_BOT_WORKDIR es informativo; el chdir real lo hace entorno_aplicado."""
    base = dir_bots() / bot.nombre
    env = {
        "COGNIA_BOT": bot.nombre,
        "COGNIA_BOTS_DIR": str(dir_bots()),
        "COGNIA_DB_PATH": str(base / DIR_MEMORIA),
        "COGNIA_RUTINAS_DIR": str(base / "rutinas"),
        "COGNIA_MONITORES_DIR": str(base / "monitores"),
        "COGNIA_TASKS_FILE": str(base / "tasks_board.json"),
        "COGNIA_PROMPT_USUARIO": "0",
    }
    if bot.modo_permiso:
        env["COGNIA_PERMISSION_MODE"] = bot.modo_permiso
    if bot.acceso_total:
        env["COGNIA_ACCESO_TOTAL"] = "1"
    if bot.workdir:
        env["COGNIA_BOT_WORKDIR"] = bot.workdir
    return env


def sufijo_agente(bot: Bot, tope: int = 300) -> str:
    """Identidad del bot para el carril AGENTE: corto y estructurado, al
    estilo user_prefs.personalization_suffix. <= `tope` chars SIEMPRE."""
    cabeza = f"Eres {bot.nombre}, {bot.titulo}." if bot.titulo else f"Eres {bot.nombre}."
    desc = " ".join((bot.descripcion or "").split())
    if desc:
        libre = tope - len(cabeza) - 1
        if libre > 8 and len(desc) > libre:
            desc = desc[:libre - 3].rstrip() + "..."
        elif libre <= 8:
            desc = ""
    texto = f"{cabeza} {desc}".strip() if desc else cabeza
    return texto[:tope]


@dataclass
class Contexto:
    """Lo que un turno del bot necesita, ya resuelto en su entorno.
    modelo: el pinneado del perfil ("" = hereda); modelo_servido: lo que el
    backend sirve AHORA (None sin backend); si no coinciden, avisos lo dice.
    workdir: el directorio de trabajo del bot ("" = el del proceso); si esta,
    entorno_aplicado ya hizo chdir a el."""
    bot:            Bot
    system_cerebro: str
    sufijo_agente:  str
    skills:         dict
    allowed_tools:  set | None
    modelo:         str
    avisos:         list = field(default_factory=list)
    modelo_servido: str | None = None
    workdir:        str = ""


def _cargar_skills(bot: Bot, avisos: list) -> dict:
    try:
        from cognia.agent.skills import load_skills
    except Exception as e:
        avisos.append(f"skills no disponibles: {e}")
        return {}
    todas = load_skills(extra_dirs=[str(ruta(bot, "skills"))])
    if not bot.skills:
        return todas
    elegidas = {k: v for k, v in todas.items() if k in set(bot.skills)}
    faltan = sorted(set(bot.skills) - set(elegidas))
    if faltan:
        avisos.append(f"skills declaradas y no encontradas: {', '.join(faltan)}")
    return elegidas


def _tools_permitidas(bot: Bot, avisos: list) -> set | None:
    if bot.tools:
        return set(bot.tools)
    try:
        from cognia.agent.tools import ROLE_TOOLS
        return set(ROLE_TOOLS["implementador"])
    except Exception as e:
        avisos.append(f"ROLE_TOOLS no disponible ({e}); sin restriccion de tools")
        return None


def _protocolo_encendido(explicito: bool | None) -> bool:
    if explicito is not None:
        return explicito
    return os.environ.get("COGNIA_BOTS_PROTOCOLO", "").strip().lower() not in ("0", "off", "no")


# Serializacion de turnos (ver docstring del modulo). RLock: el mismo hilo
# puede anidar contexto() (procesar_inbox -> correr_turno -> instancia ...).
CANDADO_TURNO = threading.RLock()
# Toda mutacion de os.environ de este paquete pasa por aqui (corta: solo el
# update/restauracion, nunca el turno entero).
_CANDADO_ENV = threading.Lock()
# Bots en contexto, del mas externo al mas interno. Un hilo hijo del turno
# (rutinas.llamar_agente) ve el mismo nombre arriba de la pila y no bloquea.
_PILA: list = []
ESPERA_AVISO_S = 2.0
# Identidad del turno POR HILO/CONTEXTO (ver docstring del modulo): la lee
# bot_activo() antes que COGNIA_BOT. Los hilos nuevos NO la heredan salvo
# que se arranquen con contextvars.copy_context().run(...).
_BOT_CTX: contextvars.ContextVar = contextvars.ContextVar("cognia_bot_en_contexto",
                                                          default=None)


def bot_en_turno() -> str | None:
    """Nombre del bot cuyo turno esta en curso en ESTE proceso (en cualquier
    hilo), o None. Es lo que consulta el carril de rutinas del REPL antes de
    tickear: con un bot en turno, COGNIA_RUTINAS_DIR es el del bot."""
    return _PILA[-1] if _PILA else None


def bot_de_este_hilo() -> str | None:
    """Nombre del bot en contexto en ESTE hilo (ContextVar), o None. Es la
    fuente primaria de bot_activo(); COGNIA_BOT es el respaldo."""
    return _BOT_CTX.get()


def _aplicar_workdir(bot: Bot) -> str | None:
    """os.chdir(bot.workdir) si esta y existe; devuelve el cwd anterior para
    restaurarlo, o None si no se toco. Un workdir que ya no existe se avisa
    (log) y el turno corre en el cwd del proceso: mejor que reventar el turno
    por una carpeta borrada."""
    if not bot.workdir:
        return None
    destino = Path(bot.workdir).expanduser()
    if not destino.is_dir():
        logger.warning("bots: workdir de %s no existe (%s); el turno corre en %s",
                       bot.nombre, bot.workdir, os.getcwd())
        return None
    antes = os.getcwd()
    os.chdir(str(destino))
    return antes


def _aplicar_env(env: dict) -> dict:
    """update() de os.environ bajo _CANDADO_ENV; devuelve el DELTA anterior
    ({clave: valor_previo|None}) para restaurar exactamente esas claves."""
    with _CANDADO_ENV:
        antes = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
    return antes


def _restaurar_env(antes: dict) -> None:
    with _CANDADO_ENV:
        for k, v in antes.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@contextmanager
def entorno_aplicado(bot: Bot, env: dict | None = None):
    """Aplica `env` (default entorno(bot)) sobre os.environ SERIALIZADO por
    CANDADO_TURNO y restaura el delta al salir (tambien con excepcion). Si el
    mismo bot ya esta en turno (hilo hijo, o anidado en el mismo hilo) no
    aplica nada ni bloquea: el entorno ya es el suyo. Si OTRO bot esta en
    turno en otro hilo, espera (y lo dice por log pasados ESPERA_AVISO_S)."""
    env = entorno(bot) if env is None else env
    if _BOT_CTX.get() == bot.nombre:
        yield                       # anidado en el mismo hilo/contexto
        return
    if _PILA and _PILA[-1] == bot.nombre:
        # Hilo hijo del turno sin la ContextVar heredada: la env ya es la
        # suya; solo se le da la identidad por hilo (y se le quita al salir).
        token = _BOT_CTX.set(bot.nombre)
        try:
            yield
        finally:
            _BOT_CTX.reset(token)
        return
    if not CANDADO_TURNO.acquire(timeout=ESPERA_AVISO_S):
        logger.warning("bots: %s espera a que termine el turno de %s",
                       bot.nombre, bot_en_turno() or "otro bot")
        CANDADO_TURNO.acquire()
    try:
        _PILA.append(bot.nombre)
        token = _BOT_CTX.set(bot.nombre)
        antes = _aplicar_env(env)
        cwd_antes = _aplicar_workdir(bot)
        try:
            yield
        finally:
            if cwd_antes is not None:
                try:
                    os.chdir(cwd_antes)
                except OSError as e:
                    logger.warning("bots: no pude volver al cwd %s: %s", cwd_antes, e)
            _restaurar_env(antes)
            _BOT_CTX.reset(token)
            _PILA.pop()
    finally:
        CANDADO_TURNO.release()


@contextmanager
def entorno_lectura(bot: Bot):
    """Solo COGNIA_RUTINAS_DIR del bot, para LEER su almacen de rutinas
    (listar/pendientes/ejecuciones) sin esperar a CANDADO_TURNO: el roster,
    /api/bots y `estado` no pueden quedarse minutos detras de un turno del
    27B. Si el bot ya esta en turno no toca nada. Ventana de riesgo asumida y
    documentada: si OTRO bot esta en turno en otro hilo, durante los
    milisegundos de la lectura ese turno veria este COGNIA_RUTINAS_DIR;
    solo afecta a quien lea rutinas justo entonces (el turno no tickea)."""
    if _PILA and _PILA[-1] == bot.nombre:
        yield
        return
    clave = "COGNIA_RUTINAS_DIR"
    antes = _aplicar_env({clave: entorno(bot)[clave]})
    try:
        yield
    finally:
        _restaurar_env(antes)


@contextmanager
def contexto(bot: Bot, canon: bool = True, protocolo: bool | None = None):
    """Aplica entorno(bot) sobre os.environ (serializado: entorno_aplicado),
    produce Contexto y RESTAURA las claves tocadas al salir (tambien si hay
    excepcion). `canon`: es el chat canonico -> se suma el protocolo de
    mensajeria (salvo COGNIA_BOTS_PROTOCOLO=0 o protocolo=False)."""
    with entorno_aplicado(bot):
        avisos: list = []
        alma = alma_de(bot)
        # El ALMA va en el SLOT 1 (identidad) del system del cerebro, y la
        # base de conducta + papel se conservan (Hermes reemplaza solo el
        # SOUL; `system = alma` a secas perdia 1458 -> 690 chars de conducta,
        # revision adversarial 2026-08-25). Sin ALMA, la identidad integrada
        # de Cognia + el sufijo corto del bot. En ambos casos el prompt de
        # usuario del dueno queda fuera (override y COGNIA_PROMPT_USUARIO=0).
        try:
            from cognia.system_prompt import build_system_prompt
            if alma:
                system = build_system_prompt(rol="cerebro", prompt_usuario_override=alma)
            else:
                system = build_system_prompt(rol="cerebro") + "\n\n" + sufijo_agente(bot)
        except Exception as e:
            avisos.append(f"system_prompt no disponible: {e}")
            system = alma or sufijo_agente(bot)
        if canon and _protocolo_encendido(protocolo):
            # El carril CEREBRO no tiene tools: su protocolo no puede pedir
            # una (el 27B escribia `mensaje_bot("alfa", ...)` como TEXTO y
            # procesar_inbox lo reenviaba tal cual; e2e 2026-08-25).
            system = system + "\n\n" + protocolo_mensajeria(bot, con_tool=False)
        servido = leer_modelo_servido() if bot.modelo else None
        aviso_m = aviso_modelo(bot, servido) if bot.modelo else None
        if aviso_m:
            # Fallo en voz alta: el turno corre con el modelo global y el
            # canon, el REPL y la API lo ven (ejecutor anota los avisos).
            avisos.append(aviso_m)
        ctx = Contexto(
            bot=bot, system_cerebro=system, sufijo_agente=sufijo_agente(bot),
            skills=_cargar_skills(bot, avisos),
            allowed_tools=_tools_permitidas(bot, avisos),
            modelo=bot.modelo or "", avisos=avisos,
            modelo_servido=servido,
            workdir=bot.workdir or "",
        )
        for a in avisos:
            logger.warning("bots: contexto(%s): %s", bot.nombre, a)
        yield ctx


# ---------------------------------------------------------------------------
# Actividad
# ---------------------------------------------------------------------------

def ultima_actividad(bot) -> float | None:
    """Epoch del ultimo apunte en el chat canonico (mtime de canon.jsonl) o
    None si el bot nunca hablo."""
    f = ruta(bot, *FICHERO_CANON)
    try:
        return f.stat().st_mtime if f.is_file() else None
    except OSError as e:
        logger.warning("bots: no pude leer el mtime de %s: %s", f, e)
        return None


def activo(bot, ventana_s: float = 90) -> bool:
    """'Active now' de Hermes: escribio en los ultimos `ventana_s` segundos."""
    t = ultima_actividad(bot)
    return t is not None and (time.time() - t) <= ventana_s


def bot_activo() -> Bot | None:
    """El bot en cuyo contexto corre ESTE HILO: primero la ContextVar que
    puso entorno_aplicado (inmune a que otro hilo pise la env), y si no hay,
    COGNIA_BOT (un subproceso/daemon arrancado con la variable ya puesta, o
    un hilo hijo sin herencia de contexto). None fuera de un bot. Es lo que
    decide si la tool mensaje_bot se registra y como firma."""
    n = _BOT_CTX.get() or os.environ.get("COGNIA_BOT", "").strip()
    return obtener(n) if n else None
