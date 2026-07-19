"""
cognia/pantalla/cambios.py
==========================
Deteccion de "momentos importantes" por hash perceptual
(planes/JARVIS_COGNIA.md 4.3).

La idea, que es la que usan los detectores de escena: en vez de guardar todos
los frames, se calcula un hash chico de cada uno y se compara con el anterior.
Si la distancia de Hamming supera un umbral, la pantalla cambio de verdad y ese
frame vale la pena. Es barato: el hash trabaja sobre una miniatura de 9x8 en
escala de grises, asi que el costo no depende del tamaño de la pantalla.

Se usa dHash (hash de diferencias) y no un hash criptografico porque tiene que
ser ROBUSTO a cambios minusculos: el cursor que parpadea, el reloj que avanza un
minuto o una animacion de un pixel no son "un momento importante". Un sha256
cambiaria entero con un solo pixel distinto, que es exactamente lo contrario de
lo que se necesita.
"""

import numpy as np

# Umbral por defecto: cuantos bits de los 64 tienen que diferir para considerar
# que la pantalla cambio. Calibrado a ojo y ajustable; el gate J5 del plan lo
# somete a medicion real (1 h de captura continua).
UMBRAL_HAMMING = 8


def _a_gris(frame: np.ndarray) -> np.ndarray:
    """Frame BGRA/BGR/RGB o ya gris -> matriz 2D float."""
    a = np.asarray(frame)
    if a.ndim == 2:
        return a.astype(np.float64)
    # Luminancia sobre los tres primeros canales. El orden BGR vs RGB cambia
    # que peso lleva cada canal, pero para DETECTAR CAMBIOS da igual: lo que
    # importa es que dos frames iguales den el mismo numero.
    return a[:, :, :3].astype(np.float64).mean(axis=2)


def dhash(frame: np.ndarray, tamano: int = 8) -> int:
    """Hash perceptual de diferencias, de tamano*tamano bits (64 por defecto).

    Reduce el frame a una miniatura de (tamano+1) x tamano en gris y compara
    cada pixel con su vecino de la derecha: cada comparacion es un bit. Lo que
    se codifica es el GRADIENTE, o sea la estructura de la imagen, que es
    estable ante cambios chicos de brillo.
    """
    gris = _a_gris(frame)
    mini = _redimensionar(gris, ancho=tamano + 1, alto=tamano)
    bits = mini[:, 1:] > mini[:, :-1]
    valor = 0
    for bit in bits.flatten():
        valor = (valor << 1) | int(bit)
    return valor


def _redimensionar(gris: np.ndarray, ancho: int, alto: int) -> np.ndarray:
    """Miniatura por promediado de bloques (area averaging), solo con numpy.

    No se usa PIL para que el hash no dependa de una libreria de imagenes ni de
    su version: el mismo frame tiene que dar el mismo hash siempre, incluso
    entre maquinas distintas.
    """
    alto_orig, ancho_orig = gris.shape
    filas = np.linspace(0, alto_orig, alto + 1).astype(int)
    cols = np.linspace(0, ancho_orig, ancho + 1).astype(int)
    salida = np.empty((alto, ancho), dtype=np.float64)
    for i in range(alto):
        f0, f1 = filas[i], max(filas[i + 1], filas[i] + 1)
        for j in range(ancho):
            c0, c1 = cols[j], max(cols[j + 1], cols[j] + 1)
            salida[i, j] = gris[f0:f1, c0:c1].mean()
    return salida


def distancia_hamming(a: int, b: int) -> int:
    """Cuantos bits difieren entre dos hashes."""
    return int(bin(a ^ b).count("1"))


class DetectorCambios:
    """Decide si un frame es un momento nuevo o mas de lo mismo.

        det = DetectorCambios(umbral=8)
        if det.es_cambio(frame):
            guardar(frame)

    Es con estado a proposito: compara siempre contra el ultimo frame ACEPTADO,
    no contra el inmediatamente anterior. Asi una deriva lenta (una barra de
    progreso que avanza de a un pixel) termina disparando cuando acumula cambio
    suficiente, en vez de no disparar nunca porque cada paso individual es chico.
    """

    def __init__(self, umbral: int = UMBRAL_HAMMING, tamano: int = 8):
        self.umbral = umbral
        self.tamano = tamano
        self.hash_actual: int | None = None
        self.ultima_distancia: int | None = None
        self.vistos = 0
        self.aceptados = 0

    def es_cambio(self, frame) -> bool:
        h = dhash(frame, tamano=self.tamano)
        self.vistos += 1
        if self.hash_actual is None:
            self.hash_actual = h
            self.aceptados += 1
            self.ultima_distancia = None
            return True               # el primer frame siempre es un momento
        distancia = distancia_hamming(self.hash_actual, h)
        self.ultima_distancia = distancia
        if distancia >= self.umbral:
            self.hash_actual = h
            self.aceptados += 1
            return True
        return False

    def estadisticas(self) -> dict:
        return {"vistos": self.vistos, "aceptados": self.aceptados,
                "descartados": self.vistos - self.aceptados,
                "umbral": self.umbral,
                "ultima_distancia": self.ultima_distancia}
