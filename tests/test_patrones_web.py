"""
La biblioteca de patrones: guiarse de lo ya creado bonito y funcional.

Idea del dueno (2026-07-20): reusar tecnicas de paginas que ya funcionan, sin
copiarlas enteras. Los fragmentos salen de la pagina de referencia que paso
la sonda y el critico; el selector elige cuales ensenar segun la idea.
"""

from cognia.program_creator.patrones import DIR_PATRONES, elegir_patrones


def test_dashboard_recibe_los_tres_en_orden_visual():
    """Tiles arriba, grafico al medio, tabla abajo: el orden de la pagina."""
    r = elegir_patrones(
        "pagina web que simule un dashboard de inversiones con grafico "
        "animado y cotizaciones", max_n=3)
    assert [n for n, _ in r] == ["tiles_kpi", "grafico_svg", "tabla_estados"]


def test_una_idea_sin_relacion_no_recibe_ruido():
    """Meter patrones de dashboard en un reloj seria contaminar el prompt."""
    assert elegir_patrones("un reloj analogico animado", 3) == []


def test_respeta_max_n():
    r = elegir_patrones("dashboard con grafico y tabla", max_n=1)
    assert len(r) == 1


def test_el_contenido_es_el_fragmento_real():
    r = elegir_patrones("una grafica de lineas", 2)
    assert len(r) == 1
    nombre, codigo = r[0]
    assert nombre == "grafico_svg"
    # La proteccion anti-NaN es el motivo de ser del fragmento: si alguien la
    # quita del patron, este test lo delata.
    assert "y1 - y0 < 1" in codigo


def test_los_ficheros_de_patrones_existen():
    """El mapa no puede apuntar a ficheros que no estan en el repo."""
    for fichero in ("tiles_kpi.html", "grafico_svg.html", "tabla_estados.html"):
        assert (DIR_PATRONES / fichero).is_file(), f"falta {fichero}"


def test_nunca_lanza_con_entrada_rara():
    assert elegir_patrones("", 3) == []
    assert elegir_patrones(None if False else "x" * 10_000, 3) is not None
