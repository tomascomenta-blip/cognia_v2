# -*- coding: utf-8 -*-
"""
cognia/clases/servidor_vivo.py
==============================
EL TRANSPORTE del cuaderno que se ve escribirse solo: un servidor HTTP local y
efimero que sirve la pagina del cuaderno, le empuja por SSE cada linea que
almacen.py acaba de escribir en disco y -- por UNA sola ruta, `POST /accion` --
deja que el duenio corrija encima de lo que escribio la IA.

POR QUE EXISTE (y por que no es un fichero HTML suelto)
------------------------------------------------------
`vista.export()` ya escribe un HTML precioso y lo abre con `file://`. Ese
camino se queda MUERTO en cuanto la pagina tiene que enterarse de algo:

1. UNA PAGINA `file://` NO PUEDE PEDIR NADA. Chrome y Edge le dan origen
   opaco ("null"): `fetch`/XHR contra otro fichero local se bloquean por CORS
   y `EventSource` ni se plantea. O sea: un cuaderno en vivo servido por
   `file://` no puede hacer polling ni recibir eventos. No es una molestia de
   configuracion, es la regla del navegador desde hace anios.
2. LOS ADJUNTOS SE EMBEBEN EN BASE64 y por eso `vista.TOPE_ADJUNTO` existe.
   Sirviendolos por URL (`/adj/...`) la pagina deja de cargar megabytes de
   base64 en cada refresco y el navegador se los cachea el solo.
3. EL ESTADO ES PYTHON. `jornada.estado()` es la unica puerta al estado
   (grabando / pausada / materia); congelarlo dentro del HTML deja al widget
   mintiendo a los dos minutos.

SEGURIDAD (esto sirve las notas de clase del duenio: es superficie real)
-----------------------------------------------------------------------
El patron entero esta COPIADO de `cognia/agent/flujoteca_editor.py`, que es el
servidor local ya depurado de esta casa. No se reinventa nada:

  - bind estricto a 127.0.0.1 y PUERTO 0. El puerto lo elige el sistema
    porque en este equipo 8080, 8765, 8766, 8777 y 8899 ya estan tomados, y
    ademas `tailscaled` ocupa el 8080 en sus interfaces: un puerto fijo aqui
    no es una preferencia, es un choque garantizado.
  - TOKEN DE UN SOLO ARRANQUE (`secrets.token_urlsafe(24)`). Viaja en la
    query (`?t=`) Y en la cabecera `X-Cognia-Token`. LA QUERY NO ES PEREZA:
    `EventSource` NO PUEDE PONER CABECERAS (su constructor solo acepta
    `withCredentials`), asi que sin token en la URL no hay SSE posible.
  - Validacion de `Origin`/`Host`: solo 127.0.0.1/localhost/[::1] con el
    puerto propio. Es la defensa contra DNS rebinding (un dominio del
    atacante que resuelva a 127.0.0.1 llega con SU nombre en `Host`).
  - Comparacion del token EN BYTES dentro del `try` de la ruta:
    `secrets.compare_digest` sobre `str` LANZA `TypeError` con cualquier
    caracter no-ASCII y las cabeceras se decodifican como latin-1. Es un
    fallo ya pagado en el editor de flujos: un solo byte >127 tumbaba el
    guardia ANTES de responder y volcaba el traceback al REPL del duenio.
  - `timeout` de conexion y tope de `Content-Length`: la linea de peticion se
    lee ANTES del token, asi que sin timeout cualquier proceso local deja
    hilos clavados para siempre dentro del proceso del REPL.
  - EL RELOJ DEL AUTO-APAGADO SOLO LO REARMA QUIEN PASA EL GUARDIA. Marcando
    antes, cualquiera mantiene el servidor vivo golpeando el puerto sin
    credencial.
  - UNA SOLA RUTA ESCRIBE (`POST /accion`) y pasa por el MISMO guardia que el
    resto: token, Origin y Host. Ademas exige `Content-Type: application/json`
    y un `Content-Length` declarado y por debajo de `TOPE_CUERPO`: un cuerpo
    sin tope tumbaria el proceso que esta grabando la clase del duenio. El
    resto de rutas POST siguen siendo 404 con el motivo escrito.

LA PUERTA DE ESCRITURA (`POST /accion`)
---------------------------------------
La promesa del producto es "la IA escribe y yo corrijo encima; lo que yo toco
queda fijado". Sin esta ruta la pagina lo hacia TODO menos lo ultimo.

  - LA ESCRITURA NO SE HACE AQUI. Este modulo no abre un solo fichero del
    documento: valida y delega en el manejador (por defecto
    `vista_viva.aplicar_accion`, inyectable con `fijar_acciones`), que entra
    por las puertas de `documento.py`. Ahi vive el lock, el diario
    append-only, la instantanea y la REGLA DE ORO (un bloque fijado por el
    duenio no lo pisa la IA). Un segundo camino de escritura seria un segundo
    formato de diario y una segunda forma de saltarse esa regla.
  - TODO LO QUE LLEGA ES DATO. Nunca una ruta, nunca un nombre de funcion:
    la accion se busca en el manejador, el `tipo` se valida contra
    `documento.TIPOS` (lista cerrada) y el `id` contra los bloques que existen
    de verdad. Un id inventado devuelve un error escrito para leerlo en
    pantalla, no una excepcion ni un 500.
  - LA MATERIA TIENE QUE RESOLVERSE. `almacen._seguro` convierte cualquier
    nombre en un nombre de fichero valido, asi que una materia de puros signos
    ("///") acabaria en la carpeta "sin-nombre" SIN decirlo. Aqui se detecta y
    se contesta con el motivo. Si el documento todavia no existe, se crea (por
    `documento.abrir`), que es lo que hace que el primer bloque de una materia
    nueva no falle.
  - EL AUTOR NO RECIBE SU PROPIO CAMBIO. Ver "EL ECO" mas abajo.

EL ECO: por que el que escribe no recibe su propia escritura
------------------------------------------------------------
Escribir en el documento emite por el bus (lo hace `almacen`, que es quien
apenda el diario), y el SSE reparte eso a todas las pestanias. Sin mas, la
pestania del duenio recibiria de vuelta el bloque que acaba de teclear y lo
repintaria con lo que hay en disco JUSTO mientras lo esta corrigiendo: el
cursor salta y lo escrito despues del guardado se pierde de vista.

La solucion no necesita ni cookies ni que la pagina sepa nada nuevo:

  - CADA CARGA DE `GET /` recibe su propio identificador (`cli`), y ese
    identificador va YA PUESTO en las dos URLs que la pagina usa tal cual:
    `ctx["eventos"]` (el EventSource) y `ctx["accion"]` (el fetch de
    guardado). Dos pestanias del mismo navegador son dos cargas, o sea dos
    identificadores: la cookie no valdria, porque la comparten.
  - Mientras se aplica una accion, el identificador de quien la pidio vive en
    un `threading.local`. `almacen._emitir` corre EN EL MISMO HILO (por eso el
    evento garantiza que el dato ya esta en disco), asi que `_desde_el_bus` lo
    lee sin pasarlo por ningun sitio y SALTA la cola de ese cliente.
  - Se CUENTA (`estado()["omitidos_autor"]`). Un eco suprimido y un evento que
    nunca se emitio no pueden verse igual desde fuera.

El identificador NO es una credencial: no autoriza nada, solo dice "esta
pestania ya sabe esto". El que autoriza sigue siendo el token.

SSE: UNA COLA POR CLIENTE, Y EL BUS NO ESPERA A NADIE
----------------------------------------------------
`almacen._emitir` corre EN EL HILO QUE ESTA ESCRIBIENDO LA CLASE, y almacen ya
mide y denuncia al suscriptor que tarda mas de 0,25 s (`_TOPE_SUSCRIPTOR_S`).
O sea: el suscriptor de aqui tiene prohibido bloquear. Por eso:

  - `_desde_el_bus` solo serializa una vez y hace `put_nowait` en la cola de
    cada cliente. Nunca toca un socket.
  - CADA CLIENTE TIENE SU COLA (`TOPE_COLA`). Con una cola compartida, un
    navegador minimizado que no lee frena a los demas Y al grabador.
  - Cola llena = cliente muerto: se le cierra el socket y se CUENTA
    (`estado()["desconectados_lentos"]`). Perder a un espectador lento es el
    precio; frenar la grabacion no lo es. Un fallo silencioso aqui seria
    indistinguible de "no hay eventos", que es el modo de fallo tipico de
    esta casa.
  - `TOPE_EVENTO` recorta el evento gigante (un `apuntes.json` entero cabe en
    "clase.json") en vez de copiarlo a N colas.
  - LATIDO cada 15 s (`: latido`): un comentario SSE que no dispara ningun
    handler en el cliente pero mantiene viva la conexion frente a cualquier
    intermediario o antivirus que corte lo que lleva rato callado.
  - Desuscripcion en el `finally`: un cliente que cierra la pestania no puede
    dejar su cola creciendo para siempre.

HTTP/1.0 A PROPOSITO (el default de la stdlib, y aqui interesa)
---------------------------------------------------------------
Con HTTP/1.1 el navegador deja la conexion abierta y el hilo del handler se
queda esperando la siguiente peticion hasta el timeout: `parar()` devolveria
con hilos todavia vivos y el contrato de "cerrar de verdad" seria mentira.
Con HTTP/1.0 cada respuesta cierra su conexion y su hilo. El coste (una
conexion TCP por peticion) es irrelevante en localhost; el SSE no se ve
afectado porque su cuerpo termina justo cuando se cierra el socket.

CICLO DE VIDA
-------------
`arrancar()` levanta el bucle en un thread daemon, se suscribe al bus,
PUBLICA puerto+token en `~/.cognia/clases/servidor_vivo.json` (el handshake
que lee el widget: no hay puerto fijo que adivinar) y devuelve al REPL en el
acto. `parar()` desengancha el bus, despierta y cierra a todos los clientes
SSE, borra el handshake y hace `shutdown()` + `server_close()`.

`shutdown()` SOLO SI EL BUCLE ARRANCO: en `socketserver` espera un `Event` que
solo pone el `finally` de `serve_forever()`, asi que sobre un servidor con
bind y sin bucle bloquea PARA SIEMPRE (y esto corre tambien desde `atexit`,
donde ni Ctrl-C sirve). El vigia de ocio espera sobre un `Event` en vez de
dormir, para que `parar()` no tenga que aguantar su siesta.

PUERTA DE DIAGNOSTICO
---------------------
`estado()` dice si esta vivo, en que puerto, cuantos miran, cuantos eventos se
repartieron, a cuantos lentos se echo y cual fue el ultimo fallo. La puerta de
CLI (`/grabar-clase ver`) la cablea la pieza que sirve la pagina de verdad;
este modulo expone el gancho `fijar_pagina()` y nada mas.

CONTRATO
--------
    crear_server(host="127.0.0.1", puerto=0) -> ThreadingHTTPServer
    arrancar(*, abrir_navegador=False, timeout_s=None) -> dict
    parar() -> None
    estado() -> dict
    fijar_pagina(render|None) -> None
    fijar_acciones(manejador|None) -> None

    GET  /                 la pagina (placeholder hasta que la inyecten)
    GET  /eventos          SSE de "clase.entrada", "clase.json" y
                           "clase.accion"
    GET  /adj/<j>/<n>      un adjunto de la jornada <j>
    GET  /estado           jornada.estado() + el estado del servidor
    POST /accion           la puerta de escritura (JSON -> JSON)
"""

