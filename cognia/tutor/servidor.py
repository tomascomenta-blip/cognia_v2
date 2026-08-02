# -*- coding: utf-8 -*-
"""Servidor localhost del modo tutor: `python -m cognia.tutor`.

Sirve la UI y la API en 127.0.0.1 (LOOPBACK a proposito: el control remoto
de :8777 esta expuesto a la LAN y por eso exige token; este es local y no
necesita esa fricción). El orquestador se construye UNA vez al arrancar y
se comparte: cada sesion nueva del REPL tarda ~40s en levantar el 14B y un
tutor que hace eso por pregunta es inusable.
"""
from __future__ import annotations

import threading
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from cognia.tutor.motor import (Leccion, estudiar_tema, evaluar_respuesta,
                                responder_duda)

PUERTO = 8899
_ESTADO: dict = {"leccion": None, "orq": None}
_LOCK = threading.Lock()


def _infer_fn():
    """(system, user) -> str por la MISMA via interna de Cognia (la de
    _resumir/_generar_codigo). None si no hay backend: el motor degrada."""
    orq = _ESTADO.get("orq")
    if orq is None:
        return None

    def _f(system, user):
        r = orq.infer(user, system=system, max_tokens=1400, temperature=0.3)
        return r.text or ""
    return _f


def _arrancar_backend() -> str:
    """Carga el backend una vez. Devuelve el estado legible para la UI."""
    try:
        import cognia.first_run
        cognia.first_run.apply_config()
        from shattering.orchestrator import ShatteringOrchestrator
        orq = ShatteringOrchestrator(
            manifest_path="shattering/manifests/cognia_desktop.json")
        orq._try_load_llama()
        _ESTADO["orq"] = orq
        return "con modelo local" if orq._llama is not None else \
            "SIN modelo (modo degradado: material sin sintetizar)"
    except Exception as exc:
        _ESTADO["orq"] = None
        return f"SIN modelo ({exc})"


def crear_app() -> FastAPI:
    app = FastAPI(title="Cognia Tutor")

    @app.get("/", response_class=HTMLResponse)
    def _index():
        return (Path(__file__).parent / "static" / "index.html").read_text(
            encoding="utf-8")

    @app.get("/api/estado")
    def _estado():
        lec = _ESTADO.get("leccion")
        return {"backend": _ESTADO.get("backend", "?"),
                "tema": lec.tema if lec else None}

    @app.post("/api/estudiar")
    def _estudiar(payload: dict):
        tema = (payload or {}).get("tema", "")
        try:
            with _LOCK:
                lec = estudiar_tema(tema, infer_fn=_infer_fn())
                _ESTADO["leccion"] = lec
            return lec.dict()
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:      # nunca 500 mudo: el alumno merece causa
            return JSONResponse({"error": f"fallo estudiando: {exc}"},
                                status_code=500)

    @app.post("/api/preguntar")
    def _preguntar(payload: dict):
        lec = _ESTADO.get("leccion")
        if lec is None:
            return JSONResponse(
                {"error": "todavia no hay leccion: estudia un tema primero"},
                status_code=400)
        try:
            return responder_duda((payload or {}).get("duda", ""), lec,
                                  infer_fn=_infer_fn())
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.post("/api/responder")
    def _responder(payload: dict):
        p = payload or {}
        lec = _ESTADO.get("leccion")
        idx = int(p.get("indice", 0))
        if lec is None or idx >= len(lec.preguntas):
            return JSONResponse({"error": "pregunta inexistente"},
                                status_code=400)
        q = lec.preguntas[idx]
        card = lec.tarjetas[idx] if idx < len(lec.tarjetas) else None
        return evaluar_respuesta(q.get("pregunta", ""),
                                 q.get("respuesta_esperada", ""),
                                 p.get("respuesta", ""),
                                 infer_fn=_infer_fn(), card_id=card)

    @app.get("/api/repaso")
    def _repaso():
        """Tarjetas que TOCAN hoy (SM-2), de cualquier tema estudiado."""
        try:
            from cognia.learning.spaced_repetition import SpacedRepetitionEngine
            sr = SpacedRepetitionEngine()
            return {"pendientes": sr.get_due_cards(limit=20),
                    "stats": sr.get_stats()}
        except Exception as exc:
            return JSONResponse({"error": f"repaso no disponible: {exc}"},
                                status_code=500)

    @app.post("/api/repasar")
    def _repasar(payload: dict):
        p = payload or {}
        try:
            from cognia.learning.spaced_repetition import SpacedRepetitionEngine
            return SpacedRepetitionEngine().review_card(
                int(p.get("card_id")), max(0, min(5, int(p.get("calidad", 3)))))
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    return app


def _ip_lan() -> str:
    """IP de la LAN para poder abrirlo desde el movil. Sin red devuelve ''."""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))       # no manda nada: solo elige la ruta
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return ""


def main(argv=None) -> int:
    """--lan expone el tutor a la red local (para el movil). Por defecto es
    LOOPBACK: el tutor no pide token, asi que abrirlo a la LAN sin pedirlo
    seria regalar la maquina; con --lan se avisa en pantalla."""
    import sys
    import uvicorn
    argv = sys.argv[1:] if argv is None else argv
    lan = "--lan" in argv
    host = "0.0.0.0" if lan else "127.0.0.1"

    print("[tutor] cargando backend...", flush=True)
    _ESTADO["backend"] = _arrancar_backend()
    print(f"[tutor] backend: {_ESTADO['backend']}", flush=True)
    print(f"[tutor] Cognia Tutor en http://127.0.0.1:{PUERTO}"
          f"   <-- ABRIR ESTA URL (con el puerto :{PUERTO})", flush=True)
    if lan:
        ip = _ip_lan() or "<IP-del-PC>"
        print(f"[tutor] desde el movil: http://{ip}:{PUERTO}", flush=True)
        print("[tutor] AVISO: --lan expone el tutor a tu red local SIN "
              "autenticacion; usalo solo en una red de confianza.", flush=True)
    uvicorn.run(crear_app(), host=host, port=PUERTO, log_level="warning")
    return 0
