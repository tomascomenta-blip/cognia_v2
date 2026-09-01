# -*- coding: utf-8 -*-
"""
cognia/busqueda_imagenes.py -- buscar imagenes para el cuaderno de clase.

Hermano de busqueda_web.py: mismo molde (APIs JSON, cero raspado de HTML, cero
clave de API, cada fallo con su causa en el log), pero devolviendo METADATOS DE
IMAGEN en vez de enlaces. Aqui NO se descarga nada: bajar el fichero es trabajo
de cognia.clases.almacen.descargar_adjunto, que ya comprueba esquema,
Content-Type y tamanio. Este modulo solo dice QUE imagenes hay y DE QUIEN son.

POR QUE LA ATRIBUCION VIAJA CON EL RESULTADO Y NO ES UN EXTRA
------------------------------------------------------------
El cuaderno de clases se exporta a PDF. Una imagen CC BY-SA pegada en un PDF
sin autor ni licencia deja de estar licenciada: es una infraccion, no un
descuido de formato. Por eso `autor`, `licencia` y `url_pagina` son parte del
resultado y no se pueden perder por el camino, y por eso un resultado al que le
falta licencia o pagina de origen se DESCARTA en vez de colarse a medias (ver
_es_atribuible). Cuando lo unico que falta es el autor (tipico en dominio
publico), el resultado pasa pero marcado con atribucion_completa=False, para
que quien lo pinte pueda avisar en vez de inventarse un nombre.

TRES DATOS MEDIDOS QUE AHORRAN UNA TARDE
----------------------------------------
1. LA MINIATURA HAY QUE PEDIRSELA A LA API. Con iiurlwidth=800 la respuesta
   trae `thumburl` ya fabricada; construirla a mano
   (.../thumb/<a>/<ab>/<fichero>/800px-<fichero>) da HTTP 400 en buena parte de
   los ficheros -- el nombre de la miniatura NO es una funcion del ancho que
   pides. Medido el 2026-08-31 pidiendo 800: la respuesta trae thumbwidth 800
   y una url que dice ".../960px-Mitocondria_11.jpg" (Wikimedia redondea a sus
   anchos de siempre), y para un fichero mas pequenio que 800 devuelve el
   original con utm_content=thumbnail_unscaled, sin /thumb/ ni Npx- ninguno.
   Se usa la thumburl que devuelve la API, tal cual, con sus parametros utm.
   EL HOST DE ESA URL NO ES ESTABLE Y NO HAY QUE DARLO POR SUPUESTO: medido el
   2026-08-31, las miniaturas escaladas llegan por thumb.wikimedia.org y los
   originales sin escalar por upload.wikimedia.org, en la MISMA respuesta.
   Las dos se descargan igual de bien (comprobado con almacen.descargar_adjunto:
   http/https, Content-Type image/*, 200 sin redireccion), asi que el host es
   asunto de Wikimedia; lo unico que aqui hay que hacer es no clavarlo -- ni en
   el codigo ni en un test (ver _clave, y el metodo del cuaderno: lo que se
   comprueba es que la imagen se pueda BAJAR, no de que maquina sale).
2. EL TIMEOUT DE 10 s DE busqueda_web.py NO SIRVE AQUI. La primera consulta a
   Commons en frio se pasa de 10 s con regularidad (la busqueda full-text mas
   el imageinfo de N ficheros es bastante mas cara que un list=search pelado).
   TIMEOUT propio de 28 s.
3. SIN User-Agent IDENTIFICABLE, Wikimedia DEVUELVE 429 al encadenar
   peticiones. Es la misma leccion que el 403 de Wikipedia en busqueda_web,
   pero peor: aqui el bloqueo aparece a la tercera o cuarta consulta, asi que
   en pruebas sueltas parece que funciona.

DOS FUENTES, EN CASCADA A PROPOSITO
-----------------------------------
busqueda_web.py reparte el cupo entre sus fuentes porque alli una fuente laxa
(Wikipedia) se lo quedaba todo. Aqui la cascada SI es lo correcto: Commons es
la fuente principal porque cada fichero trae autor y licencia estructurados en
extmetadata, mientras que en Openverse la calidad de la atribucion depende del
proveedor original. Openverse entra para COMPLETAR el cupo que Commons no
llene, o entero si Commons falla. Las dos se solapan (Openverse indexa
Wikimedia): la deduplicacion compara el FICHERO y no la url, porque la MISMA
imagen llega como upload.wikimedia.org/.../9/95/fichero.jpg desde Openverse y
como thumb.wikimedia.org/.../thumb/9/95/fichero.jpg/960px-fichero.jpg?utm_...
desde Commons -- distinta ruta Y distinto host (ver _clave).

    from cognia.busqueda_imagenes import buscar
    for r in buscar("mitocondria", 5):
        print(r["titulo"], r["url_imagen"], r["atribucion"])

Puerta de diagnostico (sin pasar por el CLI):

    venv312\\Scripts\\python.exe -m cognia.busqueda_imagenes "mitocondria" 5
"""

