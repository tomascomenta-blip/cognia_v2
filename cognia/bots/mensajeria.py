"""
cognia/bots/mensajeria.py
=========================
Mensajes entre bots (inbox.jsonl) y el chat canonico (canon.jsonl).

Modelo (Hermes Bot Mode, message_agent): fire-and-forget. enviar() valida el
destino contra el roster, deja un ENVELOPE en el inbox del destino y vuelve
en el acto: el emisor termina su turno y la respuesta, si la hay, llega
DESPUES como un mensaje nuevo (la entrega la hace el daemon / ejecutor.
procesar_inbox). Los saltos (hops) frenan el ping-pong: a partir de max_hops
(3, Hermes: "3 rondas") el mensaje NO se entrega y se devuelve el motivo.

Disco, no memoria: dos procesos (REPL + daemon, o dos daemons por error)
pueden escribir el mismo inbox. Por eso hay lock entre procesos sobre un
fichero aparte (<inbox>.lock, mismo patron que backend_activo.
escribir_linea_jsonl: bloquear el jsonl en si rompe la lectura concurrente
en Windows) y el append es UN solo write() sobre O_APPEND.

Nada de aqui pasa texto por un shell: el texto va a JSON y de ahi al prompt.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from cognia.logger_config import get_logger
from cognia.bots import registro as R

try:
    import msvcrt
except ImportError:                       # POSIX
    msvcrt = None
try:
    import fcntl
except ImportError:                       # Windows
    fcntl = None

logger = get_logger(__name__)

MAX_HOPS = 3
TOPE_CUERPO_NOTIF = 500      # lo que va al centro de notificaciones


# ---------------------------------------------------------------------------
# Lock entre procesos
# ---------------------------------------------------------------------------

@contextmanager
def _lock(path: Path):
    """Mutex entre procesos sobre <path>.lock. LK_LOCK (Windows) reintenta
    ~10 s y luego lanza OSError; flock bloquea. Si no hay ninguno de los dos
    (plataforma rara) se sigue SIN lock y queda dicho en el log."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_name(path.name + ".lock")
    fdl = os.open(lock, os.O_RDWR | os.O_CREAT)
    tomado = False
    try:
        if msvcrt is not None:
            os.lseek(fdl, 0, os.SEEK_SET)
            msvcrt.locking(fdl, msvcrt.LK_LOCK, 1)
            tomado = True
        elif fcntl is not None:
            fcntl.flock(fdl, fcntl.LOCK_EX)
            tomado = True
        else:
            logger.warning("bots: sin msvcrt ni fcntl, escribo %s sin lock", path)
        yield
    finally:
        try:
            if tomado and msvcrt is not None:
                os.lseek(fdl, 0, os.SEEK_SET)
                msvcrt.locking(fdl, msvcrt.LK_UNLCK, 1)
            elif tomado and fcntl is not None:
                fcntl.flock(fdl, fcntl.LOCK_UN)
        finally:
            os.close(fdl)


def _append_linea(path: Path, fila: dict) -> None:
    """UN write() de la linea completa sobre O_APPEND, dentro del lock."""
    linea = (json.dumps(fila, ensure_ascii=False) + "\n").encode("utf-8")
    with _lock(path):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND)
        try:
            os.write(fd, linea)
        finally:
            os.close(fd)


def _leer_jsonl(path: Path) -> tuple[list, int]:
    """(filas, corruptas). Las lineas que no parsean se cuentan y se avisan:
    'inbox vacio' y 'inbox ilegible' no pueden verse igual."""
    if not path.is_file():
        return [], 0
    filas, malas = [], 0
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    filas.append(json.loads(ln))
                except ValueError:
                    malas += 1
    except OSError as e:
        logger.warning("bots: no pude leer %s: %s", path, e)
        return [], 0
    if malas:
        logger.warning("bots: %s tiene %d lineas corruptas (se saltan)", path, malas)
    return filas, malas


def _nombre(bot) -> str:
    return bot.nombre if isinstance(bot, R.Bot) else R.validar_nombre(str(bot))


def _inbox(bot) -> Path:
    return R.ruta(bot, "inbox.jsonl")


# ---------------------------------------------------------------------------
# Notificacion (opcional)
# ---------------------------------------------------------------------------

