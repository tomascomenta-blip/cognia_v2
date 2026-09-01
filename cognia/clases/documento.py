# -*- coding: utf-8 -*-
"""
cognia/clases/documento.py
==========================
El DOCUMENTO de una materia: los apuntes escritos en BLOQUES, que la IA
redacta y que el duenio corrige encima.

QUE ES Y QUE NO ES. Es un modelo de datos puro: una lista ORDENADA de bloques
persistida en disco. No es HTML, no es Word y no sabe pintarse -- eso lo hace
quien lo consume (`vista.py`, el CLI, un exportador). Aqui solo viven el
modelo, sus operaciones y su persistencia, por la misma razon por la que
`cuaderno.py` no genera HTML: el dia que haya dos pintores no puede haber dos
modelos distintos del mismo documento.

    Documento("Fisica")
      Bloque(b0001, titulo,   "Movimiento rectilineo uniforme")
      Bloque(b0002, parrafo,  "Hoy se ha visto ...")            origen=ia
      Bloque(b0003, lista,    "- v = e/t\\n- ...")               origen=ia
      Bloque(b0004, formula,  "v = e/t", meta={latex, png})     origen=ia
      Bloque(b0005, parrafo,  "OJO: el profe dijo que ...")     origen=duenio, FIJADO

LA REGLA DE ORO (la promesa que el duenio compro)
-------------------------------------------------
    UN BLOQUE FIJADO NO LO REESCRIBE NI LO BORRA LA IA. NUNCA. NI EL REFINADO
    AUTOMATICO, NI EL REPASO FINAL, NI NADA QUE ESCRIBA COMO 'ia'.

`fijado` se pone SOLO en True cuando lo toca el duenio (aniadir, editar o
mover desde su puerta), y se quita SOLO si el duenio lo pide a mano
(`fijar(materia, id, False)`). La regla no es un comentario ni una convencion
de llamada: se hace cumplir en `_aplicar()`, que es el UNICO sitio por el que
pasa toda mutacion del documento -- las de la puerta de escritura y tambien
las que se releen del diario al reconstruir. O sea que una operacion de la IA
contra un bloque fijado no se aplica ni aunque alguien la meta a mano en el
diario con un editor de texto. Y no se aplica en silencio: se anota en el
diario con una operacion 'respetado' que se puede leer con `respetados()`.

POR QUE DIARIO **Y** INSTANTANEA (las dos, no una)
--------------------------------------------------
  - El DIARIO (`diario.jsonl`, append-only, una operacion por linea, via
    `almacen.apendar` -> fsync + evento "clase.entrada") es la VERDAD. Da
    historial ("quien escribio esto y cuando") y sobrevive a un corte: un
    fichero a medio escribir pierde como mucho la ultima linea.
  - La INSTANTANEA (`documento.json`, via `almacen.guardar_json` -> temporal +
    os.replace) es una CACHE del estado. Existe para no reproducir horas de
    diario cada vez que se abre el documento: al abrir se parte de la
    instantanea y solo se reproducen las lineas posteriores.

Si se cae la instantanea, el documento se reconstruye entero desde el diario
(hay test). Si se cae el diario -- entero o por la cola --, se pierde el
historial pero NO el estado: la instantanea conserva los bloques y ademas el
CONTADOR DE IDS (`siguiente`), que es lo unico que no se puede reconstruir de
un diario incompleto. Ver `_cargar` y `_id_nuevo`: un id reciclado es peor que
un id perdido, porque un bloque nuevo heredaria las referencias del viejo. La
instantanea se reescribe cada `_ops_por_instantanea()` operaciones -- ver ahi
por que ese numero y por que esta marcado NO MEDIDO.

CONCURRENCIA
------------
Esto lo tocan dos hilos a la vez: el refinado de fondo (escribe como 'ia') y
el duenio corrigiendo. Todas las escrituras se serializan con `_LOCK`, un
RLock de MODULO. Lo que garantiza y lo que no esta escrito en `_LOCK`.

TIEMPOS. Aqui `t` es epoch (`time.time()`), NO segundos desde el inicio de la
jornada como en `cuaderno.py`: un documento de materia cruza jornadas, y un
tiempo relativo a una de ellas no significaria nada al lado de un bloque
escrito otro dia.

API publica:
    abrir(materia, crear=True) -> Documento
    documentos() -> list                 las materias que ya tienen documento
    aniadir(materia, tipo, texto, ...) -> Bloque      puerta del DUENIO
    editar / mover / borrar / fijar                   puerta del DUENIO
    aniadir_ia / escribir_ia / borrar_ia              puerta de la IA
    desde_apuntes(materia, apuntes, clave) -> dict    volcado IDEMPOTENTE
    buscar(materia, consulta) -> list
    a_markdown(materia) -> str  /  volcar(doc) -> str
    respetados(materia) -> list          lo que la IA no pudo tocar
    compactar(materia) -> Documento      fuerza la instantanea
    estado(materia=None) -> dict         puerta de DIAGNOSTICO
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
import unicodedata
from dataclasses import dataclass, field, asdict
from pathlib import Path

from cognia.clases import almacen as alm

_log = logging.getLogger(__name__)

# Disposicion en disco, bajo el mismo cuaderno de clases que todo lo demas:
#
#     ~/.cognia/clases/documentos/<materia>/diario.jsonl    append-only
#     ~/.cognia/clases/documentos/<materia>/documento.json  instantanea
#
# Va DENTRO de alm.raiz() a proposito: es lo que hace que las escrituras
# emitan "clase.entrada"/"clase.json" (ver almacen._bajo_la_raiz), o sea que
# una vista en vivo se entera de que el documento cambio sin hacer polling.
DIR_DOCUMENTOS = "documentos"
DIARIO = "diario.jsonl"
INSTANTANEA = "documento.json"
VERSION = 1

# Tipos de bloque. Lista CERRADA, por la misma razon que `cuaderno.TIPOS`:
# quien pinta y quien exporta tratan cada tipo distinto, y un tipo inventado
# se renderizaria como NADA -- texto que el duenio ve escribirse y luego no
# encuentra en su documento.
TIPO_TITULO = "titulo"
TIPO_SUBTITULO = "subtitulo"
TIPO_PARRAFO = "parrafo"
TIPO_LISTA = "lista"
TIPO_FORMULA = "formula"
TIPO_GRAFICA = "grafica"
TIPO_IMAGEN = "imagen"
TIPO_TABLA = "tabla"
TIPO_CITA = "cita"
TIPO_DEBER = "deber"
TIPO_DUDA = "duda"
TIPO_EXAMEN = "examen"
TIPOS = (TIPO_TITULO, TIPO_SUBTITULO, TIPO_PARRAFO, TIPO_LISTA, TIPO_FORMULA,
         TIPO_GRAFICA, TIPO_IMAGEN, TIPO_TABLA, TIPO_CITA, TIPO_DEBER,
         TIPO_DUDA, TIPO_EXAMEN)

# Quien escribio un bloque. Dos valores y no mas: la regla de oro se decide
# con esto, y un tercer origen ("plugin", "importado") obligaria a decidir de
# que lado cae -- mejor que quien lo aniada tenga que venir aqui y decidirlo.
ORIGEN_IA = "ia"
ORIGEN_DUENIO = "duenio"
ORIGENES = (ORIGEN_IA, ORIGEN_DUENIO)

# Operaciones del diario. 'respetado' no cambia el estado: es la ANOTACION de
# que la IA quiso tocar un bloque fijado y no pudo (ver la regla de oro).
OPS = ("crear", "aniadir", "editar", "mover", "borrar", "fijar", "respetado")

# Meta por tipo: PUNTO DE EXTENSION. Aniadir un tipo con meta propia es
# aniadir una entrada aqui, no tocar el codigo. Los defaults se rellenan
# siempre, para que quien pinte pueda hacer meta["latex"] sin defensa (el
# mismo motivo por el que apuntes._normalizar fuerza el juego de claves). Una
# clave que no este aqui NO se tira: se conserva tal cual.
META_POR_TIPO = {
    TIPO_FORMULA: {"latex": "", "png": ""},
    TIPO_GRAFICA: {"expresion": "", "png": "", "parametros": {}},
    TIPO_IMAGEN: {"adjunto": "", "atribucion": ""},
    TIPO_TABLA: {"cabecera": []},
}

# Donde vive la referencia al trozo de apuntes que genero un bloque. Es lo que
# hace IDEMPOTENTE a `desde_apuntes`: sin una marca estable, volver a volcar
# los mismos apuntes duplicaria el documento entero.
CLAVE_REF = "ref_apuntes"


class ErrorDocumento(Exception):
    """Cualquier operacion invalida sobre un documento. Lleva SIEMPRE la
    materia y el id en el mensaje: el llamante tipico es el CLI, y 'id
    invalido' sin decir cual no le sirve a nadie."""


