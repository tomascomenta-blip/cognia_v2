"""
Contexto del proyecto: que Cognia lea las reglas del repo donde trabaja.

Dos arreglos del 2026-07-20, ambos salidos de probar la funcion de verdad:

  1. AGENTS.md estaba el ULTIMO de la lista de candidatos, detras incluso de
     setup.cfg — cuando es justamente el fichero cuyo proposito es decirle a un
     agente como comportarse en ese proyecto. Si algo se recorta, no puede ser
     lo primero en caerse. La convencion salio de la investigacion de Cognia
     (`FerroxLabs/agents-md`, que la usa para forzar bucles de verificacion).

  2. En Windows el sistema de ficheros no distingue mayusculas, asi que
     "AGENTS.md" y "agents.md" son el MISMO fichero: se leia dos veces y el
     contexto del proyecto salia duplicado entero. Con n_ctx=8192 eso es
     espacio que se le quita al trabajo.
"""

import pytest

from cognia.language_engine import _build_project_context


def _secciones(ctx):
    return [l for l in ctx.splitlines() if l.startswith("--- ")]


class TestPrioridad:

    def test_agents_md_va_antes_que_el_readme(self, tmp_path):
        (tmp_path / "AGENTS.md").write_text("reglas para agentes", encoding="utf-8")
        (tmp_path / "README.md").write_text("descripcion", encoding="utf-8")

        secciones = _secciones(_build_project_context(str(tmp_path)))
        assert secciones[0] == "--- AGENTS.md ---"

    def test_agents_md_va_antes_que_setup_cfg(self, tmp_path):
        """Antes estaba detras: un fichero de empaquetado ganaba a las reglas."""
        (tmp_path / "setup.cfg").write_text("[metadata]", encoding="utf-8")
        (tmp_path / "AGENTS.md").write_text("reglas", encoding="utf-8")

        secciones = _secciones(_build_project_context(str(tmp_path)))
        assert secciones.index("--- AGENTS.md ---") < secciones.index("--- setup.cfg ---")

    def test_las_reglas_estan_de_verdad_en_el_texto(self, tmp_path):
        (tmp_path / "AGENTS.md").write_text(
            "Siempre correr los tests antes de cerrar.", encoding="utf-8")
        assert "correr los tests" in _build_project_context(str(tmp_path))


class TestSinDuplicados:

    def test_no_lee_el_mismo_fichero_dos_veces(self, tmp_path):
        """
        En un sistema case-insensitive, AGENTS.md casa tambien con agents.md.
        Antes eso duplicaba la seccion entera.
        """
        (tmp_path / "AGENTS.md").write_text("reglas del repo", encoding="utf-8")
        ctx = _build_project_context(str(tmp_path))

        assert ctx.count("reglas del repo") == 1
        secciones = _secciones(ctx)
        assert len(secciones) == len(set(secciones))

    def test_varios_ficheros_distintos_si_salen_todos(self, tmp_path):
        (tmp_path / "AGENTS.md").write_text("aaa", encoding="utf-8")
        (tmp_path / "README.md").write_text("bbb", encoding="utf-8")
        (tmp_path / "pyproject.toml").write_text("ccc", encoding="utf-8")

        assert len(_secciones(_build_project_context(str(tmp_path)))) == 3


class TestRobustez:

    def test_directorio_sin_nada_devuelve_vacio(self, tmp_path):
        assert _build_project_context(str(tmp_path)) == ""

    def test_recorta_ficheros_enormes(self, tmp_path):
        (tmp_path / "README.md").write_text("x" * 50_000, encoding="utf-8")
        ctx = _build_project_context(str(tmp_path), max_chars_per_file=500)
        assert len(ctx) < 1000
