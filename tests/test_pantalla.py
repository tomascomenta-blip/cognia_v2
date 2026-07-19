"""
tests/test_pantalla.py
======================
Tests de cognia/pantalla (ojos de Cognia, planes/JARVIS_COGNIA.md 4.3).

Todo CPU y sin tocar la pantalla real: el Vigia acepta un capturador inyectado,
asi que la deteccion de momentos se prueba con secuencias de frames guionadas.
La prueba contra la pantalla de verdad se hace por CLI, no aca.
"""

import numpy as np
import pytest

from cognia.pantalla.cambios import (UMBRAL_HAMMING, DetectorCambios, dhash,
                                     distancia_hamming)
from cognia.pantalla.vigia import Vigia


def _frame(valor=0, alto=120, ancho=160):
    """Frame BGRA liso."""
    a = np.full((alto, ancho, 4), valor, dtype=np.uint8)
    a[:, :, 3] = 255
    return a


def _frame_estructurado(semilla=0, alto=120, ancho=160):
    """Frame perceptualmente distinto por semilla: bloques claros en posiciones
    que dependen de ella.

    OJO, esto costo dos tests rojos: la primera version variaba solo RUIDO
    sobre un gradiente fijo, y el hash perceptual —haciendo exactamente lo que
    debe— promediaba ese ruido al reducir a 9x8 y devolvia el MISMO hash para
    todas las semillas. Para que dos frames tengan hashes distintos hay que
    cambiarles la estructura, no salpicarlos.
    """
    rng = np.random.default_rng(semilla)
    base = np.full((alto, ancho), 20.0)
    for _ in range(6):
        y = int(rng.integers(0, alto - 24))
        x = int(rng.integers(0, ancho - 24))
        base[y:y + 24, x:x + 24] = float(rng.integers(140, 255))
    a = np.zeros((alto, ancho, 4), dtype=np.uint8)
    for c in range(3):
        a[:, :, c] = np.clip(base, 0, 255).astype(np.uint8)
    a[:, :, 3] = 255
    return a


class TestDhash:
    def test_determinista_y_de_64_bits(self):
        f = _frame_estructurado(1)
        assert dhash(f) == dhash(f)          # mismo frame, mismo hash
        assert 0 <= dhash(f) < 2 ** 64

    def test_frames_iguales_distancia_cero(self):
        a, b = _frame_estructurado(2), _frame_estructurado(2)
        assert distancia_hamming(dhash(a), dhash(b)) == 0

    def test_cambio_minusculo_no_mueve_casi_el_hash(self):
        """Robustez: el cursor parpadeando no es 'un momento importante'."""
        a = _frame_estructurado(3)
        b = a.copy()
        b[0:3, 0:3, :3] = 0                  # 9 pixeles de 19200
        assert distancia_hamming(dhash(a), dhash(b)) < UMBRAL_HAMMING

    def test_pantalla_distinta_mueve_mucho_el_hash(self):
        a, b = _frame_estructurado(4), _frame_estructurado(44)
        assert distancia_hamming(dhash(a), dhash(b)) >= UMBRAL_HAMMING

    def test_espejar_un_gradiente_invierte_todos_los_bits(self):
        """Caso limite util de conocer: dHash codifica el gradiente
        horizontal, asi que espejar la imagen invierte los 64 bits y da la
        distancia maxima. Un umbral de 64 nunca dispararia con '>' en vez de
        '>=', por eso el detector usa '>='."""
        grad = np.zeros((120, 160, 4), dtype=np.uint8)
        for c in range(3):
            grad[:, :, c] = np.linspace(0, 255, 160,
                                        dtype=np.uint8)[None, :].repeat(120, 0)
        grad[:, :, 3] = 255
        assert distancia_hamming(dhash(grad), dhash(np.flip(grad, axis=1))) == 64

    def test_acepta_gris_y_color(self):
        color = _frame_estructurado(5)
        gris = color[:, :, :3].astype(np.float64).mean(axis=2)
        assert dhash(gris) == dhash(color)


