"""
cognia/flujos/grabador.py
=========================
QUE RESUELVE: convierte lo que el agente HIZO en una TRAYECTORIA estructurada y
fiel (una grabacion), persistida en disco, para que despues se pueda revisar,
reproducir o destilar en un flujo automatizable.

POR QUE EXISTE: el usuario pide "grabo un flujo de acciones y el agente lo
aprende". Investigado 2026-08-18: Cursor NO graba acciones (genera markdown
desde el CHAT, que es otra cosa); el unico producto que graba de verdad es
"Record a Skill" de Claude Cowork. O sea que el grabador es un hueco real, y
este modulo es el SUSTRATO: solo captura y persiste HECHOS. La destilacion a
"procedimiento" NO vive aca, a proposito.

REGLA VINCULANTE DEL REPO, HORNEADA EN EL DISENO: las skills auto-capturadas de
Cognia ENVENENARON tareas ajenas (una traza de ATASCO se ascendio a
"procedimiento verificado" y bajo el camino feliz de 5/5 a 2-4/5). Por eso una
grabacion es un REGISTRO, nunca un procedimiento: se guarda con su `ok` y su
resultado reales, incluidos los pasos que fallaron, y NADA de lo grabado queda
activo por si solo. Quien quiera ascender una grabacion a algo ejecutable tiene
que hacerla pasar un examen ejecutable; este modulo no ofrece ni un atajo para
saltarselo.

DECISIONES QUE COSTARON ALGO
----------------------------
1. JSONL APPEND-ONLY, una grabacion por fichero. Una tarea del agente puede
   durar minutos y morir a la mitad (timeout, ctrl-C, cuelgue del backend). Con
   un JSON unico reescrito al cerrar, una tarea que revienta a los 18 pasos no
   deja NADA. Append-only con flush por linea deja los 18 pasos legibles, y
   `cargar()` los lee hasta donde llega el fichero. La cabecera es la primera
   linea; el cierre es la ultima (si la hay).

2. GRABAR DESDE EL BUS, SIN TOCAR EL BUCLE. `cognia/agent/loop.py` ya emite
   ToolInicio/ToolFin/TareaInicio en `cognia/ux/events.py`. `suscribir()` se
   engancha ahi y graba sin editar una sola linea del camino caliente. LO QUE
   ESO CUESTA, DECLARADO: el bucle emite `args=args_str[:120]` y
   `resumen=resultado[:200]` (loop.py:711 y loop.py:735), asi que por el bus
   los argumentos llegan RECORTADOS a 120 chars. Consecuencias reales:
     - la RUTA sobrevive casi siempre (en el protocolo del repo va PRIMERO,
       antes del '|'), asi que `derivar_ficheros` sigue acertando;
     - el CONTENIDO de escribir_archivo/editar_archivo NO sobrevive, y el
       `comando` de `ejecutar` se corta si pasa de 120 chars.
   Por eso cada paso grabado por el bus lleva `via_bus=True`: el consumidor
   sabe que `args` puede estar truncado y que no puede reproducir el paso a
   ciegas. Si el cableado quiere el dato COMPLETO tiene que llamar
   `registrar_paso()` desde el bucle con el args entero. Es la unica forma, y
   esta expuesta.

3. UN SOLO PRODUCTOR DE PASOS POR GRABACION, EXPLICITO. Si el bus grabara y
   ademas el bucle llamara `registrar_paso()`, cada paso saldria DOS veces. No
   se resuelve con deduplicacion heuristica (adivinar que dos pasos son "el
   mismo" es exactamente el tipo de suposicion que este repo paga cara): se
   resuelve declarandolo. `iniciar(..., capturar_bus=True)` (default) graba
   desde el bus; con `capturar_bus=False` el bus solo aporta metadatos y los
   pasos los pone el cableado. Preferir el default: no requiere editar el bucle.

4. `derivar_ficheros` es HONESTA. Deriva ficheros solo de las tools cuyo
   protocolo de args lo dice sin ambiguedad. Para `ejecutar` devuelve lista
   VACIA: un comando de shell puede tocar cualquier cosa y parsearlo seria
   inventar. Una lista vacia es "no lo se"; una lista adivinada es una mentira
   que despues alguien usa para decidir.

Solo stdlib. No importa nada de cognia al importarse (el bus se importa perezoso
dentro de `suscribir`) para no crear ciclos y para que los tests corran secos.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Donde vive todo. Se resuelve EN CADA LLAMADA, no al importar: los tests
# apuntan COGNIA_FLUJOS_DIR a un tmp_path y el modulo ya puede estar importado
# por otro test (leer el env al importar es el bug clasico de "el test pasa
# solo y falla dentro de la suite").
# ---------------------------------------------------------------------------

def dir_base() -> Path:
    """Raiz de los flujos. COGNIA_FLUJOS_DIR la reemplaza entera."""
    crudo = os.environ.get("COGNIA_FLUJOS_DIR", "").strip()
    if crudo:
        return Path(crudo).expanduser()
    return Path.home() / ".cognia" / "flujos"


def dir_grabaciones() -> Path:
    return dir_base() / "grabaciones"


def ruta_de(grabacion_id: str) -> Path:
    return dir_grabaciones() / f"{_id_seguro(grabacion_id)}.jsonl"


# Un id que llega de afuera JAMAS se concatena crudo a una ruta: '../../x' es
# escritura fuera del directorio. Se recorta al conjunto seguro y punto.
_RE_ID_MALO = re.compile(r"[^A-Za-z0-9._-]")


def _id_seguro(grabacion_id: str) -> str:
    limpio = _RE_ID_MALO.sub("_", (grabacion_id or "").strip())
    return limpio[:120] or "sin_id"


# ---------------------------------------------------------------------------
# La trayectoria.
# ---------------------------------------------------------------------------

@dataclass
class Grabacion:
    """Una sesion de grabado con sus pasos. Es un REGISTRO de hechos: incluye
    los pasos que fallaron y el `ok` real del cierre."""
    id: str = ""
    titulo: str = ""
    tarea: str = ""
    workspace: str = ""
    ts_inicio: float = 0.0
    ts_fin: float = 0.0
    ok: bool = False
    resultado: str = ""
    # True cuando el fichero tiene su linea de cierre. False = la grabacion
    # murio a la mitad (crash, timeout, ctrl-C) y lo que hay son los pasos que
    # alcanzaron a escribirse. La diferencia importa: una grabacion a medias no
    # es "un flujo que funciono".
    cerrada: bool = False
    # Cuantas lineas del fichero no se pudieron leer (JSON roto, o cortado a
    # mitad de escritura). Se REPORTA en vez de silenciarse: un consumidor que
    # ve lineas_malas > 0 sabe que la trayectoria puede tener agujeros.
    lineas_malas: int = 0
    pasos: list = field(default_factory=list)
    ruta: str = ""

    def duracion_s(self) -> float:
        if self.ts_fin and self.ts_inicio:
            return max(0.0, self.ts_fin - self.ts_inicio)
        return 0.0

    def a_dict(self) -> dict:
        return {
            "id": self.id, "titulo": self.titulo, "tarea": self.tarea,
            "workspace": self.workspace, "ts_inicio": self.ts_inicio,
            "ts_fin": self.ts_fin, "ok": self.ok, "resultado": self.resultado,
            "cerrada": self.cerrada, "lineas_malas": self.lineas_malas,
            "duracion_s": self.duracion_s(), "pasos": list(self.pasos),
            "ruta": self.ruta,
        }


# ---------------------------------------------------------------------------
# Estado del proceso: que grabaciones estan ABIERTAS ahora mismo.
# ---------------------------------------------------------------------------

_lock = threading.RLock()
# id -> {"n": <contador de pasos>, "capturar_bus": bool, "ruta": str,
#        "titulo": str, "tarea": str, "workspace": str, "ts_inicio": float}
_abiertas: dict = {}
_suscrito = False


def _escribir_linea(ruta: Path, obj: dict) -> bool:
    """Append de UNA linea JSON con flush. Devuelve si se pudo; NO lanza: esto
    corre en el camino caliente del agente y una grabacion rota jamas puede
    tumbar la tarea del usuario."""
    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        # open/write/close por linea: mas syscalls, pero el fichero queda
        # consistente en disco aunque el proceso muera en el paso siguiente,
        # que es justo la razon de ser del formato.
        with open(ruta, "a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
            f.flush()
        return True
    except Exception:
        return False


def iniciar(titulo: str = "", tarea: str = "", workspace: str = "",
            capturar_bus: bool = True) -> str:
    """Abre una grabacion y escribe su cabecera. Devuelve el id.

    capturar_bus=True (default): los pasos los pone el suscriptor del bus (no
    hay que editar el bucle, pero los args llegan recortados a 120 chars).
    capturar_bus=False: los pasos los pone el cableado con `registrar_paso`.
    Ver la decision 3 de la cabecera: NO se mezclan.
    """
    # id ordenable por nombre (el listado sale cronologico sin abrir nada) +
    # sufijo aleatorio, porque dos tareas pueden arrancar el mismo segundo.
    gid = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    ts = time.time()
    ruta = ruta_de(gid)
    cabecera = {
        "tipo": "cabecera", "id": gid, "titulo": (titulo or "").strip(),
        "tarea": (tarea or "").strip(), "workspace": (workspace or "").strip(),
        "ts_inicio": ts, "version": 1,
    }
    _escribir_linea(ruta, cabecera)
    with _lock:
        _abiertas[gid] = {
            "n": 0, "capturar_bus": bool(capturar_bus), "ruta": str(ruta),
            "titulo": cabecera["titulo"], "tarea": cabecera["tarea"],
            "workspace": cabecera["workspace"], "ts_inicio": ts,
        }
    return gid


def abiertas() -> list:
    """Ids de las grabaciones abiertas en ESTE proceso (la mas nueva al final)."""
    with _lock:
        return list(_abiertas.keys())


def grabando() -> bool:
    with _lock:
        return bool(_abiertas)


def registrar_paso(grabacion_id: str, tool: str, args: str = "",
                   ok: bool = True, resumen_resultado: str = "",
                   duracion_s: float = 0.0, paso_agente: int = 0,
                   via_bus: bool = False):
    """Agrega UN paso a una grabacion abierta. Devuelve el paso grabado (dict),
    o None si el id no esta abierto. No lanza: es instrumentacion.

    `args` COMPLETO cuando lo llama el cableado desde el bucle; recortado a 120
    chars cuando viene del bus (por eso `via_bus` viaja dentro del paso).
    """
    with _lock:
        estado = _abiertas.get(grabacion_id)
        if estado is None:
            return None
        estado["n"] += 1
        n = estado["n"]
        ruta = Path(estado["ruta"])

    args = args or ""
    tool = (tool or "").strip()
    resumen = resumen_resultado or ""
    paso = {
        "tipo": "paso",
        "n": n,
        "tool": tool,
        "args": args,
        "ok": bool(ok),
        "resumen_resultado": resumen,
        "duracion_s": round(float(duracion_s or 0.0), 4),
        "ficheros_tocados": derivar_ficheros(args, tool),
        "comando": derivar_comando(args, tool),
        "exit_code": derivar_exit_code(resumen, tool),
        # El numero de paso DEL AGENTE (el que emite loop.py): no coincide con
        # `n` -- el agente puede llamar dos tools en el mismo paso, y la
        # grabacion puede haber empezado a mitad de tarea -- y las dos cuentas
        # hacen falta para leer la trayectoria.
        "paso_agente": int(paso_agente or 0),
        "via_bus": bool(via_bus),
        "ts": time.time(),
    }
    _escribir_linea(ruta, paso)
    return paso


def cerrar(grabacion_id: str, resultado: str = "", ok: bool = True) -> str:
    """Escribe la linea de cierre y saca la grabacion de las abiertas.
    Devuelve la ruta del fichero ("" si el id no estaba abierto)."""
    with _lock:
        estado = _abiertas.pop(grabacion_id, None)
    if estado is None:
        return ""
    ruta = Path(estado["ruta"])
    _escribir_linea(ruta, {
        "tipo": "cierre", "ts_fin": time.time(),
        "resultado": resultado or "", "ok": bool(ok),
        "pasos": estado["n"],
    })
    return str(ruta)


def anotar(grabacion_id: str, campo: str, valor) -> bool:
    """Corrige un campo de cabecera DESPUES de abrir (titulo/tarea/workspace).

    POR QUE EXISTE: el fichero es append-only, asi que la cabecera no se puede
    reescribir; pero el titulo real de una grabacion suele conocerse DESPUES
    (la tarea llega por TareaInicio cuando el agente arranca, no cuando el
    usuario dijo "grabame esto"). Se appendea una anotacion y `cargar()` aplica
    la ULTIMA que vea. Cero reescritura, cero perdida.
    """
    if campo not in ("titulo", "tarea", "workspace"):
        return False
    with _lock:
        estado = _abiertas.get(grabacion_id)
        ruta = Path(estado["ruta"]) if estado else ruta_de(grabacion_id)
        if estado is not None:
            estado[campo] = str(valor)
    return _escribir_linea(ruta, {"tipo": "anotacion", "campo": campo,
                                  "valor": str(valor), "ts": time.time()})


# ---------------------------------------------------------------------------
# Lectura. Tolerante a ficheros a medias: ese es el caso NORMAL, no el raro.
# ---------------------------------------------------------------------------

def cargar(grabacion_id: str):
    """Lee una grabacion del disco. Devuelve Grabacion, o None si no existe.

    Una linea que no parsea se cuenta en `lineas_malas` y se SALTA: un corte a
    mitad de escritura deja exactamente eso (media linea JSON), y perder la
    trayectoria entera por culpa del ultimo paso seria absurdo. Si la rota es
    la cabecera, se devuelve igual lo que se pueda leer, con cerrada=False.
    """
    ruta = ruta_de(grabacion_id)
    if not ruta.exists():
        return None
    g = Grabacion(id=_id_seguro(grabacion_id), ruta=str(ruta))
    try:
        crudo = ruta.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None
    for linea in crudo.splitlines():
        linea = linea.strip()
        if not linea:
            continue
        try:
            obj = json.loads(linea)
        except Exception:
            g.lineas_malas += 1
            continue
        if not isinstance(obj, dict):
            g.lineas_malas += 1
            continue
        tipo = obj.get("tipo")
        if tipo == "cabecera":
            g.id = obj.get("id") or g.id
            g.titulo = obj.get("titulo", "")
            g.tarea = obj.get("tarea", "")
            g.workspace = obj.get("workspace", "")
            g.ts_inicio = float(obj.get("ts_inicio") or 0.0)
        elif tipo == "paso":
            g.pasos.append(obj)
        elif tipo == "anotacion":
            campo = obj.get("campo")
            if campo in ("titulo", "tarea", "workspace"):
                setattr(g, campo, obj.get("valor", ""))
        elif tipo == "cierre":
            g.cerrada = True
            g.ts_fin = float(obj.get("ts_fin") or 0.0)
            g.resultado = obj.get("resultado", "")
            g.ok = bool(obj.get("ok"))
        else:
            # Linea con JSON valido pero de un tipo que no conocemos: cuenta
            # como mala igual. Callarla haria que un formato futuro se leyera
            # como "grabacion sin pasos" en vez de como "no la entiendo".
            g.lineas_malas += 1
    return g


def listar() -> list:
    """Resumen de todas las grabaciones en disco, la mas nueva primero."""
    d = dir_grabaciones()
    if not d.is_dir():
        return []
    out = []
    for f in sorted(d.glob("*.jsonl")):
        g = cargar(f.stem)
        if g is None:
            continue
        out.append({
            "id": g.id, "titulo": g.titulo, "tarea": g.tarea,
            "workspace": g.workspace, "ts_inicio": g.ts_inicio,
            "ts_fin": g.ts_fin, "ok": g.ok, "cerrada": g.cerrada,
            "pasos": len(g.pasos), "lineas_malas": g.lineas_malas,
            "duracion_s": g.duracion_s(), "ruta": g.ruta,
        })
    out.sort(key=lambda d_: (d_.get("ts_inicio") or 0.0, d_.get("id") or ""),
             reverse=True)
    return out


def borrar(grabacion_id: str) -> bool:
    """Borra el fichero de una grabacion. False si no existia."""
    with _lock:
        _abiertas.pop(grabacion_id, None)
    ruta = ruta_de(grabacion_id)
    try:
        if not ruta.exists():
            return False
        ruta.unlink()
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Derivaciones sobre el PROTOCOLO DE ARGS del repo (cognia/agent/tools.py).
# Las tools reciben un string, no un dict: 'ruta | contenido', 'clave=valor'.
# ---------------------------------------------------------------------------

# offset=/limit= de leer_archivo y timeout=/cwd= de ejecutar: van al FINAL, en
# cualquier orden, y cualquiera puede faltar (ver _RE_LEER_KV/_RE_EJEC_KV en
# tools.py, que es de donde sale esta forma).
_RE_KV_COLA = re.compile(r"\|?\s*\b(offset|limit|timeout|cwd)\s*=\s*\S+\s*$",
                         re.IGNORECASE)

# Tools cuyo PRIMER campo (antes del '|') es la ruta que tocan.
_TOOLS_RUTA_ANTES_PIPE = ("escribir_archivo", "editar_archivo",
                          "apendar_archivo")


def _limpiar_ruta(crudo: str) -> str:
    return (crudo or "").strip().strip("\"'").strip()


def _sin_kv_cola(crudo: str) -> str:
    """Quita las claves 'clave=valor' pegadas al final (pueden ser varias)."""
    txt = (crudo or "").strip()
    while True:
        m = _RE_KV_COLA.search(txt)
        if not m:
            return txt.strip()
        txt = txt[:m.start()].rstrip().rstrip("|").rstrip()


def derivar_ficheros(args: str, tool: str) -> list:
    """Que ficheros toca esta llamada, segun el protocolo de args de la tool.

    HONESTA POR DISENO: si el protocolo no lo dice sin ambiguedad devuelve []
    (que significa "no lo se") y NUNCA adivina. Caso de manual: `ejecutar`
    devuelve [] siempre -- un comando de shell puede tocar cualquier cosa, y
    parsear shell para afirmar lo contrario seria inventarse un dato que
    despues alguien usaria para decidir.
    """
    tool = (tool or "").strip()
    crudo = args or ""
    if not tool or not crudo.strip():
        return []

    if tool == "leer_archivo":
        # 'leer_archivo <path> [offset=N] [limit=M]'. La tool ademas tolera un
        # '|' colgando (structure.auto_fix se lo mete), asi que se corta ahi.
        resto = _sin_kv_cola(crudo).split("|")[0]
        ruta = _limpiar_ruta(resto)
        return [ruta] if ruta else []

    if tool in _TOOLS_RUTA_ANTES_PIPE:
        # 'ruta | contenido'. Sin '|' la llamada es invalida para la tool (te
        # devuelve "ERROR: formato"), asi que tampoco hay nada fiable que
        # derivar: no se inventa la ruta a partir del texto suelto.
        if "|" not in crudo:
            return []
        ruta = _limpiar_ruta(crudo.split("|", 1)[0])
        return [ruta] if ruta else []

    if tool == "borrar_archivo":
        # 'borrar_archivo <path>' y nada mas.
        ruta = _limpiar_ruta(crudo)
        return [ruta] if ruta else []

    if tool == "tests":
        # 'tests <ruta>': la ruta es un fichero o dir REAL que la corrida lee.
        ruta = _limpiar_ruta(crudo)
        return [ruta] if ruta else []

    if tool in ("ejecutar", "ejecutar_fondo"):
        return []

    # Toda tool desconocida cae aca: [] = "no lo se".
    return []


def derivar_comando(args: str, tool: str) -> str:
    """El comando de shell, solo para las tools que lo reciben. '' en el resto.

    En `ejecutar` las claves timeout=/cwd= van DESPUES del comando y no forman
    parte de el (ver _partir_ejec en tools.py), asi que se recortan.
    """
    if (tool or "").strip() not in ("ejecutar", "ejecutar_fondo"):
        return ""
    return _sin_kv_cola(args or "")


# 'RESULTADO ejecutar (exit 3): ...' / 'RESULTADO ejecutar: ...' lo escribe
# _shell(), que es lo que usan ejecutar, ejecutar_fondo y tests. El bucle emite
# resumen=resultado[:200], asi que esa cabecera SIEMPRE cabe en el evento.
_RE_EXIT = re.compile(r"^RESULTADO ejecutar(?:\s*\(exit\s*(-?\d+)\))?\s*:")


def derivar_exit_code(resumen_resultado: str, tool: str = ""):
    """El exit code que declara el resultado, o None si no lo declara.

    None NO es 0: 'ERROR: timeout tras 30s' y 'bloqueado por el sentinel' no
    tienen exit code, y contarlos como 0 seria afirmar que el comando salio
    bien. El `tool` se acepta y se ignora a proposito: el que manda es el texto
    del resultado, porque es el unico que lo sabe.
    """
    txt = (resumen_resultado or "").strip()
    if not txt:
        return None
    m = _RE_EXIT.match(txt)
    if not m:
        return None
    return int(m.group(1)) if m.group(1) is not None else 0


# ---------------------------------------------------------------------------
# Enganche al bus de eventos (cognia/ux/events.py). Graba SIN tocar el bucle.
# ---------------------------------------------------------------------------

def _on_evento(evento) -> None:
    """Suscriptor del bus. NO LANZA (el bus ya traga excepciones, pero un
    suscriptor que revienta en cada evento seria un coste silencioso)."""
    try:
        tipo = type(evento).__name__
        if tipo == "ToolFin":
            with _lock:
                destinos = [gid for gid, e in _abiertas.items()
                            if e.get("capturar_bus")]
            for gid in destinos:
                registrar_paso(
                    gid,
                    tool=getattr(evento, "tool", ""),
                    # RECORTADO A 120 CHARS por loop.py:735. Ver decision 2.
                    args=getattr(evento, "args", ""),
                    ok=bool(getattr(evento, "ok", True)),
                    resumen_resultado=getattr(evento, "resumen", ""),
                    duracion_s=float(getattr(evento, "duracion_s", 0.0) or 0.0),
                    paso_agente=int(getattr(evento, "paso", 0) or 0),
                    via_bus=True,
                )
        elif tipo == "TareaInicio":
            # La tarea REAL del agente. Se anota solo si la grabacion arranco
            # SIN tarea (el usuario dijo "grabame esto" antes de escribirla):
            # pisar una tarea que el cableado ya paso seria perder informacion.
            tarea = (getattr(evento, "tarea", "") or "").strip()
            if not tarea:
                return
            with _lock:
                destinos = [gid for gid, e in _abiertas.items()
                            if e.get("capturar_bus") and not e.get("tarea")]
            for gid in destinos:
                anotar(gid, "tarea", tarea)
    except Exception:
        pass


def suscribir() -> bool:
    """Engancha el grabador al bus de eventos. Idempotente.

    Devuelve False si el bus no esta disponible (import fallido): el grabador
    sigue siendo usable via `registrar_paso`, solo que sin captura automatica.
    """
    global _suscrito
    with _lock:
        if _suscrito:
            return True
    try:
        from cognia.ux import events as _ev
        _ev.suscribir(_on_evento)
    except Exception:
        return False
    with _lock:
        _suscrito = True
    return True


def desuscribir() -> bool:
    """Desengancha del bus. Idempotente. NO cierra las grabaciones abiertas:
    cerrarlas es una decision del cableado, no un efecto colateral de dejar de
    escuchar."""
    global _suscrito
    with _lock:
        if not _suscrito:
            return True
    try:
        from cognia.ux import events as _ev
        _ev.desuscribir(_on_evento)
    except Exception:
        return False
    with _lock:
        _suscrito = False
    return True
