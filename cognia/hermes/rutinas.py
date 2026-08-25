# -*- coding: utf-8 -*-
"""
cognia/hermes/rutinas.py
========================
RUTINAS PROGRAMADAS: correr un prompt (y/o un script) a una hora, cada tanto o
por expresion cron, sin que el dueno este delante.

POR QUE EXISTE (2026-08-18): Cognia sabe correr tareas cuando se lo piden, pero
no sabe correrlas SOLA. Hermes Agent lleva esto en produccion desde marzo
(`cron/jobs.py`, `cron/scheduler.py`, `cron/executions.py`; el documento
`hermes-already-has-routines.md` compara el mecanismo con las Routines de
Anthropic). Este modulo destila el mecanismo REAL de ahi, con stdlib pura.

QUE SE DESTILO, Y DE DONDE (todo leido, no imaginado):

- Modelo de datos en un JSON unico (Hermes `cron/jobs.py:85` JOBS_FILE =
  cron/jobs.json; `create_job` en :1246 arma el registro con schedule,
  next_run_at, last_run_at, last_status, last_error, repeat, enabled, state).
- `parse_schedule` con sus CUATRO formas (`cron/jobs.py:564`): duracion
  one-shot ('30m'), intervalo ('every 30m'), cron de 5 campos, e ISO one-shot.
  Aqui el parser de cron es PROPIO (Hermes exige croniter, `jobs.py:52
  _ensure_croniter`; nosotros no metemos dependencias) y esta testeado campo a
  campo, incluidas listas '1,3', rangos '1-5' y pasos '*/5'.
- Ledger de ejecuciones con TRES estados terminales y CERO reintentos
  automaticos (`cron/executions.py`: _TERMINAL_STATES = completed/failed/
  unknown; su docstring dice literalmente "it is not a retry queue"). Aqui el
  almacen es un JSONL append-only en vez de SQLite: mismo contrato (un estado
  terminal no se reescribe), sin fichero binario que pueda quedar bloqueado.
- 'desconocida' SOLO cuando se PRUEBA que el proceso dueno murio: Hermes guarda
  pid + process_started_at y compara ambos (`executions.py::_owner_is_live`),
  y su comentario "fail safe: inability to prove death must not rewrite state"
  es la regla. DIVERGENCIA DELIBERADA: Hermes, cuando no tiene tiempo de
  arranque guardado, decide `return pid == os.getpid()`, o sea da por muerto
  un pid ajeno que SI existe. Aqui eso se considera "no demostrado" y la
  ejecucion se deja como esta. Motivo: el pid se reutiliza, y marcar
  'desconocida' a un proceso vivo es exactamente la mentira que el estado
  'desconocida' existe para evitar. Ademas se guarda la MAQUINA: un registro
  de otra maquina nunca es demostrable desde aqui.
- Los tres ficheros atomicos de liveness (`cron/jobs.py:868
  record_ticker_heartbeat`, :896 _epoch_file_age, :942 record_ticker_error):
  `heartbeat` (el tick itero), `ultimo_exito` (el tick itero SIN romperse) y
  `ultimo_error` (por que se rompio). Son dos senales distintas a proposito:
  un tick que falla cada vuelta mantendria fresco el heartbeat y mentiria
  diciendo "sano" (incidentes #32612/#32895 de Hermes).
- Timeout por INACTIVIDAD, no wall-clock (`cron/scheduler.py:3510`): una
  rutina puede tardar horas si esta trabajando; lo que se mata es la que lleva
  N segundos SIN dar senales. Aqui `correr_agente_fn` puede aceptar un
  parametro `latir` (se le pasa solo si su firma lo admite) para marcar
  actividad; si no lo acepta, el limite degrada a wall-clock y se dice.
- Modo sin agente (`no_agent`, `cron/scheduler.py:2793`): el script ES la
  rutina, su stdout se entrega tal cual, stdout vacio = silencio, y fallo del
  script = alerta entregada (un vigilante que falla en silencio es el peor
  caso). Aqui es `despertar_agente=False`.
- Puerta wakeAgent (`cron/scheduler.py:2405 _parse_wake_gate`, portado a su
  vez de nanoclaw #1232): si la ULTIMA linea no vacia del stdout es un JSON
  con {"wakeAgent": false}, no se llama al agente. Cualquier otra cosa
  (no-JSON, sin la clave, o true) = despertar.
- Inyeccion de script (`cron/scheduler.py:2455`): el stdout del script se
  antepone al prompt como bloque de contexto; si el script fallo se antepone
  el error para que el agente lo reporte; si el stdout esta VACIO no se llama
  al modelo (nada que analizar).
- Contrato [SILENT] (`cron/scheduler.py:290` + `gateway/response_filters.py:73
  is_autonomous_silence_response`): marcas [SILENT] / SILENT / NO_REPLY /
  NO REPLY. Suprime la ENTREGA cuando la marca es la respuesta entera, ocupa
  ella sola la primera o la ultima linea, o abre la respuesta en su forma con
  corchetes. Una marca a mitad de frase se ENTREGA (el informe legitimo que
  dice "pense en quedarme [SILENT] pero...", incidentes #51438/#46917). Se
  anade la simetrica: '[SILENT]' cerrando la linea tambien suprime, porque el
  contrato pedido dice "empieza o termina con".
- Suprimir NO es perder: la supresion se registra en el ledger
  (`suprimido`) y el documento de la corrida se guarda en `salidas/`, igual
  que Hermes guarda el output aunque no lo entregue (`save_job_output`,
  `jobs.py:2435`).

LO QUE ESTE MODULO NO HACE (limites declarados):
- NO se demoniza y NO abre hilos de fondo por su cuenta: expone `tick()`. Que
  lo llame un hilo del REPL o una tarea programada de Windows lo decide el
  cableado (ver seccion "CABLEADO" abajo).
- NO entrega. `entregar` es una ETIQUETA de canal que viaja en el informe;
  quien manda a consola/Telegram/fichero es el integrador. Asi este modulo se
  prueba entero sin red.
- NO llama al modelo: `correr_agente_fn` se INYECTA. Firma esperada:
  `fn(prompt: str, rutina: dict) -> str`, y opcionalmente
  `fn(prompt, rutina, latir=<callable>)` si quiere el timeout por inactividad
  de verdad.
- NO hay reintentos automaticos, por diseno (regla de Hermes): una rutina que
  fallo se vuelve a intentar en su SIGUIENTE horario, no antes.
- Un proceso a la vez sobre el almacen. Hay lock de hilos dentro del proceso y
  escritura atomica (tmp + os.replace), pero NO lock entre procesos: dos
  Cognias con el mismo COGNIA_RUTINAS_DIR pueden pisarse `rutinas.json`. El
  ledger si aguanta (append de una linea).
- El cron usa hora local con offset fijo; en el salto de horario de verano la
  proxima corrida puede desplazarse una hora.

ALMACEN (override con COGNIA_RUTINAS_DIR, leido en CADA llamada para que los
tests aislen con tmp_path):

    ~/.cognia/rutinas/rutinas.json          las rutinas (lista JSON)
    ~/.cognia/rutinas/ejecuciones.jsonl     ledger append-only
    ~/.cognia/rutinas/heartbeat             epoch del ultimo tick
    ~/.cognia/rutinas/ultimo_exito          epoch del ultimo tick sin romperse
    ~/.cognia/rutinas/ultimo_error          epoch + mensaje del ultimo fallo
    ~/.cognia/rutinas/scripts/              scripts permitidos (jaula)
    ~/.cognia/rutinas/salidas/<nombre>/     documentos de cada corrida

CABLEADO (lo hace el orquestador; este modulo no toca cli.py):

    from cognia.hermes import rutinas

    def _agente_para_rutina(prompt, rutina, latir=None):
        # _run_agent_task(ai, task, _print_fn, ...) -> str
        return _run_agent_task(ai, prompt, _print_line)

    informe = rutinas.tick(None, _agente_para_rutina)
    for corrida in informe["corridas"]:
        if corrida["entregado"]:
            _print_line(corrida["salida"])
"""

from __future__ import annotations

import inspect
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import uuid
from datetime import datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Constantes (los defaults salen de Hermes; se dice de donde)
# ---------------------------------------------------------------------------

# Hermes cron/jobs.py:116 ONESHOT_GRACE_SECONDS: un one-shot creado unos
# segundos DESPUES de su minuto sigue corriendo en el siguiente tick.
_GRACIA_UNA_VEZ = 120