def _notificar(para: str, de: str, texto: str) -> str | None:
    """Deja la notificacion en NotificationCenter (user_id 'bot:<para>') para
    que /notif y el remoto la vean. Devuelve el AVISO (str) si no se pudo, o
    None. COGNIA_BOTS_NOTIF=0 la apaga (tests: el centro escribe en la db de
    escritorio del repo)."""
    if os.environ.get("COGNIA_BOTS_NOTIF", "").strip().lower() in ("0", "off", "no"):
        return None
    try:
        from cognia.notifications.notification_center import NotificationCenter
        NotificationCenter().create(
            user_id=f"bot:{para}", title=f"Mensaje de @{de}",
            body=texto[:TOPE_CUERPO_NOTIF], level="info", source="system")
        return None
    except Exception as e:                          # se ve en el envelope, no rompe
        return f"notificacion no creada: {type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def enviar(de: str, para: str, texto: str, hops: int = 0,
           max_hops: int = MAX_HOPS) -> dict:
    """Deja un envelope en el inbox de `para`. Devuelve
    {"ok": bool, "motivo": str, "id": str} (+ "aviso" si la notificacion
    fallo). Nunca lanza por un destino malo o un tope: eso es un motivo que
    la tool mensaje_bot le repite al modelo."""
    de = (de or "").strip().lstrip("@") or "usuario"
    texto = (texto or "").strip()
    if not texto:
        return {"ok": False, "motivo": "mensaje vacio", "id": ""}
    destino = R.resolver(para)
    if destino is None:
        conocidos = ", ".join(b.nombre for b in R.listar(incluir_ocultos=False)) or "ninguno"
        return {"ok": False, "id": "",
                "motivo": f"destino desconocido: {para!r} (bots: {conocidos})"}
    if destino.nombre == de:
        return {"ok": False, "motivo": "un bot no se escribe a si mismo", "id": ""}
    if hops >= max_hops:
        return {"ok": False, "id": "",
                "motivo": f"tope de saltos: hops={hops} >= max_hops={max_hops}; "
                          f"la conversacion entre bots termina aqui"}
    envelope = {
        "id": uuid.uuid4().hex[:12],
        "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "de": de, "para": destino.nombre, "texto": texto,
        "hops": int(hops), "entregado": False,
    }
    aviso = _notificar(destino.nombre, de, texto)
    if aviso:
        envelope["aviso"] = aviso
        logger.warning("bots: %s -> %s: %s", de, destino.nombre, aviso)
    try:
        _append_linea(_inbox(destino), envelope)
    except OSError as e:
        return {"ok": False, "id": "", "motivo": f"no pude escribir el inbox: {e}"}
    salida = {"ok": True, "motivo": "encolado", "id": envelope["id"]}
    if aviso:
        salida["aviso"] = aviso
    return salida


def pendientes(bot) -> list:
    """Envelopes con entregado=False, en orden de llegada."""
    filas, _ = _leer_jsonl(_inbox(bot))
    return [m for m in filas if isinstance(m, dict) and not m.get("entregado")]


def marcar_entregado(bot, id: str) -> bool:
    """Marca el envelope como entregado reescribiendo el inbox (atomico,
    dentro del lock). True si lo encontro."""
    path = _inbox(bot)
    with _lock(path):
        filas, _ = _leer_jsonl(path)
        hallado = False
        for m in filas:
            if isinstance(m, dict) and m.get("id") == id and not m.get("entregado"):
                m["entregado"] = True
                m["entregado_t"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                hallado = True
        if hallado:
            R._escribir_atomico(
                path, "".join(json.dumps(m, ensure_ascii=False) + "\n" for m in filas))
    return hallado


def formatear_entrante(m: dict) -> str:
    """Como lo ve el bot destino (prefijo de Hermes: 'Message from 🤖 x (@x):').
    El protocolo del system prompt enseña a reconocer ESTE prefijo."""
    de = (m.get("de") or "?").strip()
    return f"Mensaje de 🤖 {de} (@{de}): {m.get('texto', '')}"


def anotar_canon(bot, quien: str, texto: str) -> dict:
    """Apunta un evento {t, quien, texto} en sesiones/canon.jsonl (mismo
    formato que remoto/sesiones.Sesion.anotar, para que la pagina /bots lo
    pinte con el mismo codigo). Actualiza el mtime -> activo()."""
    evento = {"t": time.strftime("%H:%M:%S"), "quien": quien, "texto": texto}
    _append_linea(R.ruta(bot, *R.FICHERO_CANON), evento)
    return evento


def transcripcion(bot, limite: int = 200) -> list:
    """Los ultimos `limite` eventos del chat canonico."""
    filas, _ = _leer_jsonl(R.ruta(bot, *R.FICHERO_CANON))
    filas = [e for e in filas if isinstance(e, dict)]
    return filas[-limite:] if limite and limite > 0 else filas