class BloqueFijado(ErrorDocumento):
    """La IA intento tocar un bloque que el duenio fijo. Es la regla de oro
    saltando. Las puertas de la IA (`escribir_ia`, `borrar_ia`) NO la lanzan
    -- devuelven un informe, porque encontrarse bloques fijados es lo NORMAL
    en un refinado y no una excepcion --; se lanza si alguien se salta esas
    puertas."""


# ── El lock ──────────────────────────────────────────────────────────────────

# QUE GARANTIZA: que dos hilos de ESTE proceso no se pisen. Toda escritura
# hace leer-estado -> aplicar -> apendar -> (quizas) instantanea dentro del
# lock, asi que ningun hilo calcula un id o una posicion sobre un estado que
# otro ya cambio, y nadie lee una instantanea escrita a partir de un estado a
# medio aplicar. Es REENTRANTE porque `desde_apuntes` lo toma y luego llama a
# `aniadir_ia`, que vuelve a tomarlo: con un Lock normal eso seria un abrazo
# mortal contra si mismo.
#
# QUE NO GARANTIZA: nada entre PROCESOS. Dos `python -m cognia` sobre el mismo
# documento pueden intercalar operaciones; el diario aguanta (cada linea se
# escribe entera con fsync y el orden lo pone el sistema de ficheros) pero dos
# `aniadir` simultaneos podrian calcular el MISMO id. Para eso haria falta un
# fichero de bloqueo del SO, y no se ha puesto porque el caso real es un solo
# REPL con su hilo de refinado. Si algun dia hay dos procesos, se pone aqui.
#
# Tampoco hace transaccional el disco: entre el apendado del diario y la
# instantanea puede morir el proceso. Es a proposito -- el diario es la
# verdad y la instantanea solo una cache, asi que la reconstruccion reproduce
# desde la instantanea hacia delante y el estado sale igual.
_LOCK = threading.RLock()


# ── Degradacion visible ──────────────────────────────────────────────────────

_avisos_dados: set = set()
_ultimo_fallo: dict = {}


def ultimo_fallo() -> dict:
    """Lo ultimo que se degrado, o {} si nada. Es lo que lee `estado()`.

    Existe por lo de siempre en este repo: "no lo cablearon" y "se rompio" no
    pueden verse igual desde fuera. El aviso es log-once (una linea rota en el
    diario se avisa una vez, no una vez por apertura), asi que sin este dict
    la segunda apertura no dejaria rastro de que el diario sigue tocado.
    """
    return dict(_ultimo_fallo)


def _degradar(donde: str, motivo: str, accion: str = "") -> None:
    """Avisa por el canal de degradacion de la casa, UNA vez por `donde`.

    Mismo patron que `almacen._degradar_una_vez` y por el mismo motivo (lo
    pinta el REPL en ambar y lo recoge la telemetria). No se reusa aquella
    funcion porque es privada de aquel modulo y su `donde` identifica al
    almacen: si esto avisara como "clases.almacen", el aviso mentiria sobre
    quien se rompio.
    """
    _ultimo_fallo.clear()
    _ultimo_fallo.update({"donde": donde, "motivo": motivo, "t": time.time()})
    if donde in _avisos_dados:
        return
    _avisos_dados.add(donde)
    _log.warning("clases.documento: %s -- %s", donde, motivo)
    try:
        from cognia.ux import events as _ux
        _ux.emitir(_ux.Degradado(donde=donde, motivo=motivo,
                                 accion_sugerida=accion))
    except Exception as exc:
        # Se acaba de romper el canal de avisos: queda en el log y se sigue.
        # Nunca un except mudo.
        _log.warning("clases.documento: tampoco pude avisar por ux.events (%s)",
                     exc)


# ── Modelo ───────────────────────────────────────────────────────────────────

@dataclass
class Bloque:
    """Una pieza del documento.

    `texto` es MARKDOWN CRUDO a proposito: es lo que el duenio edita y lo que
    `buscar` mira. Guardar HTML o un arbol de nodos obligaria a re-parsear
    para buscar, y a que el editor supiera del arbol.

    `meta` lleva lo especifico del tipo (el latex y el PNG de una formula, el
    adjunto y la atribucion de una imagen, los parametros de una grafica). Va
    en un dict y no en campos porque los tipos crecen y un dataclass con 20
    campos opcionales seria ilegible; los defaults por tipo estan en
    META_POR_TIPO.

    `t` es epoch de CREACION y no cambia al editar: el historial de ediciones
    ya esta en el diario, y un `t` que se moviera dejaria de servir para
    ordenar por antiguedad.
    """
    id: str
    tipo: str
    texto: str = ""
    meta: dict = field(default_factory=dict)
    fijado: bool = False
    origen: str = ORIGEN_IA
    t: float = 0.0

    def a_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def de_dict(d: dict) -> "Bloque":
        return Bloque(
            id=str(d.get("id") or ""),
            tipo=str(d.get("tipo") or TIPO_PARRAFO),
            texto=str(d.get("texto") or ""),
            meta=dict(d.get("meta") or {}),
            fijado=bool(d.get("fijado")),
            origen=str(d.get("origen") or ORIGEN_IA),
            t=float(d.get("t") or 0.0),
        )


@dataclass
class Documento:
    """El estado de una materia.

    EL ORDEN ES `bloques`, la lista, y nada mas. No es el orden de un dict, ni
    un campo `posicion` que hubiera que renumerar, ni el orden por `t` (que
    seria mentira en cuanto se mueve un bloque). Se persiste como lista y se
    relee como lista.
    """
    materia: str
    bloques: list = field(default_factory=list)
    siguiente: int = 1          # contador de ids; ver `_id_nuevo`
    ops: int = 0                # lineas del diario ya aplicadas
    ops_instantanea: int = 0    # lineas que la instantanea ya incluia
    avisos: list = field(default_factory=list)
    # La instantanea decia mas operaciones de las que tiene el diario (ver
    # `_cargar`). No es solo un aviso: mientras siga asi, `ops_instantanea`
    # apunta a una linea que no existe y la cuenta de "cuanto llevo sin
    # compactar" sale NEGATIVA, o sea que la instantanea no se reescribiria
    # NUNCA mas y el documento se quedaria congelado en ella. Por eso
    # `_escribir` la fuerza en cuanto ve esta marca.
    instantanea_adelantada: bool = False

    def indice(self, bid: str) -> int:
        """La posicion de un bloque, o -1. Se busca por id y no se cachea un
        mapa: el documento tipico son decenas de bloques y un mapa que se
        desincronice de la lista seria un bug mucho mas caro que el barrido."""
        for i, b in enumerate(self.bloques):
            if b.id == bid:
                return i
        return -1

    def bloque(self, bid: str):
        i = self.indice(bid)
        return self.bloques[i] if i >= 0 else None


# ── Rutas ────────────────────────────────────────────────────────────────────

