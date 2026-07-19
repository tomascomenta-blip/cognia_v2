"""
cognia/pantalla/vigia.py
========================
Ata captura y deteccion de cambios: mira la pantalla a un ritmo bajo y entrega
SOLO los frames en los que algo cambio de verdad
(planes/JARVIS_COGNIA.md 4.3).

    for momento in Vigia(fps=2).mirar(segundos=60):
        print(momento.instante, momento.distancia)

Se captura a 2-4 FPS a proposito. El backend da 60 FPS, pero el objetivo no es
grabar video: es quedarse con los momentos importantes gastando lo minimo. A
2 FPS el costo es el hash de dos miniaturas por segundo.

PRIVACIDAD (restriccion dura del repo: cero datos personales centralizados):
esto no manda nada a ningun lado. `guardar_en` escribe PNGs en disco local y
nada mas. La pausa por ventana sensible que pide el plan (gestores de
contraseñas, ventanas de incognito) todavia NO esta implementada: hasta que lo
este, no conviene dejar el vigia corriendo desatendido.
"""

import time
from dataclasses import dataclass
from pathlib import Path

from cognia.pantalla.cambios import UMBRAL_HAMMING, DetectorCambios
from cognia.pantalla.captura import Capturador


@dataclass
class Momento:
    """Un instante en que la pantalla cambio."""
    instante: float           # time.time() de la captura
    indice: int               # cuantos frames se habian mirado
    distancia: int | None     # bits de diferencia contra el momento anterior
    frame: object             # array numpy BGRA
    ruta: str | None = None   # PNG en disco, si se pidio guardar


class Vigia:
    """Mira la pantalla y entrega los momentos distintos.

    fps: cuantas veces por segundo se mira (2-4 es lo razonable).
    umbral: bits de diferencia para considerar que cambio (ver cambios.py).
    guardar_en: carpeta donde escribir un PNG por momento, o None para no
                tocar el disco.
    """

    def __init__(self, fps: float = 2.0, umbral: int = UMBRAL_HAMMING,
                 region: dict | None = None, guardar_en=None,
                 max_momentos: int | None = None):
        if fps <= 0:
            raise ValueError("fps tiene que ser > 0")
        self.fps = fps
        self.region = region
        self.detector = DetectorCambios(umbral=umbral)
        self.guardar_en = Path(guardar_en) if guardar_en else None
        self.max_momentos = max_momentos
        if self.guardar_en:
            self.guardar_en.mkdir(parents=True, exist_ok=True)

    def mirar(self, segundos: float | None = None, _capturador=None):
        """Generador de Momentos. segundos=None mira hasta que lo corten.

        _capturador existe para poder inyectar una fuente de frames en los
        tests sin tocar la pantalla real.
        """
        intervalo = 1.0 / self.fps
        limite = None if segundos is None else time.time() + segundos
        cam = _capturador or Capturador(region=self.region)
        propio = _capturador is None
        if propio:
            cam.abrir()
        entregados = 0
        try:
            while limite is None or time.time() < limite:
                inicio = time.time()
                frame = cam.frame()
                if frame is not None and self.detector.es_cambio(frame):
                    momento = Momento(instante=inicio,
                                      indice=self.detector.vistos,
                                      distancia=self.detector.ultima_distancia,
                                      frame=frame)
                    if self.guardar_en is not None:
                        nombre = "momento_%d_%d.png" % (int(inicio * 1000),
                                                        momento.indice)
                        momento.ruta = cam.guardar_png(
                            self.guardar_en / nombre, frame)
                    yield momento
                    entregados += 1
                    if self.max_momentos and entregados >= self.max_momentos:
                        return
                # Dormir lo que falte para el ritmo pedido; si el ciclo ya
                # tardo mas que el intervalo, seguir sin dormir.
                resto = intervalo - (time.time() - inicio)
                if resto > 0:
                    time.sleep(resto)
        finally:
            if propio:
                cam.cerrar()

    def estadisticas(self) -> dict:
        return self.detector.estadisticas()