# Hermes cron/scheduler.py:2096 _DEFAULT_SCRIPT_TIMEOUT = 3600.
_TIMEOUT_SCRIPT_DEF = 3600

# Hermes cron/scheduler.py:3520 (HERMES_CRON_TIMEOUT, default 600s, 0 = sin
# limite). Es INACTIVIDAD, no duracion total.
_INACTIVIDAD_DEF = 600.0

# Cada cuanto se comprueba la inactividad mientras el agente trabaja.
_SONDEO_AGENTE = 0.25

# Estados TERMINALES del ledger. Son estos tres y solo estos: Hermes
# cron/executions.py:22 _TERMINAL_STATES = ("completed","failed","unknown").
ESTADOS_TERMINALES = ("completada", "fallida", "desconocida")

# Estados no terminales (una ejecucion abierta).
_ESTADOS_ABIERTOS = ("reclamada", "corriendo")

# gateway/response_filters.py:20 LIVE_GATEWAY_SILENT_MARKERS.
_MARCAS_SILENCIO = frozenset({"[SILENT]", "SILENT", "NO_REPLY", "NO REPLY"})

# Documentos de corrida que se conservan por rutina (Hermes
# _CRON_OUTPUT_DEFAULT_KEEP = 50, cron/jobs.py:2392).
_MAX_SALIDAS = 50

# Lineas del ledger que se conservan al podar (Hermes MAX_TERMINAL_EXECUTIONS
# = 1000; aqui se cuentan LINEAS porque el almacen es un JSONL).
_MAX_LINEAS_LEDGER = 4000

_CLASES_HORARIO = ("una_vez", "intervalo", "cron")

# Canales de ENTREGA conocidos (etiqueta que viaja en el informe; este modulo
# no entrega). "consola" es el del REPL; "inbox" existe desde el modo BOTS
# (Hermes Bot Mode, docs/user-guide/bot-mode: las rutinas de un bot caen en
# su chat canonico y el dueno las ve en su bandeja, no en una consola que
# puede no estar abierta). No se rechazan otros valores: un integrador puede
# tener su canal (telegram, fichero) y la etiqueta es suya.
CANALES_ENTREGA = ("consola", "inbox")

_RE_NOMBRE = re.compile(r"^[A-Za-z0-9_. -]{1,64}$")

_RE_DURACION = re.compile(
    r"^(\d+)\s*(m|min|mins|minuto|minutos|minute|minutes|"
    r"h|hr|hrs|hora|horas|hour|hours|"
    r"d|dia|dias|day|days)$"
)

# Identidad de ESTE proceso: una ejecucion abierta por nosotros nunca se marca
# 'desconocida' (Hermes cron/executions.py:25 _PROCESS_ID).
_PROCESO_ID = uuid.uuid4().hex
_MAQUINA = platform.node() or "?"

# Lock de hilos del almacen. No es lock entre procesos (ver limites).
_LOCK = threading.RLock()


# ---------------------------------------------------------------------------
# Ubicacion del almacen
# ---------------------------------------------------------------------------

