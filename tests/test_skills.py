"""
Tests for Claude-skill compatibility (cognia/agent/skills.py).

Pins frontmatter parsing, discovery of both flat <name>.md and <name>/SKILL.md,
description-based matching, and that the bundled skills ship and load.
"""

import pytest

from cognia.agent import skills as SK


SKILL_FLAT = """---
name: mi-skill
description: Hace una cosa util cuando el usuario pide revisar seguridad del codigo
---
# instrucciones
Paso 1. Paso 2.
"""

SKILL_DIR = """---
name: ignorado-usa-dir
description: skill en formato directorio SKILL.md
---
Cuerpo de la skill de directorio.
"""


def test_parse_frontmatter_and_body():
    fm, body = SK._parse(SKILL_FLAT)
    assert fm["name"] == "mi-skill"
    assert "revisar seguridad" in fm["description"]
    assert body.startswith("# instrucciones")


def test_load_skills_finds_flat_and_dir(tmp_path):
    (tmp_path / "mi-skill.md").write_text(SKILL_FLAT, encoding="utf-8")
    d = tmp_path / "otra"
    d.mkdir()
    (d / "SKILL.md").write_text(SKILL_DIR, encoding="utf-8")

    skills = SK.load_skills(extra_dirs=[str(tmp_path)])
    assert "mi-skill" in skills
    # dir form uses the directory name when frontmatter name is generic SKILL,
    # but here frontmatter has a name, so it wins; the dir is still discovered.
    assert "ignorado-usa-dir" in skills
    assert skills["mi-skill"].body.startswith("# instrucciones")


def test_find_skill_matches_by_description():
    skills = {
        "revisar-codigo": SK.SkillSpec(
            "revisar-codigo", "Revisa codigo en busca de bugs y riesgos", "body", "x", "cognia"),
        "documentar": SK.SkillSpec(
            "documentar", "Explica o documenta codigo", "body", "x", "cognia"),
    }
    m = SK.find_skill("revisa este codigo buscando bugs", skills)
    assert m and m.name == "revisar-codigo"


def test_find_skill_none_below_threshold():
    skills = {"x": SK.SkillSpec("x", "algo totalmente distinto", "b", "s", "cognia")}
    assert SK.find_skill("hola que tal", skills) is None


def test_skill_guidance_includes_name_and_body():
    s = SK.SkillSpec("depurar", "depura errores", "Paso 1: reproduci.", "src", "cognia")
    g = SK.skill_guidance(s)
    assert "depurar" in g and "Paso 1" in g


def test_bundled_skills_ship_and_load():
    skills = SK.load_skills()
    for name in ("revisar-codigo", "escribir-tests", "depurar", "documentar", "commit-git"):
        assert name in skills, f"falta skill bundled: {name}"
        assert skills[name].description  # has a description