from __future__ import annotations

import atexit
import itertools
import json
import logging
import os
import queue
import secrets
import socket
import tempfile
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from cognia.clases import almacen as alm

log = logging.getLogger(__name__)

__all__ = ["crear_server", "arrancar", "parar", "estado", "fijar_pagina",
           "fijar_acciones", "EVENTOS", "HANDSHAKE", "RUTA_ACCION",
           "TOPE_CUERPO", "EXIGENCIAS"]

# Los eventos que se reparten por el SSE. Los dos primeros los emite
# almacen.py por cada escritura del cuaderno y su payload es SUYO (ruta como
# str + registro/datos): aqui se reenvian tal cual, para que la pagina y el
# JSONL digan lo mismo. El tercero lo emite ESTA puerta de escritura (ver
# `_avisar_del_cambio`) y dice QUE accion se aplico, que el diario solo cuenta
# en operaciones sueltas.
EVENTOS = ("clase.entrada", "clase.json", "clase.accion")

# El evento que emite la puerta de escritura. Va DENTRO de EVENTOS a
# proposito: se reparte por el mismo SSE y con la misma supresion de eco.
EVENTO_ACCION = "clase.accion"

# El handshake: puerto + token en el directorio de clases. Sin esto el widget
# tendria que adivinar un puerto efimero, y un puerto fijo aqui choca seguro
# (ver la cabecera).
HANDSHAKE = "servidor_vivo.json"

# Minutos sin nadie mirando tras los que el servidor se apaga solo. VEINTE:
# una clase dura 50-60 min y el cuaderno se mira a rachas, asi que el vigia
# tiene que aguantar una explicacion entera sin cerrarse; pero un servidor
# olvidado en el portatil no se queda escuchando toda la tarde. Un SSE abierto
# CUENTA como alguien mirando (ver _vigilante): si no, el vigia mataria justo
# al espectador que lleva una hora quieto viendo la clase.
INACTIVIDAD_MIN = 20

# Cada cuanto mira el vigia. No hace falta afinar: 20 minutos de ocio se
# detectan igual mirando cada 20 s, y asi el hilo duerme casi todo el rato.
LATIDO_VIGIA_S = 20.0

# Latido del SSE. 15 s es el valor de manual: por debajo se llena el log del
# navegador de ruido, por encima hay proxies y antivirus que cortan una
# conexion callada. Es un COMENTARIO SSE (": latido"), no un evento: no
# dispara ningun handler en la pagina.
LATIDO_SSE_S = 15.0

# Eventos en vuelo por cliente. 64 es lo que aguanta un espectador que se
# quedo sin CPU medio segundo (la transcripcion escribe unas pocas lineas por
# segundo); pasado eso ese cliente ya no va a alcanzar el directo y se le
# echa. Es un TOPE DE PACIENCIA, no un percentil medido.
TOPE_COLA = 64

# Tope del cuerpo de UN evento SSE. "clase.json" lleva el JSON entero de
# jornada.json o de apuntes.json; con varios clientes eso se copia N veces. Lo
# que pasa de aqui se manda RECORTADO (con la ruta, que es lo que hace falta
# para releerlo del disco) en vez de callarse.
TOPE_EVENTO = 128 * 1024

# Segundos que un handler puede pasar sin que su socket avance. Sin esto una
# conexion que no termina las cabeceras deja su hilo clavado para siempre
# dentro del proceso del duenio (medido en el editor de flujos: 40 conexiones
# a medias -> 42 hilos vivos diez segundos despues).
TIMEOUT_CONEXION_S = 15.0

# Tope del apagado: `shutdown()` espera al `finally` de `serve_forever()` y
# eso corre dentro del `atexit`, donde una espera eterna cuelga el proceso.
TOPE_APAGADO_S = 5.0

# Trozo con el que se sirve un adjunto. Leer entero un clip de 30 MB para
# escribirlo de golpe es memoria retenida a cambio de nada.
_TROZO_ADJUNTO = 64 * 1024

# Solo estas tres direcciones. Un servidor con las notas del duenio no se
# sirve a la red de casa ni por descuido de quien llame.
HOSTS_PERMITIDOS = ("127.0.0.1", "localhost", "::1")

# La UNICA ruta que escribe. El nombre lo fija `vista_viva.RUTA_ACCION` y aqui
# se repite en vez de importarse: el transporte tiene que poder arrancar sin
# la pagina (ese es todo el motivo de `fijar_pagina`), y un import de arriba
# haria que una pagina rota dejara sin servidor.
RUTA_ACCION = "/accion"

# Tope del cuerpo de un POST. No es un numero de gusto: la accion mas gorda
# que existe es pegar una imagen, y `vista_viva.TOPE_IMAGEN_PEGADA` son 12 MB
# YA DECODIFICADOS, o sea 16 MB de base64 dentro del JSON. 20 MB deja margen
# para el resto del cuerpo y sigue siendo una cota dura: sin ella, un POST con
# un Content-Length de gigabytes se come la RAM del proceso que esta grabando
# la clase. Lo que pasa de aqui se rechaza POR LA CABECERA, antes de leer un
# solo byte del cuerpo.
TOPE_CUERPO = 20 * 1024 * 1024

# De donde sale el identificador de pestania (ver "EL ECO" en la cabecera).
# La query es lo que usa la pagina -- va incrustado en `ctx["accion"]` y en
# `ctx["eventos"]`, que la pagina copia tal cual --; la cabecera esta para
# cualquier otro cliente (los tests, un script) que no quiera tocar la URL.
QUERY_CLIENTE = "cli"
CABECERA_CLIENTE = "X-Cognia-Cliente"

# PUNTO DE EXTENSION de la puerta de escritura: que exige cada accion ANTES de
# que el manejador toque el disco. Las banderas:
#
#   "materia"  necesita una materia que se resuelva a una carpeta de verdad;
#   "id"       ademas apunta a un bloque que TIENE que existir ya;
#   "escribe"  cambia el documento -> se crea si no existe y se avisa por el
#              bus al terminar.
#
# Una accion que no este aqui NO se bloquea: se pasa al manejador, que tiene
# su propia validacion (documento.py lanza ErrorDocumento con el motivo
# escrito). Esta tabla solo adelanta el error y lo hace mas util -- por eso
# aniadir una accion nueva a `vista_viva.ACCIONES` sigue funcionando aunque
# nadie se acuerde de venir aqui.
EXIGENCIAS = {
    "aniadir": ("materia", "escribe"),
    "editar": ("materia", "id", "escribe"),
    "tipo": ("materia", "id", "escribe"),
    "mover": ("materia", "id", "escribe"),
    "borrar": ("materia", "id", "escribe"),
    "fijar": ("materia", "id", "escribe"),
    "formula": ("materia", "escribe"),
    "grafica": ("materia", "escribe"),
    "imagen": ("materia", "escribe"),
    "imagen_web": ("materia", "escribe"),
    "tabla": ("materia", "escribe"),
    "markdown": ("materia",),
    "buscar_imagenes": (),
}

# Cuantos ids se enumeran cuando el que pidieron no existe. Ocho caben en una
# linea de la pagina y ya dicen si el problema es "me equivoque de bloque" o
# "estoy mirando otro documento".
_IDS_EN_EL_ERROR = 8


# ---------------------------------------------------------------------------
# Estado de modulo
# ---------------------------------------------------------------------------

# Singleton: un unico servidor vivo por proceso. Dos cuadernos en vivo del
# mismo REPL solo servirian para tener dos pestanias apuntando a puertos
# distintos y una de ellas muerta.
_SERVER = None
_LOCK = threading.RLock()
_ATEXIT = [False]

# Los clientes SSE. Lista y no dict porque se recorre entera en cada evento y
# nunca se busca uno concreto.
_CLIENTES: list = []
_LOCK_CLIENTES = threading.RLock()

# Contadores de la puerta de diagnostico. Viven en el modulo y no en el
# servidor para que sobrevivan a un `parar()` y se pueda ver que paso.
_REPARTIDOS = itertools.count(0)
_ENVIADOS = [0]
_LENTOS = [0]
_OMITIDOS = [0]
_ESCRITURAS = [0]
_ULTIMO_ERROR: dict = {}

# El gancho de la pagina de verdad (ver fijar_pagina).
_PAGINA = None

# El gancho del manejador de acciones (ver fijar_acciones). En None se usa
# `vista_viva.aplicar_accion`, que es el manejador de la casa.
_ACCIONES = None

# QUIEN esta escribiendo AHORA en este hilo. Es lo que hace que el autor no
# reciba su propio cambio por el SSE: `almacen._emitir` corre en el hilo del
# que escribe, o sea en el hilo de este POST, asi que `_desde_el_bus` puede
# leerlo sin que nadie tenga que pasarselo. Un `threading.local` y no un
# global porque el refinado de la IA escribe a la vez desde otro hilo y ESE
# cambio si tiene que llegarle a todo el mundo.
_AUTOR = threading.local()


def _autor_actual() -> str:
    return str(getattr(_AUTOR, "cliente", "") or "")