class TestDetectorCambios:
    def test_el_primer_frame_siempre_es_momento(self):
        det = DetectorCambios()
        assert det.es_cambio(_frame_estructurado(6)) is True
        assert det.ultima_distancia is None

    def test_frames_repetidos_se_descartan(self):
        det = DetectorCambios()
        f = _frame_estructurado(7)
        assert det.es_cambio(f) is True
        for _ in range(5):
            assert det.es_cambio(f) is False
        assert det.estadisticas()["descartados"] == 5

    def test_compara_contra_el_ultimo_aceptado_no_contra_el_anterior(self):
        """Una deriva lenta tiene que terminar disparando: si comparara contra
        el frame inmediatamente anterior, cada paso chico seria 'sin cambio' y
        no dispararia nunca."""
        det = DetectorCambios(umbral=4)
        base = _frame_estructurado(8)
        det.es_cambio(base)
        disparo = False
        f = base.copy()
        for paso in range(1, 40):
            # Se va tapando la imagen de a poco, columna por columna.
            f = base.copy()
            f[:, :paso * 4, :3] = 0
            if det.es_cambio(f):
                disparo = True
                break
        assert disparo, "la deriva acumulada nunca disparo"

    def test_umbral_alto_descarta_mas(self):
        a, b = _frame_estructurado(9), _frame_estructurado(99)
        laxo, estricto = DetectorCambios(umbral=1), DetectorCambios(umbral=64)
        laxo.es_cambio(a)
        estricto.es_cambio(a)
        # El mismo par de frames: el laxo lo llama momento y el estricto no.
        assert laxo.es_cambio(b) is True
        assert estricto.es_cambio(b) is False


class _CapturadorFalso:
    """Fuente de frames guionada, para no depender de la pantalla real."""

    def __init__(self, frames):
        self.frames = list(frames)
        self.i = 0

    def frame(self):
        f = self.frames[min(self.i, len(self.frames) - 1)]
        self.i += 1
        return f

    def abrir(self):
        pass

    def cerrar(self):
        pass

    def guardar_png(self, ruta, frame=None):
        from PIL import Image
        Image.fromarray(self.frames[0][:, :, [2, 1, 0]]).save(str(ruta))
        return str(ruta)


class TestVigia:
    def test_entrega_solo_los_frames_que_cambiaron(self):
        a, b = _frame_estructurado(10), _frame_estructurado(110)
        # a a a b b b -> dos momentos: el primer a y el primer b. Los cuatro
        # frames repetidos se descartan, que es todo el punto del subsistema.
        cam = _CapturadorFalso([a, a, a, b, b, b])
        vig = Vigia(fps=1000, max_momentos=2)
        momentos = list(vig.mirar(segundos=5, _capturador=cam))
        assert len(momentos) == 2
        assert momentos[0].distancia is None          # el primero no compara
        assert momentos[1].distancia >= UMBRAL_HAMMING
        assert vig.estadisticas()["descartados"] >= 2

    def test_respeta_max_momentos(self):
        frames = [_frame_estructurado(i) for i in range(20)]
        cam = _CapturadorFalso(frames)
        vig = Vigia(fps=1000, umbral=1, max_momentos=3)
        assert len(list(vig.mirar(segundos=5, _capturador=cam))) == 3

    def test_guarda_png_cuando_se_pide(self, tmp_path):
        a = _frame_estructurado(11)
        cam = _CapturadorFalso([a])
        vig = Vigia(fps=1000, max_momentos=1, guardar_en=tmp_path)
        momentos = list(vig.mirar(segundos=5, _capturador=cam))
        assert len(momentos) == 1
        assert momentos[0].ruta is not None
        assert list(tmp_path.glob("*.png"))

    def test_fps_invalido_falla_temprano(self):
        with pytest.raises(ValueError):
            Vigia(fps=0)
