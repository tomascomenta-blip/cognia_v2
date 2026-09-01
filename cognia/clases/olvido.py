"""
cognia/clases/olvido.py
=======================
Que el cuaderno de un curso entero no crezca sin freno, SIN perder nunca lo
que importa.

EL PROBLEMA, EN NUMEROS DEL PROPIO FORMATO. `captura.py` guarda trozos WAV de
30 s a 16 kHz mono 16 bit: 960.000 bytes por trozo, ~115 MB por hora, ~700 MB
por una jornada de 6 h. Un curso de 180 dias son ~125 GB de audio crudo. La
transcripcion de esa misma jornada son unos cientos de KB y los apuntes,
menos. Es decir: el 99% de lo que ocupa el cuaderno es exactamente lo que
menos se vuelve a mirar, porque ya esta transcrito.

LA ESCALA DE VALOR (esto es el modulo entero; el resto es fontaneria):

  1. INTOCABLE PARA SIEMPRE -- lo que aniadio el duenio a mano
     (`cuaderno.TIPOS_DEL_USUARIO`: notas, imagenes, clips, referencias,
     marcas) y todo lo de `adjuntos/`. Es el unico contenido del cuaderno del
     que consta que a alguien le importo. Jamas se borra, ni con los umbrales
     a cero: aqui `entradas.jsonl` y `adjuntos/` no se abren para escribir.
  2. INTOCABLE -- `apuntes.json`. Son el PRODUCTO del cuaderno; borrarlos
     seria tirar justamente aquello por lo que se grabo la clase.
  3. COMPACTABLE tras N dias -- la transcripcion literal, y SOLO si esa
     jornada ya tiene apuntes DE TODO LO QUE SE DIJO. Sin apuntes no se toca:
     comprimir la fuente antes de haber destilado el producto pierde los dos a
     la vez, y es irreversible. Y "tiene apuntes" no basta: `clases/refinado.py`
     escribe apuntes MIENTRAS la clase pasa, asi que una jornada puede tener
     apuntes del primer cuarto de hora y nada del resto. Comprimir eso perdia
     para siempre la fuente de lo que nadie resumio. Por eso se le pregunta a
     `refinado.cobertura(jornada)` -- cadena declarada en las dos puntas, ver
     `_sin_refinar` aqui y la decision 8 del encabezado de refinado.py.
  4. PURGABLE tras M dias -- `audio/`, y SOLO si el STT ya escribio algo de
     esa jornada. Lo que ocupa el 99%. Los clips que el duenio guardo a mano
     NO viven ahi: viven en `adjuntos/` (los copia `almacen.copiar_adjunto`),
     asi que no caen en esta red. La condicion de "ya transcrito" es la misma
     idea que la del punto 3 un piso mas abajo: sin ella se borra la UNICA
     copia de una clase, porque `transcripcion.transcribir_pendientes()`
     existe justo para la jornada que se cerro con la cola a medias y para el
     audio que el duenio metio por fuera.

REGLA DURA: nada se borra sin que `plan()` lo pueda enseniar antes, y todo lo
que se hace deja una linea en la bitacora JSONL de la raiz del cuaderno. El
duenio tiene que poder mirar en enero por que en noviembre desaparecieron 40
GB, y la respuesta no puede ser "no se".

LOS UMBRALES (14 dias de audio, 45 de transcripcion) son un DEFAULT
CONSERVADOR, NO UNA MEDIDA. Nadie ha medido todavia cuando se deja de volver
a un audio de clase en esta maquina; 14 dias cubre de sobra el ciclo de un
examen parcial y 45 el de un trimestre. Por eso los dos salen por entorno: en
cuanto haya un dato real se cambian sin tocar codigo.

REVERSIBILIDAD, honestamente: purgar audio NO es reversible (los bytes se
van), y compactar tampoco devuelve la transcripcion literal. Lo reversible es
la DECISION, no el borrado: `plan()` la ensenia antes, `aplicar(seco=True)` la
ejecuta en vacio con las mismas cifras, y la bitacora deja constancia despues.
"""

from __future__ import annotations

import inspect
import json
import logging
import os
import re
import tempfile
import time
from datetime import datetime
from pathlib import Path

