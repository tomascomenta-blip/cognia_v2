"""
cognia/clases/almacen.py
========================
Persistencia INCREMENTAL de una jornada de clases.

POR QUE ASI. Una jornada son 5-7 horas de grabacion. Cualquier diseno que
guarde "al final" pierde la manana entera si el portatil se suspende, si el
REPL muere o si se va la luz -- y eso no es un caso raro, es el caso NORMAL
de un dia de clase. Aqui todo se escribe segun pasa:

  - Los hechos van a ficheros JSONL **append-only**, una linea por hecho. Un
    fichero a medio escribir pierde COMO MUCHO la ultima linea, y leerlo
    salta esa linea sin romperse.
  - El estado mutable (que materia va, si esta pausado) va a un JSON chico
    que se escribe de forma ATOMICA (fichero temporal + os.replace), que en
    Windows es lo unico que no deja un JSON truncado si el proceso muere en
    mitad del write.
  - El audio va en TROZOS numerados, no en un WAV gigante: un WAV de 6 horas
    con la cabecera sin cerrar es un fichero ilegible; 700 trozos de 30 s
    son 699 trozos buenos y uno malo.

Nada aqui sabe de audio, de materias ni del modelo: es solo el disco.

Lo unico que sale de aqui hacia arriba son dos eventos del bus interno
("clase.entrada" y "clase.json"), y se emiten en este modulo a proposito:
el porque esta escrito en _emitir(). Solo se emiten para escrituras que caen
DENTRO de raiz() (ver _bajo_la_raiz) y NO entran en el historial del bus (ver
_publicar_volatil): las dos cosas que hacian que el evento mintiera o que
dejaran ciego al panel de analiticas.

DISPOSICION EN DISCO

    ~/.cognia/clases/
      jornadas/
        2026-08-31/
          jornada.json          estado (atomico)
          transcripcion.jsonl   {t0,t1,texto,fuente}      append-only
          entradas.jsonl        {t,tipo,...}              append-only
          cortes.jsonl          {t,materia,confianza,por} append-only
          audio/000001.wav      trozos crudos (purgables)
          adjuntos/...          imagenes y clips del usuario
          apuntes.json          apuntes generados (atomico)
      cuaderno.json             indice global de materias (atomico)
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import time
from pathlib import Path

log = logging.getLogger(__name__)

# Nombre de los ficheros. En constantes porque los lee tambien la vista HTML
# y el olvido, y una errata suelta en uno de los tres deja un cuaderno mudo.
JORNADA = "jornada.json"
TRANSCRIPCION = "transcripcion.jsonl"
ENTRADAS = "entradas.jsonl"
CORTES = "cortes.jsonl"
APUNTES = "apuntes.json"
DIR_AUDIO = "audio"
DIR_ADJUNTOS = "adjuntos"
INDICE = "cuaderno.json"


def raiz() -> Path:
    """~/.cognia/clases, creada. COGNIA_CLASES_DIR la mueve (util en tests:
    sin esto los tests escribirian en el cuaderno REAL del dueno)."""
    env = os.environ.get("COGNIA_CLASES_DIR", "").strip()
    base = Path(env) if env else Path.home() / ".cognia" / "clases"
    base.mkdir(parents=True, exist_ok=True)
    return base


def dir_jornada(nombre: str) -> Path:
    d = raiz() / "jornadas" / _seguro(nombre)
    (d / DIR_AUDIO).mkdir(parents=True, exist_ok=True)
    (d / DIR_ADJUNTOS).mkdir(parents=True, exist_ok=True)
    return d


def _seguro(nombre: str) -> str:
    """Un nombre de jornada/materia que venga del usuario NO puede salirse de
    la carpeta. Se filtra a lo que es seguro en un nombre de fichero en
    Windows y se recorta; vacio -> 'sin-nombre'."""
    limpio = "".join(c if (c.isalnum() or c in " -_.") else "-"
                     for c in (nombre or "").strip())
    limpio = limpio.strip(" .-")[:80]
    return limpio or "sin-nombre"


# ── Aviso al bus ─────────────────────────────────────────────────────────────

# 0,25 s. NO MEDIDO: es un tope de PACIENCIA con el suscriptor, no un
# percentil de nada. Existe porque esto corre en el hilo que esta escribiendo
# la clase (ver _emitir): pasado ese rato el que escucha ya esta robandole
# tiempo al grabador, y hay que poder verlo en vez de adivinarlo.
_TOPE_SUSCRIPTOR_S = 0.25

# Ultimo fallo del canal de avisos, para la puerta de diagnostico. Se guarda
# el ULTIMO y se avisa solo la PRIMERA vez por via (ver _degradar_una_vez).
_avisos_dados: set = set()
_ultimo_fallo: dict = {}


def ultimo_fallo_bus() -> dict:
    """Lo ultimo que se rompio avisando al bus, o {} si nunca fallo.

    Es la puerta de diagnostico del modulo (CLAUDE.md: un subsistema que se
    calla y uno que no esta cableado no pueden verse igual desde fuera). Como
    el aviso es log-once para no escribir miles de trazas en una clase de
    cinco horas, sin esto la segunda mitad de la jornada no dejaria rastro
    ninguno de que el bus sigue roto.
    """
    return dict(_ultimo_fallo)


def _degradar_una_vez(donde: str, motivo: str, accion: str = "") -> None:
    """Avisa por el canal de degradacion de la casa, UNA vez por `donde`.

    POR QUE LOG-ONCE. Una jornada son 5-7 horas y decenas de miles de lineas.
    El codigo anterior logueaba con exc_info=True en CADA emision: un bus roto
    (o un suscriptor roto) no producia un aviso, producia un log de megabytes
    en el que el fallo real quedaba enterrado. El estado que importa ("el bus
    sigue caido") se consulta con ultimo_fallo_bus(), no releyendo el log.

    POR QUE cognia.ux.events y no logging a secas: es el canal que CLAUDE.md
    exige para toda degradacion (lo pinta el REPL en ambar y lo recoge la
    telemetria). El import es perezoso y va en try: este modulo es la capa de
    disco del cuaderno y no puede dejar de importarse porque cambie la UX.
    """
    _ultimo_fallo.clear()
    _ultimo_fallo.update({"donde": donde, "motivo": motivo, "t": time.time()})
    if donde in _avisos_dados:
        return
    _avisos_dados.add(donde)
    log.warning("clases.almacen: %s -- %s", donde, motivo)
    try:
        from cognia.ux import events as _ux
        _ux.emitir(_ux.Degradado(donde=donde, motivo=motivo,
                                 accion_sugerida=accion))
    except Exception as exc:
        # El canal de avisos es lo que se acaba de romper: se deja constancia
        # en el log y se sigue. Nunca un except mudo.
        log.warning("clases.almacen: tampoco pude avisar por ux.events (%s)",
                    exc)


def _bajo_la_raiz(ruta: Path) -> bool:
    """True si `ruta` cae dentro del cuaderno de clases (raiz()).

    POR QUE EXISTE. `apendar` y `guardar_json` NO son privadas de este
    paquete: cognia/compilador/bitacora.py reusa estas mismas primitivas (y
    hace bien, son las que hacen fsync y os.replace). Sin este filtro toda
    linea que el compilador escribe en ~/.cognia/compilador salia anunciada
    como "clase.entrada", o sea: el evento MENTIA sobre su origen y quien
    mira una clase en vivo se comia las escrituras de otro subsistema.

    Se decide por la RUTA y no por quien llama: la ruta es el dato que ya
    viaja dentro del evento, no depende de la pila y sigue siendo cierta si
    manana llama un modulo nuevo. Si raiz() no se puede resolver (env var
    apuntando a algo imposible) se devuelve False: mejor un evento de menos
    que uno que miente.
    """
    try:
        base = raiz().resolve()
        objetivo = Path(ruta).resolve()
    except OSError:
        return False
    return objetivo == base or base in objetivo.parents


def _publicar_volatil(evento: str, datos: dict) -> None:
    """Entrega el evento a los suscriptores SIN meterlo en el historial.

    POR QUE NO SE USA events.emit(). El bus guarda un anillo de 200 eventos
    (_HISTORIAL_MAX) y cognia/analytics/panel.py:resumen_eventos() lo usa como
    su UNICA fuente de diagnostico de la sesion. Una clase de cinco horas mete
    decenas de miles de "clase.entrada": a los primeros segundos de grabacion
    el anillo es 100% cuaderno y el panel queda ciego para todo lo demas
    (tools, sentinel, agente). Estos eventos son de ALTA FRECUENCIA y de valor
    solo en vivo -- releerlos del historial no le sirve a nadie, porque el
    dato de verdad esta en el JSONL de la jornada.

    ASI QUE se hace lo que hace bus.emit() menos la linea del historial:
    misma forma de evento ({"evento", "ts", ...datos}), mismos suscriptores
    (los del evento MAS los del comodin "*"), mismo aislamiento por callback.
    Se toma el lock del bus para leer los suscriptores por la misma razon que
    el: un callback puede (de)suscribir durante la emision.

    Si algun dia events.py ofrece una emision volatil nativa, este es el unico
    sitio que hay que cambiar; el fallback esta en _emitir().
    """
    from cognia.events import get_bus

    bus = get_bus()
    ev = {"evento": evento, "ts": time.time(), **datos}
    with bus._lock:
        callbacks = list(bus._subs.get(evento, [])) + \
            list(bus._subs.get("*", []))
    for cb in callbacks:
        t0 = time.perf_counter()
        try:
            cb(ev)
        except Exception as exc:
            _degradar_una_vez(
                "clases.almacen.suscriptor",
                "un suscriptor de %r lanzo %s: %s"
                % (evento, type(exc).__name__, exc),
                accion="revisar el codigo que escucha %r" % (evento,))
        tardo = time.perf_counter() - t0
        if tardo > _TOPE_SUSCRIPTOR_S:
            _degradar_una_vez(
                "clases.almacen.suscriptor_lento",
                "un suscriptor de %r tardo %.2f s (tope %.2f): esta frenando "
                "la grabacion" % (evento, tardo, _TOPE_SUSCRIPTOR_S),
                accion="que el suscriptor encole y devuelva en el acto")


def _emitir(evento: str, **datos) -> None:
    """Publica en el bus interno sin poder tumbar la escritura que lo llama.

    POR QUE EN ESTE MODULO Y NO EN LOS LLAMANTES. `apendar` es el UNICO punto
    por el que pasa toda linea nueva de una jornada (transcripcion.jsonl,
    entradas.jsonl, cortes.jsonl) y `guardar_json` el UNICO que escribe
    jornada.json y apuntes.json. Emitiendo en esos dos sitios se cubre el
    100% de los cambios de estado del cuaderno con cuatro lineas, en vez de
    instrumentar cuatro modulos (jornada, cuaderno, apuntes, transcripcion) o
    poner a quien mira en vivo a hacer polling del disco.

    POR QUE EL try/except, DE VERDAD. El caso que se documentaba antes -- el
    suscriptor que REVIENTA -- ya lo aisla el bucle de _publicar_volatil. El
    modo de fallo caro es OTRO y no estaba escrito: esto corre EN EL HILO DEL
    ESCRITOR, o sea en el mismo hilo que esta grabando la clase, asi que un
    suscriptor LENTO (una vista que repinta, un socket que espera, un fsync
    ajeno) no rompe nada: retrasa la siguiente linea de transcripcion. Un
    except no protege de eso -- no hay forma de interrumpir un callback en
    Python sin cambiar el hilo, y cambiar el hilo romperia la garantia que
    hace util a este evento (cuando llega, el dato YA esta en disco). Lo que
    si se hace es MEDIRLO y avisar (ver _TOPE_SUSCRIPTOR_S): quien escucha
    tiene que encolar y devolver en el acto, y si no lo hace se ve.

    El try de aqui cubre lo que queda: que el bus no este (events.py movido,
    roto o con otra forma). Cuando eso pasa se cae a la emision publica --
    entregar el evento importa mas que no ensuciar el historial -- y se avisa
    una sola vez por el canal de degradacion.

    El import va DENTRO a proposito: almacen.py es la capa de disco del
    cuaderno y no puede empezar a fallar al importarse porque cambie
    events.py.
    """
    try:
        _publicar_volatil(evento, datos)
    except Exception as exc:
        try:
            from cognia.events import emit
            emit(evento, **datos)
        except Exception as exc2:
            _degradar_una_vez(
                "clases.almacen.bus",
                "no se pudo emitir %r (%s: %s)"
                % (evento, type(exc2).__name__, exc2),
                accion="revisar cognia/events.py")
            return
        _degradar_una_vez(
            "clases.almacen.bus_volatil",
            "el bus no admite emision volatil (%s: %s); los eventos de clase "
            "vuelven a entrar en el historial y el panel de analiticas se "
            "queda sin sitio" % (type(exc).__name__, exc),
            accion="revisar cognia/events.py (EventBus._subs/_lock)")


# ── JSONL append-only ────────────────────────────────────────────────────────

def apendar(ruta: Path, registro: dict) -> None:
    """Una linea JSON al final, con flush. El flush no es opcional: sin el,
    los ultimos minutos de clase viven en el buffer del proceso y se pierden
    justo en el corte que este fichero existe para sobrevivir.

    Avisa con "clase.entrada" (ruta + registro) despues del fsync y con el
    fichero ya cerrado: quien escuche puede leer la linea de disco al recibir
    el evento, y si revienta la linea ya esta guardada. Ver _emitir().

    Solo avisa si la ruta cae dentro del cuaderno de clases: esta funcion la
    reusan otros subsistemas (ver _bajo_la_raiz) y un evento "clase.entrada"
    que no es de una clase es peor que ningun evento.
    """
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(registro, ensure_ascii=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    if _bajo_la_raiz(ruta):
        _emitir("clase.entrada", ruta=str(ruta), registro=registro)


def leer_jsonl(ruta: Path) -> list:
    """Los registros de un JSONL, SALTANDO las lineas rotas.

    La ultima linea de un fichero que se corto a mitad no es JSON. Reventar
    ahi tiraria la jornada entera por el ultimo medio segundo: se salta y se
    sigue, que es justo para lo que se eligio el formato.
    """
    if not ruta.exists():
        return []
    fuera = []
    with ruta.open("r", encoding="utf-8", errors="replace") as fh:
        for linea in fh:
            linea = linea.strip()
            if not linea:
                continue
            try:
                fuera.append(json.loads(linea))
            except ValueError:
                continue
    return fuera


# ── JSON atomico ─────────────────────────────────────────────────────────────

def guardar_json(ruta: Path, datos) -> None:
    """Escribe con fichero temporal + os.replace (atomico en NTFS).

    Un `open(w)` normal trunca el fichero ANTES de escribir: si el proceso
    muere ahi, el estado de la jornada queda en 0 bytes y la manana entera
    pasa a ser irrecuperable aunque los JSONL esten intactos.

    Avisa con "clase.json" (ruta + datos) DESPUES del os.replace, nunca antes:
    un suscriptor que reaccione leyendo el fichero tiene que encontrarse el
    contenido nuevo entero, no el viejo ni un temporal. Ver _emitir().

    Y solo si la ruta cae dentro del cuaderno de clases (ver _bajo_la_raiz):
    el compilador escribe su indice con esta misma funcion y eso no es una
    clase.
    """
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
    if _bajo_la_raiz(ruta):
        _emitir("clase.json", ruta=str(ruta), datos=datos)


def leer_json(ruta: Path, defecto=None):
    """El JSON, o `defecto` si no esta o esta roto. Nunca lanza: un indice
    corrupto no puede impedir grabar la clase de hoy."""
    if not ruta.exists():
        return defecto
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return defecto


# ── Adjuntos ─────────────────────────────────────────────────────────────────

def _siguiente_adjunto(destino_dir: Path, prefijo: str) -> int:
    """El numero mas alto en uso + 1. NO la cuenta de ficheros.

    Contar reutiliza nombres: con img_0001..img_0003 en disco, borrar dos deja
    la cuenta en 1 y el siguiente adjunto vuelve a llamarse img_0002, PISANDO
    el fichero al que ya apunta una entrada del cuaderno. Leyendo el maximo el
    numero solo sube, que es lo que hace falta para que una referencia
    guardada siga significando lo mismo dentro de seis meses.

    Lo que no parsea como numero se ignora (un adjunto renombrado a mano no
    puede impedir guardar el siguiente).
    """
    mayor = 0
    for p in destino_dir.glob(prefijo + "_*"):
        cuerpo = p.stem[len(prefijo) + 1:]
        if cuerpo.isdigit():
            mayor = max(mayor, int(cuerpo))
    return mayor + 1


def copiar_adjunto(jornada: str, origen, prefijo: str = "adj") -> str:
    """Copia un fichero del usuario DENTRO de la jornada y devuelve su nombre.

    Se copia y no se referencia la ruta original a proposito: el cuaderno
    tiene que seguir enseniando la foto de la pizarra dentro de seis meses,
    cuando esa captura ya no este en Descargas.

    `prefijo` pasa por _seguro como el nombre de jornada: es un argumento que
    puede venir del usuario, y una barra ahi escribiria el adjunto FUERA de
    adjuntos/ (o fuera del cuaderno entero con "..").
    """
    origen = Path(origen).expanduser()
    if not origen.is_file():
        raise FileNotFoundError(str(origen))
    prefijo = _seguro(prefijo)
    destino_dir = dir_jornada(jornada) / DIR_ADJUNTOS
    n = _siguiente_adjunto(destino_dir, prefijo)
    destino = destino_dir / ("%s_%04d%s" % (prefijo, n, origen.suffix.lower()))
    shutil.copy2(origen, destino)
    return destino.name


# 25 s. NO MEDIDO: es un tope de paciencia, no un percentil de nada. La
# descarga la dispara el duenio en mitad de una clase y bloquea el REPL
# mientras corre, asi que el numero se eligio por lo que se aguanta mirando
# una pantalla quieta. Lo que si es duro: urllib SIN timeout espera para
# siempre (el default de urlopen es None), y ese cuelgue eterno es justo el
# fallo que este numero existe para impedir.
TIMEOUT_DESCARGA = 25

# Wikimedia responde 429 a los User-Agent genericos y exige uno identificable
# con forma de contacto (su politica de UA). Es la fuente tipica de la imagen
# que se pega en una clase, asi que el UA lleva proyecto y una URL donde ver
# quien es. Sin esto la descarga falla solo en unas fuentes y no en otras,
# que es el peor modo de fallo posible para diagnosticar.
USER_AGENT_DESCARGA = "Cognia/1.0 (cuaderno de clases; +https://pypi.org/project/cognia-ai/)"

# Trozo de lectura. 64 KB es el compromiso de siempre entre llamadas al socket
# y memoria retenida; lo importante no es el numero sino que se lea A TROZOS,
# porque leer entero antes de comprobar el tamanio haria inutil el tope.
_TROZO_DESCARGA = 64 * 1024


def _extensiones_de_imagen(tabla: dict) -> dict:
    """Invierte {extension: mime} a {mime: extension} para elegir con que
    nombre se guarda lo que baja de la red.

    La tabla que entra es la de vista.py y no una copia local: si el cuaderno
    solo sabe embeber seis formatos, descargar un septimo dejaria el fichero
    en disco y la entrada MUDA en el HTML. Una sola fuente de verdad evita
    exactamente ese desajuste.

    Cuando dos extensiones comparten MIME (.jpg y .jpeg) gana la primera de la
    tabla, para que la misma url baje siempre con el mismo nombre.
    """
    fuera = {}
    for ext, mime in tabla.items():
        fuera.setdefault(mime, ext)
    return fuera


def descargar_adjunto(jornada: str, url: str, prefijo: str = "img") -> str:
    """Baja una imagen de la web DENTRO de la jornada y devuelve su nombre.

    Devuelve lo mismo que copiar_adjunto (el nombre del fichero dentro de
    adjuntos/, no la ruta) porque los dos alimentan el mismo campo `adjunto`
    del cuaderno; quien llama no tiene que saber de donde vino.

    QUE SE COMPRUEBA Y POR QUE:
      - Solo http/https, en la url tecleada Y en la url FINAL. Mirar solo la
        tecleada no basta: urllib sigue las redirecciones por su cuenta y su
        HTTPRedirectHandler admite tambien ftp://, asi que un servidor http
        podia mandar la descarga a otro esquema y saltarse la guardia. urllib
        abre ademas file://, y una url pegada sin mirar copiaria un fichero
        cualquiera del disco dentro del cuaderno.
      - El Content-Type contra la tabla de imagenes de vista.py (ver
        _extensiones_de_imagen): lo que no se pueda enseniar no se guarda.
      - El tamanio por DOS caminos distintos, y el primero antes siquiera de
        abrir el fichero de destino: el Content-Length que declara el
        servidor corta sin tocar el disco, y el conteo real segun se lee corta
        cuando el servidor no lo declara o miente. Se corta en el tope por
        adjunto de vista.py, que es
        el mismo a partir del cual la vista ya se niega a embeber: bajar algo
        que la vista rechazaria seria ocupar disco para nada.

    Se escribe en un .tmp y se hace os.replace al final, como guardar_json:
    un corte a mitad de descarga no puede dejar un adjunto medio escrito con
    nombre definitivo, porque eso se ve como una imagen corrupta para siempre.

    Todo fallo LANZA con la url y el paso en el mensaje. Devolver None dejaria
    una entrada del cuaderno apuntando a un adjunto que no existe, y "no se
    pudo bajar" seria indistinguible de "nadie lo pidio".
    """
    # Imports perezosos: vista.py importa a almacen (al reves seria un ciclo)
    # y urllib solo hace falta si de verdad se baja algo.
    import urllib.parse
    import urllib.request

    from cognia.clases import vista

    url = (url or "").strip()
    esquema = urllib.parse.urlsplit(url).scheme.lower()
    if esquema not in ("http", "https"):
        raise ValueError("descargar_adjunto solo acepta http/https, llego %r"
                         % (url,))

    tope = int(vista.TOPE_ADJUNTO)
    permitidos = _extensiones_de_imagen(vista._MIME_IMAGEN)

    peticion = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT_DESCARGA})
    try:
        respuesta = urllib.request.urlopen(peticion,
                                           timeout=TIMEOUT_DESCARGA)
    except Exception as exc:
        raise OSError("no se pudo abrir %s (%s s de espera): %s"
                      % (url, TIMEOUT_DESCARGA, exc)) from exc

    with respuesta:
        # La url FINAL, ya seguidas las redirecciones (ver el docstring).
        final = respuesta.geturl() or url
        if urllib.parse.urlsplit(final).scheme.lower() not in ("http", "https"):
            raise ValueError(
                "%s redirigio a %r, que no es http/https: no se descarga"
                % (url, final))

        mime = (respuesta.headers.get("Content-Type") or "")
        mime = mime.split(";")[0].strip().lower()
        if mime not in permitidos:
            raise ValueError(
                "%s no devolvio una imagen: Content-Type %s. El cuaderno solo "
                "guarda %s" % (url, mime or "(ninguno)",
                               ", ".join(sorted(permitidos))))
        extension = permitidos[mime]

        declarado = (respuesta.headers.get("Content-Length") or "").strip()
        if declarado.isdigit() and int(declarado) > tope:
            raise ValueError(
                "%s declara %.1f MB y el tope por adjunto son %.0f MB: no se "
                "descarga" % (url, int(declarado) / 1048576.0, tope / 1048576.0))

        # El prefijo puede venir del usuario: por _seguro antes de construir
        # ninguna ruta con el (ver copiar_adjunto). Y el numero se lee del
        # maximo en uso, no de la cuenta de ficheros (ver _siguiente_adjunto).
        prefijo = _seguro(prefijo)
        destino_dir = dir_jornada(jornada) / DIR_ADJUNTOS
        n = _siguiente_adjunto(destino_dir, prefijo)
        destino = destino_dir / ("%s_%04d%s" % (prefijo, n, extension))

        fd, tmp = tempfile.mkstemp(dir=str(destino_dir), suffix=".tmp")
        leidos = 0
        try:
            with os.fdopen(fd, "wb") as fh:
                while True:
                    trozo = respuesta.read(_TROZO_DESCARGA)
                    if not trozo:
                        break
                    leidos += len(trozo)
                    if leidos > tope:
                        raise ValueError(
                            "%s se paso del tope por adjunto (%.0f MB) tras "
                            "leer %.1f MB: se aborta y no queda fichero"
                            % (url, tope / 1048576.0, leidos / 1048576.0))
                    fh.write(trozo)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, destino)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    return destino.name


def ruta_adjunto(jornada: str, nombre: str) -> Path:
    return dir_jornada(jornada) / DIR_ADJUNTOS / _seguro(nombre)


# ── Jornadas ─────────────────────────────────────────────────────────────────

# Fecha de jornada ya leida, por HUELLA de jornada.json (ruta + mtime_ns +
# tamanio). Medido en este disco con 180 jornadas: listar las carpetas cuesta
# 0,90 ms, hacer stat de los 180 jornada.json 2,30 ms y leerlos y parsearlos
# 11,11 ms. jornadas() no es una llamada rara -- cuaderno.py la usa cinco
# veces en un mismo flujo, vista_viva.py una vez por refresco de la pagina y
# materias.py la mete en la clave de su cache de vocabulario -- asi que pagar
# los 11 ms enteros cada vez seria pagar el curso completo por una pregunta
# que casi siempre tiene la misma respuesta. Con la huella se paga el stat
# (2,30 ms) y solo se parsea lo que CAMBIO: en una clase en vivo, una sola
# jornada de todas las del curso.
#
# La huella es fiable porque el unico que escribe jornada.json es
# guardar_json, que termina en os.replace: el fichero nuevo trae mtime y
# tamanio nuevos. Queda el hueco clasico (dos escrituras del MISMO tamanio
# dentro de la misma marca de tiempo), y aqui es inofensivo a proposito:
# `inicio_epoch` se fija UNA vez al pulsar grabar (jornada.py, arrancar) y ya
# no vuelve a cambiar en toda la jornada, asi que lo que podria quedarse
# rancio es justo el campo que no se mueve.
_CACHE_FECHA: dict = {}

# 512 huellas. NO MEDIDO: es un tope de MEMORIA, no un percentil. Cada
# jornada viva aporta una entrada (mas una vieja por cada reescritura de su
# jornada.json), asi que un curso entero no llega; el tope existe para que un
# proceso larguisimo -- o una bateria de tests que crea decenas de cuadernos
# en tmp_path -- no acumule para siempre. Al llegar se vacia entero en vez de
# desalojar por antiguedad: reconstruirla cuesta los 11 ms medidos arriba y
# no merece llevar un orden de uso.
_TOPE_CACHE_FECHA = 512


def _epoch_del_nombre(nombre: str):
    """La fecha que promete la CONVENCION 'YYYY-MM-DD' del nombre, o None.

    Es el ultimo recurso, no la fuente: el nombre lo puede haber puesto
    cualquiera. Pero hace falta, porque la jornada de HOY recien creada
    todavia no tiene jornada.json (dir_jornada crea la carpeta; el
    inicio_epoch no se escribe hasta que se pulsa grabar) y sin este respaldo
    se iria al fondo de la lista justo el dia que es la que importa.

    Se lee la fecha a medianoche LOCAL, igual que olvido._edad_dias, para que
    las dos piezas fechen la misma carpeta igual.
    """
    try:
        return float(time.mktime(time.strptime(str(nombre)[:10], "%Y-%m-%d")))
    except (ValueError, OverflowError, TypeError):
        return None


def _inicio_epoch(ruta: Path) -> float:
    """`inicio_epoch` de un jornada.json, con la cache por huella. 0.0 si no
    hay fichero, no se puede leer o el campo no es un numero util."""
    try:
        st = os.stat(ruta)
    except OSError:
        return 0.0                  # sin jornada.json (o ilegible): sin dato
    huella = (str(ruta), st.st_mtime_ns, st.st_size)
    if huella in _CACHE_FECHA:
        return _CACHE_FECHA[huella]
    crudo = leer_json(ruta, {}) or {}
    try:
        inicio = float(crudo.get("inicio_epoch") or 0.0)
    except (TypeError, ValueError):
        inicio = 0.0                # jornada.json escrito por otra cosa
    if inicio < 0.0:
        inicio = 0.0
    if len(_CACHE_FECHA) >= _TOPE_CACHE_FECHA:
        _CACHE_FECHA.clear()
    _CACHE_FECHA[huella] = inicio
    return inicio


def _fecha_del_dir(d: Path):
    """La fecha de la jornada que vive en `d`, o None si no se puede fechar."""
    inicio = _inicio_epoch(d / JORNADA)
    if inicio > 0.0:
        return inicio
    return _epoch_del_nombre(d.name)


def fecha_de(nombre: str):
    """Cuando EMPEZO la jornada `nombre` (epoch), o None si no hay forma.

    Dos fuentes, en este orden y por este motivo:

      1. `inicio_epoch` de jornada.json. Es el instante real en que se pulso
         grabar, lo escribe el propio grabador y sobrevive a que alguien
         copie, importe o renombre la carpeta.
      2. El nombre 'YYYY-MM-DD'. Es una CONVENCION -- la que pone
         jornada.nombre_de_hoy() -- y por eso va segunda: se rompe en cuanto
         una carpeta llega de otro sitio o la renombra una mano humana.

    None significa "esta carpeta no se sabe fechar", que NO es lo mismo que
    "es vieja": ver el orden que define jornadas().

    Es el mismo orden de precedencia que usa olvido._edad_dias para decidir
    que se purga. Que las dos piezas fechen igual no es cosmetico: si el
    olvido creyera que una jornada es de agosto y el cuaderno la enseniara
    como la ultima, se borraria audio de lo que el dueno esta mirando.
    """
    return _fecha_del_dir(raiz() / "jornadas" / _seguro(nombre))


def jornadas() -> list:
    """Nombres de jornada, de la mas nueva a la mas vieja POR FECHA.

    POR QUE NO POR NOMBRE. Esto era `sorted(nombres, reverse=True)`, y ordenar
    por nombre no es ordenar por fecha: cualquier carpeta que ordene despues
    alfabeticamente ('a-b', 'zzz', 'temp') se pone la primera. Y jornadas()[0]
    no es un detalle de presentacion, es "la ultima jornada" para media casa
    (el panel de /grabar-clase estado, /grabar-clase apuntes, /grabar-clase
    transcribir, la pagina viva). El sintoma medido: nada mas cerrar una clase
    de verdad, el estado contestaba "ultima jornada a-b / estado nueva /
    duracion 0 min / sesiones 0" -- y parecia que no se habia grabado nada,
    mientras apuntes y transcribir trabajaban sobre la carpeta equivocada.

    DONDE VA LA QUE NO SE PUEDE FECHAR (ver fecha_de). Al FINAL, detras de
    todas las fechadas, y entre ellas por nombre descendente:

      - No puede colarse primera, porque ser "la ultima jornada" es lo unico
        que jornadas()[0] promete y una carpeta sin fecha no puede probarlo.
        Ese es exactamente el bug.
      - Y no puede desaparecer, aunque filtrarla arreglaria el bug de la
        primera posicion: esta lista es la que recorren el indice de materias
        (cuaderno.py), el vocabulario (materias.py) y el olvido (olvido.py).
        Una jornada escondida seria invisible en el cuaderno y a la vez
        inmortal para el olvido, que es el peor par posible: ocupa disco para
        siempre y el dueno no puede ni verla para borrarla.

    Las fechadas empatadas se desempatan tambien por nombre descendente, que
    es lo que pone '2026-08-31-2' (la clase de la tarde) delante de
    '2026-08-31' cuando las dos son del mismo dia y ninguna tiene todavia
    inicio_epoch.

    El coste esta medido y acotado con cache: ver _CACHE_FECHA.
    """
    base = raiz() / "jornadas"
    if not base.is_dir():
        return []
    filas = []
    for d in base.iterdir():
        if not d.is_dir():
            continue
        fecha = _fecha_del_dir(d)
        # El primer elemento separa los dos grupos con reverse=True (True va
        # delante de False), asi que la fecha de relleno de las que no se
        # pueden fechar nunca se compara contra una fecha de verdad.
        filas.append((fecha is not None, fecha or 0.0, d.name))
    filas.sort(reverse=True)
    return [nombre for _, _, nombre in filas]


def bytes_de(jornada: str) -> dict:
    """{'audio': n, 'adjuntos': n, 'texto': n} en bytes. Lo usa el olvido para
    decidir que purgar y el /grabar-clase estado para no mentir sobre lo que
    ocupa el cuaderno."""
    d = dir_jornada(jornada)
    def _suma(p):
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
    texto = sum(f.stat().st_size for f in d.glob("*.json*") if f.is_file())
    return {"audio": _suma(d / DIR_AUDIO),
            "adjuntos": _suma(d / DIR_ADJUNTOS),
            "texto": texto}
