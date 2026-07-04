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


# ── TAREA 2: record_skill_use + decay ───────────────────────────────────
# Sidecar JSON por directorio (<dir>/.skill_usage.json), NUNCA el
# frontmatter del .md. find_skill penaliza (excluye) una skill con historial
# consistentemente malo (>=3 fallos, 0 exitos).

def test_record_skill_use_persiste_en_sidecar_no_en_el_md(tmp_path):
    md = tmp_path / "mi-skill.md"
    md.write_text(SKILL_FLAT, encoding="utf-8")
    skills = {"mi-skill": SK.SkillSpec("mi-skill", "d", "b", str(md), "cognia")}

    SK.record_skill_use("mi-skill", True, skills=skills)
    SK.record_skill_use("mi-skill", True, skills=skills)
    SK.record_skill_use("mi-skill", False, skills=skills)

    # el .md del usuario no se toca
    assert md.read_text(encoding="utf-8") == SKILL_FLAT
    # el sidecar SI persiste los conteos
    sidecar = tmp_path / ".skill_usage.json"
    assert sidecar.exists()
    import json
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    assert data["mi-skill"] == {"uses_ok": 2, "uses_fail": 1}
    # escritura atomica: no quedan temporales colgados
    assert not list(tmp_path.glob(".skill_usage.json.tmp-*"))


def test_record_skill_use_skill_inexistente_no_hace_nada(tmp_path):
    SK.record_skill_use("no-existe", True, skills={})
    assert not (tmp_path / ".skill_usage.json").exists()


def test_find_skill_penaliza_skill_con_mal_historial(tmp_path):
    request = "necesito ayuda con configuracion de docker y contenedores en produccion"
    mal_md = tmp_path / "mal-historial.md"
    mal_md.write_text("x", encoding="utf-8")
    ok_md = tmp_path / "confiable.md"
    ok_md.write_text("x", encoding="utf-8")

    skills = {
        "mal-historial": SK.SkillSpec(
            "mal-historial",
            "Ayuda con configuracion de docker y contenedores en produccion",
            "body", str(mal_md), "cognia"),
        "confiable": SK.SkillSpec(
            "confiable", "Ayuda con el manejo de docker", "body", str(ok_md), "cognia"),
    }

    # sin historial: gana la de mayor solapamiento lexico (mal-historial)
    m0 = SK.find_skill(request, skills)
    assert m0.name == "mal-historial"

    # 3 fallos y 0 exitos -> se penaliza y deja de ganar
    for _ in range(3):
        SK.record_skill_use("mal-historial", False, skills=skills)
    m1 = SK.find_skill(request, skills)
    assert m1 is not None and m1.name == "confiable"


def test_find_skill_no_penaliza_si_tiene_al_menos_un_exito(tmp_path):
    request = "necesito ayuda con configuracion de docker y contenedores en produccion"
    md = tmp_path / "con-exitos.md"
    md.write_text("x", encoding="utf-8")
    skills = {
        "con-exitos": SK.SkillSpec(
            "con-exitos",
            "Ayuda con configuracion de docker y contenedores en produccion",
            "body", str(md), "cognia"),
    }
    for _ in range(3):
        SK.record_skill_use("con-exitos", False, skills=skills)
    SK.record_skill_use("con-exitos", True, skills=skills)  # 1 exito rompe el streak
    m = SK.find_skill(request, skills)
    assert m is not None and m.name == "con-exitos"


# ── TAREA 3a: fallback semantico en find_skill ──────────────────────────
# El fallback usa cognia.vectors.text_to_vector/cosine_similarity tal cual
# (cero dependencias nuevas). Se mockean esas 2 funciones para fijar la
# LOGICA de umbral/orden de forma determinista (el fallback de n-gramas de
# vectors.py es ruidoso para texto corto -- ver SEMANTIC_MATCH_THRESHOLD en
# skills.py -- asi que el test no depende de sus valores exactos).

def _mock_vectors(monkeypatch, table: dict):
    import cognia.vectors as V

    def fake_text_to_vector(text, dim=None):
        return table.get(text, [0.0, 0.0])

    def fake_cosine(a, b):
        return sum(x * y for x, y in zip(a, b))

    monkeypatch.setattr(V, "text_to_vector", fake_text_to_vector)
    monkeypatch.setattr(V, "cosine_similarity", fake_cosine)


