# -*- coding: utf-8 -*-
"""
cognia/clases/vista_viva.py
===========================
LA PAGINA QUE EL DUENIO MIRA MIENTRAS LE DAN CLASE: la IA escribe el documento
de la materia en vivo y el duenio corrige encima, sin que nada de lo que este
tecleando se pierda.

QUE ES. El pintor de `documento.py` para el transporte de `servidor_vivo.py`.
Se cablea con `servidor_vivo.fijar_pagina(vista_viva.render)` y desde ese
momento `GET /` sirve esto. Aqui NO hay modelo (el modelo es documento.py) ni
transporte (el transporte es servidor_vivo.py): hay una pagina y el manejador
de sus acciones.

POR QUE UN EDITOR DE BLOQUES Y NO UN contenteditable GIGANTE
-----------------------------------------------------------
Decision tomada, no negociable. Un contenteditable con el documento entero
obliga a LEER HTML del navegador para persistirlo -- `innerHTML` de vuelta a
Python -- y eso reintroduce por la puerta de atras justo lo que esta casa
saco a proposito de sus paginas. Ademas el modelo guarda MARKDOWN CRUDO
(`Bloque.texto`), que es lo que el duenio reconoce y lo que `documento.buscar`
mira: convertirlo a HTML y volver seria perder informacion en cada vuelta.
Asi que el bloque enfocado se edita en un `<textarea>` de markdown y los
demas se pintan renderizados.

LA TRAMPA QUE ESTA PAGINA ESQUIVA (medida en este mismo repo)
-------------------------------------------------------------
`cognia/oficina/server.py:121` reconstruye su panel cada 2 s: le BORRA al
usuario lo que esta tecleando y le quita el foco. Esta pagina recibe eventos
constantemente (cada linea de transcripcion y cada operacion del documento),
o sea que tiene el mismo veneno servido en vena. La regla, que es la unica
que hay que verificar al leer el JS:

    EL NODO DEL BLOQUE QUE EL DUENIO ESTA EDITANDO NO SE RECONSTRUYE, NO SE
    RELLENA Y NO SE MUEVE. NUNCA. HAGA LO QUE HAGA EL EVENTO.

Y su gemela, que costo un fallo de perdida de trabajo (arreglada 2026-08-31):

    HAY UN EDITOR ABIERTO COMO MUCHO, Y EL SIGUIENTE NO SE ABRE HASTA QUE EL
    ANTERIOR HAYA CERRADO DE VERDAD.

Cerrar guardando es ASINCRONO (sale una peticion), asi que abrir sin esperar
dejaba DOS textareas vivos compartiendo un solo par de variables
(`S.editando` / `S.area`): el guardado que volvia tarde desconectaba el editor
recien abierto y el boton "reintentar" del banner mandaba el texto de un
bloque al id del OTRO. Por eso `cerrarEditor` devuelve una promesa, `abrirEditor`
se encadena detras, y cada guardado va atado a SU id y SU textarea en vez de
leer el estado global.

Lo primero se implementa reconciliando por id (`S.nodos`) en vez de vaciar el
contenedor: cada bloque tiene SU nodo, que se rellena solo si su firma
cambio, y el nodo en edicion se salta entero. Como el nodo no se recrea, el
`<textarea>` conserva por construccion su `selectionStart`/`selectionEnd`, su
scroll y el foco -- no hay que "restaurar el cursor", que es el apanio que
siempre acaba fallando en el caso raro. Lo que la IA quiera hacer sobre ese
bloque se ENCOLA y se anuncia con una marca en la interfaz (`.cola`); no se
pisa.

LO QUE TAMPOCO SE PIERDE EN UN REPINTADO
----------------------------------------
El cursor no es lo unico que el duenio tiene puesto, asi que sobreviven a
cualquier evento: la SELECCION (repintar el bloque que tiene senialado se la
borra de las manos, asi que ese repintado se APLAZA hasta que la suelte -- y
entonces entra, que aplazar no puede volverse quedarse viejo) y el SCROLL (un
bloque que entra por encima le sube el texto a media frase: se ancla un nodo
de referencia antes de tocar el DOM y se corrige `main.scrollTop` despues).
Y al irse la pestania se apaga todo (`pagehide`): un EventSource abierto deja
un hilo del servidor esperando con su cola creciendo. Volver del bfcache
(`pageshow` con `persisted`) lo vuelve a encender, porque una pagina restaurada
con los temporizadores muertos es otra vez la que parece viva y esta muerta.

EL MARKDOWN SE VE PINTADO, Y AUN ASI NO HAY HTML CRUDO
------------------------------------------------------
El bloque guarda markdown CRUDO, asi que pintarlo con textContent le ensenia
al duenio sus propias marcas ("La **segunda ley de Newton** relaciona..."),
que es lo primero que se lee del documento. Negrita, cursiva, codigo y enlace
se pintan CONSTRUYENDO NODOS (createElement + textContent, funcion `marcas`
del JS): la prohibicion de asignar marcado a un nodo no se levanta ni para
esto -- es justo lo que hace que un apunte con una etiqueta escrita dentro se
lea como texto. Los enlaces pasan por la MISMA validacion de URL que ya tenia
la pagina, y lo que no case (un asterisco sin cerrar, un destino que no es
web) se queda literal en pantalla: comerse texto del duenio para disimular una
marca a medias seria peor que ensenar el markdown.

LO QUE LA PAGINA HACE CON LOS PNG EN TEMA OSCURO
------------------------------------------------
Las formulas y las graficas las dibuja `mates.py` con matplotlib: TINTA OSCURA
SOBRE PAPEL BLANCO, y eso en tema oscuro es un rectangulo blanco de 775x537
deslumbrando. El arreglo es de esta pagina (que es quien sabe que tema hay):
se invierte el PNG con un filtro de CSS, solo en los bloques de formula y
grafica -- una foto invertida seria un negativo -- y se apaga al imprimir,
porque el papel es blanco tenga el tema que tenga.

EL BANNER TIENE DUENO
---------------------
Hay UN banner y varias cosas que contar. La de "no se pudo guardar" lleva
DENTRO el boton que recupera el texto del duenio, asi que pesa mas que las
demas (`PESO_BANNER`) y una caida del SSE ni la tapa ni la borra; el estado de
la conexion se sigue viendo en la barra de directo, que es donde no estorba.

EDITAR FIJA, Y SE VE
--------------------
`documento.editar` es la puerta del DUENIO: deja el bloque `fijado=True` y
`origen=duenio`, y a partir de ahi la regla de oro del modelo impide que la
IA lo reescriba, lo mueva o lo borre. Esa es la promesa central del producto,
asi que la pagina la ENSENIA (el candado de `.fijado`) en vez de dejarla como
una propiedad invisible del JSON. Por eso las acciones de escritura de aqui
entran por la puerta del duenio y NUNCA por `escribir_ia`.

TIEMPO REAL HONESTO
-------------------
La latencia minima real no la pone esta pagina: son los 30 s del trozo de
audio (`captura.SEGUNDOS_TROZO`) MAS lo que tarde Whisper. Una pagina que
solo latiera un punto verde estaria mintiendo, asi que la barra dice siempre
"el ultimo trozo cerro hace N s" -- el reloj sale del `mtime` de
`transcripcion.jsonl` al abrir y de los eventos SSE despues. Y si el
`EventSource` cae: banner visible y reintento exponencial de 2 s a 30 s.
Nunca una pagina que parece viva y esta muerta.

DE DONDE SALEN LOS CAMBIOS (y por que no hay polling)
-----------------------------------------------------
`almacen.apendar` emite "clase.entrada" con `ruta` + `registro` DESPUES del
fsync, y el diario del documento es un JSONL apendado con esa misma funcion:
o sea que el evento SSE lleva dentro la operacion entera del diario. La
pagina la aplica sobre su lista local -- es la misma linea que el proceso ya
aplico en disco, no una adivinanza -- y por eso no hace falta ni un GET de
refresco. Si llega una operacion que no sabe aplicar, lo DICE y ofrece
recargar: un documento desincronizado en silencio seria el vacio silencioso
de siempre.

ESCRITURA: EL MANEJADOR VIVE AQUI, LA PUERTA LA PONE EL TRANSPORTE
------------------------------------------------------------------
`servidor_vivo.py` es hoy de SOLO LECTURA (su `do_POST` responde 404 con el
motivo escrito). Este modulo trae `aplicar_accion(peticion) -> dict`, que es
el manejador completo y probado de todo lo que la pagina sabe pedir; cuando
el transporte abra su puerta de escritura, cablearla es pasarle esta funcion
y darle a la pagina la ruta en `ctx["accion"]`. Mientras tanto la pagina NO
finge: el primer intento de guardar que falle levanta el banner de
"solo lectura", explica por que, y **deja el texto del duenio en su
textarea** -- perder lo tecleado seria exactamente el fallo que esta pagina
existe para no cometer.

REGLAS DE LA CASA QUE ESTE FICHERO CUMPLE (las vigilan los tests)
-----------------------------------------------------------------
  - cero CDN: ni "http://" ni "https://" ni `<link` ni `<script src`;
  - cero innerHTML: todo por `<template>` clonados + textContent/setAttribute;
  - el bloque `<script>` es ASCII puro (REGLAS_HTML_TEMPLATE_PYTHON.md, 2);
  - el JSON embebido va con TODOS los "<" a \\u003c y con U+2028/U+2029
    escapados (WHATWG 13.2.5.15 y el lexer de JS: los dos dejan la pagina
    MUDA, que es un fallo sin sintoma);
  - los placeholders se sustituyen en UNA sola pasada con re.sub, para que un
    titulo que contenga "__DATOS__" no se coma el JSON;
  - ni un acento grave en el JS (plantillas de cadena) ni un caracter no-ASCII.

El cerebrito de `assets/cerebro.svg` va INLINE: un SVG dentro de text/html no
necesita el xmlns, asi que se le quita (y se le quitan los comentarios, que
si llevan una URL de ejemplo) antes de pegarlo. Si tras limpiarlo quedara una
cadena de red, no se pinta: la regla de cero-CDN manda sobre el adorno.

API publica:
    render(ctx) -> str                  el gancho de servidor_vivo.fijar_pagina
    render_html(datos, ctx=None, titulo=...) -> str
    construir(materia=None, ahora=None) -> dict
    aplicar_accion(peticion) -> dict     el manejador de la puerta de escritura
    ACCIONES                             punto de extension (dict de acciones)
    estado() -> dict                     puerta de diagnostico
    export(path=None, ...) -> Path       la pagina a disco (para mirarla)
"""

from __future__ import annotations

import base64
import html as _html
import json
import logging
import os
import re
import tempfile
import time
from pathlib import Path

from cognia.clases import almacen as alm
from cognia.clases import documento as doc

log = logging.getLogger(__name__)

__all__ = ["render", "render_html", "construir", "aplicar_accion", "estado",
           "export", "ACCIONES", "TIPOS_VISIBLES", "TOPE_IMAGEN_PEGADA",
           "RUTA_ACCION"]

# La ruta de la puerta de escritura. Se usa solo si el ctx del transporte no
# trae la suya: el dia que servidor_vivo abra su POST, pasa ctx["accion"] y
# esta constante deja de mandar. Se declara para que la pagina no lleve una
# ruta inventada escondida en el JS.
RUTA_ACCION = "/accion"

# Etiqueta legible de cada tipo de bloque, en el orden en que se ofrecen en el
# selector. El duenio no tiene por que saber que 'deber' es un tipo del modelo.
# ES EL PUNTO DE EXTENSION de la pagina: un tipo nuevo en documento.TIPOS se
# ensenia aniadiendo su fila aqui (y su rama en pintarVista, si necesita algo
# mas que texto).
TIPOS_VISIBLES = (
    (doc.TIPO_TITULO, "Titulo"),
    (doc.TIPO_SUBTITULO, "Subtitulo"),
    (doc.TIPO_PARRAFO, "Parrafo"),
    (doc.TIPO_LISTA, "Lista"),
    (doc.TIPO_FORMULA, "Formula"),
    (doc.TIPO_GRAFICA, "Grafica"),
    (doc.TIPO_IMAGEN, "Imagen"),
    (doc.TIPO_TABLA, "Tabla"),
    (doc.TIPO_CITA, "Cita"),
    (doc.TIPO_DEBER, "Deber"),
    (doc.TIPO_DUDA, "Duda"),
    (doc.TIPO_EXAMEN, "Entra en el examen"),
)

# Tope de la imagen que llega PEGADA o subida desde la pagina, en bytes ya
# decodificados. 12 MB: una captura de pantalla 4K en PNG ronda los 8 y una
# foto de movil en JPEG no llega a 6, asi que deja pasar el caso real y corta
# el pegado accidental de un video o de un PDF. NO ES UN NUMERO MEDIDO: es un
# tope de sensatez, y el motivo de que exista es que el cuerpo entra en RAM
# entero antes de tocar el disco.
TOPE_IMAGEN_PEGADA = 12 * 1024 * 1024

# Segundos de audio que se juntan antes de transcribir. NO se copia el numero:
# se lee de captura.py si se puede (ver `_segundos_trozo`), porque este dato
# es una PROMESA que la pagina le hace al duenio sobre cuanto tarda en verse
# lo que se acaba de decir, y una copia que se desactualice convierte la
# promesa en mentira.
SEGUNDOS_TROZO_POR_DEFECTO = 30.0

# Cuantos resultados devuelve la busqueda de imagenes. Ocho caben en el panel
# sin scroll y es lo que ya usa cognia/busqueda_imagenes.py por defecto.
N_IMAGENES = 8

# Prefijos de los adjuntos que fabrica esta pagina. Van separados por origen
# para que en `adjuntos/` se vea de un vistazo que puso cada camino.
PREFIJO_FORMULA = "formula"
PREFIJO_GRAFICA = "grafica"
PREFIJO_PEGADA = "pegada"
PREFIJO_WEB = "img"


# ── Degradacion visible ──────────────────────────────────────────────────────

_ultimo_fallo: dict = {}


def ultimo_fallo() -> dict:
    """Lo ultimo que se degrado, o {}. Lo lee `estado()`.

    Mismo motivo que en documento.py: "no lo cablearon" y "se rompio" no
    pueden verse igual desde fuera, y esta pagina tiene cuatro subsistemas
    opcionales colgando (matplotlib para las formulas, sympy para las
    graficas, la red para las imagenes, el transporte para escribir).
    """
    return dict(_ultimo_fallo)


def _degradar(donde: str, motivo: str, accion: str = "") -> None:
    """Avisa por el canal de la casa y guarda el ultimo fallo. Nunca mudo."""
    _ultimo_fallo.clear()
    _ultimo_fallo.update({"donde": donde, "motivo": motivo, "t": time.time()})
    log.warning("clases.vista_viva: %s -- %s", donde, motivo)
    try:
        from cognia.ux import events as _ux
        _ux.emitir(_ux.Degradado(donde=donde, motivo=motivo,
                                 accion_sugerida=accion))
    except Exception as exc:
        # El canal de avisos es justo lo que se acaba de romper: queda en el
        # log y se sigue. Nunca un except mudo.
        log.warning("clases.vista_viva: tampoco pude avisar por ux (%s)", exc)


