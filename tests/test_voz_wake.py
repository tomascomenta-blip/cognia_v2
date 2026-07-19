"""
tests/test_voz_wake.py
======================
Tests de la palabra de activacion (planes/JARVIS_COGNIA.md 4.1).

Con un modelo falso: no descargan pesos, no abren el microfono y no dependen de
que la maquina tenga tarjeta de sonido. Lo que se fija es la LOGICA de
activacion: umbral, antirrebote y que nada de esto pueda tumbar el hilo que
escucha.
"""

import numpy as np
import pytest

from cognia.voz.wake import (CHUNK_MUESTRAS, TASA_MUESTREO, DetectorPalabra,
                             Escucha)


class _ModeloFalso:
    """Doble de openwakeword.model.Model: devuelve puntajes guionados."""

    def __init__(self, secuencia):
        self.secuencia = list(secuencia)
        self.i = 0
        self.models = {"hey_jarvis": None}

    def predict(self, x):
        v = self.secuencia[min(self.i, len(self.secuencia) - 1)]
        self.i += 1
        return {"hey_jarvis": v, "alexa": 0.0}


class _Reloj:
    """Tiempo controlado, para probar el antirrebote sin esperar."""

    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def avanzar(self, seg):
        self.t += seg


def _chunk():
    return np.zeros(CHUNK_MUESTRAS, dtype=np.int16)


class TestDetector:
    def test_por_debajo_del_umbral_no_activa(self):
        det = DetectorPalabra(modelo=_ModeloFalso([0.1, 0.3, 0.49]),
                              umbral=0.5, reloj=_Reloj())
        assert [det.detecto(_chunk()) for _ in range(3)] == [None, None, None]
        assert det.detecciones == 0

    def test_por_encima_del_umbral_activa(self):
        det = DetectorPalabra(modelo=_ModeloFalso([0.9]), umbral=0.5,
                              reloj=_Reloj())
        assert det.detecto(_chunk()) == "hey_jarvis"
        assert det.detecciones == 1

    def test_devuelve_la_palabra_de_mayor_puntaje(self):
        class Dos:
            models = {}
            def predict(self, x):
                return {"hey_jarvis": 0.6, "alexa": 0.95}
        det = DetectorPalabra(modelo=Dos(), umbral=0.5, reloj=_Reloj())
        assert det.detecto(_chunk()) == "alexa"

    def test_umbral_mas_alto_filtra_mas(self):
        estricto = DetectorPalabra(modelo=_ModeloFalso([0.7]), umbral=0.9,
                                   reloj=_Reloj())
        laxo = DetectorPalabra(modelo=_ModeloFalso([0.7]), umbral=0.6,
                               reloj=_Reloj())
        assert estricto.detecto(_chunk()) is None
        assert laxo.detecto(_chunk()) == "hey_jarvis"


class TestAntirrebote:
    def test_una_activacion_por_vez_que_se_habla(self):
        """Decir la palabra una vez puntua alto durante varios trozos
        seguidos; tiene que disparar UNA sola activacion."""
        reloj = _Reloj()
        det = DetectorPalabra(modelo=_ModeloFalso([0.9] * 8), umbral=0.5,
                              antirrebote=2.0, reloj=reloj)
        activaciones = []
        for _ in range(8):
            reloj.avanzar(0.08)          # 80 ms por trozo, como el audio real
            p = det.detecto(_chunk())
            if p:
                activaciones.append(p)
        assert len(activaciones) == 1

    def test_pasado_el_antirrebote_vuelve_a_activar(self):
        reloj = _Reloj()
        det = DetectorPalabra(modelo=_ModeloFalso([0.9] * 4), umbral=0.5,
                              antirrebote=2.0, reloj=reloj)
        assert det.detecto(_chunk()) == "hey_jarvis"
        reloj.avanzar(2.5)
        assert det.detecto(_chunk()) == "hey_jarvis"
        assert det.detecciones == 2


class TestRobustez:
    def test_un_modelo_roto_no_lanza(self):
        """Si el modelo falla, escuchar sigue vivo y simplemente no detecta."""
        class Roto:
            models = {}
            def predict(self, x):
                raise RuntimeError("onnx se cayo")
        det = DetectorPalabra(modelo=Roto(), reloj=_Reloj())
        assert det.detecto(_chunk()) is None
        assert det.puntajes(_chunk()) == {}

    def test_un_callback_roto_no_corta_la_escucha(self):
        def explota(palabra):
            raise ValueError("el manejador esta mal")
        det = DetectorPalabra(modelo=_ModeloFalso([0.9] * 3), umbral=0.5,
                              antirrebote=0.0, reloj=_Reloj())
        escucha = Escucha(al_detectar=explota, detector=det)
        # No se propaga la excepcion y se siguen procesando los trozos.
        assert len(escucha.escuchar_de([_chunk() for _ in range(3)])) == 3


class TestEscucha:
    def test_escuchar_de_una_secuencia_sin_microfono(self):
        det = DetectorPalabra(modelo=_ModeloFalso([0.1, 0.2, 0.95, 0.1]),
                              umbral=0.5, antirrebote=0.0, reloj=_Reloj())
        vistas = []
        escucha = Escucha(al_detectar=vistas.append, detector=det)
        assert escucha.escuchar_de([_chunk() for _ in range(4)]) == ["hey_jarvis"]
        assert vistas == ["hey_jarvis"]

    def test_respeta_el_limite(self):
        det = DetectorPalabra(modelo=_ModeloFalso([0.9] * 10), umbral=0.5,
                              antirrebote=0.0, reloj=_Reloj())
        escucha = Escucha(detector=det)
        assert len(escucha.escuchar_de([_chunk() for _ in range(10)],
                                       limite=3)) == 3

    def test_arrancar_y_parar_sin_microfono_no_rompe(self):
        """Sin tarjeta de sonido el hilo termina solo; parar() no debe colgar."""
        escucha = Escucha(detector=DetectorPalabra(modelo=_ModeloFalso([0.0]),
                                                   reloj=_Reloj()),
                          dispositivo=-999)
        escucha.arrancar()
        assert escucha.escuchando is True
        escucha.parar(timeout=3.0)
        assert escucha.escuchando is False


class TestFormatoDeAudio:
    def test_constantes_son_las_que_espera_el_modelo(self):
        assert TASA_MUESTREO == 16000
        assert CHUNK_MUESTRAS == 1280          # 80 ms
        assert CHUNK_MUESTRAS / TASA_MUESTREO == pytest.approx(0.08)
