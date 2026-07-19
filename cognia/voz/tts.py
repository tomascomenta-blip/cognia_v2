"""
cognia/voz/tts.py
=================
Boca de Cognia: sintesis de voz con Piper (planes/JARVIS_COGNIA.md 4.1).

POR QUE PIPER Y NO KOKORO NI XTTS. Piper corre en CPU, tiene voces en español y
no compite por la VRAM, que en esta maquina ya esta tomada por el modelo de
lenguaje. Kokoro suena mas natural pero su cobertura de español habia que
verificarla y ocupa GPU; XTTS clona voz pero es mas de diez veces mas lento. En
un asistente por voz la latencia manda sobre el timbre.

LATENCIA REAL MEDIDA en esta maquina (2026-07-19), separando frio de caliente
porque la diferencia es de 25x y confunde:
  - primera frase: ~1.1 s, casi todo carga perezosa del modelo (1.28 s medidos
    aparte solo para PiperVoice.load)
  - frases siguientes, con la voz ya cargada: **45 ms**
El ~40 ms que cita la literatura es el numero EN CALIENTE y es correcto. Por eso
conviene precargar la voz al arrancar la sesion en vez de en la primera
respuesta: paga 1.2 s una sola vez, cuando nadie esta esperando, y despues
contesta en 45 ms. Entra holgado en el presupuesto del gate J3 (2.5 s de punta a
punta para toda la cadena).

Hablar es interrumpible a proposito: si el dueño vuelve a hablar mientras Cognia
responde, lo que se espera de un asistente es que se calle, no que termine su
parrafo.
"""

import threading
import wave
from pathlib import Path

VOZ_POR_DEFECTO = "es_ES-davefx-medium"
DIR_VOCES = Path.home() / ".cognia" / "voces"


def voces_instaladas(directorio: Path | None = None) -> list[str]:
    """Nombres de las voces descargadas."""
    d = Path(directorio or DIR_VOCES)
    if not d.is_dir():
        return []
    return sorted(f.stem for f in d.glob("*.onnx"))


def descargar_voz(nombre: str = VOZ_POR_DEFECTO,
                  directorio: Path | None = None) -> Path:
    """Descarga una voz si falta y devuelve la ruta al modelo."""
    d = Path(directorio or DIR_VOCES)
    d.mkdir(parents=True, exist_ok=True)
    destino = d / ("%s.onnx" % nombre)
    if not destino.exists():
        from piper.download_voices import download_voice
        download_voice(nombre, d)
    return destino


class Voz:
    """Sintetiza y reproduce habla.

        voz = Voz()
        voz.decir("Hola, soy Cognia")
        voz.callar()          # corta la reproduccion en curso

    La voz se carga perezosamente: importar este modulo no descarga ni carga
    nada, para que arrancar el CLI siga siendo instantaneo.
    """

    def __init__(self, nombre: str = VOZ_POR_DEFECTO,
                 directorio: Path | None = None, backend=None):
        self.nombre = nombre
        self.directorio = Path(directorio or DIR_VOCES)
        self._voz = backend
        self._hilo = None
        self._interrumpir = threading.Event()
        self.hablando = False

    @property
    def voz(self):
        if self._voz is None:
            from piper import PiperVoice
            self._voz = PiperVoice.load(descargar_voz(self.nombre,
                                                      self.directorio))
        return self._voz

    def sintetizar(self, texto: str) -> tuple[bytes, int]:
        """texto -> (audio PCM int16, tasa de muestreo). Cadena vacia si falla:
        que la voz no funcione no puede tumbar la respuesta de Cognia."""
        try:
            trozos = list(self.voz.synthesize(texto))
        except Exception:
            return b"", 22050
        if not trozos:
            return b"", 22050
        audio = b"".join(t.audio_int16_bytes for t in trozos)
        return audio, trozos[0].sample_rate

    def guardar_wav(self, texto: str, ruta) -> str | None:
        """Sintetiza a un archivo WAV. Devuelve la ruta, o None si fallo."""
        audio, tasa = self.sintetizar(texto)
        if not audio:
            return None
        with wave.open(str(ruta), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)          # int16
            w.setframerate(tasa)
            w.writeframes(audio)
        return str(ruta)

    def decir(self, texto: str, bloquear: bool = False) -> bool:
        """Sintetiza y reproduce. bloquear=False devuelve el control enseguida
        y habla en segundo plano, que es lo que quiere un asistente."""
        audio, tasa = self.sintetizar(texto)
        if not audio:
            return False
        self.callar()                  # una sola voz a la vez
        self._interrumpir.clear()
        if bloquear:
            self._reproducir(audio, tasa)
            return True
        self._hilo = threading.Thread(target=self._reproducir,
                                      args=(audio, tasa), daemon=True,
                                      name="cognia-tts")
        self._hilo.start()
        return True

    def callar(self, timeout: float = 2.0):
        """Corta la reproduccion en curso."""
        self._interrumpir.set()
        if self._hilo is not None:
            self._hilo.join(timeout=timeout)
            self._hilo = None
        self.hablando = False

    def _reproducir(self, audio: bytes, tasa: int):
        try:
            import numpy as np
            import sounddevice as sd
        except Exception:
            return
        self.hablando = True
        try:
            muestras = np.frombuffer(audio, dtype=np.int16)
            # Se reproduce por bloques y no de una, para poder cortar a mitad
            # de frase cuando el dueño vuelve a hablar.
            bloque = tasa // 10        # 100 ms
            with sd.OutputStream(samplerate=tasa, channels=1,
                                 dtype="int16") as salida:
                for i in range(0, len(muestras), bloque):
                    if self._interrumpir.is_set():
                        break
                    salida.write(muestras[i:i + bloque])
        except Exception:
            pass
        finally:
            self.hablando = False
