# -*- coding: utf-8 -*-
"""Tests del puente F4 (asset_bridge): partes deterministas, sin GPU.

La generación real de sprites (cognia.assets) y el E2E con LLM se verifican en GPU
fuera de la suite. Aquí: codificación data URI, inyección de ASSETS+cableado en el
HTML, y construcción del prompt. Imports de cognia.assets perezosos -> importa en CPU."""
import base64
import importlib
import json

ab = importlib.import_module("cognia.program_creator.asset_bridge")


def test_asset_a_datauri(tmp_path):
    p = tmp_path / "x.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    uri = ab.asset_a_datauri(p)
    assert uri.startswith("data:image/png;base64,")
    b64 = uri.split(",", 1)[1]
    assert base64.b64decode(b64) == b"\x89PNG\r\n\x1a\nfake"


def test_inyectar_assets_head_y_body():
    html = "<!DOCTYPE html><html><head><title>t</title></head><body><img data-asset=\"hero\"></body></html>"
    out = ab.inyectar_assets(html, {"hero": "data:image/png;base64,AAA"})
    # ASSETS global inyectado dentro del head
    assert "window.ASSETS=" in out
    assert '"hero"' in out or "'hero'" in out
    # el ASSETS va tras <head>, antes de </head>
    assert out.index("window.ASSETS=") < out.index("</head>")
    # el cableado va antes de </body>
    assert "querySelectorAll('[data-asset]')" in out
    assert out.index("querySelectorAll('[data-asset]')") < out.index("</body>")


def test_inyectar_assets_json_valido():
    assets = {"a": "data:image/png;base64,ZZ", "b": "data:image/png;base64,YY"}
    out = ab.inyectar_assets("<html><head></head><body></body></html>", assets)
    # el objeto ASSETS embebido debe ser JSON parseable
    m = out.split("window.ASSETS=", 1)[1]
    payload = m.split(";</script>", 1)[0]
    assert json.loads(payload) == assets


def test_inyectar_sin_head_ni_body():
    out = ab.inyectar_assets("<div>hola</div>", {"x": "data:image/png;base64,Q"})
    assert "window.ASSETS=" in out              # sin head -> se antepone
    assert "querySelectorAll('[data-asset]')" in out   # sin body -> se agrega al final


def test_build_prompt_lista_sprites():
    specs = [{"name": "girasol", "prompt": "a sunflower", "desc": "un girasol"},
             {"name": "zombie", "prompt": "a zombie"}]
    p = ab.build_prompt_web_con_assets("jardin PvZ", specs)
    assert 'data-asset="girasol"' in p
    assert 'data-asset="zombie"' in p
    assert "un girasol" in p                    # usa desc cuando existe
    assert "a zombie" in p                      # cae al prompt cuando no hay desc
    assert "offline" in p.lower()               # mantiene la regla de autocontenido


def test_wiring_es_idempotente_en_forma():
    # el cableado no debe romper si ASSETS no existe (usa window.ASSITS||{})
    assert "window.ASSETS||{}" in ab._WIRING