def carpeta(materia: str) -> Path:
    """La carpeta del documento de una materia. NO la crea.

    No la crea a proposito: `abrir(materia, crear=False)`, `buscar` y
    `estado()` pasan por aqui, y un mkdir en el camino de LECTURA dejaba una
    carpeta vacia por cada materia que alguien mirara -- que luego salia en
    `documentos()` como un documento que nadie escribio nunca. La carpeta la
    crean las primitivas del almacen en la primera escritura de verdad
    (`apendar` y `guardar_json` hacen mkdir del padre).

    El nombre pasa por `almacen._seguro` -- privada de aquel modulo, pero es
    la MISMA sanitizacion que usan jornadas y adjuntos, y tener dos reglas de
    nombres seguros en el mismo cuaderno acabaria con dos carpetas para la
    misma materia. La materia de verdad (con sus tildes y sus barras) se
    guarda dentro de la instantanea, que es de donde la lee `documentos()`.
    """
    return alm.raiz() / DIR_DOCUMENTOS / alm._seguro(materia)


def ruta_diario(materia: str) -> Path:
    return carpeta(materia) / DIARIO


def ruta_instantanea(materia: str) -> Path:
    return carpeta(materia) / INSTANTANEA


def documentos() -> list:
    """Las materias que ya tienen documento, ordenadas. Devuelve el nombre
    REAL (el de dentro de la instantanea) y cae al de la carpeta si no la
    hay."""
    base = alm.raiz() / DIR_DOCUMENTOS
    if not base.is_dir():
        return []
    fuera = []
    for d in sorted(base.iterdir()):
        if not d.is_dir():
            continue
        if not (d / DIARIO).exists() and not (d / INSTANTANEA).exists():
            # Una carpeta sin diario ni instantanea no es un documento: es
            # basura de una version anterior o de un borrado a medias, y
            # listarla haria creer que hay apuntes donde no hay nada.
            continue
        crudo = alm.leer_json(d / INSTANTANEA, {}) or {}
        fuera.append(str(crudo.get("materia") or d.name))
    return fuera


# ── Lectura del diario ───────────────────────────────────────────────────────

def _lineas(ruta: Path) -> list:
    """Las lineas CRUDAS del diario, sin parsear.

    Se parte por "\\n" y no con `str.splitlines()` a proposito: splitlines
    tambien corta por \\x0b, \\x1c y U+2028, y `json.dumps(ensure_ascii=False)`
    NO escapa U+2028. Un bloque con ese caracter (se cuela copiando de un PDF)
    contaria como dos lineas y descuadraria el indice de la instantanea, que
    es un numero de LINEAS. `almacen.apendar` escribe siempre registro+"\\n"
    con newline="\\n", asi que partir por "\\n" es exacto.
    """
    if not ruta.exists():
        return []
    crudo = ruta.read_text(encoding="utf-8", errors="replace")
    lineas = crudo.split("\n")
    if lineas and lineas[-1] == "":
        lineas.pop()
    return lineas


def _cerrar_linea_rota(ruta: Path) -> bool:
    """Si el diario no acaba en salto de linea, se lo pone antes de apendar.

    POR QUE. `almacen.apendar` abre en modo "a" y escribe la linea entera. Si
    el proceso murio en mitad de una escritura, el fichero acaba a medias y
    SIN salto: la siguiente operacion se pegaria al final de esa basura y las
    dos lineas -- la rota y la NUEVA -- quedarian ilegibles. O sea que un
    corte antiguo se comeria una operacion futura, que es justo lo que el
    formato append-only existe para evitar. Cerrando la linea, la rota queda
    sola (se salta al leer) y la nueva entra limpia.

    No se reescribe ni se borra nada: el diario es append-only y el unico
    byte que se aniade es el salto que faltaba.
    """
    try:
        if not ruta.exists() or ruta.stat().st_size == 0:
            return False
        with ruta.open("rb") as fh:
            fh.seek(-1, os.SEEK_END)
            if fh.read(1) == b"\n":
                return False
        with ruta.open("ab") as fh:
            fh.write(b"\n")
            fh.flush()
            os.fsync(fh.fileno())
    except OSError as exc:
        _degradar("clases.documento.cerrar_linea",
                  "no pude cerrar la ultima linea de %s (%s): la proxima "
                  "operacion podria pegarse a una linea rota" % (ruta, exc),
                  accion="revisar permisos sobre el cuaderno de clases")
        return False
    _degradar("clases.documento.diario_roto",
              "el diario %s acababa a medias (corte durante una escritura): "
              "se cierra la linea y se sigue; esa operacion se perdio" % (ruta,),
              accion="ninguna, el resto del documento esta intacto")
    return True


def _ops_por_instantanea() -> int:
    """Cada cuantas operaciones se reescribe la instantanea.

    20, y esta NO MEDIDO: es un compromiso elegido a ojo, no un percentil de
    nada. Lo que hay a cada lado:
      - Reescribir en CADA operacion cuesta un JSON completo del documento
        mas un fsync por cada tecla del duenio; el diario ya garantiza la
        durabilidad, asi que ese fsync no compra nada.
      - No reescribir nunca obliga a reproducir el diario entero al abrir, que
        es exactamente lo que la instantanea existe para no hacer.
    Con 20, abrir reproduce como mucho 19 operaciones (inserciones y ediciones
    sobre una lista de decenas de elementos: microsegundos) y el JSON se
    reescribe una vez cada 20 correcciones, que a ritmo humano es un par de
    minutos. Si algun dia se mide, se mide aqui.

    COGNIA_DOC_OPS_INSTANTANEA lo mueve (los tests lo bajan a 2 para poder
    comprobar la compactacion sin escribir 20 operaciones). Se acota a >= 1:
    un 0 significaria "compactar cada -infinitas" y dejaria la instantanea
    congelada para siempre sin que se notara.
    """
    crudo = os.environ.get("COGNIA_DOC_OPS_INSTANTANEA", "").strip()
    if crudo.isdigit() and int(crudo) >= 1:
        return int(crudo)
    if crudo:
        _degradar("clases.documento.knob",
                  "COGNIA_DOC_OPS_INSTANTANEA=%r no es un entero >= 1: se usa "
                  "el valor por defecto (20)" % (crudo,),
                  accion="poner un entero o quitar la variable")
    return 20


