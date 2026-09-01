# -*- coding: utf-8 -*-
"""Arranque por hitos y extraccion de ruta de los args de escritura (2026-09-01)."""
from __future__ import annotations

from cognia.agent.loop import _ruta_escrita
from cognia.harness.contrato_tarea import Contrato


def test_arranque_solo_con_encargo_grande():
    corto = Contrato("Crea saluda.py que imprima hola y ejecutalo.")
    assert not corto.activo
    largo = Contrato("Haz una app con:\n1. Un formulario de alta con validacion real\n"
                     "2. Una lista de elementos con filtro por texto\n"
                     "3. Persistencia en localStorage entre recargas\n"
                     "4. Exportacion a JSON descargable\n")
    assert largo.activo
    texto = largo.arranque_para_modelo()
    assert "ESQUELETO MINIMO" in texto
    assert "apendar_archivo" in texto
    assert "4 requisitos" in texto


def test_ruta_escrita_entiende_json_y_legado():
    assert _ruta_escrita('{"ruta": "js/app.js", "contenido": "a | b"}') == "js/app.js"
    assert _ruta_escrita('{"path": "x.py", "content": "z"}') == "x.py"
    assert _ruta_escrita("index.html | <html>") == "index.html"
    assert _ruta_escrita('"con comillas.py" | x') == "con comillas.py"
    assert _ruta_escrita("") == ""
    assert _ruta_escrita(None) == ""