from cognia.clases import almacen as alm
from cognia.clases import cuaderno as cua

_log = logging.getLogger(__name__)

# Bitacora del olvido: JSONL append-only en la RAIZ del cuaderno, no dentro de
# la jornada -- que es justo lo que puede desaparecer. Es la unica prueba de
# por que el cuaderno pesa hoy menos que ayer.
BITACORA = "olvido.jsonl"

# Defaults conservadores, no medidos (ver cabecera). Configurables por entorno.
DIAS_AUDIO = 14
DIAS_TRANSCRIPCION = 45
# A cuanto se aspira a dejar la transcripcion al compactarla. 0.30 es donde el
# recorte deterministico todavia deja una frase de cada tres: suficiente para
# reconocer de que iba el trozo si algun dia hay que volver.
FRACCION_COMPACTA = 0.30

ENV_ACTIVO = "COGNIA_CLASES_OLVIDO"
ENV_DIAS_AUDIO = "COGNIA_CLASES_DIAS_AUDIO"
ENV_DIAS_TRANSCRIPCION = "COGNIA_CLASES_DIAS_TRANSCRIPCION"
ENV_FRACCION = "COGNIA_CLASES_FRACCION_COMPACTA"

ACCION_PURGAR_AUDIO = "purgar_audio"
ACCION_COMPACTAR = "compactar_transcripcion"
ACCION_NADA = "nada"

# Una jornada en estos estados esta VIVA (el grabador tiene ficheros abiertos
# dentro de audio/). Purgar ahi no es olvido, es sabotaje.
ESTADOS_ABIERTOS = ("grabando", "pausada")

_FIN_DE_FRASE = re.compile(r"(?<=[.!?])\s+")
# La marca de un salto en el recorte. En constante porque su longitud entra en
# el presupuesto del muestreo: escribirla a mano en un sitio y contarla a mano
# en otro es como el reparto se torcio la primera vez.
_SALTO = "[...]"


# -- politica ----------------------------------------------------------------

def politica() -> dict:
    """Los umbrales vigentes. Se leen del entorno EN CADA LLAMADA a proposito:
    un valor cacheado en el import haria que cambiar el umbral en el REPL no
    tuviera efecto hasta reiniciar, y el sintoma seria un olvido que "no hace
    caso" -- el tipo de fallo mudo que este repo ya pago caro."""
    return {
        "activo": _env_bool(ENV_ACTIVO, True),
        "dias_audio": _env_num(ENV_DIAS_AUDIO, DIAS_AUDIO, entero=True),
        "dias_transcripcion": _env_num(ENV_DIAS_TRANSCRIPCION,
                                       DIAS_TRANSCRIPCION, entero=True),
        "fraccion_compacta": _env_num(ENV_FRACCION, FRACCION_COMPACTA),
        "bitacora": BITACORA,
    }


def _env_bool(nombre: str, defecto: bool) -> bool:
    crudo = os.environ.get(nombre, "").strip().lower()
    if not crudo:
        return defecto
    if crudo in ("1", "si", "true", "on", "yes"):
        return True
    if crudo in ("0", "no", "false", "off"):
        return False
    _log.warning("olvido: %s=%r no es un si/no; se usa el defecto %s",
                 nombre, crudo, defecto)
    return defecto


def _env_num(nombre: str, defecto, entero: bool = False):
    """El numero del entorno, o el defecto CON MOTIVO VISIBLE si no cuela.

    Un umbral mal escrito no puede degradar a 0 por accidente: 0 significa
    "todo es viejo" y purgaria el curso entero de una pasada. Por eso lo
    ilegible y lo negativo vuelven al defecto y avisan, en vez de colar.
    """
    crudo = os.environ.get(nombre, "").strip()
    if not crudo:
        return defecto
    try:
        valor = int(crudo) if entero else float(crudo)
    except ValueError:
        _log.warning("olvido: %s=%r no es un numero; se usa el defecto %s",
                     nombre, crudo, defecto)
        return defecto
    if valor < 0:
        _log.warning("olvido: %s=%r es negativo; se usa el defecto %s",
                     nombre, crudo, defecto)
        return defecto
    return valor


