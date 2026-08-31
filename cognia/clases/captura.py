"""
cognia/clases/captura.py
========================
Grabar la jornada: el audio que SUENA en el ordenador, no el del microfono.

POR QUE LOOPBACK Y NO MICROFONO. Una clase virtual (Meet, Zoom, Teams) entra
por los altavoces. Grabar el microfono capta al alumno y el eco de la sala;
el profesor se oye mal o no se oye. Lo que hay que capturar es la SALIDA del
sistema -- WASAPI loopback en Windows.

MEDIDO 2026-08-31 en la maquina del duenio antes de escribir nada:

    sounddevice 0.5.5  -> WasapiSettings(exclusive, auto_convert,
                          explicit_sample_format): NO tiene 'loopback'.
                          Este build de PortAudio no lo trae.
    soundcard          -> sc.get_microphone(sc.default_speaker().name,
                          include_loopback=True) grabo el tono de prueba con
                          pico=0.50127 / rms=0.28471. FUNCIONA.

De ahi la dependencia: `soundcard`, y como EXTRA opcional (`cognia-ai[clases]`),
porque una instalacion que solo quiere el CLI no tiene por que arrastrar
cffi ni tocar el audio del equipo. Sin el paquete, `disponible()` dice que
no y por que -- nunca un fallo mudo.

DOS FUENTES A LA VEZ. `fuente='ambas'` graba loopback Y microfono en hilos
distintos y los guarda por separado: la clase virtual y lo que dice el duenio
(o el aula fisica) no son la misma senial, y mezclarlas antes de transcribir
le da a Whisper dos voces pisadas. Cada trozo lleva su etiqueta y la
transcripcion sabe de cual viene.

TROZOS, NO UN WAV GIGANTE. Cada `segundos_trozo` se cierra un WAV numerado.
Motivos, los dos medidos en este repo: un WAV de 6 h con la cabecera sin
cerrar es ilegible, y la transcripcion puede ir consumiendo trozos MIENTRAS
la clase sigue, que es lo que hace que al acabar el cuaderno ya este hecho.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
import wave
from pathlib import Path

from cognia.clases import almacen as alm

_log = logging.getLogger(__name__)

# Whisper trabaja a 16 kHz mono. Se captura a la tasa nativa del dispositivo
# (48 kHz casi siempre) y se remuestrea al guardar: pedirle 16 kHz a WASAPI
# obliga al conversor del sistema y en algunos drivers devuelve silencio.
TASA_DESTINO = 16000
SEGUNDOS_TROZO = 30.0     # 30 s: bastante contexto para Whisper, poca perdida
FUENTE_SISTEMA = "sistema"
FUENTE_MICRO = "micro"


def disponible() -> tuple:
    """(bool, motivo). El motivo NO es decorativo: es lo que el CLI ensenia
    cuando /grabar-clase no puede arrancar, y la diferencia entre 'falta un
    paquete' y 'este equipo no tiene loopback' son dos arreglos distintos."""
    try:
        import soundcard                                   # noqa: F401
    except ImportError:
        return False, ("falta el paquete 'soundcard' (captura del audio del "
                       "sistema). Instalalo con:  pip install soundcard   "
                       "-- o  pip install cognia-ai[clases]")
    except Exception as exc:                               # cffi mal montado
        return False, "soundcard no carga: %s: %s" % (type(exc).__name__, exc)
    try:
        import soundcard as sc
        alt = sc.default_speaker()
        if alt is None:
            return False, "este equipo no declara altavoz por defecto"
        sc.get_microphone(str(alt.name), include_loopback=True)
        return True, "loopback listo sobre '%s'" % alt.name
    except Exception as exc:
        return False, ("el equipo no deja capturar la salida (loopback): "
                       "%s: %s" % (type(exc).__name__, exc))


def _remuestrear(muestras, origen: int, destino: int):
    """Remuestreo lineal a `destino` Hz, mono. Reusa el del oido de Cognia
    (voz/stt.remuestrear) y solo cae a una version local si ese modulo no
    esta: dos remuestreos distintos en el mismo producto darian dos
    transcripciones distintas del mismo audio."""
    import numpy as np
    muestras = np.asarray(muestras, dtype=np.float32)
    if muestras.ndim > 1:                       # a mono por promedio de canales
        muestras = muestras.mean(axis=1)
    if origen == destino or muestras.size == 0:
        return muestras
    try:
        from cognia.voz.stt import remuestrear as _rm
        return _rm(muestras, origen, destino)
    except Exception:
        n = int(round(muestras.size * (destino / float(origen))))
        if n <= 0:
            return muestras[:0]
        x = np.linspace(0.0, muestras.size - 1.0, n, dtype=np.float32)
        return np.interp(x, np.arange(muestras.size, dtype=np.float32),
                         muestras).astype(np.float32)


