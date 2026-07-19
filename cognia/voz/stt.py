"""
cognia/voz/stt.py
=================
Oido de Cognia: transcripcion con faster-whisper
(planes/JARVIS_COGNIA.md 4.1, gate J2).

POR QUE faster-whisper: es la reimplementacion de produccion de Whisper, 4x mas
rapida en GPU con int8 y con la misma precision. Para español hay que quedarse
en la familia Whisper — Parakeet es dramaticamente mas rapido pero esta orientado
a ingles.

EL PROBLEMA DE VRAM, QUE DECIDE EL DISEÑO. En esta maquina el Qwen2.5-7B ya
ocupa 6.3 GB medidos de los 16, y `large-v3` pide ~10. No entran. Por eso:

  - el modelo por defecto es `small` (~1 GB), que anda bien en español y deja
    lugar; `medium` y `large-v3` quedan disponibles por parametro para cuando la
    GPU este libre;
  - la carga es PEREZOSA y hay `descargar()` explicito, para poder soltar la
    VRAM entre turnos en vez de tenerla tomada mientras Cognia no escucha;
  - el device por defecto es **'cpu'**, no 'auto'.

POR QUE 'cpu' Y NO 'auto' (bug real, encontrado verificando de verdad): con
'auto', faster-whisper ve que HAY una GPU y la elige — sin mirar si le queda
lugar. Con el entrenamiento del BDraft ocupando 14.9 de los 16.3 GB, el proceso
se COLGO indefinidamente: media hora despues seguia con 0 segundos de CPU y 4 MB
de memoria, o sea bloqueado, no lento. "Disponible" para 'auto' significa que
existe, no que entre. En una maquina donde la GPU se comparte con un 7B, elegir
CPU por defecto y pedir GPU explicitamente cuando se sabe que esta libre es la
unica opcion que no se cuelga sola. La docstring anterior afirmaba que 'auto'
caia a CPU solo; era falso y lo desmintio la primera prueba real.

El gate J2 del plan mide el tiempo de swap real; hasta que se mida, el defecto
conservador es el chico.
"""

import unicodedata
import wave
from pathlib import Path

import numpy as np

MODELO_POR_DEFECTO = "small"
TASA_WHISPER = 16000        # Whisper trabaja siempre a 16 kHz
IDIOMA_POR_DEFECTO = "es"
# 'auto' se cuelga cuando la GPU existe pero esta llena (ver docstring). Para
# usar GPU hay que pedirla explicitamente, sabiendo que hay lugar.
DEVICE_SEGURO = "cpu"


def audio_de_wav(ruta) -> tuple[np.ndarray, int]:
    """WAV -> (float32 mono en [-1,1], tasa). Solo stdlib + numpy."""
    with wave.open(str(ruta), "rb") as w:
        canales, ancho = w.getnchannels(), w.getsampwidth()
        tasa, n = w.getframerate(), w.getnframes()
        crudo = w.readframes(n)
    if ancho != 2:
        raise ValueError("solo se soporta PCM de 16 bits, no de %d" % (ancho * 8))
    muestras = np.frombuffer(crudo, dtype=np.int16).astype(np.float32) / 32768.0
    if canales > 1:
        muestras = muestras.reshape(-1, canales).mean(axis=1)
    return muestras, tasa


def remuestrear(muestras: np.ndarray, origen: int,
                destino: int = TASA_WHISPER) -> np.ndarray:
    """Remuestreo lineal. Alcanza para voz: Piper entrega 22050 Hz y Whisper
    quiere 16000, y para transcribir no hace falta un filtro elaborado."""
    if origen == destino or muestras.size == 0:
        return muestras
    n_destino = int(round(muestras.size * destino / origen))
    x_viejo = np.linspace(0.0, 1.0, muestras.size, dtype=np.float64)
    x_nuevo = np.linspace(0.0, 1.0, n_destino, dtype=np.float64)
    return np.interp(x_nuevo, x_viejo, muestras).astype(np.float32)


# Frases que Whisper produce sobre silencio o ruido, heredadas de los
# subtitulos de YouTube con los que se entreno. El VAD filtra la mayoria, pero
# alguna se cuela igual y no puede llegar al motor como si fuera una orden.
_ALUCINACIONES = {
    "suscribete", "subscribe", "gracias por ver el video",
    "gracias por ver", "subtitulos realizados por la comunidad de amara org",
    "subtitulado por la comunidad de amara org", "thanks for watching",
    "thank you for watching", "amara org", "mas videos", "musica", "aplausos",
}


