# -*- coding: utf-8 -*-
"""
cognia/agent/flujoteca_editor.py
================================
El SERVIDOR local y efimero que sirve el editor visual de flujos y hace de
puente entre el navegador, la flujoteca y el modelo local.

POR QUE UN SERVIDOR Y NO UN FICHERO HTML SUELTO (2026-08-29)
------------------------------------------------------------
Las tres razones son bloqueantes, no preferencias:

1. EL CHAT NECESITA AL MODELO. Una pagina abierta por `file://` tiene origen
   `null`; `llama-server` en :8080 no emite `Access-Control-Allow-Origin`
   para ese origen y el `fetch` muere sin error visible. Ademas el prompt de
   flujos necesita el catalogo de tools y el saneado, que son Python.
2. GUARDAR TIENE QUE VALIDAR. `flows.validar()` es el unico validador que
   manda (ciclos, wires colgados, tool inexistente). Si el editor guardara
   desde el navegador escribiendo por descarga, el fallo apareceria al
   EJECUTAR, que es exactamente lo que la cabecera de `flujo_ia.py` declara
   inaceptable.
3. EL CATALOGO DE NODOS ES PYTHON. `tools.catalogo_schemas()` +
   `familias.estado()` + identidad: embeberlo congelado deja la paleta
   desincronizada en cuanto se activa una familia.

SEGURIDAD (un servidor que escribe en ~/.cognia/flujoteca es superficie real)
----------------------------------------------------------------------------
  - bind estricto a 127.0.0.1.
  - TOKEN DE UN SOLO ARRANQUE, `secrets.token_urlsafe(24)`, generado en
    `crear_server()`. Viaja en la query de la URL de apertura y despues en
    la cabecera `X-Cognia-Token` de cada fetch. Sin token valido -> 403.
  - Validacion de `Origin`/`Host`: solo `http://127.0.0.1:<puerto>` y
    `http://localhost:<puerto>`. Es la defensa contra DNS rebinding.
  - `log_message` mudo y `daemon_threads = True`: si un handler se cuelga,
    no impide el apagado (memoria: matar el shell no mata el proceso).
  - EL GUARDIA COMPARA EN BYTES Y CORRE DENTRO DEL `try`. `compare_digest`
    sobre `str` LANZA `TypeError` con cualquier caracter no-ASCII, y las
    cabeceras HTTP se decodifican como latin-1: un solo byte >127 en
    `X-Cognia-Token` (o en `?t=`) tumbaba el guardia ANTES de responder, sin
    codigo HTTP y volcando el traceback entero al stderr del REPL del dueno,
    sin conocer el token. Por eso `_token_ok` codifica a bytes y `_pasa()` va
    DENTRO del `try/except` de las rutas, no antes.
  - `_Handler.timeout` (`TIMEOUT_CONEXION_S`) y tope de `Content-Length`
    (`TOPE_CUERPO`): la linea de peticion se lee ANTES del token, asi que sin
    timeout cualquier proceso local dejaba hilos clavados PARA SIEMPRE dentro
    del proceso del REPL (medido: 40 conexiones a medias -> 42 hilos vivos
    diez segundos despues). Y un POST con `Content-Length: 4000` y 5 bytes
    clavaba su hilo en el `read`.
  - EL RELOJ DEL AUTO-APAGADO SOLO LO REARMA UNA PETICION QUE PASA EL
    GUARDIA. Con `_marcar()` antes de `_pasa()`, cualquiera podia mantener el
    editor vivo indefinidamente golpeando el puerto sin credencial.
  - `POST /api/ejecutar` ES UN 404 A PROPOSITO, y no un pendiente. Ejecutar
    un flujo desde un boton del navegador saltaria la confirmacion TTY que
    protege `borrar_archivo`, `ejecutar` y `mcp`, y `run_tool` necesita un
    `ctx` real (`ai`, `working_memory`, `agent_state`, `print_fn`) que el
    servidor no tiene. La via que SI existe es el REPL:
    `/flujoteca ejecutar <nombre> [prompt]`, y eso es lo que dice el 404.
    (El texto viejo remitia a `COGNIA_EDITOR_EJECUTAR=1`, una variable que no
    lee NADIE en el repo: prometia una puerta que no existe.)

CICLO DE VIDA
-------------
`abrir(nombre)` levanta el server en un THREAD DAEMON, abre el navegador y
DEVUELVE AL REPL INMEDIATAMENTE. Nunca `serve_forever()` en el hilo
principal: colgaria el REPL. Un unico servidor vivo por proceso (singleton
de modulo); `parar()` hace `shutdown()` + `server_close()`. Hoy las dos
unicas vias de apagado en produccion son el `atexit` que se registra en la
primera `abrir()` y el vigia de los 30 min de ocio.
TODO(F-CABLE): cuando `cognia/cli.py` importe este modulo, la rama `/salir`
llamara ademas a `parar()`; hasta entonces esa via NO existe (nadie importa
el modulo fuera de sus tests) y decir lo contrario aqui seria mentira.
`puerto=0` para no chocar con 8080/8765/8766/8777/8899, que ya estan
ocupados en esta maquina.

`shutdown()` SOLO SI EL BUCLE ARRANCO. En `socketserver`, `shutdown()` hace
`__is_shut_down.wait()` SIN timeout y ese `Event` solo se pone en el
`finally` de `serve_forever()`: sobre un servidor con bind+listen y sin
bucle, bloquea ETERNAMENTE. Como eso corre dentro del `atexit`, colgaba el
proceso entero durante la finalizacion del interprete, donde ni Ctrl-C
sirve (reproducido: `EXIT=124`). De ahi dos reglas: `abrir()` publica el
singleton DESPUES de que `hilo.start()` haya devuelto -si lanza
(`RuntimeError: can't start new thread`), se cierra el socket y el singleton
queda vacio en vez de mentir con `vivo: True`- y `_apagar()` mira el hilo
antes de pedir `shutdown()`, con un tope de tiempo por si el bucle esta
atascado en un handler.

LAS POSICIONES VIVEN FUERA DEL DAG
----------------------------------
`meta["ui"]["pos"] = {id: {"x": int, "y": int}}`, nunca dentro del nodo:
(a) `flujo_ia.sanear_flujo` reconstruye cada nodo con una whitelist cerrada
y descartaria `x/y` en cada edicion conversacional; (b) `flujoteca.comparar`
compara una tupla fija de 7 campos, asi que cada arrastre contaria como
cambio y el historial se llenaria de ruido. De ahi que `/api/pos` NO cree
version.

CONTRATO (copiado del plan, FASE 0 y PEDIDO 3.3)
------------------------------------------------
Firmas publicas:

    crear_server(host="127.0.0.1", puerto=0) -> ThreadingHTTPServer
    abrir(nombre: str, *, open_browser=True, timeout_s=None) -> dict
    parar() -> None
    estado() -> dict

Base: `http://127.0.0.1:<puerto>`. Todas las respuestas JSON con
`Content-Type: application/json; charset=utf-8`. Errores:
`{"ok": false, "error": "<mensaje>"}` con 400/403/404/500.

    GET  /                            ?t=<token> -> HTML del editor, o 403
    GET  /api/flujos                  {"ok":true,"flujos":[{nombre,slug,
                                      descripcion,version_actual,n_versiones,
                                      n_nodos,modificado}]}  (= flujoteca.listar())
    GET  /api/flujo?nombre=<n>&v=<int?>
                                      {"ok":true,nombre,descripcion,version,
                                       flujo:{nombre,nodos},ui:{pos:{...}},
                                       layout:<build_layout>,
                                       versiones:[{v,ts,nota,n_nodos,actual,existe}]}
    GET  /api/catalogo                {"ok":true,"categorias":[...],
                                       "nodos":[{nombre,descripcion,categoria,
                                       color,icono,danger,familia,flag,activa,
                                       params:[{nombre,tipo,requerido,
                                       descripcion,clave}]}]}
    POST /api/pos                     {"nombre","pos":{id:{x,y}}} -> {"ok":true}
                                      escribe meta["ui"]["pos"], NO crea version
    POST /api/guardar                 {"nombre","flujo","nota","pos"} ->
                                      {"ok":true,"version":int,"meta":{...}}
                                      `flows.validar(flujo, tool_existe=...)`
                                      ANTES de `flujoteca.guardar()`; si falla,
                                      400 con el motivo real y NO SE ESCRIBE NADA
    POST /api/validar                 {"flujo"} -> {"ok":bool,"orden":[ids],"error":str}
    POST /api/chat                    {"nombre","flujo","mensaje"} ->
                                      {"ok":bool,"flujo","resumen","motivo",
                                       "ms","modelo","via"}
    POST /api/restaurar               {"nombre","version":int,"nota":""} ->
                                      {"ok":true,"version":int}
    POST /api/cerrar                  {"ok":true} + shutdown() diferido

El chat NO habla con el backend por su cuenta: llama a
`flujo_ia.editar(flujo, mensaje, tool_existe=lambda n: n in TOOLS,
listar_tools=lambda: _listar_tools(flujo, mensaje))`, que ya resuelve el
backend, extrae el JSON, lo pasa por `sanear_flujo` y lo valida. Si
`ok:false`, EL FLUJO VUELVE EXACTAMENTE COMO ENTRO y el motivo se pinta en el
chat. Se reutiliza `flujo_ia` -y no se toca su firma- porque tiene 701 lineas
de tests con `generar_fn` inyectado.

LO QUE SE OFRECE NO ES LO QUE SE ACEPTA. `tool_existe` es el registro ENTERO;
`listar_tools` va ACOTADO (las tools del flujo + hasta 12 candidatas del
pedido, ver `_listar_tools`). Con las 70, el bloque de tools del prompt son
~7,5 KB -- `flujo_ia` pinta una linea POR TOOL con su firma -- y el
presupuesto del delta se agota antes de escribir el JSON: 5 de los 6 casos
del e2e del editor del 2026-08-29 se perdieron asi.

`via` dice por donde salio el turno ("delta" | "flujo entero" | ""). No es
decorativo: hasta el 2026-08-29 este chat NO podia editar un flujo de 7 nodos
(5 de 6 casos del e2e daban "no cupo en el presupuesto de tokens"), y la causa
estaba justo en el reparto que ese campo delata. Instrumentado el camino, el
JSON de salida costaba 82-405 tokens y el RAZONAMIENTO 1.300-8.192: la
plantilla de chat de Qwen3.8 arranca en `reasoning_effort='xhigh'` cuando
nadie dice lo contrario, y `_completar_fn()` -- esta funcion, la de aqui
abajo -- no decia nada. El camino de texto plano del CLI si lo apagaba, por
eso el fallo solo se veia en el editor visual. Hoy `flujo_ia` pide primero un
DELTA (operaciones, coste de salida constante: 244-309 tokens para flujos de
2 a 20 nodos) y con el pensamiento apagado; el DAG entero queda de respaldo.
El turno del caso real bajo de 35,4 s con ok:false a ~10 s con ok:true.

`abrir()` devuelve al menos `{"url", "puerto", "token", "nombre"}`.
`estado()` describe el servidor vivo (o su ausencia) sin levantarlo.

IMPLEMENTACION (agente E, 2026-08-29)
-------------------------------------
El handler es una clase de MODULO, no una clausura: todo lo que necesita
cuelga del propio servidor (`self.server.token`, `.nombre`, `.ultimo`), asi
que `crear_server()` cabe en diez lineas y el handler se puede leer entero
sin perseguir variables capturadas.

Nada de estado global salvo el singleton `_SERVER` y su `_LOCK`. Cada
endpoint es tolerante por su cuenta: un fallo al leer el catalogo no puede
impedir que la pagina abra, porque la pagina es justo lo que queda cuando lo
demas falla.
"""
from __future__ import annotations

