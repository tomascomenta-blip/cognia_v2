# -*- coding: utf-8 -*-
"""Las herramientas con las que la IA ESCRIBE en el documento de una materia.

QUE ES ESTO. `cognia/clases/documento.py` es el modelo: bloques ordenados,
diario append-only y la REGLA DE ORO (lo que toca el duenio queda FIJADO y la
IA no lo reescribe, ni lo mueve, ni lo borra). Aqui esta la puerta por la que
el agente lo usa: siete tools que convierten ese modelo en "un Word para la
IA" -- escribir un parrafo, corregirlo, meter una formula dibujada, una
grafica, una imagen o una tabla.

POR QUE SIETE Y NO VEINTITRES (el catalogo tiene techo MEDIDO)
--------------------------------------------------------------
El A/B de este repo (2026-07-25, n=4+4) midio que pasar de 14 a 46 tools baja
el camino feliz de 4,25/5 a 2,5/5: mas herramientas no es mas capacidad, es
mas distraccion. Asi que el conjunto se eligio por lo que es IMPOSIBLE sin el,
no por lo que seria comodo:

  doc_ver ....... sin leer, el modelo escribe a ciegas: no sabe que ids hay,
                  ni cuales estan fijados, ni si ya escribio eso.
  doc_escribir .. la unica forma de aniadir texto (titulo, parrafo, lista,
                  cita, deber, duda, examen: todos los tipos que son SOLO
                  markdown van por aqui con tipo=).
  doc_editar .... corregirse a si misma sin duplicar el documento.
  doc_formula ... un bloque formula necesita meta{latex,png} y una llamada a
                  matplotlib: con doc_escribir saldria texto plano.
  doc_grafica ... idem con meta{expresion,png,parametros}.
  doc_imagen .... idem con meta{adjunto,atribucion} y la copia del fichero.
  doc_tabla ..... idem con meta{cabecera} y la validacion del markdown.

Y lo que se dejo FUERA a proposito: borrar, mover, fijar y desfijar. Reordenar
y tirar apuntes es del duenio (documento.py ya lo expone en SU puerta); darle
a la IA un doc_borrar seria regalarle la forma mas barata de romper la promesa
del producto, y cuesta ademas una linea del catalogo.

LA FAMILIA ES OPT-IN (COGNIA_DOC_TOOLS=1) por lo mismo: solo se anuncia
cuando hay un cuaderno abierto. Ver `cognia/harness/familias.py`.

SOBRE QUE MATERIA SE ESCRIBE
----------------------------
NO se pasa en cada llamada. Un argumento `materia` repetido en siete tools es
un argumento que el modelo se inventa a la tercera vuelta ("Fisica", "fisica",
"Fisica 2") y acaba con los apuntes repartidos en tres documentos que el
duenio no encuentra. Se resuelve por TRES sitios, en este orden:

  1. EL CONTEXTO DE LA EJECUCION -- ctx['materia'] / ctx['materia_documento'],
     o los mismos dentro de ctx['working_memory']. Es lo que sabe la tarea en
     curso y lo que deja la puerta del CLI al abrir el cuaderno.
  2. LA JORNADA VIVA -- `jornada.estado()['materia']` cuando se esta grabando.
     Es el camino que funciona SIN que nadie cablee nada: si el duenio esta
     dando Fisica ahora mismo, los apuntes de este turno son de Fisica.
     Solo cuenta con `grabando`: la ultima jornada CERRADA devuelve la materia
     de la ultima clase del dia, y manana eso escribiria en la equivocada.
  3. COGNIA_DOC_MATERIA -- ULTIMO RECURSO, para pruebas y para forzar el
     documento desde fuera. No es el camino normal: durante un tiempo fue el
     UNICO, y como nadie la ponia las siete tools eran inertes (siempre
     devolvian "no hay ningun documento abierto").

Sin ninguno de los tres las tools no adivinan -- escribir en "la unica
materia que existe" son apuntes reales en un documento que nadie pidio --:
devuelven un error que dice EXACTAMENTE como abrir el documento.

EL FORMATO DE LOS ARGUMENTOS (la regla de oro del protocolo texto)
------------------------------------------------------------------
Por debajo del JSON, una tool recibe UN string y lo parte con
`re.split(r"\\s*\\|\\s*", args, maxsplit=1)`. Aqui el contenido es justo lo que
lleva barras verticales (una tabla markdown) y contrabarras (un LaTeX), asi
que EL CONTENIDO VA SIEMPRE PRIMERO Y ENTERO y las opciones van DETRAS como
`clave=valor` sueltos:

    doc_escribir Hoy hemos visto el MRU tipo=parrafo tras=b0007
    doc_tabla | Magnitud | Unidad |\\n|---|---|\\n| v | m/s | tras=b0003

Ese orden no es un gusto: `tools.armar_args` (el puente del tool-calling
nativo) construye "posicionales unidos por ' | '" y CUELGA las claves al
FINAL, asi que un parser de opciones-delante se descuadraria con el modelo
real. Las claves se reconocen por una lista blanca cerrada (`tipo`, `tras`,
`var`, `desde`, `hasta`, `id`) y solo al final del string: un parrafo que
diga "la formula es v = e/t" no pierde su cola porque `v` no es una clave.

ARGUMENTOS CORTADOS. Un turno que se agota a mitad del JSON deja el contenido
a medias, y la compactacion del historial ha llegado a hacer que el modelo
copie el MARCADOR DE TRUNCADO al disco (medido 2026-08-26). Aqui eso acabaria
DENTRO de los apuntes del duenio, asi que cada escritura mira el marcador y
se niega. La otra mitad (que el bucle rescate el trozo que si llego) esta en
`loop.py`, que no es de este modulo: ver los avisos de la entrega.

Imports PEREZOSOS dentro de cada tool: registrar esto no arrastra matplotlib
ni sympy. Si falta un paquete, el mensaje trae el `pip install` exacto -- lo
que nunca hace es quedarse callado, que es el modo de fallo fichado de la
casa.
"""
from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path

