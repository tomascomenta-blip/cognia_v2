# -*- coding: utf-8 -*-
"""Tests de repo_a_prompt (ingeniería inversa de repos, sin red y sin LLM).

Cubre el contrato anti-degradación-silenciosa: la especificación heurística
NUNCA es vacía, el modo degradado se detecta y avisa, el LLM solo puede tocar
la sección 'Prompt reconstruido', y los acentos sobreviven (regla anti-Latin-1
del repo). e2e local al final: la herramienta sobre el propio cognia_v2.
"""
import types
from pathlib import Path

import pytest

import cognia.knowledge.repo_map as rm
from cognia.knowledge import repo_reverse as rr


@pytest.fixture
def mini_repo(tmp_path):
    (tmp_path / "README.md").write_text(
        "# Mini\n\nAplicación de gestión de tareas con acentos: años, más.\n\n"
        "## Features\n\n- listar tareas\n- completar tareas\n",
        encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "mini"\ndescription = "gestor de tareas"\n'
        'dependencies = ["requests"]\n\n'
        '[project.scripts]\nmini = "pkg.cli:main"\n',
        encoding="utf-8")
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "core.py").write_text(
        "from pkg.util import ayuda\n\n\ndef listar():\n    return ayuda()\n\n\n"
        "def completar(t):\n    return t\n", encoding="utf-8")
    (pkg / "util.py").write_text(
        "def ayuda():\n    return []\n", encoding="utf-8")
    (pkg / "cli.py").write_text(
        "import requests\nfrom pkg.core import listar\n\n\n"
        "def main():\n    return listar()\n\n\n"
        'if __name__ == "__main__":\n    main()\n', encoding="utf-8")
    return tmp_path


def _limpiar_caches():
    rm._CACHE.clear()
    import cognia.knowledge.code_nav as cn
    cn._CACHE.clear()


def test_detectar_paquetes(mini_repo, tmp_path):
    assert rr.detectar_paquetes(mini_repo) == ("pkg",)
    vacio = tmp_path / "vacio"
    vacio.mkdir()
    assert rr.detectar_paquetes(vacio) == ()


@pytest.fixture
def repo_plano(tmp_path):
    """Repo SIN subdirs: los .py viven directo en la raíz (caso A13: un dir
    plano de 19 .py perdía todo el grafo AST)."""
    (tmp_path / "nucleo.py").write_text(
        "import util\n\n\ndef correr():\n    return util.ayuda()\n",
        encoding="utf-8")
    (tmp_path / "util.py").write_text(
        "def ayuda():\n    return []\n", encoding="utf-8")
    (tmp_path / "cli.py").write_text(
        "import requests\nfrom nucleo import correr\n\n\n"
        'if __name__ == "__main__":\n    correr()\n', encoding="utf-8")
    return tmp_path


def test_detectar_paquetes_dir_plano(repo_plano):
    paqs = rr.detectar_paquetes(repo_plano)
    assert paqs[0] == "."                              # la raíz como paquete
    assert set(paqs[1:]) == {"cli", "nucleo", "util"}  # stems para _imports_de


def test_analizar_repo_dir_plano_tiene_grafo(repo_plano):
    _limpiar_caches()
    a = rr.analizar_repo(repo_plano)
    # antes del fix: aviso "sin paquetes Python organizables: sin grafo AST"
    assert not any("sin grafo AST" in av for av in a["avisos"])
    assert a["mapa"] and set(a["mapa"]["modulos"]) == {"cli", "nucleo", "util"}
    assert any("cli" in e for e in a["entry_points"])  # guard main detectado
    # los imports internos planos NO se reportan como deps externas
    assert not any(d.startswith(("util", "nucleo")) for d in a["deps_externas"])
    assert any(d.startswith("requests") for d in a["deps_externas"])


def test_analizar_repo_completo(mini_repo):
    _limpiar_caches()
    a = rr.analizar_repo(mini_repo)
    assert any("pkg.cli" in e for e in a["entry_points"])          # guard main
    assert any("mini = pkg.cli:main" in e for e in a["entry_points"])
    assert any(d.startswith("requests") for d in a["deps_externas"])
    assert a["mapa"]["modulos"]
    # pkg.util lo importa core -> aparece con usado_por>=1 en el texto
    assert "pkg.util" in a["mapa"]["texto"]
    assert "usado_por=1" in a["mapa"]["texto"]


