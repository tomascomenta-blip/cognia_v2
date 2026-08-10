# -*- coding: utf-8 -*-
"""Protocolo HTTP minimo para workers job-based del summoner (stdlib puro).

POR QUE existe: los backends pesados de GPU (SDXL, TripoSR, ...) cachean el
modelo en globals sin unload (p.ej. cognia.assets._PIPE). La unica descarga
fiable es MATAR EL PROCESO. Por eso cada backend corre como subproceso
(venv312gpu) detras de este mini-servidor: el summoner lo lanza, le manda jobs
por POST /job y lo mata cuando sobra la VRAM. Matar el proceso ES el unload.

POR QUE stdlib puro: este modulo se importa desde venv312gpu (que solo tiene
torch/diffusers y NO tiene las deps de cognia instaladas como paquete); no
puede arrastrar nada de cognia ni de terceros.

Contrato (congelado en plan_olas.md, agente B):
  GET  /health -> 200 {"ok": true, "rol", "ocupado", "cargado"}  SIEMPRE
                  responde, incluso a mitad de un job (ThreadingHTTPServer:
                  un /health mudo durante los ~22 s de un SDXL haria que el
                  barrido del summoner lo diera por muerto).
  POST /job    -> 200 {"ok": true, ...} | 200 {"ok": false, "error": tb[-2000:]}
                  Serializado por Lock (una GPU = un job a la vez). Una
                  excepcion del job NO mata al worker: vuelve como error.
  POST /apagar -> 200 {"ok": true} y el servidor se apaga limpio (~0.2 s).

Carga del modelo: perezosa por default (el primer /job la dispara), para que
/health aparezca rapido y el ensure() del summoner no confunda "cargando
modelo" con "proceso colgado" — el campo "cargado" del health lo hace visible.
Con COGNIA_WORKER_PRELOAD=1 se carga ANTES de abrir el puerto.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Optional


def servir(puerto: int, rol: str, cargar_fn: Optional[Callable[[], None]],
           manejar_fn: Callable[[dict], dict]) -> None:
    """Sirve el protocolo de worker en 127.0.0.1:puerto. BLOQUEA hasta /apagar.

    cargar_fn:  carga el modelo (idempotente aca: se llama a lo sumo una vez).
                None = no hay nada que precargar.
    manejar_fn: dict payload -> dict resultado. Si no trae "ok", se asume True.

    Nunca 0.0.0.0: el worker es local a la maquina, exponerlo seria regalar
    ejecucion de jobs GPU a la red.
    """
    estado = {"ocupado": False, "cargado": False}
    lock_job = threading.Lock()    # serializa /job: una GPU, un job a la vez
    lock_carga = threading.Lock()  # protege la carga unica del modelo

    def _cargar() -> None:
        # Doble chequeo: barato cuando ya cargo, correcto si dos jobs
        # llegaran a la vez (no pasa por lock_job, pero cuesta poco ser sano).
        if estado["cargado"]:
            return
        with lock_carga:
            if estado["cargado"]:
                return
            if cargar_fn is not None:
                cargar_fn()
            estado["cargado"] = True

    if os.environ.get("COGNIA_WORKER_PRELOAD", "0") == "1":
        # Si la precarga revienta, el worker NO abre el puerto: el summoner
        # vera "murio al arrancar" + el traceback en el log. Fallo visible.
        _cargar()

    class _Handler(BaseHTTPRequestHandler):

        # -- helpers -------------------------------------------------------
        def _responder(self, codigo: int, obj: dict) -> None:
            cuerpo = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            try:
                self.send_response(codigo)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(cuerpo)))
                self.end_headers()
                self.wfile.write(cuerpo)
            except (ConnectionError, BrokenPipeError, OSError):
                # El cliente corto (timeout del lado summoner). El worker
                # sigue vivo; el resultado del job igual quedo en disco.
                pass

        # -- rutas ---------------------------------------------------------
        def do_GET(self):  # noqa: N802 (nombre que exige BaseHTTPRequestHandler)
            if self.path == "/health":
                self._responder(200, {"ok": True, "rol": rol,
                                      "ocupado": estado["ocupado"],
                                      "cargado": estado["cargado"]})
            else:
                self._responder(404, {"ok": False,
                                      "error": "ruta desconocida: %s" % self.path})

        def do_POST(self):  # noqa: N802
            if self.path == "/apagar":
                self._responder(200, {"ok": True})
                # Timer para que la respuesta salga antes del shutdown
                # (shutdown() desde el hilo del handler se colgaria).
                threading.Timer(0.2, servidor.shutdown).start()
                return
            if self.path != "/job":
                self._responder(404, {"ok": False,
                                      "error": "ruta desconocida: %s" % self.path})
                return
            # Parseo del payload FUERA del lock: un body roto no debe
            # encolarse detras de un job de minutos.
            try:
                n = int(self.headers.get("Content-Length") or 0)
                crudo = self.rfile.read(n) if n else b""
                payload = json.loads(crudo.decode("utf-8")) if crudo else {}
                if not isinstance(payload, dict):
                    raise ValueError("el payload debe ser un objeto JSON, no %s"
                                     % type(payload).__name__)
            except Exception:
                self._responder(200, {"ok": False,
                                      "error": traceback.format_exc()[-2000:]})
                return
            with lock_job:
                estado["ocupado"] = True
                try:
                    _cargar()
                    r = manejar_fn(payload)
                    if not isinstance(r, dict):
                        r = {"ok": False,
                             "error": "manejar_fn devolvio %s; se esperaba dict"
                                      % type(r).__name__}
                    r.setdefault("ok", True)
                    self._responder(200, r)
                except Exception:
                    # El job murio; el worker NO. tb[-2000:] para que el
                    # summoner pueda mostrar la cola del error sin megabytes.
                    self._responder(200, {"ok": False,
                                          "error": traceback.format_exc()[-2000:]})
                finally:
                    estado["ocupado"] = False

        # -- logging -------------------------------------------------------
        def log_message(self, formato, *args):  # noqa: A002
            # /health llega cada pocos segundos desde el barrido del summoner:
            # loguearlo enterraria los errores reales en el log del rol.
            if self.path == "/health":
                return
            sys.stderr.write("[worker %s] %s\n" % (rol, formato % args))
            sys.stderr.flush()

    servidor = ThreadingHTTPServer(("127.0.0.1", int(puerto)), _Handler)
    servidor.daemon_threads = True  # un handler colgado no impide el apagado
    try:
        servidor.serve_forever(poll_interval=0.1)
    finally:
        servidor.server_close()