def _avisar(donde: str, motivo: str, accion: str = "") -> None:
    """Deja constancia de una degradacion por el canal de la casa.

    Mismo patron que `almacen._degradar_una_vez`, con el import perezoso por
    la misma razon: este modulo es transporte y no puede dejar de importarse
    porque cambie la UX. Aqui NO es log-once -- los fallos de este modulo son
    raros y de a uno (un cliente lento, una pagina inyectada que revienta), no
    decenas de miles como los eventos de una jornada -- pero SI se guarda el
    ultimo para `estado()`, que es lo que se mira cuando el cuaderno se queda
    quieto y nadie sabe si es que no pasa nada o es que esta roto.
    """
    _ULTIMO_ERROR.clear()
    _ULTIMO_ERROR.update({"donde": donde, "motivo": motivo, "t": time.time()})
    log.warning("clases.servidor_vivo: %s -- %s", donde, motivo)
    try:
        from cognia.ux import events as _ux
        _ux.emitir(_ux.Degradado(donde=donde, motivo=motivo,
                                 accion_sugerida=accion))
    except Exception as exc:
        # El canal de avisos es justo lo que se acaba de romper: queda en el
        # log y se sigue. Nunca un except mudo.
        log.warning("clases.servidor_vivo: tampoco pude avisar por ux (%s)",
                    exc)


# ---------------------------------------------------------------------------
# Clientes SSE: una cola por cada uno
# ---------------------------------------------------------------------------

class _Cliente:
    """Un espectador SSE: su cola, su socket y sus cuentas.

    El socket se guarda porque es la UNICA forma de despertar al hilo del
    handler cuando esta bloqueado escribiendo en un cliente que no lee: un
    `shutdown()` desde el hilo del bus hace que ese `write` levante en vez de
    esperar al timeout del socket. La bandera `muerto` sola no basta -- nadie
    la mira mientras se esta bloqueado dentro de `write`.
    """

    __slots__ = ("cola", "conn", "hilo", "muerto", "motivo", "desde",
                 "enviados", "perdidos", "cid", "omitidos")

    def __init__(self, conn, cid: str = ""):
        # El tope se lee AQUI (global del modulo) y no como default de la
        # firma: asi un ajuste de TOPE_COLA vale para el siguiente cliente sin
        # reimportar nada.
        self.cola = queue.Queue(maxsize=max(1, int(TOPE_COLA)))
        self.conn = conn
        self.hilo = threading.current_thread()
        self.muerto = False
        self.motivo = ""
        self.desde = time.time()
        self.enviados = 0
        self.perdidos = 0
        # El identificador de la pestania. Vacio = un cliente que no dijo
        # quien es (un curl, el placeholder viejo): a ese se le manda TODO,
        # porque suprimirle un eco que quiza si necesita seria peor que
        # mandarselo dos veces.
        self.cid = str(cid or "")
        self.omitidos = 0


def _suscribir(conn, cid: str = "") -> _Cliente:
    cli = _Cliente(conn, cid)
    with _LOCK_CLIENTES:
        _CLIENTES.append(cli)
    return cli


def _desuscribir(cli: _Cliente) -> None:
    """Saca al cliente de la lista. Idempotente: lo llama el `finally` del
    handler y tambien puede haberlo sacado ya `_matar` desde el hilo del bus.
    """
    with _LOCK_CLIENTES:
        if cli in _CLIENTES:
            _CLIENTES.remove(cli)


def _matar(cli: _Cliente, motivo: str) -> None:
    """Echa a un cliente y le cierra el socket, desde cualquier hilo.

    El `shutdown()` es lo que hace que esto funcione de verdad: despierta al
    hilo del handler aunque este bloqueado en `write` contra un cliente que
    no lee. El `close` lo hace el propio handler al terminar, que es quien es
    duenio del socket; aqui solo se le corta el suministro.
    """
    cli.muerto = True
    cli.motivo = motivo
    _desuscribir(cli)
    try:
        cli.cola.put_nowait(None)     # despierta al que espera en la cola
    except queue.Full:
        pass                          # ya tiene 64 cosas que leer: da igual
    try:
        cli.conn.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass                          # ya estaba cerrado por el otro lado


def _n_clientes() -> int:
    with _LOCK_CLIENTES:
        return len(_CLIENTES)


def _cerrar_clientes(motivo: str) -> None:
    with _LOCK_CLIENTES:
        vivos = list(_CLIENTES)
    for cli in vivos:
        _matar(cli, motivo)


def _formatear(ev: dict) -> str:
    """El evento del bus a un frame SSE, serializado UNA vez para todos.

    `default=str` para que un Path o un datetime que se cuele en el payload no
    tumbe el reparto entero: el evento llega feo antes que no llegar.

    Lo que pasa de TOPE_EVENTO se manda RECORTADO conservando la ruta: quien
    escucha puede releer el fichero del disco (el evento se emite DESPUES del
    fsync, esa es toda su gracia), y asi un apuntes.json de dos megas no se
    copia a la cola de cada espectador.
    """
    nombre = str(ev.get("evento") or "clase")
    try:
        cuerpo = json.dumps(ev, ensure_ascii=False, default=str)
    except (TypeError, ValueError) as exc:
        cuerpo = json.dumps({"evento": nombre, "ts": ev.get("ts"),
                             "aviso": "payload no serializable: %s" % exc},
                            ensure_ascii=False)
    if len(cuerpo) > TOPE_EVENTO:
        cuerpo = json.dumps({"evento": nombre, "ts": ev.get("ts"),
                             "ruta": str(ev.get("ruta") or ""),
                             "recortado": len(cuerpo)}, ensure_ascii=False)
    n = next(_REPARTIDOS)
    # `id:` para que el navegador mande Last-Event-ID al reconectar. Hoy no se
    # usa para reponer nada (el estado de verdad esta en disco), pero cuesta
    # una linea y deja la puerta abierta.
    return "id: %d\nevent: %s\ndata: %s\n\n" % (n, nombre, cuerpo)


def _desde_el_bus(ev) -> None:
    """El suscriptor. Corre EN EL HILO QUE ESCRIBE LA CLASE: no bloquea.

    Todo lo que hace es serializar una vez y `put_nowait` por cliente. Nada
    de sockets, nada de disco, nada de locks que no sean los dos de aqui.
    Almacen mide este callback y denuncia si pasa de 0,25 s, asi que no es
    una recomendacion: es el contrato.

    Cola llena = ese cliente no alcanza el directo y se le echa CONTANDOLO.
    La alternativa (esperar sitio) es exactamente lo que no se puede hacer:
    frenaria la transcripcion de la clase por un navegador minimizado.

    El try de fuera existe porque este callback es el ULTIMO codigo que corre
    dentro del `apendar` del grabador: un fallo aqui (una lista mutada, un
    socket raro) no puede propagarse a quien esta guardando la clase.

    EL AUTOR SE SALTA AQUI, y antes de serializar. Si el unico que mira es la
    pestania que acaba de guardar, este evento no cuesta ni un `json.dumps`
    dentro del hilo que escribe -- y sobre todo no le vuelve a esa pestania el
    bloque que su duenio esta corrigiendo en ese momento. Ver "EL ECO" en la
    cabecera del modulo.
    """
    try:
        autor = _autor_actual()
        with _LOCK_CLIENTES:
            if not _CLIENTES:
                return                      # nadie mira: ni serializar
            destinos = [c for c in _CLIENTES
                        if not (autor and c.cid and c.cid == autor)]
            for c in _CLIENTES:
                if autor and c.cid and c.cid == autor:
                    c.omitidos += 1
                    _OMITIDOS[0] += 1
        if not destinos:
            return                          # solo miraba el propio autor
        trozo = _formatear(ev if isinstance(ev, dict) else {"evento": "clase"})
        _ENVIADOS[0] += 1
        for cli in destinos:
            if cli.muerto:
                continue
            try:
                cli.cola.put_nowait(trozo)
            except queue.Full:
                cli.perdidos += 1
                _LENTOS[0] += 1
                _matar(cli, "cola llena (%d eventos sin leer)" % TOPE_COLA)
                _avisar("clases.servidor_vivo.cliente_lento",
                        "un cliente SSE acumulo %d eventos sin leer y se le "
                        "desconecto para no frenar la grabacion" % TOPE_COLA,
                        accion="recargar la pagina del cuaderno")
    except Exception as exc:
        nombre = ev.get("evento") if isinstance(ev, dict) else "?"
        _avisar("clases.servidor_vivo.bus",
                "el reparto de %r reviento (%s: %s)"
                % (nombre, type(exc).__name__, exc),
                accion="revisar cognia/clases/servidor_vivo.py")


def _enganchar_bus() -> None:
    """Suscribe `_desde_el_bus` a los dos eventos del cuaderno.

    `EventBus.subscribe` ya deduplica por identidad del callback, asi que
    llamar dos veces no duplica entregas.
    """
    from cognia import events
    for nombre in EVENTOS:
        events.subscribe(nombre, _desde_el_bus)


def _soltar_bus() -> None:
    """Desengancha. Se hace ANTES de cerrar clientes en `parar()`: un evento
    que llega mientras se esta apagando solo puede acabar en un socket que ya
    no existe."""
    try:
        from cognia import events
        for nombre in EVENTOS:
            events.unsubscribe(nombre, _desde_el_bus)
    except Exception as exc:
        _avisar("clases.servidor_vivo.bus",
                "no se pudo desenganchar del bus (%s: %s)"
                % (type(exc).__name__, exc),
                accion="revisar cognia/events.py")


# ---------------------------------------------------------------------------
# La pagina: gancho + placeholder
# ---------------------------------------------------------------------------

def fijar_pagina(render) -> None:
    """Inyecta quien pinta `GET /`. `None` vuelve al placeholder.

    `render(ctx: dict) -> str`, con ctx = {"base", "token", "puerto",
    "eventos", "estado", "adj"}: las URLs ya montadas con el token, para que
    la pagina no tenga que saber como se pasa la credencial.

    ES UN GANCHO Y NO UN import PORQUE LA PAGINA ES DE OTRA PIEZA. El
    transporte tiene que poder arrancar, servir y probarse aunque la pagina de
    verdad todavia no exista o reviente al pintarse: si `render` lanza, se
    sirve el placeholder y se avisa (ver `_servir_pagina`). Al reves -- un
    import directo -- una pagina rota dejaria sin cuaderno en vivo Y sin
    forma de ver que se rompio.
    """
    global _PAGINA
    if render is not None and not callable(render):
        raise TypeError("fijar_pagina espera un callable(ctx) -> str o None")
    _PAGINA = render


