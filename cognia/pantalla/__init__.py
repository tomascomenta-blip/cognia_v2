"""
cognia/pantalla — ojos de Cognia.

Captura de pantalla y deteccion de momentos importantes, segun
planes/JARVIS_COGNIA.md seccion 4.3.

  captura.py  Capturador: frames de la pantalla o de una region (mss)
  cambios.py  DetectorCambios: hash perceptual para quedarse solo con los
              frames en los que la pantalla REALMENTE cambio
  vigia.py    Vigia: ata las dos cosas y entrega solo los momentos distintos
"""

from cognia.pantalla.cambios import DetectorCambios, dhash, distancia_hamming
from cognia.pantalla.captura import Capturador
from cognia.pantalla.vigia import Vigia

__all__ = ["Capturador", "DetectorCambios", "Vigia", "dhash",
           "distancia_hamming"]