def _es_alucinacion(texto: str) -> bool:
    """El texto es una de las muletillas que Whisper inventa sobre silencio?"""
    if not texto:
        return True
    # Sin acentos: Whisper escribe "¡Suscríbete!" con tilde y la lista esta en
    # ASCII, asi que comparar sin normalizar deja pasar la basura.
    sin_acentos = unicodedata.normalize("NFD", texto.lower())
    sin_acentos = "".join(c for c in sin_acentos
                          if unicodedata.category(c) != "Mn")
    # La puntuacion se reemplaza por ESPACIO, no se borra: borrandola,
    # "Amara.org" quedaba "amaraorg" pegado y no coincidia con "amara org".
    limpio = "".join(c if (c.isalnum() or c.isspace()) else " "
                     for c in sin_acentos)
    limpio = " ".join(limpio.split())
    if limpio in _ALUCINACIONES:
        return True
    # Solo se descarta lo de UN caracter (puntuacion suelta, "...", una letra).
    # El corte NO puede ser mas alto: "si" y "no" son respuestas legitimas de
    # dos caracteres y un asistente por voz las necesita.
    return len(limpio) < 2


class Transcriptor:
    """Convierte audio en texto.

        stt = Transcriptor()
        stt.transcribir_wav("pregunta.wav")
        stt.descargar()          # suelta la VRAM entre turnos

    Se puede pasar directo como `transcriptor` a SesionVoz porque es invocable.
    """

    def __init__(self, modelo: str = MODELO_POR_DEFECTO, device: str = DEVICE_SEGURO,
                 compute_type: str = "default", idioma: str = IDIOMA_POR_DEFECTO,
                 backend=None):
        self.modelo = modelo
        self.device = device
        self.compute_type = compute_type
        self.idioma = idioma
        self._backend = backend

    @property
    def whisper(self):
        if self._backend is None:
            from faster_whisper import WhisperModel
            self._backend = WhisperModel(self.modelo, device=self.device,
                                         compute_type=self.compute_type)
        return self._backend

    def descargar(self):
        """Suelta el modelo. Con la GPU compartida con un 7B, tener el STT
        residente mientras nadie habla es VRAM regalada."""
        self._backend = None

    def transcribir(self, muestras, tasa: int = TASA_WHISPER) -> str:
        """Audio float32 mono -> texto. Cadena vacia ante cualquier fallo: que
        no se entienda no puede tumbar la sesion de voz."""
        try:
            audio = np.asarray(muestras, dtype=np.float32)
            if audio.size == 0:
                return ""
            audio = remuestrear(audio, tasa, TASA_WHISPER)
            # vad_filter recorta lo que no es voz ANTES de transcribir. Sin
            # esto, Whisper alucina sobre el silencio: entrenado con subtitulos
            # de YouTube, ante ruido de fondo devuelve cosas como "¡Suscribete!"
            # o "Gracias por ver el video". Paso de verdad en la primera prueba
            # con microfono: el asistente desperto, grabo ambiente y le mando
            # "¡Suscribete!" al motor como si fuera una pregunta del dueño.
            segmentos, _info = self.whisper.transcribe(
                audio, language=self.idioma, vad_filter=True)
            texto = " ".join(s.text.strip() for s in segmentos).strip()
            return "" if _es_alucinacion(texto) else texto
        except Exception:
            return ""

    def transcribir_wav(self, ruta) -> str:
        try:
            muestras, tasa = audio_de_wav(Path(ruta))
        except Exception:
            return ""
        return self.transcribir(muestras, tasa)

    def __call__(self, audio) -> str:
        """Para enchufarlo como `transcriptor` de SesionVoz: acepta una ruta a
        WAV, bytes PCM int16 o un array de numpy."""
        if isinstance(audio, (str, Path)):
            return self.transcribir_wav(audio)
        if isinstance(audio, (bytes, bytearray)):
            muestras = np.frombuffer(audio, dtype=np.int16).astype(np.float32)
            return self.transcribir(muestras / 32768.0, TASA_WHISPER)
        return self.transcribir(audio, TASA_WHISPER)
