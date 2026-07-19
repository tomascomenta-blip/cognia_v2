"""
cognia/pantalla/captura.py
==========================
Captura de pantalla para Cognia (planes/JARVIS_COGNIA.md 4.3).

Usa `mss`, no DXcam. El plan original elegia DXcam por sus 240+ FPS, pero al
medirlo en esta maquina resulto que DXcam importa `cv2` de forma incondicional,
o sea que arrastra OpenCV entero. Y la ventaja no servia para nada: el diseño
captura a 2-4 FPS para quedarse con los momentos importantes, no para grabar
video. `mss` mide 60 FPS a 1920x1080 (medido 2026-07-19), entre 15 y 30 veces
mas de lo que hace falta, sin dependencias pesadas y ademas multiplataforma.

Devuelve frames como arrays numpy BGRA (alto, ancho, 4), que es lo que entrega
el backend sin conversiones: quien necesite otro formato convierte, para que
capturar no pague un costo que quiza nadie use.
"""

import numpy as np

# Regiones utiles: mss numera los monitores desde 1; el 0 es el escritorio
# virtual completo (todos los monitores juntos).
MONITOR_PRINCIPAL = 1
ESCRITORIO_COMPLETO = 0


class Capturador:
    """Captura frames de la pantalla o de una region.

    Se usa como context manager para que el recurso del sistema se libere
    siempre:

        with Capturador() as cam:
            frame = cam.frame()

    region: dict {'top','left','width','height'} o None para el monitor entero.
    """

    def __init__(self, monitor: int = MONITOR_PRINCIPAL, region: dict | None = None):
        self.monitor = monitor
        self.region = region
        self._sct = None

    def __enter__(self):
        self.abrir()
        return self

    def __exit__(self, *exc):
        self.cerrar()
        return False

    def abrir(self):
        if self._sct is not None:
            return
        import mss
        # mss.mss() esta deprecado a favor de mss.MSS(); se prefiere el nuevo
        # nombre y se cae al viejo para no romper con versiones anteriores.
        self._sct = (mss.MSS() if hasattr(mss, "MSS") else mss.mss())

    def cerrar(self):
        if self._sct is None:
            return
        try:
            self._sct.close()
        except Exception:
            pass
        self._sct = None

    def _objetivo(self) -> dict:
        if self.region is not None:
            return self.region
        return self._sct.monitors[self.monitor]

    def geometria(self) -> dict:
        """Que zona se esta capturando, sin capturar nada."""
        self.abrir()
        objetivo = self._objetivo()
        return {"top": objetivo["top"], "left": objetivo["left"],
                "width": objetivo["width"], "height": objetivo["height"]}

    def frame(self) -> np.ndarray:
        """Un frame como array BGRA (alto, ancho, 4)."""
        self.abrir()
        return np.asarray(self._sct.grab(self._objetivo()))

    def guardar_png(self, ruta, frame: np.ndarray | None = None) -> str:
        """Guarda un frame como PNG. Sirve para la memoria visual y para poder
        mandarle una captura al modelo de vision."""
        from PIL import Image
        if frame is None:
            frame = self.frame()
        # BGRA -> RGB: se descarta el canal alfa, que en pantalla es opaco.
        rgb = frame[:, :, [2, 1, 0]]
        Image.fromarray(rgb).save(str(ruta))
        return str(ruta)
