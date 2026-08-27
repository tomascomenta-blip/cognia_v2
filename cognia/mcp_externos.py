# -*- coding: utf-8 -*-
"""
mcp_externos.py — Los servidores MCP que YA tienes configurados para otros
clientes de IA, usables desde Cognia.

POR QUE EXISTE (2026-08-26, pedido del dueno: "que los MCP de otras IA sean
compatibles con el CLI de Cognia, como el MCP de Roblox").

`mcp_libre.py` habla MCP, pero solo por HTTP+SSE y contra una lista fija de
tres servidores remotos. Los MCP de verdad que el dueno tiene puestos --
Roblox Studio, filesystem, playwright, word, context7 -- son TODOS de
transporte **stdio**: el cliente lanza un subproceso y habla JSON-RPC por su
stdin/stdout. Cognia no podia usar ninguno.

Este modulo pone las dos piezas que faltaban:

  1. `ClienteStdio` — el mismo protocolo MCP sobre un subproceso. Expone la
     MISMA API que `mcp_libre.ClienteMCP` (`conectar`, `listar_herramientas`,
     `llamar`), asi que quien ya sabe hablar con un servidor MCP no se entera
     de que cambio el transporte.
  2. `descubrir()` — lee las configuraciones de los clientes de IA instalados
     y devuelve los servidores declarados, sin que el dueno tenga que copiar
     nada a mano. Si manana anade un MCP a Claude Code, Cognia lo ve.

EL FRAMING DEL TRANSPORTE stdio, que es donde se equivoca todo el mundo: MCP
usa **JSON por linea** (un mensaje JSON-RPC completo por renglon, terminado en
\\n). NO usa las cabeceras `Content-Length:` del Language Server Protocol, que
es de lo que se parte por analogia. Y stderr NO es parte del canal: los
servidores escriben ahi sus logs (npx suelta avisos de instalacion), asi que
mezclarlo con stdout rompe el parseo.

Solo stdlib: subprocess, json, threading, queue. Misma linea que el resto del
repo -- traer un SDK de MCP para cuatro mensajes JSON-RPC seria cambiar una
dependencia por comodidad.
"""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from cognia.mcp_libre import PROTOCOLO, ErrorMCP, Herramienta

__all__ = [
    "ClienteStdio", "ServidorExterno", "descubrir", "formatear_descubiertos",
    "ORIGENES", "cliente_de",
]

# Cuanto se espera una respuesta del subproceso. 30 s como el cliente HTTP,
# pero el arranque tiene su propio tope: un `npx -y` que se baja el paquete la
# primera vez tarda MUCHO mas que una llamada normal.
TIMEOUT = 30.0
TIMEOUT_ARRANQUE = 120.0


@dataclass
class ServidorExterno:
    """Un servidor MCP declarado en la config de otro cliente de IA."""
    nombre: str
    comando: str
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    origen: str = ""          # que cliente lo declaraba (para poder decirlo)
    alcance: str = "global"   # 'global' o la ruta del proyecto
    url: str = ""             # si es remoto en vez de stdio

    @property
    def es_stdio(self) -> bool:
        return not self.url

    def resumen(self) -> str:
        que = self.url or " ".join([self.comando] + list(self.args))
        return f"{self.nombre}  [{self.origen}]  {que[:88]}"


