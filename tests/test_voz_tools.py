# -*- coding: utf-8 -*-
"""Tests de las tools de VOZ (ola 1, agente V) — CPU puro, todo mockeado.

POR QUE estos casos y no otros: cubren las cinco trampas pre-registradas
del plan — flag apagado (bug A5: sin mensaje DESHABILITADA el researcher
sintetiza duplicados), parseo con '|' embebido en el texto (que va ULTIMO),
backend ausente con motivo legible, el gate del summoner llamado incluso
cuando el backend revienta (fuga de reserva de VRAM), y el contrato JSON
de stdout contaminado (que en la practica es EL modo de fallo de los
subprocess con vendors ruidosos).
"""
from __future__ import annotations

import hashlib
import sys
import types
from pathlib import Path

import pytest


# ── helpers ──────────────────────────────────────────────────────────────

def _registrar():
    """Registra las tools con un decorador falso y devuelve el registry."""
    from cognia.agent import voz_tools
    reg = {}

    def tool(name, doc, danger=False, desc="", params=None):
        def deco(fn):
            reg[name] = {"fn": fn, "doc": doc}
            return fn
        return deco

    voz_tools.register(tool)
    return reg


class FakeVoz:
    """Doble de tts.Voz que anota la ultima llamada, sin piper ni audio."""
    ultimo = None

    def __init__(self, *a, **k):
        pass

    def guardar_wav(self, texto, ruta):
        FakeVoz.ultimo = ("guardar", texto, str(ruta))
        return str(ruta)

    def decir(self, texto, bloquear=False):
        FakeVoz.ultimo = ("decir", texto, bloquear)
        return True

    def callar(self, timeout=2.0):
        pass


class FakeTranscriptor:
    """Doble de stt.Transcriptor; anota idioma y si se descargo."""
    instancias = []

    def __init__(self, *a, **k):
        self.idioma = k.get("idioma", "es")
        self.descargado = False
        self.texto = "prueba de sintesis"
        FakeTranscriptor.instancias.append(self)

    def __call__(self, ruta):
        return self.texto

    def descargar(self):
        self.descargado = True


@pytest.fixture()
def voz_tools_mod(monkeypatch, tmp_path):
    """Modulo con workspace redirigido a tmp y deps 'instaladas'."""
    from cognia.agent import voz_tools
    monkeypatch.setattr(voz_tools, "_salida_voz",
                        lambda nombre: tmp_path / nombre)
    monkeypatch.setattr(voz_tools, "_hay_modulo", lambda n: True)
    FakeVoz.ultimo = None
    FakeTranscriptor.instancias = []
    return voz_tools


def _gate_falso(monkeypatch, ok=True, motivo=""):
    """Inyecta un _backend_gate espia en sys.modules y devuelve las llamadas."""
    llamadas = []
    fake = types.ModuleType("cognia.agent._backend_gate")

    def pedir_backend(rol, mib):
        llamadas.append(("pedir", rol, mib))
        return (ok, "", motivo)

    def soltar_backend(rol):
        llamadas.append(("soltar", rol))

    fake.pedir_backend = pedir_backend
    fake.soltar_backend = soltar_backend
    monkeypatch.setitem(sys.modules, "cognia.agent._backend_gate", fake)
    return llamadas


# ── 1. flag apagado -> DESHABILITADA (mecanismo _OPTIN_PREFIJOS) ─────────

def test_flag_apagado_da_deshabilitada(monkeypatch):
    """Con COGNIA_VOZ_TOOLS apagado, run_tool responde DESHABILITADA con el
    flag exacto — no 'no existe' (que dispara record_wanted_tool, bug A5).
    Hasta que el integrador de ola 2 cablee tools.py, el prefijo se inyecta
    aqui: este test protege el MECANISMO del que voz depende."""
    from cognia.agent import tools
    monkeypatch.delenv("COGNIA_VOZ_TOOLS", raising=False)
    if not any(p == "voz_" for p, _ in tools._OPTIN_PREFIJOS):
        monkeypatch.setattr(
            tools, "_OPTIN_PREFIJOS",
            tools._OPTIN_PREFIJOS + (("voz_", "COGNIA_VOZ_TOOLS"),))
    sin_voz = {k: v for k, v in tools.TOOLS.items()
               if not k.startswith("voz_")}
    monkeypatch.setattr(tools, "TOOLS", sin_voz)
    out = tools.run_tool("voz_decir", "hola", {})
    assert "DESHABILITADA" in out
    assert "COGNIA_VOZ_TOOLS=1" in out


# ── 2. registro ──────────────────────────────────────────────────────────