# -- tiempo ------------------------------------------------------------------

def _epoch(ahora) -> float:
    """`ahora` como epoch. Acepta None (reloj), un epoch o un datetime.

    Que TODO el modulo reciba el instante por parametro no es cosmetica: es lo
    que permite probar el olvido sin depender del reloj de pared, y lo que
    deja simular "y si dejo pasar tres meses" ANTES de borrar nada."""
    if ahora is None:
        return time.time()
    if hasattr(ahora, "timestamp"):
        return float(ahora.timestamp())
    return float(ahora)


def _edad_dias(nombre: str, ahora: float):
    """Dias que tiene la jornada, o None si no se puede fechar.

    Dos fuentes, en este orden: `inicio_epoch` de la jornada (el instante real
    en que se pulso grabar) y, si falta, el nombre 'YYYY-MM-DD'. Si ninguna
    resuelve se devuelve None y la jornada queda INTOCABLE: lo que no se sabe
    fechar no se puede declarar viejo."""
    j = cua.cargar_jornada(nombre)
    try:
        inicio = float(j.inicio_epoch or 0.0)
    except (TypeError, ValueError):
        inicio = 0.0
    if inicio <= 0.0:
        try:
            inicio = datetime.strptime(nombre[:10], "%Y-%m-%d").timestamp()
        except ValueError:
            _log.warning("olvido: la jornada %r no tiene inicio_epoch ni un "
                         "nombre con fecha; se deja intacta", nombre)
            return None
    return (ahora - inicio) / 86400.0


# -- plan --------------------------------------------------------------------

def plan(ahora=None) -> list:
    """Las acciones que SE HARIAN, sin hacer ninguna.

    Devuelve tambien filas 'nada' cuando algo ya es viejo pero la escala de
    valor lo protege. Esas filas son la mitad util del plan: enseniar solo lo
    que se borra deja al duenio sin saber que quedo protegido y por que, que
    es justo la pregunta que se hace cuando ve el cuaderno adelgazar.
    """
    pol = politica()
    t = _epoch(ahora)
    filas = []

    if not pol["activo"]:
        return [_fila("", ACCION_NADA, "politica", 0,
                      "olvido desactivado por %s" % ENV_ACTIVO)]

    for nombre in alm.jornadas():
        d = alm.dir_jornada(nombre)
        edad = _edad_dias(nombre, t)
        if edad is None:
            filas.append(_fila(nombre, ACCION_NADA, "jornada", 0,
                               "sin fecha fiable: no se toca nada de ella"))
            continue
        j = cua.cargar_jornada(nombre)
        abierta = str(j.estado or "") in ESTADOS_ABIERTOS

        # Precondicion del punto 4: que el STT haya escrito algo de esta
        # jornada. Se mide una vez y sirve para las dos reglas.
        ruta_t = d / alm.TRANSCRIPCION
        bytes_t = ruta_t.stat().st_size if ruta_t.is_file() else 0

        # 4. audio crudo
        bytes_audio = _bytes_dir(d / alm.DIR_AUDIO)
        if bytes_audio > 0 and edad >= pol["dias_audio"]:
            if abierta:
                filas.append(_fila(nombre, ACCION_NADA, alm.DIR_AUDIO,
                                   bytes_audio,
                                   "jornada en estado %r: el grabador tiene "
                                   "ficheros abiertos ahi" % j.estado))
            elif bytes_t <= 0:
                filas.append(_fila(
                    nombre, ACCION_NADA, alm.DIR_AUDIO, bytes_audio,
                    "vieja (%.1f dias) pero SIN transcribir: borrar el audio "
                    "aqui no deja ni el WAV ni el texto. Corre antes "
                    "transcripcion.transcribir_pendientes(%r)"
                    % (edad, nombre)))
            else:
                filas.append(_fila(
                    nombre, ACCION_PURGAR_AUDIO, alm.DIR_AUDIO, bytes_audio,
                    "audio crudo de %.1f dias (umbral %s); el STT ya escribio "
                    "%s de esta jornada y los clips que guardo el duenio viven "
                    "en %s" % (edad, pol["dias_audio"], alm.TRANSCRIPCION,
                               alm.DIR_ADJUNTOS)))

        # 3. transcripcion literal
        if bytes_t > 0 and edad >= pol["dias_transcripcion"]:
            if abierta:
                filas.append(_fila(nombre, ACCION_NADA, alm.TRANSCRIPCION,
                                   bytes_t,
                                   "jornada en estado %r: sigue creciendo"
                                   % j.estado))
            elif _ya_compactada(ruta_t):
                pass          # ni accion ni proteccion que contar: sin fila
            elif not _hay_apuntes(nombre):
                filas.append(_fila(
                    nombre, ACCION_NADA, alm.TRANSCRIPCION, bytes_t,
                    "vieja (%.1f dias) pero SIN apuntes: comprimir la fuente "
                    "antes de destilar el producto pierde los dos" % edad))
            else:
                a_medias = _sin_refinar(nombre)
                if a_medias:
                    filas.append(_fila(nombre, ACCION_NADA, alm.TRANSCRIPCION,
                                       bytes_t,
                                       "vieja (%.1f dias) pero %s"
                                       % (edad, a_medias)))
                else:
                    filas.append(_fila(
                        nombre, ACCION_COMPACTAR, alm.TRANSCRIPCION, bytes_t,
                        "transcripcion literal de %.1f dias (umbral %s) con "
                        "apuntes ya generados"
                        % (edad, pol["dias_transcripcion"])))
    return filas