# Variable que dice sobre que documento se escribe cuando NI el ctx NI la
# jornada viva lo dicen. Ultimo recurso a proposito: durante un tiempo fue el
# UNICO camino y, como nadie la ponia, las siete tools eran inertes.
ENV_MATERIA = "COGNIA_DOC_MATERIA"

# Lo que `jornada.estado()` pone en 'materia' mientras no ha clasificado la
# clase en curso. NO es una materia: tomarlo por buena crearia en el cuaderno
# del duenio un documento llamado "(sin clasificar aun)".
_MATERIA_SIN_CLASIFICAR = "(sin clasificar aun)"

# Por que fallo el ultimo intento de mirar la jornada viva (import roto, disco
# ilegible). Se ensenia DENTRO del error de la tool: en esta casa "no lo
# cablearon" y "se rompio" no pueden verse igual desde afuera, y un fallo mudo
# aqui se leeria como "no hay clase" cuando en realidad la hay.
_FALLO_JORNADA = {"motivo": ""}

# Las opciones (`tipo=`, `tras=`, `var=`, `desde=`, `hasta=`, `id=`) se leen
# del FINAL del string y solo si la clave esta en la lista blanca que pasa
# cada tool: es lo que permite que el contenido lleve un "v = e/t" sin que el
# parser se coma la cola del parrafo.
_RE_CLAVE_FINAL = re.compile(r"(?:^|\s)([a-z_]+)\s*=\s*([^\s|]*)\s*$")

# Los tipos que doc_escribir acepta: los que son SOLO markdown. Los otros
# cuatro tienen tool propia porque necesitan meta y un render.
_TIPOS_TEXTO = ("parrafo", "titulo", "subtitulo", "lista", "cita", "deber",
                "duda", "examen")
_TOOL_DEL_TIPO = {"formula": "doc_formula", "grafica": "doc_grafica",
                  "imagen": "doc_imagen", "tabla": "doc_tabla"}

# El marcador que la compactacion del historial mete en los argumentos largos
# (loop._MARCA_ARG_TRUNCADO). Se busca el trozo estable, no la cadena entera
# con sus puntos suspensivos unicode: el modelo lo copia re-escrito a mano.
_MARCA_TRUNCADO = "(argumento truncado"

# Cuanto se ensenia de cada bloque en el indice y cuanto en total. El techo
# existe porque un documento de un trimestre no cabe en un turno: se recorta y
# se DICE como pedir el tramo que falta, en vez de que el aci_trim generico se
# coma el medio y el modelo edite ids que no vio.
_ANCHO_LINEA = 90
_TOPE_VISTA = 4000
_TOPE_BLOQUE = 2000


# ── Errores que ensenian ─────────────────────────────────────────────────────

class _Rechazo(Exception):
    """Un error que el MODELO tiene que leer y corregir, no una traza.

    Existe para que el cuerpo de cada tool sea plano (validar y seguir) y el
    mensaje suba entero al RESULTADO ... ERROR. Nada de esto es excepcional
    para el proceso: un id mal escrito es el dia a dia de un agente.
    """


def _ok(nombre: str, mensaje: str) -> str:
    return "RESULTADO %s OK: %s" % (nombre, mensaje)


def _error(nombre: str, mensaje: str) -> str:
    return "RESULTADO %s ERROR: %s" % (nombre, mensaje)


def _motivo(exc: BaseException) -> str:
    """La excepcion, en algo que el modelo pueda ACCIONAR.

    Las de documento.py y mates.py ya vienen escritas para ensenarse tal cual
    (llevan el id, la materia, o el pip install exacto). El resto se envuelve
    con su tipo delante: sin el, un error raro sale como una frase suelta y no
    hay forma de saber de donde vino.
    """
    if isinstance(exc, _Rechazo):
        return str(exc)
    texto = str(exc).strip() or exc.__class__.__name__
    if exc.__class__.__name__ in ("ErrorDocumento", "BloqueFijado",
                                  "ErrorDeMates", "FaltaDependencia"):
        return texto
    if isinstance(exc, ImportError):
        return ("falta una dependencia del cuaderno (%s). Instalala con:  "
                "pip install matplotlib sympy" % (texto,))
    return "%s: %s" % (type(exc).__name__, texto)


# ── Parseo de argumentos ─────────────────────────────────────────────────────

def _partir_claves(args: str, permitidas: tuple) -> tuple:
    """(contenido, claves) separando los `clave=valor` DEL FINAL.

    Se recorta desde atras y solo mientras la clave este en `permitidas`: asi
    "la velocidad es v = e/t" conserva su cola (v no es clave de nadie) y
    "sin(x) desde=-10 hasta=10" entrega la expresion limpia. Es el orden que
    produce `tools.armar_args` para una tool con params posicionales + claves,
    o sea el que llega de verdad desde el tool-calling nativo.
    """
    resto = (args or "").strip()
    claves: dict = {}
    while resto:
        m = _RE_CLAVE_FINAL.search(resto)
        if not m or m.group(1) not in permitidas or m.group(1) in claves:
            break
        claves[m.group(1)] = m.group(2).strip()
        resto = resto[:m.start()].rstrip()
    return resto.strip(), claves


