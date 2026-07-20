"""
Skills que escribio Cognia a partir de su propia investigacion (2026-07-20).

Las cuatro salieron de lo que encontro investigando agentes de coding:
  investigar-tema        <- su research_engine y los agentes CLI
  ahorrar-contexto       <- headroomlabs-ai/headroom (comprimir antes del LLM)
  orientarse-en-un-repo  <- tirth8205/code-review-graph (mapa del codebase)
  insistir-hasta-cumplir <- snwfdhmp/awesome-ralph (bucle hasta la especificacion)

Lo que fijan estos tests es la parte que fallo al escribirlas y que solo se ve
probandolas: una skill cuya descripcion no lleva las palabras que usa el
usuario NO SE ACTIVA NUNCA, y entonces da igual lo bien escrito que este el
cuerpo. Medido: 2 de las 4 no saltaban, y 'insistir-hasta-cumplir' perdia
contra 'escribir-tests' porque la palabra "tests" dominaba.
"""

import re
from pathlib import Path

import pytest

from cognia.agent.skills import find_skill, load_skills
from cognia.agent.tools import TOOLS

SKILLS_DIR = Path(__file__).resolve().parent.parent / "cognia" / "skills"

NUEVAS = [
    "investigar-tema",
    "ahorrar-contexto",
    "orientarse-en-un-repo",
    "insistir-hasta-cumplir",
]


@pytest.fixture(scope="module")
def skills():
    return load_skills()


class TestCargan:

    @pytest.mark.parametrize("nombre", NUEVAS)
    def test_el_fichero_existe(self, nombre):
        assert (SKILLS_DIR / f"{nombre}.md").exists()

    @pytest.mark.parametrize("nombre", NUEVAS)
    def test_se_registra(self, nombre, skills):
        assert nombre in skills

    @pytest.mark.parametrize("nombre", NUEVAS)
    def test_tiene_pasos_y_reglas(self, nombre):
        texto = (SKILLS_DIR / f"{nombre}.md").read_text(encoding="utf-8")
        assert "## Como proceder" in texto
        assert "## Reglas" in texto
        assert re.search(r"^1\.", texto, re.MULTILINE), "faltan pasos numerados"


class TestSeActivan:
    """
    Una skill que no se activa es una skill que no existe. Cada frase de aqui
    es una que fallaba antes de reescribir las descripciones.
    """

    @pytest.mark.parametrize("frase,esperada", [
        ("no entiendo este repositorio nuevo, por donde empiezo", "orientarse-en-un-repo"),
        ("investiga a fondo que opciones hay antes de decidir",   "investigar-tema"),
        ("este log es larguisimo y no cabe en el contexto",       "ahorrar-contexto"),
        ("la salida ocupa demasiado, comprimela",                 "ahorrar-contexto"),
        ("no pares hasta que funcione",                           "insistir-hasta-cumplir"),
        ("reintenta hasta cumplir la especificacion",             "insistir-hasta-cumplir"),
    ])
    def test_la_frase_del_usuario_encuentra_su_skill(self, frase, esperada, skills):
        hallada = find_skill(frase, skills)
        assert hallada is not None, f"'{frase}' no activo ninguna skill"
        assert hallada.name == esperada


class TestNoInventanNada:

    @pytest.mark.parametrize("nombre", NUEVAS)
    def test_solo_cita_herramientas_que_existen(self, nombre):
        """
        Una skill que manda usar una herramienta inexistente lleva al agente a
        un callejon sin salida.
        """
        texto = (SKILLS_DIR / f"{nombre}.md").read_text(encoding="utf-8")
        # Solo se miran los verbos en backticks que parecen nombres de tool:
        # minusculas con guion bajo, sin punto (los con punto son modulos).
        candidatos = {c for c in re.findall(r"`([a-z][a-z_]+)`", texto)
                      if "." not in c}
        # Palabras del formato, no herramientas.
        candidatos -= {"name", "description", "markdown", "python", "main",
                       "app", "frontmatter"}

        inventadas = candidatos - set(TOOLS)
        assert not inventadas, f"{nombre} cita herramientas que no existen: {inventadas}"

    @pytest.mark.parametrize("nombre", NUEVAS)
    def test_los_comandos_que_cita_existen(self, nombre):
        """/mapa-codigo si existe; cognia.mapa_proyecto no es un comando."""
        texto = (SKILLS_DIR / f"{nombre}.md").read_text(encoding="utf-8")
        for cmd in re.findall(r"`(/[a-z-]+)`", texto):
            assert cmd in ("/mapa-codigo", "/imagenes", "/crear", "/investigar",
                           "/biblioteca", "/mapa"), f"comando desconocido: {cmd}"
