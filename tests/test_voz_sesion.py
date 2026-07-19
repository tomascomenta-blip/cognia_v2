"""
tests/test_voz_sesion.py
========================
Maquina de estados de la conversacion hablada (planes/JARVIS_COGNIA.md 4.1).

Todo con piezas inyectadas: sin GPU, sin microfono y sin modelo. Lo que se fija
son las tres conductas absurdas que un asistente por voz tiene si los estados
estan mal manejados — transcribir su propia voz, aceptar una orden mientras
piensa la anterior, y quedarse escuchando para siempre.
"""

import pytest

from cognia.voz.sesion import (DESPIERTO, DORMIDO, ESCUCHANDO, HABLANDO,
                               PENSANDO, SesionVoz)


class _Voz:
    def __init__(self):
        self.dicho = []
        self.callada = 0

    def decir(self, texto, bloquear=False):
        self.dicho.append(texto)
        return True

    def callar(self):
        self.callada += 1


class _Reloj:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def avanzar(self, s):
        self.t += s


def _sesion(**kw):
    kw.setdefault("transcriptor", lambda a: "que hora es")
    kw.setdefault("cerebro", lambda t: "son las tres")
    kw.setdefault("voz", _Voz())
    kw.setdefault("reloj", _Reloj())
    return SesionVoz(**kw)


class TestTurnoCompleto:
    def test_de_dormido_a_respuesta_y_vuelta(self):
        s = _sesion()
        assert s.estado == DORMIDO
        assert s.al_detectar_palabra("cerebro") is True
        assert s.estado == DESPIERTO
        turno = s.procesar_turno(b"audio")
        assert turno["ok"] is True
        assert turno["texto"] == "que hora es"
        assert turno["respuesta"] == "son las tres"
        assert s.voz.dicho == ["son las tres"]
        assert s.estado == DORMIDO           # lista para la proxima
        assert s.turnos == 1

    def test_registra_el_historial(self):
        s = _sesion()
        for _ in range(3):
            s.al_detectar_palabra()
            s.procesar_turno(b"audio")
        assert s.estadisticas() == {"estado": DORMIDO, "turnos": 3,
                                    "historial": 3}


class TestNoEscuchaCuandoNoDebe:
    def test_dormida_ignora_el_audio(self):
        """Sin esto transcribiria cualquier ruido, incluida su propia voz."""
        s = _sesion()
        r = s.procesar_turno(b"ruido de la tele")
        assert r["ok"] is False
        assert "no esta despierta" in r["motivo"]
        assert s.voz.dicho == []

    def test_la_palabra_no_interrumpe_mientras_piensa(self):
        """Aceptarla ahi encolaria ordenes a medio procesar."""
        s = _sesion()
        s.al_detectar_palabra()
        s.estado = PENSANDO
        assert s.al_detectar_palabra() is False
        assert s.estado == PENSANDO

    def test_la_palabra_si_interrumpe_mientras_habla(self):
        """Lo que uno espera de un asistente es que se calle y escuche."""
        s = _sesion()
        s.estado = HABLANDO
        assert s.al_detectar_palabra() is True
        assert s.voz.callada == 1
        assert s.estado == DESPIERTO


class TestExpiracion:
    def test_se_duerme_si_nadie_habla(self):
        """Una activacion accidental no puede dejar el microfono abierto."""
        reloj = _Reloj()
        s = _sesion(reloj=reloj, espera_maxima=8.0)
        s.al_detectar_palabra()
        assert s.expiro() is False
        reloj.avanzar(8.5)
        assert s.expiro() is True
        s.dormir()
        assert s.estado == DORMIDO

    def test_dormida_no_expira(self):
        s = _sesion()
        assert s.expiro() is False

    def test_dormir_es_idempotente(self):
        s = _sesion()
        s.dormir()
        s.dormir()
        assert s.estado == DORMIDO


class TestDegradacion:
    def test_si_no_se_entendio_vuelve_a_dormir(self):
        s = _sesion(transcriptor=lambda a: "   ")
        s.al_detectar_palabra()
        r = s.procesar_turno(b"audio")
        assert r["ok"] is False and "no se entendio" in r["motivo"]
        assert s.estado == DORMIDO

    def test_un_stt_roto_no_tumba_la_sesion(self):
        def explota(audio):
            raise RuntimeError("whisper se cayo")
        s = _sesion(transcriptor=explota)
        s.al_detectar_palabra()
        assert s.procesar_turno(b"audio")["ok"] is False
        assert s.estado == DORMIDO
        # Y sigue atendiendo la proxima vez.
        s.transcriptor = lambda a: "hola"
        s.al_detectar_palabra()
        assert s.procesar_turno(b"audio")["ok"] is True

    def test_un_cerebro_roto_no_tumba_la_sesion(self):
        def explota(t):
            raise RuntimeError("el motor se cayo")
        s = _sesion(cerebro=explota)
        s.al_detectar_palabra()
        r = s.procesar_turno(b"audio")
        assert r["ok"] is False and r["texto"] == "que hora es"
        assert s.estado == DORMIDO

    def test_acepta_el_dict_de_responder_articulado(self):
        """El cerebro real devuelve un dict, no una cadena."""
        s = _sesion(cerebro=lambda t: {"response": "respuesta del motor"})
        s.al_detectar_palabra()
        assert s.procesar_turno(b"audio")["respuesta"] == "respuesta del motor"

    def test_funciona_sin_voz(self):
        """Sin TTS el turno se completa igual; solo no suena."""
        s = _sesion(voz=None)
        s.al_detectar_palabra()
        assert s.procesar_turno(b"audio")["ok"] is True