import atexit
import json
import os
import re
import secrets
import socket
import threading
import time
import unicodedata
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

__all__ = ["crear_server", "abrir", "parar", "estado"]

# Singleton de modulo: un unico servidor vivo por proceso.
_SERVER = None
_LOCK = threading.RLock()
_ATEXIT = [False]

# Minutos sin peticiones tras los que el servidor se apaga solo.
INACTIVIDAD_MIN = 30

# Cada cuanto mira el vigilante. No hace falta afinar: 30 min de ocio se
# detectan igual de bien mirando cada 20 s, y asi el thread duerme casi todo
# el rato.
LATIDO_S = 20.0

# Tope del cuerpo de un POST. Un flujo grande son ~50 KB, asi que 1 MB ya es
# veinte veces el caso peor real; los 8 MB de antes solo servian para que una
# peticion sola se comiera la memoria del REPL.
TOPE_CUERPO = 1024 * 1024

# Segundos que un handler puede pasar sin que su socket avance. Sin esto, una
# conexion que no termina las cabeceras deja su hilo clavado PARA SIEMPRE
# dentro del proceso del dueno (medido: 40 conexiones -> 42 hilos, y seguian
# ahi diez segundos despues). 15 s es holgado para localhost y corto para un
# vecino ruidoso. El chat con el modelo NO se ve afectado: el timeout es del
# socket, y mientras el modelo piensa no hay operaciones de socket.
TIMEOUT_CONEXION_S = 15.0

