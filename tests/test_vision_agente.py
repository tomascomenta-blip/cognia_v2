# -*- coding: utf-8 -*-
"""Tests del bucle percibir->decidir->actuar (seguro por defecto).

Con fakes: percepción inyectada + escritorio fake. Verifica dry-run por defecto,
el gate de permisos, y que sobre ventana sensible no se decide ni actúa."""
import importlib

import numpy as np

ap = importlib.import_module("cognia.vision.agente_pantalla")
pv = importlib.import_module("cognia.vision.percepcion")
from cognia.control.permisos import Accion, GestorPermisos  # noqa: E402


class FakeCap:
    def __init__(self): self.capturas = 0
    def frame(self):
        self.capturas += 1
        return np.full((8, 8, 4), self.capturas * 10 % 255, dtype=np.uint8)
    def guardar_png(self, ruta, frame=None): return ruta


class FakeEsc:
    def __init__(self, ventana="Bloc de notas", controles=None):
        self._v = ventana
        self._c = controles or [{"nombre": "Guardar", "tipo": "ButtonControl"}]
        self.clicks = []
    def ventana_activa(self): return self._v
    def listar_elementos(self, limite=60): return self._c[:limite]
    def clic(self, texto): self.clicks.append(texto); return f"RESULTADO clic OK: {texto}"
    def escribir(self, texto): return f"RESULTADO escribir OK"
    def enfocar(self, n): return "ok"
    def abrir_app(self, n): return "ok"


def _agente(ventana="Bloc de notas", ejecutar=False, confirmar=None):
    serv = pv.ServicioPercepcion(capturador=FakeCap(), escritorio=FakeEsc(ventana))
    esc = FakeEsc(ventana)
    perm = GestorPermisos(confirmar=confirmar, modo_estricto=True)
    ag = ap.AgentePantalla(servicio=serv, escritorio=esc, permisos=perm,
                           ejecutar=ejecutar)
    return ag, esc


def test_dry_run_por_defecto_no_ejecuta():
    ag, esc = _agente()
    reg = ag.paso(ap.politica_por_control("Guardar"))
    assert reg.intencion is not None and reg.intencion.tipo == "clic"
    assert reg.permitida is False        # clic = CONFIRMAR, sin canal -> denegada
    assert reg.ejecutada is False
    assert esc.clicks == []


def test_accion_confirmada_pero_dry_run_no_ejecuta():
    # con confirmar=True el gate permite, pero ejecutar=False -> sigue en sombra
    ag, esc = _agente(ejecutar=False, confirmar=lambda q: True)
    reg = ag.paso(ap.politica_por_control("Guardar"))
    assert reg.permitida is True
    assert reg.ejecutada is False
    assert "DRY-RUN" in reg.resultado
    assert esc.clicks == []


def test_ejecuta_cuando_activado_y_permitido():
    ag, esc = _agente(ejecutar=True, confirmar=lambda q: True)
    reg = ag.paso(ap.politica_por_control("Guardar"))
    assert reg.permitida is True and reg.ejecutada is True
    assert esc.clicks == ["Guardar"]


def test_ventana_sensible_no_decide_ni_actua():
    ag, esc = _agente(ventana="Bitwarden", ejecutar=True, confirmar=lambda q: True)
    reg = ag.paso(ap.politica_por_control("Guardar"))
    assert reg.intencion is None          # ni siquiera se consulta la politica
    assert reg.ejecutada is False
    assert "sensible" in reg.motivo.lower()
    assert esc.clicks == []


def test_politica_sin_match_no_propone():
    ag, esc = _agente()
    reg = ag.paso(ap.politica_por_control("NoExisteEsteControl"))
    assert reg.intencion is None
    assert reg.ejecutada is False


def test_bucle_para_por_max_pasos():
    ag, esc = _agente()
    regs = list(ag.bucle(ap.politica_por_control("Guardar"), max_pasos=3))
    assert len(regs) == 3
