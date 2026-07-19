"""
tests/test_voz_stt.py
=====================
Tests del oido de Cognia (planes/JARVIS_COGNIA.md 4.1).

Con un backend falso: no descargan pesos ni ocupan GPU, que hoy esta tomada por
el entrenamiento del BDraft. La prueba con Whisper de verdad es el ida y vuelta
Piper -> Whisper, y se hace por CLI.
"""

import wave

import numpy as np
import pytest

from cognia.voz.stt import (TASA_WHISPER, Transcriptor, audio_de_wav,
                            remuestrear)


class _Segmento:
    def __init__(self, text):
        self.text = text


class _WhisperFalso:
    def __init__(self, texto="hola que tal", explota=False):
        self.texto = texto
        self.explota = explota
        self.recibido = []

    def transcribe(self, audio, language=None):
        if self.explota:
            raise RuntimeError("ctranslate2 se cayo")
        self.recibido.append((len(audio), language))
        return [_Segmento(p) for p in self.texto.split("|")], {"language": language}


def _wav(tmp_path, tasa=22050, segundos=0.5, canales=1):
    ruta = tmp_path / "audio.wav"
    n = int(tasa * segundos)
    t = np.linspace(0, segundos, n, dtype=np.float32)
    onda = (np.sin(2 * np.pi * 440 * t) * 16000).astype(np.int16)
    if canales > 1:
        onda = np.repeat(onda[:, None], canales, axis=1).ravel()
    with wave.open(str(ruta), "wb") as w:
        w.setnchannels(canales)
        w.setsampwidth(2)
        w.setframerate(tasa)
        w.writeframes(onda.tobytes())
    return ruta


class TestLecturaDeWav:
    def test_lee_mono(self, tmp_path):
        muestras, tasa = audio_de_wav(_wav(tmp_path))
        assert tasa == 22050
        assert muestras.dtype == np.float32
        assert -1.0 <= muestras.min() and muestras.max() <= 1.0

    def test_mezcla_estereo_a_mono(self, tmp_path):
        muestras, _ = audio_de_wav(_wav(tmp_path, canales=2))
        assert muestras.ndim == 1

    def test_rechaza_ancho_distinto_de_16_bits(self, tmp_path):
        ruta = tmp_path / "raro.wav"
        with wave.open(str(ruta), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(1)          # 8 bits
            w.setframerate(16000)
            w.writeframes(b"\x00" * 100)
        with pytest.raises(ValueError):
            audio_de_wav(ruta)


class TestRemuestreo:
    def test_de_22050_a_16000(self):
        x = np.random.default_rng(0).standard_normal(22050).astype(np.float32)
        y = remuestrear(x, 22050, 16000)
        assert len(y) == 16000
        assert y.dtype == np.float32

    def test_misma_tasa_no_toca_nada(self):
        x = np.zeros(100, dtype=np.float32)
        assert remuestrear(x, 16000, 16000) is x

    def test_audio_vacio(self):
        assert remuestrear(np.array([], dtype=np.float32), 22050).size == 0


class TestTranscriptor:
    def test_une_los_segmentos(self):
        t = Transcriptor(backend=_WhisperFalso("hola|que tal"))
        assert t.transcribir(np.zeros(16000, dtype=np.float32)) == "hola que tal"

    def test_remuestrea_antes_de_transcribir(self):
        falso = _WhisperFalso()
        t = Transcriptor(backend=falso)
        t.transcribir(np.zeros(22050, dtype=np.float32), tasa=22050)
        assert falso.recibido[0][0] == TASA_WHISPER      # 1 s a 16 kHz

    def test_pasa_el_idioma(self):
        falso = _WhisperFalso()
        Transcriptor(backend=falso, idioma="es").transcribir(
            np.zeros(16000, dtype=np.float32))
        assert falso.recibido[0][1] == "es"

    def test_audio_vacio_devuelve_cadena_vacia(self):
        t = Transcriptor(backend=_WhisperFalso())
        assert t.transcribir(np.array([], dtype=np.float32)) == ""

    def test_un_backend_roto_no_tumba_la_sesion(self):
        t = Transcriptor(backend=_WhisperFalso(explota=True))
        assert t.transcribir(np.zeros(16000, dtype=np.float32)) == ""

    def test_wav_inexistente_devuelve_vacio(self):
        t = Transcriptor(backend=_WhisperFalso())
        assert t.transcribir_wav("no_existe_este_archivo.wav") == ""

    def test_descargar_suelta_el_modelo(self):
        """Con la GPU compartida con un 7B, tenerlo residente es VRAM regalada."""
        t = Transcriptor(backend=_WhisperFalso())
        assert t._backend is not None
        t.descargar()
        assert t._backend is None


class TestEnchufableEnLaSesion:
    def test_acepta_ruta_bytes_y_array(self, tmp_path):
        t = Transcriptor(backend=_WhisperFalso("ok"))
        assert t(_wav(tmp_path)) == "ok"
        assert t(np.zeros(1600, dtype=np.int16).tobytes()) == "ok"
        assert t(np.zeros(16000, dtype=np.float32)) == "ok"

    def test_funciona_como_transcriptor_de_SesionVoz(self):
        from cognia.voz.sesion import SesionVoz
        s = SesionVoz(transcriptor=Transcriptor(backend=_WhisperFalso("que hora es")),
                      cerebro=lambda t: "son las tres")
        s.al_detectar_palabra()
        turno = s.procesar_turno(np.zeros(16000, dtype=np.float32))
        assert turno["ok"] is True
        assert turno["texto"] == "que hora es"
