"""
cognia/voz — oidos y boca de Cognia.

Segun planes/JARVIS_COGNIA.md 4.1.

  wake.py   DetectorPalabra + Escucha: la palabra de activacion
  stt.py    faster-whisper                       — pendiente (necesita la GPU)
  tts.py    Piper                                — pendiente
  sesion.py maquina de estados de la conversacion — pendiente

Sobre "cerebro": openWakeWord trae 6 modelos preentrenados (alexa, hey_jarvis,
hey_mycroft, hey_rhasspy, timer, weather) y "cerebro" NO es uno de ellos. Hay
que entrenar un modelo propio con muestras sinteticas de TTS, que es el gate J1
del plan. Hasta entonces el modulo funciona con cualquier modelo disponible, asi
que el resto de la cadena se puede construir y probar con `hey_jarvis` sin
esperar a eso.
"""

from cognia.voz.wake import (CHUNK_MUESTRAS, TASA_MUESTREO, DetectorPalabra,
                             Escucha, modelos_disponibles)

__all__ = ["DetectorPalabra", "Escucha", "modelos_disponibles",
           "TASA_MUESTREO", "CHUNK_MUESTRAS"]
