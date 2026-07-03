"""
Regresion del ORACULO del benchmark de diseño (cognia_v3/eval/bench_design.py).

El bench de diseño no tiene juez LLM: su unica fuente de verdad es el checker
DOM/CSS. Estos tests fijan la semantica del checker (fixtures GOOD/BAD +
casos positivos y negativos por tipo de assert) para que ningun cambio
posterior la mueva en silencio — si el oraculo cambia, los numeros del bench
dejan de ser comparables (P7 de 06_AGENTE_PLAN.md).
"""
from cognia_v3.eval.bench_design import (
    SPECS, check_page, full_asserts, run_selftest, validate_specs,
)


def test_selftest_completo():
    """Los 33 casos congelados del self-test (GOOD/BAD) pasan."""
    n_ok, n_total, fails = run_selftest()
    assert not fails, f"self-test roto: {fails}"
    assert n_ok == n_total


def test_specs_validas():
    """25 specs, ids unicos, tipos conocidos, >= 6 asserts cada una."""
    assert validate_specs() == []
    assert len(SPECS) == 25
    assert len({s["id"] for s in SPECS}) == 25


def test_asserts_totales_congelados():
    """El total de asserts es el numero congelado del pre-registro.

    Si este test falla, alguien edito las specs DESPUES del freeze: eso
    invalida la comparabilidad del bench y va a 01_DESVIOS.md con fecha.
    """
    total = sum(len(full_asserts(s)) for s in SPECS)
    assert total == 363, f"total de asserts cambio: {total} != 363"


def test_pagina_vacia_falla_todo():
    """Una respuesta vacia no pasa ningun assert (0 puntos, no crash)."""
    results = check_page("", full_asserts(SPECS[0]))
    assert all(not r["ok"] for r in results)


def test_html_sin_estilo_falla_css():
    """HTML valido pero sin <style>: los asserts css_* fallan, no crashean."""
    html = ("<!DOCTYPE html><html lang='en'><head><title>x</title>"
            "<meta name='viewport' content='width=device-width'>"
            "</head><body><h1>x</h1></body></html>")
    results = check_page(html, [
        {"type": "doc_basics"},
        {"type": "css_rule", "sel": "body", "prop": "display"},
        {"type": "css_media"},
    ])
    assert results[0]["ok"] is True
    assert results[1]["ok"] is False
    assert results[2]["ok"] is False


# ── Brazo v1 repair (eje-3 CP1): describe_failed sin leakage ─────────────

def test_describe_failed_lenguaje_de_requisito():
    """describe_failed devuelve requisitos incumplidos (no el HTML correcto):
    cada linea traza a un requisito del prompt, no revela una respuesta oculta."""
    from cognia_v3.eval.bench_design import describe_failed, check_page, SPECS, full_asserts
    html = ("<!DOCTYPE html><html lang=en><head><title>x</title>"
            "<meta name=viewport content='width=device-width'>"
            "<style>body{margin:0}</style></head><body><h1>CloudBox</h1></body></html>")
    res = check_page(html, full_asserts(SPECS[0]))
    txt = describe_failed(res)
    assert txt  # hay requisitos incumplidos
    # es lenguaje de requisito, no markup de solucion
    assert "<article" not in txt and "```" not in txt
    assert "Falta" in txt or "debe" in txt.lower()


def test_describe_failed_pagina_perfecta_vacio():
    """Una pagina que pasa todo no genera feedback de repair."""
    from cognia_v3.eval.bench_design import describe_failed, check_page, GOOD_PAGE
    res = check_page(GOOD_PAGE, [{"type": "doc_basics"}, {"type": "lang_attr"}])
    assert describe_failed(res) == ""