def test_spec_heuristica_nunca_vacia_y_utf8(mini_repo):
    _limpiar_caches()
    a = rr.analizar_repo(mini_repo)
    a["origen_desc"] = "ruta local (test)"
    spec = rr.spec_heuristica(a)
    assert "## Objetivo" in spec
    assert "## Puntos de entrada" in spec
    assert "## Límites" in spec
    assert "gestión" in spec          # el acento del README sobrevive
    assert "SIN LLM" in spec


def test_repo_sin_nada(tmp_path):
    _limpiar_caches()
    (tmp_path / "script.py").write_text("print(1)\n", encoding="utf-8")
    res = rr.repo_a_prompt(str(tmp_path), infer_fn=None)
    assert res["texto"]
    assert "inventario" in res["texto"]


def test_sin_llm(mini_repo):
    _limpiar_caches()
    res = rr.repo_a_prompt(str(mini_repo), infer_fn=None)
    assert res["modo"] == "heuristico"
    assert res["texto"]


def test_llm_vacio_y_degradado(mini_repo):
    _limpiar_caches()
    esqueleto = rr.repo_a_prompt(str(mini_repo), infer_fn=None)["texto"]
    for fn in (lambda s, u: "", lambda s, u: "[DEGRADADO] backend caido"):
        res = rr.repo_a_prompt(str(mini_repo), infer_fn=fn)
        assert res["modo"] == "heuristico_degradado"
        assert "backend" in res["aviso"]
        assert res["texto"]
        # mismo esqueleto determinista (solo cambia la marca de modo/aviso)
        assert "## Arquitectura observada" in res["texto"]
        assert "[plantilla heurística — sin LLM]" in res["texto"]
    # y una excepcion del backend tampoco rompe
    def explota(s, u):
        raise RuntimeError("sin GPU")
    res = rr.repo_a_prompt(str(mini_repo), infer_fn=explota)
    assert res["modo"] == "heuristico_degradado"
    assert esqueleto  # el esqueleto base existe y no es vacio


def test_llm_ok(mini_repo):
    _limpiar_caches()
    fake = "Quiero una app que gestione tareas con listado y completado."
    res = rr.repo_a_prompt(str(mini_repo), infer_fn=lambda s, u: fake)
    assert res["modo"] == "llm"
    cuerpo = res["texto"]
    idx_prompt = cuerpo.index("## Prompt reconstruido")
    idx_lim = cuerpo.index("## Límites")
    assert fake in cuerpo[idx_prompt:idx_lim]      # el fake va en SU seccion
    assert "## Arquitectura observada" in cuerpo   # y el resto sigue
    assert "pkg.core" in cuerpo                    # ...determinista del AST


def test_entrada_invalida(tmp_path):
    with pytest.raises(ValueError):
        rr.repo_a_prompt("C:/no/existe/xyz_repo_falso", infer_fn=None)
    with pytest.raises(ValueError):
        rr.repo_a_prompt("https://gitlab.com/o/r", infer_fn=None)


