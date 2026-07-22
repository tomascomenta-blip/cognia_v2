# -*- coding: utf-8 -*-
"""Tests del generador de wiki de código (deepwiki-open nativo)."""
from cognia.knowledge import code_nav as cn
from cognia.knowledge import code_wiki as cw


def _mk(tmp_path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "core.py").write_text("def nucleo():\n    return 1\n", encoding="utf-8")
    (pkg / "a.py").write_text("from pkg.core import nucleo\n\ndef alpha():\n    return nucleo()\n",
                              encoding="utf-8")
    (pkg / "b.py").write_text("from pkg.core import nucleo\n\ndef beta():\n    return 2\n",
                              encoding="utf-8")
    return tmp_path


def test_pagina_modulo_contenido(tmp_path):
    _mk(tmp_path)
    cn._CACHE.clear()
    idx = cn._construir(tmp_path, ("pkg",))
    pag = cw.pagina_modulo("pkg.core", idx)
    assert "# `pkg.core`" in pag
    assert "`nucleo`" in pag
    assert "Importado por (2)" in pag
    assert "```mermaid" in pag


def test_mermaid_ids_seguros(tmp_path):
    _mk(tmp_path)
    cn._CACHE.clear()
    idx = cn._construir(tmp_path, ("pkg",))
    m = cw.mermaid_deps("pkg.core", idx)
    # sin puntos en los ids de nodo (romperían Mermaid)
    assert "n_pkg_core" in m
    assert "graph LR" in m


def test_generar_wiki_index_y_paginas(tmp_path):
    _mk(tmp_path)
    cn._CACHE.clear()
    w = cw.generar_wiki(raiz=tmp_path, paquetes=("pkg",))
    assert w["n_modulos"] >= 3
    assert "pkg.core" in w["paginas"]
    # core (2 importadores) va antes que a/b (0) en el índice
    assert w["index"].index("pkg.core") < w["index"].index("pkg.a")


def test_generar_wiki_escribe_a_disco(tmp_path):
    _mk(tmp_path)
    cn._CACHE.clear()
    dest = tmp_path / "wiki"
    cw.generar_wiki(raiz=tmp_path, paquetes=("pkg",), destino=str(dest))
    assert (dest / "index.md").exists()
    assert (dest / "pkg_core.md").exists()
    assert "nucleo" in (dest / "pkg_core.md").read_text(encoding="utf-8")