from __future__ import annotations

import html
import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

# El contacto tiene que ser REAL y alcanzable: la politica de user-agent de
# Wikimedia pide poder avisar a un humano antes de bloquear. Se pone la pagina
# publica del proyecto (la de pyproject.toml) y no el correo del duenio.
USER_AGENT = ("Cognia/1.0 (cuaderno de clases; "
              "+https://github.com/tomascomenta-blip/cognia_v2)")

# Ver punto 2 del docstring: 10 s (el de busqueda_web) falla en frio.
TIMEOUT = 28

# Ancho de la miniatura que se le pide a Commons. 800 px es lo que la vista del
# cuaderno embebe sin recortar; pedir el original (a veces 4000 px y varios MB)
# haria que descargar_adjunto se choque contra su tope de tamanio.
ANCHO_MINIATURA = 800

# Topes de las dos APIs para peticiones anonimas. Pedir mas no da mas: Commons
# recorta a 50 y Openverse contesta 400 por encima de 20.
_TOPE_COMMONS = 50
_TOPE_OPENVERSE = 20


class ErrorBusquedaImagenes(RuntimeError):
    """
    No se pudo buscar en NINGUNA fuente.

    Se lanza en vez de devolver [] porque "no hay imagenes de esto" y "no hubo
    forma de preguntar" son dos cosas distintas para quien esta escribiendo un
    apunte, y una lista vacia muda las confunde -- que es el modo de fallo mas
    caro de este repo. Cero resultados con las fuentes vivas SI devuelve [].
    """


def _limpiar(texto: str | None) -> str:
    """
    Texto plano a partir de un valor de extmetadata.

    El campo Artist de Commons es HTML de verdad: llega como
    '<bdi><a href="..." title="...">Laboratoires Servier</a></bdi>'. Sin
    limpiarlo, el autor que acabaria en el PIE DE FOTO del PDF seria una
    etiqueta. Acepta None porque un extmetadata puede traer la clave con valor
    nulo y reventar aqui tumbaria la fuente entera por un solo fichero.
    """
    if not texto:
        return ""
    texto = re.sub(r"<[^>]+>", " ", texto)
    texto = html.unescape(texto)
    return re.sub(r"\s+", " ", texto).strip()


def _pedir_json(url: str, fuente: str) -> dict:
    """
    GET + json.load, traduciendo TODO fallo a un mensaje que se pueda leer.

    Los errores de urllib no sirven para ensenar: 'HTTP Error 429: Too Many
    Requests' no dice a quien pasa ni que hacer. Se lanza ErrorBusquedaImagenes
    con la fuente y la accion, y quien llama decide si sigue con la otra fuente.
    """
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as respuesta:
            datos = json.load(respuesta)
    except urllib.error.HTTPError as e:
        if e.code == 429:
            detalle = ("demasiadas peticiones (HTTP 429): esta limitando el "
                       "ritmo, esperar unos minutos antes de reintentar")
        elif e.code in (403, 401):
            detalle = (f"acceso rechazado (HTTP {e.code}): revisar el "
                       f"User-Agent, ahora es {USER_AGENT!r}")
        else:
            detalle = f"HTTP {e.code} {e.reason}"
        raise ErrorBusquedaImagenes(f"{fuente}: {detalle}") from e
    except TimeoutError as e:
        raise ErrorBusquedaImagenes(
            f"{fuente}: no respondio en {TIMEOUT} s") from e
    except urllib.error.URLError as e:
        # URLError envuelve al timeout del socket y al fallo de DNS. El .reason
        # es lo unico util que trae; el str() pelado sale como
        # '<urlopen error [Errno 11001] getaddrinfo failed>'.
        if isinstance(e.reason, TimeoutError):
            detalle = f"no respondio en {TIMEOUT} s"
        else:
            detalle = f"no se pudo conectar ({e.reason})"
        raise ErrorBusquedaImagenes(f"{fuente}: {detalle}") from e
    except ValueError as e:            # json.JSONDecodeError hereda de esta
        raise ErrorBusquedaImagenes(
            f"{fuente}: respondio algo que no es JSON ({e})") from e
    _sin_error_de_api(datos, fuente)
    return datos