# ── Datos para la pagina ─────────────────────────────────────────────────────

def _segundos_trozo() -> float:
    """Los segundos de audio que se juntan antes de transcribir.

    Se lee de `captura.SEGUNDOS_TROZO` con import perezoso y dentro de un try:
    captura arrastra `soundcard`, que no esta en todas las maquinas, y esta
    pagina tiene que abrirse igual en un ordenador donde no se pueda grabar
    (mirar los apuntes de ayer es un caso de uso entero).
    """
    try:
        from cognia.clases import captura
        return float(captura.SEGUNDOS_TROZO)
    except Exception as exc:
        log.debug("clases.vista_viva: sin captura.SEGUNDOS_TROZO (%s)", exc)
        return SEGUNDOS_TROZO_POR_DEFECTO


def _sello(ahora=None) -> str:
    """La fecha de generacion del pie, con el instante INYECTABLE.

    Mismo patron y mismo motivo que `vista._sello`: sin esto la pagina no es
    una funcion de sus datos y ningun test puede fijarla entera.
    """
    if ahora is None:
        epoch = time.time()
    elif hasattr(ahora, "timestamp"):
        epoch = float(ahora.timestamp())
    else:
        epoch = float(ahora)
    return time.strftime("%d/%m/%Y %H:%M", time.localtime(epoch))


def _jornadas() -> list:
    try:
        return alm.jornadas()
    except Exception as exc:
        _degradar("clases.vista_viva.jornadas",
                  "no pude listar las jornadas (%s: %s)"
                  % (type(exc).__name__, exc),
                  accion="revisar ~/.cognia/clases/jornadas")
        return []


def _jornada_destino(preferida: str = "") -> str:
    """La jornada donde se guardan los adjuntos que fabrica la pagina.

    Orden: la que pida el llamante, la mas reciente del cuaderno, y si no hay
    ninguna, la de HOY (que es donde de verdad pertenece una foto sacada hoy).
    La carpeta la crea `almacen.copiar_adjunto` en la primera escritura; aqui
    solo se decide el nombre.
    """
    preferida = str(preferida or "").strip()
    if preferida:
        return preferida
    js = _jornadas()
    return js[0] if js else time.strftime("%Y-%m-%d")


def _ultimo_trozo() -> float:
    """Epoch en que se cerro el ultimo trozo transcrito, o 0.0.

    Es el `mtime` de `transcripcion.jsonl` de la jornada mas reciente: el
    fichero se escribe con fsync justo al cerrar el trozo, asi que su fecha ES
    el instante que la barra promete. Preferirlo a mirar la ultima linea es
    deliberado -- un stat cuesta microsegundos y no hay que parsear un JSONL
    que puede tener miles de lineas cada vez que alguien abre la pagina.
    """
    js = _jornadas()
    if not js:
        return 0.0
    ruta = alm.dir_jornada(js[0]) / alm.TRANSCRIPCION
    try:
        return float(ruta.stat().st_mtime) if ruta.is_file() else 0.0
    except OSError as exc:
        log.debug("clases.vista_viva: sin mtime de %s (%s)", ruta, exc)
        return 0.0


def _mimes_imagen() -> dict:
    """{extension: mime} de lo que el cuaderno sabe ensenniar.

    Se lee de `vista._MIME_IMAGEN` y no se copia por lo mismo que hace
    `servidor_vivo._mimes_servibles`: si el cuaderno solo sabe pintar seis
    formatos, guardar un septimo deja el fichero en disco y el bloque MUDO.
    """
    try:
        from cognia.clases import vista
        return dict(vista._MIME_IMAGEN)
    except Exception as exc:
        _degradar("clases.vista_viva.mimes",
                  "no pude leer la tabla de MIME de vista.py (%s: %s)"
                  % (type(exc).__name__, exc),
                  accion="revisar cognia/clases/vista.py")
        return {".png": "image/png", ".jpg": "image/jpeg"}


def _buscar_adjunto(nombre: str, jornada: str = "") -> tuple:
    """(jornada, aviso) donde vive un adjunto, buscandolo si hace falta.

    Los bloques de formula, grafica e imagen guardan el NOMBRE del fichero en
    su meta; la jornada va tambien en la meta desde que esta pagina los crea,
    pero un documento escrito antes (o por el volcado de apuntes) puede no
    llevarla. En ese caso se busca de la jornada mas nueva a la mas vieja:
    son unas pocas carpetas y el `.is_file()` es barato. Si no aparece se
    devuelve el motivo, que la pagina pinta en el bloque -- una imagen que
    falta y no se explica es el vacio silencioso de siempre.
    """
    nombre = str(nombre or "").strip()
    if not nombre:
        return "", ""
    candidatas = ([str(jornada)] if jornada else []) + _jornadas()
    vistas = []
    for j in candidatas:
        if not j or j in vistas:
            continue
        vistas.append(j)
        try:
            if alm.ruta_adjunto(j, nombre).is_file():
                return j, ""
        except OSError as exc:
            log.debug("clases.vista_viva: %s/%s ilegible (%s)", j, nombre, exc)
    return "", ("el fichero '%s' no esta en los adjuntos de ninguna jornada"
                % nombre)


def _bloque_a_dict(b) -> dict:
    """Un `Bloque` como lo necesita la pagina: el modelo + donde esta su PNG.

    `texto` viaja CRUDO (es markdown y es lo que el duenio edita) y `busca` es
    el heno en minusculas para el buscador de la propia pagina: calcularlo
    aqui hace que buscar cueste lo mismo con 20 bloques que con 2000.
    """
    meta = dict(b.meta or {})
    fichero = ""
    if b.tipo == doc.TIPO_IMAGEN:
        fichero = str(meta.get("adjunto") or "")
    elif b.tipo in (doc.TIPO_FORMULA, doc.TIPO_GRAFICA):
        fichero = str(meta.get("png") or "")
    jornada, aviso = ("", "")
    if fichero:
        jornada, aviso = _buscar_adjunto(fichero, str(meta.get("jornada") or ""))
    heno = " ".join([b.texto or "", str(meta.get("latex") or ""),
                     str(meta.get("expresion") or ""),
                     str(meta.get("atribucion") or "")])
    return {"id": b.id, "tipo": b.tipo, "texto": b.texto or "",
            "fijado": bool(b.fijado), "origen": b.origen, "t": float(b.t or 0.0),
            "meta": meta, "adjunto": fichero, "jornada": jornada,
            "aviso": aviso, "busca": heno.lower()}


def construir(materia=None, ahora=None) -> dict:
    """El dict que la pagina lleva dentro: el documento de UNA materia.

    Una materia y no todas a proposito: esto es un editor abierto sobre lo que
    se esta dando ahora, no el cuaderno entero (para eso esta `vista.py`).
    Cambiar de materia recarga la pagina con `?materia=`.

    Nunca lanza: si el documento no se puede leer, devuelve la pagina vacia
    DICIENDO por que, que no es lo mismo que devolverla vacia.
    """
    t0 = time.monotonic()
    avisos: list = []
    try:
        materias = doc.documentos()
    except Exception as exc:
        _degradar("clases.vista_viva.documentos",
                  "no pude listar los documentos (%s: %s)"
                  % (type(exc).__name__, exc),
                  accion="revisar ~/.cognia/clases/documentos")
        materias, avisos = [], ["no pude listar los documentos: %s" % exc]

    elegida = str(materia or "").strip()
    if elegida and elegida not in materias:
        # No es un error: puede ser una materia que todavia no tiene documento
        # (se creara con el primer bloque). Se dice para que no parezca que la
        # pagina eligio otra cosa por su cuenta.
        avisos.append("la materia %r todavia no tiene documento: se abrira "
                      "vacio al escribir el primer bloque" % elegida)
    if not elegida:
        elegida = materias[0] if materias else ""

    bloques, fijados = [], 0
    if elegida:
        try:
            documento = doc.abrir(elegida, crear=False)
            bloques = [_bloque_a_dict(b) for b in documento.bloques]
            fijados = sum(1 for b in bloques if b["fijado"])
            avisos += list(documento.avisos)
        except Exception as exc:
            _degradar("clases.vista_viva.abrir",
                      "no pude abrir el documento de %r (%s: %s)"
                      % (elegida, type(exc).__name__, exc),
                      accion="revisar el diario del documento")
            avisos.append("no pude abrir el documento de %r: %s" % (elegida, exc))

    markdown = ""
    if elegida and bloques:
        try:
            markdown = doc.a_markdown(elegida)
        except Exception as exc:
            # El markdown embebido es solo la RED del boton de descargar (el
            # bueno lo pide al servidor): que falle no puede tumbar la pagina.
            avisos.append("no pude preparar el markdown de respaldo: %s" % exc)

    for a in [b["aviso"] for b in bloques if b["aviso"]]:
        avisos.append(a)

    return {
        "materia": elegida,
        "materias": materias,
        "bloques": bloques,
        "n_fijados": fijados,
        "diario": str(doc.ruta_diario(elegida)) if elegida else "",
        "transcripcion": alm.TRANSCRIPCION,
        "ultimo_trozo": _ultimo_trozo(),
        "ahora": time.time(),
        "segundos_trozo": _segundos_trozo(),
        "markdown": markdown,
        "avisos": avisos,
        "generado": _sello(ahora),
        "ms": int((time.monotonic() - t0) * 1000),
    }


# ── La puerta de escritura ───────────────────────────────────────────────────

class _Fallo(Exception):
    """Un error de la peticion que hay que CONTARLE al duenio tal cual.

    Existe para que las acciones puedan cortar con un mensaje escrito para un
    humano sin que cada una tenga que construir su dict de respuesta.
    """


def _texto(p: dict, clave: str, obligatorio: bool = False) -> str:
    v = str(p.get(clave) or "").strip()
    if obligatorio and not v:
        raise _Fallo("falta %r en la peticion" % clave)
    return v


def _materia_de(p: dict) -> str:
    return _texto(p, "materia", True)


def _acc_aniadir(p: dict) -> dict:
    """Un bloque nuevo, escrito por el DUENIO (nace fijado)."""
    materia = _materia_de(p)
    tipo = _texto(p, "tipo") or doc.TIPO_PARRAFO
    b = doc.aniadir(materia, tipo, p.get("texto") or "",
                    meta=p.get("meta"), tras=p.get("tras") or None,
                    al_principio=bool(p.get("al_principio")))
    return {"id": b.id}


def _acc_editar(p: dict) -> dict:
    """La correccion del duenio. FIJA el bloque: es la promesa del producto.

    Entra por `documento.editar` (puerta del DUENIO) y no por `escribir_ia`
    justo por eso -- con la puerta de la IA el bloque quedaria suelto y el
    refinado de fondo se comeria la correccion en la siguiente pasada.
    """
    materia = _materia_de(p)
    bid = _texto(p, "id", True)
    b = doc.editar(materia, bid, texto=str(p.get("texto") or ""))
    return {"id": bid, "fijado": bool(b.fijado)}


def _acc_tipo(p: dict) -> dict:
    """Cambia el TIPO de un bloque conservando texto, meta y sitio.

    El modelo no tiene operacion de tipo (`documento.OPS` no la lleva y
    `editar` solo toca texto y meta), asi que se hace con un borrar + aniadir
    en el mismo sitio. EL ID CAMBIA, y se devuelve el nuevo: los ids no se
    reciclan nunca (ver `documento._id_nuevo`), asi que fingir que es el mismo
    bloque seria mentir en la respuesta.
    """
    materia = _materia_de(p)
    bid = _texto(p, "id", True)
    tipo = _texto(p, "tipo", True)
    if tipo not in doc.TIPOS:
        raise _Fallo("tipo %r desconocido; los que hay son: %s"
                     % (tipo, ", ".join(doc.TIPOS)))
    documento = doc.abrir(materia, crear=False)
    i = documento.indice(bid)
    if i < 0:
        raise _Fallo("en el documento de %r no hay ningun bloque %r"
                     % (materia, bid))
    viejo = documento.bloques[i]
    if viejo.tipo == tipo:
        return {"id": bid, "sin_cambio": True}
    anterior = documento.bloques[i - 1].id if i > 0 else ""
    nuevo = doc.aniadir(materia, tipo, viejo.texto, meta=dict(viejo.meta),
                        tras=anterior or None, al_principio=(i == 0))
    doc.borrar(materia, bid)
    return {"id": nuevo.id, "antes": bid}


def _acc_mover(p: dict) -> dict:
    materia = _materia_de(p)
    bid = _texto(p, "id", True)
    doc.mover(materia, bid, tras=p.get("tras") or None,
              al_principio=bool(p.get("al_principio")))
    return {"id": bid}


def _acc_borrar(p: dict) -> dict:
    materia = _materia_de(p)
    bid = _texto(p, "id", True)
    doc.borrar(materia, bid)
    return {"id": bid}


def _acc_fijar(p: dict) -> dict:
    """Fija o SUELTA un bloque. Soltar solo lo puede pedir el duenio, y esta
    es su unica puerta: es como le devuelve a la IA un bloque que corrigio."""
    materia = _materia_de(p)
    bid = _texto(p, "id", True)
    b = doc.fijar(materia, bid, bool(p.get("valor", True)))
    return {"id": bid, "fijado": bool(b.fijado)}


def _acc_formula(p: dict) -> dict:
    """LaTeX -> PNG con `mates.formula_a_png` + bloque de formula.

    EL LATEX CRUDO SE QUEDA EN EL BLOQUE (texto y meta['latex']): es lo que se
    edita cuando el duenio se equivoco en un subindice y es lo que encuentra
    `documento.buscar`. Un bloque que solo llevara el PNG seria una imagen
    muerta dentro de unos apuntes que se buscan por texto.
    """
    from cognia.clases import mates
    materia = _materia_de(p)
    latex = _texto(p, "latex", True)
    jornada = _jornada_destino(_texto(p, "jornada"))
    destino = alm.dir_jornada(jornada) / alm.DIR_ADJUNTOS
    n = alm._siguiente_adjunto(destino, PREFIJO_FORMULA)
    ruta = destino / ("%s_%04d.png" % (PREFIJO_FORMULA, n))
    try:
        salida = mates.formula_a_png(latex, ruta)
    except mates.ErrorDeMates as exc:
        raise _Fallo(str(exc)) from exc
    meta = {"latex": latex, "png": ruta.name, "jornada": jornada}
    b = doc.aniadir(materia, doc.TIPO_FORMULA, latex, meta=meta,
                    tras=p.get("tras") or None)
    return {"id": b.id, "png": ruta.name, "jornada": jornada,
            "avisos": list(salida.get("avisos") or [])}


