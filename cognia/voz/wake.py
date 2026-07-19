"""
cognia/voz/wake.py
==================
Palabra de activacion para Cognia (planes/JARVIS_COGNIA.md 4.1, gate J1).

El pedido del dueño es decir "cerebro" y que Cognia se despierte. Este modulo es
la parte que escucha permanentemente y decide cuando eso paso.

POR QUE openWakeWord Y NO PORCUPINE. Porcupine es mas maduro y entrena una
palabra nueva en diez segundos desde su consola web, pero cuesta 6.000+ USD al
año. openWakeWord es gratis, corre en ONNX sobre CPU y permite palabras
personalizadas; el precio es tener que entrenar el modelo uno mismo.

ESTADO DE "CEREBRO": todavia no existe. openWakeWord trae 6 modelos
preentrenados (alexa, hey_jarvis, hey_mycroft, hey_rhasspy, timer, weather) y
ninguno sirve. Entrenar el propio con muestras sinteticas de TTS es el gate J1
del plan. Mientras tanto este modulo acepta CUALQUIER modelo disponible, asi que
el resto de la cadena (STT -> Cognia -> TTS) se construye y se prueba con
`hey_jarvis` sin quedar bloqueada esperando.

Formato de audio: 16 kHz, mono, int16, en trozos de 1280 muestras (80 ms), que
es lo que espera el modelo. Escuchar cuesta ~0.1 de un core.
"""

import queue
import threading

TASA_MUESTREO = 16000
CHUNK_MUESTRAS = 1280          # 80 ms, el tamaño que espera openWakeWord
UMBRAL_POR_DEFECTO = 0.5
# Silencio minimo entre dos activaciones. Sin esto, una sola vez que alguien
# dice la palabra dispara varias veces seguidas, porque el modelo puntua alto
# durante varios trozos consecutivos.
ANTIRREBOTE_SEG = 2.0


def modelos_disponibles() -> list[str]:
    """Nombres de los modelos de wake word instalados."""
    try:
        from openwakeword.model import Model
        return sorted(Model(inference_framework="onnx").models.keys())
    except Exception:
        return []


class DetectorPalabra:
    """Puntua trozos de audio y avisa cuando se dijo la palabra.

        det = DetectorPalabra(palabras=["hey_jarvis"], umbral=0.5)
        if det.detecto(chunk):
            despertar()

    palabras: modelos a escuchar. None escucha todos los instalados.
    umbral: puntaje minimo (0..1). Mas alto = menos falsos positivos y mas
            palabras que se pierden. El gate J1 lo calibra midiendo de verdad.
    reloj: fuente de tiempo, inyectable para poder testear el antirrebote sin
           esperar segundos reales.
    """

    def __init__(self, palabras=None, umbral: float = UMBRAL_POR_DEFECTO,
                 antirrebote: float = ANTIRREBOTE_SEG, modelo=None,
                 reloj=None):
        self.palabras = list(palabras) if palabras else None
        self.umbral = umbral
        self.antirrebote = antirrebote
        self._modelo = modelo
        import time as _time
        self.reloj = reloj or _time.monotonic
        # None y no 0.0: con 0.0 el antirrebote se aplica ANTES de que haya
        # habido una primera activacion, y con un reloj que arranca cerca de
        # cero la primerisima deteccion queda suprimida para siempre. Con
        # time.monotonic() el bug se esconde (devuelve el uptime, un numero
        # grande), asi que solo aparece con otro reloj. Lo cazo un test.
        self.ultima_activacion: float | None = None
        self.detecciones = 0
        self.ultimos_puntajes: dict = {}

    @property
    def modelo(self):
        if self._modelo is None:
            from openwakeword.model import Model
            if self.palabras:
                self._modelo = Model(wakeword_models=self.palabras,
                                     inference_framework="onnx")
            else:
                self._modelo = Model(inference_framework="onnx")
        return self._modelo

    def puntajes(self, chunk) -> dict:
        """Puntaje de cada palabra para este trozo de audio. Nunca lanza: un
        fallo del modelo no puede tumbar el hilo que escucha."""
        try:
            self.ultimos_puntajes = dict(self.modelo.predict(chunk))
        except Exception:
            self.ultimos_puntajes = {}
        return self.ultimos_puntajes

    def detecto(self, chunk) -> str | None:
        """Nombre de la palabra detectada, o None.

        Devuelve None mientras dure el antirrebote aunque el puntaje siga
        alto: una activacion por vez que se habla, no una por trozo de audio.
        """
        puntajes = self.puntajes(chunk)
        if not puntajes:
            return None
        palabra, valor = max(puntajes.items(), key=lambda kv: kv[1])
        if valor < self.umbral:
            return None
        ahora = self.reloj()
        if (self.ultima_activacion is not None
                and ahora - self.ultima_activacion < self.antirrebote):
            return None
        self.ultima_activacion = ahora
        self.detecciones += 1
        return palabra

    def estadisticas(self) -> dict:
        return {"detecciones": self.detecciones, "umbral": self.umbral,
                "palabras": self.palabras or "todas",
                "ultimos_puntajes": self.ultimos_puntajes}


