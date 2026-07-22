# -*- coding: utf-8 -*-
"""Tests de la navegación de código (find-def / find-refs desde AST, sin BD)."""
from cognia.knowledge import code_nav as cn


def _mk(tmp_path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "core.py").write_text(
        "def nucleo():\n    return 1\n\n\nclass Motor:\n    pass\n",
        encoding="utf-8")
    (pkg / "a.py").write_text(
        "from pkg.core import nucleo\n\n\ndef alpha():\n    return nucleo()\n",
        encoding="utf-8")
    (pkg / "b.py").write_text(
        "from pkg.core import nucleo\n\n\ndef beta():\n    return nucleo() + 1\n",
        encoding="utf-8")
    return tmp_path


def test_vecindad_modulo(tmp_path):
    _mk(tmp_path)
    cn._CACHE.clear()
    v = cn.vecindad("pkg.core", raiz=tmp_path, paquetes=("pkg",))
    assert v["tipo"] == "modulo"
    assert "nucleo" in v["define"] and "Motor" in v["define"]
    assert set(v["importado_por"]) == {"pkg.a", "pkg.b"}


def test_vecindad_simbolo_def_y_refs(tmp_path):
    _mk(tmp_path)
    cn._CACHE.clear()
    v = cn.vecindad("nucleo", raiz=tmp_path, paquetes=("pkg",))
    assert v["tipo"] == "simbolo"
    assert v["definido_en"] == ["pkg.core"]
    # a.py y b.py referencian nucleo (import + llamada); no la cuenta su definidor
    assert set(v["referenciado_en"]) == {"pkg.a", "pkg.b"}
    assert v["n_referencias"] == 2
    assert v["encontrado"]


def test_simbolo_inexistente(tmp_path):
    _mk(tmp_path)
    cn._CACHE.clear()
    v = cn.vecindad("no_existe_xyz", raiz=tmp_path, paquetes=("pkg",))
    assert v["tipo"] == "simbolo"
    assert not v["encontrado"]
    assert "no encontrado" in cn.formatear(v)


def test_formatear_modulo(tmp_path):
    _mk(tmp_path)
    cn._CACHE.clear()
    txt = cn.formatear(cn.vecindad("pkg.core", raiz=tmp_path, paquetes=("pkg",)))
    assert "define:" in txt and "importado_por:" in txt


def test_cache_reuse(tmp_path):
    _mk(tmp_path)
    cn._CACHE.clear()
    cn.vecindad("nucleo", raiz=tmp_path, paquetes=("pkg",))
    claves = set(cn._CACHE.keys())
    cn.vecindad("pkg.core", raiz=tmp_path, paquetes=("pkg",))
    assert set(cn._CACHE.keys()) == claves