def _fila(jornada, accion, objetivo, tam, por_que) -> dict:
    return {"jornada": jornada, "accion": accion, "objetivo": objetivo,
            "bytes": int(tam), "por_que": por_que}


def _bytes_dir(p: Path) -> int:
    if not p.is_dir():
        return 0
    total = 0
    for f in p.rglob("*"):
        try:
            if f.is_file():
                total += f.stat().st_size
        except OSError as exc:                 # fichero en uso o ya movido
            _log.warning("olvido: no se puede medir %s: %s", f, exc)
    return total


def _hay_apuntes(nombre: str) -> bool:
    """Si la jornada tiene apuntes generados. Un `apuntes.json` que existe
    pero esta vacio NO cuenta: es el estado de "se intento y no salio", y
    tratarlo como producto destilado es exactamente el error que hace perder
    la fuente y el resumen a la vez.

    OJO: esto dice si hay ALGO, no si hay apuntes DE TODO. Lo segundo lo dice
    `_sin_refinar`, y las dos preguntas hay que hacerlas: unos apuntes del
    primer cuarto de hora tambien son "algo".
    """
    datos = alm.leer_json(alm.dir_jornada(nombre) / alm.APUNTES, {}) or {}
    if not isinstance(datos, dict):
        return bool(datos)
    return any(bool(v) for v in datos.values())


def _sin_refinar(nombre: str) -> str:
    """El motivo por el que esta transcripcion NO se puede comprimir todavia,
    o '' si si se puede.

    PERDIDA DE DATOS QUE ESTO EVITA (medida en el codigo, no supuesta):
    `clases/refinado.py` escribe apuntes cada pocos minutos MIENTRAS la clase
    pasa, con una marca de agua (`chars_entrada`) de hasta donde ha leido. Si
    el modelo local se cae -- o el disyuntor apaga el refinado -- esa marca se
    queda a mitad de la clase, pero la entrada ya existe y `_hay_apuntes`
    devuelve True. Compactar entonces sustituye la transcripcion literal por
    un 30% muestreado, o sea que la fuente del tramo que NADIE resumio
    desaparece para siempre. La compresion es irreversible; esperar no cuesta
    nada.

    POR QUE PROTEGER LA JORNADA ENTERA Y NO SOLO EL TRAMO: `_compactar_
    transcripcion` colapsa el JSONL en UN registro, y trocearlo por sesiones
    (que se cortan por materia, no por linea de transcripcion) seria inventar
    una correspondencia que hoy no existe en ningun sitio. Proteger de mas es
    reversible; comprimir de mas, no.

    Los dos fallos posibles se resuelven distinto A PROPOSITO: si `refinado`
    no esta (una instalacion sin esa pieza) nadie pudo escribir apuntes a
    medias y se compacta como siempre; si esta pero la consulta revienta, NO
    se compacta -- lo que no se puede verificar no se destruye.
    """
    try:
        from cognia.clases import refinado as ref
    except ImportError as exc:
        _log.warning("olvido: clases/refinado.py no esta (%s); no hay quien "
                     "haya escrito apuntes a medias y se compacta como "
                     "siempre", exc)
        return ""
    try:
        info = ref.cobertura(nombre)
    except Exception as exc:
        _log.warning("olvido: no se pudo comprobar la cobertura de los "
                     "apuntes de %s (%s: %s)", nombre, type(exc).__name__, exc)
        return ("no se pudo comprobar si quedan tramos sin resumir (%s: %s): "
                "la transcripcion literal no se toca hasta saberlo"
                % (type(exc).__name__, exc))
    if not info.get("toco_el_refinado") or info.get("completo"):
        return ""
    return ("el refinado en caliente dejo %d de %d chars SIN resumir: "
            "comprimir ahora perderia la fuente de lo que nadie destilo. "
            "Termina el refinado ('%s ahora') o regenera los apuntes de la "
            "jornada" % (info.get("pendiente", 0), info.get("chars_dichos", 0),
                         getattr(ref, "SUBCOMANDO_CLI", "/grabar-clase refinado")))