def test_find_skill_fallback_semantico_para_pedido_parafraseado(monkeypatch):
    skills = {
        "escribir-tests": SK.SkillSpec(
            "escribir-tests", "genera casos de prueba automaticos para una funcion",
            "body", "x", "cognia"),
        "documentar": SK.SkillSpec(
            "documentar", "explica o documenta codigo", "body", "x", "cognia"),
    }
    # el pedido NO comparte ningun token lexico con ninguna de las 2 skills
    assert SK.find_skill("pedido parafraseado", skills) is None  # sin mock: nada

    _mock_vectors(monkeypatch, {
        "pedido parafraseado": [1.0, 0.0],
        "escribir-tests genera casos de prueba automaticos para una funcion": [0.9, 0.1],
        "documentar explica o documenta codigo": [0.0, 1.0],
    })
    m = SK.find_skill("pedido parafraseado", skills)
    assert m and m.name == "escribir-tests"


def test_find_skill_fallback_semantico_no_matchea_no_relacionado(monkeypatch):
    skills = {
        "escribir-tests": SK.SkillSpec(
            "escribir-tests", "genera casos de prueba automaticos para una funcion",
            "body", "x", "cognia"),
    }
    _mock_vectors(monkeypatch, {
        "escribir-tests genera casos de prueba automaticos para una funcion": [0.9, 0.1],
        # "algo sin relacion" no esta en la tabla -> vector [0,0] -> sim 0.0
    })
    assert SK.find_skill("algo sin relacion ni pizca de esto", skills) is None


def test_find_skill_lexico_gana_primero_sin_llamar_al_semantico(monkeypatch):
    import cognia.vectors as V

    def _boom(*a, **k):
        raise AssertionError("no deberia llamarse: el lexico ya encontro match")

    monkeypatch.setattr(V, "text_to_vector", _boom)
    skills = {
        "revisar-codigo": SK.SkillSpec(
            "revisar-codigo", "Revisa codigo en busca de bugs y riesgos", "body", "x", "cognia"),
    }
    m = SK.find_skill("revisa este codigo buscando bugs", skills)
    assert m and m.name == "revisar-codigo"


# ── TAREA 3b: dedupe semantico en persist_skill ─────────────────────────
# Segundo filtro (ademas del difflib sobre el NOMBRE existente): similitud
# coseno sobre descripcion+cuerpo, umbral alto (SEMANTIC_DUP_THRESHOLD=0.90)
# para rechazar solo duplicados casi textuales, con nombre distinto.

def _isolate_skill_dir(monkeypatch, tmp_path):
    cs = tmp_path / "cs"
    monkeypatch.setattr(SK, "AUTO_SKILL_DIR", cs)
    monkeypatch.setattr(SK, "SKILL_DIRS", [cs])
    return cs


def test_persist_skill_rechaza_duplicado_semantico_con_nombre_distinto(monkeypatch, tmp_path):
    _isolate_skill_dir(monkeypatch, tmp_path)
    desc = "Repara un bug reportado por los tests y deja todo verde"
    body_orig = ("Paso 1. Leer el archivo objetivo. Paso 2. Ejecutar pytest sobre "
                "el modulo. Paso 3. Si falla, corregir el bug e imprimir el traceback.")
    body_casi_igual = ("Paso 1. Leer el archivo objetivo. Paso 2. Ejecutar pytest sobre "
                       "el modulo. Paso 3. Si falla, arreglar el bug e imprimir el traceback.")

    r1 = SK.persist_skill("reparar-bug", desc, body_orig, "tests verdes (5 passed)")
    assert r1["ok"], r1

    # nombre TOTALMENTE distinto (no dispara el gate de difflib sobre nombre)
    r2 = SK.persist_skill("arreglar-fallo", desc, body_casi_igual, "tests verdes (5 passed)")
    assert not r2["ok"]
    assert "duplicada" in r2["reason"]


def test_persist_skill_no_rechaza_skills_genuinamente_distintas(monkeypatch, tmp_path):
    _isolate_skill_dir(monkeypatch, tmp_path)
    r1 = SK.persist_skill(
        "reparar-bug", "Repara un bug reportado por los tests y deja todo verde",
        "Paso 1. Leer el archivo objetivo. Paso 2. Ejecutar pytest sobre el modulo. "
        "Paso 3. Si falla, corregir el bug e imprimir el traceback.",
        "tests verdes (5 passed)")
    assert r1["ok"], r1

    r2 = SK.persist_skill(
        "exportar-tabla-csv", "Exporta filas de la tabla usuarios de la base de datos a CSV",
        "Paso 1. Abrir la base de datos. Paso 2. Contar filas por tabla. "
        "Paso 3. Exportar un resumen a CSV.",
        "tests verdes (5 passed)")
    assert r2["ok"], r2
    assert (tmp_path / "cs" / "exportar-tabla-csv.md").exists()
