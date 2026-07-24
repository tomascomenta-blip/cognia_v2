# -*- coding: utf-8 -*-
"""`/ver`: el puente entre los ojos de Cognia y su cerebro de texto.

cognia/vision/ sabia percibir la pantalla desde hace tiempo (captura + arbol UIA
-> texto, ventanas sensibles redactadas) pero NADIE podia alcanzarlo: no habia
comando. Capacidad construida, probada y desconectada. Esto cubre el puente.

No se prueba la captura real (depende del SO y de que haya escritorio): se
inyectan percepciones de mentira y se verifica el contrato.
"""
import types

import pytest

from cognia.vision.mirar import percibir_pantalla, ver


class _PercepcionFalsa:
    def __init__(self, ventana="Bloc de notas", sensible=False):
        self.ventana = ventana
        self.sensible = sensible
        self.ancho, self.alto = 1920, 1080
        self.cambio = True
        self.ruta_frame = None
        self.controles = [{"nombre": "Archivo"}, {"nombre": "Guardar"}]
        self.instante = 0.0


def _inyectar(monkeypatch, percepcion):
    """Hace que ServicioPercepcion().instantanea() devuelva lo que queramos."""
    import cognia.vision.percepcion as vp
    monkeypatch.setattr(vp.ServicioPercepcion, "instantanea",
                        lambda self, **k: percepcion)


def test_sin_pregunta_describe_lo_que_ve(monkeypatch):
    _inyectar(monkeypatch, _PercepcionFalsa())
    salida = ver()
    assert "Bloc de notas" in salida
    assert "Archivo" in salida and "Guardar" in salida


def test_ventana_sensible_no_se_describe(monkeypatch):
    """Sobre una ventana sensible la percepcion viene redactada y se respeta."""
    _inyectar(monkeypatch, _PercepcionFalsa(ventana="Banco - incognito", sensible=True))
    salida = ver("que ves?", ai=object())
    assert "sensible" in salida.lower()
    assert "Archivo" not in salida          # no se filtran controles


def test_con_pregunta_usa_el_cerebro(monkeypatch):
    """La pregunta va al modelo CON lo que se ve como contexto."""
    _inyectar(monkeypatch, _PercepcionFalsa())
    visto = {}

    class _Orq:
        def infer(self, prompt, **k):
            visto["prompt"] = prompt
            return types.SimpleNamespace(text="Tenes el Bloc de notas abierto.")

    ai = types.SimpleNamespace(_orchestrator=_Orq())
    salida = ver("que ventana tengo?", ai)
    assert "Bloc de notas abierto" in salida
    assert "Bloc de notas" in visto["prompt"]      # el contexto viajo
    assert "que ventana tengo?" in visto["prompt"]


def test_si_el_modelo_no_responde_devuelve_lo_que_ve(monkeypatch):
    _inyectar(monkeypatch, _PercepcionFalsa())

    class _OrqMudo:
        def infer(self, prompt, **k):
            return types.SimpleNamespace(text="")

    salida = ver("algo?", types.SimpleNamespace(_orchestrator=_OrqMudo()))
    assert "Bloc de notas" in salida              # al menos la percepcion


def test_nunca_lanza_si_la_percepcion_falla(monkeypatch):
    """Sin escritorio o sin mss, el comando explica en vez de reventar."""
    import cognia.vision.percepcion as vp

    def _boom(self, **k):
        raise RuntimeError("sin escritorio")
    monkeypatch.setattr(vp.ServicioPercepcion, "instantanea", _boom)

    p = percibir_pantalla()
    assert p["ok"] is False and "sin escritorio" in p["error"]
    salida = ver()
    assert "No pude mirar la pantalla" in salida
    assert "mss" in salida                        # dice QUE le falta


def test_el_cli_expone_el_comando():
    import pathlib
    cli = (pathlib.Path(__file__).resolve().parent.parent / "cognia" / "cli.py")
    src = cli.read_text(encoding="utf-8", errors="replace")
    assert 'raw == "/ver"' in src
    assert '"/ver":' in src                       # y esta en la ayuda
