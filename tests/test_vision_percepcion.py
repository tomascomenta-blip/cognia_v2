# -*- coding: utf-8 -*-
"""Tests del servicio de percepción de pantalla (modo sombra, read-only).

Todo con capturador/escritorio INYECTADOS (fakes) -> no toca la pantalla real ni
requiere mss/uiautomation. Verifica la composición y, sobre todo, la SEGURIDAD:
sobre ventana sensible NO se captura y la percepción sale redactada."""
import importlib

import numpy as np
import pytest

pv = importlib.import_module("cognia.vision.percepcion")


class FakeCapturador:
    def __init__(self, frames):
        self.frames = frames
        self.i = 0
        self.capturas = 0          # cuántas veces se pidió frame (para la prueba de seguridad)
        self.guardados = []

    def frame(self):
        self.capturas += 1
        f = self.frames[min(self.i, len(self.frames) - 1)]
        self.i += 1
        return f

    def guardar_png(self, ruta, frame=None):
        self.guardados.append(ruta)
        return ruta


class FakeEscritorio:
    def __init__(self, ventana="Editor - archivo.txt", controles=None):
        self._ventana = ventana
        self._controles = controles or [{"nombre": "Guardar", "tipo": "ButtonControl"},
                                        {"nombre": "Cerrar", "tipo": "ButtonControl"}]

    def ventana_activa(self):
        return self._ventana

    def listar_elementos(self, limite=60):
        return self._controles[:limite]


def _frame(v):
    return np.full((16, 16, 4), v, dtype=np.uint8)


def _serv(ventana="Editor - archivo.txt", frames=None):
    cap = FakeCapturador(frames or [_frame(10), _frame(200)])
    esc = FakeEscritorio(ventana=ventana)
    return pv.ServicioPercepcion(capturador=cap, escritorio=esc), cap, esc


def test_instantanea_normal():
    serv, cap, esc = _serv()
    p = serv.instantanea()
    assert p.sensible is False
    assert p.ventana == "Editor - archivo.txt"
    assert p.ancho == 16 and p.alto == 16
    assert any(c["nombre"] == "Guardar" for c in p.controles)
    assert cap.capturas == 1


def test_instantanea_ventana_sensible_no_captura():
    # SEGURIDAD: sobre un gestor de contraseñas no se captura ni se leen controles.
    serv, cap, esc = _serv(ventana="Bitwarden - Gestor de contraseñas")
    p = serv.instantanea()
    assert p.sensible is True
    assert p.controles == []
    assert cap.capturas == 0          # nunca se llamó a frame()
    assert "sensible" in pv.describir(p).lower()


def test_describir_normal_lista_controles():
    serv, _, _ = _serv()
    txt = pv.describir(serv.instantanea())
    assert "Editor - archivo.txt" in txt
    assert "Guardar" in txt


def test_percibir_para_por_max_momentos():
    serv, cap, esc = _serv(frames=[_frame(10), _frame(200), _frame(50), _frame(90)])
    momentos = list(serv.percibir(max_momentos=2, solo_cambios=False))
    assert len(momentos) == 2
    assert all(isinstance(m, pv.Percepcion) for m in momentos)


def test_percibir_solo_cambios_filtra_iguales():
    # frames idénticos -> tras el primero, no hay cambio -> solo_cambios no emite
    serv, cap, esc = _serv(frames=[_frame(77)] * 6)
    momentos = list(serv.percibir(max_momentos=1, solo_cambios=True, segundos=2))
    # el primer frame siempre es cambio (DetectorCambios) -> 1 emitido y corta
    assert len(momentos) == 1
    assert momentos[0].cambio is True


def test_percibir_sensible_redacta_sin_capturar():
    serv, cap, esc = _serv(ventana="Banca en linea - PayPal")
    momentos = list(serv.percibir(max_momentos=1, solo_cambios=False))
    assert momentos[0].sensible is True
    assert cap.capturas == 0


def test_guardar_frame_opcional():
    serv, cap, esc = _serv()
    p = serv.instantanea(guardar_en="salida.png")
    assert p.ruta_frame == "salida.png"
    assert cap.guardados == ["salida.png"]