def dir_rutinas() -> Path:
    """Raiz del almacen; COGNIA_RUTINAS_DIR permite override (tests)."""
    override = os.environ.get("COGNIA_RUTINAS_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".cognia" / "rutinas"


def dir_scripts() -> Path:
    """Jaula de scripts. Un script fuera de aqui NO se ejecuta (Hermes hace lo
    mismo con HERMES_HOME/scripts, cron/scheduler.py:2233)."""
    return dir_rutinas() / "scripts"


def _dir_salidas() -> Path:
    return dir_rutinas() / "salidas"


def _fichero_rutinas() -> Path:
    return dir_rutinas() / "rutinas.json"


def _fichero_ledger() -> Path:
    return dir_rutinas() / "ejecuciones.jsonl"


def _asegurar_dirs() -> None:
    for d in (dir_rutinas(), dir_scripts(), _dir_salidas()):
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass


def _escribir_atomico(path: Path, texto: str) -> bool:
    """tmp + fsync + os.replace. Un corte a mitad deja el fichero ANTERIOR
    legible, nunca un JSON truncado. Devuelve exito; no lanza."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".rut_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                f.write(texto)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
            return True
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Tiempo
# ---------------------------------------------------------------------------

def _ahora() -> datetime:
    """Ahora con tzinfo de offset fijo (el del sistema)."""
    return datetime.now().astimezone()


def _aware(dt: datetime) -> datetime:
    """Un naive se interpreta como hora local. Asi `pendientes(datetime(...))`
    de un test funciona sin que el llamante tenga que fabricar tzinfo."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=_ahora().tzinfo)
    return dt


def _norm_ahora(ahora) -> datetime:
    if isinstance(ahora, datetime):
        return _aware(ahora)
    return _ahora()


def _desde_iso(texto):
    """ISO -> datetime aware, o None si no se puede leer (nunca lanza)."""
    if not texto or not isinstance(texto, str):
        return None
    try:
        return _aware(datetime.fromisoformat(texto.strip().replace("Z", "+00:00")))
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Parser de horarios (las CUATRO formas de Hermes parse_schedule)
# ---------------------------------------------------------------------------

def parse_duracion(texto: str) -> int:
    """'30m' -> 30, '2h' -> 120, '1d' -> 1440 (minutos). Lanza ValueError."""
    if not isinstance(texto, str):
        raise ValueError("Duracion invalida: se esperaba texto")
    m = _RE_DURACION.match(texto.strip().lower())
    if not m:
        raise ValueError(
            "Duracion invalida: %r. Usa '30m', '2h' o '1d'." % texto)
    valor = int(m.group(1))
    if valor <= 0:
        raise ValueError("Duracion invalida: %r (tiene que ser > 0)." % texto)
    unidad = m.group(2)[0]  # m | h | d
    return valor * {"m": 1, "h": 60, "d": 1440}[unidad]


def _campo_cron(txt: str, minimo: int, maximo: int, nombre: str):
    """Un campo cron -> (set de valores permitidos, es_comodin).

    Acepta '*', '*/N', 'a', 'a-b', 'a-b/N', 'a/N' y listas separadas por coma.
    Devolver ademas si el campo es comodin hace falta para la semantica
    dia-del-mes / dia-de-semana (ver _dia_coincide).
    """
    txt = (txt or "").strip()
    if not txt:
        raise ValueError("Campo cron vacio en '%s'" % nombre)
    valores = set()
    comodin = True
    for parte in txt.split(","):
        parte = parte.strip()
        if not parte:
            raise ValueError("Campo cron '%s' con item vacio: %r" % (nombre, txt))
        paso = 1
        if "/" in parte:
            base, _, paso_txt = parte.partition("/")
            base = base.strip()
            try:
                paso = int(paso_txt.strip())
            except ValueError:
                raise ValueError(
                    "Paso invalido en el campo '%s': %r" % (nombre, parte))
            if paso < 1:
                raise ValueError(
                    "Paso invalido en el campo '%s': %r (tiene que ser >= 1)"
                    % (nombre, parte))
        else:
            base = parte
        if base == "*":
            ini, fin = minimo, maximo
            # '*/2' NO es comodin: restringe. Importa para la semantica
            # dia-del-mes / dia-de-semana (ver _dia_coincide).
            if paso != 1:
                comodin = False
        elif "-" in base.lstrip("-"):
            ini_txt, _, fin_txt = base.partition("-")
            ini = _entero_cron(ini_txt, nombre, parte)
            fin = _entero_cron(fin_txt, nombre, parte)
            comodin = False
        else:
            ini = _entero_cron(base, nombre, parte)
            # 'a/N' significa desde a hasta el maximo con ese paso (croniter).
            fin = maximo if paso > 1 else ini
            comodin = False
        if ini < minimo or fin > maximo or ini > fin:
            raise ValueError(
                "Campo cron '%s' fuera de rango (%d-%d): %r"
                % (nombre, minimo, maximo, parte))
        valores.update(range(ini, fin + 1, paso))
    if not valores:
        raise ValueError("Campo cron '%s' no admite ningun valor: %r" % (nombre, txt))
    # El domingo se escribe 0 o 7. Se normaliza DESPUES de expandir el rango
    # para que '5-7' siga siendo viernes-sabado-domingo; normalizar antes lo
    # convertia en 0-5 (lunes a viernes), justo los dias contrarios.
    if nombre == "semana" and 7 in valores:
        valores.add(0)
    return valores, comodin


def _entero_cron(txt: str, nombre: str, parte: str) -> int:
    try:
        return int(txt.strip())
    except (ValueError, AttributeError):
        raise ValueError("Campo cron '%s' invalido: %r" % (nombre, parte))


def parse_cron(expr: str) -> dict:
    """Expresion de 5 campos -> conjuntos de valores. Lanza ValueError.

    Se escribe a mano a proposito: Hermes depende de croniter
    (cron/jobs.py:52) y una dependencia externa para cinco campos de enteros no
    se paga. Semantica estandar de Vixie cron: si dia-del-mes Y dia-de-semana
    estan ambos restringidos, coincide con CUALQUIERA de los dos (OR); si solo
    uno lo esta, manda ese.
    """
    if not isinstance(expr, str):
        raise ValueError("Expresion cron invalida: se esperaba texto")
    partes = expr.split()
    if len(partes) != 5:
        raise ValueError(
            "Expresion cron invalida %r: se esperan 5 campos "
            "(minuto hora dia mes semana)." % expr)
    minuto, _ = _campo_cron(partes[0], 0, 59, "minuto")
    hora, _ = _campo_cron(partes[1], 0, 23, "hora")
    dia, dia_libre = _campo_cron(partes[2], 1, 31, "dia")
    mes, _ = _campo_cron(partes[3], 1, 12, "mes")
    semana, semana_libre = _campo_cron(partes[4], 0, 7, "semana")
    return {
        "minuto": sorted(minuto),
        "hora": sorted(hora),
        "dia": sorted(dia),
        "mes": sorted(mes),
        "semana": sorted(semana),
        "dia_libre": bool(dia_libre),
        "semana_libre": bool(semana_libre),
    }


def _dia_coincide(campos: dict, dt: datetime) -> bool:
    if dt.month not in campos["mes"]:
        return False
    dow = dt.isoweekday() % 7          # cron: 0 = domingo
    en_dia = dt.day in campos["dia"]
    en_semana = dow in campos["semana"]
    if campos["dia_libre"] and campos["semana_libre"]:
        return True
    if campos["dia_libre"]:
        return en_semana
    if campos["semana_libre"]:
        return en_dia
    return en_dia or en_semana          # OR: semantica estandar de cron


def _siguiente_cron(campos: dict, desde: datetime):
    """Primer instante ESTRICTAMENTE posterior a `desde` que casa. None si no
    hay ninguno en 4 anos (p.ej. '0 0 30 2 *', el 30 de febrero)."""
    cursor = (desde + timedelta(minutes=1)).replace(second=0, microsecond=0)
    limite = cursor + timedelta(days=366 * 4)
    minutos = set(campos["minuto"])
    horas = set(campos["hora"])
    while cursor <= limite:
        if not _dia_coincide(campos, cursor):
            cursor = (cursor + timedelta(days=1)).replace(hour=0, minute=0)
            continue
        if cursor.hour not in horas:
            cursor = (cursor + timedelta(hours=1)).replace(minute=0)
            continue
        if cursor.minute not in minutos:
            cursor = cursor + timedelta(minutes=1)
            continue
        return cursor
    return None


def parse_horario(texto: str, ahora=None) -> dict:
    """Texto -> horario estructurado. Lanza ValueError con las 4 formas.

    Orden de reconocimiento identico al de Hermes (cron/jobs.py:564): primero
    'cada/every X', luego cron de 5 campos, luego ISO, y por ultimo duracion
    suelta. El orden importa: '30m' es one-shot y 'cada 30m' es intervalo.

    Devuelve dict con "clase" en (una_vez, intervalo, cron):
      una_vez  -> {"correr_en": ISO}
      intervalo-> {"minutos": int}
      cron     -> {"expr": str, "campos": {...}}
    """
    if not isinstance(texto, str) or not texto.strip():
        raise ValueError("Horario vacio.")
    ahora_dt = _norm_ahora(ahora)
    crudo = texto.strip()
    bajo = crudo.lower()

    # 1) intervalo: 'cada 30m' / 'every 30m'
    for prefijo in ("cada ", "every "):
        if bajo.startswith(prefijo):
            minutos = parse_duracion(crudo[len(prefijo):])
            return {
                "clase": "intervalo",
                "minutos": minutos,
                "texto": crudo,
                "display": "cada %dm" % minutos,
            }

    # 2) cron de 5 campos
    partes = crudo.split()
    if len(partes) == 5 and all(re.match(r"^[\d\*\-,/]+$", p) for p in partes):
        campos = parse_cron(crudo)
        return {
            "clase": "cron",
            "expr": crudo,
            "campos": campos,
            "texto": crudo,
            "display": crudo,
        }

    # 3) ISO one-shot anclado
    if "T" in crudo or re.match(r"^\d{4}-\d{2}-\d{2}", crudo):
        dt = _desde_iso(crudo)
        if dt is None:
            raise ValueError("Marca de tiempo invalida: %r" % crudo)
        return {
            "clase": "una_vez",
            "correr_en": dt.isoformat(),
            "texto": crudo,
            "display": "una vez el %s" % dt.strftime("%Y-%m-%d %H:%M"),
        }

    # 4) duracion suelta -> one-shot desde ahora
    try:
        minutos = parse_duracion(crudo)
    except ValueError:
        raise ValueError(
            "Horario invalido %r. Usa:\n"
            "  - Duracion: '30m', '2h', '1d' (una vez)\n"
            "  - Intervalo: 'cada 30m', 'every 2h'\n"
            "  - Cron de 5 campos: '0 2 * * *' (listas 1,3 rangos 1-5 pasos */5)\n"
            "  - Marca ISO: '2026-08-19T09:00' (una vez)" % crudo)
    return {
        "clase": "una_vez",
        "correr_en": (ahora_dt + timedelta(minutes=minutos)).isoformat(),
        "texto": crudo,
        "display": "una vez dentro de %s" % crudo,
    }


def _gracia(horario: dict, campos=None) -> float:
    """Cuanto puede llegar tarde una corrida y aun asi RECUPERARSE en vez de
    saltarse. Hermes _compute_grace_seconds (cron/jobs.py:738): medio periodo,
    acotado entre 120s y 2h. Sin esto, una rutina '*/5' parada un mes dispara
    una vez por tick hasta ponerse al dia (una tormenta, no una recuperacion).
    """
    minimo, maximo = 120.0, 7200.0
    clase = horario.get("clase")
    if clase == "intervalo":
        minutos = horario.get("minutos") or 1
        return max(minimo, min(minutos * 60 / 2.0, maximo))
    if clase == "cron" and isinstance(campos, dict):
        ref = _ahora()
        uno = _siguiente_cron(campos, ref)
        if uno is not None:
            dos = _siguiente_cron(campos, uno)
            if dos is not None:
                periodo = (dos - uno).total_seconds()
                return max(minimo, min(periodo / 2.0, maximo))
    return minimo


def siguiente(horario: dict, ultima_en=None, ahora=None):
    """Proxima corrida en ISO, o None si ya no hay mas.

    Hermes cron/jobs.py:772 compute_next_run. Detalles conservados:
    - one-shot: si ya corrio (`ultima_en`) no vuelve NUNCA; y solo es
      recuperable dentro de la gracia de 120s (_recoverable_oneshot_run_at).
    - intervalo/cron: la base es la ULTIMA corrida cuando existe, no el
      arranque del proceso, para que un reinicio no desplace el horario.
    - si esa base deja la proxima corrida MAS atrasada que la gracia, se
      adelanta al siguiente hueco desde ahora (la corrida perdida se pierde,
      pero no se dispara N veces seguidas para "recuperarla").
    """
    if not isinstance(horario, dict):
        return None
    ahora_dt = _norm_ahora(ahora)
    clase = horario.get("clase")

    if clase == "una_vez":
        if ultima_en:
            return None
        correr = _desde_iso(horario.get("correr_en"))
        if correr is None:
            return None
        if correr >= ahora_dt - timedelta(seconds=_GRACIA_UNA_VEZ):
            return correr.isoformat()
        return None

    if clase == "intervalo":
        minutos = horario.get("minutos")
        if not isinstance(minutos, int) or minutos <= 0:
            return None
        base = _desde_iso(ultima_en) or ahora_dt
        nxt = base + timedelta(minutes=minutos)
        if nxt < ahora_dt - timedelta(seconds=_gracia(horario)):
            nxt = ahora_dt + timedelta(minutes=minutos)
        return nxt.isoformat()

    if clase == "cron":
        campos = horario.get("campos")
        if not isinstance(campos, dict):
            try:
                campos = parse_cron(str(horario.get("expr") or ""))
            except ValueError:
                return None
        base = _desde_iso(ultima_en) or ahora_dt
        nxt = _siguiente_cron(campos, base)
        if nxt is None:
            return None
        if nxt < ahora_dt - timedelta(seconds=_gracia(horario, campos)):
            nxt = _siguiente_cron(campos, ahora_dt)
        return nxt.isoformat() if nxt is not None else None

    return None


# ---------------------------------------------------------------------------
# Almacen de rutinas (rutinas.json)
# ---------------------------------------------------------------------------

def _cargar() -> list:
    """Lista de rutinas. Un JSON ilegible devuelve [] en vez de romper el
    turno: la instrumentacion nunca mata al llamante."""
    path = _fichero_rutinas()
    try:
        crudo = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    try:
        datos = json.loads(crudo)
    except (ValueError, TypeError):
        return []
    if not isinstance(datos, list):
        return []
    return [r for r in datos if isinstance(r, dict) and r.get("nombre")]


def _guardar(rutinas: list) -> bool:
    _asegurar_dirs()
    return _escribir_atomico(
        _fichero_rutinas(), json.dumps(rutinas, ensure_ascii=False, indent=2) + "\n")


def _normaliza_workdir(workdir):
    if not workdir:
        return None
    try:
        return str(Path(str(workdir)).expanduser().resolve())
    except (OSError, ValueError):
        return None


def crear(nombre: str, horario: str, prompt: str, *, script=None,
          entregar: str = "consola", despertar_agente: bool = True,
          workdir=None, bot=None) -> dict:
    """Crea una rutina y la deja armada. Devuelve el registro.

    Lanza ValueError con el motivo cuando la configuracion no puede correr
    (nombre repetido, horario ilegible, one-shot ya pasado, sin agente y sin
    script). Es camino de CONFIGURACION, no camino caliente: aqui fallar
    ruidosamente es lo correcto; el que se calla es `tick`.

    `bot`: nombre del bot dueno de la rutina (modo BOTS: cada bot tiene su
    propio almacen via COGNIA_RUTINAS_DIR, asi que el campo es informativo y
    sale en listar() para que el roster y el remoto sepan de quien es; es el
    "[bot:<name>] <titulo>" con que Hermes etiqueta sus cron jobs). None =
    rutina del REPL global.
    """
    nombre = (nombre or "").strip()
    if not _RE_NOMBRE.match(nombre):
        raise ValueError(
            "Nombre invalido %r: 1-64 caracteres, letras, numeros, espacio, "
            "'.', '_' o '-' (se usa como carpeta de salidas)." % nombre)

    prompt = (prompt or "").strip() if isinstance(prompt, str) else ""
    script = (str(script).strip() or None) if script else None
    entregar = (entregar or "").strip() or "consola"
    despertar_agente = bool(despertar_agente)

    # Hermes cron/jobs.py:1345: no_agent sin script no es nada.
    if not despertar_agente and not script:
        raise ValueError(
            "despertar_agente=False exige script: sin agente y sin script no "
            "hay nada que correr.")
    if despertar_agente and not prompt:
        raise ValueError("Una rutina con agente necesita prompt.")

    ahora_dt = _ahora()
    parsed = parse_horario(horario, ahora=ahora_dt)
    proxima = siguiente(parsed, ultima_en=None, ahora=ahora_dt)
    if parsed["clase"] == "una_vez" and proxima is None:
        raise ValueError(
            "El instante pedido (%s) esta a mas de %ds en el pasado y no se "
            "puede programar." % (parsed.get("correr_en"), _GRACIA_UNA_VEZ))

    registro = {
        "nombre": nombre,
        "prompt": prompt,
        "script": script,
        "horario": parsed,
        "horario_txt": parsed.get("display", str(horario)),
        "entregar": entregar,
        "despertar_agente": despertar_agente,
        "workdir": _normaliza_workdir(workdir),
        "bot": (str(bot).strip() or None) if bot else None,
        "activa": True,
        "estado": "programada",
        "creada_en": ahora_dt.isoformat(),
        "proxima_en": proxima,
        "ultima_en": None,
        "ultimo_estado": None,
        "ultimo_detalle": None,
        "corridas": 0,
    }
    with _LOCK:
        rutinas = _cargar()
        if any(r.get("nombre") == nombre for r in rutinas):
            raise ValueError("Ya existe una rutina llamada %r." % nombre)
        rutinas.append(registro)
        if not _guardar(rutinas):
            raise ValueError(
                "No se pudo escribir %s (permisos o disco)." % _fichero_rutinas())
    return dict(registro)


def nombre_libre(base: str = "rutina") -> str:
    """'<base>-<N>' con N = mayor indice ya usado + 1 (1 si no hay ninguno).

    NO es len()+1: con rutina-1..3 y un rm de rutina-2, len()+1 daba
    'rutina-3', que existe, y crear() rechazaba TODAS las altas siguientes
    hasta borrar a mano (revision adversarial 2026-08-25, /bots rutina add).
    Solo cuentan los nombres con la forma exacta '<base>-<digitos>'; un
    nombre libre ('vigia') no mueve el contador.
    """
    base = (base or "rutina").strip() or "rutina"
    patron = re.compile(r"^%s-(\d+)$" % re.escape(base))
    mayor = 0
    for r in listar():
        m = patron.match(str(r.get("nombre", "")))
        if m:
            mayor = max(mayor, int(m.group(1)))
    return "%s-%d" % (base, mayor + 1)


def listar() -> list:
    """Rutinas guardadas, la de proxima corrida mas cercana primero."""
    with _LOCK:
        rutinas = _cargar()

    def _clave(r):
        dt = _desde_iso(r.get("proxima_en"))
        # Las sin proxima corrida van al final, no al principio.
        return (dt is None, dt or _ahora(), str(r.get("nombre") or ""))

    return sorted((dict(r) for r in rutinas), key=_clave)


def obtener(nombre: str):
    """Una rutina por nombre, o None."""
    nombre = (nombre or "").strip()
    with _LOCK:
        for r in _cargar():
            if r.get("nombre") == nombre:
                return dict(r)
    return None


def borrar(nombre: str) -> bool:
    """Borra la rutina. True si existia. El ledger NO se toca: el historial de
    lo que ya corrio sobrevive a la rutina."""
    nombre = (nombre or "").strip()
    with _LOCK:
        rutinas = _cargar()
        quedan = [r for r in rutinas if r.get("nombre") != nombre]
        if len(quedan) == len(rutinas):
            return False
        _guardar(quedan)
    return True


def pendientes(ahora=None) -> list:
    """Rutinas activas cuya proxima corrida ya llego (`proxima_en <= ahora`).

    Una rutina sin `proxima_en` NO esta pendiente: o termino (one-shot) o su
    horario no se pudo calcular, y en los dos casos dispararla seria inventar.
    """
    ahora_dt = _norm_ahora(ahora)
    listas = []
    with _LOCK:
        for r in _cargar():
            if not r.get("activa", True):
                continue
            prox = _desde_iso(r.get("proxima_en"))
            if prox is not None and prox <= ahora_dt:
                listas.append(dict(r))
    listas.sort(key=lambda r: (_desde_iso(r.get("proxima_en")) or ahora_dt,
                              str(r.get("nombre") or "")))
    return listas


def marcar_corrida(nombre: str, estado: str, detalle=None, ahora=None):
    """Cierra la corrida en el registro de la rutina y re-arma la siguiente.

    Hermes cron/jobs.py:1689 mark_job_run. Se conservan dos decisiones suyas:
    - un one-shot que ya corrio se desactiva (queda con estado 'completada');
      aqui NO se borra, para no perder el historial visible.
    - una rutina RECURRENTE que no logra calcular su proxima corrida queda
      'error' pero SIGUE ACTIVA (incidente #16265: desactivarla convertia un
      fallo de calculo en "ya termino" y el horario del dueno se apagaba solo).

    `estado` fuera de los tres terminales se registra como 'fallida' con el
    valor recibido en el detalle: esto corre despues de una corrida real y no
    puede tumbar el turno por un argumento mal escrito.
    """
    nombre = (nombre or "").strip()
    if estado not in ESTADOS_TERMINALES:
        detalle = "estado no terminal %r; se registra como fallida. %s" % (
            estado, detalle or "")
        estado = "fallida"
    ahora_dt = _norm_ahora(ahora)
    with _LOCK:
        rutinas = _cargar()
        for r in rutinas:
            if r.get("nombre") != nombre:
                continue
            r["ultima_en"] = ahora_dt.isoformat()
            r["ultimo_estado"] = estado
            r["ultimo_detalle"] = str(detalle) if detalle else None
            r["corridas"] = int(r.get("corridas") or 0) + 1
            horario = r.get("horario") or {}
            r["proxima_en"] = siguiente(
                horario, ultima_en=r["ultima_en"], ahora=ahora_dt)
            if r["proxima_en"] is None:
                if horario.get("clase") in ("cron", "intervalo"):
                    r["estado"] = "error"          # sigue activa a proposito
                else:
                    r["activa"] = False
                    r["estado"] = "completada"
            else:
                r["estado"] = "programada"
            _guardar(rutinas)
            return dict(r)
    return None


# ---------------------------------------------------------------------------
# Ledger de ejecuciones (append-only, tres estados terminales, cero reintentos)
# ---------------------------------------------------------------------------

def _anexar_ledger(registro: dict) -> bool:
    """Una linea JSON por transicion. El append de una linea corta es la
    escritura mas robusta que hay: no reescribe lo anterior, asi que un corte
    solo puede dejar la ULTIMA linea a medias (y esa se salta al leer)."""
    _asegurar_dirs()
    try:
        linea = json.dumps(registro, ensure_ascii=False) + "\n"
    except (TypeError, ValueError):
        return False
    try:
        with open(_fichero_ledger(), "a", encoding="utf-8", newline="\n") as f:
            f.write(linea)
        return True
    except OSError:
        return False


def _leer_ledger() -> list:
    """Todas las lineas legibles, en orden. Una linea corrupta se salta:
    perder una transicion es malo, perder el historial entero es peor."""
    try:
        crudo = _fichero_ledger().read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out = []
    for linea in crudo.splitlines():
        linea = linea.strip()
        if not linea:
            continue
        try:
            reg = json.loads(linea)
        except (ValueError, TypeError):
            continue
        if isinstance(reg, dict) and reg.get("id"):
            out.append(reg)
    return out


def _estados_efectivos() -> dict:
    """id -> ultima transicion escrita para ese id."""
    efectivo = {}
    for reg in _leer_ledger():
        efectivo[reg["id"]] = reg
    return efectivo


def ejecuciones(rutina=None, limite: int = 50) -> list:
    """Estado EFECTIVO de las ejecuciones, la mas nueva primero."""
    regs = list(_estados_efectivos().values())
    if rutina:
        regs = [r for r in regs if r.get("rutina") == rutina]
    regs.sort(key=lambda r: str(r.get("actualizada_en") or ""), reverse=True)
    return regs[:max(1, int(limite))]


def _podar_ledger() -> None:
    """Recorta el JSONL cuando se pasa de _MAX_LINEAS_LEDGER, conservando las
    ultimas. Se hace reescribiendo el fichero entero de forma atomica."""
    lineas = _leer_ledger()
    if len(lineas) <= _MAX_LINEAS_LEDGER:
        return
    recorte = lineas[-_MAX_LINEAS_LEDGER:]
    texto = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recorte)
    _escribir_atomico(_fichero_ledger(), texto)