def guardar_wav(ruta: Path, muestras, tasa: int = TASA_DESTINO) -> None:
    """PCM 16 bit mono. Se cierra SIEMPRE antes de anunciar el trozo: un
    consumidor que lea un WAV con la cabecera a medias ve 0 frames."""
    import numpy as np
    pcm = np.clip(np.asarray(muestras, dtype=np.float32), -1.0, 1.0)
    pcm = (pcm * 32767.0).astype(np.int16)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(ruta), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(tasa))
        w.writeframes(pcm.tobytes())


class Grabador:
    """Captura continua a trozos WAV, en hilos daemon.

    Contrato: `arrancar()` no bloquea y `parar()` cierra el trozo en curso.
    Los trozos terminados se anuncian por `cola` como
    ``{'ruta', 'fuente', 't0', 't1', 'pico'}`` para que la transcripcion los
    consuma mientras la clase sigue.

    Un fallo del dispositivo NO tumba la grabacion: se anota en `avisos`, se
    espera y se reintenta. Que se caiga el driver a mitad de la segunda hora
    no puede costar las cuatro que quedan.
    """

    def __init__(self, jornada: str, fuente: str = FUENTE_SISTEMA,
                 segundos_trozo: float = SEGUNDOS_TROZO,
                 t_inicial: float = 0.0):
        self.jornada = jornada
        self.fuente = fuente
        self.segundos_trozo = max(5.0, float(segundos_trozo))
        self.cola: "queue.Queue" = queue.Queue()
        self.avisos: list = []
        self._parar = threading.Event()
        self._hilos: list = []
        self._n = 0
        self._lock = threading.Lock()
        self._t = float(t_inicial)      # reloj de la jornada, en segundos

    # -- ciclo de vida ------------------------------------------------------
    def arrancar(self) -> tuple:
        ok, motivo = disponible()
        if not ok:
            return False, motivo
        fuentes = ([FUENTE_SISTEMA, FUENTE_MICRO] if self.fuente == "ambas"
                   else [self.fuente])
        for f in fuentes:
            h = threading.Thread(target=self._bucle, args=(f,), daemon=True,
                                 name="clases-captura-" + f)
            h.start()
            self._hilos.append(h)
        return True, motivo

    def parar(self, timeout: float = 10.0) -> None:
        self._parar.set()
        for h in self._hilos:
            h.join(timeout=timeout)
        self._hilos = []

    @property
    def viva(self) -> bool:
        return any(h.is_alive() for h in self._hilos)

    # -- interno ------------------------------------------------------------
    def _dispositivo(self, fuente: str):
        import soundcard as sc
        if fuente == FUENTE_MICRO:
            return sc.default_microphone()
        return sc.get_microphone(str(sc.default_speaker().name),
                                 include_loopback=True)

    def _siguiente_ruta(self, fuente: str) -> Path:
        with self._lock:
            self._n += 1
            n = self._n
        return (alm.dir_jornada(self.jornada) / alm.DIR_AUDIO
                / ("%06d_%s.wav" % (n, fuente)))

    def _bucle(self, fuente: str) -> None:
        import numpy as np
        fallos = 0
        while not self._parar.is_set():
            try:
                dev = self._dispositivo(fuente)
                if dev is None:
                    raise RuntimeError("sin dispositivo para '%s'" % fuente)
                tasa = 48000
                with dev.recorder(samplerate=tasa, channels=1) as rec:
                    fallos = 0
                    while not self._parar.is_set():
                        t0 = self._t
                        n_frames = int(tasa * self.segundos_trozo)
                        datos = rec.record(numframes=n_frames)
                        if self._parar.is_set() and datos is None:
                            break
                        muestras = _remuestrear(datos, tasa, TASA_DESTINO)
                        dur = muestras.size / float(TASA_DESTINO)
                        # El reloj lo lleva UNA sola fuente para que dos
                        # grabadores no avancen la jornada al doble.
                        if fuente == FUENTE_SISTEMA or len(self._hilos) == 1:
                            self._t = t0 + dur
                        ruta = self._siguiente_ruta(fuente)
                        guardar_wav(ruta, muestras)
                        self.cola.put({
                            "ruta": str(ruta), "fuente": fuente,
                            "t0": t0, "t1": t0 + dur,
                            "pico": float(np.abs(muestras).max()) if muestras.size else 0.0,
                        })
            except Exception as exc:
                fallos += 1
                aviso = ("captura '%s' fallo (%d): %s: %s"
                         % (fuente, fallos, type(exc).__name__, exc))
                self.avisos.append(aviso)
                _log.warning(aviso)
                if fallos >= 5:
                    self.avisos.append("captura '%s' abandonada tras 5 fallos"
                                       % fuente)
                    return
                # Espera creciente, pero cortable: si el duenio para la
                # jornada durante el bache, no se queda 8 s colgado.
                self._parar.wait(min(8.0, 1.0 * fallos))