def fijar_acciones(manejador) -> None:
    """Inyecta quien APLICA lo que llega por `POST /accion`. `None` vuelve al
    manejador de la casa (`vista_viva.aplicar_accion`).

    `manejador(peticion: dict) -> dict` con `{"ok": True, ...}` o
    `{"ok": False, "error": "<escrito para un humano>"}`.

    ES UN GANCHO POR LO MISMO QUE `fijar_pagina`, y ademas por una razon
    propia: aqui se decide QUE se puede escribir en el cuaderno del duenio.
    Con el gancho, un test puede probar el guardia, el tope de cuerpo y la
    supresion del eco sin arrastrar la pagina entera; y el dia que haya otro
    consumidor (un editor distinto, un modo lectura-escritura acotado) se le
    pasa SU manejador en vez de tocar el transporte.

    El default NO es None-y-a-callar: sin manejador inyectado se importa
    perezosamente `vista_viva.aplicar_accion`, que es el que entra por las
    puertas de `documento.py`. Asi el cuaderno guarda de verdad sin que nadie
    tenga que cablear nada, y si ese import falla se contesta con el motivo
    (ver `_manejador`).
    """
    global _ACCIONES
    if manejador is not None and not callable(manejador):
        raise TypeError("fijar_acciones espera un callable(peticion) -> dict "
                        "o None")
    _ACCIONES = manejador


def _manejador():
    """El manejador de acciones vigente, o `None` si no hay ninguno usable.

    El import es PEREZOSO y va aqui dentro: `vista_viva` arrastra la pagina
    entera (y con ella `documento`, `almacen` y la tabla de MIME), y este
    modulo tiene que poder importarse y servir aunque esa pieza este rota.
    Cuando no se puede, se avisa por el canal de degradacion y quien pidio la
    accion recibe el motivo escrito -- que es lo unico que distingue "no lo
    cablearon" de "se rompio".
    """
    if _ACCIONES is not None:
        return _ACCIONES
    try:
        from cognia.clases import vista_viva
        return vista_viva.aplicar_accion
    except Exception as exc:
        _avisar("clases.servidor_vivo.acciones",
                "no se pudo cargar el manejador de escritura de "
                "vista_viva.py (%s: %s): el cuaderno solo puede leerse"
                % (type(exc).__name__, exc),
                accion="revisar cognia/clases/vista_viva.py")
        return None


def _pagina_placeholder(ctx: dict) -> str:
    """El minimo que demuestra que el transporte funciona, y lo dice.

    No pretende ser el cuaderno: abre el SSE y va escribiendo lo que llega.
    Sirve para verificar a mano (con el REPL grabando al lado) que los eventos
    salen, que es justo lo que un test no puede ensenniar.
    """
    eventos = json.dumps(ctx.get("eventos", ""))
    return (
        "<!doctype html>\n<html lang=\"es\"><head><meta charset=\"utf-8\">\n"
        "<title>Cuaderno en vivo (placeholder)</title>\n"
        "<style>body{font:14px/1.5 system-ui,sans-serif;margin:2rem;"
        "background:#111;color:#eee}li{font-family:ui-monospace,monospace;"
        "font-size:12px}code{color:#8cf}</style></head><body>\n"
        "<h1>Cuaderno en vivo</h1>\n"
        "<p>Esto es el <b>placeholder del transporte</b>: la pagina de verdad "
        "se inyecta con <code>servidor_vivo.fijar_pagina()</code>. Lo que "
        "sale abajo son los eventos que "
        "<code>cognia/clases/almacen.py</code> acaba de escribir en disco."
        "</p>\n<p id=\"estado\">conectando...</p>\n<ul id=\"log\"></ul>\n"
        "<script>\n"
        "var es = new EventSource(" + eventos + ");\n"
        "var log = document.getElementById('log');\n"
        "var est = document.getElementById('estado');\n"
        "es.onopen = function(){ est.textContent = 'conectado'; };\n"
        "es.onerror = function(){ est.textContent = 'sin conexion'; };\n"
        "function pinta(e){ var li = document.createElement('li');\n"
        "  li.textContent = e.type + '  ' + e.data.slice(0, 300);\n"
        "  log.insertBefore(li, log.firstChild);\n"
        "  while (log.children.length > 200) log.removeChild(log.lastChild); }\n"
        "es.addEventListener('clase.entrada', pinta);\n"
        "es.addEventListener('clase.json', pinta);\n"
        "</script>\n</body></html>\n")


# ---------------------------------------------------------------------------
# Adjuntos: la ruta se sanea con almacen._seguro y ADEMAS se comprueba
# ---------------------------------------------------------------------------

def _mimes_servibles() -> dict:
    """{extension: mime} de lo que la vista sabe ensenniar.

    Se lee de `vista._MIME_IMAGEN` y no se copia: si el cuaderno solo sabe
    embeber seis formatos, servir un septimo dejaria el fichero descargado y
    la entrada muda. Una sola fuente de verdad.
    """
    try:
        from cognia.clases import vista
        return dict(vista._MIME_IMAGEN)
    except Exception as exc:
        _avisar("clases.servidor_vivo.mimes",
                "no se pudo leer la tabla de MIME de vista.py (%s: %s): los "
                "adjuntos se sirven como descarga" % (type(exc).__name__, exc),
                accion="revisar cognia/clases/vista.py")
        return {}


def _ruta_adjunto(jornada: str, nombre: str) -> Path:
    """La ruta del adjunto, saneada, SIN crear nada y sin poder escaparse.

    Tres cosas, y ninguna sobra:

    1. `almacen._seguro` en los DOS tramos. Es el saneador de la casa (deja
       alfanumericos y " -_." y recorta), y usarlo -- privado y todo -- en vez
       de escribir otro es a proposito: dos saneadores distintos para el mismo
       nombre acaban discrepando, y el dia que discrepan uno de los dos deja
       pasar algo.
    2. NO se llama a `almacen.ruta_adjunto`, que hace lo mismo pero pasando
       por `dir_jornada`, y `dir_jornada` CREA `audio/` y `adjuntos/`. Un GET
       de un curioso a `/adj/loquesea/x.png` fabricaria carpetas de jornada
       vacias en el cuaderno del duenio. Un servidor de solo lectura no toca
       el disco.
    3. Cinturon y tirantes: se resuelve y se comprueba que sigue DENTRO de
       `adjuntos/`. Con `_seguro` no deberia poder salirse nunca (una barra o
       un ".." se convierten en "-" y el nombre vacio cae a "sin-nombre");
       esta comprobacion es la que garantiza que si alguien afloja `_seguro`
       manniana, aqui se ve un 403 y no una fuga.
    """
    base = alm.raiz() / "jornadas" / alm._seguro(jornada) / alm.DIR_ADJUNTOS
    destino = base / alm._seguro(nombre)
    try:
        base_r = base.resolve()
        destino_r = destino.resolve()
    except OSError as exc:
        raise ValueError("ruta de adjunto irresoluble: %s" % exc) from exc
    if base_r not in destino_r.parents:
        raise ValueError("el adjunto %r se sale de la jornada %r"
                         % (nombre, jornada))
    return destino_r


# ---------------------------------------------------------------------------
# La puerta de escritura: validar (sin tocar disco), preparar y avisar
# ---------------------------------------------------------------------------

class _PeticionMala(Exception):
    """Un cuerpo que ni se llega a mirar. Lleva SU codigo HTTP dentro.

    Existe para que `_leer_json` pueda cortar en cualquiera de sus seis
    comprobaciones con el codigo que corresponde (411, 413, 415, 400) sin
    devolver tuplas ni banderas por medio programa.
    """

    def __init__(self, motivo: str, code: int = 400):
        super().__init__(motivo)
        self.code = int(code)


def _texto_de(p: dict, clave: str) -> str:
    """El valor de una clave como texto, o "" si no vino.

    Un numero o un booleano se convierten (un id JSON puede llegar como
    numero desde un cliente que no sea la pagina); una lista o un dict NO se
    aplastan a su repr: eso es una peticion mal formada y `_revisar_forma` la
    tiene que poder negar.
    """
    v = p.get(clave)
    if v is None:
        return ""
    if isinstance(v, (dict, list, tuple)):
        return "\x00"          # marca de "esto no es un texto"
    return str(v).strip()


def _revisar_forma(peticion) -> tuple:
    """Todo lo que se puede negar SIN tocar el disco.

    Devuelve `(nombre, exige, error)`. Con `error` no vacio no se llama al
    manejador: el mensaje esta escrito para pintarlo en la pagina.

    El `tipo` se valida CONTRA `documento.TIPOS`, que es la lista cerrada, y
    no contra lo que se le ocurra a quien manda el JSON: un tipo inventado se
    guardaria en el diario y luego no lo sabria pintar nadie -- texto que el
    duenio ve escribirse y despues no encuentra, que es el modo de fallo caro
    de esta casa.
    """
    if not isinstance(peticion, dict):
        return "", (), ("una accion se pide con un objeto JSON, llego %s"
                        % type(peticion).__name__)
    nombre = _texto_de(peticion, "accion")
    if not nombre or nombre == "\x00":
        return "", (), "falta 'accion' en la peticion: no se que hacer"
    exige = tuple(EXIGENCIAS.get(nombre, ()))
    for clave in ("materia", "id", "tras", "tipo"):
        if _texto_de(peticion, clave) == "\x00":
            return nombre, exige, ("'%s' tiene que ser texto, no %s"
                                   % (clave, type(peticion[clave]).__name__))
    tipo = _texto_de(peticion, "tipo")
    if tipo:
        try:
            from cognia.clases import documento as _doc
        except Exception as exc:
            return nombre, exige, ("no puedo validar el tipo de bloque: "
                                   "documento.py no es importable (%s: %s)"
                                   % (type(exc).__name__, exc))
        if tipo not in _doc.TIPOS:
            return nombre, exige, (
                "tipo de bloque %r desconocido; los que hay son: %s"
                % (tipo, ", ".join(_doc.TIPOS)))
    if "materia" in exige and not _texto_de(peticion, "materia"):
        return nombre, exige, ("falta 'materia' en la peticion: no se en que "
                               "documento escribir")
    if "id" in exige and not _texto_de(peticion, "id"):
        return nombre, exige, ("falta 'id' en la peticion: no se que bloque "
                               "tocar")
    return nombre, exige, ""


