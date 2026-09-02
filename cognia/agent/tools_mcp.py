# -*- coding: utf-8 -*-
"""
tools_mcp.py — La puerta del agente a los servidores MCP de otros clientes.

POR QUE DOS TOOLS Y NO DOSCIENTAS. Los cinco servidores que el dueno tiene
configurados suman **186 herramientas** (Roblox 26, filesystem 14, context7 2,
word 120, playwright 24). Registrarlas una a una seria lo obvio y seria un
error medido: el A/B de este repo (2026-07-25, n=4+4) dice que pasar de un
catalogo chico a uno de 46 herramientas baja el camino feliz de 4,25/5 a
2,5/5. Por eso existen `CORE_TOOLS` (12 a mano) y el registro dinamico. Meter
186 no es "mas capacidad": es enterrar las 12 que el modelo usa siempre.

Asi que el catalogo crece en DOS entradas, no en 186:

    mcp_herramientas <servidor>            que sabe hacer ese servidor
    mcp <servidor> | <tool> | <args JSON>  ejecutar una de las suyas

El modelo descubre bajo demanda, igual que hace con `ver_salida` a partir del
texto de `ejecutar_fondo`: el catalogo se mantiene chico y la capacidad entera
sigue alcanzable. Es la misma via del registro dinamico del arnes, sin el
indice BM25 -- aqui el "buscador" es el propio servidor MCP, que ya expone su
`tools/list` con descripciones escritas por quien lo hizo.

OPT-IN DURO, como las tools VLM/TX: con `COGNIA_MCP` apagado el registry no
cambia ni un byte y el catalogo del agente es exactamente el de antes. La tool
existe igual (esta registrada), asi que `run_tool` contesta "DESHABILITADA —
activala con COGNIA_MCP=1" en vez de "no existe", que es la diferencia entre
"Cognia no sabe hacerlo" y "falta encender el flag".

SEGURIDAD: `danger=True` en las dos. Un servidor MCP es CODIGO DE TERCEROS que
puede borrar ficheros, abrir el navegador o ejecutar Luau en Roblox, y su
peligro no vive en un comando de shell que el sentinel pueda clasificar, sino
dentro de un JSON. Marcarlas peligrosas es lo unico honesto: el gate decide.
"""

from __future__ import annotations

import json

from cognia.agent.tools import tool

# Conexiones vivas: nombre de servidor -> cliente. Un servidor MCP stdio es un
# SUBPROCESO, y levantarlo por llamada costaria el arranque entero cada vez
# (medido: filesystem tarda 11 s en el primer `npx`, 0,0 s despues). Se
# reutiliza mientras la sesion viva.
_VIVOS: dict = {}


def _servidores() -> dict:
    from cognia.mcp_externos import descubrir
    return {s.nombre: s for s in descubrir()}


def _conectar(nombre: str):
    """Cliente conectado a ese servidor, reusando el de antes si sigue vivo."""
    cli = _VIVOS.get(nombre)
    if cli is not None and getattr(cli, "conectado", False):
        return cli
    srv = _servidores().get(nombre)
    if srv is None:
        disponibles = ", ".join(sorted(_servidores())) or "(ninguno)"
        raise KeyError(f"servidor MCP '{nombre}' no configurado. "
                       f"Hay: {disponibles}")
    from cognia.mcp_externos import cliente_de
    cli = cliente_de(srv)
    cli.conectar()
    _VIVOS[nombre] = cli
    return cli


def cerrar_todos() -> int:
    """Cierra las conexiones vivas. Devuelve cuantas cerro.

    La usa el cierre del REPL: un servidor stdio es un subproceso y dejarlo
    huerfano al salir es la clase de fuga que este repo ya pago cara
    ('matar el shell no mata el proceso')."""
    n = 0
    for cli in list(_VIVOS.values()):
        try:
            cli.cerrar()
            n += 1
        except Exception:
            pass
    _VIVOS.clear()
    return n


@tool("mcp_herramientas",
      "mcp_herramientas <servidor> - lista las herramientas de un servidor MCP",
      danger=False,
      desc="Lista las herramientas que ofrece un servidor MCP configurado en "
           "tus clientes de IA (Roblox_Studio, filesystem, playwright, word, "
           "context7...). Usala ANTES de 'mcp' para saber que nombre y que "
           "argumentos acepta la herramienta que quieres. Sin argumento, "
           "lista los servidores disponibles.",
      params=[{"nombre": "servidor", "tipo": "string", "requerido": False,
               "descripcion": "nombre del servidor; vacio = listar servidores"}])