def _ya_compactada(ruta: Path) -> bool:
    regs = alm.leer_jsonl(ruta)
    return bool(regs) and all(bool(r.get("compactado")) for r in regs)


# -- aplicar -----------------------------------------------------------------

def aplicar(ahora=None, seco=False, orch=None) -> dict:
    """Ejecuta el plan (o lo simula si seco=True).

    `seco=True` recorre EL MISMO camino y devuelve LAS MISMAS cifras que la
    corrida real -- incluida la compactacion, que se calcula entera y solo no
    se escribe. Un simulacro que estima por otro lado no sirve para nada: lo
    que hay que poder revisar antes de borrar 40 GB es el resultado exacto.

    `orch` es opcional y va al final para no romper la firma publica. Si hay
    orquestador se le pide a `apuntes.compactar` la compactacion buena; si no
    lo hay (o falla), se usa un recorte deterministico: peor, pero real y
    siempre disponible.
    """
    t = _epoch(ahora)
    filas = plan(t)
    pol = politica()
    acciones = 0
    liberados = 0
    detalle = []

    for fila in filas:
        nombre = fila["jornada"]
        if fila["accion"] == ACCION_NADA:
            detalle.append("%s: PROTEGIDO %s -- %s"
                           % (nombre or "(politica)", fila["objetivo"],
                              fila["por_que"]))
            continue

        if fila["accion"] == ACCION_PURGAR_AUDIO:
            ganado, fallos = _purgar_audio(
                alm.dir_jornada(nombre) / alm.DIR_AUDIO, seco)
            acciones += 1
            liberados += ganado
            detalle.append("%s: audio purgado, %s liberados"
                           % (nombre, _humano(ganado)))
            for f in fallos:
                detalle.append("%s: NO se pudo borrar %s" % (nombre, f))
            _apuntar(t, nombre, fila["accion"], fila["objetivo"], ganado,
                     fila["por_que"], seco, fallos)

        elif fila["accion"] == ACCION_COMPACTAR:
            ganado, via = _compactar_transcripcion(
                alm.dir_jornada(nombre) / alm.TRANSCRIPCION,
                pol["fraccion_compacta"], seco, orch)
            if ganado <= 0:
                detalle.append("%s: transcripcion NO compactada (%s)"
                               % (nombre, via))
                continue
            acciones += 1
            liberados += ganado
            detalle.append("%s: transcripcion compactada por %s, %s liberados"
                           % (nombre, via, _humano(ganado)))
            _apuntar(t, nombre, fila["accion"], fila["objetivo"], ganado,
                     "%s [%s]" % (fila["por_que"], via), seco, [])

    return {"acciones": acciones, "bytes_liberados": int(liberados),
            "detalle": detalle, "protegido": _contar_protegido(filas)}