def _sin_error_de_api(datos, fuente: str) -> None:
    """
    Un HTTP 200 de MediaWiki puede ser un error, y hay que decirlo.

    Cuando la consulta rompe el parser de la API (un gsrsearch con comillas sin
    cerrar, un parametro que dejo de existir), MediaWiki NO devuelve un codigo
    HTTP de error: contesta 200 con el cuerpo {"error": {"code": ..., "info":
    ...}} y sin la clave "query". Mirando solo el codigo HTTP, parsear_commons
    ve una respuesta sin paginas, devuelve [] y el aviso acaba diciendo
    "commons no aporto imagenes" -- una MENTIRA, porque la fuente si contesto y
    lo que dijo fue que la consulta esta mal. Es el vacio silencioso que este
    modulo existe para no repetir. `info` viene con HTML (lleva enlaces a la
    documentacion), asi que pasa por _limpiar antes de ir al mensaje.
    """
    if not isinstance(datos, dict):
        return
    error = datos.get("error")
    if isinstance(error, dict):
        codigo = _limpiar(str(error.get("code") or "")) or "sin codigo"
        info = _limpiar(str(error.get("info") or "")) or "sin detalle"
        raise ErrorBusquedaImagenes(
            f"{fuente}: la API rechazo la consulta (HTTP 200 con error "
            f"{codigo}): {info}")
    if isinstance(error, str) and error.strip():
        raise ErrorBusquedaImagenes(
            f"{fuente}: la API rechazo la consulta (HTTP 200 con error): "
            f"{_limpiar(error)}")


def _es_atribuible(resultado: dict) -> bool:
    """
    Un resultado sin licencia o sin pagina de origen NO entra en el cuaderno.

    Sin `url_pagina` no hay a donde apuntar para justificar el uso, y sin
    `licencia` no se sabe siquiera si se puede usar. Falta de `autor` NO
    descarta (el dominio publico no siempre lo trae): eso se marca con
    atribucion_completa=False y se deja pasar.
    """
    return bool(resultado.get("url_imagen")
                and resultado.get("url_pagina")
                and resultado.get("licencia"))


def _resultado(titulo, url_imagen, url_pagina, autor, licencia,
               ancho, alto, fuente, licencia_url="") -> dict:
    """
    Arma el dict con la linea de atribucion ya redactada.

    LIMPIA AQUI, NO EN CADA PARSER. Este es el unico sitio por el que pasan
    TODAS las fuentes, y el texto que sale de aqui acaba en el cuaderno del
    duenio y en su exportacion a PDF. Cuando la limpieza vivia solo en la rama
    de Commons, el titulo, el autor y la atribucion de Openverse entraban con
    el HTML del proveedor original tal cual -- exactamente el fallo que
    _limpiar existe para evitar. Poniendolo en el cuello de botella, una fuente
    nueva (ver FUENTES) nace limpia sin que nadie se acuerde de llamarla.
    Las urls NO se tocan: html.unescape sobre una url la puede romper.
    """
    titulo = _limpiar(titulo)
    autor = _limpiar(autor)
    licencia = _limpiar(licencia)
    partes = [p for p in (titulo, autor, licencia) if p]
    return {
        "titulo":      titulo,
        "url_imagen":  url_imagen,
        "url_pagina":  url_pagina,
        "autor":       autor,
        "licencia":    licencia,
        "licencia_url": licencia_url,
        "ancho":       ancho,
        "alto":        alto,
        "fuente":      fuente,
        # Linea lista para el pie de foto: quien pinte el cuaderno no tiene que
        # saber redactar una atribucion correcta para no meter la pata.
        "atribucion":  " - ".join(partes + [url_pagina]),
        "atribucion_completa": bool(autor and licencia),
    }