class Escucha:
    """Escucha el microfono en segundo plano y avisa cuando se dijo la palabra.

        escucha = Escucha(al_detectar=lambda p: print("me llamaron:", p))
        escucha.arrancar()
        ...
        escucha.parar()

    Corre en un hilo aparte para no bloquear el CLI. El microfono se abre
    recien al arrancar y se cierra al parar: no se deja el microfono tomado
    mientras Cognia no esta escuchando a proposito.
    """

    def __init__(self, al_detectar=None, detector: DetectorPalabra | None = None,
                 dispositivo=None):
        self.al_detectar = al_detectar
        self.detector = detector or DetectorPalabra()
        self.dispositivo = dispositivo
        self._hilo = None
        self._parar = threading.Event()
        self._cola = queue.Queue()
        self.escuchando = False

    def arrancar(self):
        if self.escuchando:
            return
        self._parar.clear()
        self._hilo = threading.Thread(target=self._bucle, daemon=True,
                                      name="cognia-wake")
        self._hilo.start()
        self.escuchando = True

    def parar(self, timeout: float = 2.0):
        self._parar.set()
        if self._hilo is not None:
            self._hilo.join(timeout=timeout)
            self._hilo = None
        self.escuchando = False

    def _bucle(self):
        try:
            import sounddevice as sd
        except Exception:
            return

        def entrada(datos, frames, tiempo, estado):
            # El callback de audio tiene que devolver YA: solo encola.
            self._cola.put(bytes(datos))

        try:
            with sd.RawInputStream(samplerate=TASA_MUESTREO, blocksize=CHUNK_MUESTRAS,
                                   dtype="int16", channels=1,
                                   device=self.dispositivo, callback=entrada):
                self._consumir()
        except Exception:
            return

    def _consumir(self):
        import numpy as np
        while not self._parar.is_set():
            try:
                crudo = self._cola.get(timeout=0.2)
            except queue.Empty:
                continue
            chunk = np.frombuffer(crudo, dtype=np.int16)
            palabra = self.detector.detecto(chunk)
            if palabra and self.al_detectar:
                try:
                    self.al_detectar(palabra)
                except Exception:
                    pass          # un callback roto no corta la escucha

    def escuchar_de(self, chunks, limite: int | None = None) -> list[str]:
        """Procesa una secuencia de trozos ya capturados, sin microfono.

        Existe para poder probar la deteccion con audio de archivo o generado,
        que es como se va a calibrar el umbral en el gate J1.
        """
        detectadas = []
        for chunk in chunks:
            palabra = self.detector.detecto(chunk)
            if palabra:
                detectadas.append(palabra)
                if self.al_detectar:
                    try:
                        self.al_detectar(palabra)
                    except Exception:
                        pass
                if limite and len(detectadas) >= limite:
                    break
        return detectadas