def _purgar_audio(directorio: Path, seco: bool):
    """Borra los trozos WAV. Devuelve (bytes, [fallos]).

    Los bytes se cuentan por fichero EFECTIVAMENTE borrado y no por el tamanio
    de la carpeta: en Windows un WAV que el grabador aun tiene abierto no se
    deja borrar, y sumarlo igual seria mentir sobre el espacio recuperado.
    La carpeta se conserva: `dir_jornada` la volveria a crear igual, y sin
    ella la jornada pareceria no haber grabado nunca nada.
    """
    ganado, fallos = 0, []
    if not directorio.is_dir():
        return 0, fallos
    for f in sorted(directorio.rglob("*")):
        if not f.is_file():
            continue
        try:
            tam = f.stat().st_size
        except OSError as exc:
            _log.warning("olvido: no se puede medir %s: %s", f, exc)
            fallos.append("%s (%s)" % (f.name, exc))
            continue
        if seco:
            ganado += tam
            continue
        try:
            f.unlink()
        except OSError as exc:                 # en uso, permisos, unidad caida
            _log.warning("olvido: no se puede borrar %s: %s", f, exc)
            fallos.append("%s (%s)" % (f.name, exc))
            continue
        ganado += tam
    return ganado, fallos


def _compactar_transcripcion(ruta: Path, fraccion: float, seco: bool, orch):
    """Sustituye la transcripcion literal por su version compactada.

    Devuelve (bytes_liberados, via/motivo). Queda UN registro con el tramo
    entero marcado `compactado`, con la forma {t0,t1,texto,fuente} que ya lee
    `cuaderno.Entrada.de_dict`: asi la vista, los apuntes y el propio olvido
    siguen leyendo la jornada sin aprender un formato nuevo, y `compactado`
    es lo que evita volver a compactar lo ya compactado cada dia.
    """
    if not ruta.is_file():
        return 0, "no hay transcripcion"
    regs = alm.leer_jsonl(ruta)
    if not regs:
        return 0, "transcripcion vacia"
    if all(bool(r.get("compactado")) for r in regs):
        return 0, "ya estaba compactada"

    texto = " ".join(str(r.get("texto") or "").strip() for r in regs).strip()
    if not texto:
        return 0, "sin texto que compactar"
    t0 = min(float(r.get("t0") or r.get("t") or 0.0) for r in regs)
    t1 = max(float(r.get("t1") or r.get("t_fin") or 0.0) for r in regs)

    compacto, via = _texto_compacto(texto, fraccion, orch)
    antes = ruta.stat().st_size
    nuevo = {"t0": t0, "t1": t1, "texto": compacto, "fuente": "compactado",
             "compactado": True, "lineas_originales": len(regs),
             "bytes_originales": antes, "via": via}
    linea = json.dumps(nuevo, ensure_ascii=False) + "\n"
    despues = len(linea.encode("utf-8"))
    if despues >= antes:
        # Compactar y ocupar mas es perder el literal a cambio de nada.
        return 0, "la version compactada no es mas chica que la original"
    if not seco:
        _escribir_jsonl(ruta, linea)
    return antes - despues, via


