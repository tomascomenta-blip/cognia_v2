# -*- coding: utf-8 -*-
"""La revision profunda CORRE el guion propio de la pagina (`<pagina>.guion.txt`,
2026-09-04): un assert que falla reprueba (fallo_duro='guion'), un guion que pasa
deja ok=True, y sin guion la fase queda en ok=None con el motivo. Playwright real."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from cognia.harness import revision_profunda as rp

pytestmark = pytest.mark.skipif(importlib.util.find_spec("playwright") is None, reason="sin Playwright")

PAGINA = """<!doctype html><html><head><title>Contador</title>
<style>body{font-family:sans-serif} button{padding:8px 16px} #n{font-size:2em}</style></head><body>
<h1>Contador de prueba</h1>
<p>Pulsa el boton para sumar uno.</p>
<button id="b">Sumar</button>
<span id="n">0</span>
<script>
let n = 0;
window.n = 0;
document.getElementById('b').onclick = () => {
  n++;
  window.n = n;
  document.getElementById('n').textContent = n;
};
</script>
</body></html>"""


def _art(tmp_path):
    p = tmp_path / "index.html"
    p.write_text(PAGINA, encoding="utf-8")
    return {"id": "index", "title": "index", "description": "", "directorio": str(tmp_path),
            "lenguaje": "html", "entrypoint": str(p), "archivos_py": []}


def test_ruta_guion_de():
    assert rp.ruta_guion_de("x/index.html").name == "index.html.guion.txt"


def test_sin_guion_no_reprueba(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIA_CONTRATO_WEB", "0")
    r = rp.fase_producto(_art(tmp_path), 60)
    g = r["fases"]["guion"]
    assert g["ok"] is None and "no existe" in g["detalle"]
    assert r["fallo_duro"] != "guion"


def test_guion_que_pasa_y_guion_que_falla(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIA_CONTRATO_WEB", "0")
    art = _art(tmp_path)
    guion = rp.ruta_guion_de(art["entrypoint"])
    guion.write_text("clic #b; clic #b; assert window.n == 2; assert texto contiene \"2\"; assert sin errores", encoding="utf-8")
    r = rp.fase_producto(art, 60)
    assert r["fases"]["guion"]["ok"] is True, r["fases"]["guion"]["detalle"]
    assert r["fases"]["guion"]["pasos"] == 5 and r["fallo_duro"] != "guion"
    # el guion que pasa se DICE en el detalle (no solo el contrato generico)
    if r["fallo_duro"] is None:
        assert "guion propio OK (5 pasos, index.html.guion.txt)" in r["detalle"], r["detalle"]
    # (la fase 'arranca' de autoprueba puede reprobar esta pagina estatica por sus
    # propias heuristicas -- "no se anima sola" --; eso no es de este test)
    guion.write_text("clic #b; assert window.n == 5", encoding="utf-8")
    r = rp.fase_producto(art, 60)
    g = r["fases"]["guion"]
    assert g["ok"] is False and r["ok"] is False
    assert r["fallo_duro"] in ("guion", "arranca", "sin_stubs")
    assert "window.n == 5" in " ".join(g["asserts_fallidos"])
    assert "GUION PROPIO FALLA" in g["detalle"]