def _cargar(materia: str) -> Documento:
    """El estado del documento: instantanea + las operaciones posteriores.

    Si la instantanea no esta o esta rota, se reproduce el diario ENTERO:
    perder la instantanea nunca puede costar el documento.

    Y AL REVES, que es el caso que se hizo mal la primera vez: si el DIARIO
    perdio lineas (truncado, copiado a medias, restaurado de una copia vieja)
    la instantanea dice mas operaciones de las que hay. Lo que NO se puede
    hacer entonces es tirar los bloques y reconstruir desde cero, que es lo
    que hacia antes:
      - se pierde el estado que la instantanea si tenia (el docstring del
        modulo promete lo contrario: perder el diario cuesta el historial, no
        el estado), y
      - se pierde el CONTADOR DE IDS, asi que el siguiente bloque reciclaria
        el id de uno que ya existio. Un id reciclado es peor que un id
        perdido: la referencia guardada (en un meta, en un apunte, en un
        mensaje del chat) apunta de pronto a OTRO bloque -- por ejemplo al que
        el duenio tenia fijado.
    Lo correcto es que manda la instantanea para esas lineas: las que quedan
    en el diario son un PREFIJO de las que ella ya incluye (un fichero se
    trunca por la cola), asi que no se reproduce ninguna y el estado se queda
    como estaba. Se marca `instantanea_adelantada` para que la proxima
    escritura la reescriba y el indice vuelva a cuadrar.

    El contador de ids sale SIEMPRE del maximo de las tres fuentes: lo que
    diga la instantanea, lo que empuje el diario al reproducirlo (incluidas
    las lineas 'aniadir' que se descartan: ese id se quemo igual) y los
    bloques vivos. Asi no baja ni perdiendo cualquiera de ellas.
    """
    car = carpeta(materia)
    crudo = alm.leer_json(car / INSTANTANEA, {}) or {}
    if not isinstance(crudo, dict):
        crudo = {}
    doc = Documento(materia=str(crudo.get("materia") or materia))
    doc.bloques = [Bloque.de_dict(b) for b in (crudo.get("bloques") or [])]
    tope_instantanea = max(1, int(crudo.get("siguiente") or 1))
    doc.siguiente = tope_instantanea
    desde = max(0, int(crudo.get("ops") or 0))

    lineas = _lineas(car / DIARIO)
    if desde > len(lineas):
        _degradar("clases.documento.instantanea_adelantada",
                  "la instantanea de %r dice %d operaciones y el diario solo "
                  "tiene %d lineas: al diario le falta la cola, asi que "
                  "manda la instantanea y no se reproduce nada (esas lineas "
                  "ya estan dentro de ella). Se pierde el historial, no el "
                  "estado"
                  % (materia, desde, len(lineas)),
                  accion="ninguna, la instantanea se reescribe en la proxima "
                         "escritura")
        doc.instantanea_adelantada = True
        desde = len(lineas)

    if not crudo.get("siguiente") and doc.bloques:
        # Instantanea de una version vieja (o con el contador corrupto) que si
        # trae bloques: las lineas que NO se van a reproducir son la unica
        # memoria que queda de los ids ya quemados -- entre ellos los de
        # bloques borrados, que no estan en `bloques`. Se recorren solo en
        # este caso degradado; en el normal el contador ya viene guardado.
        tope_instantanea = max(tope_instantanea, _tope_de_ids(lineas[:desde]))
        doc.siguiente = tope_instantanea

    doc.ops_instantanea = desde
    for n, linea in enumerate(lineas[desde:], start=desde + 1):
        linea = linea.strip()
        if not linea:
            continue
        try:
            reg = json.loads(linea)
        except ValueError:
            reg = None
        if not isinstance(reg, dict):
            # Dos casos que acaban igual: la linea se corto a mitad (no es
            # JSON) o es JSON pero no un registro (`123`, una lista, algo que
            # metio un editor). Ninguno puede tirar el documento: se salta,
            # como hace almacen.leer_jsonl, y se DICE. El isinstance no es
            # decorativo -- sin el, un `"texto"` suelto en el diario no era
            # una linea saltada sino un AttributeError dentro de `_aplicar`
            # que se llevaba el documento entero al abrirlo.
            doc.avisos.append("linea %d del diario ilegible" % n)
            _degradar("clases.documento.linea_ilegible",
                      "la linea %d del diario de %r no es un registro JSON: "
                      "se salta" % (n, materia),
                      accion="ninguna, es lo esperable tras un corte")
            continue
        try:
            _aplicar(doc, reg)
        except ErrorDocumento as exc:
            # Una operacion del diario que hoy no vale (por ejemplo una de la
            # IA contra un bloque que el duenio fijo DESPUES, o metida a mano)
            # se descarta al reproducir. La regla de oro se aplica tambien
            # aqui: es el unico modo de que no se pueda colar por el diario.
            doc.avisos.append("linea %d descartada: %s" % (n, exc))
            _degradar("clases.documento.op_descartada",
                      "la linea %d del diario de %r no se pudo aplicar: %s"
                      % (n, materia, exc),
                      accion="ninguna, el estado se reconstruye sin ella")
            if reg.get("op") == "aniadir":
                # No se aplico, pero ese id existio: si el contador no lo
                # cuenta, el proximo bloque nace con el id de aquel.
                bid = str((reg.get("bloque") or {}).get("id") or "")
                doc.siguiente = max(doc.siguiente, _num_id(bid) + 1)
    doc.ops = len(lineas)
    doc.siguiente = max(doc.siguiente, tope_instantanea,
                        _tope_de_bloques(doc.bloques))
    return doc


def _guardar_instantanea(doc: Documento) -> None:
    """Escribe la cache del estado, atomicamente (via almacen.guardar_json).

    `siguiente` va DENTRO a proposito: es lo unico del documento que no se
    puede reconstruir de un diario incompleto (un 'aniadir' truncado se lleva
    el unico rastro de que ese id existio), y sin el un diario truncado
    reciclaria ids. Ver `_cargar`.
    """
    alm.guardar_json(ruta_instantanea(doc.materia), {
        "v": VERSION,
        "materia": doc.materia,
        "t": time.time(),
        "ops": doc.ops,
        "siguiente": doc.siguiente,
        "bloques": [b.a_dict() for b in doc.bloques],
    })
    doc.ops_instantanea = doc.ops
    doc.instantanea_adelantada = False


# ── Ids ──────────────────────────────────────────────────────────────────────

def _id_nuevo(doc: Documento) -> str:
    """El id del proximo bloque: 'b' + un contador del documento.

    POR QUE UN CONTADOR Y NO time.time() NI random:
      - Un id por reloj colisiona en cuanto dos bloques se crean en el mismo
        instante (el volcado de unos apuntes crea veinte de golpe), y ademas
        no es monotono: un cambio de hora o un NTP hacia atras lo repite.
      - Un id aleatorio no colisiona en la practica pero no es REPRODUCIBLE:
        reproducir el mismo diario dos veces daria documentos con ids
        distintos, y los tests no podrian comprobar nada estable.
      - El contador es unico por construccion, va en orden de creacion, se
        reconstruye igual desde el diario (cada 'aniadir' lo empuja al leerlo)
        y se lee de un vistazo cuando el duenio dice "borra el b0007".

    Y NUNCA BAJA, aunque se borren bloques -- misma razon que
    `almacen._siguiente_adjunto`: reutilizar el numero haria que una
    referencia guardada (en meta, en un apunte, en un mensaje del chat)
    apuntara de pronto a otro bloque. El id no cambia nunca.
    """
    return "b%04d" % doc.siguiente


def _num_id(bid: str) -> int:
    cuerpo = bid[1:] if bid[:1] == "b" else ""
    return int(cuerpo) if cuerpo.isdigit() else 0


def _tope_de_bloques(bloques) -> int:
    """El contador que hace falta para no repetir ningun id de los VIVOS.

    Es la tercera fuente del contador (las otras dos son la instantanea y el
    diario). Sola no basta -- no sabe de bloques borrados --, pero es la unica
    que sigue ahi cuando el diario esta truncado Y la instantanea no traia
    contador.
    """
    tope = 1
    for b in bloques:
        tope = max(tope, _num_id(b.id) + 1)
    return tope


def _tope_de_ids(lineas) -> int:
    """El id mas alto que se haya CREADO en esas lineas del diario, + 1.

    Solo se llama en el camino degradado (instantanea sin contador): cuesta un
    json.loads por linea y el motivo entero de tener instantanea es no
    recorrer el diario al abrir. En el camino normal el contador viene
    guardado y esto no se toca. Se prefiltra por texto para no parsear las
    lineas que ni siquiera son 'aniadir'.
    """
    tope = 1
    for linea in lineas:
        if '"aniadir"' not in linea:
            continue
        try:
            reg = json.loads(linea.strip())
        except ValueError:
            continue
        if not isinstance(reg, dict):
            continue
        bid = str((reg.get("bloque") or {}).get("id") or "")
        tope = max(tope, _num_id(bid) + 1)
    return tope


# ── Aplicacion de operaciones (el UNICO camino de mutacion) ──────────────────

def _meta_completa(tipo: str, meta) -> dict:
    """La meta del bloque con los defaults de su tipo puestos.

    Se rellena lo que falta y NO se quita nada de lo que venga: una clave que
    este modulo no conozca puede ser del exportador o del duenio, y borrarla
    al guardar seria una via de perdida silenciosa (la misma que apuntes.py
    tuvo con las claves alias).
    """
    fuera = dict(META_POR_TIPO.get(tipo) or {})
    for k, v in dict(meta or {}).items():
        fuera[k] = v
    return fuera