# -- Wikimedia Commons -------------------------------------------------------

def _url_commons(consulta: str, n: int) -> str:
    """
    generator=search + prop=imageinfo en UNA peticion.

    generator (y no list=search) porque asi la busqueda alimenta directamente
    al imageinfo: con list=search harian falta dos viajes, y el segundo es el
    caro. gsrnamespace=6 limita a la namespace Fichero, y 'filetype:bitmap'
    deja fuera SVG, PDF, videos y audio -- que la busqueda devuelve mezclados
    y que la vista del cuaderno no sabe embeber.
    """
    busqueda = f"filetype:bitmap {consulta}"
    parametros = {
        "action": "query",
        "format": "json",
        # formatversion=2 devuelve query.pages como LISTA. Con la 1 es un dict
        # indexado por pageid y ademas se pierde el orden de relevancia.
        "formatversion": "2",
        "generator": "search",
        "gsrsearch": busqueda,
        "gsrnamespace": "6",
        "gsrlimit": str(n),
        "prop": "imageinfo",
        "iiprop": "url|size|extmetadata",
        "iiurlwidth": str(ANCHO_MINIATURA),
        # Sin el filtro, extmetadata trae 30 campos por fichero (incluida una
        # tabla HTML entera en Credit) y la respuesta se va a megabytes.
        "iiextmetadatafilter": "Artist|LicenseShortName|LicenseUrl",
    }
    return ("https://commons.wikimedia.org/w/api.php?"
            + urllib.parse.urlencode(parametros))


