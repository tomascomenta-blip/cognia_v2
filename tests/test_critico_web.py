"""
El critico profesional: un rol SEPARADO del creador que opina el trabajo.

Motivo (el dueno, 2026-07-20): "si alguien que no es artista opina sobre su
propio trabajo dira 'esta buenisimo'; tiene que criticar un profesional".
Medido: el autoevaluador daba 7.6 a una pagina cuyo grafico era una caja
blanca vacia; el critico (UIGEN como experto) le dio 4.5.
"""

from unittest.mock import patch

from cognia.program_creator.critico import _parsear, criticar_web


# ── El parser ──────────────────────────────────────────────────────────────

def test_parsea_formato_exacto():
    r = _parsear("NOTA: 4.5\nVEREDICTO: flojo\nDEFECTOS:\n- sin ejes\n- sin color")
    assert r["nota"] == 4.5
    assert r["veredicto"] == "flojo"
    assert r["defectos"] == ["sin ejes", "sin color"]


def test_tolera_ingles_y_coma_decimal():
    r = _parsear("NOTE: 7,5\nVERDICT: decent\nDEFECTS:\n- none")
    assert r["nota"] == 7.5
    assert r["defectos"] == []


def test_ninguno_es_lista_vacia():
    assert _parsear("NOTA: 9.0\nVEREDICTO: ok\nDEFECTOS:\n- ninguno")["defectos"] == []


def test_nota_se_recorta_al_rango():
    assert _parsear("NOTA: 15\nVEREDICTO: x\nDEFECTOS:\n- ninguno")["nota"] == 10.0


def test_bloque_think_se_ignora():
    """Los modelos con razonamiento (UIGEN-X) anteponen <think>...</think>.
    La NOTA dentro del razonamiento NO es el veredicto."""
    r = _parsear("<think>quiza NOTA: 9? no, es floja...</think>\n"
                 "NOTA: 3.0\nVEREDICTO: floja\nDEFECTOS:\n- vacia")
    assert r["nota"] == 3.0


def test_basura_devuelve_none():
    assert _parsear("no pienso puntuar esto") is None


# ── criticar_web ───────────────────────────────────────────────────────────

def test_sin_backend_devuelve_none():
    with patch("cognia.program_creator.critico.disponible", return_value=False):
        assert criticar_web("idea", "<html></html>", {}) is None


def test_camino_residente_marca_el_critico():
    with patch("cognia.program_creator.critico.disponible", return_value=True), \
         patch("cognia.program_creator.critico.generar",
               return_value="NOTA: 6.0\nVEREDICTO: pasable\nDEFECTOS:\n- ninguno"):
        r = criticar_web("idea", "<html></html>", {"se_mueve": True})
    assert r["critico"] == "residente"
    assert r["nota"] == 6.0


def test_el_html_se_trunca_tambien_en_el_camino_residente():
    """Regresion: la v1 solo truncaba en la rama del experto; el camino normal
    metia el HTML entero (40KB revientan el contexto de 8k)."""
    capturado = {}

    def _generar(prompt, **kw):
        capturado["prompt"] = prompt
        return "NOTA: 5.0\nVEREDICTO: x\nDEFECTOS:\n- ninguno"

    with patch("cognia.program_creator.critico.disponible", return_value=True), \
         patch("cognia.program_creator.critico.generar", side_effect=_generar):
        criticar_web("idea", "x" * 50_000, {})

    assert len(capturado["prompt"]) < 10_000


def test_la_url_del_experto_se_lee_al_llamar_no_al_importar(monkeypatch):
    """Regresion: la v1 leia COGNIA_CRITICO_URL al importar el modulo, asi que
    exportarla a mitad de sesion se ignoraba en silencio."""
    llamadas = []

    def _post_falso(url, prompt):
        llamadas.append(url)
        return "NOTA: 4.0\nVEREDICTO: duro\nDEFECTOS:\n- denso no es"

    monkeypatch.setenv("COGNIA_CRITICO_URL", "http://127.0.0.1:9999")
    with patch("cognia.program_creator.critico._preguntar_experto",
               side_effect=_post_falso):
        r = criticar_web("idea", "<html></html>", {})

    assert llamadas == ["http://127.0.0.1:9999"]
    assert r["critico"] == "experto"


def test_experto_caido_cae_al_residente(monkeypatch):
    monkeypatch.setenv("COGNIA_CRITICO_URL", "http://127.0.0.1:9999")
    with patch("cognia.program_creator.critico._preguntar_experto",
               return_value=None), \
         patch("cognia.program_creator.critico.disponible", return_value=True), \
         patch("cognia.program_creator.critico.generar",
               return_value="NOTA: 6.5\nVEREDICTO: ok\nDEFECTOS:\n- ninguno"):
        r = criticar_web("idea", "<html></html>", {})
    assert r["critico"] == "residente"