def _validar_tipo(tipo: str) -> str:
    if tipo not in TIPOS:
        raise ErrorDocumento(
            "tipo de bloque %r desconocido; los tipos del documento son: %s"
            % (tipo, ", ".join(TIPOS)))
    return tipo


def _donde(doc: Documento, reg: dict) -> int:
    """La posicion en la que entra un bloque segun `tras`/`al_principio`."""
    if reg.get("al_principio"):
        return 0
    tras = reg.get("tras")
    if tras:
        i = doc.indice(str(tras))
        if i < 0:
            raise ErrorDocumento(
                "no se puede colocar tras %r: en el documento de %r no hay "
                "ningun bloque con ese id" % (tras, doc.materia))
        return i + 1
    return len(doc.bloques)


def _aplicar(doc: Documento, reg: dict) -> None:
    """Aplica UNA operacion al estado en memoria. Lanza ErrorDocumento si no
    vale.

    ESTE ES EL EMBUDO. Pasan por aqui las operaciones que se van a escribir en
    el diario Y las que se releen de el al reconstruir. Por eso la regla de
    oro se comprueba AQUI y no en las puertas: una operacion de la IA contra
    un bloque fijado no se aplica ni escribiendola a mano en el diario.
    """
    op = str(reg.get("op") or "")
    if op not in OPS:
        raise ErrorDocumento("operacion %r desconocida; las que hay son: %s"
                             % (op, ", ".join(OPS)))
    quien = str(reg.get("quien") or ORIGEN_DUENIO)

    if op == "crear":
        doc.materia = str(reg.get("materia") or doc.materia)
        return
    if op == "respetado":
        # Anotacion pura: deja constancia de que la IA quiso tocar algo fijado
        # y no lo toco. No cambia el estado a proposito.
        return

    if op == "aniadir":
        b = Bloque.de_dict(reg.get("bloque") or {})
        _validar_tipo(b.tipo)
        if not b.id:
            raise ErrorDocumento("un bloque sin id no se puede aniadir al "
                                 "documento de %r" % (doc.materia,))
        if doc.bloque(b.id) is not None:
            raise ErrorDocumento("el documento de %r ya tiene un bloque %s"
                                 % (doc.materia, b.id))
        if b.origen not in ORIGENES:
            raise ErrorDocumento("origen %r desconocido; solo %s"
                                 % (b.origen, " o ".join(ORIGENES)))
        b.meta = _meta_completa(b.tipo, b.meta)
        doc.bloques.insert(_donde(doc, reg), b)
        doc.siguiente = max(doc.siguiente, _num_id(b.id) + 1)
        return

    bid = str(reg.get("id") or "")
    b = doc.bloque(bid)
    if b is None:
        raise ErrorDocumento("en el documento de %r no hay ningun bloque %r"
                             % (doc.materia, bid))

    # ── LA REGLA DE ORO ──────────────────────────────────────────────────
    # Cualquier operacion que MODIFIQUE un bloque fijado y venga de la IA se
    # rechaza. Se incluye 'mover' y 'fijar' ademas de 'editar' y 'borrar':
    # cambiar de sitio el parrafo que el duenio escribio, o desfijarlo para
    # reescribirlo despues, seria la misma promesa rota por la puerta de
    # atras. Desfijar es cosa del duenio, siempre.
    if quien == ORIGEN_IA and b.fijado:
        raise BloqueFijado(
            "el bloque %s del documento de %r esta FIJADO por el duenio: la "
            "IA no lo reescribe, no lo mueve y no lo borra (op %r)"
            % (bid, doc.materia, op))

    if op == "editar":
        if reg.get("texto") is not None:
            b.texto = str(reg.get("texto"))
        if reg.get("meta") is not None:
            b.meta = _meta_completa(b.tipo, reg.get("meta"))
        if quien == ORIGEN_DUENIO:
            # La regla de oro, la otra mitad: lo que toca el duenio queda
            # fijado y pasa a ser suyo. Sin esto habria que acordarse de
            # fijar a mano cada correccion, y el refinado se comeria la
            # primera que se olvidara.
            b.fijado = True
            b.origen = ORIGEN_DUENIO
        return

    if op == "mover":
        # El destino se valida ANTES de sacar el bloque de la lista. Al reves,
        # un `tras` que no existe dejaria el bloque fuera del documento: en la
        # puerta de escritura no se notaria (el estado se descarta al fallar),
        # pero al REPRODUCIR el diario el estado es acumulativo y esa
        # operacion mala se llevaria el bloque por delante.
        tras = reg.get("tras")
        if tras and str(tras) == bid:
            raise ErrorDocumento("no se puede mover el bloque %s tras si "
                                 "mismo (documento de %r)" % (bid, doc.materia))
        if tras and doc.indice(str(tras)) < 0:
            raise ErrorDocumento(
                "no se puede mover %s tras %r: en el documento de %r no hay "
                "ningun bloque con ese id" % (bid, tras, doc.materia))
        doc.bloques.pop(doc.indice(bid))
        doc.bloques.insert(_donde(doc, reg), b)
        if quien == ORIGEN_DUENIO:
            b.fijado = True
        return

    if op == "borrar":
        doc.bloques.pop(doc.indice(bid))
        return

    if op == "fijar":
        b.fijado = bool(reg.get("fijado", True))
        return


