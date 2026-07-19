"""
cognia/voz — oidos y boca de Cognia.

Segun planes/JARVIS_COGNIA.md 4.1.

  wake.py   DetectorPalabra + Escucha: la palabra de activacion
  tts.py    Voz: sintesis con Piper, interrumpible
  sesion.py SesionVoz: maquina de estados que coordina el turno hablado
  stt.py    faster-whisper                       — pendiente (necesita la GPU)

Sobre "cerebro": openWakeWord trae 6 modelos preentrenados (alexa, hey_jarvis,
hey_mycroft, hey_rhasspy, timer, weather) y "cerebro" NO es uno de ellos. Hay
que entrenar un modelo propio con muestras sinteticas de TTS, que es el gate J1
del plan. Hasta entonces el modulo funciona con cualquier modelo disponible, asi
que el resto de la cadena se puede construir y probar con `hey_jarvis` sin
esperar a eso.
"""

from cognia.voz.sesion import (DESPIERTO, DORMIDO, ESCUCHANDO, HABLANDO,
                               PENSANDO, SesionVoz)
from cognia.voz.tts import VOZ_POR_DEFECTO, Voz, descargar_voz, voces_instaladas
from cognia.voz.wake import (CHUNK_MUESTRAS, TASA_MUESTREO, DetectorPalabra,
                             Escucha, modelos_disponibles)

__all__ = ["DetectorPalabra", "Escucha", "SesionVoz", "Voz",
           "modelos_disponibles", "voces_instaladas", "descargar_voz",
           "TASA_MUESTREO", "CHUNK_MUESTRAS", "VOZ_POR_DEFECTO",
           "DORMIDO", "DESPIERTO", "ESCUCHANDO", "PENSANDO", "HABLANDO"]