def _id_normal(crudo: str) -> str:
    """'7', 'b7' y 'b0007' son el mismo bloque.

    El modelo escribe el id como lo lee y a veces le come los ceros. Un id que
    no existe cuesta un turno entero de ida y vuelta, y normalizar aqui es
    determinista: 'b%04d' es el formato que fabrica documento._id_nuevo.
    """
    t = (crudo or "").strip()
    m = re.fullmatch(r"b?0*(\d{1,9})", t, flags=re.IGNORECASE)
    return "b%04d" % int(m.group(1)) if m else t


def _sin_marca_de_truncado(texto: str) -> None:
    """El contenido no puede ser el marcador de truncado del historial.

    Medido el 2026-08-26 sobre ficheros: el modelo copia al disco el
    "… (argumento truncado: ...)" que la compactacion metio en el historial y
    la escritura "sale bien". En un fichero se recupera releyendo; en los
    apuntes del duenio queda un parrafo de basura dentro de su materia.
    """
    if _MARCA_TRUNCADO in (texto or ""):
        raise _Rechazo(
            "lo que mandaste es el MARCADOR DE TRUNCADO del historial, no "
            "texto de los apuntes. Ese texto aparece porque el contenido "
            "viejo se recorto para ahorrar contexto. NO lo copies: lee el "
            "documento con doc_ver y escribe el contenido de verdad")


def _texto_obligatorio(nombre: str, texto: str, ejemplo: str) -> str:
    if not (texto or "").strip():
        raise _Rechazo("falta el contenido. Se usa asi:  %s" % (ejemplo,))
    _sin_marca_de_truncado(texto)
    return texto.strip()


# ── El documento sobre el que se escribe ─────────────────────────────────────

def _materia_de_la_jornada() -> str:
    """La materia de la clase que se esta grabando AHORA MISMO, o "".

    Es el camino que funciona SIN que nadie cablee nada: si el duenio esta
    dando Fisica, los apuntes de este turno son de Fisica.

    Solo cuenta con `grabando`. La rama de jornada CERRADA de `estado()`
    devuelve la materia de la ULTIMA clase del dia: manana por la maniana eso
    escribiria los apuntes nuevos dentro de la materia de ayer por la tarde,
    y en silencio.

    El import es PEREZOSO (jornada arrastra captura y transcripcion) y el
    fallo se GUARDA en vez de tragarse: si la jornada no se pudo consultar,
    el error final de la tool lo dice, porque "no hay clase" y "no pude
    mirar" son dos estados distintos.
    """
    try:
        from cognia.clases import jornada
        estado = jornada.estado()
    except Exception as exc:
        _FALLO_JORNADA["motivo"] = "%s: %s" % (type(exc).__name__, exc)
        return ""
    _FALLO_JORNADA["motivo"] = ""
    if not estado.get("grabando"):
        return ""
    materia = str(estado.get("materia") or "").strip()
    if not materia or materia == _MATERIA_SIN_CLASIFICAR or materia[:1] == "(":
        return ""
    return materia


def _materia(ctx) -> str:
    """La materia del documento abierto. Lanza _Rechazo si no hay ninguno.

    Orden (el de la cabecera del modulo):
      1. EL CTX de la ejecucion -- lo que sabe la tarea en curso y lo que deja
         la puerta del CLI al abrir el cuaderno.
      2. LA JORNADA VIVA -- el camino que no depende de que nadie cablee nada.
      3. La variable de entorno -- ultimo recurso, para pruebas y para forzar
         el documento desde fuera.

    No hay cuarto sitio a proposito: adivinar la materia (por ejemplo "la
    unica que existe") escribiria apuntes reales en un documento que nadie
    pidio, y el duenio no los encontraria.
    """
    import os
    contexto = ctx if isinstance(ctx, dict) else {}
    memoria = contexto.get("working_memory")
    fuentes = [contexto, memoria if isinstance(memoria, dict) else {}]
    for fuente in fuentes:
        for clave in ("materia", "materia_documento"):
            valor = str(fuente.get(clave) or "").strip()
            if valor:
                return valor
    viva = _materia_de_la_jornada()
    if viva:
        return viva
    valor = os.environ.get(ENV_MATERIA, "").strip()
    if valor:
        return valor
    degradado = ("  (la jornada tampoco se pudo consultar: %s)"
                 % _FALLO_JORNADA["motivo"]) if _FALLO_JORNADA["motivo"] else ""
    raise _Rechazo(
        "no hay ningun documento abierto: no se sabe en que materia escribir. "
        "Abre el cuaderno de la materia desde el CLI, o arranca la clase con "
        "/grabar-clase (mientras se graba, los apuntes van a la materia que "
        "se esta dando). Para forzar un documento desde fuera: %s=<materia>."
        "%s" % (ENV_MATERIA, degradado))


def _documento():
    """El modulo del modelo, importado PEREZOSAMENTE.

    Registrar la familia no puede costar el almacen ni el diario: hasta que el
    agente no llama a una de estas tools, `cognia.clases.documento` no se
    importa.
    """
    from cognia.clases import documento as _doc
    return _doc


