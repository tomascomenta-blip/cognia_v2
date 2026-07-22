# -*- coding: utf-8 -*-
"""Tests del repo-map (PageRank personalizado sobre el grafo de código).

Regla del repo: un test que falle sin el fix y pase con él. Aquí se verifica el
contrato del selector de contexto: (1) los módulos núcleo (muy importados)
rankean por encima de los aislados; (2) la personalización sube lo mencionado;
(3) la salida lista símbolos y uso; (4) el presupuesto de chars corta; (5) la
caché por firma no reparsea."""
from cognia.knowledge import repo_map as rm


def _mk(tmp_path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "core.py").write_text(
        "def nucleo():\n    return 1\n\n\nclass Motor:\n    def run(self):\n        return 2\n",
        encoding="utf-8")
    (pkg / "a.py").write_text(
        "from pkg.core import nucleo\n\n\ndef alpha():\n    return nucleo()\n",
        encoding="utf-8")
    (pkg / "b.py").write_text(
        "from pkg.core import nucleo, Motor\n\n\ndef beta():\n    return nucleo()\n",
        encoding="utf-8")
    (pkg / "lonely.py").write_text(
        "def zeta_unico():\n    return 42\n",
        encoding="utf-8")
    return tmp_path


def test_core_ranks_above_lonely(tmp_path):
    _mk(tmp_path)
    rm._CACHE.clear()
    res = rm.repo_map(raiz=tmp_path, paquetes=("pkg",))
    ranks = res["ranks"]
    assert ranks["pkg.core"] > ranks["pkg.lonely"]
    assert "pkg.core" in res["modulos"]
    assert res["modulos"].index("pkg.core") < res["modulos"].index("pkg.lonely")


def test_personalization_surfaces_mentioned(tmp_path):
    _mk(tmp_path)
    rm._CACHE.clear()
    base = rm.repo_map(raiz=tmp_path, paquetes=("pkg",))
    sesgado = rm.repo_map(mentioned="arregla zeta_unico", raiz=tmp_path,
                          paquetes=("pkg",))
    # El sesgo hacia 'zeta_unico' sube el rank de su módulo (lonely) respecto al
    # ranking estructural puro.
    assert sesgado["ranks"]["pkg.lonely"] > base["ranks"]["pkg.lonely"]
    assert "pkg.lonely" in sesgado["modulos"]


def test_symbols_and_usage_in_text(tmp_path):
    _mk(tmp_path)
    rm._CACHE.clear()
    res = rm.repo_map(raiz=tmp_path, paquetes=("pkg",))
    assert "nucleo" in res["texto"]
    assert "Motor" in res["texto"]
    # core lo importan a.py y b.py -> usado_por=2
    assert "usado_por=2" in res["texto"]


def test_char_budget_truncates(tmp_path):
    _mk(tmp_path)
    rm._CACHE.clear()
    res = rm.repo_map(raiz=tmp_path, paquetes=("pkg",), max_chars=30)
    assert len(res["modulos"]) < res["n_modulos"]
    assert len(res["modulos"]) >= 1


def test_cache_reuse_same_signature(tmp_path):
    _mk(tmp_path)
    rm._CACHE.clear()
    rm.repo_map(raiz=tmp_path, paquetes=("pkg",))
    claves = set(rm._CACHE.keys())
    assert len(claves) >= 1
    # Segunda llamada con el mismo árbol -> misma firma -> no crea entrada nueva.
    rm.repo_map(mentioned="nucleo", raiz=tmp_path, paquetes=("pkg",))
    assert set(rm._CACHE.keys()) == claves


def test_empty_when_no_packages(tmp_path):
    (tmp_path / "vacio").mkdir()
    rm._CACHE.clear()
    res = rm.repo_map(raiz=tmp_path, paquetes=("noexiste",))
    assert res["texto"] == ""
    assert res["modulos"] == []
