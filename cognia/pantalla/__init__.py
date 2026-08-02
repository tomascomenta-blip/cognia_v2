"""
cognia/pantalla — ojos de Cognia.

Captura de pantalla y deteccion de momentos importantes, segun
planes/JARVIS_COGNIA.md seccion 4.3.

  captura.py  Capturador: frames de la pantalla o de una region (mss)
  cambios.py  DetectorCambios: hash perceptual para quedarse solo con los
              frames en los que la pantalla REALMENTE cambio

Vigia se retiro (superado por cognia/vision/percepcion.ServicioPercepcion).
"""

from cognia.pantalla.cambios import DetectorCambios, dhash, distancia_hamming
from cognia.pantalla.captura import Capturador

__all__ = ["Capturador", "DetectorCambios", "dhash", "distancia_hamming"]