def _adjuntos(materia: str) -> Path:
    """Donde van los PNG y las imagenes de ESTE documento.

    Dentro de la carpeta del documento (que vive bajo `almacen.raiz()`) por
    dos razones: los adjuntos viajan con los apuntes de su materia, y todo lo
    que se escribe ahi emite los eventos del cuaderno, asi que una vista en
    vivo se entera sin hacer polling.
    """
    destino = _documento().carpeta(materia) / "adjuntos"
    destino.mkdir(parents=True, exist_ok=True)
    return destino


def _nombre_estable(prefijo: str, semilla: str, extension: str = ".png") -> str:
    """Un nombre de fichero DETERMINISTA para el mismo contenido.

    Con `hash()` (que es lo que hacen las tools de imagen) el mismo latex daria
    un PNG distinto en cada proceso -- PYTHONHASHSEED aleatoriza el hash de
    str -- y el documento acumularia copias del mismo dibujo. Con sha1 del
    contenido, reescribir la misma formula reusa el fichero.
    """
    firma = hashlib.sha1(semilla.encode("utf-8", "replace")).hexdigest()[:10]
    return "%s_%s%s" % (prefijo, firma, extension)


def _aniadir(nombre: str, ctx, tipo: str, texto: str, meta: dict,
             tras: str = "", materia: str = "") -> str:
    """Aniade el bloque por la puerta de la IA y devuelve el mensaje de OK.

    `tras` vacio = al final, que es como se escriben unos apuntes. Un `tras`
    que no existe lo rechaza `documento._donde` con un mensaje que ya nombra
    el id, asi que no se comprueba dos veces.

    `materia` se PASA cuando quien llama ya la resolvio (las tres tools que
    dibujan antes de aniadir). Volver a resolverla aqui costaba una segunda
    consulta a la jornada por escritura y, peor, dejaba una ventana: si la
    clase cambia entre el dibujo y el bloque, el PNG queda en la carpeta de
    una materia y el bloque que lo nombra en otra.
    """
    materia = (materia or "").strip() or _materia(ctx)
    doc = _documento()
    bloque = doc.aniadir_ia(materia, tipo, texto, meta=meta or {},
                            tras=_id_normal(tras) if tras else None)
    donde = " tras %s" % _id_normal(tras) if tras else " al final"
    return _ok(nombre, "bloque %s aniadido (%s)%s en el documento de %r"
               % (bloque.id, tipo, donde, materia))


# ── Vista ────────────────────────────────────────────────────────────────────

def _recorte(texto: str, ancho: int) -> str:
    plano = " / ".join(l.strip() for l in (texto or "").splitlines() if l.strip())
    return plano if len(plano) <= ancho else plano[:ancho - 3] + "..."


def _posicion(d, crudo: str, defecto: int) -> int:
    """Un `desde=`/`hasta=` de doc_ver -> posicion 1-indexada.

    Se aceptan las dos formas en las que el modelo lo va a escribir: un numero
    (la posicion) o un id de bloque (b0007), que es lo que tiene delante
    cuando acaba de leer el indice.
    """
    t = (crudo or "").strip()
    if not t:
        return defecto
    if t.isdigit():
        return int(t)
    i = d.indice(_id_normal(t))
    if i < 0:
        raise _Rechazo("en el documento de %r no hay ningun bloque %r; mira "
                       "los ids con doc_ver" % (d.materia, t))
    return i + 1


def _ficha(b, tope: int) -> str:
    """Un bloque ENTERO (lo que devuelve doc_ver id=...)."""
    marca = " FIJADO-POR-EL-DUENIO" if b.fijado else ""
    texto = b.texto or ""
    cola = ""
    if len(texto) > tope:
        texto, cola = texto[:tope], ("\n[... %d chars mas; el bloque entero "
                                     "esta en el documento ...]"
                                     % (len(texto) - tope))
    lineas = ["%s %s (%s)%s" % (b.id, b.tipo, b.origen, marca), texto + cola]
    interesante = {k: v for k, v in (b.meta or {}).items() if v}
    if interesante:
        lineas.append("meta: %s" % (interesante,))
    return "\n".join(lineas)


# ── Registro ─────────────────────────────────────────────────────────────────