class ClienteStdio:
    """Cliente MCP sobre un subproceso, con la API de `mcp_libre.ClienteMCP`.

        c = ClienteStdio("cmd.exe", ["/c", "...\\mcp.bat"])
        c.conectar()
        for h in c.listar_herramientas():
            print(h.resumen())
        c.cerrar()

    Usable como context manager, que es lo que evita dejar subprocesos
    huerfanos cuando algo falla a mitad.
    """

    def __init__(self, comando: str, args: List[str] = None,
                 env: Dict[str, str] = None, nombre_cliente: str = "cognia",
                 cwd: str = None):
        self.comando = comando
        self.args = list(args or [])
        self.env_extra = dict(env or {})
        self.nombre = nombre_cliente
        self.cwd = cwd
        self.servidor: Dict[str, Any] = {}
        self.conectado = False
        self._proc: Optional[subprocess.Popen] = None
        self._cola: "queue.Queue[str]" = queue.Queue()
        self._stderr: List[str] = []
        self._id = 0
        self._lock = threading.Lock()

    # ── ciclo de vida ───────────────────────────────────────────────────

    def __enter__(self):
        self.conectar()
        return self

    def __exit__(self, *_exc):
        self.cerrar()
        return False

    def _resolver(self) -> str:
        """La ruta real del ejecutable.

        EN WINDOWS ESTO NO ES OPCIONAL: los servidores MCP se declaran como
        `npx`, pero lo que existe en el PATH es `npx.cmd`. `Popen` sin shell
        NO aplica PATHEXT, asi que el comando tal cual falla con
        `[WinError 2] El sistema no puede encontrar el archivo especificado`.
        MEDIDO: de los cinco servidores del dueno, TRES (context7, filesystem,
        playwright) se lanzan con npx y morian asi; el de Roblox se salvaba
        solo porque su config ya dice `cmd.exe`.
        `shutil.which` si mira PATHEXT, que es exactamente lo que falta. Y se
        resuelve aqui en vez de tirar de `shell=True`, que meteria el comando
        entero por el interprete de ordenes -- una via de inyeccion para algo
        que viene de un fichero de configuracion.
        """
        if os.path.isabs(self.comando) and os.path.exists(self.comando):
            return self.comando
        return shutil.which(self.comando) or self.comando

    def _arrancar(self) -> None:
        if self._proc is not None:
            return
        entorno = dict(os.environ)
        entorno.update({str(k): str(v) for k, v in self.env_extra.items()})
        try:
            self._proc = subprocess.Popen(
                [self._resolver()] + self.args,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=entorno, cwd=self.cwd,
                text=True, encoding="utf-8", errors="replace",
                bufsize=1,          # por LINEA: el framing de MCP es NDJSON
            )
        except (OSError, ValueError) as exc:
            raise ErrorMCP(f"no se pudo lanzar '{self.comando}': {exc}") from exc

        # Dos hilos lectores. stdout va a una cola (el canal JSON-RPC) y
        # stderr se guarda aparte: los servidores escriben logs ahi y
        # mezclarlo con el canal rompe el parseo. Ademas, sin drenar stderr un
        # servidor hablador llena el buffer del pipe y se BLOQUEA -- un cuelgue
        # que parece "el servidor no responde" y es culpa del cliente.
        threading.Thread(target=self._leer_stdout, daemon=True).start()
        threading.Thread(target=self._leer_stderr, daemon=True).start()

    def _leer_stdout(self) -> None:
        try:
            for linea in self._proc.stdout:
                if linea.strip():
                    self._cola.put(linea)
        except (ValueError, OSError):
            pass                      # pipe cerrado: el proceso murio
        finally:
            self._cola.put("")        # centinela: se acabo el canal

    def _leer_stderr(self) -> None:
        try:
            for linea in self._proc.stderr:
                self._stderr.append(linea.rstrip())
                del self._stderr[:-40]     # solo la cola, para el diagnostico
        except (ValueError, OSError):
            pass

    def cerrar(self) -> None:
        """Termina el subproceso. Idempotente y nunca lanza."""
        proc, self._proc = self._proc, None
        self.conectado = False
        if proc is None:
            return
        for cerrar in (proc.stdin, proc.stdout, proc.stderr):
            try:
                cerrar.close()
            except Exception:
                pass
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    # ── transporte ──────────────────────────────────────────────────────

    def _siguiente_id(self) -> int:
        self._id += 1
        return self._id

    def _diagnostico(self) -> str:
        """Las ultimas lineas de stderr. Sin esto, un servidor que muere al
        arrancar (falta node, ruta mala, paquete inexistente) sale como un
        timeout mudo y no hay forma de saber por que."""
        cola = [l for l in self._stderr if l.strip()][-6:]
        return ("\n  " + "\n  ".join(cola)) if cola else ""

    def _enviar(self, cuerpo: dict, esperar: bool = True,
                timeout: float = None) -> Optional[dict]:
        self._arrancar()
        linea = json.dumps(cuerpo, ensure_ascii=False) + "\n"
        with self._lock:
            try:
                self._proc.stdin.write(linea)
                self._proc.stdin.flush()
            except (OSError, ValueError, AttributeError) as exc:
                raise ErrorMCP(f"el servidor '{self.comando}' cerro la "
                               f"entrada: {exc}{self._diagnostico()}") from exc
            if not esperar:
                return None
            esperado = cuerpo.get("id")
            limite = timeout if timeout is not None else TIMEOUT
            # El servidor puede intercalar notificaciones y respuestas de otras
            # peticiones: se lee hasta encontrar la del id pedido en vez de
            # tomar el primer renglon que llegue.
            while True:
                try:
                    cruda = self._cola.get(timeout=limite)
                except queue.Empty:
                    raise ErrorMCP(
                        f"'{self.comando}' no contesto en {limite:.0f}s"
                        f"{self._diagnostico()}")
                if cruda == "":
                    raise ErrorMCP(f"el servidor '{self.comando}' se cerro sin "
                                   f"contestar{self._diagnostico()}")
                try:
                    msg = json.loads(cruda)
                except ValueError:
                    continue          # renglon que no es JSON: log del server
                if not isinstance(msg, dict):
                    continue
                if msg.get("id") == esperado:
                    return msg
                # notificacion o respuesta ajena: se descarta y se sigue

    def _llamar_rpc(self, metodo: str, params: dict = None,
                    timeout: float = None) -> Any:
        resp = self._enviar({"jsonrpc": "2.0", "id": self._siguiente_id(),
                             "method": metodo, "params": params or {}},
                            timeout=timeout)
        if resp is None:
            raise ErrorMCP(f"{metodo}: sin respuesta")
        if "error" in resp:
            err = resp["error"]
            raise ErrorMCP(f"{metodo}: {err.get('message', err)}")
        return resp.get("result", {})

    # ── protocolo (identico al del cliente HTTP) ────────────────────────

    def conectar(self) -> Dict[str, Any]:
        """Handshake. El arranque lleva su propio timeout, mas largo: un
        `npx -y` que se baja el paquete la primera vez tarda minutos, y
        cortarlo a los 30 s haria pensar que el servidor esta roto."""
        resultado = self._llamar_rpc("initialize", {
            "protocolVersion": PROTOCOLO,
            "capabilities": {},
            "clientInfo": {"name": self.nombre, "version": "1.0"},
        }, timeout=TIMEOUT_ARRANQUE)
        self.servidor = resultado.get("serverInfo", {})
        try:
            self._enviar({"jsonrpc": "2.0",
                          "method": "notifications/initialized",
                          "params": {}}, esperar=False)
        except ErrorMCP:
            pass        # hay servidores que no la exigen
        self.conectado = True
        return resultado

    def listar_herramientas(self) -> List[Herramienta]:
        if not self.conectado:
            self.conectar()
        crudas = self._llamar_rpc("tools/list").get("tools", [])
        return [Herramienta(nombre=h.get("name", "?"),
                            descripcion=h.get("description", ""),
                            esquema=h.get("inputSchema", {}))
                for h in crudas]

    def llamar(self, herramienta: str, argumentos: dict = None,
               timeout: float = None) -> str:
        """Ejecuta una herramienta y devuelve su salida como texto."""
        if not self.conectado:
            self.conectar()
        resultado = self._llamar_rpc(
            "tools/call", {"name": herramienta, "arguments": argumentos or {}},
            timeout=timeout)
        partes = []
        for bloque in resultado.get("content", []):
            if bloque.get("type") == "text":
                partes.append(bloque.get("text", ""))
            elif bloque.get("type") == "image":
                partes.append(f"[imagen {bloque.get('mimeType', '?')}, "
                              f"{len(bloque.get('data', ''))} bytes en base64]")
        texto = "\n".join(partes) if partes else json.dumps(resultado)[:2000]
        # isError es del protocolo: un fallo de la tool NO es un fallo del
        # transporte, pero el llamador tiene que poder distinguirlo.
        if resultado.get("isError"):
            return f"ERROR de la herramienta '{herramienta}': {texto}"
        return texto