# Tope total para leer el cuerpo de un POST, contando todos los trozos. El
# timeout de socket solo acota UNA lectura: sin este tope, un cliente que
# gotea un byte cada 14 s mantiene su hilo vivo indefinidamente.
TOPE_LECTURA_S = 20.0

# Tope del apagado. Un `shutdown()` espera al `finally` de `serve_forever()`;
# si un handler esta atascado, esa espera no puede ser eterna porque corre
# dentro del `atexit`.
TOPE_APAGADO_S = 5.0

# Solo estas tres direcciones. Un editor que escribe en ~/.cognia/flujoteca
# no se sirve a la red de casa ni por descuido.
HOSTS_PERMITIDOS = ("127.0.0.1", "localhost", "::1")


# ---------------------------------------------------------------------------
# Datos: todo lo que el servidor sabe contar, cada cosa tolerante a su fallo
# ---------------------------------------------------------------------------

def _tool_existe():
    """`lambda n: n in TOOLS` con el registro real, o None si no se puede.

    None (y no `lambda _: True`) porque `flows.validar` ya trata None como
    "no compruebes el registro": si el import de tools falla, se valida la
    forma del grafo y se dice la verdad, en vez de aprobar cualquier nombre.
    """
    try:
        from cognia.agent import tools as _tools
    except Exception:
        return None
    return lambda n: n in _tools.TOOLS


# Cuantas tools NUEVAS (las que el flujo todavia no usa) se le ofrecen al
# modelo en un turno de chat. LAS 70 NO CABEN, y no es una cuestion de gusto:
# `flujo_ia._lineas_de_tools` renderiza una linea por tool con su FIRMA y su
# descripcion, asi que la lista completa son ~70 lineas (~5 KB) de prompt en
# CADA turno; el presupuesto de salida del delta se agota antes de escribir el
# JSON y el turno vuelve con ok:false. Eso es lo que costo 5 de los 6 casos
# del e2e del editor del 2026-08-29. Las que el flujo YA usa van SIEMPRE (si
# no, "usa SOLO estas" invitaria al modelo a reescribir los nodos que no
# tocaba), y encima de esas van hasta 12 candidatas puntuadas contra el
# PEDIDO. La forma de los args -- que es lo que de verdad se venia
# adivinando -- llega igual, porque llega en la firma de cada linea.
TOPE_CANDIDATAS = 12

# El relleno cuando el pedido no casa con ninguna descripcion ("hazlo
# reintentable", "quita el segundo paso"): las tools con las que se construye
# el 90% de los flujos del dueno, para que la lista nunca llegue vacia. Se
# filtran contra el registro vivo, asi que una que no este registrada (o que
# se renombre) simplemente no sale.
BASE_CANDIDATAS = ("prompt", "escribir_archivo", "leer_archivo", "buscar",
                   "resumir", "listar", "ejecutar", "http_get")

_RX_PALABRA = re.compile(r"[a-z0-9]{3,}")

# Palabras de tres o cuatro letras que aparecen en CUALQUIER pedido y no
# distinguen nada. Sin esto, "que", "para" y "como" puntuan a cualquier tool
# cuya descripcion las lleve, que son casi todas.
_VACIAS = frozenset((
    "que", "con", "los", "las", "del", "una", "uno", "por", "sin", "sus",
    "para", "este", "esta", "esto", "eso", "como", "pero", "mas", "muy",
    "hay", "ahi", "aqui", "ahora", "luego", "antes", "despues", "todo",
    "toda", "nada", "algo", "quiero", "quisiera", "haz", "hazlo", "pon",
    "ponle", "dame", "flujo", "nodo", "nodos", "paso", "pasos"))


def _raices(texto: str) -> set:
    """Las raices de 4 letras de las palabras de un texto, sin tildes.

    Cuatro letras y no la palabra entera porque el dueno escribe "escribe" y
    la tool se llama "escribir_archivo": por palabra exacta no casaria ni una.
    Se admiten palabras de TRES letras (su raiz es la palabra entera) porque
    "web" es de las que mas informacion llevan en un pedido de flujo.
    """
    plano = unicodedata.normalize("NFD", str(texto or "").lower())
    plano = "".join(c for c in plano if unicodedata.category(c) != "Mn")
    return {p[:4] for p in _RX_PALABRA.findall(plano) if p not in _VACIAS}


def _tools_del_flujo(flujo) -> list:
    """Los nombres de tool que el flujo usa hoy, en orden y sin repetir."""
    fuera = []
    if isinstance(flujo, dict):
        for n in flujo.get("nodos") or ():
            if not isinstance(n, dict):
                continue
            t = str(n.get("tool") or "").strip()
            if t and t not in fuera:
                fuera.append(t)
    return fuera