def _revisar_documento(peticion: dict, exige) -> str:
    """Lo que SI toca disco: la materia se resuelve y el id existe.

    Devuelve "" o el motivo escrito. Dos cosas, y ninguna sobra:

    1. LA MATERIA SE TIENE QUE RESOLVER. `almacen._seguro` convierte
       cualquier cosa en un nombre de fichero valido y lo vacio cae a
       "sin-nombre": una materia de puros signos escribiria en una carpeta
       que el duenio no pidio y NADIE lo diria. Aqui se dice.
    2. EL ID TIENE QUE EXISTIR, y si no, se enumeran los que hay. El
       manejador tambien lo comprueba (documento.py lanza ErrorDocumento),
       pero ese mensaje no dice cuales son los ids buenos, y el fallo tipico
       es tener abierta otra materia.

    Con "escribe" el documento SE CREA si no existe -- es lo que hace que el
    primer bloque de una materia nueva no falle --, y se crea por
    `documento.abrir`, o sea con su linea 'crear' en el diario y el nombre
    REAL de la materia dentro. Sin "escribe" no se crea nada: mirar un
    documento no puede fabricarlo.
    """
    if "materia" not in exige:
        return ""
    materia = _texto_de(peticion, "materia")
    saneada = alm._seguro(materia)
    if saneada == "sin-nombre" and materia.lower() != "sin-nombre":
        return ("la materia %r no se puede resolver a una carpeta del "
                "cuaderno: escribela con letras o numeros" % materia)
    try:
        from cognia.clases import documento as _doc
    except Exception as exc:
        return ("no puedo escribir: documento.py no es importable (%s: %s)"
                % (type(exc).__name__, exc))
    try:
        doc = _doc.abrir(materia, crear=("escribe" in exige))
    except _doc.ErrorDocumento as exc:
        return str(exc)
    except OSError as exc:
        return ("no pude abrir el documento de %r en disco (%s)"
                % (materia, exc))
    if "id" not in exige:
        return ""
    bid = _texto_de(peticion, "id")
    if doc.bloque(bid) is not None:
        return ""
    ids = [b.id for b in doc.bloques]
    muestra = ", ".join(ids[:_IDS_EN_EL_ERROR]) or "(ninguno: esta vacio)"
    resto = ("" if len(ids) <= _IDS_EN_EL_ERROR
             else " (y %d mas)" % (len(ids) - _IDS_EN_EL_ERROR))
    return ("en el documento de %r no hay ningun bloque %r; los que hay son: "
            "%s%s" % (materia, bid, muestra, resto))


def _avisar_del_cambio(nombre: str, peticion: dict, respuesta: dict) -> None:
    """Emite `clase.accion` por el bus tras una escritura que salio bien.

    POR QUE UN EVENTO PROPIO SI `almacen` YA EMITE. Lo que almacen emite es la
    LINEA DEL DIARIO ('editar b0003', 'mover b0007'), que es justo lo que la
    pagina necesita para actualizar un bloque. Esto otro dice QUE PASO a nivel
    de accion (que materia, que accion, que id) y le sirve a cualquier otro
    que escuche el bus -- el widget, un log, una segunda pieza -- sin tener
    que reconstruirlo de las lineas sueltas.

    Va por `almacen._emitir` y no por `events.emit` a proposito: esa es la
    puerta que emite VOLATIL (sin entrar en el historial del bus, que es de
    tamanio acotado y lo mira el panel de analiticas) y la que ya tiene el
    fallback si el bus cambia de forma. Dos formas de emitir el mismo tipo de
    evento acabarian con la mitad de los eventos en el historial.

    Corre TODAVIA dentro de la ventana del autor (`_AUTOR`), asi que este
    evento tampoco le vuelve a la pestania que lo provoco.
    """
    try:
        alm._emitir(EVENTO_ACCION, accion=nombre,
                    materia=_texto_de(peticion, "materia"),
                    id=_texto_de(peticion, "id") or str(respuesta.get("id")
                                                        or ""),
                    autor=_autor_actual())
    except Exception as exc:
        # La escritura YA se hizo: esto solo es el aviso a las demas
        # pestanias. Se dice y se sigue -- nunca un except mudo.
        _avisar("clases.servidor_vivo.aviso_cambio",
                "la accion %r se guardo pero no se pudo anunciar por el bus "
                "(%s: %s): otras pestanias pueden quedarse desfasadas"
                % (nombre, type(exc).__name__, exc),
                accion="recargar la otra pestania del cuaderno")


