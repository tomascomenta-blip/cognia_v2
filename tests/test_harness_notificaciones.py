# -*- coding: utf-8 -*-
"""
Regresion (2026-08-23): un turno del 27B local dura MINUTOS y Cognia no emitia
NINGUNA senal de "ya termine": el dueno volvia a la ventana a mirar.

Estos tests fijan el contrato de `cognia/harness/notificaciones.py` (F5,
patron Crush/Codex): la secuencia OSC 9 EXACTA que emite (ESC ] 9 ; texto BEL,
el toast de Windows Terminal), el gate de interactividad del modo auto (un
pipe/CI no recibe bytes de escape jamas), el umbral del turno largo (default
20 s), el apagado por env COGNIA_NOTIFY, el opt-in de los degradados y la
degradacion explicita (avisador UNA vez por sesion, nunca lanza).

Sin el modulo, el fichero entero falla en el import.

Todo corre contra buffers en memoria: el unico stream real que toca el modulo
en produccion es sys.__stdout__, y aqui se inyecta el destino.
"""

from __future__ import annotations

import io

import pytest

from cognia.harness import notificaciones as notif


class _TtyFalsa(io.StringIO):
    """Un buffer que dice ser terminal: el gate mira isatty(), no la clase."""

    def isatty(self):
        return True


class _StreamRoto(io.StringIO):
    """Un stream cuyo write revienta: el terminal que rechaza el escape."""

    def write(self, *_a, **_k):
        raise OSError("terminal cerrado")


@pytest.fixture(autouse=True)
def subsistema_aislado(monkeypatch):
    """Ni env del developer ni config real del CLI; telemetria fresca."""
    monkeypatch.delenv("COGNIA_NOTIFY", raising=False)
    monkeypatch.setattr(notif, "_leer_config_cli", lambda: {})
    monkeypatch.setattr(notif, "_AVISADOR", None)
    notif._AVISADO[0] = False
    notif._ULTIMO.clear()
    notif._ULTIMO_ERROR.clear()


# ── La secuencia exacta ───────────────────────────────────────────────────────

def test_osc9_secuencia_exacta_a_buffer():
    """El contrato con Windows Terminal: ESC ] 9 ; titulo: cuerpo BEL."""
    buf = _TtyFalsa()
    assert notif.notificar("Cognia", "turno terminado (25s)",
                           destino=buf, modo="osc") is True
    assert buf.getvalue() == "\x1b]9;Cognia: turno terminado (25s)\x07"


def test_bell_emite_solo_bel():
    buf = _TtyFalsa()
    assert notif.notificar("Cognia", "algo", destino=buf, modo="bell") is True
    assert buf.getvalue() == "\a"


def test_sanea_controles_dentro_del_texto():
    """Un ESC o BEL DENTRO del texto cerraria/romperia la propia secuencia y
    el resto se pintaria crudo en el terminal."""
    buf = _TtyFalsa()
    notif.notificar("Cog\x1bnia", "lin\x07ea\nrota", destino=buf, modo="osc")
    assert buf.getvalue() == "\x1b]9;Cognia: linearota\x07"


# ── El gate de interactividad del modo auto ───────────────────────────────────

def test_auto_sin_tty_no_emite_nada():
    """Un pipe (CI, captura, el canal del movil) JAMAS recibe escapes."""
    buf = io.StringIO()          # isatty() -> False
    assert notif.notificar("Cognia", "x", destino=buf, modo="auto") is False
    assert buf.getvalue() == ""


def test_auto_con_tty_emite_osc():
    buf = _TtyFalsa()
    assert notif.notificar("Cognia", "x", destino=buf, modo="auto") is True
    assert buf.getvalue().startswith("\x1b]9;")


# ── Off por env y por config ──────────────────────────────────────────────────

def test_env_off_es_silencio_total(monkeypatch):
    monkeypatch.setenv("COGNIA_NOTIFY", "off")
    buf = _TtyFalsa()
    assert notif.notificar("Cognia", "x", destino=buf) is False
    assert notif.notificar_evento("turno_terminado", duracion_s=999,
                                  destino=buf) is False
    assert buf.getvalue() == ""


def test_env_gana_a_la_config(monkeypatch):
    """COGNIA_NOTIFY=bell manda aunque la config diga modo osc."""
    monkeypatch.setenv("COGNIA_NOTIFY", "bell")
    monkeypatch.setattr(notif, "_leer_config_cli",
                        lambda: {"notificar_modo": "osc"})
    buf = _TtyFalsa()
    assert notif.notificar("Cognia", "x", destino=buf) is True
    assert buf.getvalue() == "\a"


def test_config_notificar_off_apaga(monkeypatch):
    monkeypatch.setattr(notif, "_leer_config_cli", lambda: {"notificar": "off"})
    buf = _TtyFalsa()
    assert notif.notificar("Cognia", "x", destino=buf) is False
    assert buf.getvalue() == ""


# ── El umbral del turno largo ─────────────────────────────────────────────────