def test_registro_nombres_y_docs():
    reg = _registrar()
    assert set(reg) == {"voz_decir", "voz_escuchar", "voz_clonar"}
    assert "guardar=" in reg["voz_decir"]["doc"]
    assert "Piper" in reg["voz_decir"]["doc"]
    assert "faster-whisper" in reg["voz_escuchar"]["doc"]
    assert "OpenVoice" in reg["voz_clonar"]["doc"]


# ── 3. voz_decir: parseo (opciones primero, texto ULTIMO) ────────────────

def test_voz_decir_guardar_con_pipes_en_texto(voz_tools_mod, monkeypatch,
                                              tmp_path):
    monkeypatch.setattr("cognia.voz.tts.Voz", FakeVoz)
    reg = _registrar()
    out = reg["voz_decir"]["fn"]("guardar=out.wav | hola | mundo", {})
    assert out.startswith("RESULTADO voz_decir OK:")
    accion, texto, ruta = FakeVoz.ultimo
    assert accion == "guardar"
    assert texto == "hola | mundo"          # el pipe del TEXTO sobrevive
    assert ruta == str(tmp_path / "out.wav")


def test_voz_decir_sin_guardar_texto_entero(voz_tools_mod, monkeypatch):
    monkeypatch.setattr("cognia.voz.tts.Voz", FakeVoz)
    reg = _registrar()
    out = reg["voz_decir"]["fn"]("hola | tal cual", {})
    assert "OK: dicho" in out
    accion, texto, bloquear = FakeVoz.ultimo
    assert accion == "decir"
    assert texto == "hola | tal cual"       # sin guardar= NADA se recorta
    assert bloquear is True                 # fin determinista del paso


def test_voz_decir_errores_de_formato(voz_tools_mod):
    reg = _registrar()
    assert "ERROR" in reg["voz_decir"]["fn"]("", {})
    out = reg["voz_decir"]["fn"]("guardar=solo.wav", {})
    assert "ERROR" in out and "falta el texto" in out


def test_voz_decir_sin_piper_sugiere_extra(voz_tools_mod, monkeypatch):
    monkeypatch.setattr(voz_tools_mod, "_hay_modulo", lambda n: False)
    reg = _registrar()
    out = reg["voz_decir"]["fn"]("hola", {})
    assert "ERROR" in out and "cognia-ai[voz]" in out


# ── 3b. voz_escuchar ─────────────────────────────────────────────────────

def test_voz_escuchar_ok_idioma_y_descarga(voz_tools_mod, monkeypatch,
                                           tmp_path):
    monkeypatch.setattr("cognia.voz.stt.Transcriptor", FakeTranscriptor)
    wav = tmp_path / "audio.wav"
    wav.write_bytes(b"RIFF")
    reg = _registrar()
    out = reg["voz_escuchar"]["fn"](f"{wav} | idioma=en", {})
    assert out == "RESULTADO voz_escuchar OK: prueba de sintesis"
    t = FakeTranscriptor.instancias[-1]
    assert t.idioma == "en"
    assert t.descargado is True             # VRAM/RAM soltada en finally


def test_voz_escuchar_ruta_inexistente(voz_tools_mod):
    reg = _registrar()
    out = reg["voz_escuchar"]["fn"]("no_existe.wav", {})
    assert "ERROR" in out and "no existe" in out


def test_voz_escuchar_vacia_es_error_legible(voz_tools_mod, monkeypatch,
                                             tmp_path):
    monkeypatch.setattr("cognia.voz.stt.Transcriptor", FakeTranscriptor)
    wav = tmp_path / "silencio.wav"
    wav.write_bytes(b"RIFF")
    reg = _registrar()

    def _vacio(self, ruta):
        return ""
    monkeypatch.setattr(FakeTranscriptor, "__call__", _vacio)
    out = reg["voz_escuchar"]["fn"](str(wav), {})
    assert "ERROR" in out and "vacia" in out
    assert FakeTranscriptor.instancias[-1].descargado is True


def test_voz_escuchar_opcion_invalida(voz_tools_mod, tmp_path):
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF")
    reg = _registrar()
    out = reg["voz_escuchar"]["fn"](f"{wav} | device=cuda", {})
    assert "ERROR" in out and "idioma=es" in out    # device NO se expone


# ── 4. voz_clonar: backend ausente -> motivo en el ERROR ─────────────────

def test_voz_clonar_backend_ausente_motivo_visible(voz_tools_mod, monkeypatch,
                                                   tmp_path):
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"RIFF")
    monkeypatch.setattr("cognia.voz.clonar.clonar_disponible",
                        lambda: (False, "faltan pesos EQIS-77"))
    reg = _registrar()
    out = reg["voz_clonar"]["fn"](f"{ref} | hola", {})
    assert "ERROR" in out and "faltan pesos EQIS-77" in out


