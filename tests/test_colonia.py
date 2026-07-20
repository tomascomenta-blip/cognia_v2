"""
La colonia dentro de Cognia: expertos numpy + feromona.

La regla pre-registrada (planes/FLOTA_MICROEXPERTOS.md): un experto NUNCA
reemplaza a su heuristica en silencio — primero rastro, despues mando.
"""

import json

import pytest

from cognia.colonia import feromona, opinar
from cognia.colonia.experto_numpy import verificar_paridad


# ── Paridad torch-numpy: la guardia contra la reimplementacion desviada ────

@pytest.mark.parametrize("nombre", ["idea_router", "idioma"])
def test_paridad_torch_numpy(nombre):
    """El forward numpy debe reproducir los logits de torch a 1e-4. Si esto
    falla, alguien toco una capa y el experto opina distinto del que se
    entreno y paso su gate."""
    diff = verificar_paridad(nombre)
    assert diff < 1e-4


# ── Opinar ─────────────────────────────────────────────────────────────────

def test_opina_correcto_en_los_casos_de_su_gate():
    assert opinar("idea_router", "pagina web con un dashboard animado")[0] == "web"
    assert opinar("idea_router",
                  "modulo python que parsee HTML con urllib")[0] == "python_module"
    assert opinar("idioma", "por que no funciona la busqueda")[0] == "es"
    assert opinar("idioma", "why does the search not work")[0] == "en"


def test_experto_inexistente_no_lanza():
    assert opinar("no_existe", "lo que sea") == ("", 0.0)


# ── Feromona ───────────────────────────────────────────────────────────────

@pytest.fixture
def rastro_temporal(tmp_path, monkeypatch):
    monkeypatch.setattr(feromona, "RUTA_RASTRO", tmp_path / "feromona.json")


def test_sin_rastro_el_experto_no_manda(rastro_temporal):
    """El estado inicial: la heuristica manda. Es la regla del plan."""
    assert feromona.el_experto_manda("idea_router") is False
    w, n = feromona.peso("idea_router")
    assert n == 0 and w == 0.5


def test_el_rastro_se_refuerza_y_da_el_mando(rastro_temporal):
    for _ in range(feromona.MIN_EVIDENCIA):
        feromona.confirmar("t", acerto_experto=True)
    assert feromona.el_experto_manda("t") is True


def test_evidencia_insuficiente_no_da_mando_aunque_gane(rastro_temporal):
    """5 aciertos de 5 no bastan: sin MIN_EVIDENCIA es rastro, no camino."""
    for _ in range(5):
        feromona.confirmar("t", acerto_experto=True)
    w, n = feromona.peso("t")
    assert w > 0.7
    assert feromona.el_experto_manda("t") is False


def test_experto_que_pierde_no_manda(rastro_temporal):
    for _ in range(30):
        feromona.confirmar("t", acerto_experto=False)
    assert feromona.el_experto_manda("t") is False


def test_las_discrepancias_quedan_acotadas(rastro_temporal):
    for i in range(250):
        feromona.registrar_discrepancia("t", f"texto {i}", "a", "b")
    datos = json.loads(feromona.RUTA_RASTRO.read_text(encoding="utf-8"))
    assert len(datos["t"]["discrepancias"]) == 200


# ── La integracion: la heuristica sigue mandando ───────────────────────────

def test_es_idea_web_sigue_mandando_la_heuristica(rastro_temporal):
    """Con rastro vacio, _es_idea_web decide igual que antes de la colonia —
    los casos golden del detector no pueden cambiar por la segunda voz."""
    from cognia.program_creator.generator import _es_idea_web
    assert _es_idea_web("una pagina web con animaciones") is True
    assert _es_idea_web(
        "modulo Python para convertir HTML a texto plano, con unittest") is False
    assert _es_idea_web("gestor de tareas en terminal con SQLite") is False