def _acc_grafica(p: dict) -> dict:
    """Una expresion -> PNG con `mates.graficar` + bloque de grafica."""
    from cognia.clases import mates
    materia = _materia_de(p)
    expresion = _texto(p, "expresion", True)
    jornada = _jornada_destino(_texto(p, "jornada"))
    destino = alm.dir_jornada(jornada) / alm.DIR_ADJUNTOS
    n = alm._siguiente_adjunto(destino, PREFIJO_GRAFICA)
    ruta = destino / ("%s_%04d.png" % (PREFIJO_GRAFICA, n))
    parametros = {"var": _texto(p, "var") or "x",
                  "desde": float(p.get("desde", -10.0)),
                  "hasta": float(p.get("hasta", 10.0))}
    try:
        salida = mates.graficar(ruta, expresion=expresion,
                                var=parametros["var"],
                                desde=parametros["desde"],
                                hasta=parametros["hasta"])
    except mates.ErrorDeMates as exc:
        raise _Fallo(str(exc)) from exc
    meta = {"expresion": expresion, "png": ruta.name, "jornada": jornada,
            "parametros": parametros}
    b = doc.aniadir(materia, doc.TIPO_GRAFICA,
                    _texto(p, "texto") or expresion, meta=meta,
                    tras=p.get("tras") or None)
    return {"id": b.id, "png": ruta.name, "jornada": jornada,
            "avisos": list(salida.get("avisos") or [])}


def _extension_de(mime: str) -> str:
    for ext, m in _mimes_imagen().items():
        if m == mime:
            return ext
    return ""


def _acc_imagen(p: dict) -> dict:
    """Una imagen del disco o del portapapeles -> adjunto + bloque.

    Dos entradas y una sola salida: `ruta` (un fichero del ordenador) o
    `datos` (un data: URI, que es lo que da el portapapeles y lo que devuelve
    FileReader al subir). Las dos acaban en `almacen.copiar_adjunto`, que es
    quien numera y sanea el nombre: tener dos formas de nombrar adjuntos
    acabaria con dos convenciones en la misma carpeta.
    """
    materia = _materia_de(p)
    jornada = _jornada_destino(_texto(p, "jornada"))
    ruta = _texto(p, "ruta")
    datos = str(p.get("datos") or "")
    if ruta:
        origen = Path(ruta).expanduser()
        if not origen.is_file():
            raise _Fallo("no encuentro el fichero %s" % origen)
        if origen.suffix.lower() not in _mimes_imagen():
            raise _Fallo("'%s' no es un formato que el cuaderno sepa ensenniar "
                         "(%s)" % (origen.name, ", ".join(sorted(_mimes_imagen()))))
        nombre = alm.copiar_adjunto(jornada, origen, prefijo=PREFIJO_PEGADA)
    elif datos:
        m = re.match(r"^data:([a-z]+/[a-z0-9.+-]+);base64,", datos, re.I)
        if not m:
            raise _Fallo("los datos pegados no son un data: URI en base64")
        mime = m.group(1).lower()
        ext = _extension_de(mime)
        if not ext:
            raise _Fallo("el cuaderno no sabe ensenniar %r; pegar PNG, JPEG, "
                         "GIF, WEBP o BMP" % mime)
        try:
            crudo = base64.b64decode(datos[m.end():], validate=True)
        except (ValueError, TypeError) as exc:
            raise _Fallo("el base64 de la imagen esta roto: %s" % exc) from exc
        if len(crudo) > TOPE_IMAGEN_PEGADA:
            raise _Fallo("la imagen pesa %.1f MB y el tope al pegar son %.0f MB"
                         % (len(crudo) / 1048576.0,
                            TOPE_IMAGEN_PEGADA / 1048576.0))
        fd, tmp = tempfile.mkstemp(suffix=ext)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(crudo)
            nombre = alm.copiar_adjunto(jornada, tmp, prefijo=PREFIJO_PEGADA)
        finally:
            try:
                os.unlink(tmp)
            except OSError as exc:
                # El adjunto YA esta copiado: un temporal que no se borra es
                # basura, no una perdida de datos. Se dice y se sigue.
                log.warning("clases.vista_viva: no pude borrar el temporal %s "
                            "(%s)", tmp, exc)
    else:
        raise _Fallo("una imagen se inserta con 'ruta' (un fichero) o con "
                     "'datos' (un data: URI del portapapeles)")
    meta = {"adjunto": nombre, "jornada": jornada,
            "atribucion": _texto(p, "atribucion")}
    b = doc.aniadir(materia, doc.TIPO_IMAGEN, _texto(p, "texto"), meta=meta,
                    tras=p.get("tras") or None)
    return {"id": b.id, "adjunto": nombre, "jornada": jornada}


def _acc_buscar_imagenes(p: dict) -> dict:
    """Busca imagenes REUTILIZABLES y devuelve solo sus metadatos.

    NO se pintan las miniaturas remotas en la pagina a proposito: cargarlas
    seria hacer que un cuaderno servido en 127.0.0.1 fuera a buscar bytes a
    Wikimedia en cada busqueda, y esta casa tiene la regla de cero descargas
    externas en sus paginas. Se ensenia titulo, autor y licencia; al elegir
    una, el SERVIDOR la baja (`imagen_web`) y entonces si se ve, servida por
    /adj como cualquier otro adjunto.
    """
    from cognia import busqueda_imagenes as bi
    consulta = _texto(p, "consulta", True)
    try:
        resultados, avisos = bi.buscar_con_avisos(
            consulta, int(p.get("n") or N_IMAGENES))
    except bi.ErrorBusquedaImagenes as exc:
        raise _Fallo("no pude buscar imagenes: %s" % exc) from exc
    limpios = [{"titulo": r.get("titulo", ""), "autor": r.get("autor", ""),
                "licencia": r.get("licencia", ""),
                "atribucion": r.get("atribucion", ""),
                "ancho": r.get("ancho", 0), "alto": r.get("alto", 0),
                "url_imagen": r.get("url_imagen", ""),
                "url_pagina": r.get("url_pagina", ""),
                "fuente": r.get("fuente", "")} for r in resultados]
    return {"resultados": limpios, "avisos": list(avisos)}


def _acc_imagen_web(p: dict) -> dict:
    """Baja una imagen encontrada en la busqueda y la mete como bloque.

    La descarga la hace `almacen.descargar_adjunto`, que ya comprueba esquema,
    Content-Type y tamanio (y sigue comprobandolos DESPUES de las
    redirecciones). Aqui no se reimplementa ninguna de esas guardias.
    """
    materia = _materia_de(p)
    url = _texto(p, "url", True)
    jornada = _jornada_destino(_texto(p, "jornada"))
    try:
        nombre = alm.descargar_adjunto(jornada, url, prefijo=PREFIJO_WEB)
    except Exception as exc:
        raise _Fallo("no pude bajar la imagen (%s: %s)"
                     % (type(exc).__name__, exc)) from exc
    meta = {"adjunto": nombre, "jornada": jornada,
            "atribucion": _texto(p, "atribucion")}
    b = doc.aniadir(materia, doc.TIPO_IMAGEN, _texto(p, "texto"), meta=meta,
                    tras=p.get("tras") or None)
    return {"id": b.id, "adjunto": nombre, "jornada": jornada}


def _acc_tabla(p: dict) -> dict:
    """Una tabla vacia de n x m en markdown, lista para rellenar tecleando."""
    materia = _materia_de(p)
    filas = max(1, min(30, int(p.get("filas") or 3)))
    columnas = max(1, min(12, int(p.get("columnas") or 3)))
    cabecera = ["col %d" % (i + 1) for i in range(columnas)]
    lineas = ["| " + " | ".join(cabecera) + " |",
              "|" + "|".join(["---"] * columnas) + "|"]
    for _ in range(filas):
        lineas.append("|" + "|".join(["   "] * columnas) + "|")
    b = doc.aniadir(materia, doc.TIPO_TABLA, "\n".join(lineas),
                    meta={"cabecera": cabecera}, tras=p.get("tras") or None)
    return {"id": b.id}


def _acc_markdown(p: dict) -> dict:
    """El documento entero en markdown, tal como lo escribe `documento`.

    La pagina lo pide para el boton de descargar en vez de fabricarlo en JS:
    con dos generadores de markdown, el fichero que el duenio se lleva y el
    que exporta el CLI acabarian siendo distintos.
    """
    materia = _materia_de(p)
    return {"markdown": doc.a_markdown(materia), "materia": materia}


# PUNTO DE EXTENSION de la puerta de escritura: una accion nueva es una fila
# aqui y su boton en la pagina. No hay if-chain enterrado en ningun sitio.
ACCIONES = {
    "aniadir": _acc_aniadir,
    "editar": _acc_editar,
    "tipo": _acc_tipo,
    "mover": _acc_mover,
    "borrar": _acc_borrar,
    "fijar": _acc_fijar,
    "formula": _acc_formula,
    "grafica": _acc_grafica,
    "imagen": _acc_imagen,
    "buscar_imagenes": _acc_buscar_imagenes,
    "imagen_web": _acc_imagen_web,
    "tabla": _acc_tabla,
    "markdown": _acc_markdown,
}

# Las acciones que CAMBIAN el documento: tras ellas la respuesta lleva la
# lista de bloques al dia, para que la pagina no tenga que pedirla aparte ni
# esperar a que le vuelva su propio evento.
_ACCIONES_QUE_ESCRIBEN = ("aniadir", "editar", "tipo", "mover", "borrar",
                          "fijar", "formula", "grafica", "imagen",
                          "imagen_web", "tabla")


def aplicar_accion(peticion: dict) -> dict:
    """El manejador de la puerta de escritura. NUNCA lanza: siempre responde.

    Devuelve `{"ok": True, ...}` o `{"ok": False, "error": "<para humanos>"}`,
    y en las acciones que escriben aniade `bloques` (el documento al dia) y
    `materia`. Que no lance es parte del contrato: al otro lado hay un handler
    HTTP y una pagina, y un traceback ahi se convierte en un 500 mudo donde el
    duenio no distingue "no se pudo" de "no esta cableado".

    Cada fallo lleva el MOTIVO escrito para leerlo en la pagina, no el nombre
    de una excepcion.
    """
    if not isinstance(peticion, dict):
        return {"ok": False,
                "error": "una accion se pide con un objeto JSON, llego %s"
                         % type(peticion).__name__}
    nombre = str(peticion.get("accion") or "").strip()
    fn = ACCIONES.get(nombre)
    if fn is None:
        return {"ok": False,
                "error": "accion %r desconocida; las que hay son: %s"
                         % (nombre, ", ".join(sorted(ACCIONES)))}
    try:
        fuera = dict(fn(peticion) or {})
    except _Fallo as exc:
        return {"ok": False, "error": str(exc), "accion": nombre}
    except doc.ErrorDocumento as exc:
        return {"ok": False, "error": str(exc), "accion": nombre}
    except ImportError as exc:
        # Un subsistema opcional que no esta (matplotlib, sympy, la busqueda
        # de imagenes). Se distingue del error de uso: el arreglo es instalar
        # algo, no escribir otra cosa.
        _degradar("clases.vista_viva.%s" % nombre,
                  "falta una dependencia para %r: %s" % (nombre, exc),
                  accion="instalar lo que falte en venv312")
        return {"ok": False, "accion": nombre,
                "error": "para %r falta una dependencia: %s" % (nombre, exc)}
    except Exception as exc:
        _degradar("clases.vista_viva.%s" % nombre,
                  "la accion %r reviento (%s: %s)"
                  % (nombre, type(exc).__name__, exc),
                  accion="revisar cognia/clases/vista_viva.py")
        return {"ok": False, "accion": nombre,
                "error": "%s: %s" % (type(exc).__name__, exc)}
    fuera.update({"ok": True, "accion": nombre})
    if nombre in _ACCIONES_QUE_ESCRIBEN:
        materia = str(peticion.get("materia") or "")
        try:
            fuera["bloques"] = [_bloque_a_dict(b)
                                for b in doc.abrir(materia, crear=False).bloques]
            fuera["materia"] = materia
        except Exception as exc:
            # La escritura SI se hizo: no se puede devolver ok=False. Se avisa
            # de que la lista no viaja y la pagina se queda con la suya.
            fuera["aviso"] = ("la operacion se guardo pero no pude releer el "
                              "documento: %s" % exc)
    return fuera


# ── El cerebrito, inline y sin una sola URL ──────────────────────────────────

_COMENTARIO_XML = re.compile(r"<!--.*?-->", re.DOTALL)
_XMLNS = re.compile(r'\s+xmlns(?::\w+)?="[^"]*"')


def _cerebro_inline() -> str:
    """El SVG del cerebrito listo para pegar dentro del HTML.

    Un SVG inline en un documento text/html NO necesita el xmlns (lo dice el
    parser de HTML: el elemento entra ya en el namespace SVG), asi que se
    quita -- y con el, la unica cadena "http" del fichero. Los comentarios se
    van tambien porque llevan otra. Si despues de limpiar quedara cualquier
    resto de una URL, se devuelve cadena vacia: la regla de cero-CDN de esta
    casa vale mas que el adorno, y una pagina sin icono se ve perfectamente.
    """
    ruta = Path(__file__).with_name("assets") / "cerebro.svg"
    try:
        crudo = ruta.read_text(encoding="utf-8")
    except OSError as exc:
        _degradar("clases.vista_viva.cerebro",
                  "no pude leer %s (%s): la cabecera va sin icono" % (ruta, exc),
                  accion="comprobar cognia/clases/assets/cerebro.svg")
        return ""
    limpio = _XMLNS.sub("", _COMENTARIO_XML.sub("", crudo)).strip()
    if "//" in limpio or "http" in limpio.lower():
        _degradar("clases.vista_viva.cerebro",
                  "el SVG del cerebro sigue teniendo una URL despues de "
                  "limpiarlo: se pinta la pagina SIN icono para no romper la "
                  "regla de cero descargas externas",
                  accion="quitar la URL de cognia/clases/assets/cerebro.svg")
        return ""
    return limpio


# ── La pagina ────────────────────────────────────────────────────────────────

_HTML = r"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITULO__</title>
<style>
/* Sobrio y legible para leer horas seguidas: una columna de ancho de lectura,
   fondo de papel y tipografia del sistema. Claro por defecto y oscuro cuando
   el sistema lo pide; el boton manda sobre el sistema y se recuerda. Los
   tokens se REDEFINEN uno a uno, no se invierten. */