def parsear_commons(data: dict) -> list[dict]:
    """
    De la respuesta de la API de Commons a la lista de resultados.

    Publica a proposito: es lo unico que puede romperse cuando Wikimedia
    cambie el formato, asi que los tests la ejercitan contra una respuesta REAL
    guardada, sin red de por medio.
    """
    paginas = (data.get("query") or {}).get("pages") or []
    resultados = []
    descartados = 0
    for pagina in paginas:
        info = (pagina.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        # thumburl la fabrica la API (punto 1 del docstring). Si no viniera --
        # pasa con ficheros que no se pueden escalar -- se cae al original,
        # que descargar_adjunto rechazara si se pasa de tamanio; mejor eso que
        # una url inventada que da 400.
        url_imagen = info.get("thumburl") or info.get("url") or ""
        titulo = re.sub(r"^File:", "", pagina.get("title") or "").strip()
        r = _resultado(
            titulo=titulo,
            url_imagen=url_imagen,
            url_pagina=info.get("descriptionurl") or "",
            autor=_limpiar((meta.get("Artist") or {}).get("value")),
            licencia=_limpiar((meta.get("LicenseShortName") or {}).get("value")),
            licencia_url=_limpiar((meta.get("LicenseUrl") or {}).get("value")),
            # El ancho/alto que importa es el de LO QUE SE VA A PEGAR, o sea la
            # miniatura; el del original solo sirve para llevarse un susto al
            # maquetar.
            ancho=info.get("thumbwidth") or info.get("width") or 0,
            alto=info.get("thumbheight") or info.get("height") or 0,
            fuente="commons",
        )
        if not _es_atribuible(r):
            descartados += 1
            continue
        resultados.append(r)
    if descartados:
        logger.warning("Commons: %d resultado(s) descartado(s) por venir sin "
                       "licencia o sin pagina de origen", descartados)
    return resultados


def buscar_commons(consulta: str, n: int) -> list[dict]:
    """Consulta Commons. Lanza ErrorBusquedaImagenes si la fuente falla."""
    n = max(1, min(int(n), _TOPE_COMMONS))
    return parsear_commons(_pedir_json(_url_commons(consulta, n),
                                       "Wikimedia Commons"))


# -- Openverse ---------------------------------------------------------------

def _url_openverse(consulta: str, n: int) -> str:
    """Busqueda anonima de Openverse (la clave solo sube el cupo por hora)."""
    parametros = {
        "format": "json",
        "q": consulta,
        "page_size": str(n),
        # Sin esto entran fotos marcadas como sensibles, y esto acaba en un
        # cuaderno de clase.
        "mature": "false",
    }
    return "https://api.openverse.org/v1/images/?" + urllib.parse.urlencode(parametros)


def _licencia_openverse(item: dict) -> str:
    """
    'by-nc-sa' + '2.0' -> 'CC BY-NC-SA 2.0'.

    Openverse devuelve el codigo en minusculas y la version aparte; pegarlos
    tal cual en un pie de foto ('by-nc-sa') no identifica ninguna licencia.
    """
    codigo = (item.get("license") or "").strip()
    if not codigo:
        return ""
    version = (item.get("license_version") or "").strip()
    if codigo.lower() in ("cc0", "pdm"):
        etiqueta = codigo.upper()
    else:
        etiqueta = "CC " + codigo.upper()
    return f"{etiqueta} {version}".strip()


def parsear_openverse(data: dict) -> list[dict]:
    """De la respuesta de la API de Openverse a la lista de resultados."""
    resultados = []
    descartados = 0
    for item in data.get("results") or []:
        r = _resultado(
            titulo=(item.get("title") or "").strip(),
            # `url` es el fichero original en el proveedor; `thumbnail` es un
            # proxy de la propia API de Openverse, con su cupo por hora: si se
            # pega en el cuaderno, la imagen deja de cargar cuando el cupo se
            # agota.
            url_imagen=item.get("url") or "",
            url_pagina=item.get("foreign_landing_url") or "",
            autor=(item.get("creator") or "").strip(),
            licencia=_licencia_openverse(item),
            licencia_url=item.get("license_url") or "",
            ancho=item.get("width") or 0,
            alto=item.get("height") or 0,
            fuente="openverse",
        )
        # Openverse ya redacta la atribucion en su idioma; se prefiere la suya
        # cuando viene, porque incluye el enlace a la licencia.
        if item.get("attribution"):
            # _limpiar (y no un re.sub de espacios) porque la atribucion de
            # Openverse la escribe el proveedor original: llega con <a href=...>
            # y con entidades HTML, y esta linea es LITERALMENTE el pie de foto
            # que se pega en el cuaderno.
            r["atribucion"] = _limpiar(item["attribution"])
        if not _es_atribuible(r):
            descartados += 1
            continue
        resultados.append(r)
    if descartados:
        logger.warning("Openverse: %d resultado(s) descartado(s) por venir sin "
                       "licencia o sin pagina de origen", descartados)
    return resultados


def buscar_openverse(consulta: str, n: int) -> list[dict]:
    """Consulta Openverse. Lanza ErrorBusquedaImagenes si la fuente falla."""
    n = max(1, min(int(n), _TOPE_OPENVERSE))
    return parsear_openverse(_pedir_json(_url_openverse(consulta, n),
                                         "Openverse"))


# Punto de extension: anadir una fuente es anadir una entrada aqui (y su
# parsear_*). El orden es el orden de la cascada.
FUENTES = {
    "commons":   buscar_commons,
    "openverse": buscar_openverse,
}


def _clave(resultado: dict) -> str:
    """
    Clave de deduplicacion: el FICHERO, no la url con la que llego.

    Openverse indexa Wikimedia, asi que la MISMA imagen llega por dos caminos.
    Quitar solo el query string NO basta y falla justo en el caso mayoritario:
    para todo fichero de mas de ANCHO_MINIATURA px, Commons devuelve la url de
    una MINIATURA, que tiene otra ruta entera --

        commons/thumb/9/95/Mitocondria_11.jpg/960px-Mitocondria_11.jpg  (Commons)
        commons/9/95/Mitocondria_11.jpg                                 (Openverse)

    -- y esa es exactamente la imagen que sale duplicada en el cuaderno. La
    ruta de miniatura de MediaWiki es derivable: es la del original con
    '/thumb/' metido en medio y un segmento '<N>px-<fichero>' pegado al final,
    asi que deshacer esas dos cosas devuelve al fichero de verdad. Se
    des-escapa el porcentaje porque las dos APIs no codifican igual el mismo
    nombre (Mitoc%C3%B4ndria vs Mitocondria con la tilde ya decodificada).

    Y TAMPOCO BASTA CON LA RUTA: HAY QUE NORMALIZAR EL HOST (medido 2026-08-31)
    ----------------------------------------------------------------------
    Wikimedia sirve el MISMO fichero desde mas de un host, y hoy la API de
    Commons devuelve las miniaturas escaladas por uno distinto del original:

        thumb.wikimedia.org/wikipedia/commons/thumb/9/95/X.jpg/960px-X.jpg
        upload.wikimedia.org/wikipedia/commons/9/95/X.jpg

    (thumb.wikimedia.org responde 200 el mismo: no es una redireccion a
    upload, es otro host sirviendo lo mismo). Con el netloc crudo dentro de la
    clave, deshacer el /thumb/ ya no sirve de nada -- las dos claves siguen
    saliendo distintas y la imagen vuelve a entrar DOS VECES en el cuaderno,
    que es justo lo que esta funcion existe para impedir. Se colapsa cualquier
    host de wikimedia.org a uno solo. No se tira el netloc entero porque
    entonces dos ficheros homonimos de fuentes futuras distintas (FUENTES) se
    fundirian en uno, que es el fallo contrario y peor: perder una imagen.
    """
    partes = urllib.parse.urlsplit(resultado.get("url_imagen") or "")
    ruta = partes.path
    if "/thumb/" in ruta:
        ruta = ruta.replace("/thumb/", "/", 1).rsplit("/", 1)[0]
    ruta = urllib.parse.unquote(ruta)
    host = partes.netloc.lower()
    # Sin el punto delante, un dominio 'malwikimedia.org' entraria tambien.
    if host == "wikimedia.org" or host.endswith(".wikimedia.org"):
        host = "wikimedia.org"
    return f"{host}{ruta}".lower()


def buscar_con_avisos(consulta: str, n: int = 8,
                      fuentes: "tuple[str, ...] | None" = None
                      ) -> "tuple[list[dict], list[str]]":
    """
    Como buscar(), pero devolviendo tambien los avisos legibles.

    Existe porque el CLI tiene que poder decir "salieron 3 de Commons,
    Openverse esta caido" en vez de ensenar 3 resultados y callarse. buscar()
    es el atajo para quien solo quiere la lista.

    Lanza ErrorBusquedaImagenes solo si fallan TODAS las fuentes consultadas,
    con el motivo de cada una en el mensaje.
    """
    consulta = (consulta or "").strip()
    if not consulta:
        raise ErrorBusquedaImagenes("busqueda vacia: hace falta que buscar")

    n = max(1, int(n))
    if fuentes is None:
        elegidas = list(FUENTES.items())
    else:
        elegidas = []
        for nombre in fuentes:
            if nombre not in FUENTES:
                logger.warning("Fuente de imagenes desconocida, la ignoro: %s",
                               nombre)
                continue
            elegidas.append((nombre, FUENTES[nombre]))
    if not elegidas:
        raise ErrorBusquedaImagenes(
            "ninguna fuente valida; las que hay: " + ", ".join(FUENTES))

    resultados: list[dict] = []
    vistas: set[str] = set()
    avisos: list[str] = []
    fallos: list[str] = []

    for nombre, funcion in elegidas:
        if len(resultados) >= n:
            break
        try:
            crudos = funcion(consulta, n - len(resultados))
        except ErrorBusquedaImagenes as e:
            # Degradacion que se DICE: sin esto, "Commons caido" y "Commons no
            # tiene nada de esto" se ven igual desde fuera.
            logger.warning("Fuente de imagenes caida: %s", e)
            fallos.append(str(e))
            avisos.append(f"{nombre} fallo: {e}")
            continue
        except Exception as e:                    # noqa: BLE001
            # El fallo que este modulo dice existir para detectar es que una de
            # las dos APIs cambie de formato, y ese NO llega como
            # ErrorBusquedaImagenes: llega como AttributeError o TypeError
            # dentro del parser. Dejarlo subir crudo revienta el cuaderno con
            # un traceback que no dice ni que fuente fue. Se convierte en un
            # aviso que nombra la fuente, el tipo y el sitio (el traceback
            # entero queda en el log via logger.exception), y la cascada sigue
            # con la otra fuente. No se captura BaseException: un Ctrl-C tiene
            # que salir.
            logger.exception("Fuente de imagenes rota (formato inesperado): %s",
                             nombre)
            detalle = (f"{nombre}: respuesta inesperada de la API "
                       f"({type(e).__name__}: {e}); seguramente cambio el "
                       f"formato, revisar parsear_{nombre}")
            fallos.append(detalle)
            avisos.append(f"{nombre} fallo: {detalle}")
            continue
        nuevos = 0
        for r in crudos:
            clave = _clave(r)
            if not clave or clave in vistas:
                continue
            vistas.add(clave)
            resultados.append(r)
            nuevos += 1
            if len(resultados) >= n:
                break
        if nuevos == 0:
            avisos.append(f"{nombre} no aporto imagenes para {consulta!r}")

    if fallos and len(fallos) == len(elegidas):
        raise ErrorBusquedaImagenes(
            "no se pudo buscar imagenes en ninguna fuente. " + " | ".join(fallos))

    if not resultados:
        # No es un error (las fuentes contestaron), pero tampoco puede pasar en
        # silencio: el llamador tiene el motivo en los avisos.
        avisos.append(f"ninguna fuente encontro imagenes para {consulta!r}; "
                      "probar con menos palabras o en ingles")

    return resultados[:n], avisos


def buscar(consulta: str, n: int = 8,
           fuentes: "tuple[str, ...] | None" = None) -> list[dict]:
    """
    Busca imagenes reutilizables y devuelve sus METADATOS (no las descarga).

    Cada dict trae: titulo, url_imagen, url_pagina, autor, licencia, ancho,
    alto -- mas licencia_url, fuente, atribucion (linea lista para el pie de
    foto) y atribucion_completa. `url_imagen` es la miniatura de ANCHO_MINIATURA
    px que devuelve la API, que es lo que hay que pasarle luego a
    cognia.clases.almacen.descargar_adjunto.

    Lanza ErrorBusquedaImagenes si no se pudo consultar ninguna fuente; los
    avisos de degradacion parcial van al log (usar buscar_con_avisos para
    tenerlos en la mano).
    """
    resultados, avisos = buscar_con_avisos(consulta, n, fuentes)
    for aviso in avisos:
        logger.info("busqueda de imagenes: %s", aviso)
    return resultados


def formatear(resultados: list[dict]) -> str:
    """Listado legible para la consola. Lo usa la puerta de diagnostico."""
    if not resultados:
        return "(sin imagenes)"
    lineas = []
    for i, r in enumerate(resultados, 1):
        marca = "" if r["atribucion_completa"] else "  [SIN AUTOR]"
        lineas.append(f"{i}. {r['titulo']}  ({r['ancho']}x{r['alto']}, "
                      f"{r['fuente']}){marca}")
        lineas.append(f"   imagen: {r['url_imagen']}")
        lineas.append(f"   credito: {r['atribucion']}")
    return "\n".join(lineas)


def _main(argv: "list[str] | None" = None) -> int:
    """
    Puerta de diagnostico: dice si la busqueda esta viva y con que config.

    Regla del repo: nada entra sin puerta, aunque sea infraestructura. El
    comando del CLI lo cablea la pieza que usa esto; esta puerta es la que
    permite comprobar la fuente sin arrancar el REPL entero.
    """
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "estado"):
        print("uso: python -m cognia.busqueda_imagenes \"<consulta>\" [n]")
        print(f"fuentes: {', '.join(FUENTES)}")
        print(f"timeout: {TIMEOUT} s | miniatura: {ANCHO_MINIATURA} px")
        print(f"user-agent: {USER_AGENT}")
        return 0
    consulta = argv[0]
    n = int(argv[1]) if len(argv) > 1 else 5
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        resultados, avisos = buscar_con_avisos(consulta, n)
    except ErrorBusquedaImagenes as e:
        print(f"ERROR: {e}")
        return 1
    print(formatear(resultados))
    for aviso in avisos:
        print(f"AVISO: {aviso}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
