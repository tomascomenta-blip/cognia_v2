"""
servidor.py — la API del control remoto (FastAPI + WebSocket).

Sirve la app movil (static/) y expone:
  proyectos/sesiones (CRUD), mensajes (stdin del REPL real), stream por WS,
  comandos con descripciones (para las sugerencias del "/"), saludo por hora,
  output images de los programas generados, estado de la oficina, grafo de
  conocimiento, y los "monitores" (sesiones/REPLs vivos con su PID).
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import queue
import random
import sys
import threading
import time
from collections import deque
from pathlib import Path

from fastapi import FastAPI, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import sesiones as _sesiones
from .sesiones import (ColaSuscriptor, GestorSesiones, RAIZ_DATOS,
                       cargar_proyectos, guardar_proyectos,
                       registrar_proyecto,
                       # servidor.pid: una sola lectura para el servidor y el
                       # CLI (/remoto estado|parar llaman leer_pid_servidor)
                       estado_pid_servidor, leer_pid_servidor,
                       ruta_pid_servidor)

__all__ = ["crear_app", "main", "leer_pid_servidor", "estado_pid_servidor",
           "ruta_pid_servidor"]

ESTATICOS = Path(__file__).parent / "static"

# Defaults de escucha. Se pueden cambiar por --host/--port o por env
# (COGNIA_REMOTO_HOST/PORT): antes 0.0.0.0:8777 estaba FIJO en main() y no
# habia forma de servir solo en una interfaz (VPN, localhost para probar).
HOST_DEFAULT = "0.0.0.0"
PUERTO_DEFAULT = 8777

# Lo que el FRONT pregunta en /api/version para saber que servidor tiene
# delante (un movil con la PWA cacheada puede hablar con un servidor viejo).
CAPACIDADES = ["interrumpir", "delta", "subir", "ficheros"]

# Techo del body de /mensaje. Un mensaje del movil es texto que el REPL lee
# por stdin: 1 MB ya es un pegado gigante; sin techo, un POST de 500 MB se
# leia ENTERO en memoria antes de rechazar nada.
MAX_BODY_MENSAJE = 1 * 1024 * 1024

# Subida de ficheros (contrato F): 20 MB y una allowlist de extensiones. Las
# imagenes van a <proyecto>/imagenes/ (donde el agente ya deja las suyas y
# el chat las sabe insertar); el resto a <proyecto>/adjuntos/.
MAX_SUBIDA = 20 * 1024 * 1024
# Techo del body ENTERO de /subir, por cabecera y en el middleware: el
# fichero (MAX_SUBIDA) mas el envoltorio multipart (limites, cabeceras de la
# parte: cientos de bytes; 1 MB de margen es generoso). Ver el comentario del
# endpoint: es la unica defensa que corta ANTES de que starlette spoolee.
MAX_CUERPO_SUBIDA = MAX_SUBIDA + 1024 * 1024
_EXTS_SUBIDA_IMAGEN = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
_EXTS_SUBIDA_OTRAS = {".txt", ".md", ".pdf", ".csv", ".json"}
_EXTS_SUBIDA = _EXTS_SUBIDA_IMAGEN | _EXTS_SUBIDA_OTRAS

# Carpetas que /ficheros nunca lista: ruido y, en el caso de venv, decenas de
# miles de entradas que convertian el autocompletado en un walk de segundos.
_DIRS_EXCLUIDOS_FICHEROS = {".git", "venv", ".venv", "node_modules",
                            "__pycache__", ".mypy_cache", ".pytest_cache"}
_MAX_ENTRADAS_WALK = 20000

# Cada cuanto despierta el WS a comprobar que el cliente sigue ahi. NO es un
# poll (la espera es un asyncio.Event que el productor dispara al instante):
# es el techo para que un movil que se fue sin eventos pendientes no quede
# suscrito para siempre. Constante y no literal para poder bajarlo en tests.
ESPERA_WS_S = 30.0

# El evento que despierta a TODOS los WS al apagar el servidor (ver
# despertar_para_apagar): el endpoint lo reenvia al movil y cierra con 1001.
EVENTO_APAGADO = {"quien": "sistema",
                  "texto": "⚠ el servidor remoto se esta apagando",
                  "apagando": True}


def despertar_para_apagar(app) -> int:
    """Manda EVENTO_APAGADO a todas las colas de WS de la app. Devuelve
    cuantas desperto. Lo llama _ServidorUvicorn.handle_exit desde un hilo
    propio (ver ahi por que)."""
    gestor = getattr(app.state, "gestor", None)
    if gestor is None:
        return 0
    return gestor.despertar_suscriptores(
        {"t": time.strftime("%H:%M:%S"), **EVENTO_APAGADO})

# skills empaquetadas con Cognia (solo LECTURA desde el movil) y el dir de
# skills del usuario (cognia_skills/, el mismo destino que persist_skill):
# el PUT del movil escribe SIEMPRE en el segundo — un dispositivo de la LAN
# no modifica ficheros trackeados del repo.
_DIR_FLUJOS = Path(__file__).resolve().parent.parent / "skills"
_DIR_FLUJOS_EDIT = Path(__file__).resolve().parent.parent.parent / "cognia_skills"

# Saludos por franja horaria; uno al azar en cada arranque de la app.
_SALUDOS = {
    "madrugada": [
        "¿Trasnochando? Cognia también. ¿En qué trabajamos?",
        "Las mejores ideas salen de madrugada. Cuéntame.",
        "Silencio, café y Cognia. Combinación ganadora.",
    ],
    "manana": [
        "Buenos días. ¿Qué construimos hoy?",
        "Café en mano y a darle. ¿Por dónde empezamos?",
        "Buenos días. Los REPLs están calientes.",
    ],
    "tarde": [
        "Buenas tardes. ¿Seguimos donde lo dejamos?",
        "La tarde rinde si la empujamos. ¿Qué toca?",
        "Buenas tardes. Cognia lista para trabajar.",
    ],
    "noche": [
        "Buenas noches. ¿Un último empujón al proyecto?",
        "La noche es buena para el código. ¿Qué hacemos?",
        "Cognia de guardia nocturna. Tú dirás.",
    ],
}


def _franja() -> str:
    h = time.localtime().tm_hour
    if h < 6:
        return "madrugada"
    if h < 13:
        return "manana"
    if h < 20:
        return "tarde"
    return "noche"


def _comandos() -> list[dict]:
    """Todos los comandos del REPL con su descripcion, para las sugerencias."""
    try:
        from cognia.cli import _CMD_DESCRIPTIONS
        return [{"cmd": c, "desc": d} for c, d in
                sorted(_CMD_DESCRIPTIONS.items())]
    except Exception:
        return []


# Formatos que el chat sabe insertar. El agente genera PNG (RGBA transparente),
# pero una captura o un asset descargado puede ser jpg/webp.
_EXTS_IMAGEN = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".webp": "image/webp", ".gif": "image/gif", ".bmp": "image/bmp",
    ".svg": "image/svg+xml",
}


def _raices_imagen() -> list[Path]:
    """Carpetas cuyas imagenes puede insertar el chat.

    Los proyectos registrados son la raiz que importa: el REPL corre con cwd
    ahi, y ahi caen las imagenes del agente (<proyecto>/imagenes/) y las que
    genere cualquier script suyo."""
    raices = [RAIZ_DATOS.resolve()]
    try:
        from cognia.program_creator.storage import DEFAULT_STORAGE_DIR
        raices.append(Path(DEFAULT_STORAGE_DIR).resolve())
    except Exception:
        pass
    for pr in cargar_proyectos():
        try:
            raices.append(Path(pr["ruta"]).resolve())
        except Exception:
            pass
    ws = os.environ.get("COGNIA_AGENT_WORKSPACE")
    if ws:
        try:
            raices.append(Path(ws).resolve())
        except Exception:
            pass
    return raices


def _dentro_de_raices(p: Path) -> bool:
    """True si p cuelga de alguna raiz permitida (ya resuelta: sin .. ni
    symlinks que se escapen)."""
    for raiz in _raices_imagen():
        if p == raiz or raiz in p.parents:
            return True
    return False


def _imagenes_recientes(limite: int = 30) -> list[dict]:
    """Las output/input images de los programas generados, mas nuevas primero."""
    try:
        from cognia.program_creator.storage import DEFAULT_STORAGE_DIR
        raiz = Path(DEFAULT_STORAGE_DIR)
    except Exception:
        return []
    encontradas = []
    for png in raiz.glob("*/*/*.png"):
        encontradas.append(png)
    encontradas.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [{"programa": p.parent.parent.name, "tipo": p.parent.name,
             "nombre": p.name, "ruta": str(p),
             "url": f"/api/imagen?ruta={p}"}
            for p in encontradas[:limite]]


def asegurar_token(dirbase: Path) -> str:
    """Token compartido del remoto (token.txt junto al cert). El servidor
    escucha en 0.0.0.0 con COGNIA_ACCESO_TOTAL=1 en cada sesion: sin esto,
    cualquier dispositivo de la LAN pilotaba la maquina e inyectaba skills.
    Se genera una vez, se imprime en el arranque y el movil lo recibe por
    ?token= en la URL (el front lo guarda en localStorage)."""
    fichero = dirbase / "token.txt"
    try:
        tok = fichero.read_text(encoding="utf-8").strip()
        if tok:
            return tok
    except OSError:
        pass
    import secrets
    tok = secrets.token_urlsafe(24)
    dirbase.mkdir(parents=True, exist_ok=True)
    fichero.write_text(tok, encoding="utf-8")
    return tok


def _token_valido(recibido: str, esperado: str) -> bool:
    # compare_digest: sin atajos de tiempo (el token viaja por la LAN).
    # El TypeError NO es opcional: compare_digest revienta con str no-ASCII
    # ("comparing strings with non-ASCII characters is not supported"), y como
    # esto corre DENTRO del middleware, un ?token=cafe%CC%81 devolvia un 500 sin
    # manejar en vez de un 401. Cualquier token no comparable es invalido.
    if not recibido:
        return False
    try:
        return hmac.compare_digest(recibido, esperado)
    except TypeError:
        return False


class LimitadorAuth:
    """Rate limit de autenticacion FALLIDA por IP: `max_fallos` en `ventana_s`
    segundos bloquean a esa IP `bloqueo_s` segundos. El bloqueo aplica a las
    peticiones SIN token valido (429 / WS 4429); una peticion con el token
    correcto pasa aunque su IP este bloqueada. La primera version bloqueaba
    tambien al token bueno "para no dejar entrar a la fuerza bruta que
    acierta": eso no frena nada — quien tiene el token correcto ya gano — y
    si dejaba fuera un minuto al dueno cuya PWA cacheo un token viejo y
    reintento 10 veces antes de abrir la URL nueva (hallazgo rev1
    2026-08-25, medido con TestClient: el 11º GET con token BUENO daba 429).
    Lo que si frena la fuerza bruta es que un intento MAS con token malo
    desde esa IP no se evalua (429 sin tocar el comparador). Reloj
    inyectable para probarlo sin dormir. Sin esto, el token de 24 bytes era
    atacable a la velocidad que diera la LAN."""

    def __init__(self, max_fallos: int = 10, ventana_s: float = 60.0,
                 bloqueo_s: float = 60.0, reloj=time.monotonic):
        self.max_fallos = max(1, int(max_fallos))
        self.ventana_s = float(ventana_s)
        self.bloqueo_s = float(bloqueo_s)
        self._reloj = reloj
        self._fallos: dict[str, deque] = {}
        self._bloqueadas: dict[str, float] = {}
        self._lock = threading.Lock()

    def bloqueada(self, ip: str) -> float:
        """Segundos que le quedan de bloqueo a la IP (0 = libre)."""
        with self._lock:
            hasta = self._bloqueadas.get(ip)
            if hasta is None:
                return 0.0
            resta = hasta - self._reloj()
            if resta <= 0:
                del self._bloqueadas[ip]
                self._fallos.pop(ip, None)
                return 0.0
            return resta

    def fallo(self, ip: str) -> bool:
        """Registra un fallo; True si con este la IP queda bloqueada."""
        ahora = self._reloj()
        with self._lock:
            cola = self._fallos.setdefault(ip, deque())
            cola.append(ahora)
            while cola and ahora - cola[0] > self.ventana_s:
                cola.popleft()
            if len(cola) >= self.max_fallos:
                self._bloqueadas[ip] = ahora + self.bloqueo_s
                return True
            return False

    def exito(self, ip: str) -> None:
        with self._lock:
            self._fallos.pop(ip, None)


def _ip_de(request) -> str:
    try:
        return request.client.host or "?"
    except Exception:
        return "?"


def _origenes_permitidos(host: str, port: int) -> list[str]:
    """La allowlist de CORS = el PROPIO origen del servidor (la PWA se sirve
    desde el), en sus tres nombres: la IP LAN, 127.0.0.1 y localhost. Nunca
    "*": con el token en localStorage, un origen ajeno con CORS abierto podria
    leer respuestas de la API desde una pagina cualquiera de la LAN."""
    nombres = ["127.0.0.1", "localhost"]
    ip = _ip_lan()
    if ip:
        nombres.insert(0, ip)
    if host and host not in ("0.0.0.0", "::", "") and host not in nombres:
        nombres.insert(0, host)
    return [f"https://{n}:{port}" for n in nombres]


def _nombre_seguro(nombre: str) -> str:
    """Solo el basename, con caracteres seguros: la subida nunca escribe fuera
    de imagenes/ o adjuntos/ del proyecto ("../../x" -> "x")."""
    base = Path(nombre or "").name
    limpio = "".join(c if (c.isalnum() or c in "-_. ") else "_" for c in base)
    limpio = limpio.strip(" .")
    return limpio or "archivo"


def _listar_ficheros(raiz: Path, prefijo: str, limite: int = 30) -> list[str]:
    """Rutas RELATIVAS (con /) bajo raiz cuyo nombre o ruta empieza por el
    prefijo (sin distinguir mayusculas). Solo dentro de raiz: el prefijo no
    puede escapar porque no se usa como ruta, solo como filtro sobre lo que
    el walk ya encontro."""
    q = (prefijo or "").strip().replace("\\", "/").lower()
    if q.startswith("./"):
        q = q[2:]
    salida: list[str] = []
    vistas = 0
    raiz = raiz.resolve()
    for actual, dirs, ficheros in os.walk(raiz):
        # solo por NOMBRE EXACTO: `startswith(".git")` escondia .github
        # (workflows de CI que el movil quiere mencionar), hallazgo 2026-08-25
        dirs[:] = sorted(d for d in dirs if d not in _DIRS_EXCLUIDOS_FICHEROS)
        rel_dir = Path(actual).relative_to(raiz).as_posix()
        for nombre in sorted(ficheros):
            vistas += 1
            if vistas > _MAX_ENTRADAS_WALK:
                return salida
            rel = nombre if rel_dir == "." else f"{rel_dir}/{nombre}"
            if (not q or rel.lower().startswith(q)
                    or nombre.lower().startswith(q)):
                salida.append(rel)
                if len(salida) >= limite:
                    return salida
    return salida


def crear_app(host: str = HOST_DEFAULT, port: int = PUERTO_DEFAULT) -> FastAPI:
    app = FastAPI(title="Cognia Remoto")
    gestor = GestorSesiones()
    token = asegurar_token(RAIZ_DATOS)
    limitador = LimitadorAuth()
    app.state.gestor = gestor
    app.state.limitador = limitador

    # CORS con allowlist = el propio origen. Sin middleware no habia CORS
    # (el navegador aplica same-origin, que ya protegia); con "*" se abriria
    # la API a cualquier pagina de la LAN. La lista se calcula con host/port
    # REALES de escucha, por eso crear_app los recibe.
    app.add_middleware(CORSMiddleware,
                       allow_origins=_origenes_permitidos(host, port),
                       allow_credentials=False,
                       allow_methods=["GET", "POST", "PUT", "DELETE"],
                       allow_headers=["X-Cognia-Token", "Content-Type"])

    # ── autenticacion: token compartido para TODO /api/* y /ws/* ──
    # La app ("/", /static) se sirve sin token: no expone datos; toda accion
    # real pasa por /api o /ws. Header X-Cognia-Token o ?token= (imagenes
    # via <img src> y el WebSocket no pueden mandar headers).
    @app.middleware("http")
    async def _auth(request: Request, call_next):
        ruta = request.url.path
        if ruta.startswith("/api/"):
            ip = _ip_de(request)
            recibido = (request.headers.get("x-cognia-token")
                        or request.query_params.get("token", ""))
            if not _token_valido(recibido, token):
                # sin token valido: primero el bloqueo (un intento mas desde
                # una IP bloqueada ni se cuenta), luego el fallo. El token
                # BUENO nunca llega aqui: no se bloquea (ver LimitadorAuth).
                resta = limitador.bloqueada(ip)
                if resta > 0:
                    return JSONResponse(
                        {"error": "demasiados intentos de autenticacion "
                                  f"fallidos; espera {int(resta) + 1} s"},
                        status_code=429,
                        headers={"Retry-After": str(int(resta) + 1)})
                limitador.fallo(ip)
                return JSONResponse(
                    {"error": "token invalido o ausente (ver "
                              "~/.cognia/remoto/token.txt)"},
                    status_code=401)
            limitador.exito(ip)
            # techo del body de /subir POR CABECERA, antes de que FastAPI
            # parsee el multipart (que starlette spoolea ENTERO a disco sin
            # tope por fichero: ver el endpoint). Un cliente honesto manda
            # Content-Length; uno que mienta o use chunked cae en el tope del
            # endpoint, ya spooleado.
            if ruta.endswith("/subir") and request.method == "POST":
                try:
                    largo = int(request.headers.get("content-length") or 0)
                except ValueError:
                    largo = 0
                if largo > MAX_CUERPO_SUBIDA:
                    return JSONResponse(
                        {"error": f"subida demasiado grande ({largo} bytes; "
                                  f"tope {MAX_SUBIDA} + envoltorio)"},
                        status_code=413)
            # techo del body de /mensaje POR CABECERA, antes de leer nada
            # (el endpoint vuelve a medirlo sobre lo leido: un cliente puede
            # mentir en Content-Length o mandar chunked)
            if ruta.endswith("/mensaje") and request.method == "POST":
                try:
                    largo = int(request.headers.get("content-length") or 0)
                except ValueError:
                    largo = 0
                if largo > MAX_BODY_MENSAJE:
                    return JSONResponse(
                        {"error": f"mensaje demasiado grande ({largo} bytes; "
                                  f"tope {MAX_BODY_MENSAJE})"},
                        status_code=413)
        return await call_next(request)

    # ── version y capacidades: el front sabe con que servidor habla ──
    @app.get("/api/version")
    def version():
        try:
            from cognia import __version__ as v
        except Exception as e:
            v = f"desconocida ({e})"
        return {"version": v, "capacidades": list(CAPACIDADES),
                "acceso_default": "total"}

    def _proyecto(pid: str) -> dict:
        for pr in cargar_proyectos():
            if pr["id"] == pid:
                return pr
        # HTTPException y no ValueError: el ValueError salia como 500 mudo
        # (TestClient lo relanzaba; uvicorn lo tragaba en un "Internal
        # Server Error" sin cuerpo). 404 con el id, legible desde el movil.
        from fastapi import HTTPException
        raise HTTPException(status_code=404,
                            detail=f"proyecto desconocido: {pid}")

    # ── app movil ──
    @app.get("/")
    def raiz():
        return FileResponse(ESTATICOS / "index.html")

    # ── saludo por hora ──
    @app.get("/api/saludo")
    def saludo():
        franja = _franja()
        return {"franja": franja, "texto": random.choice(_SALUDOS[franja])}

    # ── proyectos ──
    @app.get("/api/proyectos")
    def proyectos():
        vivos = {v["proyecto"] for v in gestor.vivas()}
        salida = []
        for pr in cargar_proyectos():
            salida.append({**pr,
                           "sesiones": len(gestor.indice(pr["id"])),
                           "activo": pr["id"] in vivos})
        return salida

    @app.post("/api/proyectos")
    def alta_proyecto(cuerpo: dict):
        try:
            return registrar_proyecto(cuerpo.get("ruta", ""))
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    @app.delete("/api/proyectos/{pid}")
    def baja_proyecto(pid: str):
        # antes solo quitaba la entrada del json: los REPLs del proyecto
        # quedaban huerfanos (6 medidos) y sus transcripciones colgadas.
        paradas = gestor.parar_proyecto(pid)
        proyectos = [p for p in cargar_proyectos() if p["id"] != pid]
        guardar_proyectos(proyectos)
        # las transcripciones NO se borran: van a la papelera del remoto
        # (recuperables a mano si la baja fue un error)
        papelera = None
        d = RAIZ_DATOS / pid
        if d.is_dir():
            destino = (RAIZ_DATOS / "papelera"
                       / f"{pid}-{time.strftime('%Y%m%d-%H%M%S')}")
            destino.parent.mkdir(parents=True, exist_ok=True)
            try:
                d.rename(destino)
                papelera = str(destino)
            except OSError:
                pass   # fichero en uso: los datos quedan donde estaban
        return {"ok": True, "sesiones_paradas": paradas, "papelera": papelera}

    # ── sesiones ──
    @app.get("/api/proyectos/{pid}/sesiones")
    def sesiones(pid: str):
        return gestor.indice(pid)

    @app.post("/api/proyectos/{pid}/sesiones")
    def nueva_sesion(pid: str, cuerpo: dict | None = None):
        # "acceso": "total" (default, el historico del movil) o "restringido"
        # (sin COGNIA_ACCESO_TOTAL ni computer-use). Cableado para que el
        # front pueda ofrecer sesiones de solo-conversar sin tocar el back.
        s = gestor.crear(_proyecto(pid), (cuerpo or {}).get("titulo", ""),
                         acceso=(cuerpo or {}).get("acceso", "total"))
        return {"id": s.id, "titulo": s.titulo, "acceso": s.acceso}

    @app.delete("/api/proyectos/{pid}/sesiones/{sid}")
    def borrar_sesion(pid: str, sid: str):
        return {"ok": gestor.borrar(pid, sid)}

    @app.post("/api/proyectos/{pid}/sesiones/{sid}/parar")
    def parar_sesion(pid: str, sid: str):
        # parar SIN destruir: el REPL muere, el .jsonl sobrevive y la sesion
        # puede reabrirse (enviar() re-arranca). Antes la unica salida era el
        # DELETE, que borra la transcripcion: 6 REPLs eternos medidos.
        return {"ok": gestor.parar_sesion(sid)}

    @app.get("/api/proyectos/{pid}/sesiones/{sid}/transcripcion")
    def transcripcion(pid: str, sid: str):
        return gestor.obtener(_proyecto(pid), sid).transcripcion()

    @app.post("/api/proyectos/{pid}/sesiones/{sid}/mensaje")
    async def mensaje(pid: str, sid: str, request: Request):
        # el body se lee A MANO para medirlo: `cuerpo: dict` lo habria
        # cargado entero (y parseado) antes de poder decir 413
        crudo = await request.body()
        if len(crudo) > MAX_BODY_MENSAJE:
            return JSONResponse(
                {"error": f"mensaje demasiado grande ({len(crudo)} bytes; "
                          f"tope {MAX_BODY_MENSAJE})"},
                status_code=413)
        try:
            cuerpo = json.loads(crudo.decode("utf-8"))
            if not isinstance(cuerpo, dict):
                raise ValueError("el body debe ser un objeto JSON")
        except (ValueError, UnicodeDecodeError) as e:
            return JSONResponse({"error": f"JSON invalido: {e}"},
                                status_code=400)
        texto = (cuerpo.get("texto") or "").strip()
        if not texto:
            return JSONResponse({"error": "mensaje vacio"}, status_code=400)
        s = gestor.obtener(_proyecto(pid), sid)
        # enviar() puede arrancar el REPL y dormir 1 s: fuera del loop
        import asyncio
        await asyncio.to_thread(s.enviar, texto)
        return {"ok": True, "entradas": len(_sesiones.entradas_para_repl(texto))}

    @app.post("/api/proyectos/{pid}/sesiones/{sid}/interrumpir")
    def interrumpir(pid: str, sid: str):
        """Corta la generacion en curso sin matar el REPL (contrato A).
        {"ok": bool, "motivo": str}; ok=False con motivo legible si la sesion
        no esta viva o la senal no se pudo mandar."""
        _proyecto(pid)
        return gestor.interrumpir(sid)

    # ── ficheros del proyecto (autocompletado de @ruta) y subida ──
    @app.get("/api/proyectos/{pid}/ficheros")
    def ficheros(pid: str, q: str = ""):
        raiz = Path(_proyecto(pid)["ruta"])
        if not raiz.is_dir():
            return JSONResponse({"error": "la carpeta del proyecto no existe"},
                                status_code=404)
        return {"items": _listar_ficheros(raiz, q)}

    @app.post("/api/proyectos/{pid}/subir")
    async def subir(pid: str, archivo: UploadFile):
        raiz = Path(_proyecto(pid)["ruta"]).resolve()
        nombre = _nombre_seguro(archivo.filename or "")
        ext = Path(nombre).suffix.lower()
        if ext not in _EXTS_SUBIDA:
            return JSONResponse(
                {"error": f"extension no permitida: {ext or 'sin extension'} "
                          f"(valen {', '.join(sorted(_EXTS_SUBIDA))})"},
                status_code=415)
        # HONESTO sobre el tope (hallazgo rev1 2026-08-25): con `archivo:
        # UploadFile` FastAPI parsea TODO el form antes de entrar aqui, y
        # starlette (formparsers.py: spool_max_size=1 MB, max_part_size solo
        # para partes que no son fichero) escribe el fichero ENTERO a un
        # SpooledTemporaryFile en %TEMP%. El bucle de abajo lee de ese
        # temporal ya escrito: corta el GUARDADO en <proyecto>, no la
        # recepcion. Lo que si corta antes de recibir es el middleware _auth,
        # por Content-Length (MAX_CUERPO_SUBIDA) — un cliente que mienta en la
        # cabecera o mande chunked se spoolea entero y recibe el 413 aqui.
        trozos, total = [], 0
        while True:
            trozo = await archivo.read(256 * 1024)
            if not trozo:
                break
            total += len(trozo)
            if total > MAX_SUBIDA:
                return JSONResponse(
                    {"error": f"fichero demasiado grande (tope {MAX_SUBIDA} "
                              "bytes)"},
                    status_code=413)
            trozos.append(trozo)
        sub = "imagenes" if ext in _EXTS_SUBIDA_IMAGEN else "adjuntos"
        carpeta = raiz / sub
        carpeta.mkdir(parents=True, exist_ok=True)
        destino = carpeta / nombre
        # no pisar: "foto.png" -> "foto-2.png" si ya existe
        n = 1
        while destino.exists():
            n += 1
            destino = carpeta / f"{Path(nombre).stem}-{n}{ext}"
        if raiz not in destino.resolve().parents:
            return JSONResponse({"error": "ruta fuera del proyecto"},
                                status_code=400)
        destino.write_bytes(b"".join(trozos))
        rel = destino.relative_to(raiz).as_posix()
        return {"ruta": rel, "mencion": f"@{rel}", "bytes": total}

    # ── stream en vivo ──
    @app.websocket("/ws/{pid}/{sid}")
    async def ws(websocket: WebSocket, pid: str, sid: str):
        # el middleware http no cubre websockets: mismo token, a mano.
        recibido = (websocket.headers.get("x-cognia-token")
                    or websocket.query_params.get("token", ""))
        ip = _ip_de(websocket)
        if not _token_valido(recibido, token):
            # mismo orden que el middleware http: el token bueno no se bloquea
            resta = limitador.bloqueada(ip)
            if resta > 0:
                # 4429 = "demasiados intentos" (codigo de la app); el reason
                # viaja al movil, que lo pinta (ws.onclose en index.html)
                await websocket.close(
                    code=4429, reason=f"demasiados intentos, espera "
                                      f"{int(resta) + 1} s")
                return
            limitador.fallo(ip)
            await websocket.close(code=4401)   # 4401 = "no autorizado" (app)
            return
        limitador.exito(ip)
        await websocket.accept()
        s = gestor.obtener(_proyecto(pid), sid)
        import asyncio
        # La espera es un asyncio.Event que el PRODUCTOR dispara desde su
        # hilo (al_poner -> call_soon_threadsafe): ni poll ni hilo del pool.
        # Historia: poll con sleep(0.15) (150 ms de latencia) -> to_thread(
        # q.get, timeout=30) (latencia cero, pero cada WS abierto clavaba un
        # hilo del pool por defecto — el mismo pool de /mensaje — y al apagar
        # uvicorn cancelaba la tarea a los 5 s y el hilo seguia en q.get:
        # 29,1 s de salida con UN movil conectado, medido 2 veces 2026-08-25,
        # mas un traceback CancelledError en el log). Con el Event la
        # cancelacion es instantanea y no hay hilo que esperar.
        loop = asyncio.get_running_loop()
        hay = asyncio.Event()
        # cola CON TECHO: un movil atascado en mitad de un workflow ya no la
        # hace crecer sin limite. Lo que se tira se cuenta y se ANUNCIA abajo.
        q = ColaSuscriptor(al_poner=lambda: loop.call_soon_threadsafe(hay.set))
        with s.lock:
            s.suscriptores.append(q)
        try:
            while True:
                try:
                    evento = q.get_nowait()
                except queue.Empty:
                    # clear ANTES de esperar: un set() encolado por el
                    # productor entre el get_nowait y aqui corre en el loop
                    # DESPUES de que esta corrutina ceda, asi que no se pierde
                    hay.clear()
                    try:
                        await asyncio.wait_for(hay.wait(), timeout=ESPERA_WS_S)
                    except asyncio.TimeoutError:
                        # sin eventos: verificar que el cliente siga ahi (la
                        # desconexion solo se detecta al enviar; sin esto un
                        # movil que se fue sin eventos pendientes quedaba
                        # suscrito para siempre)
                        if websocket.client_state.name != "CONNECTED":
                            break
                    continue
                if evento.get("apagando"):
                    # el servidor se va (despertar_para_apagar): se avisa y se
                    # CIERRA — es lo que deja a uvicorn sin conexiones que
                    # esperar y lo que hace que la salida tarde decimas y no
                    # timeout_graceful_shutdown. 1001 = "going away".
                    await websocket.send_text(
                        json.dumps(evento, ensure_ascii=False))
                    await websocket.close(code=1001,
                                          reason="servidor apagandose")
                    break
                # el agujero se anuncia PEGADO al primer evento que si llega,
                # en el orden en que el usuario lo lee: primero "faltan N",
                # despues lo que sobrevivio. Silencio aca = el movil creyendo
                # que vio el workflow entero.
                perdidas = q.tomar_descartadas()
                if perdidas:
                    await websocket.send_text(json.dumps(
                        {"t": time.strftime("%H:%M:%S"), "quien": "sistema",
                         "texto": (f"⚠ se perdieron {perdidas} lineas "
                                   f"mientras estabas desconectado"),
                         "perdidas": perdidas}, ensure_ascii=False))
                await websocket.send_text(
                    json.dumps(evento, ensure_ascii=False))
        except WebSocketDisconnect:
            pass
        except asyncio.CancelledError:
            # uvicorn cancela las tareas vivas al apagar (tras
            # timeout_graceful_shutdown): es el camino cuando el aviso de
            # apagado no llego (WS aceptado despues de la senal). Se cierra
            # la conexion y se termina en orden: dejar subir la cancelacion
            # era el "Exception in ASGI application ... CancelledError" del
            # log. No se relanza a proposito: la tarea ya hizo su trabajo.
            try:
                await websocket.close(code=1001, reason="servidor apagandose")
            except Exception as e:
                print(f"[remoto] ws {pid}/{sid}: no pude cerrar al apagar: "
                      f"{type(e).__name__}: {e}", file=sys.stderr, flush=True)
        finally:
            with s.lock:
                if q in s.suscriptores:
                    s.suscriptores.remove(q)

    # ── comandos y sugerencias ──
    @app.get("/api/comandos")
    def comandos():
        return _comandos()

    # ── imagenes ──
    @app.get("/api/imagenes")
    def imagenes():
        return _imagenes_recientes()

    @app.get("/api/imagen")
    def imagen(ruta: str):
        """Sirve una imagen para insertarla en el chat.

        Antes solo abria PNGs de la biblioteca de programas, y ese era el bug
        (medido 2026-07-25): el agente deja SUS imagenes en el workspace
        (<proyecto>/imagenes/gen_*.png via image_tools), el front las detectaba
        en el texto, pedia esta ruta, recibia 403 y el onerror BORRABA el <img>.
        Inserción de imágenes que existía y desaparecía en silencio.
        Ahora se autoriza por RAICES (proyectos registrados + biblioteca +
        datos del remoto), no por una sola carpeta; sigue sin poder leer el
        disco entero."""
        try:
            p = Path(ruta).resolve()
        except Exception:
            return JSONResponse({"error": "ruta invalida"}, status_code=400)
        # la RAIZ se juzga primero: "fuera de mis carpetas" es 403 sea cual sea
        # la extension (un C:/Windows/win.ini nunca es un problema de formato)
        if not _dentro_de_raices(p):
            return JSONResponse(
                {"error": "ruta fuera de los proyectos y la biblioteca"},
                status_code=403)
        if p.suffix.lower() not in _EXTS_IMAGEN:
            return JSONResponse(
                {"error": f"formato no servible: {p.suffix or 'sin extension'}"},
                status_code=415)
        if not p.is_file():
            return JSONResponse({"error": "no existe"}, status_code=404)
        return FileResponse(p, media_type=_EXTS_IMAGEN[p.suffix.lower()])

    # ── Jarvis: cerebro central + expertos y roles (para la vista 3D de voz) ──
    # Colores estables por experto; el cerebro es verde y va en el centro.
    _EXPERTOS_ROLES = [
        ("planificador", "rol",     "#4a90d9", "descompone la meta en subtareas"),
        ("generador",    "rol",     "#8f7ae8", "escribe el codigo/So la respuesta"),
        ("evaluador",    "rol",     "#d9a441", "juzga si el resultado cumple"),
        ("juez",         "rol",     "#e05b7c", "arbitra entre respuestas"),
        ("critico",      "rol",     "#d96a4a", "critica y remata la calidad"),
        ("investigador", "rol",     "#5fc9c0", "busca y sintetiza fuentes"),
        ("lector_web",   "rol",     "#57a0e0", "navega y extrae de paginas"),
        ("busqueda_web", "rol",     "#a3c94a", "busca en la web sin API key"),
        ("proactividad", "rol",     "#c95fa4", "propone siguientes pasos"),
        ("vista",        "rol",     "#7ec8a9", "revisa el render visual"),
    ]

    def _color_experto(nombre: str) -> str:
        paleta = ["#2ea86c", "#4a90d9", "#d9a441", "#c95fa4", "#5fc9c0",
                  "#d96a4a", "#8f7ae8", "#a3c94a", "#e05b7c", "#57a0e0"]
        return paleta[sum(ord(c) for c in nombre) % len(paleta)]

    @app.get("/api/expertos")
    def expertos():
        """Catalogo para la vista Jarvis: cerebro central + micro-expertos
        (los .npz reales en disco) + roles/subsistemas sobre el modelo."""
        salida = [{"id": "cerebro", "nombre": "Cognia", "tipo": "cerebro",
                   "color": "#2ea86c", "central": True,
                   "descripcion": "el modelo central que razona y decide"}]
        # micro-expertos = carpetas con config.json en microexpertos/;
        # activo = tiene pesos.npz (pide_grafico fue KILL, no tiene pesos).
        try:
            base = Path(__file__).resolve().parent.parent / "microexpertos"
            for d in sorted(base.iterdir()):
                if d.is_dir() and (d / "config.json").exists():
                    activo = (d / "pesos.npz").exists()
                    salida.append({"id": d.name, "nombre": d.name,
                                   "tipo": "microexperto", "activo": activo,
                                   "color": _color_experto(d.name),
                                   "descripcion": "micro-experto byte-level (colonia)"
                                   + ("" if activo else " — inactivo (KILL)")})
        except Exception:
            pass
        for nombre, tipo, color, desc in _EXPERTOS_ROLES:
            salida.append({"id": nombre, "nombre": nombre, "tipo": tipo,
                           "color": color, "descripcion": desc})
        return salida

    # ── paneles: oficina, grafo, monitores ──
    @app.get("/api/oficina")
    def oficina():
        """La oficina vive por-proyecto (oficina_estado.json en su carpeta):
        se agregan los snapshots de todos los proyectos que tengan una."""
        try:
            from cognia.oficina.estado import Oficina
        except Exception as e:
            # antes: except → [] y "sin oficinas" indistinguible de "roto"
            return JSONResponse({"error": f"oficina no disponible: {e}"},
                                status_code=500)
        salida = []
        for pr in cargar_proyectos():
            try:
                f = Path(pr["ruta"]) / "oficina_estado.json"
                if f.is_file():
                    snap = Oficina(str(f)).snapshot()
                    salida.append({"proyecto": pr["nombre"],
                                   "metas": snap.get("metas", []),
                                   "tareas": snap.get("tareas", {})})
            except Exception as e:
                # un snapshot corrupto no esconde los demas ni a si mismo
                salida.append({"proyecto": pr["nombre"], "error": str(e)})
        return salida

    @app.get("/api/grafo")
    def grafo(tema: str = ""):
        try:
            from cognia.knowledge.graph import KnowledgeGraph
            kg = KnowledgeGraph()
            if tema:
                hechos = kg.get_facts(tema)[:30]
                vecinos = kg.get_neighbors(tema)[:30]
                return {"tema": tema, "hechos": hechos, "vecinos": vecinos}
            st = kg.stats()
            recientes = kg.get_all_triples(limit=40)
            return {"stats": st, "triples": recientes}
        except Exception as e:
            return {"error": f"grafo no disponible: {e}"}

    @app.get("/api/monitores")
    def monitores():
        return gestor.vivas()

    # ── grafo VISUAL: nodos+aristas con componentes coloreados por tema ──
    @app.get("/api/grafo_visual")
    def grafo_visual(limite: int = 80):
        try:
            from cognia.knowledge.graph import KnowledgeGraph
            crudos = KnowledgeGraph().get_all_triples(limit=1000)
        except Exception as e:
            return {"error": str(e), "nodos": [], "aristas": []}

        # Muestreo ESTRATIFICADO por relacion: sin esto, un KG dominado por
        # una relacion (665 related_to vs 9 is_a) llenaba el cupo con una
        # sola y los temas por tipo desaparecian del dibujo.
        por_rel: dict[str, list] = {}
        for t in crudos:
            por_rel.setdefault(str(t[1]), []).append(t)
        triples = []
        i = 0
        while len(triples) < limite and any(por_rel.values()):
            for rel in list(por_rel):
                if i < len(por_rel[rel]):
                    triples.append(por_rel[rel][i])
                    if len(triples) >= limite:
                        break
            i += 1

        nombres: dict[str, int] = {}
        aristas = []
        padre: list[int] = []

        def nodo(n: str) -> int:
            if n not in nombres:
                nombres[n] = len(nombres)
                padre.append(nombres[n])
            return nombres[n]

        def raiz(i: int) -> int:
            while padre[i] != i:
                padre[i] = padre[padre[i]]
                i = padre[i]
            return i

        pares = []
        for t in triples:
            s, p, o = str(t[0]), str(t[1]), str(t[2])
            a, b = nodo(s), nodo(o)
            pares.append((a, b))
            aristas.append({"de": a, "a": b, "rel": p})

        # Un super-hub (p. ej. "default", conectado a todo) colapsaria TODOS
        # los temas en uno. Los hubs no fusionan componentes: los temas salen
        # de la estructura real, y el hub se pinta neutro.
        grado: dict[int, int] = {}
        for a, b in pares:
            grado[a] = grado.get(a, 0) + 1
            grado[b] = grado.get(b, 0) + 1
        umbral_hub = max(6, len(pares) // 6)
        hubs = {i for i, g in grado.items() if g >= umbral_hub}
        for a, b in pares:
            if a in hubs or b in hubs:
                continue
            padre[raiz(a)] = raiz(b)

        # Tamano de cada componente sin contar hubs
        tam: dict[int, int] = {}
        for i in range(len(padre)):
            if i not in hubs:
                r = raiz(i)
                tam[r] = tam.get(r, 0) + 1

        # Un KG en estrella (todo colgando de un hub) deja puros singletons:
        # ahi el tema honesto es el TIPO DE RELACION con el hub (is_a,
        # capable_of...), que si agrupa por significado.
        rel_al_hub: dict[int, str] = {}
        for ar in aristas:
            a, b = ar["de"], ar["a"]
            if a in hubs and b not in hubs:
                rel_al_hub.setdefault(b, ar["rel"])
            elif b in hubs and a not in hubs:
                rel_al_hub.setdefault(a, ar["rel"])

        comp_idx: dict = {}
        nodos = []
        for nombre, i in nombres.items():
            if i in hubs:
                nodos.append({"id": i, "nombre": nombre, "tema": -1,
                              "hub": True})
                continue
            r = raiz(i)
            if tam.get(r, 1) > 1:
                clave = ("comp", r)
            else:
                clave = ("rel", rel_al_hub.get(i, "otros"))
            comp = comp_idx.setdefault(clave, len(comp_idx))
            etiqueta = clave[1] if clave[0] == "rel" else ""
            nodos.append({"id": i, "nombre": nombre, "tema": comp,
                          **({"grupo": etiqueta} if etiqueta else {})})
        return {"nodos": nodos, "aristas": aristas,
                "n_temas": len(comp_idx), "hubs": len(hubs)}

    # ── flujos de trabajo (skills del agente): ver y editar ──
    @app.get("/api/flujos")
    def flujos():
        # empaquetadas + las del usuario; en la vista gana la edicion del
        # usuario (para que el editor del movil haga round-trip).
        por_nombre: dict[str, dict] = {}
        for d in (_DIR_FLUJOS, _DIR_FLUJOS_EDIT):
            if not d.is_dir():
                continue
            for f in sorted(d.glob("*.md")):
                por_nombre[f.stem] = {
                    "nombre": f.stem,
                    "contenido": f.read_text(encoding="utf-8")}
        return sorted(por_nombre.values(), key=lambda x: x["nombre"])

    @app.put("/api/flujos/{nombre}")
    def guardar_flujo(nombre: str, cuerpo: dict):
        # nombre saneado: solo el stem, sin rutas — el movil no escribe fuera
        # de la carpeta de skills.
        limpio = "".join(c for c in nombre if c.isalnum() or c in "-_")
        if not limpio:
            return JSONResponse({"error": "nombre invalido"}, status_code=400)
        contenido = cuerpo.get("contenido", "")
        # una skill ES una inyeccion de instrucciones al agente: mismo
        # blocklist que persist_skill antes de persistir nada.
        # FAIL-CLOSED: si el escaneo no esta disponible (import roto, error
        # dentro del scan) NO se persiste. El 'except: hits = []' anterior
        # desactivaba el blocklist EN SILENCIO y dejaba pasar cualquier
        # contenido — un fallo de import se convertia en un bypass de
        # seguridad. Sin escaneo no hay PUT.
        try:
            from cognia.agent.skills import skill_safety_scan
            hits = skill_safety_scan(limpio + "\n" + contenido)
        except Exception as e:
            return JSONResponse(
                {"error": "escaneo de seguridad no disponible; el flujo NO "
                          f"se guardo ({type(e).__name__}: {e})"},
                status_code=503)
        if hits:
            return JSONResponse(
                {"error": f"contenido peligroso (blocklist): {hits[:3]}"},
                status_code=400)
        _DIR_FLUJOS_EDIT.mkdir(parents=True, exist_ok=True)
        (_DIR_FLUJOS_EDIT / f"{limpio}.md").write_text(
            contenido, encoding="utf-8")
        return {"ok": True, "nombre": limpio}

    # ── oficina 3D isometrica: lanzarla para un proyecto y embeberla ──
    _oficina3d: dict = {"proc": None, "puerto": 8766}

    @app.get("/api/oficina3d")
    def oficina3d_estado():
        p = _oficina3d["proc"]
        viva = p is not None and p.poll() is None
        return {"viva": viva, "puerto": _oficina3d["puerto"]}

    @app.post("/api/oficina3d")
    def oficina3d_arrancar(cuerpo: dict):
        import subprocess
        import sys
        p = _oficina3d["proc"]
        if p is not None and p.poll() is None:
            return {"ok": True, "puerto": _oficina3d["puerto"]}
        pid = cuerpo.get("proyecto_id", "")
        try:
            ruta = Path(_proyecto(pid)["ruta"]) if pid else Path.cwd()
        except Exception:
            ruta = Path.cwd()
        estado = ruta / "oficina_estado.json"
        raiz_repo = str(Path(__file__).resolve().parent.parent.parent)
        import os as _os
        env = dict(_os.environ, PYTHONUTF8="1",
                   PYTHONPATH=raiz_repo + _os.pathsep +
                   _os.environ.get("PYTHONPATH", ""))
        # --sin-modelo: el panel es para VER la oficina; el motor con modelo
        # se maneja desde el chat (/oficina) si se quiere.
        # --host 0.0.0.0: el iframe lo abre el MOVIL con la IP del PC en la LAN,
        # no localhost; sin esto la oficina quedaba invisible desde el telefono.
        # stderr a un log (no DEVNULL) para no perder el motivo si el arranque
        # falla en silencio (familia de degradacion silenciosa de Cognia).
        log_ofi = ruta / "oficina3d.log"
        cert, key = asegurar_cert(RAIZ_DATOS)   # mismo cert que el remoto (HTTPS)
        _oficina3d["proc"] = subprocess.Popen(
            [sys.executable, "-m", "cognia.oficina",
             "--puerto", str(_oficina3d["puerto"]), "--host", "0.0.0.0",
             "--cert", cert, "--key", key,
             "--estado", str(estado), "--sin-modelo"],
            cwd=str(ruta), env=env,
            stdout=subprocess.DEVNULL,
            stderr=open(log_ofi, "w", encoding="utf-8"))
        return {"ok": True, "puerto": _oficina3d["puerto"]}

    app.mount("/static", StaticFiles(directory=str(ESTATICOS)), name="static")
    return app


def _ip_lan() -> str | None:
    """La IP LAN del PC (para meterla en el certificado y en el mensaje)."""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80)); ip = s.getsockname()[0]; s.close()
        return ip
    except Exception:
        return None


def asegurar_cert(dirbase: Path) -> tuple[str, str]:
    """Certificado autofirmado en dirbase (cert.pem/key.pem). Necesario para
    HTTPS: el navegador SOLO habilita el microfono (getUserMedia/SpeechRecognition)
    en 'contexto seguro' — https:// o localhost. En http://<IP-LAN> el micro
    queda bloqueado y ni pide permiso. La clave privada vive FUERA del repo
    (~/.cognia/remoto), nunca se commitea."""
    cert, key = dirbase / "cert.pem", dirbase / "key.pem"
    if cert.exists() and key.exists():
        return str(cert), str(key)
    dirbase.mkdir(parents=True, exist_ok=True)
    import datetime
    import ipaddress
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    sans = [x509.DNSName("localhost"),
            x509.IPAddress(ipaddress.IPv4Address("127.0.0.1"))]
    ip = _ip_lan()
    if ip:
        try:
            sans.append(x509.IPAddress(ipaddress.IPv4Address(ip)))
        except Exception:
            pass
    nombre = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Cognia Remoto")])
    ahora = datetime.datetime.now(datetime.timezone.utc)
    c = (x509.CertificateBuilder()
         .subject_name(nombre).issuer_name(nombre)
         .public_key(k.public_key()).serial_number(x509.random_serial_number())
         .not_valid_before(ahora - datetime.timedelta(days=1))
         .not_valid_after(ahora + datetime.timedelta(days=3650))
         .add_extension(x509.SubjectAlternativeName(sans), critical=False)
         .sign(k, hashes.SHA256()))
    key.write_bytes(k.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption()))
    cert.write_bytes(c.public_bytes(serialization.Encoding.PEM))
    return str(cert), str(key)


def construir_parser() -> argparse.ArgumentParser:
    """`python -m cognia.remoto [--host IP] [--port N] [--limpiar [--dry-run]]`.
    Los defaults salen del env (COGNIA_REMOTO_HOST/PORT) y, si no, de las
    constantes: la CLI gana al env, el env gana al default."""
    ap = argparse.ArgumentParser(
        prog="python -m cognia.remoto",
        description="Control remoto movil de Cognia (FastAPI + REPLs reales).")
    ap.add_argument("--host",
                    default=os.environ.get("COGNIA_REMOTO_HOST") or HOST_DEFAULT,
                    help=f"interfaz de escucha (default {HOST_DEFAULT}; "
                         "env COGNIA_REMOTO_HOST)")
    ap.add_argument("--port", type=int,
                    default=int(os.environ.get("COGNIA_REMOTO_PORT")
                                or PUERTO_DEFAULT),
                    help=f"puerto (default {PUERTO_DEFAULT}; env "
                         "COGNIA_REMOTO_PORT)")
    ap.add_argument("--limpiar", action="store_true",
                    help="borrar carpetas de ~/.cognia/remoto sin proyecto en "
                         "proyectos.json (listando lo borrado) y salir")
    ap.add_argument("--dry-run", action="store_true",
                    help="con --limpiar: solo listar, no borrar")
    return ap


def parsear_args(argv: list[str] | None = None) -> argparse.Namespace:
    return construir_parser().parse_args(argv)


def limpiar_desde_cli(dry_run: bool, raiz: Path | None = None) -> int:
    """El subcomando --limpiar: imprime cada carpeta y el total."""
    raiz = raiz or RAIZ_DATOS
    afectadas = _sesiones.limpiar_huerfanas(raiz, dry_run=dry_run)
    verbo = "se borraria" if dry_run else "borrada"
    for ruta in afectadas:
        print(f"  {verbo}: {ruta}")
    print(f"{len(afectadas)} carpeta(s) huerfana(s) en {raiz}"
          + (" (dry-run: nada borrado)" if dry_run else ""))
    return 0


def escribir_pid_servidor(raiz: Path, host: str, port: int) -> Path | None:
    """servidor.pid = JSON {"pid","host","port"} (UNICO formato; lo lee
    leer_pid_servidor). None si no se pudo escribir (se dice)."""
    f = ruta_pid_servidor(raiz)
    try:
        f.write_text(json.dumps({"pid": os.getpid(), "host": host,
                                 "port": port}), encoding="utf-8")
        return f
    except OSError as e:
        print(f"[remoto] no pude escribir {f}: {e} "
              "(/remoto parar no encontrara este servidor)")
        return None


def borrar_pid_servidor_propio(raiz: Path) -> bool:
    """Borra servidor.pid SOLO si sigue nombrando a este proceso: un segundo
    servidor que arranco (y no piso el fichero) no debe llevarse al salir el
    .pid del primero. Idempotente (atexit + finally + handler de senal)."""
    f = ruta_pid_servidor(raiz)
    try:
        info = json.loads(f.read_text(encoding="utf-8"))
        if int(info.get("pid", -1)) != os.getpid():
            return False
        f.unlink(missing_ok=True)
        return True
    except FileNotFoundError:
        return False
    except (OSError, ValueError, TypeError) as e:
        print(f"[remoto] no pude borrar {f}: {e}")
        return False


def _servidor_uvicorn(app):
    """La subclase de uvicorn.Server con el apagado que despierta a los WS.
    Definida en una funcion (import perezoso de uvicorn: el modulo se importa
    en el CLI para leer servidor.pid sin arrancar nada)."""
    import uvicorn

    class _ServidorUvicorn(uvicorn.Server):
        def __init__(self, config):
            super().__init__(config)
            self.apagados = 0        # colas despertadas (lo mira el test)

        def handle_exit(self, sig, frame):
            # PRIMERO despertar a los WS, DESPUES should_exit. Asi cada WS
            # cierra por su cuenta (codigo 1001) y uvicorn no encuentra
            # conexiones que esperar: la salida con un movil conectado pasa
            # de 29,1 s (medido 2026-08-25) a decimas. En un hilo propio y
            # no aqui: este handler corre entre bytecodes del hilo principal
            # (el del loop), que puede estar DENTRO de un `with s.lock` del
            # endpoint ws — tomar ese Lock (no reentrante) desde el handler
            # seria un interbloqueo en el peor momento.
            def _despertar():
                try:
                    self.apagados = despertar_para_apagar(app)
                except Exception as e:
                    print(f"[remoto] no pude avisar a los WS del apagado: "
                          f"{type(e).__name__}: {e}", file=sys.stderr,
                          flush=True)
            threading.Thread(target=_despertar, name="remoto-apagado",
                             daemon=True).start()
            super().handle_exit(sig, frame)

    return _ServidorUvicorn


def servir(app, host: str, port: int, cert: str, key: str) -> None:
    """uvicorn.run(app, ...) con nuestro Server (ver _servidor_uvicorn).
    Mismo comportamiento que uvicorn.run: Ctrl-C no es un traceback y no
    poder arrancar (puerto ocupado) sale con codigo 3 como hace uvicorn."""
    import uvicorn
    # timeout_graceful_shutdown: sin el, uvicorn espera a que se cierren
    # las conexiones keep-alive del movil y un Ctrl-C/CTRL_BREAK tardaba
    # 30 s en salir con un cliente conectado (medido 2026-08-25: 0,2 s
    # sin cliente, 30,2 s con un httpx.Client abierto). 5 s bastan para
    # terminar las peticiones en curso; los WS se cierran solos al recibir
    # EVENTO_APAGADO y no llegan a consumirlo.
    config = uvicorn.Config(app, host=host, port=port,
                            ssl_certfile=cert, ssl_keyfile=key,
                            log_level="warning", timeout_graceful_shutdown=5)
    servidor = _servidor_uvicorn(app)(config)
    try:
        servidor.run()
    except KeyboardInterrupt:
        # uvicorn ya atrapo la senal y apago en orden; el KI que llega hasta
        # aqui es un Ctrl-C repetido durante el apagado (uvicorn.run hace lo
        # mismo). Se dice, no se calla.
        print("[remoto] interrumpido durante el apagado", flush=True)
    if not servidor.started:
        print("[remoto] el servidor no llego a arrancar (¿puerto ocupado? "
              "ver arriba)", file=sys.stderr, flush=True)
        raise SystemExit(3)


def main(argv: list[str] | None = None) -> int:
    args = parsear_args(argv)
    if args.limpiar:
        return limpiar_desde_cli(args.dry_run)
    import atexit
    import signal
    # ¿Hay OTRO servidor vivo sobre esta RAIZ? Entonces sus .pid de sesion
    # son de REPLs VIVOS, no huerfanos: ni se reconcilian ni se pisa su
    # servidor.pid (hallazgo rev1 2026-08-25, medido con dos servidores
    # reales: el segundo mataba las sesiones del primero y /remoto parar
    # pasaba a apuntar al segundo). Se avisa y se sigue: dos servidores en
    # puertos distintos son legitimos (VPN + LAN, una prueba).
    otro, motivo = estado_pid_servidor(RAIZ_DATOS)
    if otro is not None and otro["pid"] != os.getpid():
        print(f"[remoto] ya hay un servidor vivo (pid {otro['pid']} en "
              f"{otro['host']}:{otro['port']}, {motivo}): no reconcilio sus "
              "sesiones ni toco servidor.pid; /remoto parar seguira "
              "apuntando a el")
    else:
        if motivo != "no hay servidor.pid":
            print(f"[remoto] {motivo}")
        # RECONCILIACION: REPLs de un servidor anterior (su .pid sigue en
        # disco). No se pueden readoptar (su stdout era del proceso muerto):
        # se matan si son nuestros (ver reconciliar_huerfanos) y se anota en
        # su jsonl. Aqui y no en crear_app(): los tests crean apps.
        for h in _sesiones.reconciliar_huerfanos(RAIZ_DATOS):
            print(f"[remoto] sesion huerfana {h['proyecto']}/{h['sesion']} "
                  f"(pid {h['pid']}): {h['accion']}")
    app = crear_app(host=args.host, port=args.port)
    cert, key = asegurar_cert(RAIZ_DATOS)
    tok = asegurar_token(RAIZ_DATOS)
    ip = _ip_lan() or "<IP-del-PC>"
    host_url = ip if args.host in ("0.0.0.0", "::", "") else args.host
    # la URL con ?token= entra de una: el front lo guarda en localStorage y
    # las visitas siguientes ya no lo necesitan en la URL.
    print(f"Cognia Remoto en https://{args.host}:{args.port}  (desde el "
          f"celular: https://{host_url}:{args.port}/?token={tok} — aceptá el "
          f"aviso de certificado UNA vez; solo con https funciona el microfono)")
    print(f"Token de acceso: {tok}  (guardado en {RAIZ_DATOS / 'token.txt'})")
    # PID del servidor para `/remoto parar` del CLI local (contrato H): solo
    # si no hay otro vivo (ver arriba). Se borra al salir por TODAS las vias
    # que dan ocasion: finally (salida limpia y SIGINT/SIGTERM/SIGBREAK, que
    # uvicorn atrapa y convierte en un return normal), atexit (por si un
    # SystemExit sale por otro lado) y un handler propio para las senales
    # que lleguen ANTES de que uvicorn instale los suyos. Lo que NO da
    # ocasion es TerminateProcess (kill /F, lo que hace /remoto parar): ahi
    # el fichero queda y lo detecta la LECTURA (leer_pid_servidor comprueba
    # que el pid este vivo y sea un servidor) — por eso el borrado solo es
    # higiene y la verdad la pone el lector.
    raiz = RAIZ_DATOS
    if otro is None:
        escribir_pid_servidor(raiz, args.host, args.port)
        atexit.register(borrar_pid_servidor_propio, raiz)

    def _salir_por_senal(signum, _frame):
        borrar_pid_servidor_propio(raiz)          # no-op si no es nuestro
        raise SystemExit(128 + int(signum))

    # Tambien cuando NO somos el dueno del fichero: uvicorn, al terminar,
    # restaura el handler original y RE-LANZA la senal capturada; con el
    # default de Windows para SIGBREAK el proceso moria en seco dentro de
    # uvicorn.run (medido: rc 3 en el segundo servidor del e2e) y el finally
    # de abajo no corria. Con este handler la salida es un SystemExit limpio.
    for nombre in ("SIGINT", "SIGTERM", "SIGBREAK"):
        sig = getattr(signal, nombre, None)
        if sig is not None:
            try:
                signal.signal(sig, _salir_por_senal)
            except (ValueError, OSError) as e:       # no en el hilo principal
                print(f"[remoto] sin handler de {nombre}: {e}", flush=True)
    # stdout suele ser el servidor.log al que /remoto arrancar redirige: sin
    # flush, con el buffer de bloque (8 KB) las lineas de arriba tardaban en
    # aparecer (o se perdian si el proceso moria por kill), medido 2026-08-25
    sys.stdout.flush()
    try:
        servir(app, host=args.host, port=args.port, cert=cert, key=key)
    finally:
        borrar_pid_servidor_propio(raiz)
    return 0