def _escribir_jsonl(ruta: Path, contenido: str) -> None:
    """Reemplazo ATOMICO del JSONL (temporal + os.replace), por el mismo
    motivo que `almacen.guardar_json`: un open(w) que muera a mitad deja la
    transcripcion en 0 bytes, y aqui el original ya no existe en ningun otro
    sitio del que recuperarlo."""
    fd, tmp = tempfile.mkstemp(dir=str(ruta.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(contenido)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, ruta)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError as exc:
            _log.warning("olvido: temporal huerfano %s: %s", tmp, exc)
        raise


# -- compactacion del texto --------------------------------------------------

def _texto_compacto(texto: str, fraccion: float, orch):
    """(texto_compacto, via). Primero el destilador bueno, luego el barato.

    `apuntes.compactar` es quien sabe resumir; este modulo NO reimplementa esa
    inteligencia. Pero el olvido tiene que correr igual en una maquina sin
    modelo cargado, asi que el camino deterministico es parte del contrato y
    no un plan B decorativo: purgar 40 GB de audio no puede quedar bloqueado
    porque el modelo no este levantado.
    """
    objetivo = max(200, int(len(texto) * max(0.01, float(fraccion))))
    if len(texto) <= objetivo:
        return texto, "sin recorte"
    # Se atrapa Exception y no solo ImportError A PROPOSITO: un apuntes.py que
    # reviente al importarse (o un destilador que reviente por fuera de
    # `_pedir_compactar`) subiria hasta `aplicar` y la abortaria A MITAD --
    # despues de haber borrado el audio de las jornadas anteriores y sin
    # devolver ni el resumen ni las cifras. El motivo queda en el log; lo que
    # no puede pasar es que se caiga callando.
    try:
        from cognia.clases import apuntes as _ap
        salida = _pedir_compactar(_ap, texto, objetivo, orch)
    except Exception as exc:
        _log.warning("olvido: el destilador no esta disponible (%s: %s); se "
                     "compacta con recorte deterministico",
                     type(exc).__name__, exc)
    else:
        if salida:
            return salida, "apuntes.compactar"
    return _recorte_uniforme(texto, objetivo), "recorte uniforme"


def _pedir_compactar(modulo, texto: str, objetivo: int, orch):
    """Llama a `apuntes.compactar` adaptandose a su firma.

    Se inspecciona la firma en vez de asumirla porque el destilador puede o no
    aceptar orquestador y tope. Cualquier fallo suyo degrada a None CON MOTIVO
    en el log: que el modelo no responda no puede impedir liberar el audio,
    que es la parte que funciona siempre.
    """
    fn = getattr(modulo, "compactar", None)
    if not callable(fn):
        _log.warning("olvido: cognia.clases.apuntes no expone compactar(); se "
                     "compacta con recorte deterministico")
        return None
    extra = {}
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError) as exc:
        _log.warning("olvido: no se puede leer la firma de compactar(): %s", exc)
        params = {}
    if "orch" in params:
        extra["orch"] = orch
    # El tope va por nombre y no posicional: `compactar(texto, tope_chars)` lo
    # tiene como obligatorio, y otra firma podria no tenerlo. Los nombres
    # estan en orden de concreto a generico.
    for clave in ("tope_chars", "objetivo", "tope", "max_chars", "limite"):
        if clave in params:
            extra[clave] = objetivo
            break
    try:
        salida = fn(texto, **extra)
    except Exception as exc:                   # el destilador no es critico
        _log.warning("olvido: apuntes.compactar fallo (%s: %s); se compacta "
                     "con recorte deterministico", type(exc).__name__, exc)
        return None
    if isinstance(salida, dict):
        salida = salida.get("texto") or salida.get("resumen") or ""
    if not isinstance(salida, str) or not salida.strip():
        _log.warning("olvido: apuntes.compactar devolvio %s vacio o no-texto; "
                     "se compacta con recorte deterministico",
                     type(salida).__name__)
        return None
    if len(salida) >= len(texto):
        _log.warning("olvido: apuntes.compactar no acorto (%d -> %d); se "
                     "compacta con recorte deterministico",
                     len(texto), len(salida))
        return None
    return salida.strip()