def register(tool):
    """Registra la familia doc_* en el registry del agente.

    Mismo molde que `image_tools.register`: un modulo, una funcion, las tools
    dentro. Quien la llama es `harness/familias.py` (carga en caliente) o el
    arranque de `agent/tools.py` si algun dia se le pone el bloque opt-in.
    """

    @tool(
        "doc_ver",
        "doc_ver [id=b0007] [desde=b0003] [hasta=b0009]  -- lee el documento "
        "de la materia: el indice de bloques con sus ids, un tramo, o un "
        "bloque entero con id=",
        desc=(
            "Lee el documento (los apuntes) de la materia abierta. Sin "
            "argumentos devuelve el indice: el id, el tipo y el principio de "
            "cada bloque, con una marca en los que el duenio fijo. Usalo "
            "ANTES de escribir para saber que hay ya y donde encaja lo nuevo, "
            "y despues de escribir solo si necesitas releer. Con id= devuelve "
            "ese bloque entero (texto completo y meta)."
        ),
        params=[
            {"nombre": "id", "tipo": "string", "requerido": False,
             "clave": True,
             "descripcion": "un bloque concreto, por ejemplo b0007: devuelve "
                            "su texto completo en vez del indice"},
            {"nombre": "desde", "tipo": "string", "requerido": False,
             "clave": True,
             "descripcion": "primer bloque del tramo: un id (b0003) o una "
                            "posicion (3)"},
            {"nombre": "hasta", "tipo": "string", "requerido": False,
             "clave": True,
             "descripcion": "ultimo bloque del tramo, inclusive"},
        ],
    )
    def _doc_ver(args, ctx):
        try:
            _, claves = _partir_claves(args, ("id", "desde", "hasta"))
            materia = _materia(ctx)
            d = _documento().abrir(materia, crear=False)
            if claves.get("id"):
                bid = _id_normal(claves["id"])
                b = d.bloque(bid)
                if b is None:
                    raise _Rechazo(
                        "en el documento de %r no hay ningun bloque %r. Mira "
                        "los ids que si existen con doc_ver sin argumentos"
                        % (materia, bid))
                return _ok("doc_ver", "\n" + _ficha(b, _TOPE_BLOQUE))
            if not d.bloques:
                return _ok("doc_ver",
                           "el documento de %r esta vacio. Empieza con "
                           "doc_escribir <titulo de la clase> tipo=titulo"
                           % (materia,))
            desde = max(1, _posicion(d, claves.get("desde"), 1))
            # max(1, ...): un 'hasta=0' escrito por el modelo dejaba el tope
            # en cero y el mensaje de mas abajo indexaba d.bloques[-1].
            hasta = max(1, min(len(d.bloques),
                               _posicion(d, claves.get("hasta"),
                                         len(d.bloques))))
            if desde > hasta:
                # Un tramo del reves devolvia el indice VACIO, sin decir por
                # que: el modelo lo lee como "aqui no hay nada" y se pone a
                # reescribir bloques que si existen.
                raise _Rechazo(
                    "el tramo esta del reves: desde=%s es posterior a "
                    "hasta=%s. Pidelo al derecho:  doc_ver desde=%s hasta=%s"
                    % (d.bloques[min(desde, len(d.bloques)) - 1].id,
                       d.bloques[hasta - 1].id, d.bloques[hasta - 1].id,
                       d.bloques[min(desde, len(d.bloques)) - 1].id))
            fijados = sum(1 for b in d.bloques if b.fijado)
            cabecera = ("DOCUMENTO %r -- %d bloques (%d fijados por el duenio)"
                        % (materia, len(d.bloques), fijados))
            filas, cortado = [], 0
            for b in d.bloques[desde - 1:hasta]:
                fila = "%s %-9s %s %s" % (b.id, b.tipo, "*" if b.fijado else " ",
                                          _recorte(b.texto, _ANCHO_LINEA))
                # `filas and`: SIEMPRE entra al menos un bloque. Sin eso, un
                # tope mas bajo que una fila devolveria una pagina vacia que
                # pide otra vez lo mismo -- el mismo bucle de abajo, por otra
                # puerta.
                if filas and sum(len(f) for f in filas) + len(fila) > _TOPE_VISTA:
                    cortado = hasta - (desde - 1) - len(filas)
                    break
                filas.append(fila.rstrip())
            pie = ["", "* = FIJADO por el duenio: doc_editar no lo cambia; si "
                       "falta algo, escribe un bloque nuevo con "
                       "doc_escribir ... tras=<id>"]
            if cortado:
                # EL SIGUIENTE bloque del TRAMO, no el enesimo del documento.
                # Indexar desde el principio (d.bloques[len(filas)]) devolvia
                # el mismo id en cada pagina a partir de la segunda: el modelo
                # pedia eternamente doc_ver desde=b0038 y se gastaba el
                # presupuesto entero de la clase releyendo lo mismo.
                siguiente = d.bloques[(desde - 1) + len(filas)].id
                # Si el duenio (o el modelo) acoto con hasta=, la siguiente
                # pagina tiene que seguir acotada: sin esto, pedir la
                # continuacion de un tramo devuelve el documento hasta el final.
                cola = (" hasta=%s" % d.bloques[hasta - 1].id
                        if claves.get("hasta") else "")
                pie.append("quedan %d bloques sin ensenar: pidelos con "
                           "doc_ver desde=%s%s" % (cortado, siguiente, cola))
            return _ok("doc_ver", "\n" + "\n".join([cabecera] + filas + pie))
        except Exception as exc:
            return _error("doc_ver", _motivo(exc))

    @tool(
        "doc_escribir",
        "doc_escribir <texto> [tipo=parrafo|titulo|subtitulo|lista|cita|deber|"
        "duda|examen] [tras=b0007]  -- aniade un bloque de texto al documento "
        "(por defecto un parrafo al final)",
        desc=(
            "Aniade un bloque nuevo a los apuntes de la materia. El texto es "
            "markdown y va PRIMERO y entero: las opciones (tipo=, tras=) van "
            "detras. Sin tras= el bloque va al final, que es como se escriben "
            "unos apuntes. Para una formula, una grafica, una imagen o una "
            "tabla NO uses esta: tienen tool propia porque ademas dibujan."
        ),
        params=[
            {"nombre": "texto", "tipo": "string", "requerido": True,
             "descripcion": "el contenido en markdown; puede llevar saltos de "
                            "linea y barras verticales"},
            {"nombre": "tipo", "tipo": "string", "requerido": False,
             "clave": True,
             "descripcion": "parrafo (defecto), titulo, subtitulo, lista, "
                            "cita, deber, duda o examen"},
            {"nombre": "tras", "tipo": "string", "requerido": False,
             "clave": True,
             "descripcion": "id del bloque tras el que se inserta; sin esto "
                            "va al final"},
        ],
    )
    def _doc_escribir(args, ctx):
        try:
            texto, claves = _partir_claves(args, ("tipo", "tras"))
            texto = _texto_obligatorio(
                "doc_escribir", texto,
                "doc_escribir Hoy hemos visto el MRU tipo=parrafo")
            tipo = (claves.get("tipo") or "parrafo").strip().lower()
            if tipo in _TOOL_DEL_TIPO:
                raise _Rechazo(
                    "un bloque de tipo %r no se escribe con doc_escribir "
                    "(quedaria como texto plano, sin dibujar): usa %s"
                    % (tipo, _TOOL_DEL_TIPO[tipo]))
            if tipo not in _TIPOS_TEXTO:
                raise _Rechazo(
                    "tipo %r desconocido. Los de texto son: %s (y para "
                    "formula, grafica, imagen o tabla hay tool propia)"
                    % (tipo, ", ".join(_TIPOS_TEXTO)))
            return _aniadir("doc_escribir", ctx, tipo, texto, {},
                            claves.get("tras", ""))
        except Exception as exc:
            return _error("doc_escribir", _motivo(exc))

    @tool(
        "doc_editar",
        "doc_editar <id> | <texto nuevo>  -- reescribe un bloque que escribio "
        "la IA (los que fijo el duenio NO se tocan)",
        desc=(
            "Reescribe el contenido de un bloque que ya existe, por su id. Es "
            "la forma de corregirse sin duplicar los apuntes. Si el bloque lo "
            "corrigio el duenio esta FIJADO y no se cambia: en ese caso "
            "escribe un bloque nuevo debajo con doc_escribir ... tras=<id>. "
            "En una formula o una grafica, el texto nuevo es el latex o la "
            "expresion: se vuelve a dibujar."
        ),
        params=[
            {"nombre": "id", "tipo": "string", "requerido": True,
             "descripcion": "id del bloque, por ejemplo b0007 (lo da doc_ver)"},
            {"nombre": "texto", "tipo": "string", "requerido": True,
             "descripcion": "el contenido nuevo COMPLETO; va el ultimo porque "
                            "puede llevar barras verticales y saltos de linea"},
        ],
    )
    def _doc_editar(args, ctx):
        try:
            partes = re.split(r"\s*\|\s*", args or "", maxsplit=1)
            if len(partes) != 2 or not partes[0].strip():
                raise _Rechazo(
                    "formato. Se usa asi:  doc_editar b0007 | el texto nuevo "
                    "completo   (el id delante, separado por una barra)")
            bid = _id_normal(partes[0])
            texto = _texto_obligatorio("doc_editar", partes[1],
                                       "doc_editar b0007 | el texto nuevo")
            materia = _materia(ctx)
            doc = _documento()
            d = doc.abrir(materia, crear=False)
            b = d.bloque(bid)
            if b is None:
                raise _Rechazo(
                    "en el documento de %r no hay ningun bloque %r. Mira los "
                    "ids con doc_ver; si querias aniadir algo, usa "
                    "doc_escribir" % (materia, bid))
            if b.fijado:
                # La REGLA DE ORO. `escribir_ia` ya la haria cumplir y lo
                # anotaria en el diario, pero el modelo necesita leer QUE HACER
                # distinto, no solo que no se pudo.
                doc.escribir_ia(materia, bid, texto=texto)   # deja la anotacion
                return _error(
                    "doc_editar",
                    "el bloque %s lo edito el DUENIO y esta fijado: la IA no "
                    "lo reescribe. Si quieres aniadir algo, escribe un bloque "
                    "nuevo debajo:  doc_escribir <lo que falta> tras=%s"
                    % (bid, bid))
            meta = dict(b.meta or {})
            if b.tipo == "formula":
                meta.update(_pintar_formula(materia, texto))
                nuevo_texto = texto
            elif b.tipo == "grafica":
                dibujo = _pintar_grafica(materia, texto, {})
                meta.update(dibujo["meta"])
                nuevo_texto = dibujo["texto"]
            elif b.tipo == "tabla":
                meta["cabecera"] = _cabecera_de_tabla(texto)
                nuevo_texto = texto
            else:
                nuevo_texto = texto
            informe = doc.escribir_ia(materia, bid, texto=nuevo_texto,
                                      meta=meta)
            if not informe.get("ok"):
                return _error("doc_editar", informe.get("motivo") or
                              "el bloque %s no se pudo reescribir" % (bid,))
            return _ok("doc_editar", "bloque %s reescrito (%s) en el "
                       "documento de %r" % (bid, b.tipo, materia))
        except Exception as exc:
            return _error("doc_editar", _motivo(exc))

    @tool(
        "doc_formula",
        "doc_formula <latex> [tras=b0007]  -- aniade una formula DIBUJADA "
        "(LaTeX de formula: \\frac, \\sqrt, \\sum, ^, _)",
        desc=(
            "Aniade una formula a los apuntes y la dibuja en PNG (sin "
            "instalar LaTeX: lo hace matplotlib). El latex va primero y "
            "entero, con sus contrabarras, sin dolares. Entiende el LaTeX de "
            "FORMULA, no el de documento (\\begin{align} no)."
        ),
        params=[
            {"nombre": "latex", "tipo": "string", "requerido": True,
             "descripcion": r"la formula, por ejemplo \frac{1}{2}mv^2"},
            {"nombre": "tras", "tipo": "string", "requerido": False,
             "clave": True,
             "descripcion": "id del bloque tras el que se inserta"},
        ],
    )
    def _doc_formula(args, ctx):
        try:
            latex, claves = _partir_claves(args, ("tras",))
            latex = _texto_obligatorio("doc_formula", latex,
                                       r"doc_formula \frac{1}{2}mv^2")
            materia = _materia(ctx)
            meta = _pintar_formula(materia, latex)
            return _aniadir("doc_formula", ctx, "formula", latex, meta,
                            claves.get("tras", ""), materia=materia)
        except Exception as exc:
            return _error("doc_formula", _motivo(exc))

    @tool(
        "doc_grafica",
        "doc_grafica <expresion> [var=x] [desde=-10] [hasta=10] [tras=b0007]  "
        "-- aniade la GRAFICA de una expresion (sin(x)/x, x**2-3*x)",
        desc=(
            "Dibuja la grafica de una expresion en una variable y la aniade a "
            "los apuntes. La expresion va primera y entera; el rango y la "
            "variable van detras como opciones. Sirve para ensenar una "
            "funcion que se ha visto en clase; no evalua codigo, solo "
            "matematicas."
        ),
        params=[
            {"nombre": "expresion", "tipo": "string", "requerido": True,
             "descripcion": "la funcion, por ejemplo sin(x)/x"},
            {"nombre": "var", "tipo": "string", "requerido": False,
             "clave": True, "descripcion": "la variable (defecto x)"},
            {"nombre": "desde", "tipo": "number", "requerido": False,
             "clave": True, "descripcion": "principio del rango (defecto -10)"},
            {"nombre": "hasta", "tipo": "number", "requerido": False,
             "clave": True, "descripcion": "final del rango (defecto 10)"},
            {"nombre": "tras", "tipo": "string", "requerido": False,
             "clave": True,
             "descripcion": "id del bloque tras el que se inserta"},
        ],
    )
    def _doc_grafica(args, ctx):
        try:
            expresion, claves = _partir_claves(
                args, ("var", "desde", "hasta", "tras"))
            expresion = _texto_obligatorio(
                "doc_grafica", expresion, "doc_grafica sin(x)/x desde=-10 hasta=10")
            materia = _materia(ctx)
            dibujo = _pintar_grafica(materia, expresion, claves)
            return _aniadir("doc_grafica", ctx, "grafica", dibujo["texto"],
                            dibujo["meta"], claves.get("tras", ""),
                            materia=materia)
        except Exception as exc:
            return _error("doc_grafica", _motivo(exc))

    @tool(
        "doc_imagen",
        "doc_imagen <ruta del png/jpg> | <pie de foto> [tras=b0007]  -- mete "
        "una imagen ya existente en el documento, con su pie",
        desc=(
            "Aniade a los apuntes una imagen que ya esta en el disco (por "
            "ejemplo la que acaba de generar imagen_generar, o una foto de la "
            "pizarra) y la copia junto al documento para que no se pierda si "
            "el original se mueve. El pie va el ultimo porque es texto libre."
        ),
        params=[
            {"nombre": "ruta", "tipo": "string", "requerido": True,
             "descripcion": "ruta del fichero de imagen que ya existe"},
            {"nombre": "pie", "tipo": "string", "requerido": False,
             "descripcion": "pie de foto: lo que se lee debajo y por lo que se "
                            "busca la imagen en el cuaderno"},
            {"nombre": "tras", "tipo": "string", "requerido": False,
             "clave": True,
             "descripcion": "id del bloque tras el que se inserta"},
        ],
    )
    def _doc_imagen(args, ctx):
        try:
            cuerpo, claves = _partir_claves(args, ("tras",))
            partes = re.split(r"\s*\|\s*", cuerpo, maxsplit=1)
            ruta = (partes[0] or "").strip().strip('"')
            pie = partes[1].strip() if len(partes) == 2 else ""
            if not ruta:
                raise _Rechazo(
                    "falta la ruta. Se usa asi:  doc_imagen C:\\ruta\\dibujo.png "
                    "| el pie de foto")
            _sin_marca_de_truncado(pie)
            origen = Path(ruta).expanduser()
            if not origen.is_file():
                raise _Rechazo(
                    # %s y no %r: en Windows el repr duplica las contrabarras
                    # de la ruta y el modelo copia esa version escapada en el
                    # reintento, con lo que la segunda llamada tambien falla.
                    "no existe la imagen '%s'. Da la ruta completa del fichero, "
                    "o generala antes (imagen_generar) y pasa la ruta que "
                    "devuelva" % (str(origen),))
            materia = _materia(ctx)
            destino = _adjuntos(materia) / _nombre_estable(
                "img", "%s|%d" % (origen.name, origen.stat().st_size),
                origen.suffix.lower() or ".png")
            if origen.resolve() != destino.resolve():
                shutil.copy2(origen, destino)
            return _aniadir("doc_imagen", ctx, "imagen", pie,
                            {"adjunto": str(destino), "atribucion": ""},
                            claves.get("tras", ""), materia=materia)
        except Exception as exc:
            return _error("doc_imagen", _motivo(exc))

    @tool(
        "doc_tabla",
        "doc_tabla <tabla en markdown con | y su fila de guiones> [tras=b0007]"
        "  -- aniade una tabla al documento",
        desc=(
            "Aniade una tabla a los apuntes. Se escribe en markdown, con las "
            "barras verticales y la fila de guiones debajo de la cabecera:  "
            "| Magnitud | Unidad |  luego  |---|---|  y luego cada fila. La "
            "tabla va primera y entera: las barras no se parten."
        ),
        params=[
            {"nombre": "tabla", "tipo": "string", "requerido": True,
             "descripcion": "la tabla en markdown, con saltos de linea y "
                            "barras verticales"},
            {"nombre": "tras", "tipo": "string", "requerido": False,
             "clave": True,
             "descripcion": "id del bloque tras el que se inserta"},
        ],
    )
    def _doc_tabla(args, ctx):
        try:
            tabla, claves = _partir_claves(args, ("tras",))
            tabla = _texto_obligatorio(
                "doc_tabla", tabla,
                "doc_tabla | Magnitud | Unidad |\\n|---|---|\\n| v | m/s |")
            cabecera = _cabecera_de_tabla(tabla)
            return _aniadir("doc_tabla", ctx, "tabla", tabla,
                            {"cabecera": cabecera}, claves.get("tras", ""))
        except Exception as exc:
            return _error("doc_tabla", _motivo(exc))

    return {"doc_ver": _doc_ver, "doc_escribir": _doc_escribir,
            "doc_editar": _doc_editar, "doc_formula": _doc_formula,
            "doc_grafica": _doc_grafica, "doc_imagen": _doc_imagen,
            "doc_tabla": _doc_tabla}


