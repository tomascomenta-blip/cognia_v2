"""
cognia/clases/jornada.py
========================
El ORQUESTADOR: lo que pasa entre "/grabar-clase" y un cuaderno hecho.

Junta las cuatro piezas y las hace sobrevivir a una jornada de 7 horas:

    captura.Grabador  --cola de trozos-->  transcripcion.Transcripcion
                                                     |
                                              transcripcion.jsonl
                                                     |
                              materias.detectar  ->  cortes.jsonl
                                                     |
                              apuntes.generar    ->  apuntes.json
                                                     |
                              vista.export       ->  cuaderno.html

POR QUE UN SINGLETON DE MODULO. El REPL es un proceso vivo y el duenio teclea
"/grabar-clase" una vez por la maniana y "/grabar-clase parar" por la tarde,
con horas de otros comandos en medio. La jornada tiene que vivir FUERA del
handler del comando. Es el mismo patron que el editor de flujos y los
monitores: un objeto de modulo con hilos daemon.

POR QUE LA DETECCION DE MATERIA VA EN CALIENTE Y TAMBIEN AL CERRAR. En
caliente para que el duenio vea en que materia esta y pueda corregirla ("no,
esto es Fisica") mientras la clase pasa. Y otra vez ENTERA al cerrar, porque
detectar un corte con lo que viene DESPUES es mucho mas fiable que con solo
lo de antes: al final del dia se conoce toda la jornada y se puede reconsiderar.
Lo de en caliente es una ayuda; lo del cierre es la verdad.

RESISTENCIA. Nada de lo que hace un ciclo puede tumbar la grabacion: si la
deteccion falla, se anota y se sigue capturando. Perder la clasificacion es
molesto; perder la clase es irreparable.

UN LOCK DE PROCESO, ADEMAS DEL SINGLETON. `_VIVA` es un singleton de MODULO:
sirve dentro de ESTE proceso y no lo ve nadie mas. Con el widget de escritorio
y el REPL abiertos a la vez habria dos grabadores escribiendo la misma carpeta,
dos relojes distintos y una transcripcion intercalada. Por eso `arrancar()`
toma antes `~/.cognia/clases/grabando.lock` con su PID: si el PID de dentro
sigue vivo, se niega DICIENDO QUE PROCESO lo tiene; si esta muerto, el lock es
rancio (el REPL anterior murio sin cerrar) y se roba dejando aviso. Y SIEMPRE
hay salida: los PID se reciclan, asi que un lock viejo cuyo numero hoy es de
otro programa bloquearia la grabacion para siempre -- por eso un lock con mas
de EDAD_LOCK_ABSURDA se considera rancio aunque conteste vivo, y por eso
existe `forzar_liberacion()`, que lo quita a mano y lo dice.

JORNADA.JSON SE ESCRIBE POR CAMPOS, NUNCA ENTERO. Hay cuatro escritores (el
vigia cada 90 s, pausar/reanudar, la deteccion y el cierre) y algunos tardan
minutos entre que leen y escriben. Guardar el objeto entero desde una copia
vieja BORRA lo que otro escribio en medio: la pausa del duenio se perdia asi,
de forma intermitente y muda. Todos pasan por `_actualizar_jornada`, que
relee, toca solo sus campos y guarda, bajo `_LOCK_JORNADA`.

PAUSAR Y MUTEAR NO SON LO MISMO. Pausar es "esto de ahora no es clase" (el
recreo, una llamada): la jornada queda `pausada` en disco, que es el estado que
`olvido` ya respeta para no purgar una jornada abierta. Mutear es "no grabes lo
que suena, pero sigue la clase": el reloj NO se detiene en ninguno de los dos,
porque `t` es lo que situa las notas del duenio dentro del cuaderno y un reloj
congelado las amontonaria todas en el mismo segundo.
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import tempfile
import threading
import time
from pathlib import Path

from cognia.clases import almacen as alm
from cognia.clases import captura as cap
from cognia.clases import cuaderno as cua
from cognia.clases import transcripcion as tra

_log = logging.getLogger(__name__)

# Cada cuanto se revisa si hay que cortar por materia, en segundos de pared.
# 90 s: bastante corto para que el duenio vea la materia bien pronto, bastante
# largo para no llamar al detector por cada trozo de 30 s.
PERIODO_DETECCION = 90.0

# El lock de proceso, dentro de la raiz del cuaderno (asi COGNIA_CLASES_DIR lo
# mueve tambien en los tests y una suite no puede bloquear al duenio).
LOCK = "grabando.lock"

# A partir de aqui un lock se considera RANCIO aunque su PID conteste "vivo".
# POR QUE HACE FALTA: los PID se reciclan. Un lock que quedo sin borrar hace
# tres dias tiene un PID que hoy es de otro programa cualquiera; `_pid_vivo`
# dice VIVO con razon y la grabacion queda bloqueada PARA SIEMPRE sin que
# nadie pueda hacer nada. 18 h es el numero: una jornada de clase son 5-7 h
# (ver el encabezado), asi que ni la mas larga con el portatil suspendido a
# mitad llega ahi, y a la vez cualquier lock de "ayer" cae dentro.
EDAD_LOCK_ABSURDA = 18 * 3600.0

# Reintentos del os.replace de _reescribir_jsonl. MEDIDO aqui el 2026-08-31:
# en Windows, os.replace sobre un destino que otro hilo tiene ABIERTO para leer
# falla con PermissionError [WinError 5] (CPython abre los ficheros sin
# FILE_SHARE_DELETE). El lector del cuaderno tiene el fichero abierto unos
# microsegundos, asi que reintentar poco y rapido basta; 0,5 s de techo total
# porque pasado eso el problema ya no es la carrera sino otra cosa (un antivirus
# o un fichero bloqueado) y hay que verla como aviso, no seguir esperando.
_REINTENTOS_REPLACE = 20
_ESPERA_REPLACE = 0.025


# ── Escritura ATOMICA de un JSONL entero ─────────────────────────────────────
# AVISO: esto pertenece a `almacen` (junto a guardar_json, que hace lo mismo
# para JSON). Vive aqui porque `almacen.py` lo esta tocando otro agente en
# paralelo; conviene moverlo a almacen.reescribir_jsonl en cuanto se pueda, sin
# cambiar el comportamiento.

def _reescribir_jsonl(ruta: Path, registros: list) -> None:
    """Deja el JSONL con EXACTAMENTE estos registros, de una sola vez.

    Borrar y volver a apendar linea a linea deja una ventana en la que el
    fichero no existe o esta a medias. En cortes.jsonl eso no es teorico:
    `cuaderno.sesiones_de` interpreta "sin cortes" como UNA sesion entera de
    'Sin clasificar', asi que el cuaderno vivo parpadearia de 'Fisica' a 'Sin
    clasificar' en cada deteccion (cada PERIODO_DETECCION segundos). Con
    fichero temporal + os.replace el lector ve siempre la version vieja o la
    nueva, nunca un hueco.

    MEDIDO el 2026-08-31 (60 reescrituras de 12 cortes, un lector cada 1 ms):
    con el codigo viejo el lector veia 2, 3, 5, 6, 8, 9, 10, 11 y 12 cortes y
    ademas reventaba con FileNotFoundError; con esto, 565 lecturas y las 565
    de 12. Lo que queda es que 4 de esas lecturas dieron PermissionError (el
    replace en vuelo): un fallo VISIBLE y raro en vez de un dato falso mudo.
    AVISO para quien recoja esto: `almacen.leer_jsonl` deberia reintentar ante
    PermissionError para que esas 4 tampoco se noten.
    """
    ruta.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(ruta.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            for reg in registros:
                fh.write(json.dumps(reg, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        for intento in range(_REINTENTOS_REPLACE):
            try:
                os.replace(tmp, ruta)
                return
            except PermissionError:
                if intento == _REINTENTOS_REPLACE - 1:
                    raise
                time.sleep(_ESPERA_REPLACE)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ── Lock de proceso ──────────────────────────────────────────────────────────

def ruta_lock() -> Path:
    return alm.raiz() / LOCK


_K32 = None


def _kernel32():
    """kernel32 con los argtypes/restype ya declarados, una sola vez.

    Vive aparte de `_pid_vivo` por dos motivos: se declara UNA vez en vez de
    en cada consulta del lock, y sobre todo se puede MIRAR desde un test --
    que el HANDLE viaje entero no se puede comprobar por el resultado (los
    handles de un proceso recien arrancado caben de sobra en 32 bits y el bug
    solo asoma cuando no), asi que lo que se comprueba es la declaracion.
    """
    global _K32
    if _K32 is None:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL,
                                    wintypes.DWORD]
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE,
                                           ctypes.POINTER(wintypes.DWORD)]
        k32.GetExitCodeProcess.restype = wintypes.BOOL
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        k32.CloseHandle.restype = wintypes.BOOL
        _K32 = k32
    return _K32


def _pid_vivo(pid: int) -> bool:
    """Si ese PID esta corriendo AHORA.

    En Windows NO se usa `os.kill(pid, 0)`: CPython implementa os.kill en
    Windows con TerminateProcess para cualquier senial que no sea
    CTRL_C_EVENT/CTRL_BREAK_EVENT, o sea que "preguntar" MATARIA la otra
    grabacion. Se pregunta con OpenProcess + GetExitCodeProcess.

    Si no se puede mirar por permisos (el lock es de otro usuario), se responde
    VIVO: robarle el lock a un proceso que no se pudo comprobar es peor que
    negarse a grabar, porque el resultado del robo son dos grabadores sobre la
    misma carpeta.

    LOS argtypes/restype NO SON DECORACION. Sin declararlos, ctypes asume que
    toda funcion devuelve `int` (c_int, 32 bits CON signo) y OpenProcess
    devuelve un HANDLE de 64 bits en un proceso de 64 bits: el handle llega
    TRUNCADO y con el signo cambiado, y ese valor roto es el que se le pasa
    luego a GetExitCodeProcess y a CloseHandle. Lo que sale de ahi es un
    "muerto" falso (y el robo del lock de una grabacion viva) mas una fuga de
    handles. Declarados, ctypes marshala el HANDLE entero.
    """
    pid = int(pid or 0)
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        k32 = _kernel32()
        # PROCESS_QUERY_LIMITED_INFORMATION: el permiso minimo que basta para
        # preguntar por el codigo de salida y que no exige ser el dueno.
        h = k32.OpenProcess(0x1000, False, pid)
        if not h:
            return ctypes.get_last_error() == 5      # ERROR_ACCESS_DENIED
        try:
            codigo = wintypes.DWORD()
            if not k32.GetExitCodeProcess(h, ctypes.byref(codigo)):
                return True                          # no se pudo saber: vivo
            return codigo.value == 259               # STILL_ACTIVE
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def lock_actual() -> dict:
    """{} si no hay lock legible; si lo hay, su contenido + 'vivo', 'ajeno',
    'edad' y 'absurdo'.

    Lo lee tambien `estado()`, que es lo que pinta el widget: saber que la
    grabacion la tiene OTRA ventana es la diferencia entre "no graba" y "graba,
    pero no aqui".

    OJO al {} : significa "no hay lock O el lock no se puede leer". Quien
    decida robarlo tiene que distinguir los dos casos mirando si el FICHERO
    existe (lo hace `_tomar_lock`), porque pisar un lock ilegible sin decirlo
    es exactamente el fallo mudo que este modulo persigue.
    """
    ruta = ruta_lock()
    datos = alm.leer_json(ruta, None)
    if not isinstance(datos, dict) or not datos.get("pid"):
        return {}
    pid = int(datos.get("pid") or 0)
    fuera = dict(datos)
    fuera["pid"] = pid
    fuera["vivo"] = _pid_vivo(pid)
    fuera["ajeno"] = pid != os.getpid()
    # La EDAD es lo unico que delata un PID REUTILIZADO: el sistema recicla
    # los PID, asi que un lock de anteayer cuyo PID "vive" casi seguro apunta
    # a un proceso que no tiene nada que ver (un chrome.exe que heredo el
    # numero). Ver EDAD_LOCK_ABSURDA.
    fuera["edad"] = max(0.0, time.time() - float(datos.get("epoch") or 0.0))
    fuera["absurdo"] = fuera["edad"] > EDAD_LOCK_ABSURDA
    return fuera


def _tomar_lock(nombre: str) -> tuple:
    """(ok, aviso). Reserva la grabacion para ESTE proceso.

    Se crea con O_EXCL para que dos procesos que arrancan a la vez no se
    pisen: el que pierde la carrera lee el lock del otro y se niega. Un lock de
    un PID muerto es rancio (el REPL anterior murio sin cerrar) y se roba, pero
    dejando aviso: "no lo cerro nadie" y "se lo he quitado a otro" no pueden
    verse igual desde fuera.

    LOS TRES MOTIVOS PARA ROBARLO, y los tres dejan aviso:
      - el PID esta muerto (el caso normal: el REPL anterior no cerro);
      - el lock esta ILEGIBLE (vacio, truncado o sin PID). Antes se reescribia
        en silencio con ok=True y aviso="": ni se negaba ni avisaba, que es el
        peor de los dos mundos. Un lock que no se puede leer no protege a
        nadie, asi que se toma -- pero DICIENDOLO, porque un fichero de 0 bytes
        ahi significa que alguien murio a mitad del write;
      - el lock es ABSURDAMENTE viejo (EDAD_LOCK_ABSURDA) aunque su PID
        conteste vivo: eso es un PID reciclado, no una grabacion.
    """
    ruta = ruta_lock()
    crudo = json.dumps({"pid": os.getpid(), "jornada": nombre,
                        "epoch": time.time()}, ensure_ascii=False)
    aviso = ""
    try:
        fd = os.open(str(ruta), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        viejo = lock_actual()
        pid = int(viejo.get("pid") or 0)
        if not pid:
            aviso = ("el lock de grabacion estaba ilegible (vacio o corrupto): "
                     "no protegia a nadie, me quedo yo con la grabacion")
            _log.warning(aviso)
        elif pid != os.getpid() and viejo.get("vivo") and viejo.get("absurdo"):
            aviso = ("lock del PID %d (jornada '%s') con %.1f h de antiguedad: "
                     "ese PID esta reciclado, no es una grabacion. Me quedo yo"
                     % (pid, viejo.get("jornada") or "?",
                        float(viejo.get("edad") or 0.0) / 3600.0))
            _log.warning(aviso)
        elif pid and pid != os.getpid() and viejo.get("vivo"):
            cuando = time.strftime("%H:%M", time.localtime(
                float(viejo.get("epoch") or 0.0)))
            return False, ("ya hay una grabacion en el proceso PID %d "
                           "(jornada '%s', desde las %s). Paras ahi con "
                           "/grabar-clase parar, cierras ese proceso, o -- si "
                           "sabes que ese PID ya no es Cognia -- lo liberas a "
                           "la fuerza con jornada.forzar_liberacion()."
                           % (pid, viejo.get("jornada") or "?", cuando))
        elif pid != os.getpid():
            aviso = ("lock rancio del PID %d (jornada '%s'): ese proceso ya no "
                     "existe, me quedo yo con la grabacion"
                     % (pid, viejo.get("jornada") or "?"))
            _log.warning(aviso)
        try:
            _reescribir_lock(ruta, crudo)
        except OSError as exc:
            return False, "no pude tomar el lock de grabacion: %s" % exc
    else:
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(crudo + "\n")
                fh.flush()
                os.fsync(fh.fileno())
        except OSError as exc:
            return False, "no pude escribir el lock de grabacion: %s" % exc
    _registrar_atexit()
    return True, aviso


def _reescribir_lock(ruta: Path, crudo: str) -> None:
    """Pisa el lock rancio de forma atomica: mismo motivo que guardar_json."""
    fd, tmp = tempfile.mkstemp(dir=str(ruta.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(crudo + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, ruta)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _registrar_atexit() -> None:
    """atexit.register una sola vez: registrarlo en cada arrancar() apilaria
    una llamada por jornada y el log se llenaria de intentos inutiles."""
    global _ATEXIT_PUESTO
    if not _ATEXIT_PUESTO:
        atexit.register(_soltar_lock)
        _ATEXIT_PUESTO = True


_ATEXIT_PUESTO = False


def _soltar_lock() -> str:
    """Borra el lock SOLO si es nuestro. Devuelve "" o el aviso de por que no.

    Comprobar el PID no es paranoia: si otro proceso ya nos lo robo por rancio,
    borrarlo aqui le dejaria la grabacion sin lock y volveriamos al problema de
    los dos grabadores.

    UN LOCK ILEGIBLE NO SE BORRA. Antes, un fichero vacio o corrupto no pasaba
    el `isinstance(datos, dict)` y caia directo en el unlink: se le quitaba el
    lock a OTRO proceso (el que lo estuviera escribiendo en ese instante) sin
    decir nada. Nuestro lock lo escribimos nosotros y siempre es legible, asi
    que uno ilegible no puede ser el nuestro: se deja y se avisa. Para el caso
    de que quede atascado esta `forzar_liberacion`, que si lo borra pero
    porque lo pide una persona.
    """
    ruta = ruta_lock()
    try:
        if not ruta.exists():
            return ""
        datos = alm.leer_json(ruta, None)
        if not isinstance(datos, dict) or not datos.get("pid"):
            aviso = ("no suelto el lock de grabacion: esta ilegible (vacio o "
                     "corrupto) y no puedo demostrar que sea mio. "
                     "jornada.forzar_liberacion() lo quita")
            _log.warning(aviso)
            return aviso
        if int(datos.get("pid") or 0) != os.getpid():
            aviso = ("no suelto el lock de grabacion: ahora es del PID %d, no "
                     "mio" % int(datos.get("pid") or 0))
            _log.warning(aviso)
            return aviso
        os.unlink(str(ruta))
    except FileNotFoundError:
        return ""
    except OSError as exc:
        aviso = "no pude soltar el lock de grabacion: %s" % exc
        _log.warning(aviso)
        return aviso
    return ""


def forzar_liberacion(motivo: str = "") -> dict:
    """LA SALIDA DE EMERGENCIA: quita el lock sea de quien sea.

    POR QUE TIENE QUE EXISTIR. `_pid_vivo` responde VIVO cuando no puede
    comprobar el proceso, y ademas los PID se reciclan: un lock olvidado cuyo
    numero hoy es de chrome.exe deja la grabacion bloqueada para siempre y sin
    ninguna forma de salir. `EDAD_LOCK_ABSURDA` cubre el caso tipico
    (automatico, a las 18 h), pero por debajo de ese umbral hace falta una
    puerta manual: el duenio SABE si ese PID es su otra ventana de Cognia o no.

    Es deliberadamente una funcion aparte y no un flag de `arrancar()`: robar
    el lock de una grabacion viva de verdad produce dos grabadores sobre la
    misma carpeta, asi que tiene que costar teclear algo.

    Devuelve {'liberado', 'lock', 'aviso'}: 'lock' es lo que habia (para poder
    ensenar a quien se le quito) y 'liberado' es False si no habia nada.
    """
    ruta = ruta_lock()
    habia = lock_actual()
    if not ruta.exists():
        return {"liberado": False, "lock": {},
                "aviso": "no habia ningun lock de grabacion que liberar"}
    try:
        os.unlink(str(ruta))
    except FileNotFoundError:
        return {"liberado": False, "lock": habia,
                "aviso": "el lock desaparecio solo antes de quitarlo"}
    except OSError as exc:
        aviso = "no pude forzar la liberacion del lock: %s" % exc
        _log.warning(aviso)
        return {"liberado": False, "lock": habia, "aviso": aviso}
    aviso = ("lock de grabacion liberado A LA FUERZA (PID %s, jornada '%s')%s"
             % (habia.get("pid") or "ilegible",
                habia.get("jornada") or "?",
                (": " + motivo) if motivo else ""))
    _log.warning(aviso)
    return {"liberado": True, "lock": habia, "aviso": aviso}


# ── Escritura de jornada.json: read-modify-write bajo lock ───────────────────
# Reentrantes a proposito: `detectar` puede llamarse desde dentro de una
# operacion que ya tiene el lock (el cierre llama a detectar, y el detector
# real puede tocar el cuaderno), y un Lock normal ahi seria un cuelgue.
_LOCK_JORNADA = threading.RLock()
_LOCK_CORTES = threading.RLock()


def _actualizar_jornada(nombre: str, **campos):
    """Cambia SOLO estos campos de jornada.json, leyendo justo antes. Devuelve
    la Jornada guardada.

    EL BUG QUE ESTO MATA (lost update). El patron viejo era
    `j = cargar_jornada(); j.loquesea = x; guardar_jornada(j)` con MUCHO
    trabajo en medio: `detectar()` cargaba la jornada al empezar y la guardaba
    entera al terminar, minutos despues. Si el duenio pulsaba Pausa en ese
    hueco -- y el hueco se abre cada PERIODO_DETECCION = 90 s, o sea casi
    siempre -- `guardar_jornada` reescribia el objeto RANCIO y devolvia el
    estado a "grabando". La pausa quedaba sin efecto de forma intermitente y
    sin ninguna traza: el peor modo de fallo posible.

    Aqui la lectura, la modificacion y la escritura pasan juntas bajo
    `_LOCK_JORNADA` y cada llamante toca UNICAMENTE sus campos, asi que dos
    escritores concurrentes ya no se pisan aunque el segundo tarde en llegar.

    Un valor CALLABLE se aplica sobre el valor actual (`segundos=lambda v:
    max(v, t)`): es lo que hace falta para "no bajar el reloj" sin volver a
    traer una copia entera de fuera, que es justo lo que causaba el bug.

    NO cubre a otros PROCESOS. Es un lock de hilos: contra el segundo proceso
    esta el lock de fichero (`_tomar_lock`), que es lo que impide que existan
    dos grabadores a la vez.
    """
    with _LOCK_JORNADA:
        j = cua.cargar_jornada(nombre)
        for clave, valor in campos.items():
            setattr(j, clave, valor(getattr(j, clave)) if callable(valor)
                    else valor)
        cua.guardar_jornada(j)
        return j


class JornadaViva:
    """Una jornada en curso. No se instancia a mano: se usa `arrancar()`."""

    def __init__(self, nombre: str, fuente: str = cap.FUENTE_SISTEMA,
                 transcriptor=None, orch=None, grabador=None):
        self.nombre = nombre
        self.orch = orch
        # `grabador` se inyecta: un test no puede abrir el loopback WASAPI de
        # la maquina, y sin esto no habria forma de probar pausa/mute/lock.
        self.grabador = grabador or cap.Grabador(nombre, fuente=fuente)
        self.transcripcion = tra.Transcripcion(nombre, transcriptor=transcriptor)
        self.avisos: list = []
        self.pausada = False
        self.muteada = False
        self._parar = threading.Event()
        self._vigia = None
        self._t0_pared = 0.0
        self._lock_mio = False

    # -- ciclo de vida ------------------------------------------------------
    def arrancar(self) -> tuple:
        # El lock va ANTES de tocar el audio: si graba otro proceso, ni
        # siquiera hay que abrir el dispositivo para saber que no toca.
        ok, aviso = _tomar_lock(self.nombre)
        if not ok:
            return False, aviso
        self._lock_mio = True
        if aviso:
            self.avisos.append(aviso)
        ok, motivo = self.grabador.arrancar()
        if not ok:
            # Sin captura no hay jornada: soltar el lock o el siguiente
            # intento se encontraria bloqueado por nosotros mismos.
            self._soltar_mi_lock()
            return False, motivo
        self.transcripcion.arrancar(self.grabador.cola)
        self._t0_pared = time.time()
        _actualizar_jornada(self.nombre, estado="grabando",
                            inicio_epoch=lambda v: v or self._t0_pared)
        self._vigia = threading.Thread(target=self._bucle_vigia, daemon=True,
                                       name="clases-vigia")
        self._vigia.start()
        return True, motivo

    def parar(self) -> dict:
        """Cierra la jornada: para la captura, vacia la transcripcion, detecta
        materias con TODO el dia delante, VACIA LA COLA DEL REFINADO EN
        CALIENTE y genera los apuntes.

        EL ORDEN DE LOS TRES ULTIMOS PASOS ES EL CONTRATO, no una casualidad:
        primero los cortes definitivos (el refinado escribe bajo la clave de
        sesion, que depende de ellos), despues `refinado.cerrar` (el unico que
        procesa el ultimo tramo de clase) y solo entonces `generar_apuntes`.
        """
        self._parar.set()
        self.grabador.parar()
        self.transcripcion.parar()
        if self._vigia is not None:
            self._vigia.join(timeout=5.0)
        self.avisos.extend(self.grabador.avisos)
        self.avisos.extend(self.transcripcion.avisos)

        resumen = {"jornada": self.nombre, "avisos": list(self.avisos)}
        resumen["cortes"] = self.detectar(definitivo=True)
        resumen["refinado"] = self._cerrar_refinado()
        resumen["apuntes"] = self.generar_apuntes()

        j = _actualizar_jornada(
            self.nombre, estado="cerrada", fin_epoch=time.time(),
            segundos=lambda v: max(v, self.grabador._t),
            aviso=self.avisos[-1] if self.avisos else "")
        resumen["segundos"] = j.segundos
        self.pausada = False
        self._soltar_mi_lock()
        resumen["avisos"] = list(self.avisos)
        return resumen

    def _soltar_mi_lock(self) -> None:
        """Suelta el lock y SE QUEDA con el aviso si no pudo: un lock que
        sobrevive a `parar()` bloquea la siguiente grabacion del duenio, y
        callarlo aqui haria que el bloqueo apareciera manana sin causa."""
        if self._lock_mio:
            aviso = _soltar_lock()
            if aviso:
                self.avisos.append(aviso)
                _log.warning(aviso)
            self._lock_mio = False

    @property
    def viva(self) -> bool:
        return self.grabador.viva or self.transcripcion.viva

    # -- pausa y mute -------------------------------------------------------
    def _aplicar_mudo(self) -> None:
        """El grabador tiene UN solo interruptor; aqui hay dos motivos para
        cerrarlo. Se recalcula desde los dos para que desmutear estando en
        pausa no reabra el audio (y al reves)."""
        self.grabador.mudo = bool(self.pausada or self.muteada)

    def pausar(self) -> dict:
        """Pausa la jornada: deja de entrar audio y el estado en disco pasa a
        'pausada'.

        El estado ya estaba DECLARADO (`cuaderno.Jornada.estado`) y ya lo
        respeta `olvido.ESTADOS_ABIERTOS` para no purgar una jornada abierta;
        lo que faltaba era alguien que lo escribiera.

        Deja marca en el cuaderno por la regla de la casa: sin ella, el hueco
        en la transcripcion se ve igual que una captura rota.
        """
        if self.pausada:
            return {"pausada": True, "cambio": False}
        self.pausada = True
        self._aplicar_mudo()
        self._escribir_estado("pausada")
        self.anotar(cua.TIPO_MARCA, texto="jornada pausada")
        return {"pausada": True, "cambio": True}

    def reanudar(self) -> dict:
        """Vuelve a 'grabando'. Si el micro seguia muteado, sigue muteado: son
        dos interruptores distintos y reanudar no puede des-mutear a espaldas
        del duenio."""
        if not self.pausada:
            return {"pausada": False, "cambio": False}
        self.pausada = False
        self._aplicar_mudo()
        self._escribir_estado("grabando")
        self.anotar(cua.TIPO_MARCA, texto="jornada reanudada")
        return {"pausada": False, "cambio": True}

    def mutear(self) -> dict:
        """Descarta el audio SIN parar la grabacion ni el reloj.

        Para cuando suena algo que no es la clase (una llamada, musica) y el
        duenio no quiere que entre al cuaderno. La jornada sigue 'grabando': el
        tiempo corre y las notas siguen cayendo en su minuto.

        LA UNIDAD ES EL TROZO, NO EL SEGUNDO, y conviene saberlo antes de
        pulsarlo. El grabador decide si descarta cuando CIERRA cada trozo de
        `captura.SEGUNDOS_TROZO` (30 s), asi que:
          - mutear tira el trozo EN VUELO entero, incluida la clase que suene
            en los segundos anteriores al muteo;
          - desmutear conserva entero el trozo que empezo mudo, incluido lo
            que sonaba mientras estaba muteado.
        O sea que el corte real cae en el limite del trozo, hasta 30 s a cada
        lado de donde se pulso. Se deja asi a proposito: cortar por dentro del
        trozo exigiria un reloj de pared aparte del reloj de la jornada (que
        solo avanza al cerrar el trozo), y la alternativa de parar y rearrancar
        la captura es justo lo que mas ha tumbado el driver WASAPI. Que quede
        ESCRITO, porque un docstring que promete un corte al segundo y descarta
        media clase es peor que la imprecision.
        """
        if self.muteada:
            return {"muteada": True, "cambio": False}
        self.muteada = True
        self._aplicar_mudo()
        self.anotar(cua.TIPO_MARCA, texto="micro muteado")
        return {"muteada": True, "cambio": True}

    def desmutear(self) -> dict:
        """Vuelve a dejar entrar el audio. Con la misma granularidad de trozo
        que `mutear`: el trozo que estaba en vuelo al desmutear se guarda
        ENTERO, con la parte que sonaba mientras estaba muteado."""
        if not self.muteada:
            return {"muteada": False, "cambio": False}
        self.muteada = False
        self._aplicar_mudo()
        self.anotar(cua.TIPO_MARCA, texto="micro reanudado")
        return {"muteada": False, "cambio": True}

    def _escribir_estado(self, estado: str) -> None:
        """El estado y el reloj, a jornada.json. El reloj va con el estado
        porque una jornada que se pausa y se retoma tiene que volver en el
        segundo bueno.

        Toca SOLO `estado` y `segundos` (ver `_actualizar_jornada`): guardar
        aqui el objeto entero era lo que dejaba que el vigia, con su copia de
        hace 90 s, borrara la pausa recien pulsada.
        """
        _actualizar_jornada(self.nombre, estado=estado,
                            segundos=lambda v: max(v, self.grabador._t))

    # -- trabajo ------------------------------------------------------------
    def _bucle_vigia(self) -> None:
        """Detecta materia cada PERIODO_DETECCION y persiste el reloj.

        El estado se reescribe aqui y no en el grabador para que un cuelgue de
        la deteccion no deje la jornada sin actualizar los segundos: el reloj
        es lo que permite retomar una jornada interrumpida en el punto bueno.
        """
        while not self._parar.wait(PERIODO_DETECCION):
            try:
                _actualizar_jornada(self.nombre, segundos=self.grabador._t)
                self.detectar(definitivo=False)
            except Exception as exc:
                aviso = "vigia: %s: %s" % (type(exc).__name__, exc)
                self.avisos.append(aviso)
                _log.warning(aviso)
            # FUERA del try de arriba a proposito: que falle la deteccion no
            # puede dejar la clase sin refinar, ni al reves. Cada uno se
            # protege por su cuenta.
            self._refinar_en_caliente()

    def _refinar_en_caliente(self) -> None:
        """Una vuelta del refinado incremental (`clases/refinado.py`).

        Se llama en CADA vuelta del vigia y es `refinado.tick` quien decide si
        toca por periodo (5 minutos por defecto): asi el ritmo del refinado se
        configura donde vive el refinado y esta jornada no necesita un hilo
        mas ni un segundo reloj que mantener vivo.

        NADA DE LO QUE PASE AQUI PUEDE TUMBAR LA GRABACION -- es la regla de
        resistencia del encabezado. Un import que no esta o una excepcion del
        refinado se anotan y se sigue capturando: perder los apuntes en
        caliente es molesto (se generan igual al cerrar), perder la clase es
        irreparable.
        """
        try:
            from cognia.clases import refinado as ref
        except ImportError as exc:
            aviso = "refinado en caliente no disponible: %s" % exc
            if aviso not in self.avisos:
                self.avisos.append(aviso)
                _log.warning(aviso)
            return
        try:
            res = ref.tick(self.nombre)
        except Exception as exc:
            aviso = "refinado: %s: %s" % (type(exc).__name__, exc)
            self.avisos.append(aviso)
            _log.warning(aviso)
            return
        # `tick` devuelve SOLO los avisos que dice por primera vez (los
        # deduplica el propio refinado), asi que esto no puede llenar la lista
        # con el mismo "el modelo no esta arriba" cada 90 segundos.
        for aviso in res.get("avisos") or []:
            self.avisos.append(aviso)

    def _cerrar_refinado(self) -> dict:
        """Vacia la cola del refinado en caliente ANTES de generar los apuntes.

        POR QUE ES IMPRESCINDIBLE Y NO UN ADORNO: `apuntes.generar` devuelve
        TAL CUAL unos apuntes que ya existen (apuntes.py:814), asi que en
        cuanto el refinado escribio la primera entrada de una sesion,
        `generar_apuntes()` ya no vuelve a mirar esa clase. Lo que el refinado
        no haya procesado no lo procesa NADIE: sin esta llamada se perdia
        siempre el ultimo tramo de la clase -- que es justo donde el profesor
        manda los deberes y dice que entra en el examen.

        POR QUE AQUI Y NO EN EL VIGIA: `parar()` le da 5 s de join al hilo
        vigia y una sola ventana de modelo tarda ~13 s. Tiene que correr en el
        hilo que cierra, con el vigia ya muerto (o sea, despues del join).

        Un fallo suyo NO puede tumbar el cierre -- misma regla de resistencia
        que `_refinar_en_caliente`: se anota y se sigue, porque los apuntes
        que ya estan escritos y el cierre de la jornada valen mas que el
        ultimo tramo.
        """
        try:
            from cognia.clases import refinado as ref
        except ImportError as exc:
            aviso = ("refinado en caliente no disponible al cerrar (%s): el "
                     "ultimo tramo de clase se queda sin refinar" % exc)
            self.avisos.append(aviso)
            _log.warning(aviso)
            return {}
        try:
            res = ref.cerrar(self.nombre)
        except Exception as exc:
            aviso = ("refinado al cerrar: %s: %s (el ultimo tramo se queda "
                     "sin refinar)" % (type(exc).__name__, exc))
            self.avisos.append(aviso)
            _log.warning(aviso)
            return {}
        for aviso in res.get("avisos") or []:
            self.avisos.append(aviso)
        return res

    def detectar(self, definitivo: bool = False) -> list:
        """Recalcula los cortes de materia y los reescribe.

        Se REESCRIBE el fichero entero en vez de apendar: los cortes no son
        hechos observados sino una INTERPRETACION del dia, y una
        interpretacion vieja al lado de la nueva confundiria al cuaderno. Los
        cortes que el duenio puso a mano se conservan siempre.

        La reescritura es ATOMICA (`_reescribir_jsonl`). Borrar y reapendar
        dejaba el fichero inexistente o a medias durante un instante, cada
        PERIODO_DETECCION segundos, y quien lo leyera justo ahi veia una
        jornada 'Sin clasificar' entera.

        LOS MANUALES SE RELEEN AL FINAL, no al principio. Entre que empieza la
        deteccion y que se escribe el fichero pasan segundos (o minutos, con el
        modelo delante), y en ese hueco el duenio puede teclear
        `/grabar-clase materia Fisica`: `marcar_materia` apendaba su corte y
        esta reescritura, hecha con la lista leida ANTES, lo borraba. El
        docstring prometia que el manual gana siempre y el manual desaparecia.
        La relectura pasa dentro de `_LOCK_CORTES`, el mismo que toma
        `marcar_materia`, asi que tampoco cabe entre la relectura y el
        replace.
        """
        try:
            from cognia.clases import materias as mat
        except ImportError as exc:
            self.avisos.append("deteccion de materias no disponible: %s" % exc)
            return []
        d = alm.dir_jornada(self.nombre)
        entradas = cua._cargar_entradas(self.nombre)
        if not entradas:
            return []
        horario = cua.cargar_jornada(self.nombre).horario
        try:
            cortes = mat.detectar(entradas,
                                  materias_conocidas=cua.materias_conocidas(),
                                  pistas={"horario": horario},
                                  orch=self.orch if definitivo else None)
        except Exception as exc:
            aviso = "deteccion fallo: %s: %s" % (type(exc).__name__, exc)
            self.avisos.append(aviso)
            _log.warning(aviso)
            return []
        ruta = d / alm.CORTES
        with _LOCK_CORTES:
            manuales = [c for c in alm.leer_jsonl(ruta)
                        if str(c.get("por") or "") == "manual"]
            # Un corte manual GANA a uno automatico que caiga cerca: el duenio
            # ya dijo lo que es esa clase y no hay senial que valga mas.
            for m in manuales:
                cortes = [c for c in cortes
                          if abs(float(c.get("t", 0)) - float(m.get("t", 0))) > 60.0]
                cortes.append(m)
            cortes.sort(key=lambda c: float(c.get("t") or 0.0))
            try:
                _reescribir_jsonl(ruta, cortes)
            except OSError as exc:
                self.avisos.append("no se pudieron guardar los cortes: %s" % exc)
                return cortes
        if cortes:
            # SOLO materia_actual: guardar aqui la Jornada entera cargada al
            # empezar pisaba con el estado rancio la pausa que el duenio
            # hubiera pulsado mientras corria la deteccion.
            _actualizar_jornada(
                self.nombre,
                materia_actual=str(cortes[-1].get("materia") or ""))
        return cortes

    def generar_apuntes(self) -> dict:
        try:
            from cognia.clases import apuntes as ap
        except ImportError as exc:
            self.avisos.append("generacion de apuntes no disponible: %s" % exc)
            return {}
        try:
            return ap.generar_jornada(self.nombre, orch=self.orch)
        except Exception as exc:
            aviso = "apuntes: %s: %s" % (type(exc).__name__, exc)
            self.avisos.append(aviso)
            _log.warning(aviso)
            return {}

    # -- lo que aniade el duenio -------------------------------------------
    def anotar(self, tipo: str, texto: str = "", adjunto: str = "",
               importante: bool = False) -> dict:
        reg = {"t": self.grabador._t, "tipo": tipo, "texto": texto,
               "adjunto": adjunto, "fuente": "usuario",
               "importante": bool(importante)}
        alm.apendar(alm.dir_jornada(self.nombre) / alm.ENTRADAS, reg)
        return reg

    def marcar_materia(self, materia: str) -> dict:
        """El duenio corrige la materia en curso. Es un corte MANUAL, y manda
        sobre la deteccion para siempre.

        El apend va bajo `_LOCK_CORTES` (el mismo que la reescritura de
        `detectar`) porque si cae entre la relectura de manuales y el
        os.replace, la reescritura lo borra y la correccion del duenio se
        pierde sin traza.
        """
        corte = {"t": self.grabador._t, "materia": materia,
                 "confianza": 1.0, "por": "manual"}
        with _LOCK_CORTES:
            alm.apendar(alm.dir_jornada(self.nombre) / alm.CORTES, corte)
        _actualizar_jornada(self.nombre, materia_actual=materia)
        return corte


# ── Singleton de modulo ──────────────────────────────────────────────────────
_VIVA = None
_LOCK = threading.Lock()


def nombre_de_hoy() -> str:
    """'2026-08-31', y '-2', '-3'... si ya hubo una jornada cerrada hoy.

    Dos jornadas el mismo dia no es raro: se para al mediodia y se vuelve por
    la tarde. Reusar la carpeta mezclaria las dos en un solo cuaderno.
    """
    hoy = time.strftime("%Y-%m-%d")
    existentes = [n for n in alm.jornadas() if n.startswith(hoy)]
    if not existentes:
        return hoy
    j = cua.cargar_jornada(hoy if hoy in existentes else existentes[0])
    if j.estado != "cerrada" and hoy in existentes:
        return hoy                              # retomar la de hoy sin cerrar
    return "%s-%d" % (hoy, len(existentes) + 1)


def arrancar(fuente: str = cap.FUENTE_SISTEMA, transcriptor=None,
             orch=None, nombre: str = "") -> tuple:
    """(JornadaViva|None, motivo). Idempotente: si ya hay una, la devuelve."""
    global _VIVA
    with _LOCK:
        if _VIVA is not None and _VIVA.viva:
            return _VIVA, "ya habia una jornada grabando (%s)" % _VIVA.nombre
        jv = JornadaViva(nombre or nombre_de_hoy(), fuente=fuente,
                         transcriptor=transcriptor, orch=orch)
        ok, motivo = jv.arrancar()
        if not ok:
            return None, motivo
        _VIVA = jv
        return jv, motivo


def viva():
    return _VIVA if (_VIVA is not None and _VIVA.viva) else None


def parar() -> dict:
    global _VIVA
    with _LOCK:
        if _VIVA is None:
            return {}
        res = _VIVA.parar()
        _VIVA = None
        return res


def pausar() -> dict:
    """Puerta de modulo a JornadaViva.pausar (lo que llama el widget/CLI)."""
    jv = viva()
    if jv is None:
        return {"ok": False, "motivo": "no hay ninguna jornada grabando"}
    res = dict(jv.pausar())
    res["ok"] = True
    return res


def reanudar() -> dict:
    jv = viva()
    if jv is None:
        return {"ok": False, "motivo": "no hay ninguna jornada grabando"}
    res = dict(jv.reanudar())
    res["ok"] = True
    return res


def mutear() -> dict:
    jv = viva()
    if jv is None:
        return {"ok": False, "motivo": "no hay ninguna jornada grabando"}
    res = dict(jv.mutear())
    res["ok"] = True
    return res


def desmutear() -> dict:
    jv = viva()
    if jv is None:
        return {"ok": False, "motivo": "no hay ninguna jornada grabando"}
    res = dict(jv.desmutear())
    res["ok"] = True
    return res


def _estado_base() -> dict:
    """La FORMA del dict de `estado()`: la plantilla que rellena cada rama,
    para que el widget encuentre siempre las mismas claves.

    Es una FUNCION y no una constante porque tres de los valores son mutables
    (materias, avisos, lock) y un dict de modulo copiado con dict() los
    compartiria entre todas las llamadas: quien ordenara la lista de materias
    del estado se la ordenaria a los demas.
    """
    return {"grabando": False, "jornada": "", "estado": "", "materia": "",
            "pausada": False, "muteada": False, "segundos": 0.0,
            "trozos": 0, "transcritos": 0, "silencios": 0, "descartados": 0,
            "sesiones": 0, "materias": [], "aviso": "", "avisos": [],
            "lock": {}, "otro_proceso": False}


def estado() -> dict:
    """Lo que ensenia '/grabar-clase' a secas, y lo que pinta el widget.

    Es la unica puerta al estado: el widget dibuja su menu (grabar / pausar /
    mutear) con esto y NO tocando `_VIVA` ni el grabador. Por eso salen aqui
    `pausada`, `muteada` y `otro_proceso`; sin el ultimo, un widget abierto al
    lado del REPL que graba se pintaria como "parado" y ofreceria un boton de
    grabar que solo puede fallar.

    Las claves que ya consumia el CLI (grabando/jornada/materia/segundos/
    trozos/transcritos/silencios/avisos, y estado/sesiones/materias en la rama
    cerrada) se mantienen tal cual.

    TODAS LAS RAMAS DEVUELVEN LAS MISMAS CLAVES (`_estado_base()` es la
    plantilla, y cada rama solo la actualiza). Antes no: 'descartados' salia
    solo grabando, 'estado' y 'segundos' faltaban con el cuaderno vacio y
    'materias' era un 0 en una rama y una lista en otra. Quien pinta esto es
    un widget que lo lee CADA segundo y en cualquiera de los tres estados; un
    dict con claves que aparecen y desaparecen obliga a `.get` con defaults
    repartidos por la vista, y ahi es donde nace el "0" que en realidad
    significaba "no lo se".
    """
    lock = lock_actual()
    fuera = _estado_base()
    fuera["lock"] = lock
    fuera["otro_proceso"] = bool(lock.get("vivo") and lock.get("ajeno"))
    jv = viva()
    if jv is not None:
        j = cua.cargar_jornada(jv.nombre)
        fuera.update({
            "grabando": True, "jornada": jv.nombre,
            "estado": j.estado or "grabando",
            "pausada": bool(jv.pausada), "muteada": bool(jv.muteada),
            "materia": j.materia_actual or "(sin clasificar aun)",
            "segundos": jv.grabador._t,
            "trozos": jv.transcripcion.trozos,
            "transcritos": jv.transcripcion.transcritos,
            "silencios": jv.transcripcion.silencios,
            "descartados": getattr(jv.grabador, "descartados", 0),
            "aviso": j.aviso,
            "avisos": (jv.grabador.avisos + jv.transcripcion.avisos)[-3:]})
        return fuera
    ultimas = alm.jornadas()
    if not ultimas:
        return fuera                    # cuaderno vacio: la plantilla tal cual
    j = cua.cargar_jornada(ultimas[0])
    ses = cua.sesiones_de(ultimas[0])
    fuera.update({
        "jornada": j.nombre, "estado": j.estado,
        "pausada": j.estado == "pausada",
        "materia": j.materia_actual or "(sin clasificar aun)",
        "segundos": j.segundos, "sesiones": len(ses),
        "materias": sorted({s.materia for s in ses}),
        "descartados": 0, "aviso": j.aviso})
    return fuera