def abrir_ejecucion(nombre: str, origen: str = "tick") -> dict:
    """Reclama un intento ANTES de que ocurra el efecto (Hermes
    create_execution). Guarda pid, arranque del proceso y maquina: son la
    unica prueba admisible de que el dueno murio."""
    pid = os.getpid()
    reg = {
        "id": uuid.uuid4().hex,
        "rutina": nombre,
        "origen": origen,
        "estado": "reclamada",
        "proceso": _PROCESO_ID,
        "pid": pid,
        "arranque": _arranque_proceso(pid),
        "maquina": _MAQUINA,
        "reclamada_en": _ahora().isoformat(),
        "actualizada_en": _ahora().isoformat(),
        "detalle": None,
        "suprimido": None,
    }
    _anexar_ledger(reg)
    return dict(reg)


def marcar_corriendo(ejecucion_id: str):
    """reclamada -> corriendo, una sola vez. None si ya no procede."""
    with _LOCK:
        actual = _estados_efectivos().get(ejecucion_id)
        if actual is None or actual.get("estado") != "reclamada":
            return None
        nuevo = dict(actual)
        nuevo["estado"] = "corriendo"
        nuevo["actualizada_en"] = _ahora().isoformat()
        _anexar_ledger(nuevo)
    return nuevo


