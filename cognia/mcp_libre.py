"""
mcp_libre.py — Cliente MCP para servidores gratuitos y sin registro.

POR QUE EXISTE: el dueno pidio (2026-07-20) poder usar "MCP gratuitos y sin
registro ni apikey, y que todo venga de forma nativa". Cognia no tenia ningun
soporte de MCP: ni cliente, ni transporte, ni nada.

MCP (Model Context Protocol) es JSON-RPC 2.0. Los servidores remotos hablan
HTTP y responden en SSE. El ciclo, VERIFICADO contra gitmcp.io el 2026-07-20
antes de escribir una linea de esto:

    1. POST initialize            -> devuelve la cabecera mcp-session-id
    2. POST notifications/initialized (con la sesion)
    3. POST tools/list            -> herramientas reales del servidor
    4. POST tools/call            -> ejecuta una

Sin ese paso 1 el servidor contesta `Bad Request: Mcp-Session-Id header is
required`, que es justo con lo que se tropieza quien asume el protocolo en vez
de medirlo.

Solo stdlib: urllib y json, igual que llm_local.py. Traer un SDK de MCP para
hacer cuatro POST seria cambiar una dependencia por comodidad.

NINGUN servidor de aqui pide clave ni registro. Si alguno empieza a pedirla,
sale de la lista: esa es la condicion que puso el dueno.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

TIMEOUT = 30
PROTOCOLO = "2024-11-05"

# Identificarse de verdad. Ademas de ser lo correcto, sin esto Cloudflare
# rechaza el User-Agent por defecto de urllib con un 403.
USER_AGENT = "Cognia/1.0 (+https://github.com/cognia; cliente MCP nativo)"

# Servidores libres verificados a mano. Cada entrada dice que aporta, porque
# una lista de URLs sin eso no ayuda a decidir cual usar.
SERVIDORES_LIBRES: Dict[str, Dict[str, str]] = {
    "gitmcp": {
        "url": "https://gitmcp.io/docs",
        "que_hace": "Lee documentacion y codigo de cualquier proyecto de "
                    "GitHub sin alucinar. Sin registro ni clave.",
        "verificado": "2026-07-20",
    },
    "context7": {
        "url": "https://mcp.context7.com/mcp",
        "que_hace": "Documentacion al dia de librerias y frameworks, resuelta "
                    "por nombre. Util cuando el modelo recuerda una API vieja.",
        "verificado": "2026-07-20",
    },
    "deepwiki": {
        "url": "https://mcp.deepwiki.com/mcp",
        "que_hace": "Wiki generada de repos de GitHub: preguntas en lenguaje "
                    "natural sobre como funciona un proyecto entero.",
        "verificado": "2026-07-20",
    },
}


class ErrorMCP(RuntimeError):
    """Fallo hablando con un servidor MCP."""


@dataclass
class Herramienta:
    nombre:      str
    descripcion: str
    esquema:     dict = field(default_factory=dict)

    def resumen(self) -> str:
        return f"{self.nombre}: {self.descripcion[:110]}"


def _parsear_respuesta(cuerpo: str) -> dict:
    """
    Saca el JSON de una respuesta que puede venir en SSE o en JSON pelado.

    Los servidores remotos responden `event: message\\ndata: {...}`; algunos
    devuelven el JSON directamente. Se aceptan los dos.
    """
    cuerpo = cuerpo.strip()
    if not cuerpo:
        raise ErrorMCP("respuesta vacia")

    if cuerpo.startswith("{"):
        return json.loads(cuerpo)

    for linea in cuerpo.splitlines():
        if linea.startswith("data:"):
            return json.loads(linea[5:].strip())

    raise ErrorMCP(f"no se encontro JSON en la respuesta: {cuerpo[:120]}")


class ClienteMCP:
    """
    Cliente minimo para un servidor MCP remoto sin autenticacion.

        c = ClienteMCP("https://gitmcp.io/docs")
        c.conectar()
        for h in c.listar_herramientas():
            print(h.resumen())
    """

    def __init__(self, url: str, nombre_cliente: str = "cognia"):
        self.url    = url
        self.nombre = nombre_cliente
        self.sesion: Optional[str] = None
        self.servidor: Dict[str, Any] = {}
        self._id = 0

    # ── transporte ──────────────────────────────────────────────────────

    def _siguiente_id(self) -> int:
        self._id += 1
        return self._id

    def _post(self, cuerpo: dict, esperar_respuesta: bool = True):
        datos = json.dumps(cuerpo).encode("utf-8")
        cabeceras = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            # Sin User-Agent propio, urllib manda "Python-urllib/3.12" y
            # Cloudflare lo corta con un 403 (error 1010). Medido el
            # 2026-07-20: la misma peticion con curl pasaba y con urllib no,
            # que es lo que delata que el problema es la cabecera y no el
            # protocolo.
            "User-Agent": USER_AGENT,
        }
        if self.sesion:
            cabeceras["Mcp-Session-Id"] = self.sesion

        req = urllib.request.Request(self.url, data=datos, headers=cabeceras)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                # La sesion llega en la cabecera del initialize, no en el JSON.
                nueva = r.headers.get("mcp-session-id")
                if nueva:
                    self.sesion = nueva
                if not esperar_respuesta:
                    r.read()
                    return None
                return _parsear_respuesta(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            raise ErrorMCP(f"HTTP {exc.code} de {self.url}: "
                           f"{exc.read()[:160].decode('utf-8', 'replace')}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ErrorMCP(f"no se pudo hablar con {self.url}: {exc}") from exc

    def _llamar_rpc(self, metodo: str, params: dict = None) -> Any:
        resp = self._post({
            "jsonrpc": "2.0",
            "id":      self._siguiente_id(),
            "method":  metodo,
            "params":  params or {},
        })
        if resp is None:
            raise ErrorMCP(f"{metodo}: sin respuesta")
        if "error" in resp:
            err = resp["error"]
            raise ErrorMCP(f"{metodo}: {err.get('message', err)}")
        return resp.get("result", {})

    # ── protocolo ───────────────────────────────────────────────────────

    def conectar(self) -> Dict[str, Any]:
        """Handshake. Deja la sesion lista para el resto de llamadas."""
        resultado = self._llamar_rpc("initialize", {
            "protocolVersion": PROTOCOLO,
            "capabilities":    {},
            "clientInfo":      {"name": self.nombre, "version": "1.0"},
        })
        self.servidor = resultado.get("serverInfo", {})

        # El servidor espera esta notificacion antes de aceptar peticiones.
        try:
            self._post({"jsonrpc": "2.0",
                        "method": "notifications/initialized",
                        "params": {}}, esperar_respuesta=False)
        except ErrorMCP:
            pass    # hay servidores que no la exigen; no es motivo para abortar

        return resultado

    def listar_herramientas(self) -> List[Herramienta]:
        if not self.sesion:
            self.conectar()
        crudas = self._llamar_rpc("tools/list").get("tools", [])
        return [Herramienta(nombre=h.get("name", "?"),
                            descripcion=h.get("description", ""),
                            esquema=h.get("inputSchema", {}))
                for h in crudas]

    def llamar(self, herramienta: str, argumentos: dict = None) -> str:
        """Ejecuta una herramienta y devuelve su salida como texto."""
        if not self.sesion:
            self.conectar()

        resultado = self._llamar_rpc(
            "tools/call", {"name": herramienta, "arguments": argumentos or {}})

        partes = []
        for bloque in resultado.get("content", []):
            if bloque.get("type") == "text":
                partes.append(bloque.get("text", ""))
        return "\n".join(partes) if partes else json.dumps(resultado)[:2000]


# ── API de conveniencia ─────────────────────────────────────────────────

def cliente(nombre_servidor: str) -> ClienteMCP:
    """Cliente para uno de los servidores libres conocidos."""
    if nombre_servidor not in SERVIDORES_LIBRES:
        conocidos = ", ".join(sorted(SERVIDORES_LIBRES))
        raise ErrorMCP(f"servidor '{nombre_servidor}' desconocido. Hay: {conocidos}")
    return ClienteMCP(SERVIDORES_LIBRES[nombre_servidor]["url"])


def formatear_servidores() -> str:
    """Listado para el comando /mcp."""
    lineas = [f"{len(SERVIDORES_LIBRES)} servidor(es) MCP libre(s), "
              f"sin registro ni clave:", ""]
    for nombre, info in sorted(SERVIDORES_LIBRES.items()):
        lineas.append(f"  {nombre}  ({info['url']})")
        lineas.append(f"      {info['que_hace']}")
        lineas.append(f"      verificado: {info['verificado']}")
    lineas += ["", "  /mcp herramientas <servidor>   — que sabe hacer",
               "  /mcp probar <servidor>         — comprobar que responde"]
    return "\n".join(lineas)