# ── Descubrimiento: de donde salen los servidores ───────────────────────
# Cada entrada dice DONDE mira y COMO se lee ese fichero. La lista es el punto
# de extension: un cliente de IA nuevo se agrega aqui y todo lo demas sigue
# igual. Las rutas se expanden con el entorno, asi que en otra maquina o con
# otro usuario tambien resuelven.

def _appdata(*partes: str) -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~/AppData/Roaming")
    return os.path.join(base, *partes)


ORIGENES = [
    {"cliente": "Claude Code",
     "ruta": os.path.expanduser("~/.claude.json"),
     "forma": "claude_code"},
    {"cliente": "Claude Desktop",
     "ruta": _appdata("Claude", "claude_desktop_config.json"),
     "forma": "plano"},
    {"cliente": "Cursor",
     "ruta": os.path.expanduser("~/.cursor/mcp.json"),
     "forma": "plano"},
    {"cliente": "Windsurf",
     "ruta": os.path.expanduser("~/.codeium/windsurf/mcp_config.json"),
     "forma": "plano"},
    {"cliente": "VS Code",
     "ruta": _appdata("Code", "User", "mcp.json"),
     "forma": "vscode"},
]


def _entrada_a_servidor(nombre: str, conf: dict, origen: str,
                        alcance: str = "global") -> Optional[ServidorExterno]:
    """Una entrada de config -> ServidorExterno, o None si no se entiende.

    Los clientes no coinciden del todo en el esquema: unos ponen "type",
    otros lo omiten; los remotos usan "url" y a veces "serverUrl". Se acepta
    lo que se pueda leer y se descarta el resto EN SILENCIO NO: quien llama
    recibe None y decide si avisar.
    """
    if not isinstance(conf, dict):
        return None
    url = conf.get("url") or conf.get("serverUrl") or ""
    if url:
        return ServidorExterno(nombre=nombre, comando="", args=[], env={},
                               origen=origen, alcance=alcance, url=str(url))
    comando = conf.get("command")
    if not comando:
        return None
    return ServidorExterno(
        nombre=nombre, comando=str(comando),
        args=[str(a) for a in (conf.get("args") or [])],
        env={str(k): str(v) for k, v in (conf.get("env") or {}).items()},
        origen=origen, alcance=alcance)