def _serializable(reg: dict) -> None:
    """Que la operacion quepa en una linea de JSON, ANTES de tocar nada.

    Un `meta` con un objeto raro (un Path, un datetime, un numpy) reventaria
    dentro de `almacen.apendar`, o sea DESPUES de haber aplicado la operacion
    en memoria: el llamante veria el bloque cambiado y el disco no. Se
    comprueba primero y se falla con el tipo en el mensaje.
    """
    try:
        json.dumps(reg, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ErrorDocumento(
            "la operacion no se puede guardar como JSON (%s). Todo lo que "
            "vaya en `meta` tiene que ser texto, numeros, listas o dicts"
            % (exc,)) from exc


def _escribir(materia: str, reg: dict) -> Documento:
    """Una operacion, de punta a punta: valida, apenda al diario y quizas
    compacta. Devuelve el estado YA con la operacion aplicada.

    ORDEN: primero se aplica sobre el estado recien leido (asi una operacion
    invalida no llega al diario), luego se apenda (el diario es la verdad y
    lleva fsync) y solo despues se toca la instantanea. Al reves, un corte
    entre medias dejaria una instantanea con algo que el diario no cuenta.
    """
    if not str(materia or "").strip():
        # Sin esto, escribir con la materia vacia creaba un documento
        # 'sin-nombre' (lo que devuelve almacen._seguro para una cadena
        # vacia): apuntes reales guardados en una materia que el duenio no
        # puede encontrar. Se comprueba aqui porque es el embudo de TODA
        # escritura, no solo de `abrir`.
        raise ErrorDocumento("no se puede escribir en un documento sin "
                             "materia (llego %r)" % (materia,))
    _serializable(reg)
    with _LOCK:
        # La primera escritura de una materia abre su documento, venga por
        # donde venga. Si esto solo lo hiciera `abrir`, un `aniadir` directo
        # dejaria un diario sin la operacion 'crear' -- o sea sin el nombre
        # REAL de la materia (la carpeta va saneada), y el documento se
        # llamaria para siempre como su carpeta.
        car = carpeta(materia)
        if reg.get("op") != "crear" and not (car / DIARIO).exists():
            _escribir(materia, {"op": "crear", "materia": materia,
                                "quien": ORIGEN_DUENIO, "t": time.time()})
        doc = _cargar(materia)
        _aplicar(doc, reg)
        _cerrar_linea_rota(car / DIARIO)
        alm.apendar(car / DIARIO, reg)
        doc.ops += 1
        if (doc.instantanea_adelantada
                or doc.ops - doc.ops_instantanea >= _ops_por_instantanea()):
            # `instantanea_adelantada` fuerza la reescritura AQUI y no en la
            # lectura: `_cargar` lo llaman `abrir(crear=False)`, `buscar` y
            # `estado()`, que tienen prohibido tocar el disco. Curarla en la
            # primera escritura es lo que evita que el indice desfasado se
            # quede pegado: con `ops` de la instantanea por delante del diario
            # la resta de abajo sale negativa y no compactaria nunca mas.
            _guardar_instantanea(doc)
        return doc


# ── Crear / abrir ────────────────────────────────────────────────────────────

def abrir(materia: str, crear: bool = True) -> Documento:
    """El documento de una materia. Con crear=True lo crea si no existe.

    Crear es escribir: se apenda una operacion 'crear' (que guarda el nombre
    REAL de la materia, con tildes y todo, aunque la carpeta vaya saneada) y
    se deja una instantanea. Con crear=False no se toca el disco -- es lo que
    usan las puertas de diagnostico, que no pueden inventar documentos por
    mirarlos.
    """
    materia = str(materia or "").strip()
    if not materia:
        raise ErrorDocumento("un documento necesita una materia; llego vacia")
    with _LOCK:
        car = carpeta(materia)
        existe = (car / DIARIO).exists() or (car / INSTANTANEA).exists()
        if not existe:
            if not crear:
                return Documento(materia=materia)
            _escribir(materia, {"op": "crear", "materia": materia,
                                "quien": ORIGEN_DUENIO, "t": time.time()})
            doc = _cargar(materia)
            _guardar_instantanea(doc)
            return doc
        return _cargar(materia)


def compactar(materia: str) -> Documento:
    """Fuerza la instantanea AHORA. Es lo que se llama al cerrar el REPL o
    antes de exportar: deja el disco con el estado al dia y la proxima
    apertura sin nada que reproducir."""
    with _LOCK:
        doc = _cargar(materia)
        _guardar_instantanea(doc)
        return doc


# ── Puerta del DUENIO ────────────────────────────────────────────────────────

def aniadir(materia: str, tipo: str, texto: str = "", meta=None,
            tras: str = None, al_principio: bool = False,
            origen: str = ORIGEN_DUENIO, fijado=None) -> Bloque:
    """Un bloque nuevo: al final, tras otro id, o el primero.

    `fijado` por defecto sale del origen: lo que escribe el duenio nace
    fijado (la regla de oro) y lo que escribe la IA nace suelto para que el
    refinado pueda mejorarlo. Se puede forzar, pero no hace falta casi nunca.
    """
    _validar_tipo(tipo)
    if origen not in ORIGENES:
        raise ErrorDocumento("origen %r desconocido; solo %s"
                             % (origen, " o ".join(ORIGENES)))
    if fijado is None:
        fijado = (origen == ORIGEN_DUENIO)
    with _LOCK:
        doc = _cargar(materia)
        bloque = Bloque(id=_id_nuevo(doc), tipo=tipo, texto=str(texto or ""),
                        meta=_meta_completa(tipo, meta), fijado=bool(fijado),
                        origen=origen, t=time.time())
        doc = _escribir(materia, {"op": "aniadir", "bloque": bloque.a_dict(),
                                  "tras": tras, "al_principio": bool(al_principio),
                                  "quien": origen, "t": bloque.t})
        return doc.bloque(bloque.id)


def editar(materia: str, bid: str, texto=None, meta=None) -> Bloque:
    """Cambia el texto (y/o la meta) de un bloque COMO DUENIO: lo deja fijado.

    `meta` REEMPLAZA la meta entera (con los defaults del tipo rellenados);
    para cambiar una sola clave, leer la del bloque, tocarla y pasarla.
    """
    doc = _escribir(materia, {"op": "editar", "id": str(bid), "texto": texto,
                              "meta": meta, "quien": ORIGEN_DUENIO,
                              "t": time.time()})
    return doc.bloque(str(bid))


def mover(materia: str, bid: str, tras: str = None,
          al_principio: bool = False) -> Bloque:
    """Cambia un bloque de sitio. Sin `tras` ni `al_principio` va al final."""
    doc = _escribir(materia, {"op": "mover", "id": str(bid), "tras": tras,
                              "al_principio": bool(al_principio),
                              "quien": ORIGEN_DUENIO, "t": time.time()})
    return doc.bloque(str(bid))


def borrar(materia: str, bid: str) -> None:
    """Borra un bloque. Solo el duenio: la IA usa `borrar_ia`."""
    _escribir(materia, {"op": "borrar", "id": str(bid),
                        "quien": ORIGEN_DUENIO, "t": time.time()})


def fijar(materia: str, bid: str, valor: bool = True) -> Bloque:
    """Fija o DESFIJA un bloque. Desfijar es la unica forma de devolverle a la
    IA un bloque que el duenio toco, y por eso solo se puede desde aqui."""
    doc = _escribir(materia, {"op": "fijar", "id": str(bid),
                              "fijado": bool(valor), "quien": ORIGEN_DUENIO,
                              "t": time.time()})
    return doc.bloque(str(bid))


# ── Puerta de la IA ──────────────────────────────────────────────────────────

def aniadir_ia(materia: str, tipo: str, texto: str = "", meta=None,
               tras: str = None, al_principio: bool = False) -> Bloque:
    """Aniade un bloque escrito por la IA (origen='ia', sin fijar).

    Aniadir no pisa nada de nadie, asi que aqui no hay regla que comprobar:
    es la misma operacion con el origen puesto.
    """
    return aniadir(materia, tipo, texto, meta=meta, tras=tras,
                   al_principio=al_principio, origen=ORIGEN_IA)


def escribir_ia(materia: str, bid: str, texto=None, meta=None) -> dict:
    """La IA reescribe un bloque -- SI el duenio no lo ha fijado.

    Devuelve un informe {ok, id, motivo} y NO lanza cuando el bloque esta
    fijado: encontrarse bloques del duenio es lo normal en un refinado de
    fondo, no un error, y obligar al llamante a envolver cada bloque en un
    try/except acabaria en un `except: pass` que se comeria tambien los
    errores de verdad. Lo que si lanza es lo que SI es un error: un id que no
    existe o un tipo/meta invalidos.

    Cuando respeta un bloque lo ANOTA en el diario (operacion 'respetado'),
    para que `respetados()` pueda enseniar que quiso escribir la IA y que no
    llego a escribir. Un respeto silencioso no se distingue de un refinado
    que no llego a correr.
    """
    with _LOCK:
        doc = _cargar(materia)
        b = doc.bloque(str(bid))
        if b is None:
            raise ErrorDocumento("en el documento de %r no hay ningun bloque "
                                 "%r" % (materia, bid))
        if b.fijado:
            motivo = ("el bloque %s lo fijo el duenio: la IA no lo reescribe"
                      % (bid,))
            _anotar_respetado(materia, str(bid), "editar", motivo)
            return {"ok": False, "id": str(bid), "motivo": motivo}
        _escribir(materia, {"op": "editar", "id": str(bid), "texto": texto,
                            "meta": meta, "quien": ORIGEN_IA,
                            "t": time.time()})
        return {"ok": True, "id": str(bid), "motivo": ""}


def borrar_ia(materia: str, bid: str) -> dict:
    """La IA borra un bloque -- SI el duenio no lo ha fijado. Mismo informe y
    misma anotacion que `escribir_ia`."""
    with _LOCK:
        doc = _cargar(materia)
        b = doc.bloque(str(bid))
        if b is None:
            raise ErrorDocumento("en el documento de %r no hay ningun bloque "
                                 "%r" % (materia, bid))
        if b.fijado:
            motivo = ("el bloque %s lo fijo el duenio: la IA no lo borra"
                      % (bid,))
            _anotar_respetado(materia, str(bid), "borrar", motivo)
            return {"ok": False, "id": str(bid), "motivo": motivo}
        _escribir(materia, {"op": "borrar", "id": str(bid),
                            "quien": ORIGEN_IA, "t": time.time()})
        return {"ok": True, "id": str(bid), "motivo": ""}


def _anotar_respetado(materia: str, bid: str, que: str, motivo: str,
                      huella: str = "") -> None:
    """Deja en el diario que la IA quiso tocar un bloque fijado y no pudo.

    `huella` identifica QUE queria escribir (ver `_huella`). Va en su propio
    campo y no dentro del motivo porque el motivo es texto para el duenio y la
    huella es para comparar: `desde_apuntes` la usa para no anotar dos veces
    el mismo respeto cuando se vuelcan los mismos apuntes otra vez.
    """
    _escribir(materia, {"op": "respetado", "id": bid, "que": que,
                        "motivo": motivo, "huella": huella,
                        "quien": ORIGEN_IA, "t": time.time()})


def respetados(materia: str) -> list:
    """Las anotaciones 'respetado' del diario, en orden.

    Es la prueba leible de la regla de oro: cada vez que el refinado se topa
    con algo del duenio queda una linea aqui. La lee la puerta de diagnostico
    y sirve para responder "por que no se actualizo este parrafo".
    """
    fuera = []
    for linea in _lineas(ruta_diario(materia)):
        linea = linea.strip()
        if not linea or '"respetado"' not in linea:
            continue
        try:
            reg = json.loads(linea)
        except ValueError:
            continue
        if reg.get("op") == "respetado":
            fuera.append(reg)
    return fuera


# ── Busqueda ─────────────────────────────────────────────────────────────────

def _norm(texto: str) -> str:
    """Minusculas y sin tildes, para BUSCAR.

    Aqui si se puede usar NFD (que cambia la longitud) porque el resultado
    solo se usa para un `in`; `apuntes._norm` no puede, porque recorta el
    texto original con indices calculados sobre el normalizado.
    """
    plano = unicodedata.normalize("NFD", texto or "")
    plano = "".join(c for c in plano if not unicodedata.combining(c))
    return plano.lower()


def buscar(materia: str, consulta: str) -> list:
    """Los bloques cuyo texto contiene la consulta, en el orden del documento.

    Se busca sobre `texto` -- el markdown crudo -- y no sobre la meta ni sobre
    un render: el markdown es lo que el duenio escribio y lo que reconoce. Sin
    tildes y sin mayusculas, que es como se busca de verdad en unos apuntes.
    """
    aguja = _norm(str(consulta or "").strip())
    if not aguja:
        return []
    return [b for b in abrir(materia, crear=False).bloques
            if aguja in _norm(b.texto)]


# ── Volcado a markdown ───────────────────────────────────────────────────────

def _md_bloque(b: Bloque) -> str:
    """Un bloque como markdown. El `texto` ya ES markdown: aqui solo se le
    pone la decoracion del tipo (los almohadillas del titulo, el $$ de la
    formula, el corchete del deber)."""
    texto = (b.texto or "").strip()
    if b.tipo == TIPO_TITULO:
        return "# " + texto
    if b.tipo == TIPO_SUBTITULO:
        return "## " + texto
    if b.tipo == TIPO_FORMULA:
        latex = str(b.meta.get("latex") or texto)
        return "$$\n%s\n$$" % latex
    if b.tipo in (TIPO_IMAGEN, TIPO_GRAFICA):
        ruta = str(b.meta.get("adjunto") or b.meta.get("png") or "")
        pie = texto or b.tipo
        marca = "![%s](%s)" % (pie, ruta)
        atrib = str(b.meta.get("atribucion") or "")
        return marca + ("\n\n*%s*" % atrib if atrib else "")
    if b.tipo == TIPO_CITA:
        return "\n".join("> " + l for l in texto.splitlines() or [""])
    if b.tipo == TIPO_DEBER:
        return "- [ ] " + texto
    if b.tipo == TIPO_DUDA:
        return "- (duda) " + texto
    if b.tipo == TIPO_EXAMEN:
        return "- (examen) " + texto
    # parrafo, lista y tabla van tal cual: su markdown ya es el bueno.
    return texto


def volcar(doc: Documento) -> str:
    """El documento entero como markdown, en el orden de sus bloques."""
    trozos = [_md_bloque(b) for b in doc.bloques]
    return "\n\n".join(t for t in trozos if t.strip()) + "\n"


def a_markdown(materia: str) -> str:
    return volcar(abrir(materia, crear=False))


# ── Volcado DESDE los apuntes ────────────────────────────────────────────────

def _texto_definicion(d) -> str:
    if isinstance(d, dict):
        termino = str(d.get("termino") or "").strip()
        cuerpo = str(d.get("definicion") or "").strip()
        if termino and cuerpo:
            return "**%s**: %s" % (termino, cuerpo)
        return termino or cuerpo
    return str(d or "").strip()


def _lista_md(items) -> str:
    return "\n".join("- " + x for x in items)


def _plan_de_apuntes(ap: dict, clave: str) -> list:
    """[(ref, tipo, texto, meta)] a partir del dict de `apuntes.py`.

    La `ref` es '<clave de sesion>#<seccion>[#<i>]' y es lo que hace
    idempotente el volcado: identifica al TROZO DE APUNTES, no al bloque, asi
    que regenerar los apuntes de esa sesion vuelve a caer sobre los mismos
    bloques en vez de aniadir copias.

    Las secciones de una linea (titulo, resumen) y las de lista corta (claves,
    definiciones) van en UN bloque, porque asi es como se leen y como se
    corrigen. Formulas, deberes, dudas y examen van una por bloque: cada una
    tiene vida propia (una formula lleva su PNG, un deber se tacha, una duda
    se resuelve) y el duenio va a querer fijar una sin fijar las demas.
    """
    ap = dict(ap or {})
    plan = []

    def _txt(k):
        return str(ap.get(k) or "").strip()

    def _lst(k):
        return [str(x).strip() for x in (ap.get(k) or []) if str(x).strip()]

    titulo = _txt("titulo")
    if titulo:
        plan.append(("%s#titulo" % clave, TIPO_TITULO, titulo, {}))
    resumen = _txt("resumen")
    if resumen:
        plan.append(("%s#resumen" % clave, TIPO_PARRAFO, resumen, {}))
    claves = _lst("claves")
    if claves:
        plan.append(("%s#claves" % clave, TIPO_LISTA, _lista_md(claves), {}))
    definiciones = [_texto_definicion(d) for d in (ap.get("definiciones") or [])]
    definiciones = [d for d in definiciones if d]
    if definiciones:
        plan.append(("%s#definiciones" % clave, TIPO_LISTA,
                     _lista_md(definiciones), {}))
    for i, f in enumerate(_lst("formulas")):
        plan.append(("%s#formulas#%d" % (clave, i), TIPO_FORMULA, f,
                     {"latex": f}))
    for i, d in enumerate(_lst("deberes")):
        plan.append(("%s#deberes#%d" % (clave, i), TIPO_DEBER, d, {}))
    for i, d in enumerate(_lst("dudas")):
        plan.append(("%s#dudas#%d" % (clave, i), TIPO_DUDA, d, {}))
    for i, e in enumerate(_lst("examen")):
        plan.append(("%s#examen#%d" % (clave, i), TIPO_EXAMEN, e, {}))
    return plan


def _por_ref(doc: Documento, ref: str):
    for b in doc.bloques:
        if b.meta.get(CLAVE_REF) == ref:
            return b
    return None


def _huella(tipo: str, texto: str, meta=None) -> str:
    """Marca corta y estable de lo que la IA queria escribir en un bloque.

    Sirve para distinguir DOS respetos distintos de UNO repetido: volcar los
    mismos apuntes dos veces pretende escribir exactamente lo mismo (misma
    huella -> no se vuelve a anotar, el volcado es idempotente), mientras que
    unos apuntes nuevos pretenden otra cosa (otra huella -> si se anota, que
    es informacion que el duenio querra ver).

    Entra la meta ademas del texto porque un bloque se reescribe por las dos
    cosas: dos pasadas que solo cambian el latex de una formula son dos
    intentos distintos. `sort_keys` para que el mismo contenido de un dict de
    tenga siempre la misma huella.

    sha1 y no un hash del proceso: `hash()` de Python va salado por proceso y
    la misma pasada daria huellas distintas en cada arranque, o sea que la
    idempotencia solo aguantaria dentro de una sesion. Se recorta a 12 hex
    porque esto va en cada linea del diario y aqui no hay adversario: lo unico
    que se compara es "es lo mismo que la vez pasada".
    """
    try:
        cola = json.dumps(meta or {}, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        # Una meta que no serializa no llega aqui (`_serializable` corta
        # antes), pero si llegara vale mas una huella pobre que reventar el
        # volcado entero por una anotacion.
        cola = repr(sorted((meta or {}).keys()))
    crudo = "%s\x00%s\x00%s" % (tipo or "", texto or "", cola)
    return hashlib.sha1(crudo.encode("utf-8")).hexdigest()[:12]


def desde_apuntes(materia: str, apuntes: dict, clave: str) -> dict:
    """Vuelca los apuntes de UNA sesion al documento de la materia.

    IDEMPOTENTE: llamarla dos veces con los mismos apuntes no duplica nada
    (cada bloque generado lleva su `ref_apuntes` y la segunda vez se
    reconoce). Si los apuntes cambiaron, el bloque se reescribe; si una
    seccion encogio (tres formulas pasaron a dos), el bloque sobrante se
    borra: si no, el documento acumularia para siempre lo que el modelo dijo
    en la primera pasada.

    Y RESPETA LO FIJADO, que es el punto entero: escribe por la puerta de la
    IA, asi que un bloque que el duenio corrigio no se toca -- ni se
    reescribe ni se borra -- y queda anotado en el informe (`respetados`) y en
    el diario.

    IDEMPOTENTE TAMBIEN EN EL DIARIO, que es la parte que se hizo mal la
    primera vez: una segunda pasada identica no escribe NI UNA linea. Antes
    apendaba una anotacion 'respetado' por cada bloque fijado en CADA pasada,
    asi que el refinado de fondo convertia el diario en un contador de pasadas
    -- y con el a `estado()["respetados"]`, que subia sin que pasara nada. Se
    anota un respeto cuando la IA pretende algo DISTINTO de lo ya anotado
    (misma marca id+que+huella -> ya esta dicho); el informe lo sigue
    devolviendo igual, porque quien llama tiene que saber que se respeto
    aunque no haya nada nuevo que escribir.

    Devuelve {creados, actualizados, sin_cambio, respetados, borrados}, cada
    una una lista de ids. Se toma el lock durante todo el volcado para que el
    duenio no vea el documento a medio generar; es reentrante, asi que las
    llamadas de dentro (aniadir_ia, escribir_ia) lo vuelven a tomar sin
    bloquearse.
    """
    clave = str(clave or "").strip()
    if not clave:
        raise ErrorDocumento(
            "desde_apuntes necesita la clave estable de la sesion "
            "(apuntes.clave_de_sesion): sin ella el volcado no puede saber "
            "que bloques ya escribio y duplicaria el documento entero")
    plan = _plan_de_apuntes(apuntes, clave)
    refs_plan = set(ref for ref, _, _, _ in plan)
    informe = {"creados": [], "actualizados": [], "sin_cambio": [],
               "respetados": [], "borrados": []}

    with _LOCK:
        abrir(materia)
        # Lo que YA esta anotado antes de esta pasada. Se lee una sola vez (no
        # una por bloque respetado) y se va ampliando con lo que anote esta
        # pasada, que es lo mismo que habria leido del diario.
        ya_anotado = set(
            (str(a.get("id") or ""), str(a.get("que") or ""),
             str(a.get("huella") or ""))
            for a in respetados(materia))

        def _respetar(bid, que, motivo, huella):
            """Anota el respeto si no estaba dicho, y lo mete en el informe."""
            marca = (str(bid), que, huella)
            if marca not in ya_anotado:
                _anotar_respetado(materia, str(bid), que, motivo, huella)
                ya_anotado.add(marca)
            informe["respetados"].append(bid)

        for ref, tipo, texto, meta in plan:
            doc = _cargar(materia)
            b = _por_ref(doc, ref)
            meta_nueva = _meta_completa(tipo, dict(meta, **{CLAVE_REF: ref}))
            if b is None:
                nuevo = aniadir_ia(materia, tipo, texto, meta=meta_nueva)
                informe["creados"].append(nuevo.id)
                continue
            igual = (b.texto == texto and b.meta == meta_nueva
                     and b.tipo == tipo)
            if b.fijado:
                if igual:
                    # Fijado pero ya dice exactamente lo que tocaba escribir
                    # (el duenio lo fijo sin cambiarlo, o corrigio y el modelo
                    # coincidio): no hay nada que respetar porque no habia
                    # nada que hacer. Anotarlo seria ruido.
                    informe["sin_cambio"].append(b.id)
                    continue
                _respetar(b.id, "editar",
                          "regenerando %s: el duenio ya lo corrigio" % (ref,),
                          _huella(tipo, texto))
                continue
            if igual:
                informe["sin_cambio"].append(b.id)
                continue
            escribir_ia(materia, b.id, texto=texto, meta=meta_nueva)
            informe["actualizados"].append(b.id)

        # Lo que esta pasada ya no genera pero genero una anterior. Solo se
        # miran las refs de ESTA clave: los bloques de otras sesiones (y los
        # que escribio el duenio a mano, que no tienen ref) no son asunto de
        # este volcado.
        doc = _cargar(materia)
        prefijo = clave + "#"
        sobrantes = [b for b in doc.bloques
                     if str(b.meta.get(CLAVE_REF) or "").startswith(prefijo)
                     and b.meta.get(CLAVE_REF) not in refs_plan]
        for b in sobrantes:
            if b.fijado:
                # Sin huella: aqui la IA no pretende escribir nada, pretende
                # BORRAR, y eso es siempre lo mismo. O sea que el respeto de
                # un sobrante se anota una vez y ya.
                _respetar(b.id, "borrar",
                          "ya no lo generan los apuntes de %s, pero el duenio "
                          "lo corrigio" % (clave,), "")
                continue
            borrar_ia(materia, b.id)
            informe["borrados"].append(b.id)
    return informe


# ── Puerta de diagnostico ────────────────────────────────────────────────────

def estado(materia: str = None) -> dict:
    """Que hay y como esta. Es la puerta que exige CLAUDE.md para una capa sin
    uso directo: dice si el documento existe, cuantos bloques y cuantos
    fijados tiene, cuanto diario lleva sin compactar y cual fue la ultima
    degradacion. Nunca crea nada.
    """
    base = {"raiz": str(alm.raiz() / DIR_DOCUMENTOS),
            "documentos": documentos(),
            "ops_por_instantanea": _ops_por_instantanea(),
            "ultimo_fallo": ultimo_fallo()}
    if not materia:
        return base
    doc = abrir(materia, crear=False)
    anotaciones = respetados(doc.materia)
    base.update({
        "materia": doc.materia,
        "bloques": len(doc.bloques),
        "fijados": sum(1 for b in doc.bloques if b.fijado),
        "de_la_ia": sum(1 for b in doc.bloques if b.origen == ORIGEN_IA),
        "ops": doc.ops,
        "ops_sin_compactar": doc.ops - doc.ops_instantanea,
        # BLOQUES respetados, no lineas del diario. Contar lineas daba un
        # numero que solo subia: cada refinado que se topa otra vez con el
        # mismo parrafo del duenio aniade otra anotacion, y "respetados: 14"
        # sobre un documento con UN bloque fijado no dice nada de lo que hay,
        # dice cuantas veces corrio el refinado. Eso, que tambien interesa
        # para saber si el refinado esta vivo, va aparte.
        "respetados": len(set(str(a.get("id") or "") for a in anotaciones)),
        "anotaciones_respetado": len(anotaciones),
        "avisos": list(doc.avisos),
    })
    return base
