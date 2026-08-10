# -*- coding: utf-8 -*-
"""Tests de la tool musica_orquestar -- CPU puro, summoner y backend mockeados.

POR QUE estos casos: el esqueleto comun de las familias multimodales (plan
ola 1) exige probar registro, parseo k=v, degradacion con motivo legible,
y el contrato con _backend_gate (pedir con el rol/MiB correctos y soltar en
finally INCLUSO con excepcion del backend) sin GPU ni summoner real.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

import cognia.musica as musica_pkg
from cognia.agent import musica_tools


# ---------------------------------------------------------------- helpers

def _registrar():
    """Registra la tool con un decorador de mentira y devuelve {nombre: (doc, fn)}."""
    registro = {}

    def tool(nombre, doc, **kw):
        def deco(fn):
            registro[nombre] = (doc, fn)
            return fn
        return deco

    musica_tools.register(tool)
    return registro


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    """Workspace en tmp + backend disponible + gate espiado en sys.modules."""
    # _root_actual monkeypatcheado y NO la env var: tests viejos de la suite
    # (test_escalado_7b/q35, mesa_redonda) redirigen dev.AGENT_WORKSPACE_ROOT
    # sin restaurar, y esa redireccion le GANA a COGNIA_AGENT_WORKSPACE en
    # _root_actual (leak de orden cazado en la suite completa, ola 2). El
    # monkeypatch de la funcion es inmune al orden (patron de test_tresd_tools).
    monkeypatch.setattr("cognia.agents.workers.dev_tools._root_actual",
                        lambda: str(tmp_path / "ws"))
    monkeypatch.setattr(musica_pkg, "musica_disponible", lambda: (True, ""))

    llamadas = {"pedir": [], "soltar": []}
    gate = types.ModuleType("cognia.agent._backend_gate")

    def pedir_backend(rol, mib):
        llamadas["pedir"].append((rol, mib))
        return True, "", ""

    def soltar_backend(rol):
        llamadas["soltar"].append(rol)

    gate.pedir_backend = pedir_backend
    gate.soltar_backend = soltar_backend
    monkeypatch.setitem(sys.modules, "cognia.agent._backend_gate", gate)

    def _orquestar_falso(midi_cond, salida_dir, *, grupo=2, **kw):
        rutas = []
        for g in range(grupo):
            p = Path(salida_dir) / f"song_0_{g}.mid"
            p.write_bytes(b"MThd")
            rutas.append(str(p))
        return rutas

    monkeypatch.setattr(musica_pkg, "orquestar", _orquestar_falso)
    return {"llamadas": llamadas, "gate": gate, "tmp": tmp_path}


def _correr(args):
    registro = _registrar()
    _doc, fn = registro["musica_orquestar"]
    return fn(args, {})


# ----------------------------------------------------------------- registro

def test_registro_nombre_y_doc():
    registro = _registrar()
    assert "musica_orquestar" in registro
    doc, fn = registro["musica_orquestar"]
    # el doc es lo que ve el modelo: debe ensenar el formato k=v completo
    for pedazo in ("midi=", "grupo=", "wav=1", "SymphonyGen"):
        assert pedazo in doc
    assert callable(fn)


# ------------------------------------------------------------------- parseo

def test_parseo_parte_sin_kv(entorno):
    out = _correr("una sinfonia epica")
    assert out.startswith("RESULTADO musica_orquestar ERROR:")
    assert "formato invalido" in out


def test_parseo_clave_desconocida(entorno):
    out = _correr("midi=x.mid | tempo=120")
    assert "opcion desconocida 'tempo'" in out


def test_parseo_grupo_no_entero(entorno):
    out = _correr("grupo=muchas")
    assert "grupo debe ser un entero" in out


def test_parseo_midi_inexistente(entorno, tmp_path):
    out = _correr(f"midi={tmp_path / 'nada.mid'}")
    assert out.startswith("RESULTADO musica_orquestar ERROR: no existe el MIDI")
    # fallo ANTES de reservar VRAM
    assert entorno["llamadas"]["pedir"] == []


# -------------------------------------------------------------- degradacion

def test_backend_ausente_motivo_visible(entorno, monkeypatch):
    monkeypatch.setattr(musica_pkg, "musica_disponible",
                        lambda: (False, "falta el checkpoint X en Y"))
    out = _correr("")
    assert out == "RESULTADO musica_orquestar ERROR: falta el checkpoint X en Y"
    # sin backend no se pide VRAM
    assert entorno["llamadas"]["pedir"] == []


def test_gate_sin_vram(entorno):
    entorno["gate"].pedir_backend = lambda rol, mib: (
        False, "", "VRAM insuficiente: 900 MiB libres, necesito ~2500")
    out = _correr("")
    assert "VRAM insuficiente" in out
    # sin reserva concedida no hay nada que soltar
    assert entorno["llamadas"]["soltar"] == []


def test_sin_backend_gate_sigue_avisando(entorno, monkeypatch, capsys):
    # ola 1: _backend_gate (agente A3) puede no existir aun -> la tool sigue
    # pero AVISA por stderr (degradacion visible, jamas silenciosa).
    monkeypatch.setitem(sys.modules, "cognia.agent._backend_gate", None)
    out = _correr("")
    assert out.startswith("RESULTADO musica_orquestar OK:")
    assert "_backend_gate no disponible" in capsys.readouterr().err


# ------------------------------------------------------------- camino feliz

def test_camino_feliz_solo_midi(entorno):
    out = _correr("grupo=3")
    assert out.startswith("RESULTADO musica_orquestar OK: 3 MIDI en")
    assert "song_0_0.mid" in out and "song_0_2.mid" in out
    assert "WAV" not in out
    # contrato con el summoner: rol y MiB del registry congelado
    assert entorno["llamadas"]["pedir"] == [("musica", 2500)]
    assert entorno["llamadas"]["soltar"] == ["musica"]
    # los artefactos quedan bajo <workspace>/musica/orq_*
    assert "orq_" in out and str(Path("ws") / "musica") in out


def test_excepcion_del_backend_suelta_igual(entorno, monkeypatch):
    def _revienta(*a, **k):
        raise RuntimeError("musica: timeout tras 900s")

    monkeypatch.setattr(musica_pkg, "orquestar", _revienta)
    out = _correr("")
    assert out == "RESULTADO musica_orquestar ERROR: musica: timeout tras 900s"
    # soltar_backend corrio en el finally pese a la excepcion
    assert entorno["llamadas"]["soltar"] == ["musica"]


def test_wav_sin_fluidsynth_ok_parcial(entorno, monkeypatch):
    import cognia.musica.render as render_mod
    monkeypatch.setattr(render_mod, "fluidsynth_disponible",
                        lambda: (False, "fluidsynth no esta en el PATH"))
    out = _correr("wav=1")
    # OK parcial: los MIDI son el artefacto, el motivo queda a la vista
    assert out.startswith("RESULTADO musica_orquestar OK: 2 MIDI en")
    assert "sin WAV: fluidsynth no esta en el PATH" in out


def test_wav_con_fluidsynth(entorno, monkeypatch):
    import cognia.musica.render as render_mod
    monkeypatch.setattr(render_mod, "fluidsynth_disponible", lambda: (True, ""))
    rendereados = []

    def _midi_a_wav(m, *a, **k):
        rendereados.append(m)
        return str(Path(m).with_suffix(".wav"))

    monkeypatch.setattr(render_mod, "midi_a_wav", _midi_a_wav)
    out = _correr("wav=1 | grupo=2")
    assert "+ 2 WAV" in out
    assert len(rendereados) == 2


def test_wav_render_parcial_reporta_falla(entorno, monkeypatch):
    import cognia.musica.render as render_mod
    monkeypatch.setattr(render_mod, "fluidsynth_disponible", lambda: (True, ""))

    def _midi_a_wav(m, *a, **k):
        if m.endswith("song_0_1.mid"):
            raise RuntimeError("render: WAV vacio")
        return str(Path(m).with_suffix(".wav"))

    monkeypatch.setattr(render_mod, "midi_a_wav", _midi_a_wav)
    out = _correr("wav=1")
    assert out.startswith("RESULTADO musica_orquestar OK:")
    assert "+ 1 WAV" in out
    assert "render parcial" in out and "song_0_1.mid" in out
