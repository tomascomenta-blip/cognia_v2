"""
cognia/clases/transcripcion.py
==============================
Convertir los trozos de audio de la jornada en texto, MIENTRAS la clase pasa.

POR QUE EN CALIENTE Y NO AL FINAL. Una jornada son 5-7 horas. Transcribir eso
de golpe al cerrar son ~40 min de CPU en los que el duenio esta mirando una
barra, y ademas obliga a conservar TODO el audio hasta entonces. Consumiendo
la cola segun llegan los trozos, al pulsar "parar" el cuaderno ya esta hecho
y el audio ya se puede purgar.

REUSA EL OIDO QUE YA HAY. `cognia/voz/stt.py` (faster-whisper 1.2.1, modelo
'small', 16 kHz, con filtro de alucinaciones ya escrito) es el STT del
producto. Aqui NO se monta otro: dos transcriptores distintos darian dos
transcripciones distintas del mismo audio y el cuaderno dejaria de cuadrar
con la sesion de voz.

EL AJUSTE QUE SI ES PROPIO: el modelo se mantiene RESIDENTE mientras dura la
jornada. `Transcriptor.descargar()` existe para soltar la VRAM entre turnos de
voz, que es lo correcto ahi (habla una vez cada varios minutos); aqui hay un
trozo cada 30 segundos durante horas, y recargar el modelo en cada uno
costaria mas que transcribir. Se descarga UNA vez, al cerrar la jornada.

CONTRA LA ALUCINACION DEL SILENCIO. Whisper, ante 30 segundos de silencio, se
inventa texto ("Subtitulos realizados por...", "Gracias por ver el video").
`stt._es_alucinacion` ya caza las frases tipicas, pero el filtro barato y
seguro es ANTERIOR: si el trozo no tiene energia suficiente, no se le pasa al
modelo. Un recreo de 20 minutos son 40 trozos que no hace falta ni mirar.
"""

from __future__ import annotations

import logging
import queue
import threading

from cognia.clases import almacen as alm

_log = logging.getLogger(__name__)

# Por debajo de este pico, el trozo es silencio y no se transcribe. 0.005 en
# escala -1..1 es ~ -46 dBFS: por debajo esta el ruido de sala y el zumbido de
# la linea, nunca una voz audible por los altavoces. Barato y conservador: si
# se cuela algun trozo flojo, lo peor que pasa es que se transcriba y salga
# vacio; al reves se perderia clase.
PICO_MINIMO = 0.005

# Trozos consecutivos por debajo del pico que hacen falta para anotar una
# PAUSA en el flujo. La pausa no es un detalle cosmetico: es la senial numero
# uno del detector de cambio de materia (entre clases hay silencio; a mitad de
# una explicacion, no).
TROZOS_PARA_PAUSA = 4


