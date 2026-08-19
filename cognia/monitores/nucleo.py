"""
cognia/monitores/nucleo.py
==========================
El motor de monitores PERSISTENTE con acciones.

QUE RESUELVE: que Cognia pueda esperar a que algo pase en el mundo (un build
que termina, un fichero que aparece, una URL que se cae) sin quemar tokens
mientras espera, y REACCIONAR sola cuando pasa.

POR QUE EXISTE (el motor viejo, cognia/console/monitors.py, no sirve):
  1. Vive SOLO en memoria: cerrar el REPL borra todos los monitores. Esperar
     un build de 40 minutos y perderlo por reiniciar el REPL es el fallo
     principal, y no se arregla con parches.
  2. Dispara UNA vez y el hilo muere: no hay monitor recurrente.
  3. No tiene ACCIONES: solo encola un string para que el humano lo lea. Nadie
     puede lanzar un comando ni despertar al agente.
  4. La condicion es un callable de Python: el agente no puede crear un
     monitor (no puede escribir un closure en una linea ACCION:).

QUE SE COPIA DE FUERA (estado del arte investigado, no reinventado):
  * Claude Code (Monitor): NO hay lenguaje de condiciones. La condicion ES un
    PROCESO y "una linea en stdout = un evento". Por eso aca la condicion
    canonica es {"tipo":"comando", ...} y los atajos declarativos
    (fichero_existe, url, ...) son azucar sobre la misma idea. El que espera
    paga CERO tokens hasta que dispara: el tick es un subproceso, no una
    llamada al modelo. Y se distingue por CARDINALIDAD: modo 'una_vez'
    (notificacion que SALE al cumplirse) vs 'recurrente' (una por ocurrencia).
  * Hermes (ledger): TRES estados terminales — completed / failed / unknown —
    y 'unknown' SOLO cuando se PRUEBA que nadie puede saber el resultado (aca:
    el comando se paso de timeout y LO MATAMOS nosotros, o la tarea se encolo
    para el agente y todavia nadie la atendio). Heartbeat en fichero atomico
    aparte, timeout por INACTIVIDAD (no wall-clock) y el contrato [SILENT]
    para no notificar cuando no pasa nada.
  * Cognia (console/monitors.py): lo bueno es la cola drenada entre turnos
    (pop_fired_events) y los estados por monitor. Eso se conserva:
    ``pop_eventos()`` devuelve list[str] igual que ``pop_fired_events()``.

LO QUE ESTE MODULO NO HACE, A PROPOSITO: no llama al agente ni al LLM. La
accion 'despertar_agente' ENCOLA una tarea en ``tareas_pendientes()`` y el
cableado (el REPL) la drena. Un motor que invoca al agente desde un hilo
daemon es un motor que no se puede probar en seco ni acotar por presupuesto.

REGLA DURA HEREDADA DE UNA LECCION MEDIDA de este repo (skills auto-capturadas
que ENVENENARON tareas ajenas): nada que este motor decida solo se ejecuta sin
dejar rastro auditable. TODA accion escribe en el ledger append-only con su
estado terminal, tambien las que no notifican.

NO LANZA EN EL CAMINO CALIENTE: evaluar una sonda que revienta devuelve
``error`` en el informe y deja ``ultimo_error`` en el monitor; jamas una
excepcion que mate el hilo (ese era el modo de fallo del motor viejo: una
excepcion del check_fn mataba el monitor entero para siempre).

Solo stdlib. Toda dependencia externa (ejecutar un comando, pedir una URL,
mirar un shell del proc_registry, reproducir un flujo) se INYECTA como
callable para poder probar el modulo entero en seco.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path

# Los TRES estados terminales del ledger (Hermes). No hay un cuarto: si hace
# falta uno mas es que la accion no esta bien definida.
#   completed -> se probo que salio bien
#   failed    -> se probo que salio mal
#   unknown   -> NADIE puede probar como salio (lo matamos por timeout, o la
#                tarea sigue en la cola esperando a que el agente la atienda)
ESTADOS_TERMINALES = ("completed", "failed", "unknown")

# Contrato [SILENT] (Hermes): una accion cuya salida empieza o termina con
# alguna de estas marcas se REGISTRA en el ledger pero NO notifica. Es la unica
# forma de tener un monitor recurrente cada minuto sin convertir el REPL en
# spam: el comando decide si hay algo que contar.
MARCAS_SILENT = ("[SILENT]", "SILENT", "NO_REPLY")

# Timeout por defecto de una sonda o una accion de comando. Es un timeout de
# INACTIVIDAD del subproceso completo (subprocess.run lo mata al vencer): un
# monitor cuyo comando se cuelga no puede secuestrar el hilo del motor.
TIMEOUT_COMANDO_S = 30.0

# Cada cuanto se re-evalua por defecto. Un minuto es el compromiso medido:
# suficientemente vivo para un build y suficientemente barato para dejarlo
# corriendo semanas.
INTERVALO_S = 60.0

# Cuanto duerme el hilo vivo entre ticks. El tick decide QUE toca segun el
# intervalo de cada monitor; el hilo solo marca el pulso.
PASO_HILO_S = 1.0

_MODOS = ("una_vez", "recurrente")

_LOCK_GLOBAL = threading.RLock()


# ═══════════════════════════════════════════════════════════════════════════
# Rutas y persistencia atomica
# ═══════════════════════════════════════════════════════════════════════════

def _home() -> Path:
    """~/.cognia, o COGNIA_HOME si el entorno lo redirige (misma convencion que
    arranque.py, capacidad.py y flujos/examen.py). Se resuelve EN CADA LLAMADA,
    no en el import: los tests redirigen el home DESPUES de importar."""
    crudo = os.environ.get("COGNIA_HOME", "").strip()
    return Path(crudo) if crudo else Path.home() / ".cognia"


def dir_monitores() -> Path:
    """Raiz del almacen. COGNIA_MONITORES_DIR la redirige entera (tests)."""
    crudo = os.environ.get("COGNIA_MONITORES_DIR", "").strip()
    return Path(crudo) if crudo else _home() / "monitores"


def ruta_monitores() -> Path:
    return dir_monitores() / "monitores.json"


def ruta_ledger() -> Path:
    return dir_monitores() / "eventos.jsonl"


def ruta_latido() -> Path:
    """Heartbeat en fichero SEPARADO (Hermes). Aparte del estado a proposito:
    el latido se escribe en cada tick y el estado solo cuando cambia; mezclarlos
    obliga a reescribir el estado entero 60 veces por hora sin motivo."""
    return dir_monitores() / "latido.json"


def _leer_json(ruta: Path):
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _escribir_json(ruta: Path, datos) -> bool:
    """Escritura ATOMICA (tmp + os.replace). Un monitores.json a medio escribir
    por un corte deja al motor sin memoria: el fallo que este modulo existe
    para arreglar volveria por la puerta de atras."""
    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        tmp = ruta.with_suffix(ruta.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(str(tmp), str(ruta))
        return True
    except Exception:
        return False


def _append_jsonl(ruta: Path, fila: dict) -> bool:
    """Append-only. NO se reescribe nunca: el ledger es la constancia de lo que
    el motor hizo solo mientras nadie miraba, y reescribirlo lo invalida."""
    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        with open(ruta, "a", encoding="utf-8") as f:
            f.write(json.dumps(fila, ensure_ascii=False) + "\n")
        return True
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════════════
# Sondas por defecto (todas inyectables: ver MotorMonitores.__init__)
# ═══════════════════════════════════════════════════════════════════════════

def ejecutar_comando(cmd: str, timeout_s: float = TIMEOUT_COMANDO_S,
                     cwd: str = "") -> dict:
    """Corre un comando de shell y devuelve un dict; NUNCA lanza.

    {"codigo": int|None, "salida": str, "error": str, "timeout": bool}

    codigo None + timeout True = LO MATAMOS nosotros: ese es el unico caso en
    el que el resultado es genuinamente 'unknown' (Hermes). encoding utf-8 con
    errors='replace' a proposito: en Windows la consola escupe cp1252 y un
    UnicodeDecodeError aca mataria el tick por un acento en un log.
    """
    try:
        res = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=max(0.1, float(timeout_s or TIMEOUT_COMANDO_S)),
            cwd=(cwd or None),
        )
        return {"codigo": int(res.returncode),
                "salida": res.stdout or "",
                "error": res.stderr or "",
                "timeout": False}
    except subprocess.TimeoutExpired as exc:
        salida = exc.stdout or ""
        if isinstance(salida, bytes):
            salida = salida.decode("utf-8", "replace")
        return {"codigo": None, "salida": salida,
                "error": f"timeout tras {timeout_s}s", "timeout": True}
    except Exception as exc:
        return {"codigo": None, "salida": "",
                "error": f"{type(exc).__name__}: {exc}", "timeout": False}


def sonda_url(url: str, timeout_s: float = 5.0) -> dict:
    """{"arriba": bool, "detalle": str}. Nunca lanza: una URL caida NO es un
    error de la sonda, es exactamente lo que algunos monitores esperan."""
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as r:
            codigo = int(getattr(r, "status", 0) or 0)
        return {"arriba": 200 <= codigo < 400, "detalle": f"HTTP {codigo}"}
    except Exception as exc:
        return {"arriba": False, "detalle": f"{type(exc).__name__}: {exc}"}


def sonda_proceso_vivo(pid: int) -> dict:
    """{"vivo": bool, "detalle": str}. Nunca lanza.

    POR QUE NO os.kill(pid, 0): en Windows os.kill con una signal que no sea
    CTRL_C_EVENT/CTRL_BREAK_EVENT llama a TerminateProcess — el chequeo MATA el
    proceso que venia a mirar. Aca se usa OpenProcess con
    PROCESS_QUERY_LIMITED_INFORMATION (0x1000) y GetExitCodeProcess, que es
    read-only; en POSIX si vale el os.kill(pid, 0) de toda la vida.
    """
    try:
        pid = int(pid)
    except Exception:
        return {"vivo": False, "detalle": "pid no numerico"}
    if pid <= 0:
        return {"vivo": False, "detalle": "pid invalido"}
    if os.name == "nt":
        try:
            import ctypes
            k32 = ctypes.windll.kernel32                    # type: ignore[attr-defined]
            handle = k32.OpenProcess(0x1000, False, pid)
            if not handle:
                return {"vivo": False, "detalle": f"pid {pid} no existe"}
            try:
                codigo = ctypes.c_ulong(0)
                k32.GetExitCodeProcess(handle, ctypes.byref(codigo))
                vivo = codigo.value == 259                  # STILL_ACTIVE
            finally:
                k32.CloseHandle(handle)
            return {"vivo": vivo,
                    "detalle": f"pid {pid} {'vivo' if vivo else 'terminado'}"}
        except Exception as exc:
            return {"vivo": False, "detalle": f"{type(exc).__name__}: {exc}"}
    try:
        os.kill(pid, 0)
        return {"vivo": True, "detalle": f"pid {pid} vivo"}
    except ProcessLookupError:
        return {"vivo": False, "detalle": f"pid {pid} no existe"}
    except PermissionError:
        # Existe pero es de otro usuario: existir es lo que se pregunto.
        return {"vivo": True, "detalle": f"pid {pid} vivo (otro usuario)"}
    except Exception as exc:
        return {"vivo": False, "detalle": f"{type(exc).__name__}: {exc}"}


def sonda_salida_shell(shell_id) -> list:
    """Lineas de un shell del proc_registry del REPL. Import perezoso y
    guardado: el motor tiene que poder correr en un proceso donde el REPL nunca
    arranco (un demonio, un test)."""
    try:
        from cognia.console import proc_registry
        return list(proc_registry.get_output(int(shell_id)) or [])
    except Exception:
        return []


def _huella_fichero(ruta: str) -> str:
    """mtime + sha256 del contenido. mtime SOLO no basta (la resolucion de FAT
    y de algunos NFS es de 1-2 s: un cambio rapido pasa desapercibido) y el
    hash SOLO obliga a leer el fichero entero siempre. Los dos juntos: el mtime
    es el filtro barato y el hash el juez."""
    try:
        p = Path(ruta)
        if not p.exists():
            return ""
        st = p.stat()
        if p.is_dir():
            return f"dir:{st.st_mtime_ns}"
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for bloque in iter(lambda: f.read(65536), b""):
                h.update(bloque)
        return f"{st.st_mtime_ns}:{h.hexdigest()[:16]}"
    except Exception as exc:
        return f"error:{type(exc).__name__}"


# ═══════════════════════════════════════════════════════════════════════════
# Anti-ruido: [SILENT] y horas de silencio
# ═══════════════════════════════════════════════════════════════════════════

def es_silencioso(texto: str) -> bool:
    """True si la salida lleva una marca del contrato [SILENT] al principio o
    al final. Se mira en los DOS extremos porque un script real imprime su
    marca al final (despues de trabajar) tan a menudo como al principio."""
    limpio = (texto or "").strip()
    if not limpio:
        return False
    for marca in MARCAS_SILENT:
        if limpio.startswith(marca) or limpio.endswith(marca):
            return True
    return False


def _minutos_del_dia(valor) -> int:
    """22 -> 1320 ; '22:30' -> 1350 ; '7' -> 420. -1 si no se entiende."""
    try:
        if isinstance(valor, (int, float)):
            return int(valor) % 24 * 60
        texto = str(valor).strip()
        if not texto:
            return -1
        if ":" in texto:
            hh, mm = texto.split(":", 1)
            return (int(hh) % 24) * 60 + int(mm) % 60
        return (int(texto) % 24) * 60
    except Exception:
        return -1


def en_horas_silencio(horas, ahora: float) -> bool:
    """``horas`` acepta [22, 7], ('22:00', '07:30') o '22-7'. Rango que cruza
    medianoche incluido (inicio > fin). Formato invalido -> False: un rango mal
    escrito NO puede silenciar un monitor para siempre sin que nadie lo note.
    """
    if not horas:
        return False
    try:
        if isinstance(horas, str):
            partes = re.split(r"[-]", horas, maxsplit=1)
        else:
            partes = list(horas)
        if len(partes) != 2:
            return False
        inicio = _minutos_del_dia(partes[0])
        fin = _minutos_del_dia(partes[1])
        if inicio < 0 or fin < 0 or inicio == fin:
            return False
        t = time.localtime(ahora)
        m = t.tm_hour * 60 + t.tm_min
        if inicio < fin:
            return inicio <= m < fin
        return m >= inicio or m < fin      # cruza medianoche
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════════════
# El evaluador de condiciones. NUNCA lanza: devuelve valores.
# ═══════════════════════════════════════════════════════════════════════════
#
# La condicion CANONICA es {"tipo":"comando"} — la leccion de Claude Code: la
# condicion ES un proceso, no un lenguaje de expresiones. Los demas tipos son
# atajos declarativos para los casos que la gente pide todos los dias y que
# escribir como comando seria distinto en cada sistema operativo.

def _cond_comando(cond: dict, estado: dict, sondas: dict) -> dict:
    cmd = str(cond.get("cmd") or cond.get("comando") or "").strip()
    if not cmd:
        return {"disparo": False, "error": "condicion comando sin 'cmd'"}
    res = sondas["ejecutar"](cmd, float(cond.get("timeout_s") or TIMEOUT_COMANDO_S),
                             str(cond.get("cwd") or ""))
    salida = (res.get("salida") or "") + (res.get("error") or "")
    dispara_si = str(cond.get("dispara_si") or "salida").strip()
    if res.get("timeout"):
        # Matamos la sonda: no sabemos si iba a disparar. Es un error de sonda,
        # NO un disparo — inventar un disparo con datos que no tenemos es
        # exactamente el fallo silencioso que el repo ya pago caro.
        return {"disparo": False, "error": res.get("error") or "timeout"}
    codigo = res.get("codigo")
    if dispara_si == "salida":
        texto = (res.get("salida") or "").strip()
        return {"disparo": bool(texto),
                "detalle": _corta(texto) if texto else "sin salida"}
    if dispara_si == "exit0":
        return {"disparo": codigo == 0, "detalle": f"exit {codigo}"}
    if dispara_si == "exit_no_0":
        return {"disparo": codigo not in (0, None), "detalle": f"exit {codigo}"}
    if dispara_si == "regex":
        patron = str(cond.get("patron") or "")
        if not patron:
            return {"disparo": False, "error": "dispara_si=regex sin 'patron'"}
        m = re.search(patron, salida, re.MULTILINE)
        return {"disparo": bool(m),
                "detalle": _corta(m.group(0)) if m else f"sin match de '{patron}'"}
    return {"disparo": False, "error": f"dispara_si desconocido: '{dispara_si}'"}


def _cond_fichero_existe(cond: dict, estado: dict, sondas: dict) -> dict:
    ruta = str(cond.get("ruta") or cond.get("path") or "").strip()
    if not ruta:
        return {"disparo": False, "error": "fichero_existe sin 'ruta'"}
    existe = Path(ruta).exists()
    # dispara_si='ausente' sirve para el caso simetrico y real: esperar a que
    # un lockfile DESAPAREZCA.
    if str(cond.get("dispara_si") or "existe") == "ausente":
        return {"disparo": not existe,
                "detalle": f"{'sigue' if existe else 'ya no'} existe {ruta}"}
    return {"disparo": existe,
            "detalle": f"existe {ruta}" if existe else f"aun no existe {ruta}"}


def _cond_fichero_cambio(cond: dict, estado: dict, sondas: dict) -> dict:
    ruta = str(cond.get("ruta") or cond.get("path") or "").strip()
    if not ruta:
        return {"disparo": False, "error": "fichero_cambio sin 'ruta'"}
    huella = sondas["huella"](ruta)
    previa = estado.get("huella")
    estado["huella"] = huella
    if previa is None:
        # Primera evaluacion = LINEA BASE, no disparo. Si no, todo monitor
        # recien creado dispararia al instante y el usuario aprenderia a
        # ignorar sus propios monitores (el peor final posible para uno).
        return {"disparo": False, "detalle": "linea base tomada", "estado": estado}
    if huella == previa:
        return {"disparo": False, "detalle": "sin cambios", "estado": estado}
    return {"disparo": True, "detalle": f"cambio {ruta}", "estado": estado}


def _cond_url(cond: dict, estado: dict, sondas: dict) -> dict:
    url = str(cond.get("url") or "").strip()
    if not url:
        return {"disparo": False, "error": "condicion url sin 'url'"}
    res = sondas["url"](url, float(cond.get("timeout_s") or 5.0))
    arriba = bool(res.get("arriba"))
    espera = str(cond.get("dispara_si") or cond.get("espera") or "arriba").strip()
    if espera in ("abajo", "caida"):
        return {"disparo": not arriba, "detalle": f"{url}: {res.get('detalle')}"}
    return {"disparo": arriba, "detalle": f"{url}: {res.get('detalle')}"}


def _cond_proceso_vivo(cond: dict, estado: dict, sondas: dict) -> dict:
    pid = cond.get("pid")
    if pid is None:
        return {"disparo": False, "error": "proceso_vivo sin 'pid'"}
    res = sondas["proceso"](pid)
    vivo = bool(res.get("vivo"))
    # El caso util por defecto es el CONTRARIO al nombre: casi siempre se
    # monitorea "avisame cuando MUERA" (el build termino). Se deja explicito.
    espera = str(cond.get("dispara_si") or "muerto").strip()
    if espera == "vivo":
        return {"disparo": vivo, "detalle": str(res.get("detalle") or "")}
    return {"disparo": not vivo, "detalle": str(res.get("detalle") or "")}


def _cond_salida_shell(cond: dict, estado: dict, sondas: dict) -> dict:
    shell_id = cond.get("shell_id", cond.get("shell"))
    patron = str(cond.get("patron") or "")
    if shell_id is None or not patron:
        return {"disparo": False, "error": "salida_shell necesita 'shell_id' y 'patron'"}
    lineas = sondas["shell"](shell_id)
    # Solo lineas NUEVAS: un patron que ya matcheo en la linea 3 dispararia en
    # cada tick para siempre en modo recurrente. El cursor se persiste.
    desde = int(estado.get("cursor_shell") or 0)
    nuevas = lineas[desde:]
    estado["cursor_shell"] = len(lineas)
    try:
        rx = re.compile(patron)
    except re.error as exc:
        return {"disparo": False, "error": f"patron invalido: {exc}", "estado": estado}
    for linea in nuevas:
        if rx.search(str(linea)):
            return {"disparo": True, "detalle": _corta(str(linea)), "estado": estado}
    return {"disparo": False, "detalle": f"{len(nuevas)} lineas nuevas sin match",
            "estado": estado}


_EVALUADORES = {
    "comando": _cond_comando,
    "fichero_existe": _cond_fichero_existe,
    "fichero_cambio": _cond_fichero_cambio,
    "url": _cond_url,
    "proceso_vivo": _cond_proceso_vivo,
    "salida_shell": _cond_salida_shell,
}

TIPOS_CONDICION = tuple(sorted(_EVALUADORES))


def _corta(texto: str, n: int = 200) -> str:
    texto = " ".join(str(texto or "").split())
    return texto if len(texto) <= n else texto[: n - 3] + "..."


def evaluar_condicion(condicion: dict, estado: dict = None,
                      sondas: dict = None) -> dict:
    """{"disparo": bool, "detalle": str, "error": str, "estado": dict}.

    NUNCA lanza. Un error de la sonda sale por ``error`` y el llamador lo
    guarda en ``ultimo_error``: en el motor viejo una excepcion del check_fn
    mataba el hilo y el monitor quedaba muerto en silencio para siempre.
    """
    estado = dict(estado or {})
    sondas = dict(sondas or {})
    sondas.setdefault("ejecutar", ejecutar_comando)
    sondas.setdefault("url", sonda_url)
    sondas.setdefault("proceso", sonda_proceso_vivo)
    sondas.setdefault("shell", sonda_salida_shell)
    sondas.setdefault("huella", _huella_fichero)
    tipo = str((condicion or {}).get("tipo") or "").strip()
    fn = _EVALUADORES.get(tipo)
    if fn is None:
        return {"disparo": False, "detalle": "", "estado": estado,
                "error": f"condicion desconocida: '{tipo}' "
                         f"(validas: {', '.join(TIPOS_CONDICION)})"}
    try:
        res = fn(dict(condicion), estado, sondas) or {}
    except Exception as exc:
        return {"disparo": False, "detalle": "", "estado": estado,
                "error": f"{type(exc).__name__}: {exc}"}
    return {"disparo": bool(res.get("disparo")),
            "detalle": str(res.get("detalle") or ""),
            "error": str(res.get("error") or ""),
            "estado": dict(res.get("estado") or estado)}


# ═══════════════════════════════════════════════════════════════════════════
# El motor
# ═══════════════════════════════════════════════════════════════════════════

class MotorMonitores:
    """Monitores persistidos en disco, con acciones y ledger.

    Sin hilos por defecto: ``tick(ahora=...)`` es una funcion pura de reloj
    inyectado, y eso es lo que la hace probable en seco. ``arrancar_hilo()``
    monta UN solo daemon que llama a tick — un hilo por monitor (el diseno
    viejo) multiplica los modos de fallo sin comprar nada.
    """

    def __init__(self, dir_base=None, reloj=None, ejecutar_fn=None,
                 url_fn=None, proceso_fn=None, shell_fn=None, huella_fn=None,
                 reproducir_flujo_fn=None, emitir_fn=None):
        self._dir = Path(dir_base) if dir_base else None
        self._reloj = reloj or time.time
        self._sondas = {
            "ejecutar": ejecutar_fn or ejecutar_comando,
            "url": url_fn or sonda_url,
            "proceso": proceso_fn or sonda_proceso_vivo,
            "shell": shell_fn or sonda_salida_shell,
            "huella": huella_fn or _huella_fichero,
        }
        # Inyectado = el motor reproduce el flujo en el acto. None = lo ENCOLA
        # como tarea pendiente para que lo haga quien tenga el run_tool. Las dos
        # vias dejan la misma fila en el ledger.
        self._reproducir_flujo = reproducir_flujo_fn
        self._emitir = emitir_fn or _emitir_bus
        self._lock = threading.RLock()
        self._eventos: list = []        # notificaciones listas para el REPL
        self._silenciados: list = []    # acumuladas dentro de horas_silencio
        self._tareas: list = []         # cola de despertar_agente / flujo
        self._hilo = None
        self._parar = threading.Event()
        self._monitores = self._cargar()

    # ── rutas (respetan el override por instancia y el env) ────────────────

    def dir_base(self) -> Path:
        return self._dir if self._dir is not None else dir_monitores()

    def _ruta_estado(self) -> Path:
        return self.dir_base() / "monitores.json"

    def _ruta_ledger(self) -> Path:
        return self.dir_base() / "eventos.jsonl"

    def _ruta_latido(self) -> Path:
        return self.dir_base() / "latido.json"

    # ── persistencia ──────────────────────────────────────────────────────

    def _cargar(self) -> dict:
        datos = _leer_json(self._ruta_estado()) or {}
        mons = datos.get("monitores")
        if not isinstance(mons, dict):
            return {}
        # Se filtra lo que no sea dict: un fichero editado a mano no puede
        # tumbar el motor entero al arrancar.
        return {str(k): dict(v) for k, v in mons.items() if isinstance(v, dict)}

    def _guardar(self) -> bool:
        return _escribir_json(self._ruta_estado(),
                              {"monitores": self._monitores,
                               "ts": self._reloj(), "version": 1})

    def _registrar(self, fila: dict) -> None:
        _append_jsonl(self._ruta_ledger(), fila)

    # ── alta / baja / consulta ────────────────────────────────────────────

    def crear(self, nombre: str, condicion: dict, accion: dict = None,
              intervalo_s: float = INTERVALO_S, modo: str = "recurrente",
              debounce_s: float = 0.0, horas_silencio=None,
              activo: bool = True) -> dict:
        """Crea y PERSISTE un monitor. Devuelve el dict (con 'error' si el
        alta se rechaza: crear no lanza, para que una linea ACCION: mal escrita
        del agente devuelva un mensaje util en vez de romper el turno)."""
        with self._lock:
            tipo = str((condicion or {}).get("tipo") or "").strip()
            if tipo not in _EVALUADORES:
                return {"error": f"condicion desconocida: '{tipo}' "
                                 f"(validas: {', '.join(TIPOS_CONDICION)})"}
            accion = dict(accion or {"tipo": "avisar"})
            tipo_accion = str(accion.get("tipo") or "").strip()
            if tipo_accion not in _ACCIONES:
                return {"error": f"accion desconocida: '{tipo_accion}' "
                                 f"(validas: {', '.join(sorted(_ACCIONES))})"}
            if modo not in _MODOS:
                modo = "recurrente"
            ahora = self._reloj()
            mid = self._nuevo_id()
            mon = {
                "id": mid,
                "nombre": str(nombre or "").strip() or f"monitor {mid}",
                "condicion": dict(condicion),
                "accion": accion,
                "intervalo_s": max(0.0, float(intervalo_s or 0.0)),
                "modo": modo,
                "debounce_s": max(0.0, float(debounce_s or 0.0)),
                "horas_silencio": horas_silencio or [],
                "estado": "activo" if activo else "pausado",
                "creado": ahora,
                "ultimo_chequeo": 0.0,
                "ultimo_disparo": 0.0,
                "disparos": 0,
                "ultimo_error": "",
                "activo": bool(activo),
                "memoria": {},          # estado de la sonda (huella, cursor)
            }
            self._monitores[mid] = mon
            self._guardar()
            self._registrar({"ts": ahora, "monitor_id": mid, "nombre": mon["nombre"],
                             "fase": "alta", "estado": "completed",
                             "detalle": f"{tipo} -> {tipo_accion} ({modo})"})
            return dict(mon)

    def _nuevo_id(self) -> str:
        n = 0
        for mid in self._monitores:
            m = re.match(r"^m(\d+)$", str(mid))
            if m:
                n = max(n, int(m.group(1)))
        return f"m{n + 1}"

    def listar(self) -> list:
        with self._lock:
            return [dict(m) for m in sorted(self._monitores.values(),
                                            key=lambda d: str(d.get("id")))]

    def obtener(self, mid: str):
        with self._lock:
            mon = self._monitores.get(str(mid))
            return dict(mon) if mon else None

    def borrar(self, mid: str) -> bool:
        with self._lock:
            if str(mid) not in self._monitores:
                return False
            nombre = self._monitores[str(mid)].get("nombre", "")
            del self._monitores[str(mid)]
            self._guardar()
            self._registrar({"ts": self._reloj(), "monitor_id": str(mid),
                             "nombre": nombre, "fase": "baja",
                             "estado": "completed", "detalle": "borrado"})
            return True

    def pausar(self, mid: str) -> bool:
        return self._cambiar_activo(mid, False)

    def reanudar(self, mid: str) -> bool:
        return self._cambiar_activo(mid, True)

    def _cambiar_activo(self, mid: str, activo: bool) -> bool:
        with self._lock:
            mon = self._monitores.get(str(mid))
            if mon is None:
                return False
            mon["activo"] = bool(activo)
            mon["estado"] = "activo" if activo else "pausado"
            self._guardar()
            return True

    # ── colas que el cableado drena ───────────────────────────────────────

    def pop_eventos(self) -> list:
        """Drena las notificaciones listas. list[str], IGUAL que el
        ``pop_fired_events()`` del motor viejo: el REPL ya sabe drenarlo entre
        turnos y no hay que ensenarle nada nuevo."""
        with self._lock:
            fuera = [e["texto"] for e in self._eventos]
            self._eventos = []
            return fuera

    def pop_eventos_ricos(self) -> list:
        """Igual que pop_eventos pero con el dict entero (para la UI viva)."""
        with self._lock:
            fuera = list(self._eventos)
            self._eventos = []
            return fuera

    def tareas_pendientes(self, drenar: bool = True) -> list:
        """Las tareas que 'despertar_agente' (y 'flujo' sin reproductor)
        dejaron para el agente. El motor NO llama al agente: lo hace el
        cableado, que es quien tiene el ctx, el presupuesto y el permiso."""
        with self._lock:
            fuera = [dict(t) for t in self._tareas]
            if drenar:
                self._tareas = []
            return fuera

    def confirmar_tarea(self, tarea_id: str, ok: bool, detalle: str = "") -> bool:
        """Cierra en el ledger una tarea que estaba en 'unknown'. Quien la
        atendio es el UNICO que puede probar como salio; hasta que llama aca,
        el estado honesto es 'no se sabe' (Hermes)."""
        self._registrar({"ts": self._reloj(), "monitor_id": "", "nombre": "",
                         "fase": "tarea", "tarea_id": str(tarea_id),
                         "estado": "completed" if ok else "failed",
                         "detalle": _corta(detalle, 500)})
        return True

    def ledger(self, n: int = 50) -> list:
        """Ultimas n filas del ledger, ya parseadas. Filas corruptas se saltan
        (el ledger es append-only y no se repara: se lee lo que se entiende)."""
        filas = []
        try:
            with open(self._ruta_ledger(), "r", encoding="utf-8") as f:
                for linea in f:
                    linea = linea.strip()
                    if not linea:
                        continue
                    try:
                        filas.append(json.loads(linea))
                    except Exception:
                        continue
        except Exception:
            return []
        return filas[-n:] if n and n > 0 else filas

    # ── el tick ───────────────────────────────────────────────────────────

    def tick(self, ahora: float = None, forzar: bool = False) -> dict:
        """Evalua los monitores a los que les toca. Devuelve el informe; NUNCA
        lanza. Motor SIN hilos: con ``ahora`` inyectado se prueba el debounce,
        el intervalo y las horas de silencio con un reloj fijo."""
        ahora = float(ahora if ahora is not None else self._reloj())
        informe = {"ahora": ahora, "evaluados": 0, "disparados": [],
                   "errores": [], "notificados": 0, "silenciados": 0,
                   "detalle": []}
        with self._lock:
            self._liberar_silenciados(ahora, informe)
            for mid in sorted(self._monitores):
                mon = self._monitores[mid]
                if not mon.get("activo"):
                    continue
                intervalo = float(mon.get("intervalo_s") or 0.0)
                ultimo = float(mon.get("ultimo_chequeo") or 0.0)
                # `forzar` es el tick MANUAL ("/centinela tick"): el usuario pide
                # comprobar AHORA y el intervalo no manda. Sin esto, crear un
                # monitor y tickear a los 2 segundos devolvia "evaluados 0" con
                # el monitor activo y la condicion ya cumplida -- indistinguible
                # de un motor roto. Cazado tecleando el comando, no en un test.
                if not forzar and ultimo and (ahora - ultimo) < intervalo:
                    continue
                informe["evaluados"] += 1
                self._evaluar_uno(mon, ahora, informe)
            self._guardar()
        self._latir(ahora, informe)
        return informe

    def _evaluar_uno(self, mon: dict, ahora: float, informe: dict) -> None:
        mid = mon["id"]
        mon["ultimo_chequeo"] = ahora
        res = evaluar_condicion(mon.get("condicion") or {},
                                mon.get("memoria") or {}, self._sondas)
        mon["memoria"] = res.get("estado") or {}
        if res.get("error"):
            # La sonda revento: es ultimo_error, NO una excepcion que mate el
            # tick ni un disparo inventado. El monitor sigue vivo y lo vuelve a
            # intentar en el proximo intervalo.
            mon["ultimo_error"] = _corta(res["error"], 300)
            informe["errores"].append(mid)
            informe["detalle"].append({"id": mid, "resultado": "error",
                                       "error": mon["ultimo_error"]})
            self._registrar({"ts": ahora, "monitor_id": mid,
                             "nombre": mon.get("nombre", ""), "fase": "sonda",
                             "estado": "failed", "detalle": mon["ultimo_error"]})
            return
        mon["ultimo_error"] = ""
        if not res.get("disparo"):
            informe["detalle"].append({"id": mid, "resultado": "quieto",
                                       "detalle": res.get("detalle", "")})
            return

        # DEBOUNCE: no re-disparar antes de N s. Es lo que hace usable un
        # monitor recurrente sobre algo que parpadea (una URL que va y viene).
        debounce = float(mon.get("debounce_s") or 0.0)
        ultimo_disparo = float(mon.get("ultimo_disparo") or 0.0)
        if debounce and ultimo_disparo and (ahora - ultimo_disparo) < debounce:
            informe["detalle"].append({"id": mid, "resultado": "debounce",
                                       "detalle": res.get("detalle", "")})
            return

        mon["ultimo_disparo"] = ahora
        mon["disparos"] = int(mon.get("disparos") or 0) + 1
        informe["disparados"].append(mid)
        self._registrar({"ts": ahora, "monitor_id": mid,
                         "nombre": mon.get("nombre", ""), "fase": "disparo",
                         "estado": "completed",
                         "detalle": _corta(res.get("detalle", ""))})

        salida = self._ejecutar_accion(mon, res.get("detalle", ""), ahora, informe)

        # CARDINALIDAD (Claude Code): 'una_vez' es una notificacion que SALE al
        # cumplirse; 'recurrente' es una por ocurrencia y sigue vivo.
        if str(mon.get("modo")) == "una_vez":
            mon["activo"] = False
            mon["estado"] = "disparado"
        informe["detalle"].append({"id": mid, "resultado": "disparo",
                                   "detalle": res.get("detalle", ""),
                                   "accion": salida})

    def _ejecutar_accion(self, mon: dict, detalle: str, ahora: float,
                         informe: dict) -> dict:
        accion = dict(mon.get("accion") or {"tipo": "avisar"})
        tipo = str(accion.get("tipo") or "avisar")
        fn = _ACCIONES.get(tipo)
        if fn is None:
            resultado = {"estado": "failed", "salida": "",
                         "notificar": f"accion desconocida: '{tipo}'"}
        else:
            try:
                resultado = fn(self, mon, accion, detalle) or {}
            except Exception as exc:
                # Una accion que revienta se REGISTRA como failed; el motor
                # sigue. No hay camino en el que una accion mate el tick.
                resultado = {"estado": "failed", "salida": "",
                             "notificar": f"{type(exc).__name__}: {exc}"}
        estado = str(resultado.get("estado") or "unknown")
        if estado not in ESTADOS_TERMINALES:
            estado = "unknown"
        salida = str(resultado.get("salida") or "")
        texto = str(resultado.get("notificar") or "")

        # Contrato [SILENT]: se registra SIEMPRE, se notifica solo si hay algo
        # que contar. Es la diferencia entre un monitor que se puede dejar
        # corriendo un mes y uno que el usuario apaga el primer dia.
        silencioso = es_silencioso(salida) or es_silencioso(texto)
        notificado = False
        if texto and not silencioso:
            notificado = self._notificar(mon, texto, ahora, informe)

        self._registrar({"ts": ahora, "monitor_id": mon["id"],
                         "nombre": mon.get("nombre", ""), "fase": "accion",
                         "accion": tipo, "estado": estado,
                         "detalle": _corta(detalle),
                         "salida": _corta(salida, 500),
                         "silent": bool(silencioso),
                         "notificado": bool(notificado),
                         "tarea_id": str(resultado.get("tarea_id") or "")})
        return {"tipo": tipo, "estado": estado, "silent": silencioso,
                "notificado": notificado, "salida": _corta(salida, 500),
                "tarea_id": str(resultado.get("tarea_id") or "")}

    # ── notificacion y horas de silencio ──────────────────────────────────

    def _notificar(self, mon: dict, texto: str, ahora: float,
                   informe: dict) -> bool:
        """True si la notificacion queda LISTA para el REPL; False si se
        acumula por horas de silencio. Nunca se pierde: se acumula."""
        evento = {"ts": ahora, "monitor_id": mon["id"],
                  "nombre": mon.get("nombre", ""),
                  "texto": f"[monitor {mon['id']}] {mon.get('nombre','')}: {texto}"}
        if en_horas_silencio(mon.get("horas_silencio"), ahora):
            self._silenciados.append(evento)
            informe["silenciados"] += 1
            return False
        self._eventos.append(evento)
        informe["notificados"] += 1
        self._emitir(evento["texto"])
        return True

    def _liberar_silenciados(self, ahora: float, informe: dict) -> None:
        """Al salir de las horas de silencio, lo acumulado pasa a la cola
        normal. 'Se acumula pero no se notifica' significa que llega TARDE, no
        que se tira: un monitor que traga eventos en silencio es peor que uno
        que no existe."""
        if not self._silenciados:
            return
        quedan = []
        for ev in self._silenciados:
            mon = self._monitores.get(ev["monitor_id"])
            horas = mon.get("horas_silencio") if mon else None
            if en_horas_silencio(horas, ahora):
                quedan.append(ev)
                continue
            self._eventos.append(ev)
            informe["notificados"] += 1
            self._emitir(ev["texto"])
        self._silenciados = quedan

    def silenciados_pendientes(self) -> int:
        with self._lock:
            return len(self._silenciados)

    # ── heartbeat (fichero aparte, estilo Hermes) ─────────────────────────

    def _latir(self, ahora: float, informe: dict) -> None:
        _escribir_json(self._ruta_latido(), {
            "ts": ahora, "pid": os.getpid(),
            "evaluados": informe["evaluados"],
            "disparados": len(informe["disparados"]),
            "errores": len(informe["errores"]),
            "activos": sum(1 for m in self._monitores.values() if m.get("activo")),
        })

    def latido(self) -> dict:
        return _leer_json(self._ruta_latido()) or {}

    # ── el hilo vivo del REPL ─────────────────────────────────────────────

    def arrancar_hilo(self, paso_s: float = PASO_HILO_S) -> bool:
        """UN solo daemon que llama a tick(). Idempotente: llamarlo dos veces
        no monta dos hilos (el motor viejo montaba uno POR monitor)."""
        with self._lock:
            if self._hilo is not None and self._hilo.is_alive():
                return False
            self._parar = threading.Event()
            self._hilo = threading.Thread(target=self._bucle, args=(paso_s,),
                                          daemon=True, name="monitores")
            self._hilo.start()
            return True

    def parar_hilo(self, timeout_s: float = 2.0) -> bool:
        hilo = self._hilo
        self._parar.set()
        if hilo is not None and hilo.is_alive():
            hilo.join(timeout=timeout_s)
        self._hilo = None
        return True

    def hilo_vivo(self) -> bool:
        return self._hilo is not None and self._hilo.is_alive()

    def _bucle(self, paso_s: float) -> None:
        while not self._parar.is_set():
            try:
                self.tick()
            except Exception as exc:
                # El bucle NO muere por un tick malo: el motor viejo perdia el
                # monitor entero ante la primera excepcion del check_fn.
                try:
                    self._registrar({"ts": self._reloj(), "monitor_id": "",
                                     "nombre": "", "fase": "tick",
                                     "estado": "failed",
                                     "detalle": f"{type(exc).__name__}: {exc}"})
                except Exception:
                    pass
            self._parar.wait(max(0.05, float(paso_s or PASO_HILO_S)))


# ═══════════════════════════════════════════════════════════════════════════
# Acciones. Firma: fn(motor, mon, accion, detalle) -> dict
#   {"estado": completed|failed|unknown, "salida": str, "notificar": str}
# Toda accion deja fila en el ledger (lo hace _ejecutar_accion, no ellas).
# ═══════════════════════════════════════════════════════════════════════════

def _accion_avisar(motor, mon: dict, accion: dict, detalle: str) -> dict:
    texto = str(accion.get("texto") or "").strip() or detalle or "disparo"
    # Encolar un aviso siempre se puede probar que salio bien: la prueba es que
    # el texto quedo en la cola.
    return {"estado": "completed", "salida": texto, "notificar": texto}


def _accion_ejecutar(motor, mon: dict, accion: dict, detalle: str) -> dict:
    cmd = str(accion.get("cmd") or accion.get("comando") or "").strip()
    if not cmd:
        return {"estado": "failed", "salida": "", "notificar": "accion ejecutar sin 'cmd'"}
    res = motor._sondas["ejecutar"](
        cmd, float(accion.get("timeout_s") or TIMEOUT_COMANDO_S),
        str(accion.get("cwd") or ""))
    salida = ((res.get("salida") or "") + (res.get("error") or "")).strip()
    if res.get("timeout"):
        # LO MATAMOS: el unico 'unknown' honesto de esta accion. No se sabe si
        # el trabajo se hizo, y decir completed o failed seria inventar.
        return {"estado": "unknown", "salida": salida,
                "notificar": f"comando matado por timeout: {_corta(cmd, 80)}"}
    codigo = res.get("codigo")
    estado = "completed" if codigo == 0 else "failed"
    return {"estado": estado, "salida": salida,
            "notificar": salida or f"{_corta(cmd, 80)} -> exit {codigo}"}


def _accion_despertar_agente(motor, mon: dict, accion: dict, detalle: str) -> dict:
    """ENCOLA una tarea. El modulo NO llama al agente a proposito: un hilo
    daemon que dispara al LLM no se puede probar en seco, no respeta
    presupuesto y no tiene ctx. El cableado drena tareas_pendientes()."""
    tarea = str(accion.get("tarea") or "").strip()
    if not tarea:
        return {"estado": "failed", "salida": "",
                "notificar": "despertar_agente sin 'tarea'"}
    ahora = motor._reloj()
    tarea_id = f"t{int(ahora * 1000)}-{mon['id']}"
    item = {"id": tarea_id, "monitor_id": mon["id"],
            "nombre": mon.get("nombre", ""), "tipo": "tarea",
            "tarea": tarea, "detalle": detalle, "creado": ahora}
    motor._tareas.append(item)
    # 'unknown' hasta que quien la atienda llame a confirmar_tarea(): mientras
    # este en la cola, NADIE puede probar como salio.
    return {"estado": "unknown", "salida": "", "tarea_id": tarea_id,
            "notificar": f"tarea encolada para el agente: {_corta(tarea, 120)}"}


def _accion_flujo(motor, mon: dict, accion: dict, detalle: str) -> dict:
    """Reproduce un flujo grabado. Con reproducir_flujo_fn inyectado se corre
    en el acto; sin el, se ENCOLA igual que despertar_agente (el motor no tiene
    run_tool y fabricarlo aca seria cablear el agente dentro del monitor)."""
    nombre = str(accion.get("nombre") or "").strip()
    if not nombre:
        return {"estado": "failed", "salida": "", "notificar": "accion flujo sin 'nombre'"}
    valores = dict(accion.get("valores") or {})
    if motor._reproducir_flujo is None:
        ahora = motor._reloj()
        tarea_id = f"f{int(ahora * 1000)}-{mon['id']}"
        motor._tareas.append({"id": tarea_id, "monitor_id": mon["id"],
                              "nombre": mon.get("nombre", ""), "tipo": "flujo",
                              "flujo": nombre, "valores": valores,
                              "detalle": detalle, "creado": ahora})
        return {"estado": "unknown", "salida": "", "tarea_id": tarea_id,
                "notificar": f"flujo encolado: {nombre}"}
    informe = motor._reproducir_flujo(nombre, valores) or {}
    if isinstance(informe, dict):
        ok = bool(informe.get("ok", True))
        salida = str(informe.get("resumen") or informe.get("salida") or "")
    else:
        ok, salida = True, str(informe)
    return {"estado": "completed" if ok else "failed", "salida": salida,
            "notificar": salida or f"flujo {nombre}: {'ok' if ok else 'fallo'}"}


_ACCIONES = {
    "avisar": _accion_avisar,
    "ejecutar": _accion_ejecutar,
    "despertar_agente": _accion_despertar_agente,
    "flujo": _accion_flujo,
}

TIPOS_ACCION = tuple(sorted(_ACCIONES))


def _emitir_bus(texto: str) -> None:
    """Publica el aviso en el bus de eventos si esta disponible. Guardado
    entero: el adorno jamas rompe un tick (mismo contrato que ux/events.py)."""
    try:
        from cognia.ux.events import Aviso, emitir
        emitir(Aviso(texto=texto, origen="monitores"))
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════
# Singleton de modulo: lo que el cableado (REPL / tools) usa
# ═══════════════════════════════════════════════════════════════════════════

_MOTOR = None


def motor() -> MotorMonitores:
    """El motor del proceso. Perezoso a proposito: importar este modulo no
    puede tocar el disco ni montar hilos (lo importa el arranque del CLI)."""
    global _MOTOR
    with _LOCK_GLOBAL:
        if _MOTOR is None:
            _MOTOR = MotorMonitores()
        return _MOTOR


def reiniciar_motor() -> None:
    """Suelta el singleton (tests que cambian COGNIA_MONITORES_DIR)."""
    global _MOTOR
    with _LOCK_GLOBAL:
        if _MOTOR is not None:
            try:
                _MOTOR.parar_hilo()
            except Exception:
                pass
        _MOTOR = None


def crear(nombre: str, condicion: dict, accion: dict = None, **kw) -> dict:
    return motor().crear(nombre, condicion, accion, **kw)


def listar() -> list:
    return motor().listar()


def borrar(mid: str) -> bool:
    return motor().borrar(mid)


def tick(ahora: float = None, forzar: bool = False) -> dict:
    return motor().tick(ahora, forzar=forzar)


def pop_eventos() -> list:
    """Drenaje compatible con el ``pop_fired_events()`` del motor viejo."""
    return motor().pop_eventos()


def tareas_pendientes(drenar: bool = True) -> list:
    return motor().tareas_pendientes(drenar)


def arrancar_hilo(paso_s: float = PASO_HILO_S) -> bool:
    return motor().arrancar_hilo(paso_s)


def parar_hilo() -> bool:
    return motor().parar_hilo()