# ---------------------------------------------------------------------------
# El handler
# ---------------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    """Las cuatro rutas. Todo lo suyo cuelga de `self.server`."""

    server_version = "CogniaClaseViva/1.0"
    sys_version = ""

    # `StreamRequestHandler.setup()` lo pasa a `connection.settimeout()`, asi
    # que cubre la linea de peticion -- que se lee ANTES del token -- y
    # tambien las escrituras del SSE. `handle_one_request` captura el
    # TimeoutError que sale de ahi: el hilo muere en vez de quedarse clavado.
    timeout = TIMEOUT_CONEXION_S

    # -- plomeria ----------------------------------------------------------
    def _marcar(self) -> None:
        """Una peticion VALIDA mas: reinicia el reloj del auto-apagado.

        Se llama DESPUES del guardia, nunca antes: un 403 que rearmara el
        reloj deja que cualquier proceso local mantenga vivo el servidor sin
        credencial, que es justo el control que el auto-apagado promete.
        """
        srv = self.server
        with getattr(srv, "contador_lock", _LOCK):
            srv.ultimo = time.time()
            srv.peticiones = getattr(srv, "peticiones", 0) + 1

    def _cabeceras(self, tipo: str, code: int = 200, largo=None,
                   extra=None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", tipo)
        if largo is not None:
            self.send_header("Content-Length", str(largo))
        # Las notas del duenio no se cachean ni se adivinan de tipo.
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()

    def _enviar(self, cuerpo: bytes, tipo: str, code: int = 200,
                extra=None) -> None:
        self._cabeceras(tipo, code, len(cuerpo), extra)
        try:
            self.wfile.write(cuerpo)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError,
                OSError):
            pass  # el navegador cerro la pestania a mitad

    def _json(self, obj, code: int = 200) -> None:
        cuerpo = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self._enviar(cuerpo, "application/json; charset=utf-8", code)

    def _error(self, motivo, code: int = 400) -> None:
        self._json({"ok": False, "error": str(motivo)}, code)

    def _html(self, texto: str, code: int = 200) -> None:
        self._enviar(texto.encode("utf-8"), "text/html; charset=utf-8", code)

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
        resuelva a 127.0.0.1 llega con SU nombre en `Host` y ahi se para. Un
        `Host` ausente (HTTP/1.0 a pelo) no es vector de rebinding y no se
        bloquea; lo que se bloquea es un `Host` AJENO.
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
        un `?t=` con un solo byte >127 reventaba el guardia del editor de
        flujos sin devolver codigo HTTP y volcando el traceback al REPL. En
        bytes no hay caso que lance.

        Se acepta en la QUERY ademas de en la cabecera porque `EventSource` no
        puede poner cabeceras: sin `?t=` no hay SSE. La query se queda en el
        historial del navegador del duenio, que es el mismo sitio donde ya
        esta la URL del editor de flujos.
        """
        esperado = str(getattr(self.server, "token", "") or "")
        if not esperado:
            return False
        dado = (self.headers.get("X-Cognia-Token")
                or self._query().get("t") or "")
        return secrets.compare_digest(str(dado).encode("utf-8", "ignore"),
                                      esperado.encode("utf-8"))

    def _cliente_id(self) -> str:
        """El identificador de la pestania que habla, saneado.

        NO ES UNA CREDENCIAL y no se compara con nada guardado: solo sirve
        para que el SSE sepa a quien NO mandarle el eco de su propia
        escritura (ver "EL ECO" en la cabecera). Por eso se acepta el que
        diga el cliente; lo que autoriza es el token, que ya paso.

        Se sanea igual: viaja en cabeceras y en la query, y un valor con
        saltos de linea o de kilobytes acabaria en el log y en la lista de
        clientes. Alfanumericos, guion y guion bajo, 40 caracteres.
        """
        crudo = (self.headers.get(CABECERA_CLIENTE)
                 or self._query().get(QUERY_CLIENTE) or "")
        limpio = "".join(c for c in str(crudo)
                         if c.isalnum() or c in "-_")[:40]
        return limpio

    def _leer_json(self):
        """El cuerpo del POST, ya parseado. Lanza `_PeticionMala` con codigo.

        EL ORDEN DE LAS COMPROBACIONES ES EL PUNTO. Se niega por la CABECERA
        -- antes de leer un solo byte del cuerpo -- todo lo que se puede:

          - `Transfer-Encoding` (chunked): este handler es HTTP/1.0 y no
            desagrupa trozos; leerlo como si fuera plano dejaria basura en el
            socket y un JSON roto que nadie sabria explicar.
          - `Content-Type: application/json`: la pagina lo manda asi, y de
            paso es defensa en profundidad contra CSRF -- un formulario de
            otro sitio solo puede mandar tres tipos, y ninguno es este (el
            token seguiria parandolo igual; esto es el segundo cerrojo).
          - `Content-Length` presente, numerico y por debajo de `TOPE_CUERPO`.
            ESTA es la que impide que un cuerpo enorme tumbe el proceso que
            esta grabando la clase: se rechaza por lo DECLARADO, sin
            reservar memoria.

        Y luego se lee EXACTAMENTE lo declarado, en trozos: `rfile.read()` a
        secas sobre un socket que no cierra se queda esperando para siempre.
        """
        te = (self.headers.get("Transfer-Encoding") or "").strip().lower()
        if te:
            raise _PeticionMala(
                "este servidor no entiende Transfer-Encoding %r: manda el "
                "cuerpo entero con Content-Length" % te, 411)
        tipo = (self.headers.get("Content-Type") or "").split(";")[0]
        tipo = tipo.strip().lower()
        if tipo != "application/json":
            raise _PeticionMala(
                "una accion se manda con Content-Type: application/json "
                "(llego %r)" % tipo, 415)
        bruto = self.headers.get("Content-Length")
        if bruto is None:
            raise _PeticionMala(
                "falta Content-Length: sin saber cuanto ocupa el cuerpo no se "
                "puede comprobar el tope", 411)
        try:
            largo = int(str(bruto).strip())
        except (TypeError, ValueError):
            raise _PeticionMala("Content-Length %r no es un numero" % bruto,
                                400) from None
        if largo < 0:
            raise _PeticionMala("Content-Length %r no es un numero" % bruto,
                                400)
        tope = max(1, int(TOPE_CUERPO))
        if largo > tope:
            # Se contesta y se cierra SIN leer el cuerpo: leerlo para poder
            # rechazarlo seria hacer justo lo que se esta prohibiendo.
            self.close_connection = True
            raise _PeticionMala(
                "el cuerpo declara %d bytes y el tope de esta puerta son %d "
                "(%.0f MB). Si es una imagen, pesa demasiado para pegarla."
                % (largo, tope, tope / 1048576.0), 413)
        trozos = []
        leidos = 0
        while leidos < largo:
            trozo = self.rfile.read(min(_TROZO_ADJUNTO, largo - leidos))
            if not trozo:
                raise _PeticionMala(
                    "el cuerpo llego a medias (%d de %d bytes): se corto la "
                    "conexion" % (leidos, largo), 400)
            trozos.append(trozo)
            leidos += len(trozo)
        crudo = b"".join(trozos)
        try:
            texto = crudo.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise _PeticionMala("el cuerpo no viene en UTF-8 (%s)" % exc,
                                400) from None
        try:
            return json.loads(texto or "null")
        except ValueError as exc:
            raise _PeticionMala("el cuerpo no es JSON valido: %s" % exc,
                                400) from None

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
            # consola del navegador se llene de 403 que no son del duenio.
            return self._enviar(b"", "image/x-icon", 204)
        try:
            # EL GUARDIA VA DENTRO DEL try: es codigo, y el codigo falla. Con
            # `_pasa()` fuera, un token con un byte raro cierra la conexion
            # sin respuesta y escupe el traceback al REPL.
            if not self._pasa():
                return None
            self._marcar()   # solo cuenta lo que paso el guardia
            if ruta in ("/", "/index.html"):
                return self._servir_pagina()
            if ruta == "/eventos":
                return self._eventos()
            if ruta == "/estado":
                return self._servir_estado()
            if ruta.startswith("/adj/"):
                return self._servir_adjunto(ruta)
            return self._error("no existe", 404)
        except Exception as exc:  # el servidor jamas se cae por una ruta
            return self._fallo(exc)

    def do_POST(self):  # noqa: N802
        """UNA ruta escribe (`/accion`); las demas siguen siendo 404 CON
        MOTIVO, que no es lo mismo que no existir.

        EL GUARDIA VA PRIMERO Y EL CUERPO NI SE MIRA HASTA DESPUES. Un POST
        sin token, o con el Origin de otro sitio, se contesta 403 sin haber
        leido un byte de lo que traia: esto ya no es un mirador, es una puerta
        de escritura sobre las notas del duenio.
        """
        ruta = urllib.parse.urlsplit(self.path).path
        try:
            if not self._pasa():
                return None
            self._marcar()   # solo cuenta lo que paso el guardia
            if ruta == RUTA_ACCION:
                return self._accion()
            return self._error(
                "no hay nada que escribir en %r: la unica puerta de escritura "
                "de este servidor es POST %s" % (ruta, RUTA_ACCION), 404)
        except Exception as exc:
            return self._fallo(exc)

    def _accion(self):
        """`POST /accion`: valida, delega en el manejador y devuelve el estado.

        LO QUE HACE ESTE METODO NO ES ESCRIBIR. Es: leer el cuerpo con tope,
        negar lo que no puede pasar, marcar quien es el autor para que no le
        vuelva su propio cambio, llamar al manejador (que entra por
        `documento.py`, con su lock y su diario) y anunciar el cambio por el
        bus. Ni un `open()` del documento sale de aqui.

        NUNCA SALE UNA TRAZA. Todo lo que puede fallar se contesta en JSON con
        el motivo escrito para pintarlo en la pagina: un traceback en el
        cuerpo de la respuesta acabaria en la pantalla del duenio mientras da
        clase, y no le diria que hacer.
        """
        try:
            peticion = self._leer_json()
        except _PeticionMala as exc:
            return self._error(exc, exc.code)
        nombre, exige, error = _revisar_forma(peticion)
        if error:
            return self._error(error, 400)
        error = _revisar_documento(peticion, exige)
        if error:
            return self._error(error, 400)
        manejador = _manejador()
        if manejador is None:
            return self._error(
                "el cuaderno no tiene manejador de escritura cargado: se "
                "puede leer, pero no guardar (mira /grabar-clase vivo estado)",
                503)
        cid = self._cliente_id()
        _AUTOR.cliente = cid
        try:
            try:
                respuesta = manejador(dict(peticion))
            except Exception as exc:
                # El manejador de la casa promete no lanzar; uno inyectado
                # puede. Se contesta el motivo, no la traza.
                _avisar("clases.servidor_vivo.accion",
                        "la accion %r reviento en el manejador (%s: %s)"
                        % (nombre, type(exc).__name__, exc),
                        accion="revisar cognia/clases/vista_viva.py")
                return self._error(
                    "no se pudo aplicar %r: %s" % (nombre, exc), 500)
            if not isinstance(respuesta, dict):
                return self._error(
                    "el manejador de %r contesto %s en vez de un objeto"
                    % (nombre, type(respuesta).__name__), 500)
            if not respuesta.get("ok"):
                respuesta.setdefault("ok", False)
                respuesta.setdefault("error", "la accion %r no se pudo "
                                              "aplicar" % nombre)
                return self._json(respuesta, 400)
            if "escribe" in exige:
                _ESCRITURAS[0] += 1
                _avisar_del_cambio(nombre, peticion, respuesta)
        finally:
            # SIEMPRE. Hoy cada peticion trae su hilo (HTTP/1.0 + threading),
            # pero la ventana del autor tiene que cerrarse donde se abrio: el
            # dia que este handler hable HTTP/1.1, una segunda peticion por la
            # misma conexion heredaria el autor de la anterior y le comeria
            # los eventos de la clase a esa pestania.
            _AUTOR.cliente = ""
        respuesta["autor"] = cid
        return self._json(respuesta, 200)

    def _fallo(self, exc):
        """El 500 de ultimo recurso, que tampoco puede levantar.

        Si el socket ya se fue, hasta `send_response` falla; se traga aqui
        porque a estas alturas no hay a quien contarselo -- pero se anota en
        `estado()["ultimo_error"]`, que para eso existe.
        """
        _avisar("clases.servidor_vivo.ruta",
                "%s reviento (%s: %s)"
                % (self.path, type(exc).__name__, exc),
                accion="revisar cognia/clases/servidor_vivo.py")
        try:
            return self._error("%s: %s" % (type(exc).__name__, exc), 500)
        except Exception:
            self.close_connection = True
            return None

    # -- endpoints ---------------------------------------------------------
    def _servir_pagina(self):
        """`GET /`. Si la pagina inyectada revienta, se sirve el placeholder.

        Es deliberado: el transporte tiene que seguir en pie y DECIR que la
        pagina fallo, en vez de devolver un 500 en el que no se distingue "no
        hay cuaderno" de "el cuaderno esta roto".
        """
        token = str(getattr(self.server, "token", ""))
        t = urllib.parse.quote(token)
        base = "http://127.0.0.1:%d" % self._puerto()
        # EL IDENTIFICADOR DE ESTA CARGA, incrustado en las DOS urls que la
        # pagina usa tal cual. Es lo que permite no devolverle al autor su
        # propia escritura sin tocar una linea de la pagina: cada pestania
        # hace su propio GET / y se lleva su propio `cli` (una cookie no
        # valdria: dos pestanias del mismo navegador la comparten). Ver "EL
        # ECO" en la cabecera del modulo.
        cid = secrets.token_urlsafe(8)
        cola = "&%s=%s" % (QUERY_CLIENTE, urllib.parse.quote(cid))
        ctx = {"base": base, "token": token, "puerto": self._puerto(),
               "eventos": "/eventos?t=" + t + cola,
               "estado": "/estado?t=" + t,
               "accion": RUTA_ACCION + "?t=" + t + cola,
               "cliente": cid,
               # La query de ESTA peticion, para que la pagina pueda abrir la
               # materia que pide la URL (`?materia=...`): sin esto,
               # `vista_viva.render` no tiene de donde sacarla y abre siempre
               # la primera.
               "query": self._query(),
               "adj": "/adj"}
        render = _PAGINA
        if render is not None:
            try:
                return self._html(str(render(ctx)))
            except Exception as exc:
                self.server.aviso = (
                    "la pagina inyectada fallo (%s: %s): se sirve el "
                    "placeholder" % (type(exc).__name__, exc))
                _avisar("clases.servidor_vivo.pagina", self.server.aviso,
                        accion="revisar el render pasado a fijar_pagina()")
        return self._html(_pagina_placeholder(ctx))

    def _servir_estado(self):
        """`GET /estado`. El estado de la jornada + el del transporte.

        `jornada` se importa PEREZOSAMENTE y dentro de un try: arrastra
        captura y transcripcion, y este servidor tiene que poder servir la
        pagina y los adjuntos de una jornada vieja en una maquina donde
        soundcard o faster-whisper no esten. Si no se puede, se dice.

        Del bloque `servidor` se quitan token y url: un /estado acaba pegado
        en un reporte de fallo o en una captura de pantalla, y el token es lo
        unico que no puede salir de la maquina.
        """
        try:
            from cognia.clases import jornada as _j
            datos = dict(_j.estado())
            datos["ok"] = True
        except Exception as exc:
            datos = {"ok": False,
                     "aviso": "no se pudo leer el estado de la jornada "
                              "(%s: %s)" % (type(exc).__name__, exc)}
        srv = estado()
        srv.pop("token", None)
        srv.pop("url", None)
        datos["servidor"] = srv
        return self._json(datos)

    def _servir_adjunto(self, ruta: str):
        """`GET /adj/<jornada>/<nombre>`.

        LOS TRAMOS SE PARTEN ANTES DE DECODIFICAR. Es la mitad del trabajo:
        decodificando primero, un `..%2f..%2fx` se convierte en `../../x` y
        pasa a ser TRES tramos; partiendo primero es UN tramo que `_seguro`
        aplasta a un nombre de fichero. Por eso se exige exactamente
        `["", "adj", jornada, nombre]`: un `/adj/a/b/c` no es una ruta con
        subcarpeta, es alguien probando.

        Lo que la vista no sabe embeber se sirve como `octet-stream` y como
        DESCARGA: un .html o un .svg metido a mano en `adjuntos/` y servido
        con su MIME correria con el origen de este servidor, que es el origen
        que tiene el token.
        """
        partes = ruta.split("/")
        if len(partes) != 4 or partes[0] or partes[1] != "adj":
            return self._error("un adjunto se pide como /adj/<jornada>/"
                               "<nombre>", 404)
        jornada = urllib.parse.unquote(partes[2])
        nombre = urllib.parse.unquote(partes[3])
        try:
            fichero = _ruta_adjunto(jornada, nombre)
        except ValueError as exc:
            return self._error(exc, 403)
        if not fichero.is_file():
            return self._error("no hay adjunto %r en la jornada %r"
                               % (nombre, jornada), 404)
        extension = fichero.suffix.lower()
        mime = _mimes_servibles().get(extension)
        extra = None
        if not mime:
            mime = "application/octet-stream"
            extra = {"Content-Disposition":
                     "attachment; filename=\"%s\"" % fichero.name}
        try:
            tam = fichero.stat().st_size
        except OSError as exc:
            return self._error("no se pudo leer el adjunto: %s" % exc, 404)
        self._cabeceras(mime, 200, tam, extra)
        try:
            with fichero.open("rb") as fh:
                while True:
                    trozo = fh.read(_TROZO_ADJUNTO)
                    if not trozo:
                        break
                    self.wfile.write(trozo)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError,
                OSError):
            # El navegador cancelo la imagen (pestania cerrada, scroll). No es
            # un fallo del servidor y no hay a quien responderle: la cabecera
            # ya salio.
            self.close_connection = True
        return None

    def _eventos(self):
        """`GET /eventos`: el SSE. Este hilo vive hasta que el cliente se va.

        Se escribe SIN Content-Length y con `Connection: close`: el cuerpo
        termina cuando el socket se cierra, que es lo que corresponde a un
        flujo infinito.

        `X-Accel-Buffering: no` es para el dia que esto pase por un proxy
        (nginx, un tunel de Tailscale): sin esa cabecera el proxy acumula el
        flujo y el cuaderno "en vivo" llega a rafagas de un minuto.

        El `finally` desuscribe SIEMPRE. Sin eso, cada pestania cerrada dejaria
        una cola creciendo hasta el tope y un `_matar` inutil por evento.
        """
        srv = self.server
        self._cabeceras("text/event-stream; charset=utf-8", 200, None,
                        {"Connection": "close", "X-Accel-Buffering": "no"})
        self.close_connection = True
        # El `cli` de la URL lo puso `_servir_pagina` al pintar ESTA pestania:
        # con el se sabe a quien no hay que devolverle su propia escritura.
        cli = _suscribir(self.connection, self._cliente_id())
        try:
            # `retry` para que el navegador no reconecte cada 3 s si el
            # servidor se cayo; y un comentario de apertura para que `onopen`
            # dispare en el acto en vez de al primer evento real.
            self.wfile.write(("retry: %d\n: conectado al cuaderno\n\n"
                              % int(LATIDO_SSE_S * 1000)).encode("utf-8"))
            while not cli.muerto and not getattr(srv, "parando", False):
                try:
                    trozo = cli.cola.get(timeout=LATIDO_SSE_S)
                except queue.Empty:
                    # Ni un evento en 15 s: latido. Es un COMENTARIO SSE, no
                    # dispara handlers en la pagina, y es lo que impide que un
                    # intermediario mate la conexion por callada.
                    trozo = ": latido\n\n"
                if trozo is None:
                    break            # el centinela que pone `_matar`
                self.wfile.write(trozo.encode("utf-8"))
                cli.enviados += 1
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError,
                TimeoutError, OSError, ValueError):
            # Cliente que se fue, o socket cerrado desde `_matar` mientras se
            # escribia. Ni es un fallo ni hay a quien contarselo: el motivo,
            # si lo hubo, esta en `cli.motivo` y contado en `estado()`.
            pass
        finally:
            _desuscribir(cli)
        return None

    def log_message(self, *a):  # silencio: la pagina abre un SSE y polea
        pass


# ---------------------------------------------------------------------------
# Handshake: puerto + token donde el widget los encuentra
# ---------------------------------------------------------------------------

def ruta_handshake() -> Path:
    return alm.raiz() / HANDSHAKE


def _publicar_handshake(datos: dict) -> str:
    """Escribe puerto+token de forma ATOMICA en el directorio de clases.

    Atomico (temporal + os.replace) por lo mismo que `almacen.guardar_json`:
    un widget que lo lea justo mientras se escribe tiene que ver el fichero
    viejo entero o el nuevo entero, nunca medio JSON -- y medio JSON aqui es
    un widget que no encuentra el cuaderno y no sabe por que.

    NO se usa `almacen.guardar_json` a proposito: esa funcion EMITE
    "clase.json" para todo lo que cae bajo `raiz()`, asi que el servidor se
    anunciaria a si mismo por su propio SSE como si fuera una escritura del
    cuaderno. El evento mentiria sobre su origen, que es exactamente lo que
    `almacen._bajo_la_raiz` existe para evitar.

    El `chmod 600` es correcto en POSIX y practicamente decorativo en Windows
    (los ACL mandan): el fichero vive en el perfil del duenio y contiene el
    mismo secreto que ya esta en la barra del navegador. Se dice aqui para que
    nadie lo lea como una garantia que no es.
    """
    ruta = ruta_handshake()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(ruta.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(datos, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, ruta)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    try:
        os.chmod(ruta, 0o600)
    except OSError as exc:
        _avisar("clases.servidor_vivo.handshake",
                "no se pudieron restringir los permisos de %s (%s)"
                % (ruta, exc),
                accion="comprobar los permisos de ~/.cognia/clases")
    return str(ruta)


def _borrar_handshake() -> None:
    """Fuera el fichero al parar: un handshake que sobrevive al servidor manda
    al widget contra un puerto muerto, y "no arranca" pasa a parecer "esta
    roto"."""
    try:
        ruta = ruta_handshake()
        if ruta.exists():
            ruta.unlink()
    except OSError as exc:
        _avisar("clases.servidor_vivo.handshake",
                "no se pudo borrar %s (%s): el widget puede intentar "
                "conectarse a un puerto muerto" % (HANDSHAKE, exc),
                accion="borrar a mano ~/.cognia/clases/" + HANDSHAKE)