# ── Dibujo y validacion (fuera de register: los usa tambien doc_editar) ──────

def _pintar_formula(materia: str, latex: str) -> dict:
    """El PNG de la formula + la meta del bloque. Import perezoso de mates."""
    from cognia.clases import mates
    destino = _adjuntos(materia) / _nombre_estable("formula", latex)
    res = mates.formula_a_png(latex, destino)
    return {"latex": latex, "png": res["ruta"]}


def _numero(claves: dict, nombre: str, defecto: float) -> float:
    crudo = str(claves.get(nombre) or "").strip()
    if not crudo:
        return defecto
    try:
        return float(crudo)
    except ValueError:
        raise _Rechazo(
            "%s=%r no es un numero. El rango se escribe asi:  doc_grafica "
            "sin(x)/x desde=-10 hasta=10" % (nombre, crudo)) from None


def _pintar_grafica(materia: str, expresion: str, claves: dict) -> dict:
    """{'texto', 'meta'} con el PNG ya escrito.

    El `texto` que se guarda es el que devuelve mates (la expresion con su
    rango) y no un rotulo inventado: una imagen no es buscable, y el duenio
    tiene que poder encontrar la grafica escribiendo "sin(x)/x" en el buscador
    del cuaderno seis meses despues.
    """
    from cognia.clases import mates
    var = (str(claves.get("var") or "x").strip() or "x")
    desde = _numero(claves, "desde", -10.0)
    hasta = _numero(claves, "hasta", 10.0)
    destino = _adjuntos(materia) / _nombre_estable(
        "grafica", "%s|%s|%g|%g" % (expresion, var, desde, hasta))
    res = mates.graficar_expresion(expresion, destino, var=var, desde=desde,
                                   hasta=hasta)
    return {"texto": res["texto"],
            "meta": {"expresion": expresion, "png": res["ruta"],
                     "parametros": {"var": var, "desde": desde,
                                    "hasta": hasta}}}


