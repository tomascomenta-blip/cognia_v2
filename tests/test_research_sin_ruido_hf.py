"""
Regresion: HuggingFace ensuciaba las investigaciones sobre herramientas.

HuggingFace es un hub de MODELOS. Preguntarle por agentes, servidores MCP o
skills casa por palabras sueltas. Medido el 2026-07-20 sobre las 5
investigaciones que corrio Cognia esa noche, el ruido era casi total:

  "skills de agentes"  -> lm-ner-linkedin-skills-recognition
                          job-skills_unsloth-tinyllama-bnb-4bit
                          (modelos de detectar COMPETENCIAS LABORALES: otro
                          significado de "skills")
  "MCP sin registro"   -> kyutai/pocket-tts-without-voice-cloning
                          (text-to-speech, caso con "without")
  "agentes CLI"        -> coding-gen/my_awesome_opus_books_model
                          (un artefacto de tutorial, 1 descarga)

Y no era solo tiempo perdido: el resumidor solo mira los 12 primeros
hallazgos, asi que cada uno de esos desplazaba a un repo de GitHub que si
respondia la pregunta.
"""

import pytest

from cognia.research_engine.query_planner import SENAL_HERRAMIENTAS
from cognia.research_engine.web_research import _busca_herramientas


class TestDeteccion:

    @pytest.mark.parametrize("textos", [
        ["awesome coding agents", "cli agent"],
        ["free MCP servers"],
        ["skills de agentes autonomos"],
        ["terminal coding assistant"],
        ["open source cli tool"],
        ["plugin para el editor"],
    ])
    def test_preguntas_de_herramientas(self, textos):
        assert _busca_herramientas(textos) is True

    @pytest.mark.parametrize("textos", [
        ["small model maximum context"],
        ["quantization benchmark evaluation"],
        ["transformer attention memory"],
        ["dataset de entrenamiento"],
    ])
    def test_preguntas_de_modelos_siguen_usando_hf(self, textos):
        """El salto es solo para herramientas: HF es justo lo que hace falta
        cuando la pregunta va de modelos."""
        assert _busca_herramientas(textos) is False

    def test_no_se_confunde_con_puntuacion(self):
        """
        La deteccion mira los terminos ya traducidos que produce el
        planificador, que es lo que recibe en el flujo real: la pregunta en
        espanol va tambien, pero quien decide son las queries en ingles.
        """
        assert _busca_herramientas(["awesome agent, cli tools."]) is True

    def test_lista_vacia_no_dispara(self):
        assert _busca_herramientas([]) is False


class TestUsaElMismoVocabularioQueElPlanificador:
    """
    Si la senal se duplicara en dos sitios, acabarian divergiendo. La deteccion
    reutiliza SENAL_HERRAMIENTAS, que es lo que el planificador ya usa para
    elegir entre facetas de catalogo y facetas de ML.
    """

    @pytest.mark.parametrize("palabra", ["agent", "cli", "mcp", "server", "skills"])
    def test_las_senales_clave_estan(self, palabra):
        assert palabra in SENAL_HERRAMIENTAS

    def test_cualquier_senal_dispara_la_deteccion(self):
        for palabra in SENAL_HERRAMIENTAS:
            assert _busca_herramientas([f"busco un {palabra} bueno"]) is True


def test_hf_se_desactiva_en_una_investigacion_de_herramientas(monkeypatch):
    """
    Comprobacion end-to-end sin salir a la red: si la pregunta es de
    herramientas, el scraper de HuggingFace no llega a instanciarse.
    """
    import cognia.research_engine.web_research as WR

    llamado = []

    class HFEspia:
        def __init__(self, *a, **k):
            llamado.append(1)

        def search_models(self, q):
            return []

    monkeypatch.setattr(WR, "HFScraper", HFEspia)
    monkeypatch.setattr(WR, "planificar_busquedas",
                        lambda *a, **k: ["awesome coding agents"])
    monkeypatch.setattr(WR, "GitHubScraper", lambda *a, **k: type(
        "G", (), {"search_repos": lambda self, q: []})())
    monkeypatch.setattr(WR, "ArxivScraper", lambda *a, **k: type(
        "A", (), {"search_papers": lambda self, q: []})())
    monkeypatch.setattr(WR, "generar", lambda *a, **k: "")

    WR.investigar("agentes de coding por linea de comandos",
                  usar_arxiv=False, usar_llm=False, con_contra=False)

    assert llamado == [], "no deberia haber consultado HuggingFace"


class TestLosModelosMandanSobreLasHerramientas:
    """
    Refinamiento medido el 2026-07-20, rehaciendo la pregunta original de la
    noche: "mejor MODELO open source para webs bonitas en GPU de 16GB" derivo
    queries con "generators" y "tools", se salto HuggingFace, y con ello justo
    el sitio donde vive la respuesta (GLM, Qwen, Gemma estan en HF, no en
    GitHub). Si la pregunta nombra un modelo, se mira HF aunque haya palabras
    de herramientas alrededor.
    """

    def test_una_pregunta_de_modelos_no_salta_hf(self):
        assert _busca_herramientas(
            ["mejor modelo open source para webs", "HTML CSS generator tools"]) is False

    @pytest.mark.parametrize("senal", ["modelo", "model", "llm", "gguf",
                                       "vram", "quantization"])
    def test_cualquier_senal_de_modelo_gana(self, senal):
        assert _busca_herramientas([f"{senal} con cli tools y agents"]) is False

    def test_sin_senal_de_modelo_sigue_saltando(self):
        """El filtro no se desactiva: solo cede ante una pregunta de modelos."""
        assert _busca_herramientas(["awesome cli agents", "mcp server"]) is True