def _recorte_uniforme(texto: str, objetivo: int) -> str:
    """Recorte deterministico: frases repartidas por TODO el tramo.

    Uniforme y no "los primeros N caracteres" por un motivo concreto: los
    primeros minutos de una clase son pasar lista y repetir lo del dia
    anterior. Un muestreo parejo conserva la forma de la sesion entera, que es
    lo unico que se le puede pedir a un recorte sin modelo. Los saltos se
    marcan con `_SALTO` para que nadie lea el resultado como literal.
    """
    frases = [f.strip() for f in _FIN_DE_FRASE.split(texto) if f.strip()]
    if len(frases) <= 1:
        return texto[:objetivo].rstrip() + " " + _SALTO
    medio = sum(len(f) for f in frases) / float(len(frases))
    # Cada hueco entre dos frases no contiguas mete `_SALTO` mas su espacio, y
    # ese coste hay que meterlo en la cuenta de cuantas caben. Sin el, `caben`
    # sobreestimaba, `paso` salia corto y el bucle se quedaba sin presupuesto a
    # media tira: el "reparto uniforme" degradaba a "los primeros dos tercios"
    # sin decirlo (medido aqui: con 60 frases y objetivo=400 la ultima que
    # entraba era la 40 de 59, y el resto de la clase no se muestreaba nunca).
    coste_salto = len(_SALTO) + 1
    caben = max(1, int(objetivo / max(1.0, medio + 1.0 + coste_salto)))
    # Techo y no suelo: `len // caben` deja mas candidatos de los que caben y
    # los ultimos se pierden en el break, que es justo la cola del tramo.
    paso = max(1, -(-len(frases) // caben))
    salida, usado, previa = [], 0, -2
    for i in range(0, len(frases), paso):
        f = frases[i]
        if usado + len(f) > objetivo and salida:
            break
        if i != previa + 1 and salida:
            salida.append(_SALTO)
            usado += coste_salto
        salida.append(f)
        usado += len(f) + 1
        previa = i
    if not salida:                             # una sola frase gigante
        return texto[:objetivo].rstrip() + " " + _SALTO
    if previa < len(frases) - 1:
        salida.append(_SALTO)
    return " ".join(salida)


# -- bitacora y cuentas ------------------------------------------------------

def _apuntar(t, jornada, accion, objetivo, tam, por_que, seco, fallos) -> None:
    """Una linea por accion en la bitacora, TAMBIEN en seco (marcada). Un
    simulacro que no deja rastro es indistinguible de no haber corrido, y el
    duenio necesita poder demostrar que reviso antes de borrar."""
    try:
        alm.apendar(alm.raiz() / BITACORA, {
            "t": t, "jornada": jornada, "accion": accion, "objetivo": objetivo,
            "bytes": int(tam), "por_que": por_que, "seco": bool(seco),
            "fallos": list(fallos),
        })
    except Exception as exc:
        # Exception y no solo OSError: esto corre DESPUES de un borrado
        # irreversible. Que la bitacora falle es malo (la accion queda sin
        # constancia, y por eso el aviso es explicito), pero dejar subir la
        # excepcion es peor: aborta la corrida entera sin devolver siquiera el
        # detalle de lo que ya se borro.
        _log.warning("olvido: no se pudo escribir la bitacora (%s: %s); la "
                     "accion %s sobre %s queda SIN constancia",
                     type(exc).__name__, exc, accion, jornada)


def bitacora(limite: int = 50) -> list:
    """Las ultimas lineas de la bitacora, de la mas nueva a la mas vieja. Es
    la puerta de diagnostico del modulo: sin esto, "el cuaderno pesa menos"
    no tiene explicacion posible desde fuera."""
    regs = alm.leer_jsonl(alm.raiz() / BITACORA)
    regs.reverse()
    return regs[:max(0, int(limite))]


def _contar_protegido(filas: list) -> int:
    """Cuantas piezas dejo INTACTAS la escala de valor: cada entrada del
    duenio, cada adjunto y cada cosa vieja que una regla salvo (las filas
    'nada'). Es el numero con el que se audita el modulo: si sube el espacio
    liberado y este no baja, el olvido esta haciendo justo su trabajo."""
    n = sum(1 for f in filas if f.get("accion") == ACCION_NADA)
    for nombre in alm.jornadas():
        d = alm.dir_jornada(nombre)
        for e in alm.leer_jsonl(d / alm.ENTRADAS):
            if str(e.get("tipo") or "") in cua.TIPOS_DEL_USUARIO:
                n += 1
        adj = d / alm.DIR_ADJUNTOS
        if adj.is_dir():
            n += sum(1 for f in adj.rglob("*") if f.is_file())
    return n


def _humano(n) -> str:
    """Bytes en algo que se pueda leer en el REPL. El numero exacto va en la
    bitacora; aqui manda que se entienda de un vistazo."""
    tam = float(n)
    for unidad in ("B", "KB", "MB", "GB"):
        if tam < 1024.0 or unidad == "GB":
            return ("%d %s" % (tam, unidad) if unidad == "B"
                    else "%.1f %s" % (tam, unidad))
        tam /= 1024.0
    return "%d B" % n