_RE_SEPARADOR = re.compile(r"^:?-{2,}:?$")


def _celdas(linea: str) -> list:
    """Las celdas de una fila markdown, sin los bordes vacios."""
    partes = [c.strip() for c in linea.split("|")]
    if partes and not partes[0]:
        partes = partes[1:]
    if partes and not partes[-1]:
        partes = partes[:-1]
    return partes


def _cabecera_de_tabla(tabla: str) -> list:
    """Las celdas de la cabecera. Lanza _Rechazo si el markdown no es tabla.

    Se es ESTRICTO con la fila de guiones a proposito: es lo que el modelo
    olvida, y sin ella el markdown no se pinta como tabla -- saldria una linea
    de texto con barras dentro de los apuntes del duenio. Un error que ensenia
    cuesta un turno; una tabla rota en el cuaderno no se ve hasta que la lee
    una persona.
    """
    lineas = [l for l in (tabla or "").splitlines() if l.strip()]
    if len(lineas) < 2 or "|" not in lineas[0]:
        raise _Rechazo(
            "eso no es una tabla markdown. Necesita la cabecera, la fila de "
            "guiones y al menos una fila de datos:\n"
            "| Magnitud | Unidad |\n|---|---|\n| velocidad | m/s |")
    cabecera = _celdas(lineas[0])
    separador = _celdas(lineas[1])
    if not cabecera or not separador or not all(
            _RE_SEPARADOR.match(c) for c in separador):
        raise _Rechazo(
            "a la tabla le falta la FILA DE GUIONES debajo de la cabecera "
            "(sin ella el documento la pinta como texto suelto). Asi:\n"
            "| %s |\n| %s |\n| ... |"
            % (" | ".join(cabecera or ["Magnitud", "Unidad"]),
               " | ".join(["---"] * max(2, len(cabecera)))))
    if len(separador) != len(cabecera):
        raise _Rechazo(
            "la cabecera tiene %d columnas y la fila de guiones %d: tienen "
            "que ser las mismas" % (len(cabecera), len(separador)))
    return cabecera