class Transcripcion:
    """Consume la cola del Grabador y va escribiendo transcripcion.jsonl.

    Hilo daemon. Contrato: `arrancar(cola)` no bloquea; `parar()` termina de
    vaciar lo que quede en la cola (hasta `timeout`) para no tirar los ultimos
    minutos de clase, y despues suelta el modelo.
    """

    def __init__(self, jornada: str, transcriptor=None, idioma: str = "es"):
        self.jornada = jornada
        self.idioma = idioma
        self._stt = transcriptor            # inyectable: los tests no cargan Whisper
        self._cola = None
        self._parar = threading.Event()
        self._hilo = None
        self.avisos: list = []
        self.trozos = 0
        self.transcritos = 0
        self.silencios = 0
        self._silencio_seguido = 0

    # -- STT perezoso -------------------------------------------------------
    @property
    def stt(self):
        if self._stt is None:
            from cognia.voz.stt import Transcriptor
            self._stt = Transcriptor(idioma=self.idioma)
        return self._stt

    # -- ciclo de vida ------------------------------------------------------
    def arrancar(self, cola: "queue.Queue") -> None:
        self._cola = cola
        self._hilo = threading.Thread(target=self._bucle, daemon=True,
                                      name="clases-transcripcion")
        self._hilo.start()

    def parar(self, timeout: float = 120.0) -> None:
        """Vacia la cola pendiente y luego para.

        El timeout es generoso a proposito: al pulsar 'parar' puede haber
        varios trozos sin transcribir, y cada uno tarda unos segundos. Cortar
        a los 5 s dejaria fuera los ultimos minutos de la clase -- justo los
        que el duenio acaba de oir y por los que va a mirar el cuaderno.
        """
        self._parar.set()
        if self._hilo is not None:
            self._hilo.join(timeout=timeout)
            if self._hilo.is_alive():
                self.avisos.append(
                    "la transcripcion no acabo en %ds: quedan trozos sin texto "
                    "(el audio esta guardado; se puede completar con "
                    "/grabar-clase transcribir)" % int(timeout))
        try:
            if self._stt is not None and hasattr(self._stt, "descargar"):
                self._stt.descargar()
        except Exception as exc:
            _log.warning("no se pudo soltar el STT: %s", exc)

    @property
    def viva(self) -> bool:
        return self._hilo is not None and self._hilo.is_alive()

    # -- interno ------------------------------------------------------------
    def _bucle(self) -> None:
        while True:
            try:
                trozo = self._cola.get(timeout=0.5)
            except queue.Empty:
                if self._parar.is_set():
                    return
                continue
            except Exception as exc:                 # cola rota: no morir mudo
                self.avisos.append("cola de audio rota: %s" % exc)
                return
            try:
                self.procesar(trozo)
            except Exception as exc:
                aviso = ("trozo %s sin transcribir: %s: %s"
                         % (trozo.get("ruta"), type(exc).__name__, exc))
                self.avisos.append(aviso)
                _log.warning(aviso)

    def procesar(self, trozo: dict) -> str:
        """Un trozo -> texto escrito (o '' si era silencio). Publico porque es
        lo que reusa la transcripcion diferida de un audio ya grabado."""
        self.trozos += 1
        pico = float(trozo.get("pico") or 0.0)
        if pico < PICO_MINIMO:
            self.silencios += 1
            self._silencio_seguido += 1
            if self._silencio_seguido == TROZOS_PARA_PAUSA:
                self._anotar(trozo, "", pausa=True)
            return ""
        self._silencio_seguido = 0
        texto = (self.stt.transcribir_wav(trozo["ruta"]) or "").strip()
        if not texto:
            return ""
        self.transcritos += 1
        self._anotar(trozo, texto)
        return texto

    def _anotar(self, trozo: dict, texto: str, pausa: bool = False) -> None:
        ruta = alm.dir_jornada(self.jornada) / alm.TRANSCRIPCION
        alm.apendar(ruta, {
            "t": float(trozo.get("t0") or 0.0),
            "t_fin": float(trozo.get("t1") or 0.0),
            "tipo": "transcripcion",
            "texto": texto,
            "fuente": trozo.get("fuente") or "sistema",
            "pausa": bool(pausa),
        })


def transcribir_pendientes(jornada: str, transcriptor=None,
                           progreso=None) -> dict:
    """Transcribe los WAV de una jornada que aun no tienen texto.

    Existe para dos casos REALES: la jornada que se cerro con la cola a medias
    (el aviso de `parar`), y el audio de una clase que el duenio grabo por
    fuera y quiere meter en el cuaderno. Es idempotente: se salta los trozos
    cuyo tramo de tiempo ya aparece en transcripcion.jsonl.
    """
    import wave
    d = alm.dir_jornada(jornada)
    ya = {round(float(r.get("t") or 0.0), 1)
          for r in alm.leer_jsonl(d / alm.TRANSCRIPCION)}
    tr = Transcripcion(jornada, transcriptor=transcriptor)
    wavs = sorted((d / alm.DIR_AUDIO).glob("*.wav"))
    hechos, saltados = 0, 0
    t = 0.0
    for w in wavs:
        try:
            with wave.open(str(w), "rb") as fh:
                dur = fh.getnframes() / float(fh.getframerate() or 16000)
        except Exception as exc:
            _log.warning("wav ilegible %s: %s", w.name, exc)
            continue
        t0, t = t, t + dur
        if round(t0, 1) in ya:
            saltados += 1
            continue
        import numpy as np
        with wave.open(str(w), "rb") as fh:
            crudo = np.frombuffer(fh.readframes(fh.getnframes()), dtype=np.int16)
        pico = float(np.abs(crudo).max() / 32768.0) if crudo.size else 0.0
        fuente = "micro" if w.stem.endswith("_micro") else "sistema"
        tr.procesar({"ruta": str(w), "t0": t0, "t1": t, "pico": pico,
                     "fuente": fuente})
        hechos += 1
        if progreso:
            progreso(hechos, len(wavs))
    return {"trozos": len(wavs), "transcritos": hechos, "ya_estaban": saltados,
            "silencios": tr.silencios, "avisos": tr.avisos}
