# -*- coding: utf-8 -*-
"""Tests de vlm_tools + describir_imagen (ola 1, CPU puro, sin GPU ni red).

Que cubren (cada uno falla sin su pieza):
- describir_imagen: POST mockeado, prompt default vs pregunta, system neutro,
  url override, imagen ilegible -> None (jamas lanza).
- _datauri_imagen: MIME por extension (png/jpg) y alias _datauri_png intacto
  (los llamadores viejos del arbitro y sus tests usan ese nombre).
- vlm_mirar: registro manual, parseo 'ruta | pregunta' con '|' embebido,
  ruta inexistente / extension mala -> ERROR legible (nunca excepcion),
  gate mockeado (sin VRAM -> motivo visible; ok -> respuesta; soltar en
  finally INCLUSO con excepcion del backend), fallback sin _backend_gate.
- flag apagado: la tool no corre sin COGNIA_VLM_TOOLS (mensaje DESHABILITADA
  cuando la integracion de ola 2 este cableada; tolerante mientras tanto).
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from cognia.program_creator import arbitro_visual as av
from cognia.agent import vlm_tools


# ── helpers ────────────────────────────────────────────────────────────────

def _png(tmp_path: Path, nombre: str = "img.png") -> Path:
    """PNG minimo en disco (cabecera valida; el contenido no se decodifica
    en estos tests porque el POST al VLM esta mockeado)."""
    p = tmp_path / nombre
    p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    return p


def _registrar():
    """Registra vlm_tools con un decorador de mentira y devuelve el registry."""
    tools = {}

    def tool(name, doc, danger=False, desc="", params=None):
        def deco(fn):
            tools[name] = {"fn": fn, "doc": doc}
            return fn
        return deco

    vlm_tools.register(tool)
    return tools


def _gate_falso(monkeypatch, *, ok=True, url="http://127.0.0.1:8081",
                motivo=""):
    """Inyecta un cognia.agent._backend_gate falso en sys.modules y devuelve
    la lista espia de llamadas [(fn, rol, mib), ...]."""
    llamadas = []
    mod = types.ModuleType("cognia.agent._backend_gate")

    def pedir_backend(rol, mib):
        llamadas.append(("pedir", rol, mib))
        return ok, (url if ok else ""), motivo

    def soltar_backend(rol):
        llamadas.append(("soltar", rol, None))

    mod.pedir_backend = pedir_backend
    mod.soltar_backend = soltar_backend
    monkeypatch.setitem(sys.modules, "cognia.agent._backend_gate", mod)
    return llamadas


# ── describir_imagen (arbitro_visual) ──────────────────────────────────────

def test_describir_imagen_prompt_default(tmp_path, monkeypatch):
    visto = {}

    def fake_post(url, prompt, imagenes, **kw):
        visto.update(url=url, prompt=prompt, imagenes=imagenes, **kw)
        return "un gato naranja sobre una mesa"

    monkeypatch.setattr(av, "_preguntar_vlm", fake_post)
    ruta = _png(tmp_path)
    out = av.describir_imagen(ruta)
    assert out == "un gato naranja sobre una mesa"
    # sin pregunta -> prompt default de descripcion
    assert "Describe la imagen" in visto["prompt"]
    # system NEUTRO, no el QA designer del arbitro (sesgaria la descripcion)
    assert visto["system"] != av._SYSTEM
    assert visto["max_tokens"] == 512 and visto["timeout"] == 180
    assert len(visto["imagenes"]) == 1
    assert visto["imagenes"][0].startswith("data:image/png;base64,")


def test_describir_imagen_pregunta_y_url_override(tmp_path, monkeypatch):
    visto = {}

    def fake_post(url, prompt, imagenes, **kw):
        visto.update(url=url, prompt=prompt)
        return "es un boton azul"

    monkeypatch.setattr(av, "_preguntar_vlm", fake_post)
    out = av.describir_imagen(_png(tmp_path), "que color tiene el boton?",
                              url="http://otra:9999")
    assert out == "es un boton azul"
    assert visto["prompt"] == "que color tiene el boton?"
    assert visto["url"] == "http://otra:9999"


def test_describir_imagen_ilegible_devuelve_none(tmp_path, monkeypatch):
    # jamas lanza: imagen inexistente -> None (el motivo ya quedo logueado)
    monkeypatch.setattr(av, "_preguntar_vlm",
                        lambda *a, **k: pytest.fail("no debia llegar al POST"))
    assert av.describir_imagen(tmp_path / "no_existe.png") is None


def test_datauri_imagen_mime_por_extension(tmp_path):
    png = _png(tmp_path, "a.png")
    jpg = tmp_path / "b.jpg"
    jpg.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 16)
    assert av._datauri_imagen(png).startswith("data:image/png;base64,")
    assert av._datauri_imagen(jpg).startswith("data:image/jpeg;base64,")
    assert av._datauri_imagen(tmp_path / "nada.png") is None
    # alias de compatibilidad: mismo resultado para un PNG
    assert av._datauri_png(png) == av._datauri_imagen(png)


# ── vlm_mirar: registro y parseo ───────────────────────────────────────────

def test_registro_manual_nombre_y_doc():
    tools = _registrar()
    assert set(tools) == {"vlm_mirar"}
    assert "vlm_mirar <ruta_imagen>" in tools["vlm_mirar"]["doc"]
    assert "pregunta" in tools["vlm_mirar"]["doc"]


def test_falta_ruta_y_ruta_inexistente(tmp_path):
    fn = _registrar()["vlm_mirar"]["fn"]
    assert "ERROR" in fn("", {}) and "falta la ruta" in fn("", {})
    out = fn(str(tmp_path / "nada.png"), {})
    assert out.startswith("RESULTADO vlm_mirar ERROR") and "no existe" in out


def test_extension_no_soportada(tmp_path):
    fn = _registrar()["vlm_mirar"]["fn"]
    raro = tmp_path / "cosa.gif"
    raro.write_bytes(b"GIF89a")
    out = fn(str(raro), {})
    assert "ERROR" in out and "no soportada" in out and ".png" in out


def test_parseo_pregunta_con_pipe_embebido(tmp_path, monkeypatch):
    """La pregunta va ULTIMA y puede contener '|': maxsplit=1 la preserva."""
    _gate_falso(monkeypatch, ok=True)
    visto = {}

    def fake_describir(ruta, pregunta, url=None, **kw):
        visto.update(ruta=ruta, pregunta=pregunta, url=url)
        return "respuesta"

    monkeypatch.setattr(av, "describir_imagen", fake_describir)
    ruta = _png(tmp_path)
    fn = _registrar()["vlm_mirar"]["fn"]
    out = fn(f"{ruta} | cual es mayor: a | b | c?", {})
    assert out == "RESULTADO vlm_mirar OK: respuesta"
    assert visto["pregunta"] == "cual es mayor: a | b | c?"
    assert visto["ruta"] == str(ruta)
    assert visto["url"] == "http://127.0.0.1:8081"


# ── vlm_mirar: gate del backend ────────────────────────────────────────────

def test_sin_vram_motivo_visible_y_no_suelta(tmp_path, monkeypatch):
    llamadas = _gate_falso(monkeypatch, ok=False,
                           motivo="VRAM insuficiente: 900 MiB libres")
    fn = _registrar()["vlm_mirar"]["fn"]
    out = fn(str(_png(tmp_path)), {})
    assert "ERROR" in out and "VRAM insuficiente" in out
    assert ("pedir", "vlm", 3300) in llamadas
    # no se concedio el backend: no hay reserva que soltar
    assert not any(c[0] == "soltar" for c in llamadas)


def test_ok_pide_rol_vlm_y_suelta_en_finally(tmp_path, monkeypatch):
    llamadas = _gate_falso(monkeypatch, ok=True)
    monkeypatch.setattr(av, "describir_imagen",
                        lambda *a, **k: "una pagina web con un header rojo")
    fn = _registrar()["vlm_mirar"]["fn"]
    out = fn(str(_png(tmp_path)), {})
    assert out == "RESULTADO vlm_mirar OK: una pagina web con un header rojo"
    assert llamadas == [("pedir", "vlm", 3300), ("soltar", "vlm", None)]


def test_suelta_incluso_si_el_backend_revienta(tmp_path, monkeypatch):
    llamadas = _gate_falso(monkeypatch, ok=True)

    def explota(*a, **k):
        raise RuntimeError("kaboom del VLM")

    monkeypatch.setattr(av, "describir_imagen", explota)
    fn = _registrar()["vlm_mirar"]["fn"]
    out = fn(str(_png(tmp_path)), {})
    assert "ERROR" in out and "kaboom" in out       # legible, no traceback
    assert ("soltar", "vlm", None) in llamadas      # finally SIEMPRE suelta


def test_vlm_no_responde_error_accionable(tmp_path, monkeypatch):
    llamadas = _gate_falso(monkeypatch, ok=True)
    monkeypatch.setattr(av, "describir_imagen", lambda *a, **k: None)
    fn = _registrar()["vlm_mirar"]["fn"]
    out = fn(str(_png(tmp_path)), {})
    assert "ERROR" in out and "no respondio" in out
    assert "cognia flota estado" in out             # sugerencia accionable
    assert ("soltar", "vlm", None) in llamadas


def test_fallback_sin_backend_gate(tmp_path, monkeypatch):
    """Sin _backend_gate (ImportError: la ola 1 corre en paralelo) cae al
    sondeo del arbitro y el motivo del health sigue siendo VISIBLE."""
    monkeypatch.setitem(sys.modules, "cognia.agent._backend_gate", None)
    monkeypatch.setattr(av, "vlm_disponible",
                        lambda url=None: (False, "sin VLM en :8081 (refused)"))
    fn = _registrar()["vlm_mirar"]["fn"]
    out = fn(str(_png(tmp_path)), {})
    assert "ERROR" in out and "sin VLM en :8081" in out


def test_fallback_sin_gate_ok_usa_url_vlm(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "cognia.agent._backend_gate", None)
    monkeypatch.setattr(av, "vlm_disponible", lambda url=None: (True, "ok"))
    monkeypatch.setattr(av, "url_vlm", lambda: "http://127.0.0.1:8081")
    visto = {}

    def fake_describir(ruta, pregunta, url=None, **kw):
        visto["url"] = url
        return "ok visto"

    monkeypatch.setattr(av, "describir_imagen", fake_describir)
    fn = _registrar()["vlm_mirar"]["fn"]
    assert "OK: ok visto" in fn(str(_png(tmp_path)), {})
    assert visto["url"] == "http://127.0.0.1:8081"


# ── flag apagado (gate de tools.py) ────────────────────────────────────────

def test_flag_apagado_no_ejecuta(monkeypatch):
    """Con COGNIA_VLM_TOOLS apagado la tool JAMAS corre via run_tool. Cuando
    la ola 2 cablee el prefijo vlm_ en _OPTIN_PREFIJOS el mensaje ademas dice
    como encenderla (asercion condicional: este test no depende de ola 2)."""
    monkeypatch.delenv("COGNIA_VLM_TOOLS", raising=False)
    from cognia.agent import tools as T
    import cognia.agent.background_research as br
    deseos = []
    monkeypatch.setattr(br, "record_wanted_tool",
                        lambda name, hint="": deseos.append(name))
    out = T.run_tool("vlm_mirar", "loquesea.png", {})
    assert out.startswith("ERROR")
    if T.flag_de_optin("vlm_mirar"):        # integracion ola 2 ya cableada
        assert "DESHABILITADA" in out and "COGNIA_VLM_TOOLS=1" in out