:root{
  --fondo:#fbfaf7; --papel:#ffffff; --panel:#f2f1ec; --borde:#dcd9d0;
  --texto:#1f2328; --texto2:#6b6a63; --acento:#0969da; --acento2:#0550ae;
  --marca:#9a6700; --marcafondo:#fff4d6; --ok:#1a7f37; --mal:#cf222e;
  --ia:#8250df; --iafondo:#f5eeff; --sombra:0 1px 3px rgba(31,35,40,.10);
  --png-filtro:none; --png-borde:var(--borde);
}
@media (prefers-color-scheme: dark){
  :root:not([data-tema="claro"]){
    --fondo:#0d1117; --papel:#161b22; --panel:#1c2128; --borde:#30363d;
    --texto:#e6edf3; --texto2:#9198a1; --acento:#58a6ff; --acento2:#79c0ff;
    --marca:#e3b341; --marcafondo:#332a10; --ok:#3fb950; --mal:#f85149;
    --ia:#bc8cff; --iafondo:#241a33; --sombra:0 1px 3px rgba(0,0,0,.45);
    --png-filtro:invert(1) hue-rotate(180deg); --png-borde:#c9d1d9;
  }
}
:root[data-tema="oscuro"]{
  --fondo:#0d1117; --papel:#161b22; --panel:#1c2128; --borde:#30363d;
  --texto:#e6edf3; --texto2:#9198a1; --acento:#58a6ff; --acento2:#79c0ff;
  --marca:#e3b341; --marcafondo:#332a10; --ok:#3fb950; --mal:#f85149;
  --ia:#bc8cff; --iafondo:#241a33; --sombra:0 1px 3px rgba(0,0,0,.45);
  --png-filtro:invert(1) hue-rotate(180deg); --png-borde:#c9d1d9;
}
*{box-sizing:border-box}
html,body{margin:0;height:100%}
body{background:var(--fondo);color:var(--texto);display:flex;flex-direction:column;
  font:15px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
/* NADA DE position:sticky AQUI. El que scrollea es <main>, no el body: la
   cabecera y la barra son hermanas suyas en un flex column y ya se quedan
   fijas por construccion. Un sticky con su top:47px escrito a mano no hacia
   nada hoy y mentia el dia que alguien tocara el layout. El z-index si cuenta
   (se aplica a los hijos de un flex aunque sean static). */
header{display:flex;align-items:center;gap:12px;flex-wrap:wrap;padding:10px 18px;
  background:var(--panel);border-bottom:1px solid var(--borde);z-index:20}
header svg{width:26px;height:26px;flex:0 0 26px;display:block}
h1{margin:0;font-size:15px;font-weight:600;letter-spacing:-.01em}
select,input[type=search],input[type=text],input[type=number]{
  padding:6px 10px;border-radius:6px;border:1px solid var(--borde);
  background:var(--papel);color:var(--texto);font:inherit;font-size:13.5px}
input[type=search]{flex:1;min-width:160px;max-width:380px}
input:focus,select:focus,textarea:focus{outline:2px solid var(--acento);outline-offset:1px}
button{padding:6px 11px;border-radius:6px;border:1px solid var(--borde);
  background:var(--papel);color:var(--texto);font:inherit;font-size:13px;cursor:pointer}
button:hover:not(:disabled){border-color:var(--acento);color:var(--acento)}
button:disabled{opacity:.5;cursor:not-allowed}
button.pri{background:var(--acento);border-color:var(--acento);color:#fff}
button.pri:hover:not(:disabled){background:var(--acento2);color:#fff}
/* -- barra de directo -- */
#directo{display:flex;align-items:center;gap:14px;flex-wrap:wrap;padding:6px 18px;
  background:var(--papel);border-bottom:1px solid var(--borde);font-size:12.5px;
  color:var(--texto2);font-variant-numeric:tabular-nums}
#rec{display:inline-flex;align-items:center;gap:7px;font-weight:600;color:var(--texto)}
#punto{width:9px;height:9px;border-radius:50%;background:var(--texto2);display:block}
#punto.vivo{background:var(--mal);animation:latido 1.6s ease-in-out infinite}
#punto.espera{background:var(--marca)}
@keyframes latido{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.35;transform:scale(.8)}}
#banner{display:flex;align-items:center;gap:12px;flex-wrap:wrap;padding:9px 18px;
  background:var(--marcafondo);border-bottom:1px solid var(--marca);font-size:13px}
/* El display:flex de arriba lleva un ID: le GANA al [hidden]{display:none} de
   la hoja del navegador, asi que el banner apagado se seguia pintando como
   una franja vacia con su borde. Quien pone el display tiene que apagarlo. */
#banner[hidden]{display:none}
#banner.mal{background:var(--mal);color:#fff;border-color:var(--mal)}
#banner.mal button{background:transparent;color:#fff;border-color:#fff}
/* -- herramientas -- */
#barra{display:flex;align-items:center;gap:6px;flex-wrap:wrap;padding:8px 18px;
  background:var(--panel);border-bottom:1px solid var(--borde);z-index:15}
#barra .sep{width:1px;height:20px;background:var(--borde);margin:0 4px}
/* CADA SEPARADOR VIAJA CON LO QUE SEPARA. Sueltos en un contenedor que se
   envuelve, el "|" se quedaba huerfano colgando al final de la fila de
   arriba mientras el grupo que anunciaba bajaba a la siguiente. Metidos en su
   grupo (que no se parte, nowrap), un separador solo puede ir delante de algo. */
#barra .grupo{display:inline-flex;align-items:center;gap:6px;flex-wrap:nowrap}
#barra .grupo .ayuda{margin-top:0}
/* -- documento -- */
main{flex:1;overflow-y:auto;padding:22px 18px 90px}
#doc{max-width:820px;margin:0 auto}
/* display:flow-root para que el bloque CONTENGA su botonera flotante (ver
   .util): sin el, un bloque mas bajo que los botones los dejaria salirse. */
.bl{position:relative;display:flow-root;background:var(--papel);
  border:1px solid transparent;border-radius:10px;padding:8px 12px 8px 30px;margin:0 0 6px}
.bl:hover{border-color:var(--borde)}
.bl.editando{border-color:var(--acento);box-shadow:var(--sombra)}
.bl.nueva{animation:entrar .45s ease-out}
.bl.destello{animation:destello 1.6s ease-out}
@keyframes entrar{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
@keyframes destello{0%{background:var(--iafondo)}100%{background:var(--papel)}}
.bl .candado{position:absolute;left:9px;top:11px;font-size:12px;line-height:1;
  color:var(--texto2);opacity:0;transition:opacity .3s ease}
.bl.fijado .candado{opacity:1;color:var(--ok)}
.bl.fijado{border-left:2px solid var(--ok)}
/* LA BOTONERA NO TAPA LO QUE HAY DEBAJO, Y NO HAY NINGUN NUMERO QUE AJUSTAR
   SI CRECE. Estaba en position:absolute encima del bloque: al corregir un
   parrafo, el final de la primera linea del textarea desaparecia detras del
   desplegable. Ahora:
     - LEYENDO va en float:right, o sea que las lineas de texto del bloque se
       acortan solas para dejarle sitio -- lo que mida, sin reservar ni un px
       de alto y sin que el bloque de un salto al pasar el raton por encima
       (por eso ocupa siempre su hueco y solo se enciende con visibility);
     - EDITANDO el bloque pasa a columna y la botonera es una fila propia
       ENCIMA del textarea, que es un elemento reemplazado y no sabe rodear a
       un flotante. Sea cual sea su alto, el textarea empieza debajo. */
.bl .util{float:right;margin-left:10px;display:flex;gap:3px;visibility:hidden}
.bl:hover .util,.bl.editando .util{visibility:visible}
.bl.editando{display:flex;flex-direction:column}
.bl.editando .util{float:none;align-self:flex-end;margin:0 0 4px}
.bl .util button,.bl .util select{padding:2px 6px;font-size:11.5px;line-height:1.5}
.vista h2{margin:.2em 0 .3em;font-size:22px;line-height:1.3}
.vista h3{margin:.2em 0 .3em;font-size:17.5px;line-height:1.35}
.vista .pre{white-space:pre-wrap;word-break:break-word;margin:0}
.vista ul,.vista ol{margin:.2em 0;padding-left:22px}
.vista blockquote{margin:.2em 0;padding-left:12px;border-left:3px solid var(--borde);
  color:var(--texto2)}
.vista table{border-collapse:collapse;font-size:14px}
.vista td,.vista th{border:1px solid var(--borde);padding:4px 9px;text-align:left}
/* Una imagen y una tabla son cajas, no lineas: no rodean a la botonera
   flotante, asi que se apartan debajo de ella en vez de quedarse tapadas. */
.vista img,.vista table{clear:right}
/* El tope de alto es para leer: una grafica de 950 px de alto obliga a hacer
   scroll para pasar de largo un solo bloque, y este documento se lee seguido. */
.vista img{display:block;max-width:100%;height:auto;max-height:60vh;border-radius:8px;
  border:1px solid var(--borde);margin:4px 0;background:#fff}
/* EL PNG DE UNA FORMULA O UNA GRAFICA ES TINTA OSCURA SOBRE PAPEL BLANCO
   (matplotlib guarda asi y mates.py no es de esta pagina): en tema oscuro eso
   es un rectangulo blanco de 775x537 deslumbrando sobre un fondo #0d1117. Se
   invierte AQUI, que es donde se sabe que tema hay -- invert(1) pone el papel
   negro y la tinta clara, y el hue-rotate devuelve su color a las lineas de
   colores. Solo a esos dos tipos: una FOTO invertida seria un negativo.
   El filtro tine tambien el borde de la imagen, asi que el borde de partida
   se elige claro en oscuro (--png-borde) para que salga discreto invertido.
   Al imprimir se apaga: el papel es blanco pase lo que pase (ver @media print). */
.bl.tipo-formula .vista img,.bl.tipo-grafica .vista img{
  filter:var(--png-filtro);border-color:var(--png-borde)}
.vista a{color:var(--acento)}
.vista code.cod{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;
  font-size:.9em;background:var(--panel);border-radius:5px;padding:0 4px}
.vista .latex{display:block;font-family:ui-monospace,SFMono-Regular,Consolas,monospace;
  font-size:12.5px;color:var(--texto2);margin-top:3px;white-space:pre-wrap}
.vista .pie{font-size:12.5px;color:var(--texto2)}
.et{display:inline-block;font-size:10.5px;letter-spacing:.04em;text-transform:uppercase;
  padding:0 6px;border-radius:20px;border:1px solid var(--borde);color:var(--texto2);
  margin-right:6px;vertical-align:1px}
.bl.tipo-examen{background:var(--marcafondo)}
.bl.tipo-examen .et{border-color:var(--marca);color:var(--marca)}
.bl.tipo-duda .et{border-color:var(--acento);color:var(--acento)}
textarea.ed{display:block;width:100%;min-height:60px;resize:vertical;overflow:hidden;
  padding:7px 9px;border-radius:7px;border:1px solid var(--acento);
  background:var(--fondo);color:var(--texto);
  font:14px/1.6 ui-monospace,SFMono-Regular,Consolas,monospace}
.ayuda{font-size:11.5px;color:var(--texto2);margin-top:4px}
.cola{margin-top:6px;padding:5px 9px;border-radius:6px;background:var(--iafondo);
  color:var(--texto);border:1px solid var(--ia);font-size:12.5px}
.aviso{color:var(--marca);font-size:12.5px;margin-top:3px}
.vacio{max-width:640px;margin:60px auto;text-align:center;color:var(--texto2)}
/* -- panel de insertar -- */
#panel{position:fixed;right:18px;bottom:18px;width:340px;max-width:calc(100% - 36px);
  max-height:70vh;overflow-y:auto;background:var(--papel);border:1px solid var(--borde);
  border-radius:12px;box-shadow:0 8px 30px rgba(0,0,0,.18);padding:14px;z-index:30}
#panel h2{margin:0 0 8px;font-size:14px}
#panel .fila{display:flex;gap:6px;align-items:center;margin-bottom:8px;flex-wrap:wrap}
#panel input,#panel select{flex:1;min-width:110px}
#resultados{max-height:230px;overflow-y:auto;margin-top:8px}
#resultados .res{border:1px solid var(--borde);border-radius:8px;padding:6px 8px;
  margin-bottom:5px;font-size:12.5px}
#resultados .res b{display:block;font-size:13px}
#resultados .res .lic{color:var(--texto2)}
footer{padding:6px 18px;background:var(--panel);border-top:1px solid var(--borde);
  color:var(--texto2);font-size:12px;display:flex;gap:14px;flex-wrap:wrap}
#toast{position:fixed;left:50%;bottom:22px;transform:translateX(-50%);z-index:40;
  background:var(--texto);color:var(--papel);padding:8px 14px;border-radius:8px;
  font-size:13px;opacity:0;pointer-events:none;transition:opacity .25s ease;max-width:80vw}
#toast.visible{opacity:.95}
#toast.mal{background:var(--mal);color:#fff}
/* EN UN MOVIL EL CROMO NO PUEDE COMERSE LA PANTALLA. Medido a 390x740 antes
   de esto: cabecera 151 px partida en tres filas + directo 68 + barra 142
   (casi toda la frase de ayuda envolviendose) + pie 67 = 428 de 740, y al
   documento le quedaban 203 px, o sea dos bloques y medio. Aqui se recorta lo
   que sobra en una pantalla estrecha, sin quitar NINGUNA funcion:
     - el titulo escrito se va (el cerebrito ya dice de quien es la pagina) y
       la busqueda baja a su propia linea, que es donde se puede teclear;
     - la barra de herramientas deja de envolverse y se desliza en horizontal,
       con la frase de ayuda (y su separador) fuera: se lee en pantalla ancha
       y en el movil estorba mas de lo que ensenia;
     - el pie se apila en una linea de altura normal. */
@media (max-width:640px){
  header{padding:6px 12px;gap:6px}
  h1{display:none}
  header select{max-width:7.5em;font-size:12.5px;padding:5px 6px}
  header button{padding:5px 8px;font-size:12px}
  input[type=search]{order:9;flex:1 0 100%;max-width:none;padding:5px 9px;line-height:1.4}
  #directo{padding:4px 12px;gap:10px;font-size:11.5px}
  #barra{padding:5px 12px;gap:5px;flex-wrap:nowrap;overflow-x:auto}
  #barra button{white-space:nowrap;padding:5px 8px;font-size:12px}
  /* Se va la FRASE (y su separador), no ninguna herramienta: es lo unico de
     la barra que se puede leer en pantalla ancha y aqui costaba 96 px. */
  #barra .g-ayuda{display:none}
  main{padding:14px 12px 60px}
  .bl{padding:6px 10px 6px 24px}
  /* Aqui no hay sitio para la botonera AL LADO del texto: flotando se comia
     dos tercios de la primera linea ("La segunda" y a la linea siguiente).
     En estrecho aparece al ABRIR el bloque, que ademas es lo unico que se
     puede hacer en una pantalla tactil -- tocarlo; no hay raton que pase por
     encima. Asi la linea entera es para el texto y no se reserva ni un px. */
  .bl .util{display:none}
  .bl.editando .util{display:flex}
  /* El pie de la izquierda es DATO (que documento y de cuando); el de la
     derecha es una frase fija que ya cuenta la propia pagina al corregir. */
  footer{padding:5px 12px;gap:10px;font-size:11.5px}
  #pie2{display:none}
  #panel{right:8px;bottom:8px;max-width:calc(100% - 16px)}
}
/* Quien pide menos movimiento no lo tiene: ni el latido, ni la entrada, ni el
   destello de lo que acaba de escribir la IA. */
@media (prefers-reduced-motion: reduce){
  *,*::before,*::after{animation:none!important;transition:none!important}
  #punto.vivo{opacity:1}
}
/* Imprimir es el camino universal a PDF: se va todo lo que no es el
   documento, y ningun bloque se parte entre dos hojas. */