def _listar_tools(flujo=None, mensaje: str = "") -> list:
    """Los nombres de tool que ve el modelo, ACOTADOS al flujo y al pedido.

    Sin argumentos devuelve el registro entero, que es lo que hacia siempre:
    quien no da contexto no puede recibir una lista recortada. Con `flujo` o
    `mensaje` devuelve las tools del flujo + hasta `TOPE_CANDIDATAS` mas,
    puntuadas por cuantas raices de palabra comparten con el pedido su NOMBRE
    y su descripcion del catalogo.

    Devuelve NOMBRES, no lineas: la firma la pinta `flujo_ia._lineas_de_tools`
    con `catalogo_nodos.catalogo()[n]["params"]`, que es donde ya vive esa
    regla (tres casos: params declarados -> "tool(a, b)", sin declarar -> la
    plantilla de uso del doc, ninguno de los dos -> el nombre a secas). Si
    aqui se devolvieran las lineas ya pintadas habria DOS sitios que deciden
    la firma, y ademas `flujo_ia` construye el `tool_existe` de respaldo con
    esta misma lista: "escribir_archivo(path, contenido)" no es un nombre de
    tool y rechazaria todos los flujos.
    """
    try:
        from cognia.agent import tools as _tools
        vivas = sorted(_tools.TOOLS)
    except Exception:
        return []
    if flujo is None and not str(mensaje or "").strip():
        return vivas
    en_uso = [t for t in _tools_del_flujo(flujo) if t in set(vivas)]
    ya = set(en_uso)
    resto = [n for n in vivas if n not in ya]

    fichas = {}
    try:
        from cognia.agent import catalogo_nodos as _cn
        fichas = {str(e.get("nombre")): e for e in (_cn.catalogo() or ())
                  if isinstance(e, dict) and e.get("nombre")}
    except Exception:
        fichas = {}

    pedido = _raices(mensaje)
    puntuadas = []
    for n in resto:
        desc = str((fichas.get(n) or {}).get("descripcion") or "")
        comunes = pedido & _raices(n.replace("_", " ") + " " + desc)
        if comunes:
            # -puntos primero y el nombre despues: el orden es TOTAL y no
            # depende del orden del registro, asi que dos turnos iguales dan
            # exactamente la misma lista (y el mismo prompt).
            puntuadas.append((-len(comunes), n))
    puntuadas.sort()
    candidatas = [n for _, n in puntuadas[:TOPE_CANDIDATAS]]
    for n in BASE_CANDIDATAS:
        if len(candidatas) >= TOPE_CANDIDATAS:
            break
        if n in resto and n not in candidatas:
            candidatas.append(n)
    return en_uso + candidatas


def _completar_fn():
    """El cliente de chat estructurado, o None para el camino de siempre.

    `COGNIA_EDITOR_JSON_ESTRICTO=0` lo apaga. Se pasa por parametro y no se
    importa dentro de `flujo_ia` a proposito: ese modulo sigue siendo puro y
    sus 25 tests con `generar_fn` inyectado no se enteran de esto.
    """
    if os.environ.get("COGNIA_EDITOR_JSON_ESTRICTO", "1") == "0":
        return None
    try:
        from cognia.agent import chat_client as _cc
    except Exception:
        return None
    return _cc.completar


def _listar_flujos() -> list:
    try:
        from cognia.agent import flujoteca as _ft
        return list(_ft.listar())
    except Exception:
        return []


def _catalogo() -> dict:
    """{"categorias": [...], "nodos": [...]} para `/api/catalogo`.

    Las categorias van SIN su lista `nodos` anidada: `paleta()` la trae para
    quien quiera agrupar, pero el cliente indexa por el `nodos` plano y
    mandar las dos duplicaria el catalogo entero en cada respuesta.
    """
    try:
        from cognia.agent import catalogo_nodos as _cn
        pal = _cn.paleta()
    except Exception as exc:
        return {"categorias": [], "nodos": [], "total": 0, "activas": 0,
                "aviso": f"{type(exc).__name__}: {exc}"}
    cats = []
    for c in pal.get("categorias") or []:
        cats.append({k: v for k, v in c.items() if k != "nodos"})
    return {"categorias": cats, "nodos": list(pal.get("nodos") or []),
            "total": pal.get("total", 0), "activas": pal.get("activas", 0)}


def _datos_flujo(nombre: str, version=None) -> dict:
    """La respuesta de `/api/flujo`. Levanta si el flujo o la version no estan.

    El `layout` se calcula SIEMPRE con las posiciones manuales para que el
    visor de solo lectura y el editor pinten lo mismo; el cliente usa `ui.pos`
    y se queda el layout de respaldo para los ids que nadie movio.
    """
    from cognia.agent import flow_view as _fv
    from cognia.agent import flujoteca as _ft

    nombre = str(nombre or "").strip()
    if not nombre:
        raise _ft.FlujotecaError("falta el nombre del flujo")
    flujo = _ft.cargar(nombre, version)
    ui = _ft.leer_ui(nombre)
    pos = ui.get("pos") if isinstance(ui.get("pos"), dict) else {}
    metas = _ft.versiones(nombre)
    if version:
        v = int(version)
    else:
        v = 0
        for m in metas:
            if m.get("actual"):
                v = int(m.get("v") or 0)
    return {"ok": True, "nombre": nombre,
            "descripcion": _ft.descripcion(nombre), "version": v,
            "flujo": flujo, "ui": {"pos": pos},
            "layout": _fv.build_layout(flujo, pos), "versiones": metas}


def _datos_pagina(nombre: str) -> dict:
    """Lo que se embebe en el HTML: el flujo abierto + la lista + el catalogo.

    Un flujo que no existe NO es un error aqui: la pagina abre con el lienzo
    vacio y el selector lleno, que es lo que hace falta para crear el primero.
    """
    try:
        datos = _datos_flujo(nombre)
    except Exception as exc:
        datos = {"ok": False, "nombre": str(nombre or ""), "descripcion": "",
                 "version": 0,
                 "flujo": {"nombre": str(nombre or ""), "nodos": []},
                 "ui": {"pos": {}}, "versiones": [],
                 "aviso": f"{type(exc).__name__}: {exc}"}
    datos["flujos"] = _listar_flujos()
    datos["catalogo"] = _catalogo()
    return datos


