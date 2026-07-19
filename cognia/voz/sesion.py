"""
cognia/voz/sesion.py
====================
Maquina de estados de la conversacion hablada
(planes/JARVIS_COGNIA.md 4.1, paso 4).

Es la pieza que hace que las otras trabajen juntas: escuchar la palabra de
activacion, transcribir, pensar y contestar, sin pisarse entre si.

    DORMIDO --palabra--> DESPIERTO --voz--> ESCUCHANDO --silencio--> PENSANDO
       ^                                                                 |
       |                                                                 v
       +---------------- (fin del turno) <---------------------------- HABLANDO

POR QUE UNA MAQUINA DE ESTADOS EXPLICITA y no un if adentro del callback de
audio: sin ella el sistema hace cosas absurdas que en un asistente por voz se
notan enseguida — transcribir su propia voz, aceptar una orden nueva mientras
todavia esta pensando la anterior, o quedarse escuchando para siempre si nadie
vuelve a hablar. Cada una de esas tres es un estado mal manejado, y cada una
tiene su test.

Las piezas (transcriptor, cerebro, voz) se inyectan. Este modulo no sabe si el
STT es faster-whisper ni si el cerebro es Cognia entera o una funcion de prueba:
solo coordina. Eso lo hace testeable sin GPU, sin microfono y sin modelo, que es
justo lo que hace falta mientras la GPU esta ocupada entrenando.
"""

import threading
import time

DORMIDO = "dormido"
DESPIERTO = "despierto"
ESCUCHANDO = "escuchando"
PENSANDO = "pensando"
HABLANDO = "hablando"

# Cuanto se espera hablando antes de rendirse y volver a dormir. Sin esto, una
# activacion accidental deja el microfono abierto indefinidamente.
ESPERA_MAXIMA_SEG = 8.0


class SesionVoz:
    """Coordina wake word, transcripcion, cerebro y voz.

        sesion = SesionVoz(transcriptor=stt, cerebro=responder, voz=tts)
        sesion.al_detectar_palabra("cerebro")   # lo llama Escucha
        sesion.procesar_turno(audio)

    transcriptor: callable(audio) -> str
    cerebro:      callable(texto) -> str
    voz:          objeto con decir(texto) y callar(); puede ser None
    reloj:        fuente de tiempo, inyectable para tests
    """

    def __init__(self, transcriptor=None, cerebro=None, voz=None,
                 espera_maxima: float = ESPERA_MAXIMA_SEG, reloj=None):
        self.transcriptor = transcriptor
        self.cerebro = cerebro
        self.voz = voz
        self.espera_maxima = espera_maxima
        self.reloj = reloj or time.monotonic
        self.estado = DORMIDO
        self.despertada_en: float | None = None
        self.turnos = 0
        self.historial: list[dict] = []
        self._lock = threading.Lock()

    # ── Transiciones ─────────────────────────────────────────────────────

    def al_detectar_palabra(self, palabra: str = "") -> bool:
        """La llama Escucha cuando oye la palabra de activacion.

        Devuelve False si la sesion esta ocupada. Ignorar la palabra mientras
        se piensa o se habla es deliberado: aceptarla ahi encolaria ordenes a
        medio procesar. La excepcion es HABLANDO, donde la palabra funciona
        como interrupcion —lo que uno espera de un asistente es que se calle y
        escuche, no que termine su parrafo.
        """
        with self._lock:
            if self.estado == HABLANDO:
                self.callar()
                self.estado = DESPIERTO
                self.despertada_en = self.reloj()
                return True
            if self.estado != DORMIDO:
                return False
            self.estado = DESPIERTO
            self.despertada_en = self.reloj()
            return True

    def expiro(self) -> bool:
        """Se desperto y nadie dijo nada en el tiempo maximo?"""
        if self.estado not in (DESPIERTO, ESCUCHANDO):
            return False
        if self.despertada_en is None:
            return False
        return (self.reloj() - self.despertada_en) >= self.espera_maxima

    def dormir(self):
        """Vuelve al reposo. Idempotente."""
        with self._lock:
            self.estado = DORMIDO
            self.despertada_en = None

    def callar(self):
        if self.voz is not None:
            try:
                self.voz.callar()
            except Exception:
                pass

    # ── El turno completo ────────────────────────────────────────────────

    def procesar_turno(self, audio) -> dict:
        """audio -> transcripcion -> respuesta -> voz. Devuelve el turno.

        Solo corre si la sesion fue despertada: sin esto el sistema
        transcribiria cualquier ruido, incluida su propia voz.
        """
        if self.estado not in (DESPIERTO, ESCUCHANDO):
            return {"ok": False, "motivo": "la sesion no esta despierta",
                    "estado": self.estado}

        self.estado = ESCUCHANDO
        texto = self._transcribir(audio)
        if not texto:
            self.dormir()
            return {"ok": False, "motivo": "no se entendio nada",
                    "estado": self.estado}

        self.estado = PENSANDO
        respuesta = self._pensar(texto)
        if not respuesta:
            self.dormir()
            return {"ok": False, "motivo": "el cerebro no respondio",
                    "texto": texto, "estado": self.estado}

        self.estado = HABLANDO
        self._decir(respuesta)
        self.estado = DORMIDO
        self.despertada_en = None
        self.turnos += 1
        turno = {"ok": True, "texto": texto, "respuesta": respuesta,
                 "estado": self.estado, "turno": self.turnos}
        self.historial.append(turno)
        return turno

    # ── Envoltorios que nunca lanzan ─────────────────────────────────────
    # Un fallo de cualquier pieza tiene que degradar el turno, no tumbar el
    # hilo que escucha: si el STT explota, la sesion vuelve a dormir y sigue
    # atendiendo la proxima vez que la llamen.

    def _transcribir(self, audio) -> str:
        if self.transcriptor is None:
            return ""
        try:
            return (self.transcriptor(audio) or "").strip()
        except Exception:
            return ""

    def _pensar(self, texto: str) -> str:
        if self.cerebro is None:
            return ""
        try:
            r = self.cerebro(texto)
        except Exception:
            return ""
        if isinstance(r, dict):        # responder_articulado devuelve dict
            r = r.get("response") or r.get("respuesta") or ""
        return (r or "").strip()

    def _decir(self, texto: str) -> bool:
        if self.voz is None:
            return False
        try:
            return bool(self.voz.decir(texto, bloquear=True))
        except Exception:
            return False

    def estadisticas(self) -> dict:
        return {"estado": self.estado, "turnos": self.turnos,
                "historial": len(self.historial)}