def test_voz_clonar_formato_y_referencia(voz_tools_mod, tmp_path):
    reg = _registrar()
    out = reg["voz_clonar"]["fn"]("solo_una_parte.wav", {})
    assert "ERROR" in out and "formato" in out
    out = reg["voz_clonar"]["fn"](str(tmp_path / "nope.wav") + " | hola", {})
    assert "ERROR" in out and "no existe" in out


# ── 5. summoner/gate mockeado ────────────────────────────────────────────

def test_voz_clonar_gate_concedido_usa_cuda_y_texto_ultimo(
        voz_tools_mod, monkeypatch, tmp_path):
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"RIFF")
    llamadas = _gate_falso(monkeypatch, ok=True)
    monkeypatch.setattr("cognia.voz.clonar.clonar_disponible",
                        lambda: (True, ""))
    capturado = {}

    def _clonar(referencia, texto, salida, *, device, timeout):
        capturado.update(referencia=referencia, texto=texto,
                         salida=salida, device=device)
        return salida
    monkeypatch.setattr("cognia.voz.clonar.clonar_voz", _clonar)
    reg = _registrar()
    out = reg["voz_clonar"]["fn"](f"{ref} | hola | con | pipes", {})
    assert out.startswith("RESULTADO voz_clonar OK:")
    assert capturado["texto"] == "hola | con | pipes"   # texto ULTIMO, entero
    assert capturado["device"] == "cuda"
    huella = hashlib.md5(
        f"{ref}|hola | con | pipes".encode("utf-8")).hexdigest()[:8]
    assert capturado["salida"].endswith(f"clon_{huella}.wav")  # md5, no hash()
    assert ("pedir", "voces", 3000) in llamadas
    assert ("soltar", "voces") in llamadas


def test_voz_clonar_gate_llamado_incluso_con_excepcion(
        voz_tools_mod, monkeypatch, tmp_path):
    """Si el backend revienta, la reserva de VRAM se suelta IGUAL (finally)."""
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"RIFF")
    llamadas = _gate_falso(monkeypatch, ok=True)
    monkeypatch.setattr("cognia.voz.clonar.clonar_disponible",
                        lambda: (True, ""))

    def _boom(*a, **k):
        raise RuntimeError("boom del backend")
    monkeypatch.setattr("cognia.voz.clonar.clonar_voz", _boom)
    reg = _registrar()
    out = reg["voz_clonar"]["fn"](f"{ref} | hola", {})
    assert "ERROR" in out and "boom del backend" in out
    assert ("pedir", "voces", 3000) in llamadas
    assert ("soltar", "voces") in llamadas


def test_voz_clonar_gate_niega_degrada_a_cpu_visible(
        voz_tools_mod, monkeypatch, tmp_path):
    """Sin VRAM no es ERROR: CPU funcional, nota VISIBLE, sin soltar (nada
    fue concedido)."""
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"RIFF")
    llamadas = _gate_falso(monkeypatch, ok=False,
                           motivo="VRAM libre 100 MiB < 3000 MiB")
    monkeypatch.setattr("cognia.voz.clonar.clonar_disponible",
                        lambda: (True, ""))
    capturado = {}

    def _clonar(referencia, texto, salida, *, device, timeout):
        capturado["device"] = device
        return salida
    monkeypatch.setattr("cognia.voz.clonar.clonar_voz", _clonar)
    reg = _registrar()
    out = reg["voz_clonar"]["fn"](f"{ref} | hola", {})
    assert out.startswith("RESULTADO voz_clonar OK:")
    assert "(CPU: VRAM libre 100 MiB" in out
    assert capturado["device"] == "cpu"
    assert ("pedir", "voces", 3000) in llamadas
    assert ("soltar", "voces") not in llamadas


def test_voz_clonar_sin_gate_sigue_en_cpu_avisando(
        voz_tools_mod, monkeypatch, tmp_path, capsys):
    """_backend_gate ausente (olas en paralelo): CPU + aviso, jamas silencio."""
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"RIFF")
    monkeypatch.setattr(voz_tools_mod, "_gate", lambda: None)
    monkeypatch.setattr("cognia.voz.clonar.clonar_disponible",
                        lambda: (True, ""))
    monkeypatch.setattr("cognia.voz.clonar.clonar_voz",
                        lambda *a, **k: a[2])
    reg = _registrar()
    out = reg["voz_clonar"]["fn"](f"{ref} | hola", {})
    assert out.startswith("RESULTADO voz_clonar OK:")
    assert "sin _backend_gate" in out
    assert "_backend_gate no disponible" in capsys.readouterr().err