def cerrar_ejecucion(ejecucion_id: str, estado: str, detalle=None,
                     suprimido=None):
    """Escribe un estado TERMINAL una sola vez.

    Un intento ya terminal no se reescribe (Hermes: "terminal attempts cannot
    be rewritten"). Devuelve el registro escrito, o None si no procedia.
    """
    if estado not in ESTADOS_TERMINALES:
        return None
    with _LOCK:
        actual = _estados_efectivos().get(ejecucion_id)
        if actual is None or actual.get("estado") not in _ESTADOS_ABIERTOS:
            return None
        nuevo = dict(actual)
        nuevo["estado"] = estado
        nuevo["detalle"] = str(detalle) if detalle else None
        nuevo["suprimido"] = str(suprimido) if suprimido else None
        nuevo["terminada_en"] = _ahora().isoformat()
        nuevo["actualizada_en"] = nuevo["terminada_en"]
        _anexar_ledger(nuevo)
        _podar_ledger()
    return nuevo


# --- prueba de muerte del proceso dueno -------------------------------------

def _pid_existe(pid: int):
    """True / False / None (= no se pudo determinar). None NUNCA se
    interpreta como muerto."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None
    if pid <= 0:
        return None
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            k32.OpenProcess.restype = wintypes.HANDLE
            h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if h:
                # Un handle abierto no basta: un proceso ya terminado sigue
                # siendo "abrible" mientras alguien conserve su handle. Se
                # comprueba el codigo de salida (STILL_ACTIVE = 259).
                codigo = wintypes.DWORD()
                ok = k32.GetExitCodeProcess(h, ctypes.byref(codigo))
                k32.CloseHandle(h)
                if not ok:
                    return None
                return codigo.value == 259
            err = ctypes.get_last_error()
            if err == 87:      # ERROR_INVALID_PARAMETER: ese pid no existe
                return False
            if err == 5:       # ERROR_ACCESS_DENIED: existe, pero no es nuestro
                return True
            return None
        except Exception:
            return None
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return None


def _arranque_proceso(pid: int):
    """Instante de arranque del proceso como entero comparable, o None.

    Es la mitad que falta de la prueba: el pid se REUTILIZA, asi que "existe un
    proceso con ese pid" no dice que sea el mismo. Sin este dato no hay prueba
    y el estado no se toca.
    """
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class _FILETIME(ctypes.Structure):
                _fields_ = [("dwLowDateTime", wintypes.DWORD),
                            ("dwHighDateTime", wintypes.DWORD)]

            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.OpenProcess.restype = wintypes.HANDLE
            h = k32.OpenProcess(0x1000, False, pid)
            if not h:
                return None
            creacion, salida, kernel, usuario = (_FILETIME(), _FILETIME(),
                                                 _FILETIME(), _FILETIME())
            ok = k32.GetProcessTimes(h, ctypes.byref(creacion),
                                     ctypes.byref(salida),
                                     ctypes.byref(kernel),
                                     ctypes.byref(usuario))
            k32.CloseHandle(h)
            if not ok:
                return None
            return (creacion.dwHighDateTime << 32) | creacion.dwLowDateTime
        except Exception:
            return None
    try:
        crudo = Path("/proc/%d/stat" % pid).read_text(encoding="utf-8",
                                                      errors="replace")
        # El campo 2 (comm) puede llevar espacios y parentesis; se corta por el
        # ULTIMO ')'. starttime es el campo 22 contando desde 1.
        resto = crudo[crudo.rindex(")") + 1:].split()
        return int(resto[19])
    except Exception:
        return None


def _dueno_probado_muerto(reg: dict) -> bool:
    """True SOLO cuando se demuestra que el proceso que abrio esa ejecucion ya
    no esta. Cualquier duda devuelve False (fallo seguro)."""
    if reg.get("proceso") == _PROCESO_ID:
        return False                       # somos nosotros: esta viva
    if reg.get("maquina") != _MAQUINA:
        return False                       # otra maquina: indemostrable aqui
    pid = reg.get("pid")
    existe = _pid_existe(pid)
    if existe is None:
        return False                       # no se pudo comprobar
    if existe is False:
        return True                        # probado: ese pid ya no esta
    guardado = reg.get("arranque")
    actual = _arranque_proceso(pid)
    if guardado is None or actual is None:
        # Sin arranque no hay prueba. Hermes aqui da por muerto todo pid ajeno;
        # aqui NO, porque el pid se reutiliza (ver cabecera).
        return False
    return actual != guardado              # pid reutilizado: el dueno murio


def recuperar_interrumpidas() -> int:
    """Cierra como 'desconocida' las ejecuciones cuyo dueno se PROBO muerto.

    'desconocida' no es "fallo": es "no se sabe si el efecto ocurrio". Por eso
    NO se reintenta nada (Hermes: el ledger "is not a retry queue"): la rutina
    volvera a correr en su siguiente horario y ni un minuto antes.
    """
    cerradas = 0
    with _LOCK:
        for reg in list(_estados_efectivos().values()):
            if reg.get("estado") not in _ESTADOS_ABIERTOS:
                continue
            if not _dueno_probado_muerto(reg):
                continue
            nuevo = dict(reg)
            nuevo["estado"] = "desconocida"
            nuevo["detalle"] = (
                "El proceso dueno (pid %s) desaparecio antes de escribir un "
                "estado terminal; no se sabe si la corrida llego a tener "
                "efecto." % reg.get("pid"))
            nuevo["terminada_en"] = _ahora().isoformat()
            nuevo["actualizada_en"] = nuevo["terminada_en"]
            if _anexar_ledger(nuevo):
                cerradas += 1
        if cerradas:
            _podar_ledger()
    return cerradas


# ---------------------------------------------------------------------------
# Liveness: heartbeat / ultimo_exito / ultimo_error (tres ficheros atomicos)
# ---------------------------------------------------------------------------

def _escribir_epoch(path: Path) -> None:
    _asegurar_dirs()
    _escribir_atomico(path, str(time.time()))


def registrar_latido(exito: bool = False) -> None:
    """Marca que el tick ITERO; con exito=True marca ademas que itero SIN
    romperse. Son dos senales distintas a proposito: un tick que revienta cada
    vuelta mantendria fresco el heartbeat y diria "sano" (Hermes #32612)."""
    _escribir_epoch(dir_rutinas() / "heartbeat")
    if exito:
        _escribir_epoch(dir_rutinas() / "ultimo_exito")


def _edad(path: Path):
    try:
        return max(0.0, time.time() - float(
            path.read_text(encoding="utf-8").strip()))
    except Exception:
        return None


def edad_latido():
    """Segundos desde la ultima vuelta del tick, o None si no se sabe. None es
    'no se puede determinar', NO 'esta muerto'."""
    return _edad(dir_rutinas() / "heartbeat")


def edad_ultimo_exito():
    """Segundos desde el ultimo tick que termino sin romperse, o None."""
    return _edad(dir_rutinas() / "ultimo_exito")


def registrar_error_tick(mensaje: str) -> None:
    """Deja por escrito POR QUE fallo el ultimo tick. Sin esto, otro proceso
    solo puede ver que los marcadores estan rancios y adivinar (a Hermes le
    costo ~14h de ticks fallando por un jobs.json con dueno equivocado)."""
    _asegurar_dirs()
    _escribir_atomico(dir_rutinas() / "ultimo_error",
                      "%s\n%s\n" % (time.time(), str(mensaje).strip()))


def limpiar_error_tick() -> None:
    try:
        (dir_rutinas() / "ultimo_error").unlink()
    except OSError:
        pass


def ultimo_error_tick():
    """Mensaje del ultimo tick fallido, o None."""
    try:
        crudo = (dir_rutinas() / "ultimo_error").read_text(encoding="utf-8")
    except OSError:
        return None
    lineas = crudo.splitlines()
    if len(lineas) < 2:
        return None
    return "\n".join(lineas[1:]).strip() or None


# ---------------------------------------------------------------------------
# Script: jaula, interprete, timeout, puerta wakeAgent
# ---------------------------------------------------------------------------

def _timeout_script() -> int:
    crudo = os.environ.get("COGNIA_RUTINAS_SCRIPT_TIMEOUT", "").strip()
    if crudo:
        try:
            valor = int(float(crudo))
            if valor > 0:
                return valor
        except (ValueError, TypeError):
            pass
    return _TIMEOUT_SCRIPT_DEF


def _entorno_script() -> dict:
    """Copia del entorno SIN los secretos evidentes. Hermes pasa los procesos
    hijos por `_sanitize_subprocess_env` (SECURITY.md 2.3) para que un script
    de rutina no herede credenciales del proveedor."""
    fuera = ("API_KEY", "APIKEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD")
    return {k: v for k, v in os.environ.items()
            if not any(m in k.upper() for m in fuera)}


def correr_script(script: str, workdir=None, timeout=None):
    """(ok, salida). NUNCA lanza: el fallo viaja como texto para que se pueda
    reportar. La salida de un script que fallo incluye stderr.

    El script tiene que vivir bajo `dir_scripts()`: rutas relativas se resuelven
    ahi y las absolutas se VALIDAN contra ese directorio (Hermes bloquea igual
    el traversal y la ruta absoluta inyectada, cron/scheduler.py:2246).
    """
    _asegurar_dirs()
    jaula = dir_scripts().resolve()
    crudo = Path(str(script)).expanduser()
    try:
        destino = (crudo if crudo.is_absolute() else (jaula / crudo)).resolve()
    except (OSError, ValueError) as exc:
        return False, "Ruta de script invalida %r: %s" % (script, exc)
    try:
        destino.relative_to(jaula)
    except ValueError:
        return False, (
            "Bloqueado: el script queda fuera de la jaula (%s): %r"
            % (jaula, script))
    if not destino.is_file():
        return False, "Script no encontrado: %s" % destino

    sufijo = destino.suffix.lower()
    if sufijo in (".sh", ".bash"):
        import shutil
        bash = shutil.which("bash") or (
            "/bin/bash" if os.path.isfile("/bin/bash") else None)
        if bash is None:
            return False, (
                "No hay bash en el PATH para %s. Instala Git for Windows o "
                "reescribe el script en Python (.py)." % destino.name)
        argv = [bash, str(destino)]
    elif sufijo == ".ps1":
        import shutil
        ps = shutil.which("powershell") or shutil.which("pwsh")
        if ps is None:
            return False, "No hay powershell en el PATH para %s" % destino.name
        argv = [ps, "-NoProfile", "-NonInteractive", "-File", str(destino)]
    else:
        argv = [sys.executable, str(destino)]

    segundos = int(timeout) if timeout else _timeout_script()
    extra = {}
    if sys.platform == "win32":
        # CREATE_NO_WINDOW: una rutina de fondo no abre consolas en la cara
        # del dueno.
        extra["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    cwd = workdir if (workdir and Path(str(workdir)).is_dir()) else str(destino.parent)
    try:
        res = subprocess.run(
            argv, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=segundos, cwd=cwd,
            env=_entorno_script(), **extra)
    except subprocess.TimeoutExpired:
        return False, "El script agoto el tiempo (%ss): %s" % (segundos, destino)
    except Exception as exc:
        return False, "El script no se pudo ejecutar: %s: %s" % (
            type(exc).__name__, exc)

    salida = (res.stdout or "").strip()
    err = (res.stderr or "").strip()
    if res.returncode != 0:
        partes = ["El script salio con codigo %d" % res.returncode]
        if err:
            partes.append("stderr:\n%s" % err)
        if salida:
            partes.append("stdout:\n%s" % salida)
        return False, "\n".join(partes)
    return True, salida


def puerta_despertar(salida_script: str) -> bool:
    """True = despertar al agente. Convencion de Hermes (_parse_wake_gate,
    portada de nanoclaw #1232): si la ULTIMA linea no vacia del stdout es un
    JSON con {"wakeAgent": false}, no se llama al agente. Cualquier otra cosa
    -no JSON, sin la clave, o true- significa despertar."""
    if not salida_script:
        return True
    lineas = [l for l in str(salida_script).splitlines() if l.strip()]
    if not lineas:
        return True
    try:
        puerta = json.loads(lineas[-1].strip())
    except (ValueError, TypeError):
        return True
    if not isinstance(puerta, dict):
        return True
    return puerta.get("wakeAgent", True) is not False


# ---------------------------------------------------------------------------
# Contrato [SILENT]
# ---------------------------------------------------------------------------

def _canonica(texto: str) -> str:
    return " ".join(str(texto).strip().upper().split())


def _sin_puntuacion_de_borde(texto: str) -> str:
    """Quita puntuacion suelta de los bordes SIN tocar los corchetes: el modelo
    escribe '.NO_REPLY' o '*NO_REPLY*', pero '[SILENT' mal cerrado NO puede
    convertirse en 'SILENT' (gateway/response_filters.py:31)."""
    ini, fin = 0, len(texto)
    while ini < fin and texto[ini] not in "[]" and \
            unicodedata.category(texto[ini]).startswith("P"):
        ini += 1
    while fin > ini and texto[fin - 1] not in "[]" and \
            unicodedata.category(texto[fin - 1]).startswith("P"):
        fin -= 1
    return texto[ini:fin].strip()


def _es_marca(linea: str) -> bool:
    linea = str(linea).strip()
    if _canonica(linea) in _MARCAS_SILENCIO:
        return True
    return _canonica(_sin_puntuacion_de_borde(linea)) in _MARCAS_SILENCIO


def es_silencio(respuesta) -> bool:
    """True cuando la respuesta pide SUPRIMIR la entrega.

    Regla de la via autonoma de Hermes (is_autonomous_silence_response), mas
    laxa que la del chat interactivo a proposito: suprime si la marca es la
    respuesta entera, si ocupa ella sola la primera o la ultima linea, o si el
    centinela con corchetes ABRE la respuesta ('[SILENT] sin cambios'). Se
    anade el simetrico: '[SILENT]' CERRANDO la linea tambien suprime, porque el
    contrato pedido dice "empieza o termina con". Una marca a mitad de frase se
    ENTREGA: el informe legitimo que la menciona no se puede tragar (#51438).
    """
    if not isinstance(respuesta, str):
        return False
    limpio = respuesta.strip()
    if not limpio:
        return False
    if _es_marca(limpio):
        return True
    lineas = [l for l in limpio.splitlines() if l.strip()]
    if lineas and (_es_marca(lineas[0]) or _es_marca(lineas[-1])):
        return True
    arriba = limpio.upper()
    if arriba.startswith("[SILENT]") or arriba.endswith("[SILENT]"):
        return True
    return False


# ---------------------------------------------------------------------------
# Llamada al agente con timeout por INACTIVIDAD
# ---------------------------------------------------------------------------

def _limite_inactividad():
    crudo = os.environ.get("COGNIA_RUTINAS_INACTIVIDAD", "").strip()
    if crudo:
        try:
            valor = float(crudo)
            return valor if valor > 0 else None    # 0 = sin limite
        except (ValueError, TypeError):
            pass
    return _INACTIVIDAD_DEF


def _acepta_latir(fn) -> bool:
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return False
    if "latir" in sig.parameters:
        return True
    return any(p.kind == p.VAR_KEYWORD for p in sig.parameters.values())


def llamar_agente(correr_agente_fn, prompt: str, rutina: dict, limite=None):
    """(ok, respuesta, error). Nunca propaga la excepcion del agente.

    El limite es de INACTIVIDAD, no de duracion (Hermes cron/scheduler.py:3510):
    una rutina puede tardar horas si esta llamando tools; lo que se mata es la
    que lleva N segundos sin dar senales. Para que eso sea cierto de verdad,
    `correr_agente_fn` puede aceptar `latir` (un callable sin argumentos) y
    llamarlo en cada tool / cada delta del stream. Si su firma NO lo acepta, el
    unico latido es el del arranque y el limite degrada a wall-clock: es una
    LIMITACION, y se dice en vez de fingir lo contrario.

    El hilo del agente se ABANDONA al vencer (daemon), igual que hace Hermes al
    apagar su pool con wait=False: bloquear el tick esperando a un agente
    colgado seria repetir el fallo que el timeout viene a arreglar.
    """
    if limite is None:
        limite = _limite_inactividad()
    caja = {}
    ultimo = [time.time()]

    def latir(*_a, **_k):
        ultimo[0] = time.time()

    kwargs = {"latir": latir} if _acepta_latir(correr_agente_fn) else {}

    def _correr():
        try:
            caja["resp"] = correr_agente_fn(prompt, rutina, **kwargs)
            caja["ok"] = True
        except BaseException as exc:       # noqa: BLE001 - nada rompe el tick
            caja["ok"] = False
            caja["error"] = "%s: %s" % (type(exc).__name__, exc)

    # copy_context(): el hilo hijo hereda las ContextVars del tick (la
    # identidad del bot de cognia.bots.registro y los hops del envelope).
    # Sin esto el hijo no sabia de que bot era el turno salvo por os.environ,
    # que es del proceso entero (revision adversarial 2026-08-25).
    import contextvars
    hilo = threading.Thread(target=contextvars.copy_context().run,
                            args=(_correr,), name="cognia-rutina-agente",
                            daemon=True)
    hilo.start()
    while hilo.is_alive():
        hilo.join(timeout=_SONDEO_AGENTE)
        if limite and (time.time() - ultimo[0]) >= limite:
            return False, "", (
                "El agente lleva %ds sin dar senales (limite de inactividad "
                "%ss); se abandona la corrida." % (
                    int(time.time() - ultimo[0]), int(limite)))
    if not caja.get("ok"):
        return False, "", caja.get("error") or "El agente no devolvio nada."
    resp = caja.get("resp")
    return True, resp if isinstance(resp, str) else ("" if resp is None else str(resp)), None


# ---------------------------------------------------------------------------
# Prompt de la rutina (inyeccion de script + contrato de entrega/silencio)
# ---------------------------------------------------------------------------

def _aviso_rutina(rutina: dict) -> str:
    return (
        "[IMPORTANTE: corres como RUTINA PROGRAMADA de Cognia (%s). "
        "ENTREGA: tu respuesta final se entrega sola por el canal '%s'; no "
        "intentes entregarla tu. SILENCIO: si de verdad no hay nada nuevo que "
        "reportar, responde exactamente \"[SILENT]\" y nada mas, para suprimir "
        "la entrega. Nunca mezcles [SILENT] con contenido: o informas normal, "
        "o dices [SILENT] y ya.]\n\n"
        % (rutina.get("nombre", "?"), rutina.get("entregar", "consola")))


def construir_prompt(rutina: dict, script_previo=None):
    """Prompt efectivo, o None si no hay nada que analizar.

    None significa "el script no saco nada": Hermes se salta la llamada al
    modelo en ese caso (cron/scheduler.py:2473, `return None`), porque gastar
    un turno para que el modelo diga "no habia datos" es gastar por gastar.
    """
    prompt = str(rutina.get("prompt") or "")
    if script_previo is not None:
        ok, salida = script_previo
        if ok:
            if not salida:
                return None
            prompt = (
                "## Salida del script\n"
                "Estos datos los recogio el script previo. Usalos como "
                "contexto de tu analisis.\n\n"
                "```\n%s\n```\n\n%s" % (salida, prompt))
        else:
            prompt = (
                "## Error del script\n"
                "El script de recogida de datos fallo. Reportaselo al dueno.\n\n"
                "```\n%s\n```\n\n%s" % (salida, prompt))
    return _aviso_rutina(rutina) + prompt


# ---------------------------------------------------------------------------
# Salidas (suprimir no es perder)
# ---------------------------------------------------------------------------

def _guardar_salida(nombre: str, documento: str):
    """Guarda el documento de la corrida aunque la entrega se haya suprimido.
    Devuelve la ruta o None. Poda a las _MAX_SALIDAS mas recientes."""
    if not documento:
        return None
    seguro = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(nombre))[:64] or "rutina"
    carpeta = _dir_salidas() / seguro
    try:
        carpeta.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    destino = carpeta / (datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".md")
    if not _escribir_atomico(destino, documento):
        return None
    try:
        ficheros = sorted(carpeta.glob("*.md"))
        for viejo in ficheros[:-_MAX_SALIDAS]:
            viejo.unlink()
    except OSError:
        pass
    return destino


def _documento(rutina: dict, ahora_dt: datetime, cuerpo: str, estado: str) -> str:
    return (
        "# Rutina: %s\n\n"
        "**Horario:** %s\n"
        "**Corrida:** %s\n"
        "**Estado:** %s\n\n---\n\n%s\n"
        % (rutina.get("nombre", "?"),
           rutina.get("horario_txt", "?"),
           ahora_dt.strftime("%Y-%m-%d %H:%M:%S"),
           estado, cuerpo))


# ---------------------------------------------------------------------------
# Ejecutar una rutina
# ---------------------------------------------------------------------------

def ejecutar(rutina, correr_agente_fn, ahora=None) -> dict:
    """Corre UNA rutina y devuelve el informe. No lanza y no entrega.

    Orden (el de Hermes run_one_job):
      1. script (si hay) con timeout -> (ok, stdout)
      2. si el script fallo          -> se reporta; con agente, el error se
         inyecta para que el modelo lo cuente; sin agente, se entrega la alerta
      3. puerta wakeAgent en la ULTIMA linea del stdout -> {"wakeAgent": false}
         salta al agente entero
      4. stdout vacio -> no se llama al modelo (nada que analizar)
      5. respuesta del agente con marca [SILENT] -> se suprime la ENTREGA (se
         registra que se suprimio y el documento se guarda igual)

    Claves del informe: rutina, ejecucion_id, estado (terminal), entregado,
    salida, suprimido, agente_llamado, script_ok, script_salida, detalle,
    documento, ruta_salida.
    """
    if isinstance(rutina, str):
        rutina = obtener(rutina) or {}
    if not isinstance(rutina, dict) or not rutina.get("nombre"):
        return {
            "rutina": None, "ejecucion_id": None, "estado": "fallida",
            "entregado": False, "salida": "", "suprimido": None,
            "agente_llamado": False, "script_ok": None, "script_salida": "",
            "detalle": "Rutina inexistente o sin nombre.", "documento": "",
            "ruta_salida": None,
        }

    nombre = rutina["nombre"]
    ahora_dt = _norm_ahora(ahora)
    ejec = abrir_ejecucion(nombre, origen="ejecutar")
    marcar_corriendo(ejec["id"])

    informe = {
        "rutina": nombre,
        "ejecucion_id": ejec["id"],
        "estado": "completada",
        "entregar": rutina.get("entregar", "consola"),
        "entregado": False,
        "salida": "",
        "suprimido": None,
        "agente_llamado": False,
        "script_ok": None,
        "script_salida": "",
        "detalle": None,
        "documento": "",
        "ruta_salida": None,
    }

    workdir = rutina.get("workdir")
    if workdir and not Path(str(workdir)).is_dir():
        # Hermes avisa y sigue sin workdir en vez de tumbar la corrida.
        informe["detalle"] = "workdir %r ya no existe; se corre sin el." % workdir
        workdir = None

    script_previo = None
    if rutina.get("script"):
        ok_s, salida_s = correr_script(rutina["script"], workdir=workdir)
        script_previo = (ok_s, salida_s)
        informe["script_ok"] = ok_s
        informe["script_salida"] = salida_s

        if not ok_s:
            # El script se rompio. Un vigilante que falla EN SILENCIO es el
            # peor caso posible, asi que la entrega ocurre igual y el estado
            # terminal es 'fallida' aunque despues el agente conteste bien:
            # esconder el fallo del script detras de un informe bonito es
            # exactamente la mentira que este modulo no debe contar.
            informe["estado"] = "fallida"
            informe["detalle"] = salida_s
            if not rutina.get("despertar_agente", True):
                cuerpo = "El script de la rutina '%s' fallo\n\n%s" % (nombre, salida_s)
                informe["salida"] = cuerpo
                informe["entregado"] = True
                return _cerrar(informe, rutina, ahora_dt, cuerpo)

        elif not puerta_despertar(salida_s):
            informe["suprimido"] = "wakeAgent=false"
            informe["salida"] = ""
            return _cerrar(informe, rutina, ahora_dt, salida_s)

        elif not rutina.get("despertar_agente", True):
            # Modo sin agente: el script ES la rutina. stdout vacio = silencio.
            if not salida_s.strip():
                informe["suprimido"] = "script sin salida"
                return _cerrar(informe, rutina, ahora_dt,
                               "(el script no produjo salida)")
            informe["salida"] = salida_s
            informe["entregado"] = True
            return _cerrar(informe, rutina, ahora_dt, salida_s)

    if not rutina.get("despertar_agente", True):
        # Sin agente y sin script no deberia existir (crear lo impide), pero un
        # rutinas.json editado a mano si puede traerlo.
        informe["estado"] = "fallida"
        informe["detalle"] = "despertar_agente=False sin script: nada que correr."
        return _cerrar(informe, rutina, ahora_dt, informe["detalle"])

    prompt = construir_prompt(rutina, script_previo=script_previo)
    if prompt is None:
        informe["suprimido"] = "script sin salida"
        return _cerrar(informe, rutina, ahora_dt, "(el script no produjo salida)")

    if not callable(correr_agente_fn):
        informe["estado"] = "fallida"
        informe["detalle"] = "correr_agente_fn no es invocable."
        return _cerrar(informe, rutina, ahora_dt, informe["detalle"])

    informe["agente_llamado"] = True
    ok_a, respuesta, error = llamar_agente(correr_agente_fn, prompt, rutina)
    if not ok_a:
        informe["estado"] = "fallida"
        informe["detalle"] = error
        informe["salida"] = "La rutina '%s' fallo\n\n%s" % (nombre, error)
        informe["entregado"] = True     # un fallo que nadie ve es invisible
        return _cerrar(informe, rutina, ahora_dt, error or "fallo del agente")

    if es_silencio(respuesta):
        informe["suprimido"] = "[SILENT]"
        informe["salida"] = ""
        return _cerrar(informe, rutina, ahora_dt, respuesta)

    informe["salida"] = respuesta
    informe["entregado"] = bool(respuesta.strip())
    return _cerrar(informe, rutina, ahora_dt, respuesta)


def _cerrar(informe: dict, rutina: dict, ahora_dt: datetime, cuerpo: str) -> dict:
    """Guarda el documento (aunque se haya suprimido la entrega) y escribe el
    estado terminal en el ledger, con la supresion anotada."""
    estado_txt = informe["estado"]
    if informe["suprimido"]:
        estado_txt += " (entrega suprimida: %s)" % informe["suprimido"]
    documento = _documento(rutina, ahora_dt, str(cuerpo or ""), estado_txt)
    informe["documento"] = documento
    ruta = _guardar_salida(informe["rutina"], documento)
    informe["ruta_salida"] = str(ruta) if ruta else None
    cerrar_ejecucion(informe["ejecucion_id"], informe["estado"],
                     detalle=informe.get("detalle"),
                     suprimido=informe.get("suprimido"))
    return informe


# ---------------------------------------------------------------------------
# tick: una vuelta del reloj (NO se demoniza aqui)
# ---------------------------------------------------------------------------

def tick(ahora=None, correr_agente_fn=None) -> dict:
    """Corre lo pendiente y devuelve el informe de la vuelta.

    Este modulo NO abre hilos de fondo ni instala tareas de Windows: quien
    llame a `tick` decide si es un hilo del REPL, un `schtasks` o un bucle. Asi
    el motor se prueba entero con un reloj fijo y sin proceso vivo.

    Contrato del informe: {ahora, pendientes, corridas[], recuperadas,
    entregables[], error}. `entregables` son las corridas cuya salida SI hay
    que entregar (el que entrega es el integrador).
    """
    ahora_dt = _norm_ahora(ahora)
    informe = {
        "ahora": ahora_dt.isoformat(),
        "pendientes": 0,
        "corridas": [],
        "entregables": [],
        "recuperadas": 0,
        "error": None,
    }
    registrar_latido(False)
    try:
        informe["recuperadas"] = recuperar_interrumpidas()
        debidas = pendientes(ahora_dt)
        informe["pendientes"] = len(debidas)
        for rutina in debidas:
            corrida = ejecutar(rutina, correr_agente_fn, ahora=ahora_dt)
            marcar_corrida(rutina["nombre"], corrida["estado"],
                           detalle=corrida.get("detalle"), ahora=ahora_dt)
            informe["corridas"].append(corrida)
            if corrida.get("entregado") and corrida.get("salida"):
                informe["entregables"].append(corrida)
        registrar_latido(True)
        limpiar_error_tick()
    except BaseException as exc:            # noqa: BLE001 - el tick no rompe
        informe["error"] = "%s: %s" % (type(exc).__name__, exc)
        registrar_error_tick(informe["error"])
    return informe
