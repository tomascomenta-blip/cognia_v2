# -*- coding: utf-8 -*-
"""
cognia/remoto/bots_api.py — el modo BOTS en el control remoto.

Un APIRouter que servidor.py incluye con una linea; asi el equipo que edita
index.html/servidor.py no se cruza con esto. Todo /api/bots/* queda bajo el
middleware de token de crear_app (es app-level: cubre las rutas del router).
La pagina /bots (static/bots.html) se sirve sin token como "/": no expone
datos, y el token lo lleva el propio front en localStorage.

Fuente: Hermes Bot Mode (docs/user-guide/bot-mode): roster de bots con
"Active now" (escribio en los ultimos 90 s), chat canonico por bot, inbox de
mensajes entre bots y las rutinas del bot.

POST /mensaje corre el turno en un HILO y devuelve al instante: un turno del
27B tarda minutos (82 s medidos para 60 tokens) y el movil no puede quedarse
colgado en un fetch. El front sondea /canon. `esperar: true` en el cuerpo
corre sincrono (tests y scripts). Un bot con turno en curso responde 409:
dos turnos a la vez sobre el mismo canon se pisarian el historial. Dos bots
DISTINTOS a la vez se serializan en registro.CANDADO_TURNO (os.environ es
global al proceso y el 27B tiene un slot): el segundo hilo espera su turno.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse

logger = logging.getLogger("cognia.remoto.bots")

router = APIRouter()
ESTATICOS = Path(__file__).parent / "static"

# Hook del ejecutor: None = cognia.bots.ejecutor.correr_turno (lazy). Los
# tests lo reemplazan por una funcion sin modelo.
correr_turno_fn = None

_EN_CURSO: set = set()
_LOCK = threading.Lock()


def _ejecutor():
    if correr_turno_fn is not None:
        return correr_turno_fn
    from cognia.bots import ejecutor
    return ejecutor.correr_turno


def _bot_o_404(nombre: str):
    from cognia.bots import registro as R
    b = R.resolver(nombre)
    if b is None:
        return None, JSONResponse({"error": "bot desconocido: %s" % nombre}, status_code=404)
    return b, None


def resumen(bot) -> dict:
    """Una fila del roster. Las rutinas se leen con entorno_rutinas(lectura=
    True) (rutinas lee COGNIA_RUTINAS_DIR en cada llamada; el modo lectura
    no espera al candado de turnos: el front sondea esto cada pocos
    segundos); un almacen roto no tumba la lista: se devuelve con 'aviso'."""
    from cognia.bots import registro as R, mensajeria as M
    fila = {
        "nombre": bot.nombre, "titulo": bot.titulo, "descripcion": bot.descripcion,
        "modelo": bot.modelo or "", "color": bot.color, "glifo": bot.glifo,
        "oculto": bot.oculto,
        "activo": R.activo(bot), "ultima_actividad": R.ultima_actividad(bot),
        "inbox_pendientes": len(M.pendientes(bot)),
        "rutinas": 0, "proxima_rutina": None, "en_curso": bot.nombre in _EN_CURSO,
    }
    ultimo = M.transcripcion(bot, limite=1)
    fila["ultimo_mensaje"] = ultimo[-1] if ultimo else None
    try:
        from cognia.hermes import rutinas
        from cognia.bots.ejecutor import entorno_rutinas
        with entorno_rutinas(bot, lectura=True):
            todas = rutinas.listar()
        fila["rutinas"] = len(todas)
        fila["proxima_rutina"] = next(
            (r.get("proxima_en") for r in todas if r.get("proxima_en")), None)
    except Exception as exc:
        fila["aviso"] = "rutinas no legibles: %s: %s" % (type(exc).__name__, exc)
        logger.warning("bots_api: %s: %s", bot.nombre, fila["aviso"])
    return fila


@router.get("/bots")
def pagina_bots():
    return FileResponse(ESTATICOS / "bots.html")


@router.get("/api/bots")
def listar_bots():
    from cognia.bots import registro as R
    return [resumen(b) for b in R.listar(incluir_ocultos=False)]


@router.get("/api/bots/{nombre}/canon")
def canon(nombre: str, limite: int = 200):
    from cognia.bots import mensajeria as M
    b, err = _bot_o_404(nombre)
    if err:
        return err
    return M.transcripcion(b, limite=max(1, min(int(limite), 2000)))


@router.post("/api/bots/{nombre}/mensaje")
def mensaje(nombre: str, cuerpo: dict):
    b, err = _bot_o_404(nombre)
    if err:
        return err
    texto = (cuerpo or {}).get("texto", "")
    texto = texto.strip() if isinstance(texto, str) else ""
    if not texto:
        return JSONResponse({"error": "texto vacio"}, status_code=400)
    esperar = bool((cuerpo or {}).get("esperar", False))
    fn = _ejecutor()
    with _LOCK:
        if b.nombre in _EN_CURSO:
            return JSONResponse({"error": "el bot %s ya esta respondiendo" % b.nombre},
                                status_code=409)
        _EN_CURSO.add(b.nombre)

    def _correr():
        try:
            return fn(b, texto)
        except Exception as exc:                # noqa: BLE001 - visible en el log
            logger.exception("bots_api: el turno de %s rompio", b.nombre)
            return "[error: %s: %s]" % (type(exc).__name__, exc)
        finally:
            with _LOCK:
                _EN_CURSO.discard(b.nombre)

    if esperar:
        return {"ok": True, "bot": b.nombre, "respuesta": _correr()}
    threading.Thread(target=_correr, name="cognia-bot-%s" % b.nombre, daemon=True).start()
    return {"ok": True, "bot": b.nombre, "encolado": True}


@router.get("/api/bots/{nombre}/inbox")
def inbox(nombre: str):
    from cognia.bots import mensajeria as M
    b, err = _bot_o_404(nombre)
    if err:
        return err
    pend = M.pendientes(b)
    return {"bot": b.nombre, "pendientes": pend, "total_pendientes": len(pend)}


@router.get("/api/bots/{nombre}/rutinas")
def rutinas_de(nombre: str):
    from cognia.bots.ejecutor import entorno_rutinas
    from cognia.hermes import rutinas
    b, err = _bot_o_404(nombre)
    if err:
        return err
    with entorno_rutinas(b, lectura=True):
        todas = rutinas.listar()
        ejecuciones = rutinas.ejecuciones(limite=20)
    return {"bot": b.nombre, "rutinas": todas, "ejecuciones": ejecuciones}