def _t_mcp_herramientas(args: str, ctx: dict) -> str:
    nombre = (args or "").strip().strip('"').strip("'")
    srvs = _servidores()
    if not nombre:
        if not srvs:
            return ("RESULTADO mcp_herramientas: no hay servidores MCP "
                    "configurados en este equipo.")
        lineas = ["RESULTADO mcp_herramientas: servidores disponibles:"]
        for n, s in sorted(srvs.items()):
            lineas.append(f"  {n}  ({s.origen})")
        lineas.append("Usa: mcp_herramientas <servidor>")
        return "\n".join(lineas)
    try:
        cli = _conectar(nombre)
        hs = cli.listar_herramientas()
    except KeyError as exc:
        return f"RESULTADO mcp_herramientas ERROR: {exc}"
    except Exception as exc:
        return (f"RESULTADO mcp_herramientas ERROR: no se pudo hablar con "
                f"'{nombre}': {type(exc).__name__}: {exc}")
    if not hs:
        return f"RESULTADO mcp_herramientas: '{nombre}' no ofrece ninguna."
    lineas = [f"RESULTADO mcp_herramientas: {len(hs)} en '{nombre}':"]
    for h in hs:
        req = (h.esquema or {}).get("required") or []
        props = list(((h.esquema or {}).get("properties") or {}).keys())
        firma = ", ".join(f"{p}*" if p in req else p for p in props[:8])
        lineas.append(f"  {h.nombre}({firma})")
        doc = (h.descripcion or "").strip().splitlines()
        if doc:
            lineas.append(f"      {doc[0][:120]}")
    lineas.append(f"Para ejecutar: mcp {nombre} | <herramienta> | {{\"clave\": \"valor\"}}")
    return "\n".join(lineas)


@tool("mcp",
      "mcp <servidor> | <herramienta> | <argumentos JSON> - ejecuta una tool MCP",
      danger=True,
      desc="Ejecuta una herramienta de un servidor MCP externo (Roblox Studio, "
           "filesystem, playwright, word...). Los argumentos van como objeto "
           "JSON, tal como los declara el esquema de esa herramienta: "
           "consultalo antes con mcp_herramientas. Es codigo de terceros y "
           "puede modificar el sistema, asi que pasa por el gate de permisos.",
      params=[{"nombre": "servidor", "tipo": "string", "requerido": True,
               "descripcion": "nombre del servidor MCP"},
              {"nombre": "herramienta", "tipo": "string", "requerido": True,
               "descripcion": "nombre de la herramienta dentro del servidor"},
              {"nombre": "argumentos", "tipo": "string", "requerido": False,
               "descripcion": "objeto JSON con los argumentos de la herramienta"}])
def _t_mcp(args: str, ctx: dict) -> str:
    partes = [p.strip() for p in (args or "").split("|", 2)]
    if len(partes) < 2 or not partes[0] or not partes[1]:
        return ("RESULTADO mcp ERROR: faltan argumentos. Uso: "
                "mcp <servidor> | <herramienta> | {\"clave\": \"valor\"}")
    servidor, herramienta = partes[0], partes[1]
    crudo = partes[2] if len(partes) > 2 else ""
    argumentos = {}
    if crudo:
        try:
            argumentos = json.loads(crudo)
        except ValueError as exc:
            # Decir QUE se recibio: el fallo tipico es mandar el JSON partido
            # por el '|' del protocolo texto, y sin ver el crudo no se sabe.
            return (f"RESULTADO mcp ERROR: los argumentos no son JSON valido "
                    f"({exc}). Recibi: {crudo[:160]}")
        if not isinstance(argumentos, dict):
            return ("RESULTADO mcp ERROR: los argumentos tienen que ser un "
                    "objeto JSON, no " + type(argumentos).__name__)
    # UN SERVIDOR QUE NO CONECTA NO SE REINTENTA (2026-09-01). Medido en la
    # ronda de 20 min: el modelo llamo tres veces seguidas a un servidor MCP
    # que no conectaba (para abrir su propia pagina), las tres fallaron con el
    # mismo error y la racha de fallos cerro la tarea. Un fallo de CONEXION
    # es del entorno, no de los argumentos: repetirlo no lo arregla. Se
    # recuerda por proceso y las llamadas siguientes vuelven en el acto con
    # la alternativa concreta.
    if servidor in _CAIDOS:
        return (f"RESULTADO mcp ERROR: el servidor '{servidor}' no esta disponible "
                f"en esta tarea ({_CAIDOS[servidor][:120]}). No lo reintentes: usa "
                "ejecutar / leer_archivo / escribir_archivo. Para abrir y comprobar "
                "una pagina no hace falta: el arnes la abre en un navegador tras "
                "cada escritura y te devuelve los errores.")
    try:
        cli = _conectar(servidor)
    except KeyError as exc:
        return f"RESULTADO mcp ERROR: {exc}"
    except Exception as exc:
        _CAIDOS[servidor] = f"{type(exc).__name__}: {exc}"
        return (f"RESULTADO mcp ERROR: no pude conectar con '{servidor}' "
                f"({type(exc).__name__}: {exc}). Ese servidor queda descartado "
                "para esta tarea: no lo reintentes, usa ejecutar / leer_archivo. "
                "Para abrir y comprobar una pagina no hace falta: el arnes la "
                "abre en un navegador tras cada escritura y te devuelve los errores.")
    try:
        salida = cli.llamar(herramienta, argumentos)
    except Exception as exc:
        return (f"RESULTADO mcp ERROR: '{herramienta}' en '{servidor}' fallo: "
                f"{type(exc).__name__}: {exc}")
    return f"RESULTADO mcp {servidor}.{herramienta}: {salida}"


# Servidores MCP que fallaron al conectar en este proceso: nombre -> motivo.
_CAIDOS: dict = {}
