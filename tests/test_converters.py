# -*- coding: utf-8 -*-
"""Tests del conversor universal de documentos (cognia/converters.py)."""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from cognia.converters import (CONVERTIBLES, convertir_a_texto, html_a_texto)


def test_html_extrae_texto_y_quita_script_style():
    html = ("<html><head><style>.x{color:red}</style>"
            "<script>alert(1)</script></head><body>"
            "<h1>Titulo</h1><p>Primer parrafo.</p>"
            "<p>Segundo &amp; cierre.</p></body></html>")
    txt = html_a_texto(html)
    assert "Titulo" in txt and "Primer parrafo." in txt
    assert "Segundo & cierre." in txt
    assert "alert" not in txt and "color:red" not in txt


def test_html_por_extension(tmp_path):
    p = tmp_path / "a.html"
    p.write_text("<body><p>hola mundo</p></body>", encoding="utf-8")
    assert "hola mundo" in convertir_a_texto(p)


def test_csv_a_tabla_legible(tmp_path):
    p = tmp_path / "d.csv"
    p.write_text("nombre,edad\nana,30\nluis,25\n", encoding="utf-8")
    txt = convertir_a_texto(p)
    assert "nombre | edad" in txt and "ana | 30" in txt


def test_tsv(tmp_path):
    p = tmp_path / "d.tsv"
    p.write_text("a\tb\n1\t2\n", encoding="utf-8")
    txt = convertir_a_texto(p)
    assert "a | b" in txt and "1 | 2" in txt


def test_json_pretty(tmp_path):
    p = tmp_path / "d.json"
    p.write_text('{"b":2,"a":1}', encoding="utf-8")
    txt = convertir_a_texto(p)
    assert '"b": 2' in txt and "\n" in txt          # pretty-printed


def test_texto_plano_passthrough(tmp_path):
    p = tmp_path / "d.md"
    p.write_text("# hola\n\ncontenido", encoding="utf-8")
    assert convertir_a_texto(p) == "# hola\n\ncontenido"


def test_docx_sin_dep_da_mensaje_accionable(tmp_path, monkeypatch):
    p = tmp_path / "d.docx"
    p.write_bytes(b"PK\x03\x04 fake")
    import builtins
    real_import = builtins.__import__

    def sin_docx(name, *a, **k):
        if name == "docx":
            raise ImportError("no docx")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", sin_docx)
    with pytest.raises(RuntimeError, match="python-docx"):
        convertir_a_texto(p)


def test_convertibles_incluye_formatos_clave():
    assert {".pdf", ".html", ".csv", ".docx", ".xlsx"} <= CONVERTIBLES


def test_ingest_usa_el_conversor(tmp_path):
    """_read_raw de ingest ahora rutea por el conversor: un HTML se
    ingiere como texto limpio, no como tags crudos."""
    from cognia.ingest import _read_raw
    p = tmp_path / "pagina.html"
    p.write_text("<body><h1>Doc</h1><p>cuerpo real</p>"
                 "<script>x=1</script></body>", encoding="utf-8")
    txt = _read_raw(p)
    assert "cuerpo real" in txt and "<script>" not in txt and "x=1" not in txt