def test_turno_corto_no_amerita_toast():
    """Bajo el umbral (default 20 s) el dueno sigue mirando: silencio."""
    buf = _TtyFalsa()
    assert notif.notificar_evento("turno_terminado", duracion_s=19.9,
                                  destino=buf) is False
    assert buf.getvalue() == ""


def test_turno_largo_notifica_con_los_segundos():
    buf = _TtyFalsa()
    assert notif.notificar_evento("turno_terminado", duracion_s=25.0,
                                  destino=buf) is True
    assert buf.getvalue() == "\x1b]9;Cognia: turno terminado (25s)\x07"


def test_umbral_configurable(monkeypatch):
    monkeypatch.setattr(notif, "_leer_config_cli",
                        lambda: {"notificar_umbral_s": "5"})
    buf = _TtyFalsa()
    assert notif.notificar_evento("turno_terminado", duracion_s=6,
                                  destino=buf) is True


# ── Degradados: opt-in, default off ───────────────────────────────────────────

def test_degradado_por_defecto_no_notifica():
    buf = _TtyFalsa()
    assert notif.notificar_evento("degradado", via="backend",
                                  detalle="caido", destino=buf) is False
    assert buf.getvalue() == ""


def test_degradado_opt_in_notifica(monkeypatch):
    monkeypatch.setattr(notif, "_leer_config_cli",
                        lambda: {"notificar_degradado": "on"})
    buf = _TtyFalsa()
    assert notif.notificar_evento("degradado", via="backend",
                                  detalle="caido", destino=buf) is True
    assert "backend: caido" in buf.getvalue()


# ── Degradacion del propio subsistema: avisa UNA vez, nunca lanza ─────────────

def test_fallo_emitiendo_avisa_una_sola_vez():
    avisos = []
    notif.registrar_avisador(lambda origen, motivo: avisos.append((origen, motivo)))
    roto = _StreamRoto()
    assert notif.notificar("Cognia", "x", destino=roto, modo="osc") is False
    assert notif.notificar("Cognia", "y", destino=roto, modo="osc") is False
    assert len(avisos) == 1
    assert avisos[0][0] == "notificaciones"
    assert "OSError" in avisos[0][1]
    # y la telemetria del ultimo error queda para /notificar estado
    assert "OSError" in notif.estado()["ultimo_error"]["motivo"]


def test_evento_sin_builder_se_degrada_no_calla():
    """'no lo cablearon' y 'se rompio' no pueden verse igual desde afuera."""
    avisos = []
    notif.registrar_avisador(lambda origen, motivo: avisos.append(motivo))
    assert notif.notificar_evento("no_existe", destino=_TtyFalsa()) is False
    assert len(avisos) == 1 and "no_existe" in avisos[0]


# ── Punto de extension ────────────────────────────────────────────────────────

def test_registry_eventos_es_extensible(monkeypatch):
    """Anadir un caso futuro = una entrada en EVENTOS, cero cambios al resto."""
    monkeypatch.setitem(notif.EVENTOS, "permiso_pedido",
                        lambda tool="", **_: ("Cognia", f"permiso: {tool}"))
    buf = _TtyFalsa()
    assert notif.notificar_evento("permiso_pedido", tool="ejecutar",
                                  destino=buf) is True
    assert buf.getvalue() == "\x1b]9;Cognia: permiso: ejecutar\x07"


# ── Regresion 2026-08-23 (revision adversarial): osc/bell a un PIPE ──────────

def test_modos_forzados_no_escriben_a_un_fd_real_que_no_es_tty(monkeypatch):
    """Solo 'auto' chequeaba tty: '/notificar modo osc' persistido en la
    config compartida hacia que la sesion remota (stdout=PIPE, el UNICO canal
    del movil) recibiera '\x1b]9;...\x07' pegado como prefijo de la linea
    '@EV {json}' siguiente — que dejaba de casar con startswith('@EV ') y el
    telefono perdia el evento de fin de turno. NINGUN modo puede escribirle
    bytes de escape al fd real si no es un terminal."""
    pipe = io.StringIO()                       # isatty() -> False, como un PIPE
    monkeypatch.setattr(notif, "_destino_real", lambda: pipe)
    for modo in ("osc", "bell", "auto"):
        assert notif.notificar("Cognia", "x", modo=modo) is False, modo
    assert pipe.getvalue() == ""               # ni un byte al canal
    # con el fd real siendo un terminal, los modos forzados siguen emitiendo
    tty = _TtyFalsa()
    monkeypatch.setattr(notif, "_destino_real", lambda: tty)
    assert notif.notificar("Cognia", "x", modo="osc") is True
    assert tty.getvalue() == "\x1b]9;Cognia: x\x07"
    # y un destino INYECTADO (tests, buffers propios) no queda gateado
    buf = io.StringIO()
    assert notif.notificar("Cognia", "y", destino=buf, modo="bell") is True
    assert buf.getvalue() == "\a"