# ---------------------------------------------------------------------------
# El handler
# ---------------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    """Los endpoints del editor. Todo lo suyo cuelga de `self.server`."""

    server_version = "CogniaEditorFlujos/1.0"
    sys_version = ""

    # `StreamRequestHandler.setup()` lo pasa a `connection.settimeout()`, asi
    # que cubre la lectura de la linea de peticion -que ocurre ANTES del
    # token- y la del cuerpo. `handle_one_request` ya captura el
    # `TimeoutError` que sale de ahi, cierra la conexion y vuelve: el hilo
    # muere en vez de quedarse clavado.
    timeout = TIMEOUT_CONEXION_S

    # -- plomeria ----------------------------------------------------------
    def _marcar(self) -> None:
        """Una peticion VALIDA mas: reinicia el reloj del auto-apagado.

        Se llama DESPUES de `_pasa()`, nunca antes: un 403 que rearmara el
        reloj deja que cualquier proceso local mantenga vivo el editor
        indefinidamente sin credencial, que es justo el control que el
        auto-apagado promete.
        """
        srv = self.server
        with getattr(srv, "contador_lock", _LOCK):
            srv.ultimo = time.time()
            srv.peticiones = getattr(srv, "peticiones", 0) + 1

    def _enviar(self, cuerpo: bytes, tipo: str, code: int = 200) -> None:
        self.send_response(code)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        # El editor sirve datos del dueno en localhost: que ninguna cache ni
        # ningun sniffing de tipo se metan por medio.
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        try:
            self.wfile.write(cuerpo)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError,
                OSError):
            pass  # el navegador cerro la pestana a mitad

    def _json(self, obj, code: int = 200) -> None:
        cuerpo = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._enviar(cuerpo, "application/json; charset=utf-8", code)

    def _error(self, motivo, code: int = 400) -> None:
        self._json({"ok": False, "error": str(motivo)}, code)

    def _html(self, texto: str, code: int = 200) -> None:
        self._enviar(texto.encode("utf-8"), "text/html; charset=utf-8", code)

    def _leer_tope(self, n: int) -> bytes:
        """Lee hasta `n` bytes por trozos, con tope de tiempo y sin esperar.

        `rfile.read(n)` a secas bloquea hasta juntar los `n` bytes que dijo el
        `Content-Length`: un POST que anuncia 4000 y manda 5 clavaba el hilo
        para siempre. Aqui cada trozo lo acota el timeout del socket, el total
        lo acota `TOPE_LECTURA_S`, y un cliente que se va a mitad (`b""`)
        corta el bucle en vez de esperar lo que no va a llegar.
        """
        fin = time.time() + TOPE_LECTURA_S
        trozos = []
        faltan = int(n)
        while faltan > 0 and time.time() < fin:
            trozo = self.rfile.read(min(faltan, 65536))
            if not trozo:
                break
            trozos.append(trozo)
            faltan -= len(trozo)
        return b"".join(trozos)

    def _body(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            return {}
        # El tope se mira ANTES de leer un solo byte: un Content-Length
        # gigante se rechaza sin reservar memoria ni tocar el socket.
        if n <= 0 or n > TOPE_CUERPO:
            return {}
        try:
            obj = json.loads(self._leer_tope(n).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError,
                TimeoutError, OSError):
            # Un cuerpo a medias no es motivo para tumbar el handler: el
            # endpoint responde su 400 y el hilo se cierra por su propio pie.
            return {}
        return obj if isinstance(obj, dict) else {}

    def _query(self) -> dict:
        crudo = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        return {k: v[0] for k, v in crudo.items() if v}

    # -- seguridad ---------------------------------------------------------
    def _puerto(self) -> int:
        try:
            return int(self.server.server_address[1])
        except Exception:
            return 0

    def _origen_ok(self) -> bool:
        """Host y Origin tienen que ser los del propio servidor.

        Es la defensa contra DNS rebinding: un dominio del atacante que
        resuelva a 127.0.0.1 llega con SU nombre en `Host`, y ahi se para.
        Un `Host` ausente (HTTP/1.0, un socket a pelo) no es vector de
        rebinding y no se bloquea; lo que se bloquea es un `Host` ajeno.
        """
        puerto = self._puerto()
        hosts = {"127.0.0.1:%d" % puerto, "localhost:%d" % puerto,
                 "[::1]:%d" % puerto}
        host = (self.headers.get("Host") or "").strip().lower()
        if host and host not in hosts:
            return False
        origenes = {"http://" + h for h in hosts}
        origen = (self.headers.get("Origin") or "").strip().lower()
        if origen and origen.rstrip("/") not in origenes:
            return False
        return True

    def _token_ok(self) -> bool:
        """Comparacion en tiempo constante y EN BYTES.

        `compare_digest` sobre `str` lanza `TypeError` en cuanto hay un
        caracter no-ASCII, y las cabeceras HTTP se decodifican como latin-1:
        un `X-Cognia-Token: <byte>127` -o un `?t=` con un byte no-ASCII-
        reventaba el guardia sin devolver ningun codigo HTTP y volcaba el
        traceback al stderr del REPL. En bytes no hay caso que lance.
        """
        esperado = str(getattr(self.server, "token", "") or "")
        if not esperado:
            return False
        dado = (self.headers.get("X-Cognia-Token")
                or self._query().get("t") or "")
        return secrets.compare_digest(str(dado).encode("utf-8", "ignore"),
                                      esperado.encode("utf-8"))

    def _pasa(self) -> bool:
        """403 y False si la peticion no es de esta pagina. True si sigue."""
        if not self._origen_ok():
            self._error("origen no permitido", 403)
            return False
        if not self._token_ok():
            self._error("token invalido o ausente", 403)
            return False
        return True

    # -- rutas -------------------------------------------------------------
    def do_GET(self):  # noqa: N802 - el nombre lo impone http.server
        ruta = urllib.parse.urlsplit(self.path).path
        if ruta == "/favicon.ico":
            # Antes del guardia a proposito: no filtra nada y evita que la
            # consola del navegador se llene de 403 que no son del dueno.
            return self._enviar(b"", "image/x-icon", 204)
        try:
            # EL GUARDIA VA DENTRO DEL try: es codigo, y el codigo falla. Con
            # `_pasa()` fuera, un token con un byte raro cerraba la conexion
            # sin respuesta y escupia el traceback al REPL.
            if not self._pasa():
                return None
            self._marcar()   # solo cuenta lo que paso el guardia
            if ruta in ("/", "/index.html"):
                from cognia.agent import editor_html as _eh
                datos = _datos_pagina(getattr(self.server, "nombre", ""))
                base = "http://127.0.0.1:%d" % self._puerto()
                return self._html(_eh.render(datos, base=base,
                                             token=self.server.token))
            if ruta == "/api/flujos":
                return self._json({"ok": True, "flujos": _listar_flujos()})
            if ruta == "/api/flujo":
                q = self._query()
                try:
                    version = int(q.get("v") or 0) or None
                except (TypeError, ValueError):
                    version = None
                try:
                    return self._json(
                        _datos_flujo(q.get("nombre", ""), version))
                except Exception as exc:
                    return self._error(exc, 404)
            if ruta == "/api/catalogo":
                cat = _catalogo()
                cat["ok"] = True
                return self._json(cat)
            if ruta == "/api/ejecutar":
                return self._ejecutar_no()
            return self._error("no existe", 404)
        except Exception as exc:  # el servidor jamas se cae por un endpoint
            return self._fallo(exc)

    def do_POST(self):  # noqa: N802
        ruta = urllib.parse.urlsplit(self.path).path
        try:
            if not self._pasa():   # dentro del try, igual que en do_GET
                return None
            self._marcar()
            cuerpo = self._body()
            if ruta == "/api/pos":
                return self._pos(cuerpo)
            if ruta == "/api/guardar":
                return self._guardar(cuerpo)
            if ruta == "/api/validar":
                return self._validar(cuerpo)
            if ruta == "/api/chat":
                return self._chat(cuerpo)
            if ruta == "/api/restaurar":
                return self._restaurar(cuerpo)
            if ruta == "/api/cerrar":
                return self._cerrar()
            if ruta == "/api/ejecutar":
                return self._ejecutar_no()
            return self._error("no existe", 404)
        except Exception as exc:
            return self._fallo(exc)

    def _fallo(self, exc):
        """El 500 de ultimo recurso, que tampoco puede levantar.

        Si el socket ya se fue, hasta `send_response` falla; se traga aqui
        porque a estas alturas no hay nadie a quien contarselo y lo unico que
        haria una excepcion mas es el traceback que este modulo evita.
        """
        try:
            return self._error("%s: %s" % (type(exc).__name__, exc), 500)
        except Exception:
            self.close_connection = True
            return None

    # -- endpoints ---------------------------------------------------------
    def _ejecutar_no(self):
        """El KILL explicito, dicho con su motivo Y con el comando que SI va.

        El 404 se queda -- ejecutar desde un boton del navegador saltaria la
        confirmacion del terminal que protege `borrar_archivo`, `ejecutar` y
        `mcp`, y un navegador no tiene canal de confirmacion TTY -- pero el
        texto que daba MENTIA dos veces: decia que quedaba "detras de
        COGNIA_EDITOR_EJECUTAR=1" (una variable que NO LA LEE NADIE en todo el
        repo: ponerla no habilita nada) y remitia al REPL sin decir con que
        comando. Ahora nombra el comando real, que existe y ejecuta este mismo
        flujo con la confirmacion puesta.
        """
        return self._error(
            "el editor no ejecuta flujos, y no es un pendiente: un boton del "
            "navegador no tiene donde preguntarte 'y esto lo borro?', asi que "
            "se saltaria la confirmacion del terminal que protege ejecutar y "
            "borrar_archivo. Corre el flujo desde el REPL de Cognia con "
            "/flujoteca ejecutar <nombre> [prompt] -- ahi ves el progreso "
            "nodo a nodo, el entregable y donde quedaron los ficheros.", 404)

    def _pos(self, b: dict):
        from cognia.agent import flujoteca as _ft
        nombre = str(b.get("nombre") or "").strip()
        pos = b.get("pos")
        if not nombre:
            return self._error("falta el nombre del flujo", 400)
        if not isinstance(pos, dict):
            return self._error("'pos' tiene que ser un dict {id:{x,y}}", 400)
        try:
            # guardar_ui NO crea version: las posiciones viven en meta['ui'].
            ui = _ft.guardar_ui(nombre, {"pos": pos})
        except _ft.FlujotecaError as exc:
            return self._error(exc, 404)
        return self._json({"ok": True, "n": len(ui.get("pos") or {})})

    def _guardar(self, b: dict):
        from cognia.agent import flows as _flows
        from cognia.agent import flujoteca as _ft
        nombre = str(b.get("nombre") or "").strip()
        flujo = b.get("flujo")
        if not isinstance(flujo, dict):
            return self._error("falta el flujo", 400)
        nombre = nombre or str(flujo.get("nombre") or "").strip()
        if not nombre:
            return self._error("falta el nombre del flujo", 400)
        # VALIDAR ANTES DE ESCRIBIR. Si esto levanta no se toca el disco: el
        # fallo aparece donde se entiende (editando) y no al ejecutar.
        try:
            _flows.validar(flujo, tool_existe=_tool_existe())
        except Exception as exc:
            return self._error(exc, 400)
        try:
            meta = _ft.guardar(flujo, nombre=nombre,
                               nota=str(b.get("nota") or ""),
                               tool_existe=_tool_existe())
        except Exception as exc:
            return self._error(exc, 400)
        salida = {"ok": True, "version": int(meta.get("version_actual") or 0),
                  "meta": meta}
        pos = b.get("pos")
        if isinstance(pos, dict):
            # Las posiciones van DESPUES: guardar_ui necesita la meta escrita.
            # Si fallan, la version ya existe y responder "no se guardo" seria
            # mentira, asi que se avisa aparte y `ok` sigue siendo true.
            try:
                _ft.guardar_ui(nombre, {"pos": pos})
            except Exception as exc:
                salida["aviso_ui"] = "%s: %s" % (type(exc).__name__, exc)
        return self._json(salida)

    def _validar(self, b: dict):
        """Validacion en vivo: 200 siempre, el veredicto va en `ok`.

        Un flujo a medias mientras se edita no es un error de la peticion:
        devolver 400 aqui pintaria el editor de rojo de red cuando lo que
        pasa es que falta cablear un nodo.
        """
        from cognia.agent import flows as _flows
        flujo = b.get("flujo")
        if not isinstance(flujo, dict):
            return self._json({"ok": False, "orden": [],
                               "error": "falta el flujo"})
        try:
            orden = _flows.validar(flujo, tool_existe=_tool_existe())
        except Exception as exc:
            return self._json({"ok": False, "orden": [], "error": str(exc)})
        return self._json({"ok": True, "orden": list(orden), "error": ""})

    def _chat(self, b: dict):
        """El chat del editor. NO habla con el backend: llama a flujo_ia.

        Con ok=false, `flujo_ia.editar` devuelve el flujo EXACTAMENTE como
        entro, asi que el cliente puede pintar el motivo sin comprobar nada.
        """
        from cognia.agent import flujo_ia as _fia
        flujo = b.get("flujo")
        mensaje = str(b.get("mensaje") or "").strip()
        if not isinstance(flujo, dict):
            return self._json({"ok": False, "flujo": {},
                               "motivo": "falta el flujo", "resumen": "",
                               "ms": 0, "modelo": "", "via": ""})
        if not mensaje:
            return self._json({"ok": False, "flujo": flujo,
                               "motivo": "no dijiste que cambiar",
                               "resumen": "", "ms": 0, "modelo": "",
                               "via": ""})
        # La lista va ACOTADA al flujo y al pedido (ver `_listar_tools`): con
        # las 70, el prompt del delta se come el presupuesto y el turno vuelve
        # ok:false. `tool_existe` sigue siendo el registro ENTERO: acotar lo
        # que se OFRECE no es acotar lo que se acepta, y un flujo que ya usa
        # una tool fuera de la lista se sigue validando bien.
        res = _fia.editar(flujo, mensaje, tool_existe=_tool_existe(),
                          listar_tools=lambda: _listar_tools(flujo, mensaje),
                          completar_fn=_completar_fn())
        if hasattr(res, "a_dict"):
            salida = res.a_dict()
        elif isinstance(res, dict):
            salida = dict(res)
        else:
            salida = {"ok": bool(getattr(res, "ok", False)),
                      "flujo": getattr(res, "flujo", flujo),
                      "motivo": str(getattr(res, "motivo", "")),
                      "resumen": str(getattr(res, "resumen", "")),
                      "ms": int(getattr(res, "ms", 0) or 0),
                      "modelo": str(getattr(res, "modelo", "")),
                      "via": str(getattr(res, "via", ""))}
        salida.setdefault("via", "")
        if not salida.get("ok"):
            # Cinturon y tirantes: el contrato dice que con ok=false el flujo
            # vuelve como entro, y el cliente pinta lo que le llegue.
            salida["flujo"] = flujo
        return self._json(salida)

    def _restaurar(self, b: dict):
        from cognia.agent import flujoteca as _ft
        nombre = str(b.get("nombre") or "").strip()
        try:
            version = int(b.get("version") or 0)
        except (TypeError, ValueError):
            version = 0
        if not nombre or version <= 0:
            return self._error("hace falta 'nombre' y 'version'", 400)
        try:
            meta = _ft.restaurar(nombre, version,
                                 nota=str(b.get("nota") or ""))
        except Exception as exc:
            return self._error(exc, 404)
        return self._json({"ok": True,
                           "version": int(meta.get("version_actual") or 0),
                           "meta": meta})

    def _cerrar(self):
        """Responde primero y apaga despues, en un thread aparte.

        Apagar antes de contestar deja al navegador con un fetch colgado y al
        dueno sin saber si se cerro; los 0,2 s son para que la respuesta salga
        por el socket antes de que el socket deje de existir.

        Se apaga ESTE servidor, no "el del singleton": un `parar()` a secas
        dejaria vivo cualquier servidor levantado a mano (los tests, un
        arranque efimero) y cerraria en su lugar el que estuviera abierto.
        """
        self._json({"ok": True})
        threading.Timer(0.2, _cerrar_desde, args=(self.server,)).start()

    def log_message(self, *a):  # silencio: el editor pollea y valida en vivo
        pass


# ---------------------------------------------------------------------------
# Ciclo de vida
# ---------------------------------------------------------------------------

def crear_server(host="127.0.0.1", puerto=0) -> ThreadingHTTPServer:
    """Crea (sin arrancar el bucle) el servidor del editor.

    Genera el token de un solo arranque, silencia el log y deja
    `daemon_threads=True`. Con `puerto=0` el sistema elige uno libre; el real
    se lee luego en `srv.server_address[1]`.

    El bind fuera de 127.0.0.1 se rechaza AQUI y no detras de un flag: un
    editor que escribe en ~/.cognia/flujoteca no se sirve a la red de casa ni
    por descuido de quien llame.
    """
    if str(host) not in HOSTS_PERMITIDOS:
        raise ValueError("el editor solo escucha en %s: '%s' no vale"
                         % (", ".join(HOSTS_PERMITIDOS), host))
    srv = ThreadingHTTPServer((str(host), int(puerto)), _Handler)
    srv.daemon_threads = True
    srv.token = secrets.token_urlsafe(24)
    srv.nombre = ""
    srv.ultimo = time.time()
    srv.peticiones = 0
    srv.parando = False
    # `hilo` lo pone `abrir()` con el hilo del bucle; queda declarado aqui
    # porque `_apagar()` lo consulta para no llamar a un `shutdown()` que
    # bloquearia para siempre sobre un bucle que nunca arranco.
    srv.hilo = None
    srv.aviso = ""
    srv.contador_lock = threading.Lock()
    return srv


def _bucle_corriendo(srv) -> bool:
    """Si `serve_forever()` esta corriendo de verdad sobre `srv`.

    Es la pregunta que decide si `shutdown()` se puede llamar: sobre un
    servidor cuyo bucle nunca arranco, `shutdown()` espera un `Event` que solo
    pone el `finally` de `serve_forever()`, o sea PARA SIEMPRE.

    `abrir()` deja el hilo en `srv.hilo`, y eso responde exacto. Quien levante
    el bucle por su cuenta (los tests, un arranque a mano) no deja hilo: ahi
    se asume que si, y de eso se encarga el tope de tiempo de `_apagar`.
    """
    hilo = getattr(srv, "hilo", None)
    if hilo is None:
        return True
    try:
        return bool(hilo.is_alive())
    except Exception:
        return True


def _apagar(srv, timeout_s=TOPE_APAGADO_S) -> None:
    """`shutdown()` (si procede) + `server_close()`, sin ruido ni excepciones.

    Dos defensas, las dos por el mismo dano: esto corre dentro del `atexit`,
    donde un bloqueo cuelga el proceso para siempre y ni Ctrl-C sirve.
      1. `shutdown()` SOLO si el bucle arranco (ver `_bucle_corriendo`).
      2. Y aun asi, en un hilo aparte con tope: si un handler tiene atascado
         el bucle, se cierra el socket igual en vez de esperar sin fin.
    `server_close()` va siempre: es lo que libera el puerto.
    """
    if srv is None:
        return
    srv.parando = True
    if _bucle_corriendo(srv):
        apagador = threading.Thread(target=_shutdown_mudo, args=(srv,),
                                    name="cognia-editor-apaga", daemon=True)
        try:
            apagador.start()
        except BaseException:
            # Sin hilos disponibles (que es justo el escenario que rompio
            # esto) no se arriesga un shutdown() bloqueante: se cierra el
            # socket y ya. El bucle muere solo al fallar el accept.
            apagador = None
        if apagador is not None:
            apagador.join(max(0.0, float(timeout_s)))
    try:
        srv.server_close()
    except Exception:
        pass


def _shutdown_mudo(srv) -> None:
    try:
        srv.shutdown()
    except Exception:
        pass


def _cerrar_desde(srv) -> None:
    """Apaga `srv` y, si era el del singleton, deja el singleton vacio.

    Es lo que llama `/api/cerrar`. Si no se limpiara el singleton, `estado()`
    seguiria diciendo que hay un editor vivo contra un puerto ya muerto.
    """
    global _SERVER
    with _LOCK:
        if _SERVER is srv:
            _SERVER = None
    _apagar(srv)


def _vigilante(srv) -> None:
    """Apaga el servidor tras INACTIVIDAD_MIN sin una sola peticion.

    Un editor abierto por la manana y olvidado no puede quedarse escuchando
    todo el dia. Solo apaga si SIGUE siendo el servidor del singleton: si
    entre medias se abrio otro, de este ya se ocupo quien lo reemplazo.
    """
    global _SERVER
    while True:
        time.sleep(LATIDO_S)
        if getattr(srv, "parando", False):
            return
        limite = float(INACTIVIDAD_MIN) * 60.0
        if limite <= 0:
            continue
        if time.time() - float(getattr(srv, "ultimo", 0.0)) < limite:
            continue
        with _LOCK:
            if _SERVER is not srv:
                return
            _SERVER = None
        _apagar(srv)
        return


def _escuchando(puerto: int, timeout_s=None) -> bool:
    """True cuando el socket acepta conexiones. No espera al primer GET.

    `crear_server` ya hace bind+listen, asi que en la practica esto vuelve a
    la primera vuelta; el bucle esta para que `abrir()` no mienta si algun
    dia el arranque deja de ser sincrono.
    """
    tope = 5.0 if timeout_s is None else float(timeout_s)
    fin = time.time() + max(0.0, tope)
    while True:
        s = socket.socket()
        s.settimeout(0.5)
        try:
            s.connect(("127.0.0.1", int(puerto)))
            return True
        except OSError:
            pass
        finally:
            s.close()
        if time.time() >= fin:
            return False
        time.sleep(0.02)


def _vivo(srv) -> bool:
    if srv is None or getattr(srv, "parando", False):
        return False
    try:
        return srv.fileno() >= 0
    except Exception:
        return False


def abrir(nombre: str, *, open_browser=True, timeout_s=None) -> dict:
    """Levanta el servidor en un thread daemon y devuelve al REPL.

    NUNCA llama a `serve_forever()` en el hilo del que llama: eso colgaria el
    REPL entero. Un unico servidor por proceso: abrir otro flujo reusa el que
    ya hay y solo cambia el flujo servido, para que el dueno no acumule
    pestanas apuntando a puertos muertos.

    Devuelve {"url", "base", "puerto", "token", "nombre", "nuevo"}.
    `timeout_s` acota la espera a que el socket este escuchando, no la vida
    del servidor.
    """
    global _SERVER
    nombre = str(nombre or "").strip()
    with _LOCK:
        srv = _SERVER
        if not _vivo(srv):
            srv = crear_server()
            hilo = threading.Thread(target=srv.serve_forever,
                                    name="cognia-editor-flujos", daemon=True)
            srv.hilo = hilo
            try:
                hilo.start()
            except BaseException:
                # EL SINGLETON NO SE PUBLICA HASTA AQUI. Si `start()` lanza
                # (`RuntimeError: can't start new thread` por agotamiento de
                # hilos o poca memoria), un `_SERVER` ya asignado dejaria un
                # servidor con bind+listen y sin bucle: `estado()` diria
                # `vivo: True` mintiendo -el socket acepta el handshake- y el
                # `atexit` colgaria el proceso para siempre en `shutdown()`.
                srv.parando = True
                _SERVER = None
                try:
                    srv.server_close()
                except Exception:
                    pass
                raise
            # El bucle corre: ahora si es verdad que hay un editor vivo.
            _SERVER = srv
            try:
                threading.Thread(target=_vigilante, args=(srv,),
                                 name="cognia-editor-vigia",
                                 daemon=True).start()
            except BaseException as exc:
                # Sin vigia el editor sirve igual, asi que no se tira abajo lo
                # que funciona; pero no se calla: `estado()` lo publica en
                # `aviso` y el auto-apagado deja de estar garantizado.
                srv.aviso = ("sin vigilante de inactividad (%s: %s): el editor"
                             " no se apagara solo"
                             % (type(exc).__name__, exc))
            if not _ATEXIT[0]:
                atexit.register(parar)
                _ATEXIT[0] = True
            nuevo = True
        else:
            nuevo = False
        srv.nombre = nombre
        srv.ultimo = time.time()
        token = srv.token
        puerto = int(srv.server_address[1])

    base = "http://127.0.0.1:%d" % puerto
    url = base + "/?t=" + urllib.parse.quote(token)
    _escuchando(puerto, timeout_s)
    if open_browser and not os.environ.get("COGNIA_REMOTO"):
        try:
            webbrowser.open(url)
        except Exception:
            pass  # sin display: la URL ya va en el dict que se devuelve
    return {"url": url, "base": base, "puerto": puerto, "token": token,
            "nombre": nombre, "nuevo": nuevo}


def parar() -> None:
    """Apaga el servidor vivo: `shutdown()` + `server_close()`.

    Idempotente: llamarla sin servidor no es un error, y tampoco lo es
    llamarla sobre uno cuyo bucle nunca arranco (ver `_apagar`), que es el
    caso que colgaba el proceso entero desde el `atexit`.

    Hoy la llaman el `atexit` registrado en la primera `abrir()` y, por la via
    de `_cerrar_desde`, el endpoint `/api/cerrar`.
    TODO(F-CABLE): anadir aqui la rama `/salir` de `cognia/cli.py` cuando ese
    agente cablee el modulo.
    """
    global _SERVER
    with _LOCK:
        srv = _SERVER
        _SERVER = None
    _apagar(srv)


def estado() -> dict:
    """Que hay levantado ahora mismo, sin levantar nada."""
    with _LOCK:
        srv = _SERVER
    if not _vivo(srv):
        return {"vivo": False, "puerto": 0, "url": "", "base": "",
                "nombre": "", "token": "", "peticiones": 0, "ocioso_s": 0,
                "inactividad_min": INACTIVIDAD_MIN, "aviso": ""}
    puerto = int(srv.server_address[1])
    base = "http://127.0.0.1:%d" % puerto
    return {"vivo": True, "puerto": puerto, "base": base,
            "url": base + "/?t=" + urllib.parse.quote(srv.token),
            "nombre": getattr(srv, "nombre", ""), "token": srv.token,
            "peticiones": int(getattr(srv, "peticiones", 0)),
            "ocioso_s": int(time.time()
                            - float(getattr(srv, "ultimo", time.time()))),
            "inactividad_min": INACTIVIDAD_MIN,
            # Vacio salvo que algo se degradara al abrir (hoy: el vigia que no
            # arranco). Un subsistema a medias tiene que verse desde fuera.
            "aviso": str(getattr(srv, "aviso", "") or "")}