@media print{
  header,#directo,#barra,#banner,#panel,#toast,footer,.bl .util,.ayuda{display:none!important}
  body,main{display:block;overflow:visible;background:#fff;color:#000}
  main{padding:0}
  #doc{max-width:none}
  .bl{break-inside:avoid;page-break-inside:avoid;border:none;padding-left:0;background:none}
  .bl.fijado{border-left:none}
  /* El papel es blanco aunque el duenio tenga puesto el tema oscuro: la
     inversion de los PNG de formula y grafica se apaga para imprimir. */
  .vista img{border-color:#bbb;filter:none!important}
}
</style></head><body>
<header>
  __CEREBRO__
  <h1>Cuaderno vivo</h1>
  <select id="sel-materia" title="Materia del documento"></select>
  <input id="buscar" type="search" placeholder="Buscar en el documento (tecla /)" autocomplete="off">
  <button id="b-imprimir" type="button" title="Imprimir o guardar en PDF">Imprimir</button>
  <button id="b-md" type="button" title="Descargar el documento en markdown">Markdown</button>
  <button id="b-tema" type="button" title="Tema claro u oscuro">Tema</button>
</header>
<div id="directo">
  <span id="rec"><span id="punto"></span><span id="rec-txt">conectando...</span></span>
  <span id="trozo"></span>
  <span id="cuenta"></span>
</div>
<div id="banner" hidden></div>
<div id="barra">
  <button id="b-parrafo" type="button">+ Parrafo</button>
  <button id="b-titulo" type="button">+ Titulo</button>
  <button id="b-lista" type="button">+ Lista</button>
  <span class="grupo"><span class="sep"></span>
    <button id="b-formula" type="button">Formula</button>
    <button id="b-grafica" type="button">Grafica</button>
    <button id="b-imagen" type="button">Imagen</button>
    <button id="b-tabla" type="button">Tabla</button></span>
  <span class="grupo g-ayuda"><span class="sep"></span>
    <span class="ayuda">Clic en un bloque para corregirlo. Al corregirlo queda
    FIJADO y la IA ya no lo reescribe.</span></span>
</div>
<main><div id="doc"></div></main>
<footer><span id="pie"></span><span id="pie2"></span></footer>
<div id="toast"></div>
<noscript><p style="padding:20px">Esta pagina pinta el documento con JavaScript
y lo recibe por eventos del servidor. Abrila en un navegador con JS activado.</p></noscript>

<!-- Plantillas. Todo lo que se pinta se clona de aqui y se rellena con
     textContent / setAttribute: aqui no se asigna HTML crudo a ningun nodo,
     asi que un apunte con etiquetas dentro se lee como texto y nunca como
     marcado. La palabra prohibida ni siquiera se escribe: el test que la
     vigila busca el literal en la pagina entera. -->
<template id="t-bloque"><article class="bl">
  <span class="candado" title="fijado por ti: la IA no lo toca">&#9679;</span>
  <div class="util">
    <select class="sel-tipo" title="Tipo de bloque"></select>
    <button class="b-sube" type="button" title="Subir">&uarr;</button>
    <button class="b-baja" type="button" title="Bajar">&darr;</button>
    <button class="b-fija" type="button" title="Fijar o soltar">fijar</button>
    <button class="b-borra" type="button" title="Borrar">&times;</button>
  </div>
  <div class="vista"></div>
  <div class="cola" hidden></div>
</article></template>
<template id="t-editor"><textarea class="ed" spellcheck="true"></textarea></template>
<template id="t-imagen"><img alt="Imagen del documento" loading="lazy"></template>
<template id="t-resultado"><div class="res"><b></b><span class="lic"></span>
  <div><a target="_blank" rel="noopener noreferrer">ver la ficha</a>
  <button type="button">insertar</button></div></div></template>
<template id="t-panel"><div id="panel">
  <h2></h2>
  <div class="fila"><input class="p1" type="text"></div>
  <div class="fila"><input class="p2" type="text"><input class="p3" type="text"></div>
  <div class="fila"><button class="pri b-ok" type="button">Insertar</button>
    <button class="b-no" type="button">Cerrar</button>
    <input class="fich" type="file" accept="image/*" hidden></div>
  <div class="ayuda"></div>
  <div id="resultados"></div>
</div></template>

<script>
"use strict";
/* =====================================================================
   Cuaderno vivo. Reglas de este bloque, que los tests vigilan: solo ASCII,
   ni HTML crudo asignado a un nodo, ni un acento grave, ni una URL de red.
   ===================================================================== */
var D = __DATOS__;
var C = __CTX__;
var TIPOS = __TIPOS__;

function $(s){ return document.querySelector(s); }
function tpl(id){
  return document.getElementById(id).content.firstElementChild.cloneNode(true);
}
function nodo(tag, clase, texto){
  var e = document.createElement(tag);
  if(clase) e.className = clase;
  if(texto !== undefined && texto !== null) e.textContent = texto;
  return e;
}
function normalizar(s){
  /* Sin tildes y en minusculas: es como se busca de verdad en unos apuntes.
     Mismo criterio que documento._norm, que es quien busca en Python. */
  return String(s || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
}

/* --------- estado --------- */
var S = {
  bloques: (D.bloques || []).slice(),
  nodos: {},              /* id -> el <article> que lo pinta */
  editando: null,         /* id del bloque que el duenio tiene abierto */
  area: null,             /* su <textarea> */
  original: "",           /* lo que habia al abrirlo */
  pendiente: null,        /* la promesa del guardado EN VUELO (uno como mucho) */
  cola: {},               /* id -> lo que la IA quiso hacer mientras editaba */
  ordenPendiente: false,
  aplazados: {},          /* id -> repintado aplazado por no romper la seleccion */
  nuevos: {},             /* ids que acaban de llegar: entran con animacion */
  q: "",
  ultimoTrozo: (D.ultimo_trozo || 0) * 1000,
  vacio: null,            /* el cartel de "no hay nada", si esta puesto */
  es: null, conectado: false, espera: 0, reintentoEn: 0, tReintento: null,
  tDirecto: null, tEstado: null,
  soloLectura: false, grabando: false, materiaViva: "", materia: D.materia || ""
};

/* --------- tema --------- */
/* El almacenamiento local se puede bloquear entero (ventana privada, politica
   de cookies del navegador, la pagina abierta con file://) y entonces el
   boton de Tema deja de recordar la eleccion. Callarlo era la regla de la
   casa aplicada al reves: "no lo cablearon" y "se rompio" tienen que verse
   distinto, tambien desde el navegador. Al leer basta la consola (avisar de
   algo que el duenio no ha pedido todavia seria ruido); al ESCRIBIR, que es
   una accion suya, se lo decimos en pantalla. */
function avisarAlmacen(que, e){
  var m = "el navegador no deja " + que + " el tema (" +
          ((e && e.message) || e) + ")";
  if(window.console && window.console.warn) window.console.warn("cuaderno vivo: " + m);
  return m;
}
(function(){
  var t = null;
  try{ t = localStorage.getItem("cognia_vivo_tema"); }
  catch(e){ avisarAlmacen("recordar", e); }
  if(t) document.documentElement.setAttribute("data-tema", t);
})();
$("#b-tema").onclick = function(){
  var actual = document.documentElement.getAttribute("data-tema");
  var oscuro = window.matchMedia &&
    window.matchMedia("(prefers-color-scheme: dark)").matches;
  var nuevo = (actual || (oscuro ? "oscuro" : "claro")) === "oscuro" ? "claro" : "oscuro";
  document.documentElement.setAttribute("data-tema", nuevo);
  try{ localStorage.setItem("cognia_vivo_tema", nuevo); }
  catch(e){
    toast(avisarAlmacen("guardar", e) + ": lo tendras que elegir otra vez al recargar", true);
  }
};

/* --------- avisos --------- */
var tToast = null;
function toast(txt, malo){
  var t = $("#toast");
  t.textContent = txt;
  t.className = "visible" + (malo ? " mal" : "");
  if(tToast) clearTimeout(tToast);
  tToast = setTimeout(function(){ t.className = ""; }, malo ? 7000 : 3200);
}
/* HAY UN SOLO BANNER Y VARIAS COSAS QUE CONTAR, asi que tiene dueno: el aviso
   de un guardado que fallo lleva DENTRO el boton que recupera el texto del
   duenio, y taparlo con "se corto la conexion" (o borrarlo al reconectar)
   seria dejarle sin la unica puerta a lo que escribio. Por peso: guardar >
   solo lectura / desincronizado > conexion. Lo que un banner de menos peso no
   llega a decir se sigue viendo en la barra de directo, que no miente. */
var PESO_BANNER = {conexion: 1, sync: 2, lectura: 2, guardar: 3};
var claveBanner = "";
/* El parrafo del banner se guarda aparte para poder REESCRIBIRLO sin tocar el
   boton que lleva al lado (el de reintentar el guardado es la unica puerta al
   texto del duenio: reconstruir el banner cada segundo lo borraria). */
var textoBanner = null;
function banner(txt, malo, boton, alPulsar, clave){
  clave = clave || "";
  var b = $("#banner");
  if(!b.hidden && (PESO_BANNER[clave] || 0) < (PESO_BANNER[claveBanner] || 0)) return;
  b.textContent = "";
  b.className = malo ? "mal" : "";
  textoBanner = nodo("span", null, txt);
  b.appendChild(textoBanner);
  if(boton){
    var x = nodo("button", null, boton);
    x.onclick = alPulsar;
    b.appendChild(x);
  }
  b.hidden = false;
  claveBanner = clave;
}
/* Sin clave se quita lo que haya; con clave, solo si el banner es SUYO. */
function quitarBanner(clave){
  if(clave && claveBanner !== clave) return;
  $("#banner").hidden = true;
  claveBanner = "";
  textoBanner = null;
}

/* --------- URLs: solo las que sirve ESTE servidor --------- */
function urlAdj(jornada, nombre){
  if(!jornada || !nombre) return "";
  return C.adj + "/" + encodeURIComponent(jornada) + "/" +
         encodeURIComponent(nombre) + "?t=" + encodeURIComponent(C.token);
}
/* Un src de esta pagina solo puede ser una ruta de /adj de este mismo
   servidor. Cualquier otra cosa (empezando por un dato del documento que
   quiera ser una URL) se queda fuera del DOM. */
function urlSegura(u){
  u = String(u || "");
  return u.indexOf(C.adj + "/") === 0 ? u : "";
}
/* Y un href de la ficha de una imagen buscada solo puede ser un enlace web,
   que el duenio abre en otra pestania. Nada de javascript: ni data:. */
function urlWeb(u){
  return /^https?:\/\/[^\s"'<>]+$/i.test(String(u || "")) ? String(u) : "";
}

/* =====================================================================
   MARKDOWN EN LINEA, CONSTRUIDO CON NODOS
   El bloque guarda MARKDOWN CRUDO (es lo que el duenio edita y lo que busca
   documento.py), asi que pintarlo con textContent a secas le ensenia sus
   propias marcas: la primera frase se leia "La **segunda ley de Newton**
   relaciona...". Aqui se pinta negrita, cursiva, codigo y enlace CREANDO
   NODOS (createElement + textContent). Nunca concatenando marcado: la regla
   de la casa lo prohibe y es la que hace que un apunte que traiga una
   etiqueta escrita dentro se lea como texto, que es lo que es.
   TRES DECISIONES, cada una por su motivo:
     - los enlaces pasan por urlWeb, la MISMA validacion que ya usaba la ficha
       de una imagen buscada: un "javascript:" no se pinta como enlace;
     - lo que no case (un asterisco sin cerrar, un enlace que no es web) se
       queda LITERAL en pantalla; comerse texto del duenio para disimular una
       marca a medias seria mucho peor que ensenar el markdown crudo;
     - solo el asterisco marca enfasis, no el guion bajo: en unos apuntes de
       clase "v_media" y "x_1" son mas frecuentes que un _enfasis_, y
       convertirlos en cursiva se comeria los subindices.
   El patron se construye con new RegExp desde una cadena porque el acento
   grave del codigo se escribe \x60: en este bloque no puede haber ni uno. */
/* El contenido de una marca EMPIEZA Y ACABA en algo que no es un espacio
   (\S ... \S). No es un adorno: sin la segunda condicion, "2*3 y *sin cerrar"
   se cerraria a si mismo y saldria una cursiva inventada donde el duenio
   escribio una multiplicacion. Es la misma idea que la regla de flanqueo de
   CommonMark, reducida a lo que unos apuntes necesitan. */
var RE_MARCAS = new RegExp(
  "\\*\\*(\\S(?:[\\s\\S]*?\\S)?)\\*\\*" +   /* 1: negrita */
  "|\\*(\\S(?:[^*\\n]*?\\S)?)\\*" +         /* 2: cursiva */
  "|\\x60([^\\x60\\n]+)\\x60" +             /* 3: codigo */
  "|\\[([^\\]\\n]*)\\]\\(([^)\\s]*)\\)",    /* 4: texto, 5: destino */
  "g");

function marcas(cont, texto){
  var s = String(texto || ""), m, i = 0, a;
  RE_MARCAS.lastIndex = 0;
  while((m = RE_MARCAS.exec(s)) !== null){
    if(m.index > i) cont.appendChild(document.createTextNode(s.slice(i, m.index)));
    if(m[1] !== undefined){
      cont.appendChild(nodo("strong", null, m[1]));
    } else if(m[2] !== undefined){
      cont.appendChild(nodo("em", null, m[2]));
    } else if(m[3] !== undefined){
      cont.appendChild(nodo("code", "cod", m[3]));
    } else {
      var href = urlWeb(m[5]);
      if(href){
        a = nodo("a", null, m[4]);
        a.setAttribute("href", href);
        a.setAttribute("target", "_blank");
        a.setAttribute("rel", "noopener noreferrer");
        cont.appendChild(a);
      } else {
        cont.appendChild(document.createTextNode(m[0]));
      }
    }
    i = m.index + m[0].length;
  }
  if(i < s.length) cont.appendChild(document.createTextNode(s.slice(i)));
  return cont;
}

/* =====================================================================
   PINTAR
   La regla que sostiene esta pagina entera: el nodo del bloque que se esta
   editando NO se reconstruye, NO se rellena y NO se mueve. Por eso se
   reconcilia por id en vez de vaciar el contenedor -- el textarea conserva
   por construccion su cursor, su seleccion y su scroll, sin tener que
   "restaurarlos" despues (que es el apanio que falla en el caso raro).
   ===================================================================== */
function editando(id){ return S.editando === id; }

function firma(b){
  return [b.tipo, b.texto, b.fijado ? 1 : 0, b.origen, b.adjunto || "",
          b.jornada || "", b.aviso || "",
          (b.meta && b.meta.atribucion) || ""].join("");
}

function etiquetaTipo(t){
  for(var i = 0; i < TIPOS.length; i++) if(TIPOS[i][0] === t) return TIPOS[i][1];
  return t;
}

function lineas(texto){
  return String(texto || "").split("\n");
}

function pintarVista(cont, b){
  cont.textContent = "";
  var t = b.tipo, i, l, li, ul;
  if(t === "titulo"){ cont.appendChild(marcas(nodo("h2"), b.texto)); return; }
  if(t === "subtitulo"){ cont.appendChild(marcas(nodo("h3"), b.texto)); return; }
  if(t === "lista"){
    ul = nodo("ul");
    l = lineas(b.texto);
    for(i = 0; i < l.length; i++){
      var x = l[i].replace(/^\s*[-*+]\s+/, "").trim();
      if(x) ul.appendChild(marcas(nodo("li"), x));
    }
    cont.appendChild(ul.childNodes.length ? ul : marcas(nodo("p", "pre"), b.texto));
    return;
  }
  if(t === "cita"){
    var q = nodo("blockquote");
    q.appendChild(marcas(nodo("div", "pre"),
      lineas(b.texto).map(function(z){ return z.replace(/^\s*>\s?/, ""); }).join("\n")));
    cont.appendChild(q);
    return;
  }
  if(t === "tabla"){
    var tab = nodo("table"), filas = lineas(b.texto), n = 0;
    for(i = 0; i < filas.length; i++){
      var cruda = filas[i].trim();
      if(!cruda) continue;
      if(/^\|?[\s:-]*\|[\s:|-]*$/.test(cruda) && cruda.indexOf("-") >= 0) continue;
      var celdas = cruda.replace(/^\|/, "").replace(/\|$/, "").split("|");
      var tr = nodo("tr");
      for(var j = 0; j < celdas.length; j++){
        tr.appendChild(marcas(nodo(n === 0 ? "th" : "td"), celdas[j].trim()));
      }
      tab.appendChild(tr);
      n++;
    }
    cont.appendChild(n ? tab : marcas(nodo("p", "pre"), b.texto));
    return;
  }
  if(t === "formula" || t === "grafica" || t === "imagen"){
    var src = urlSegura(urlAdj(b.jornada, b.adjunto));
    if(src){
      var img = tpl("t-imagen");
      img.setAttribute("src", src);
      if(b.texto) img.setAttribute("alt", b.texto);
      cont.appendChild(img);
    }
    if(t === "formula" && (b.meta.latex || b.texto)){
      cont.appendChild(nodo("code", "latex", b.meta.latex || b.texto));
    } else if(b.texto && t !== "formula"){
      cont.appendChild(nodo("div", "pie", b.texto));
    }
    if(b.meta && b.meta.atribucion){
      cont.appendChild(nodo("div", "pie", b.meta.atribucion));
    }
    if(!src && !b.aviso){
      cont.appendChild(nodo("div", "aviso",
        "todavia no hay imagen guardada para este bloque"));
    }
    return;
  }
  if(t === "deber" || t === "duda" || t === "examen"){
    var p = nodo("p", "pre");
    p.appendChild(nodo("span", "et", etiquetaTipo(t)));
    marcas(p, b.texto);
    cont.appendChild(p);
    return;
  }
  cont.appendChild(marcas(nodo("p", "pre"), b.texto));
}

function rellenar(art, b){
  art.className = "bl tipo-" + b.tipo + (b.fijado ? " fijado" : "") +
                  (editando(b.id) ? " editando" : "");
  if(S.nuevos[b.id]){ art.className += " nueva"; delete S.nuevos[b.id]; }
  var sel = art.querySelector(".sel-tipo");
  if(sel.value !== b.tipo) sel.value = b.tipo;
  art.querySelector(".b-fija").textContent = b.fijado ? "soltar" : "fijar";
  pintarVista(art.querySelector(".vista"), b);
  if(b.aviso){
    art.querySelector(".vista").appendChild(nodo("div", "aviso", b.aviso));
  }
  art._firma = firma(b);
}

function crearNodo(b){
  var art = tpl("t-bloque");
  art.setAttribute("data-id", b.id);
  var sel = art.querySelector(".sel-tipo");
  for(var i = 0; i < TIPOS.length; i++){
    var o = document.createElement("option");
    o.value = TIPOS[i][0];
    o.textContent = TIPOS[i][1];
    sel.appendChild(o);
  }
  sel.onchange = function(){ cambiarTipo(b.id, sel.value); };
  art.querySelector(".b-sube").onclick = function(){ mover(b.id, -1); };
  art.querySelector(".b-baja").onclick = function(){ mover(b.id, 1); };
  art.querySelector(".b-fija").onclick = function(){ alternarFijado(b.id); };
  art.querySelector(".b-borra").onclick = function(){ borrar(b.id); };
  art.querySelector(".vista").onclick = function(){ abrirEditor(b.id); };
  S.nodos[b.id] = art;
  return art;
}

function visibles(){
  if(!S.q) return S.bloques;
  var q = normalizar(S.q);
  return S.bloques.filter(function(b){
    return normalizar(b.busca + " " + b.texto).indexOf(q) >= 0 || editando(b.id);
  });
}

/* ANCLA DE SCROLL. La IA escribe mientras el duenio lee: si el bloque que
   entra queda POR ENCIMA de lo que esta mirando, el texto le salta hacia
   abajo a media frase. Se mide un nodo de referencia (el que se edita, o el
   primero visible) antes de tocar el DOM y se corrige el scroll despues.
   El contenedor que hace scroll es <main>, no la ventana. */
function anclaScroll(){
  var sc = document.querySelector("main"), ref = null, hijos, y, i;
  if(!sc) return null;
  if(S.editando && S.nodos[S.editando]) ref = S.nodos[S.editando];
  if(!ref || !ref.parentNode){
    ref = null;
    hijos = $("#doc").children;
    y = sc.getBoundingClientRect().top;
    for(i = 0; i < hijos.length; i++){
      if(hijos[i].getBoundingClientRect().bottom > y){ ref = hijos[i]; break; }
    }
  }
  if(!ref) return null;
  return {sc: sc, nodo: ref, y: ref.getBoundingClientRect().top};
}
function restaurarScroll(a){
  if(!a || !a.nodo.parentNode) return;
  var dy = a.nodo.getBoundingClientRect().top - a.y;
  if(dy) a.sc.scrollTop += dy;
}

/* La seleccion del duenio tambien es trabajo suyo: esta copiando de sus
   apuntes mientras la IA escribe, y repintar el bloque que tiene senialado se
   la borra. Se comprueba si la seleccion viva toca ESE nodo. */
function tieneSeleccion(art){
  var s = window.getSelection ? window.getSelection() : null;
  if(!s || s.isCollapsed || !s.rangeCount) return false;
  var r = s.getRangeAt(0);
  return art.contains(r.startContainer) || art.contains(r.endContainer);
}

function pintar(){
  var cont = $("#doc"), lista = visibles(), i, b, art, vistos = {};
  var ancla = anclaScroll();
  /* El cartel de vacio se quita ANTES de reconciliar: si se quedara puesto,
     seria un hijo mas del contenedor y descuadraria las posiciones con las
     que se decide si un bloque hay que moverlo. */
  if(S.vacio){
    if(S.vacio.parentNode) S.vacio.parentNode.removeChild(S.vacio);
    S.vacio = null;
  }
  for(i = 0; i < lista.length; i++){
    b = lista[i];
    vistos[b.id] = 1;
    art = S.nodos[b.id];
    if(!art){
      art = crearNodo(b);
      S.nuevos[b.id] = 1;
      rellenar(art, b);
    } else if(editando(b.id)){
      /* EL NODO EN EDICION NO SE TOCA. Si el bloque cambio por debajo, se
         encola y se avisa; pisarlo seria borrarle al duenio lo que esta
         escribiendo, que es el bug de oficina/server.py:121. */
      if(art._firma !== firma(b)) encolar(b, "la IA cambio este bloque mientras lo corregias");
    } else if(art._firma !== firma(b)){
      /* Si el duenio tiene una seleccion dentro, el repintado se APLAZA hasta
         que la suelte: el bloque se queda un momento viejo, que es mucho
         menos malo que quitarle de las manos lo que estaba senialando. */
      if(tieneSeleccion(art)){
        S.aplazados[b.id] = 1;
      } else {
        delete S.aplazados[b.id];
        rellenar(art, b);
      }
    }
    if(cont.childNodes[i] !== art){
      if(editando(b.id)){
        /* Moverlo con insertBefore lo saca y lo vuelve a meter en el DOM, y
           eso le quita el foco al textarea: se deja donde esta y el orden se
           aplica al cerrar el editor. */
        S.ordenPendiente = true;
      } else {
        cont.insertBefore(art, cont.childNodes[i] || null);
      }
    }
  }
  for(var id in S.nodos){
    if(vistos[id]) continue;
    if(editando(id)) continue;      /* tampoco se borra lo que se esta editando */
    if(S.nodos[id].parentNode) S.nodos[id].parentNode.removeChild(S.nodos[id]);
    delete S.nodos[id];
    delete S.aplazados[id];         /* el nodo se fue: su repintado ya no espera */
  }
  if(!cont.childNodes.length){
    S.vacio = nodo("div", "vacio", S.bloques.length
      ? "Ningun bloque coincide con lo que buscaste."
      : (S.materia
          ? "Este documento esta vacio: escribe el primer bloque o deja que la IA lo llene mientras te dan clase."
          : "Todavia no hay ningun documento. Se crea solo al grabar una clase, o con el primer bloque que escribas."));
    cont.appendChild(S.vacio);
  }
  restaurarScroll(ancla);
  $("#cuenta").textContent = S.bloques.length + " bloques, " +
    S.bloques.filter(function(b){ return b.fijado; }).length + " fijados por ti";
}

function encolar(b, motivo){
  S.cola[b.id] = motivo;
  var art = S.nodos[b.id];
  if(!art) return;
  var c = art.querySelector(".cola");
  c.textContent = motivo + ". Lo tuyo manda: al guardar, el bloque queda fijado.";
  c.hidden = false;
}

function destello(id){
  var art = S.nodos[id];
  if(!art || editando(id)) return;
  art.classList.remove("destello");
  /* Forzar el reflow es lo que hace que la animacion se pueda repetir en el
     mismo nodo: sin leer offsetWidth el navegador agrupa quitar y poner. */
  void art.offsetWidth;
  art.classList.add("destello");
}

/* =====================================================================
   EDITOR DE UN BLOQUE
   ===================================================================== */
function bloquePorId(id){
  for(var i = 0; i < S.bloques.length; i++) if(S.bloques[i].id === id) return S.bloques[i];
  return null;
}

function autoalto(ta){
  ta.style.height = "auto";
  ta.style.height = (ta.scrollHeight + 2) + "px";
}

/* ABRIR ES ESPERAR A QUE EL ANTERIOR HAYA CERRADO DE VERDAD.
   Aqui vivia el peor fallo que puede tener un editor: cerrarEditor(true) es
   ASINCRONO cuando hay texto cambiado (sale una peticion), y esto seguia
   adelante sin esperarlo. Quedaban DOS textareas vivos y UN solo par de
   variables (S.editando / S.area) para los dos: el guardado que volvia tarde
   apagaba el editor recien abierto (lo que se tecleara ahi ya no se podia
   guardar por ningun camino), y el boton "reintentar" del banner --que lee
   esas variables-- mandaba el texto de un bloque al OTRO. Por eso devuelve
   una promesa y no se abre nada hasta que el cierre termine. */
function abrirEditor(id){
  if(S.editando === id) return Promise.resolve();
  return cerrarEditor(true).then(function(){
    /* Si el cierre no pudo guardar, el editor anterior sigue abierto con el
       texto del duenio dentro: no se le abre otro encima. */
    if(S.editando) return;
    abrirEditorYa(id);
  });
}

function abrirEditorYa(id){
  var b = bloquePorId(id), art = S.nodos[id];
  if(!b || !art) return;
  var ta = tpl("t-editor");
  ta.value = b.texto;
  art.querySelector(".vista").hidden = true;
  art.insertBefore(ta, art.querySelector(".cola"));
  var ayuda = nodo("div", "ayuda",
    "Markdown crudo. Ctrl+Enter guarda (y FIJA el bloque), Escape cancela.");
  art.insertBefore(ayuda, art.querySelector(".cola"));
  S.editando = id;
  S.area = ta;
  S.original = b.texto;
  art.classList.add("editando");
  ta.oninput = function(){ autoalto(ta); };
  ta.onkeydown = function(e){
    if(e.key === "Enter" && (e.ctrlKey || e.metaKey)){ e.preventDefault(); cerrarEditor(true); }
    else if(e.key === "Escape"){ e.preventDefault(); cerrarEditor(false); }
  };
  ta.focus();
  ta.selectionStart = ta.selectionEnd = ta.value.length;
  autoalto(ta);
}

/* Devuelve SIEMPRE una promesa que resuelve cuando ya no hay nada abierto ni
   nada en vuelo: es lo que deja encadenar abrir, imprimir o cambiar de
   materia detras de un cierre. */
function cerrarEditor(guardar){
  if(S.pendiente) return S.pendiente;   /* uno en vuelo: no se manda otro */
  var id = S.editando, ta = S.area;
  if(!id || !ta) return Promise.resolve();
  var texto = ta.value;
  var b = bloquePorId(id);
  if(guardar && b && texto !== S.original) return guardarBloque(id, ta, texto);
  cerrarDeVerdad(id);
  return Promise.resolve();
}

/* El guardado va atado a SU bloque y a SU textarea, nunca al estado global:
   el "reintentar" del banner tiene que mandar el texto de ESE editor a ESE
   id, pase lo que pase en la pagina mientras tanto.
   Se guarda ANTES de cerrar nada: si el servidor no acepta escrituras, el
   textarea se queda abierto con el texto dentro. Perder lo tecleado es la
   unica cosa que esta pagina no puede hacer. */
function guardarBloque(id, ta, texto){
  if(S.pendiente) return S.pendiente;
  var p = accion({accion: "editar", materia: S.materia, id: id, texto: texto})
    .then(function(j){
      S.pendiente = null;
      quitarBanner("guardar");
      adoptar(j.bloques);
      cerrarDeVerdad(id);
      toast("guardado y fijado: la IA ya no toca este bloque");
    })
    .catch(function(e){
      S.pendiente = null;
      banner("No se pudo guardar. " + e.message +
             " -- Tu texto sigue en el editor: no se ha perdido nada.", true,
             "reintentar", function(){ guardarBloque(id, ta, ta.value); },
             "guardar");
    });
  S.pendiente = p;
  return p;
}

function cerrarDeVerdad(id){
  var art = S.nodos[id];
  /* Las variables solo se apagan si SIGUEN siendo de este bloque: un guardado
     que vuelve tarde no puede desconectar el editor de otro. */
  if(S.editando === id){
    S.editando = null;
    S.area = null;
    S.original = "";
  }
  if(art){
    var ta = art.querySelector("textarea.ed");
    if(ta) art.removeChild(ta);
    var ay = art.querySelector(".ayuda");
    if(ay) art.removeChild(ay);
    art.querySelector(".vista").hidden = false;
    art.classList.remove("editando");
    art._firma = "";                  /* obliga a repintarlo con lo que hay */
    var b = bloquePorId(id);
    if(b) rellenar(art, b);
    if(S.cola[id]){
      delete S.cola[id];
      art.querySelector(".cola").hidden = true;
    }
  }
  if(S.ordenPendiente){ S.ordenPendiente = false; }
  pintar();
}

/* =====================================================================
   RED: la puerta de escritura
   ===================================================================== */
function accion(cuerpo){
  return fetch(C.accion, {
    method: "POST",
    headers: {"Content-Type": "application/json", "X-Cognia-Token": C.token},
    body: JSON.stringify(cuerpo)
  }).then(function(r){
    return r.json().catch(function(){
      return {ok: false, error: "el servidor contesto algo que no es JSON (" + r.status + ")"};
    });
  }).then(function(j){
    if(!j || !j.ok){
      var motivo = (j && j.error) || "sin motivo";
      if(/solo lectura|SOLO LECTURA|404/.test(motivo)) marcarSoloLectura(motivo);
      throw new Error(motivo);
    }
    if(S.soloLectura){ S.soloLectura = false; quitarBanner("lectura"); }
    if(j.aviso) toast(j.aviso, true);
    return j;
  }).catch(function(e){
    if(e instanceof TypeError){
      /* fetch solo lanza TypeError cuando no hubo respuesta: servidor caido. */
      marcarSoloLectura("no hay respuesta del servidor local");
      throw new Error("no hay respuesta del servidor local");
    }
    throw e;
  });
}

function marcarSoloLectura(motivo){
  S.soloLectura = true;
  banner("Este cuaderno esta abierto en SOLO LECTURA (" + motivo + "). " +
         "Puedes leer y buscar; para corregir, usa el REPL de Cognia.", true,
         null, null, "lectura");
}

function adoptar(lista){
  if(!lista) return;
  S.bloques = lista;
  pintar();
}

/* --------- acciones de la barra --------- */
function tras(){
  /* Se inserta detras del bloque que se este editando, o al final. */
  return S.editando || (S.bloques.length ? S.bloques[S.bloques.length - 1].id : "");
}
function aniadir(tipo, texto){
  if(!S.materia){ toast("elige o crea una materia antes de escribir", true); return; }
  accion({accion: "aniadir", materia: S.materia, tipo: tipo,
          texto: texto || "", tras: tras()})
    .then(function(j){
      adoptar(j.bloques);
      if(j.id) abrirEditor(j.id);
    })
    .catch(function(e){ toast("no se pudo aniadir: " + e.message, true); });
}
function cambiarTipo(id, tipo){
  accion({accion: "tipo", materia: S.materia, id: id, tipo: tipo})
    .then(function(j){ adoptar(j.bloques); })
    .catch(function(e){ toast("no se pudo cambiar el tipo: " + e.message, true); });
}
function mover(id, delta){
  var i = -1, k;
  for(k = 0; k < S.bloques.length; k++) if(S.bloques[k].id === id) i = k;
  if(i < 0) return;
  var destino = i + delta;
  if(destino < 0 || destino >= S.bloques.length) return;
  var cuerpo = {accion: "mover", materia: S.materia, id: id};
  if(delta < 0 && destino === 0) cuerpo.al_principio = true;
  else cuerpo.tras = S.bloques[delta < 0 ? destino - 1 : destino].id;
  accion(cuerpo).then(function(j){ adoptar(j.bloques); })
    .catch(function(e){ toast("no se pudo mover: " + e.message, true); });
}
function alternarFijado(id){
  var b = bloquePorId(id);
  if(!b) return;
  accion({accion: "fijar", materia: S.materia, id: id, valor: !b.fijado})
    .then(function(j){ adoptar(j.bloques); })
    .catch(function(e){ toast("no se pudo fijar: " + e.message, true); });
}
function borrar(id){
  var b = bloquePorId(id);
  if(!b) return;
  if(b.texto && !window.confirm("Borrar este bloque?")) return;
  if(editando(id)) cerrarDeVerdad(id);
  accion({accion: "borrar", materia: S.materia, id: id})
    .then(function(j){ adoptar(j.bloques); })
    .catch(function(e){ toast("no se pudo borrar: " + e.message, true); });
}

/* =====================================================================
   PANEL DE INSERTAR (formula, grafica, imagen, tabla)
   ===================================================================== */
var panel = null;
function cerrarPanel(){
  if(panel && panel.parentNode) panel.parentNode.removeChild(panel);
  panel = null;
}
function abrirPanel(titulo, ayuda, campos, alAceptar){
  cerrarPanel();
  panel = tpl("t-panel");
  panel.querySelector("h2").textContent = titulo;
  panel.querySelector(".ayuda").textContent = ayuda;
  var p1 = panel.querySelector(".p1"), p2 = panel.querySelector(".p2"),
      p3 = panel.querySelector(".p3");
  p1.placeholder = campos[0] || "";
  p2.placeholder = campos[1] || "";
  p3.placeholder = campos[2] || "";
  if(campos.length < 2){ p2.hidden = true; p3.hidden = true; }
  if(campos.length === 3){ p2.value = campos[3] || ""; }
  panel.querySelector(".b-no").onclick = cerrarPanel;
  panel.querySelector(".b-ok").onclick = function(){
    alAceptar(p1.value, p2.value, p3.value, panel);
  };
  p1.onkeydown = function(e){ if(e.key === "Enter") panel.querySelector(".b-ok").click(); };
  document.body.appendChild(panel);
  p1.focus();
  return panel;
}
function insertarFormula(){
  abrirPanel("Insertar formula",
    "LaTeX de formula (\\frac, \\sqrt, ^, _). Se dibuja en PNG y el LaTeX se " +
    "queda dentro del bloque para poder corregirlo y buscarlo.",
    ["v = \\frac{e}{t}"],
    function(latex){
      if(!latex.trim()) return;
      accion({accion: "formula", materia: S.materia, latex: latex, tras: tras()})
        .then(function(j){
          adoptar(j.bloques);
          cerrarPanel();
          (j.avisos || []).forEach(function(a){ toast(a, true); });
        })
        .catch(function(e){ toast("no se pudo dibujar: " + e.message, true); });
    });
}
function insertarGrafica(){
  var p = abrirPanel("Insertar grafica",
    "Una expresion de una variable. Se dibuja con matplotlib, sin salir a la red.",
    ["sin(x)/x", "desde", "hasta"],
    function(expresion, desde, hasta){
      if(!expresion.trim()) return;
      accion({accion: "grafica", materia: S.materia, expresion: expresion,
              desde: parseFloat(desde || "-10"), hasta: parseFloat(hasta || "10"),
              tras: tras()})
        .then(function(j){ adoptar(j.bloques); cerrarPanel(); })
        .catch(function(e){ toast("no se pudo dibujar: " + e.message, true); });
    });
  p.querySelector(".p2").value = "-10";
  p.querySelector(".p3").value = "10";
}
function insertarImagen(){
  var p = abrirPanel("Insertar imagen",
    "Elige un fichero, PEGA una imagen con Ctrl+V en cualquier parte de la " +
    "pagina, o busca una imagen libre: el servidor la baja y la guarda con su " +
    "atribucion (las miniaturas no se cargan desde la red en esta pagina).",
    ["buscar imagenes libres..."],
    function(consulta, x, y, pan){
      if(!consulta.trim()) return;
      var res = pan.querySelector("#resultados");
      res.textContent = "";
      res.appendChild(nodo("div", "res", "buscando..."));
      accion({accion: "buscar_imagenes", consulta: consulta})
        .then(function(j){ pintarResultados(res, j); })
        .catch(function(e){
          res.textContent = "";
          res.appendChild(nodo("div", "res", "no se pudo buscar: " + e.message));
        });
    });
  var fich = p.querySelector(".fich");
  fich.hidden = false;
  fich.onchange = function(){
    var f = fich.files && fich.files[0];
    if(f) subirImagen(f);
  };
}
function pintarResultados(res, j){
  res.textContent = "";
  var lista = j.resultados || [];
  (j.avisos || []).forEach(function(a){ res.appendChild(nodo("div", "res", a)); });
  if(!lista.length){
    res.appendChild(nodo("div", "res", "ninguna fuente encontro imagenes."));
    return;
  }
  lista.forEach(function(r){
    var fila = tpl("t-resultado");
    fila.querySelector("b").textContent = r.titulo || "(sin titulo)";
    fila.querySelector(".lic").textContent =
      (r.autor || "autor desconocido") + " -- " + (r.licencia || "licencia ?") +
      " -- " + r.ancho + "x" + r.alto;
    var a = fila.querySelector("a"), href = urlWeb(r.url_pagina);
    if(href) a.setAttribute("href", href); else a.remove();
    fila.querySelector("button").onclick = function(){
      accion({accion: "imagen_web", materia: S.materia, url: r.url_imagen,
              atribucion: r.atribucion, texto: r.titulo, tras: tras()})
        .then(function(k){ adoptar(k.bloques); cerrarPanel(); })
        .catch(function(e){ toast("no se pudo bajar: " + e.message, true); });
    };
    res.appendChild(fila);
  });
}
function subirImagen(fichero){
  var fr = new FileReader();
  fr.onload = function(){
    accion({accion: "imagen", materia: S.materia, datos: String(fr.result),
            texto: fichero.name, tras: tras()})
      .then(function(j){ adoptar(j.bloques); cerrarPanel(); })
      .catch(function(e){ toast("no se pudo insertar: " + e.message, true); });
  };
  fr.onerror = function(){ toast("no pude leer el fichero", true); };
  fr.readAsDataURL(fichero);
}
/* Pegar una imagen del portapapeles en cualquier parte de la pagina. No se
   captura el pegado de TEXTO: dentro del textarea tiene que seguir pegando
   texto como en cualquier editor. */
document.addEventListener("paste", function(e){
  var items = (e.clipboardData && e.clipboardData.items) || [];
  for(var i = 0; i < items.length; i++){
    if(items[i].type && items[i].type.indexOf("image/") === 0){
      var f = items[i].getAsFile();
      if(f){ e.preventDefault(); subirImagen(f); }
      return;
    }
  }
});

/* =====================================================================
   EVENTOS: el documento se mueve solo
   ===================================================================== */
function indiceDe(id){
  for(var i = 0; i < S.bloques.length; i++) if(S.bloques[i].id === id) return i;
  return -1;
}
function donde(reg){
  if(reg.al_principio) return 0;
  if(reg.tras){
    var i = indiceDe(String(reg.tras));
    if(i < 0) return -1;
    return i + 1;
  }
  return S.bloques.length;
}
/* Aplica UNA linea del diario sobre la lista local. Es la misma operacion que
   el proceso ya aplico en disco (el evento sale DESPUES del fsync), no una
   adivinanza: por eso no hace falta pedirle nada al servidor. */
function aplicarOp(reg){
  if(!reg || !reg.op) return true;
  var op = reg.op, id = String(reg.id || ""), i;
  if(op === "crear" || op === "respetado"){
    if(op === "respetado" && id){
      destello(id);
      toast("la IA quiso cambiar un bloque tuyo y lo ha respetado");
    }
    return true;
  }
  if(op === "aniadir"){
    var b = reg.bloque || {};
    if(!b.id || indiceDe(b.id) >= 0) return true;      /* ya lo teniamos */
    var pos = donde(reg);
    if(pos < 0) return false;
    var nuevo = {id: b.id, tipo: b.tipo, texto: b.texto || "",
                 fijado: !!b.fijado, origen: b.origen || "ia",
                 t: b.t || 0, meta: b.meta || {},
                 adjunto: (b.meta && (b.meta.adjunto || b.meta.png)) || "",
                 jornada: (b.meta && b.meta.jornada) || "",
                 aviso: "", busca: String(b.texto || "").toLowerCase()};
    S.bloques.splice(pos, 0, nuevo);
    S.nuevos[b.id] = 1;
    return true;
  }
  i = indiceDe(id);
  if(i < 0) return op === "borrar";      /* borrar lo que no teniamos: nada que hacer */
  if(op === "editar"){
    if(reg.texto !== null && reg.texto !== undefined){
      S.bloques[i].texto = String(reg.texto);
      S.bloques[i].busca = String(reg.texto).toLowerCase();
    }
    if(reg.meta){
      S.bloques[i].meta = reg.meta;
      S.bloques[i].adjunto = reg.meta.adjunto || reg.meta.png || "";
      S.bloques[i].jornada = reg.meta.jornada || S.bloques[i].jornada;
    }
    if(reg.quien === "duenio"){ S.bloques[i].fijado = true; S.bloques[i].origen = "duenio"; }
    if(!editando(id)) destello(id);
    return true;
  }
  if(op === "mover"){
    var b2 = S.bloques.splice(i, 1)[0];
    var pos2 = donde(reg);
    if(pos2 < 0){ S.bloques.splice(i, 0, b2); return false; }
    S.bloques.splice(pos2, 0, b2);
    return true;
  }
  if(op === "borrar"){
    if(editando(id)){
      encolar(S.bloques[i], "la IA borro este bloque mientras lo corregias");
      return true;
    }
    S.bloques.splice(i, 1);
    return true;
  }
  if(op === "fijar"){
    S.bloques[i].fijado = !!reg.fijado;
    return true;
  }
  return false;
}

function esNuestroDiario(ruta){
  return !!D.diario && String(ruta || "") === D.diario;
}
function esTranscripcion(ruta){
  return String(ruta || "").indexOf(D.transcripcion) >= 0;
}

function alLlegarEvento(e){
  var d;
  try{ d = JSON.parse(e.data); }
  catch(err){ return; }               /* un frame ilegible no tumba la pagina */
  if(esTranscripcion(d.ruta)){
    S.ultimoTrozo = Date.now();
    refrescarDirecto();
  }
  if(esNuestroDiario(d.ruta)){
    if(aplicarOp(d.registro)) pintar();
    else desincronizado();
  }
}

var desincronizadoYa = false;
function desincronizado(){
  if(desincronizadoYa) return;
  desincronizadoYa = true;
  banner("Llego un cambio del documento que esta pagina no supo aplicar: lo " +
         "que ves puede estar incompleto.", false, "recargar",
         function(){ window.location.reload(); }, "sync");
}

function conectar(){
  /* El reintento programado se cancela AQUI: si no, una reconexion a mano y
     la del temporizador acaban abriendo dos EventSource contra el mismo
     servidor (dos colas, dos veces cada evento). */
  if(S.tReintento){ clearTimeout(S.tReintento); S.tReintento = null; }
  if(S.es){ S.es.close(); S.es = null; }
  var es = new EventSource(C.eventos);
  S.es = es;
  es.onopen = function(){
    if(S.es !== es) return;
    S.conectado = true;
    S.espera = 0;
    quitarBanner("conexion");
    refrescarDirecto();
  };
  es.addEventListener("clase.entrada", alLlegarEvento);
  es.addEventListener("clase.json", alLlegarEvento);
  es.onerror = function(){
    /* EventSource reconecta solo, pero con SU ritmo y sin decir nada. Aqui se
       cierra y se reintenta con retroceso exponencial CONTANDOLO en pantalla:
       una pagina que parece viva y esta muerta es el peor fallo posible en un
       cuaderno que se mira mientras te dan clase.
       El error de un EventSource que ya NO es el nuestro (lo cerro conectar()
       o apagar()) no programa nada: seria una segunda reconexion. */
    if(S.es !== es) return;
    S.conectado = false;
    es.close();
    S.es = null;
    S.espera = S.espera ? Math.min(S.espera * 2, 30000) : 2000;
    S.reintentoEn = Date.now() + S.espera;
    banner(textoReconexion(), false, "reintentar ahora",
           function(){ reintentarYa(); }, "conexion");
    if(S.tReintento) clearTimeout(S.tReintento);
    S.tReintento = setTimeout(conectar, S.espera);
    refrescarDirecto();
  };
}
/* O ES UN RELOJ DE VERDAD O NO DICE SEGUNDOS. El banner ponia "Reintentando
   en 2 s" y ahi se quedaba: un numero congelado en una pagina que ya parece
   parada es exactamente la mentira que esta pagina no puede contar. Se
   recalcula del reloj (S.reintentoEn) y lo repinta el mismo tic de un segundo
   que refresca la barra de directo -- sin temporizador nuevo, porque cada
   temporizador que se enciende hay que acordarse de apagarlo en apagar(). */
function textoReconexion(){
  var s = Math.max(0, Math.ceil((S.reintentoEn - Date.now()) / 1000));
  return "Se corto la conexion con Cognia. " +
    (s ? "Reintentando en " + s + " s. " : "Reintentando ahora mismo. ") +
    "Lo que estes escribiendo no se pierde.";
}
function refrescarCuenta(){
  if(claveBanner !== "conexion" || !textoBanner || $("#banner").hidden) return;
  textoBanner.textContent = textoReconexion();
}
function reintentarYa(){
  /* Dos clics seguidos en el boton del banner son un solo reintento: si ya
     hay un EventSource vivo (o conectando), no se abre otro. */
  if(S.es) return;
  S.espera = 0;
  conectar();
}

/* --------- la barra de directo --------- */
function humano(ms){
  var s = Math.max(0, Math.round(ms / 1000));
  if(s < 60) return s + " s";
  if(s < 3600) return Math.floor(s / 60) + " min " + (s % 60) + " s";
  return Math.floor(s / 3600) + " h " + Math.floor((s % 3600) / 60) + " min";
}
function refrescarDirecto(){
  var punto = $("#punto"), txt = $("#rec-txt");
  refrescarCuenta();
  if(!S.conectado){
    punto.className = "";
    txt.textContent = "sin conexion";
  } else if(S.grabando){
    punto.className = "vivo";
    txt.textContent = "grabando" + (S.materiaViva ? " " + S.materiaViva : "");
  } else {
    punto.className = "espera";
    txt.textContent = "conectado (no se esta grabando)";
  }
  var t = $("#trozo");
  if(!S.ultimoTrozo){
    t.textContent = "todavia no hay ningun trozo transcrito";
  } else {
    t.textContent = "el ultimo trozo cerro hace " + humano(Date.now() - S.ultimoTrozo) +
      " (se cierra uno cada " + Math.round(D.segundos_trozo) +
      " s y luego hay que transcribirlo)";
  }
}
/* El setInterval llama al que PIDE el estado, no al que pinta: pintar con un
   objeto vacio es como se rompen los listeners (REGLA 6 de la casa). */
function pedirEstado(){
  fetch(C.estado, {headers: {"X-Cognia-Token": C.token}})
    .then(function(r){ return r.json(); })
    .then(function(j){
      if(!j || typeof j !== "object") return;
      S.grabando = !!j.grabando;
      S.materiaViva = j.materia || "";
      refrescarDirecto();
    })
    .catch(function(){ /* el SSE ya dice si hay conexion: aqui no se duplica */ });
}

/* =====================================================================
   ARRANQUE
   ===================================================================== */
(function materias(){
  var sel = $("#sel-materia"), lista = D.materias || [], i;
  if(!lista.length){
    var o = document.createElement("option");
    o.value = "";
    o.textContent = "(sin documentos)";
    sel.appendChild(o);
  }
  for(i = 0; i < lista.length; i++){
    var op = document.createElement("option");
    op.value = lista[i];
    op.textContent = lista[i];
    if(lista[i] === D.materia) op.selected = true;
    sel.appendChild(op);
  }
  sel.onchange = function(){
    /* Cambiar de documento es IRSE de esta pagina: primero se cierra (y se
       guarda) lo que este abierto, y si el guardado no pudo, no se va. */
    var destino = sel.value;
    cerrarEditor(true).then(function(){
      if(S.editando){
        sel.value = S.materia;
        toast("no pude guardar lo que estas corrigiendo: no cambio de documento", true);
        return;
      }
      window.location.search = "?t=" + encodeURIComponent(C.token) +
        "&materia=" + encodeURIComponent(destino);
    });
  };
})();

$("#buscar").oninput = function(){ S.q = $("#buscar").value.trim(); pintar(); };
$("#b-imprimir").onclick = function(){
  /* Se imprime DESPUES de cerrar: con el editor abierto lo que sale en la
     hoja es el markdown crudo dentro de una caja. */
  cerrarEditor(true).then(function(){ window.print(); });
};
$("#b-md").onclick = function(){
  accion({accion: "markdown", materia: S.materia})
    .then(function(j){ bajarMarkdown(j.markdown); })
    .catch(function(){
      bajarMarkdown(D.markdown);
      toast("el servidor no contesto: te bajaste el markdown de cuando se abrio la pagina", true);
    });
};
function bajarMarkdown(texto){
  var blob = new Blob([String(texto || "")], {type: "text/markdown;charset=utf-8"});
  var a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = (S.materia || "documento") + ".md";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(function(){ URL.revokeObjectURL(a.href); }, 4000);
}
$("#b-parrafo").onclick = function(){ aniadir("parrafo", ""); };
$("#b-titulo").onclick = function(){ aniadir("subtitulo", ""); };
$("#b-lista").onclick = function(){ aniadir("lista", "- "); };
$("#b-formula").onclick = insertarFormula;
$("#b-grafica").onclick = insertarGrafica;
$("#b-imagen").onclick = insertarImagen;
$("#b-tabla").onclick = function(){
  accion({accion: "tabla", materia: S.materia, filas: 3, columnas: 3, tras: tras()})
    .then(function(j){ adoptar(j.bloques); })
    .catch(function(e){ toast("no se pudo insertar la tabla: " + e.message, true); });
};
/* Lo que se aplazo por no romper una seleccion se pinta en cuanto el duenio
   la suelta: sin esto un bloque podria quedarse viejo hasta el siguiente
   evento, que en un cuaderno parado no llega nunca. */
document.addEventListener("selectionchange", function(){
  var k, hay = false;
  for(k in S.aplazados){ hay = true; break; }
  if(!hay) return;
  var sel = window.getSelection ? window.getSelection() : null;
  if(sel && !sel.isCollapsed) return;
  pintar();
});
document.addEventListener("keydown", function(e){
  if(e.key === "/" && document.activeElement !== $("#buscar") && !S.editando){
    e.preventDefault();
    $("#buscar").focus();
  }
  if(e.key === "Escape" && !S.editando){ cerrarPanel(); }
});
(D.avisos || []).forEach(function(a){ toast(a, true); });
$("#pie").textContent = (D.materia || "sin materia") + " -- generado el " + D.generado;
$("#pie2").textContent = "Se graba desde el CLI de Cognia. Lo que corriges queda fijado.";

/* NADA DE ESTA PAGINA PUEDE QUEDAR VIVO CUANDO LA PESTANIA SE VA. Un
   EventSource abierto deja un hilo del servidor esperando (y su cola
   creciendo), y los intervalos siguen pidiendo estado a un servidor que ya no
   mira nadie. Encender y apagar estan juntos a proposito: cada temporizador
   que se crea aqui tiene que poder pararse ahi. */
function apagar(){
  if(S.es){ S.es.close(); S.es = null; }
  if(S.tReintento){ clearTimeout(S.tReintento); S.tReintento = null; }
  if(S.tDirecto){ clearInterval(S.tDirecto); S.tDirecto = null; }
  if(S.tEstado){ clearInterval(S.tEstado); S.tEstado = null; }
  if(tToast){ clearTimeout(tToast); tToast = null; }
  S.conectado = false;
}
function encender(){
  apagar();
  S.tDirecto = setInterval(refrescarDirecto, 1000);
  S.tEstado = setInterval(pedirEstado, 10000);
  pedirEstado();
  conectar();
}
window.addEventListener("pagehide", apagar);
/* Volver "atras" restaura la pagina del bfcache con todo apagado: sin esto se
   queda muda pareciendo viva, que es justo lo que no puede pasar. */
window.addEventListener("pageshow", function(e){ if(e.persisted) encender(); });
/* Y si el duenio cierra con el editor a medias, pregunta el navegador: lo
   unico que esta pagina no puede hacer es perder lo tecleado. */
function hayCambioSinGuardar(){
  return !!(S.pendiente || (S.editando && S.area && S.area.value !== S.original));
}
window.addEventListener("beforeunload", function(e){
  if(!hayCambioSinGuardar()) return;
  e.preventDefault();
  e.returnValue = "";
});

pintar();
refrescarDirecto();
encender();
</script></body></html>"""


# Lo que un literal JSON NO puede llevar crudo dentro de un <script>. Copiado
# de vista.py a proposito: es la MISMA regla y tiene que decir lo mismo en las
# dos paginas. "<" entero (no solo "</"), porque "<!--" y "<script" meten al
# tokenizador de HTML en 'script data escaped' (WHATWG 13.2.5.15) y desde ahi
# el </script> de la plantilla ya no cierra nada; y U+2028/U+2029 porque son
# terminadores de LINEA para JavaScript y json.dumps(ensure_ascii=False) los
# deja crudos -- los dos fallos acaban igual, con la pagina muda.
_ESCAPES_SCRIPT = (("<", "\\u003c"),
                   ("\u2028", "\\u2028"),
                   ("\u2029", "\\u2029"))


def _escapar_para_script(texto: str) -> str:
    """Un JSON ya serializado, listo para meter dentro de un <script>."""
    for malo, bueno in _ESCAPES_SCRIPT:
        texto = texto.replace(malo, bueno)
    return texto


def _ctx_para_pagina(ctx) -> dict:
    """Las URLs que la pagina necesita, con el token ya puesto donde toca.

    Sale del ctx de `servidor_vivo.fijar_pagina` ({"base","token","puerto",
    "eventos","estado","adj"}) y se le aniade "accion", la puerta de
    escritura: mientras el transporte no la tenga, apunta a RUTA_ACCION y el
    primer intento de guardar levanta el banner de solo lectura -- que es la
    verdad, y es mejor que un boton que no hace nada.
    """
    ctx = dict(ctx or {})
    return {"eventos": str(ctx.get("eventos") or "/eventos"),
            "estado": str(ctx.get("estado") or "/estado"),
            "adj": str(ctx.get("adj") or "/adj"),
            "accion": str(ctx.get("accion") or RUTA_ACCION),
            "token": str(ctx.get("token") or "")}


def render_html(datos, ctx=None, titulo: str = "Cuaderno vivo") -> str:
    """La pagina entera. `datos` es lo que devuelve construir().

    UNA sola pasada de sustitucion: encadenar .replace() deja que lo ya
    sustituido se reinterprete, y un titulo que contuviera "__DATOS__" se
    comeria el JSON entero (el bug que ya se pago en flujoteca_view).
    """
    if not isinstance(datos, dict):
        raise TypeError("render_html espera el dict de construir(), no %r"
                        % type(datos))
    datos = dict(datos)
    datos.setdefault("bloques", [])
    datos.setdefault("materias", [])
    datos.setdefault("materia", "")
    datos.setdefault("avisos", [])
    datos.setdefault("markdown", "")
    datos.setdefault("diario", "")
    datos.setdefault("transcripcion", alm.TRANSCRIPCION)
    datos.setdefault("segundos_trozo", SEGUNDOS_TROZO_POR_DEFECTO)
    datos.setdefault("ultimo_trozo", 0.0)
    datos.setdefault("ahora", time.time())
    datos.setdefault("generado", _sello())

    trozos = {
        "__TITULO__": _html.escape(str(titulo or "Cuaderno vivo")),
        "__DATOS__": _escapar_para_script(json.dumps(datos, ensure_ascii=False)),
        "__CTX__": _escapar_para_script(
            json.dumps(_ctx_para_pagina(ctx), ensure_ascii=False)),
        "__TIPOS__": _escapar_para_script(
            json.dumps([list(t) for t in TIPOS_VISIBLES], ensure_ascii=False)),
        "__CEREBRO__": _cerebro_inline(),
    }
    return re.sub("__TITULO__|__DATOS__|__CTX__|__TIPOS__|__CEREBRO__",
                  lambda m: trozos[m.group(0)], _HTML)


def render(ctx) -> str:
    """EL GANCHO de `servidor_vivo.fijar_pagina`: `render(ctx) -> str`.

    La materia se elige con `?materia=` en la URL, asi que se lee de
    `ctx["query"]` si el transporte la pasa y, si no, de `ctx["materia"]`.
    Sin ninguna de las dos se abre la primera materia con documento.
    """
    ctx = dict(ctx or {})
    query = dict(ctx.get("query") or {})
    materia = ctx.get("materia") or query.get("materia") or ""
    datos = construir(materia)
    tit = "Cuaderno vivo" + (" -- " + datos["materia"] if datos["materia"] else "")
    return render_html(datos, ctx=ctx, titulo=tit)


# ── Puertas de diagnostico y de disco ────────────────────────────────────────

def estado(materia=None) -> dict:
    """Que sabe hacer esta pagina AHORA, sin levantar nada.

    Es la puerta que exige CLAUDE.md para una capa sin uso directo: dice que
    materias hay, cuantos bloques tiene la abierta, que acciones acepta la
    puerta de escritura, si las formulas y las graficas se pueden dibujar en
    esta maquina y cual fue la ultima degradacion. "No lo cablearon" y "se
    rompio" tienen que verse distinto desde fuera.
    """
    datos = construir(materia)
    try:
        from cognia.clases import mates
        mates_ok, mates_motivo = mates.disponible()
    except Exception as exc:
        mates_ok, mates_motivo = False, "%s: %s" % (type(exc).__name__, exc)
    return {
        "materias": datos["materias"],
        "materia": datos["materia"],
        "bloques": len(datos["bloques"]),
        "fijados": datos["n_fijados"],
        "acciones": sorted(ACCIONES),
        "ruta_accion": RUTA_ACCION,
        "mates": {"ok": bool(mates_ok), "motivo": mates_motivo},
        "segundos_trozo": _segundos_trozo(),
        "ultimo_trozo": datos["ultimo_trozo"],
        "avisos": datos["avisos"],
        "ultimo_fallo": ultimo_fallo(),
    }


def export(path=None, materia=None, open_browser: bool = True) -> Path:
    """Escribe la pagina a disco y (por defecto) la abre.

    OJO A LO QUE ES Y A LO QUE NO ES: abierta con `file://` la pagina PINTA el
    documento pero no recibe eventos ni puede escribir -- un origen opaco no
    puede abrir un EventSource ni hacer fetch (por eso existe
    `servidor_vivo.py`). Sirve para mirar el resultado y para depurar el HTML
    sin levantar nada; el cuaderno vivo de verdad se abre desde el REPL.
    """
    datos = construir(materia)
    destino = Path(path).expanduser() if path else (Path.home() / ".cognia"
                                                    / "cuaderno_vivo.html")
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(render_html(datos), encoding="utf-8")
    if open_browser:
        import webbrowser
        try:
            webbrowser.open(destino.as_uri())
        except Exception as exc:
            # El fichero YA esta escrito: que no haya navegador no puede
            # parecer que la exportacion fallo.
            log.warning("clases.vista_viva: no pude abrir el navegador: %s", exc)
    return destino


if __name__ == "__main__":
    import sys
    if "--estado" in sys.argv:
        print(json.dumps(estado(), ensure_ascii=False, indent=2, default=str))
    else:
        ruta = export(open_browser="--no-open" not in sys.argv)
        print("cuaderno vivo -> %s" % ruta)