# ---------------------------------------------------------------------------
# Ciclo de vida
# ---------------------------------------------------------------------------

def crear_server(host: str = "127.0.0.1", puerto: int = 0
                 ) -> ThreadingHTTPServer:
    """Crea (sin arrancar el bucle) el servidor del cuaderno en vivo.

    Genera el token de un solo arranque y deja `daemon_threads=True`: si un
    handler se cuelga, no impide el apagado del proceso.

    `puerto=0` -> lo elige el sistema. En este equipo 8080, 8765, 8766, 8777 y
    8899 estan ocupados (y `tailscaled` se queda el 8080 en sus interfaces),
    asi que un puerto fijo seria un choque, no una comodidad; el real se lee
    en `srv.server_address[1]` y se publica en el handshake.

    El bind fuera de 127.0.0.1 se rechaza AQUI y no detras de un flag: las
    notas de clase del duenio no se sirven a la red de casa por descuido de
    quien llame.
    """
    if str(host) not in HOSTS_PERMITIDOS:
        raise ValueError("el cuaderno en vivo solo escucha en %s: '%s' no vale"
                         % (", ".join(HOSTS_PERMITIDOS), host))
    srv = ThreadingHTTPServer((str(host), int(puerto)), _Handler)
    srv.daemon_threads = True
    srv.token = secrets.token_urlsafe(24)
    srv.ultimo = time.time()
    srv.peticiones = 0
    srv.parando = False
    srv.aviso = ""
    # `hilo` lo pone `arrancar()`; queda declarado aqui porque `_apagar` lo
    # consulta para no pedir un `shutdown()` que bloquearia para siempre sobre
    # un bucle que nunca arranco.
    srv.hilo = None
    # El vigia ESPERA sobre este Event en vez de dormir: asi `parar()` no
    # tiene que aguantar los 20 s de su siesta para dejar el proceso limpio.
    srv.evento_parada = threading.Event()
    srv.contador_lock = threading.Lock()
    return srv


def _bucle_corriendo(srv) -> bool:
    """Si `serve_forever()` corre de verdad sobre `srv`.

    Decide si se puede llamar a `shutdown()`: sobre un servidor cuyo bucle
    nunca arranco, `shutdown()` espera un `Event` que solo pone el `finally`
    de `serve_forever()`, o sea PARA SIEMPRE. Quien levante el bucle por su
    cuenta no deja hilo: ahi se asume que si, y de eso se encarga el tope.
    """
    hilo = getattr(srv, "hilo", None)
    if hilo is None:
        return True
    try:
        return bool(hilo.is_alive())
    except Exception:
        return True


def _shutdown_mudo(srv) -> None:
    try:
        srv.shutdown()
    except Exception:
        pass


def _apagar(srv, timeout_s: float = TOPE_APAGADO_S) -> None:
    """`shutdown()` (si procede) + `server_close()`, sin ruido ni excepciones.

    Dos defensas por el mismo danio -- esto corre tambien dentro del `atexit`,
    donde un bloqueo cuelga el proceso y ni Ctrl-C sirve:
      1. `shutdown()` SOLO si el bucle arranco (ver `_bucle_corriendo`).
      2. Y aun asi, en un hilo aparte con tope: si un handler tiene atascado
         el bucle, se cierra el socket igual en vez de esperar sin fin.
    `server_close()` va siempre: es lo que libera el puerto.
    """
    if srv is None:
        return
    srv.parando = True
    evento = getattr(srv, "evento_parada", None)
    if evento is not None:
        evento.set()              # despierta al vigia en el acto
    if _bucle_corriendo(srv):
        apagador = threading.Thread(target=_shutdown_mudo, args=(srv,),
                                    name="cognia-clase-apaga", daemon=True)
        try:
            apagador.start()
        except BaseException:
            # Sin hilos disponibles no se arriesga un shutdown() bloqueante:
            # se cierra el socket y el bucle muere solo al fallar el accept.
            apagador = None
        if apagador is not None:
            apagador.join(max(0.0, float(timeout_s)))
    try:
        srv.server_close()
    except Exception:
        pass