def test_entrada_archivo_es_valueerror(tmp_path):
    # regresión: un ARCHIVO existente lanzaba NotADirectoryError (WinError 267
    # críptico) que escapaba al except del wrapper; debe ser ValueError claro
    f = tmp_path / "pyproject.toml"
    f.write_text("[project]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="archivo"):
        rr.repo_a_prompt(str(f), infer_fn=None)


def test_objetivo_salta_lineas_solo_url(tmp_path):
    # regresión: README que abre con una URL de asset (gitreverse) contaminaba
    # el Objetivo y el prompt heurístico con esa URL
    (tmp_path / "README.md").write_text(
        "# X\n\nhttps://github.com/user-attachments/assets/abc-123\n\n"
        "Herramienta que convierte repos en prompts.\n", encoding="utf-8")
    obj = rr._objetivo_de(rr.analizar_repo(tmp_path))
    assert "user-attachments" not in obj
    assert "Herramienta que convierte" in obj


def test_parsear_url_github():
    assert rr._parsear_entrada("https://github.com/o/r.git") == ("github", "o/r")
    assert rr._parsear_entrada("https://github.com/o/r") == ("github", "o/r")
    assert rr._parsear_entrada("o/r") == ("github", "o/r")


def test_wrapper_run_tool(mini_repo, monkeypatch):
    _limpiar_caches()
    import cognia.agents.workers.dev_tools as dev_tools
    from cognia.agent import repo_reverse_tool
    from cognia.agent import tools as T
    monkeypatch.setattr(dev_tools, "AGENT_WORKSPACE_ROOT", str(mini_repo))
    repo_reverse_tool.register(T.tool)   # registrar sin depender del env
    try:
        fake_orch = types.SimpleNamespace(
            infer=lambda user, **kw: types.SimpleNamespace(
                text="Quiero un gestor de tareas simple en Python."))
        ctx = {"ai": types.SimpleNamespace(_orchestrator=fake_orch),
               "working_memory": {}, "agent_state": {},
               "print_fn": lambda *a, **k: None}
        out = T.run_tool("repo_a_prompt", str(mini_repo), ctx)
        assert "RESULTADO repo_a_prompt" in out
        assert "modo=" in out
        # sin entrada -> error de uso, no excepcion
        assert "ERROR" in T.run_tool("repo_a_prompt", "", ctx)
        # un ARCHIVO como entrada -> ERROR legible, no WinError 267
        out = T.run_tool("repo_a_prompt", str(mini_repo / "pyproject.toml"),
                         ctx)
        assert "ERROR" in out and "archivo" in out
        # regresión '| salida': va por dev_tools.write_file -> backup .bak
        previo = mini_repo / "spec.md"
        previo.write_text("version vieja", encoding="utf-8")
        out = T.run_tool("repo_a_prompt", f"{mini_repo} | spec.md", ctx)
        assert "guardado en" in out
        assert previo.read_text(encoding="utf-8").startswith("# Especificación")
        assert (mini_repo / "spec.md.bak").read_text(
            encoding="utf-8") == "version vieja"
    finally:
        T.TOOLS.pop("repo_a_prompt", None)


def test_e2e_sobre_cognia_v2():
    _limpiar_caches()
    raiz = Path(__file__).resolve().parents[1]
    res = rr.repo_a_prompt(str(raiz), infer_fn=None)
    assert res["modo"] == "heuristico"
    assert res["analisis"]["mapa"]["n_modulos"] > 50
    cuerpo = res["texto"]
    idx_arq = cuerpo.index("## Arquitectura observada")
    idx_ep = cuerpo.index("## Puntos de entrada")
    assert "cognia" in cuerpo[idx_arq:idx_ep]
    assert res["analisis"]["entry_points"]        # __main__.py / console_script
    assert any("cognia" in e for e in res["analisis"]["entry_points"])
    assert len(cuerpo) > 1500


# ── Regresion 2026-08-01: el "Objetivo" agarraba el chrome del README ──
# Cazado corriendo repo_a_prompt sobre HKUDS/DeepTutor: la seccion Objetivo
# salio siendo la barra de navegacion y las notas de version, porque eran
# las primeras lineas que no empezaban por '#'.

def test_objetivo_ignora_navbar_badges_y_changelog(tmp_path):
    _limpiar_caches()
    (tmp_path / "README.md").write_text(
        "# MiProyecto\n\n"
        "[Features](#-key-features) · [Get Started](#-get-started) · "
        "[CLI](#-cli) · [Community](#-community)\n\n"
        "---\n\n"
        "> 🤝 **We welcome any kinds of contributing!** Vote on roadmap.\n\n"
        "**[2026.7.31]** [v1.5.7](https://x/releases/tag/v1.5.7) — cambios\n\n"
        "MiProyecto es un gestor de tareas con sincronización en la nube.\n",
        encoding="utf-8")
    a = rr.analizar_repo(tmp_path)
    obj = rr._objetivo_de(a)
    assert "gestor de tareas" in obj                 # la prosa real SI entra
    assert "Get Started" not in obj                  # navbar fuera
    assert "welcome any kinds" not in obj            # cita de anuncio fuera
    assert "v1.5.7" not in obj                       # changelog fuera


def test_es_chrome_readme_discrimina():
    assert rr._es_chrome_readme("[A](#a) · [B](#b) · [C](#c)")
    assert rr._es_chrome_readme("> nota de anuncio")
    assert rr._es_chrome_readme("---")
    assert rr._es_chrome_readme("**[2026.7.31]** v1.5.7 — release")
    # prosa legitima que MENCIONA un enlace no es chrome
    assert not rr._es_chrome_readme(
        "Una herramienta para analizar repos, ver la [guia](docs/guia.md) "
        "para empezar a usarla en tu proyecto.")
