"""
tests/test_voz_tts.py
=====================
Tests de la boca de Cognia (planes/JARVIS_COGNIA.md 4.1).

Con una voz falsa: no descargan modelos (60 MB) ni abren la tarjeta de sonido.
La prueba con Piper de verdad se hace por CLI.
"""

import wave

from cognia.voz.tts import VOZ_POR_DEFECTO, Voz, voces_instaladas


class _Trozo:
    def __init__(self, audio, tasa=22050):
        self.audio_int16_bytes = audio
        self.sample_rate = tasa


class _VozFalsa:
    """Doble de PiperVoice."""

    def __init__(self, trozos=None, explota=False):
        self.trozos = trozos
        self.explota = explota
        self.pedidos = []

    def synthesize(self, texto):
        self.pedidos.append(texto)
        if self.explota:
            raise RuntimeError("onnx se cayo")
        if self.trozos is not None:
            return list(self.trozos)
        return [_Trozo(b"\x01\x00" * 100), _Trozo(b"\x02\x00" * 100)]


class TestSintetizar:
    def test_concatena_los_trozos(self):
        v = Voz(backend=_VozFalsa())
        audio, tasa = v.sintetizar("hola")
        assert audio == b"\x01\x00" * 100 + b"\x02\x00" * 100
        assert tasa == 22050

    def test_pasa_el_texto_a_la_voz(self):
        falsa = _VozFalsa()
        Voz(backend=falsa).sintetizar("buenos dias")
        assert falsa.pedidos == ["buenos dias"]

    def test_una_voz_rota_no_tumba_a_cognia(self):
        """Que no funcione la voz no puede romper la respuesta."""
        audio, tasa = Voz(backend=_VozFalsa(explota=True)).sintetizar("hola")
        assert audio == b""
        assert tasa == 22050

    def test_sin_trozos_devuelve_vacio(self):
        audio, _ = Voz(backend=_VozFalsa(trozos=[])).sintetizar("")
        assert audio == b""


class TestGuardarWav:
    def test_escribe_un_wav_valido(self, tmp_path):
        destino = tmp_path / "salida.wav"
        v = Voz(backend=_VozFalsa())
        assert v.guardar_wav("hola", destino) == str(destino)
        with wave.open(str(destino), "rb") as w:
            assert w.getnchannels() == 1
            assert w.getsampwidth() == 2          # int16
            assert w.getframerate() == 22050
            assert w.getnframes() == 200          # 400 bytes / 2

    def test_si_falla_la_sintesis_no_deja_archivo_a_medias(self, tmp_path):
        destino = tmp_path / "nada.wav"
        v = Voz(backend=_VozFalsa(explota=True))
        assert v.guardar_wav("hola", destino) is None
        assert not destino.exists()


class TestReproduccion:
    def test_decir_sin_audio_devuelve_false(self):
        assert Voz(backend=_VozFalsa(explota=True)).decir("hola") is False

    def test_decir_bloqueante_termina_solo(self):
        """Sin tarjeta de sonido _reproducir sale enseguida; no debe colgar."""
        v = Voz(backend=_VozFalsa())
        assert v.decir("hola", bloquear=True) is True
        assert v.hablando is False

    def test_callar_es_idempotente(self):
        v = Voz(backend=_VozFalsa())
        v.callar()
        v.callar()
        assert v.hablando is False

    def test_decir_dos_veces_no_superpone_voces(self):
        v = Voz(backend=_VozFalsa())
        v.decir("primera")
        v.decir("segunda")          # corta la anterior antes de arrancar
        v.callar()
        assert v.hablando is False


class TestVocesInstaladas:
    def test_directorio_inexistente(self, tmp_path):
        assert voces_instaladas(tmp_path / "no_existe") == []

    def test_lista_los_onnx(self, tmp_path):
        (tmp_path / "es_ES-davefx-medium.onnx").write_bytes(b"x")
        (tmp_path / "es_ES-davefx-medium.onnx.json").write_bytes(b"{}")
        (tmp_path / "otra_cosa.txt").write_bytes(b"x")
        assert voces_instaladas(tmp_path) == ["es_ES-davefx-medium"]

    def test_la_voz_por_defecto_es_en_español(self):
        assert VOZ_POR_DEFECTO.startswith("es_")
