"""
mockup.py — el cerebro imagina el producto (brief + prompt de imagen) y el
modelo de imagenes lo dibuja. Estos tests cubren el parseo y la degradacion
con gracia (sin LLM / sin backend de imagen); la GPU queda parcheada.
"""

from unittest.mock import patch

from cognia.program_creator import mockup as mk


# ── parseo de la vision ───────────────────────────────────────────────────────

def test_parsea_brief_e_imagen():
    r = mk._parsear_vision(
        "BRIEF: dashboard oscuro, KPIs arriba, grafico central\n"
        "IMAGEN: dark dashboard, three kpi cards, line chart, teal accents")
    assert "dashboard oscuro" in r["brief"]
    assert "teal accents" in r["prompt_imagen"]


def test_ignora_bloque_think():
    r = mk._parsear_vision(
        "<think>quiza claro? no, oscuro</think>\n"
        "BRIEF: fondo oscuro\nIMAGEN: dark ui")
    assert r["brief"] == "fondo oscuro"


def test_basura_devuelve_none():
    assert mk._parsear_vision("no tengo formato") is None


# ── imaginar_vision ───────────────────────────────────────────────────────────

def test_sin_llm_cae_a_la_idea_cruda():
    with patch.object(mk, "generar", return_value=None):
        r = mk.imaginar_vision("un juego de plataformas", llm=None)
    assert r["brief"] == "un juego de plataformas"
    assert r["prompt_imagen"] == "un juego de plataformas"


def test_usa_el_backend_inyectado_si_esta():
    def _llm(prompt, system, max_tokens, temperature):
        return "BRIEF: landing minimalista\nIMAGEN: minimal landing, big hero"

    r = mk.imaginar_vision("landing de una app", llm=_llm)
    assert r["brief"] == "landing minimalista"
    assert r["prompt_imagen"] == "minimal landing, big hero"


def test_rellena_imagen_vacia_con_el_brief():
    with patch.object(mk, "generar",
                      return_value="BRIEF: algo\nIMAGEN:"):
        r = mk.imaginar_vision("idea", llm=None)
    assert r["prompt_imagen"] == "algo"


# ── generar_mockup ────────────────────────────────────────────────────────────

def test_mockup_sin_backend_devuelve_none():
    with patch("cognia.assets.backend_disponible",
               return_value=(False, "sin CUDA")):
        assert mk.generar_mockup("dark dashboard") is None