def _vigilante(srv, *, latido_s=None, ocio_s=None) -> None:
    """Apaga el servidor tras INACTIVIDAD_MIN sin nadie mirando.

    UN SSE ABIERTO CUENTA COMO ALGUIEN MIRANDO. Es la diferencia con el vigia
    del editor de flujos y no es un detalle: un espectador que lleva una hora
    viendo la clase no hace peticiones nuevas -- su conexion es una sola, de
    hace una hora -- asi que un vigia que solo mire `ultimo` le cerraria la
    pagina en la cara justo cuando esta funcionando.

    Solo apaga si SIGUE siendo el servidor del singleton: si entre medias se
    levanto otro, de este ya se ocupo quien lo reemplazo.

    `latido_s` y `ocio_s` EXISTEN PARA QUE ESTO SE PUEDA PROBAR. Los valores
    de produccion son 20 s de latido y VEINTE MINUTOS de ocio, y el ocio se
    configura en MINUTOS: sin estos dos parametros el test mas barato posible
    de "se apaga solo" costaria 60 s de suite, o sea que nadie lo escribe y el
    vigia se queda sin una sola linea que lo ejecute (que es exactamente como
    estaba). Con ellos se prueba en milisegundos el MISMO codigo que corre en
    la clase del duenio. En `None` -- lo que pasa `arrancar()` -- se leen los
    globales del modulo EN CADA VUELTA, para que ajustarlos en caliente valga
    para el vigia que ya esta girando.
    """
    while True:
        latido = float(LATIDO_VIGIA_S) if latido_s is None else float(latido_s)
        if srv.evento_parada.wait(latido):
            return                              # nos estan apagando
        if getattr(srv, "parando", False):
            return
        limite = (float(INACTIVIDAD_MIN) * 60.0 if ocio_s is None
                  else float(ocio_s))
        if limite <= 0:
            continue                            # apagado desactivado
        if _n_clientes() > 0:
            srv.ultimo = time.time()
            continue
        if time.time() - float(getattr(srv, "ultimo", 0.0)) < limite:
            continue
        with _LOCK:
            propio = (_SERVER is srv)
        if not propio:
            return
        # El texto de PRODUCCION no cambia ("20 min"): el duenio lee minutos.
        # Solo el vigia parametrizado (tests) dice segundos, porque decir
        # "0 min" seria mentir sobre lo que acaba de pasar.
        cuanto = ("%d min" % INACTIVIDAD_MIN if ocio_s is None
                  else "%.3g s" % limite)
        _avisar("clases.servidor_vivo.ocio",
                "el cuaderno en vivo se apago solo tras %s sin nadie "
                "mirando" % cuanto,
                accion="volver a abrirlo desde el REPL cuando haga falta")
        parar()
        return


def _escuchando(puerto: int, timeout_s=None) -> bool:
    """True cuando el socket acepta conexiones. No espera al primer GET.

    `crear_server` ya hace bind+listen, asi que en la practica vuelve a la
    primera vuelta; el bucle esta para que `arrancar()` no mienta si algun dia
    el arranque deja de ser sincrono.
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


def arrancar(*, abrir_navegador: bool = False, timeout_s=None) -> dict:
    """Levanta el cuaderno en vivo y devuelve al REPL EN EL ACTO.

    Nunca `serve_forever()` en el hilo de quien llama: eso colgaria el REPL
    mientras el duenio graba una clase. Un unico servidor por proceso: llamar
    dos veces devuelve el mismo (con `nuevo: False`).

    `abrir_navegador` es False por defecto -- al reves que el editor de flujos
    -- porque a esto lo llama el widget del cuaderno, que ya tiene su propia
    forma de ensenniar la pagina; quien quiera pestania la pide.

    Devuelve {"url", "base", "puerto", "token", "nuevo", "handshake"}.
    `timeout_s` acota la espera a que el socket escuche, no la vida del
    servidor.
    """
    global _SERVER
    with _LOCK:
        srv = _SERVER
        if not _vivo(srv):
            srv = crear_server()
            hilo = threading.Thread(target=srv.serve_forever,
                                    name="cognia-clase-viva", daemon=True)
            srv.hilo = hilo
            try:
                hilo.start()
            except BaseException:
                # EL SINGLETON NO SE PUBLICA HASTA AQUI. Si `start()` lanza
                # (`RuntimeError: can't start new thread`), un `_SERVER` ya
                # asignado dejaria un servidor con bind y sin bucle:
                # `estado()` diria `vivo: True` mintiendo -- el socket acepta
                # el handshake TCP -- y el `atexit` colgaria el proceso para
                # siempre dentro de `shutdown()`.
                srv.parando = True
                _SERVER = None
                try:
                    srv.server_close()
                except Exception:
                    pass
                raise
            _SERVER = srv
            _enganchar_bus()
            try:
                threading.Thread(target=_vigilante, args=(srv,),
                                 name="cognia-clase-vigia",
                                 daemon=True).start()
            except BaseException as exc:
                # Sin vigia el cuaderno se sirve igual, asi que no se tira
                # abajo lo que funciona; pero no se calla: `estado()` lo
                # publica en `aviso` y el auto-apagado deja de estar
                # garantizado.
                srv.aviso = ("sin vigilante de ocio (%s: %s): el cuaderno en "
                             "vivo no se apagara solo"
                             % (type(exc).__name__, exc))
                _avisar("clases.servidor_vivo.vigia", srv.aviso,
                        accion="parar el cuaderno a mano al terminar")
            if not _ATEXIT[0]:
                atexit.register(parar)
                _ATEXIT[0] = True
            nuevo = True
        else:
            nuevo = False
        srv.ultimo = time.time()
        token = srv.token
        puerto = int(srv.server_address[1])

    base = "http://127.0.0.1:%d" % puerto
    url = base + "/?t=" + urllib.parse.quote(token)
    _escuchando(puerto, timeout_s)
    handshake = ""
    try:
        handshake = _publicar_handshake({"puerto": puerto, "token": token,
                                         "url": url, "base": base,
                                         "pid": os.getpid(), "ts": time.time()})
    except OSError as exc:
        # El servidor SIRVE igual: lo que se pierde es que el widget lo
        # encuentre solo. Se dice, no se calla, y la URL sigue en el dict que
        # se devuelve.
        _avisar("clases.servidor_vivo.handshake",
                "no se pudo publicar %s (%s: %s): el widget no sabra en que "
                "puerto esta" % (HANDSHAKE, type(exc).__name__, exc),
                accion="abrir la URL a mano")
    if abrir_navegador and not os.environ.get("COGNIA_REMOTO"):
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception as exc:
            # Sin display no hay pestania, pero la URL ya va en el dict.
            _avisar("clases.servidor_vivo.navegador",
                    "no se pudo abrir el navegador (%s: %s)"
                    % (type(exc).__name__, exc),
                    accion="abrir a mano " + url)
    return {"url": url, "base": base, "puerto": puerto, "token": token,
            "nuevo": nuevo, "handshake": handshake}


def parar() -> None:
    """Cierra de verdad: bus, clientes, handshake y socket. Idempotente.

    EL ORDEN IMPORTA:
      1. desenganchar el bus, para que no entre un evento a mitad de apagado;
      2. matar a los clientes SSE -- cada uno tiene un hilo BLOQUEADO en
         `cola.get(timeout=15 s)` o escribiendo, y sin el centinela y el
         `shutdown()` del socket ese hilo seguiria vivo hasta 15 s despues de
         que `parar()` haya devuelto, que es justo el "hilo colgado" que este
         contrato prohibe;
      3. borrar el handshake, para no mandar al widget a un puerto muerto;
      4. `shutdown()` + `server_close()` (ver `_apagar`).

    La llaman el `atexit` registrado en el primer `arrancar()` y el vigia.
    """
    global _SERVER
    with _LOCK:
        srv = _SERVER
        _SERVER = None
    _soltar_bus()
    _cerrar_clientes("el cuaderno en vivo se esta apagando")
    _borrar_handshake()
    _apagar(srv)


def estado() -> dict:
    """Que hay levantado ahora mismo, sin levantar nada.

    Es la puerta de diagnostico del modulo (CLAUDE.md: un subsistema que se
    calla y uno que no esta cableado no pueden verse igual desde fuera). Por
    eso salen `clientes`, `enviados` y `desconectados_lentos`: con el cuaderno
    quieto, esos tres numeros distinguen "no hay eventos porque nadie graba",
    "hay eventos pero nadie mira" y "habia alguien mirando y se le echo".
    """
    with _LOCK:
        srv = _SERVER
    comun = {"clientes": _n_clientes(), "enviados": int(_ENVIADOS[0]),
             "desconectados_lentos": int(_LENTOS[0]),
             # Ecos NO mandados al que los provoco, y escrituras aceptadas.
             # Los dos numeros juntos son los que distinguen "la pagina no
             # guarda" de "guarda y no repinta": sin ellos, un eco suprimido
             # de mas se veria igual que un SSE muerto.
             "omitidos_autor": int(_OMITIDOS[0]),
             "escrituras": int(_ESCRITURAS[0]),
             "inactividad_min": INACTIVIDAD_MIN,
             "tope_cola": TOPE_COLA,
             "eventos": list(EVENTOS),
             "escritura": {"ruta": RUTA_ACCION,
                           "tope_cuerpo": int(TOPE_CUERPO),
                           "manejador_inyectado": _ACCIONES is not None,
                           "acciones": sorted(EXIGENCIAS)},
             "pagina_inyectada": _PAGINA is not None,
             "handshake": str(ruta_handshake()),
             "ultimo_error": dict(_ULTIMO_ERROR)}
    if not _vivo(srv):
        comun.update({"vivo": False, "puerto": 0, "base": "", "url": "",
                      "token": "", "peticiones": 0, "ocioso_s": 0,
                      "aviso": ""})
        return comun
    puerto = int(srv.server_address[1])
    base = "http://127.0.0.1:%d" % puerto
    comun.update({
        "vivo": True, "puerto": puerto, "base": base,
        "url": base + "/?t=" + urllib.parse.quote(srv.token),
        "token": srv.token,
        "peticiones": int(getattr(srv, "peticiones", 0)),
        "ocioso_s": int(time.time()
                        - float(getattr(srv, "ultimo", time.time()))),
        # Vacio salvo que algo se degradara al arrancar (hoy: el vigia que no
        # arranco, o una pagina inyectada que revienta). Un subsistema a
        # medias tiene que verse desde fuera.
        "aviso": str(getattr(srv, "aviso", "") or "")})
    return comun