def _leer_json(ruta: str) -> Optional[dict]:
    try:
        with open(ruta, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def descubrir(incluir_proyectos: bool = True) -> List[ServidorExterno]:
    """Todos los servidores MCP declarados por los clientes de IA instalados.

    Dedupe por nombre: si el mismo servidor esta en dos clientes, gana el
    primero de ORIGENES (y el segundo no se pierde: queda anotado el origen
    del que gano, que es el dato util para diagnosticar).
    """
    fuera: List[ServidorExterno] = []
    vistos = set()

    def _agregar(s: Optional[ServidorExterno]) -> None:
        if s is None or s.nombre in vistos:
            return
        vistos.add(s.nombre)
        fuera.append(s)

    for org in ORIGENES:
        datos = _leer_json(org["ruta"])
        if not isinstance(datos, dict):
            continue
        cliente_nom = org["cliente"]

        if org["forma"] == "vscode":
            # VS Code anida bajo "servers" y usa "type": "stdio"|"http".
            for nom, conf in (datos.get("servers") or {}).items():
                _agregar(_entrada_a_servidor(nom, conf, cliente_nom))
            continue

        for nom, conf in (datos.get("mcpServers") or {}).items():
            _agregar(_entrada_a_servidor(nom, conf, cliente_nom))

        if org["forma"] == "claude_code" and incluir_proyectos:
            # Claude Code ademas declara servidores POR PROYECTO. El MCP de
            # Roblox del dueno vive justo ahi (projects["C:/Users/usuario/
            # Desktop"]), asi que ignorar esta rama dejaria fuera el caso que
            # motivo todo esto.
            for proy, conf_p in (datos.get("projects") or {}).items():
                if not isinstance(conf_p, dict):
                    continue
                for nom, conf in (conf_p.get("mcpServers") or {}).items():
                    _agregar(_entrada_a_servidor(nom, conf, cliente_nom,
                                                 alcance=proy))
    return fuera


def cliente_de(srv: ServidorExterno):
    """El cliente que corresponde al transporte de ese servidor."""
    if srv.es_stdio:
        return ClienteStdio(srv.comando, srv.args, srv.env)
    from cognia.mcp_libre import ClienteMCP
    return ClienteMCP(srv.url)


def formatear_descubiertos(servidores: List[ServidorExterno] = None) -> str:
    """Listado para el comando /mcp."""
    servidores = descubrir() if servidores is None else servidores
    if not servidores:
        rutas = "\n".join(f"    {o['cliente']}: {o['ruta']}" for o in ORIGENES)
        return ("No encontre ningun servidor MCP configurado. Se miro en:\n"
                + rutas)
    por_origen: Dict[str, List[ServidorExterno]] = {}
    for s in servidores:
        por_origen.setdefault(s.origen, []).append(s)
    lineas = [f"{len(servidores)} servidor(es) MCP configurado(s) en tus "
              f"clientes de IA:", ""]
    for origen in sorted(por_origen):
        lineas.append(f"  desde {origen}:")
        for s in sorted(por_origen[origen], key=lambda x: x.nombre):
            que = s.url or " ".join([s.comando] + s.args)
            marca = "" if s.alcance == "global" else f"  (proyecto {s.alcance})"
            lineas.append(f"    {s.nombre:<16} {que[:72]}{marca}")
    lineas += ["", "  /mcp herramientas <servidor>   — que sabe hacer",
               "  /mcp probar <servidor>         — conectarse ahora mismo"]
    return "\n".join(lineas)
