# -*- coding: utf-8 -*-
"""Los cuatro fallos SILENCIOSOS que la auditoria del 2026-07-24 saco a la luz.

El patron es siempre el mismo y es el que el repo tiene documentado como su modo
de falla tipico: no explota, se calla y devuelve algo plausible. Un contador que
no sube, un buscador que responde vacio con error=None, un filtro que dice que
si a todo, un producto al que se culpa por un fallo del sistema operativo.
"""
import types

import pytest


# ── 1. El ciclo de investigacion autonoma nunca corria ─────────────────────────

def test_game_manager_importa_por_la_ruta_real():
    """Los tres imports hermanos (`researcher`, `knowledge_integrator`,
    `generator`) no resolvian NUNCA: el except se los tragaba, el ciclo caia a
    _memory_cycle() y se reportaba 'idle' OK con searches_done clavado en 0."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "cognia_v3" /
           "interfaces" / "game_manager.py").read_text(encoding="utf-8")
    assert "from cognia.research_engine.researcher import" in src
    assert "from cognia.research_engine.knowledge_integrator import" in src
    assert "from cognia.program_creator.generator import" in src
    # y los hermanos sueltos ya no estan
    assert "\n            from researcher import" not in src
    assert "\n        from generator import" not in src


def test_las_rutas_de_investigacion_existen_de_verdad():
    """No alcanza con escribir bien el import: el simbolo tiene que estar."""
    from cognia.research_engine.researcher import research_question
    from cognia.research_engine.knowledge_integrator import integrate_research
    from cognia.program_creator.generator import FALLBACK_CATEGORIES
    assert callable(research_question) and callable(integrate_research)
    assert FALLBACK_CATEGORIES


# ── 2. El buscador web devolvia vacio con error=None ───────────────────────────

def test_web_search_cae_al_buscador_real_si_instant_answer_viene_vacio(monkeypatch):
    """La Instant Answer API no es un buscador: ante consulta tecnica devuelve
    todo vacio. Antes eso salia como exito (error=None) y /buscar-web imprimia
    '(Sin resultados)' sin que nadie supiera por que."""
    from cognia.search.web_search import WebSearch

    w = WebSearch()
    # la instant answer responde vacio
    monkeypatch.setattr(w, "_parse_response", lambda data, n: {
        "query": "x", "abstract": "", "abstract_source": "",
        "related_topics": [], "answer": "", "cached": False, "error": None})
    # y el buscador real SI encuentra
    monkeypatch.setattr("cognia.busqueda_web.buscar", lambda c, max_resultados=5: [
        {"titulo": "Howl: Wake Word Detection", "url": "http://arxiv.org/abs/1",
         "fragmento": "un sistema de deteccion de palabra de activacion",
         "fuente": "arxiv"}])
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("no deberia llegar aca")), raising=False)

    r = w._buscar_de_verdad("wake word detection", 3)
    assert r["abstract"]
    assert r["related_topics"] and "Howl" in r["related_topics"][0]
    assert r["error"] is None


def test_web_search_sin_resultados_lo_dice_en_error(monkeypatch):
    """Si tampoco el buscador real encuentra, deja de ser un exito silencioso."""
    from cognia.search.web_search import WebSearch
    monkeypatch.setattr("cognia.busqueda_web.buscar", lambda c, max_resultados=5: [])
    r = WebSearch()._buscar_de_verdad("asdkjhasd", 3)
    assert r["error"] and "sin resultados" in r["error"]


def test_util_distingue_respuesta_vacia():
    from cognia.search.web_search import WebSearch
    assert WebSearch._util({"abstract": "algo", "related_topics": [], "answer": ""})
    assert WebSearch._util({"abstract": "", "related_topics": ["x"], "answer": ""})
    assert not WebSearch._util({"abstract": "  ", "related_topics": [], "answer": ""})


# ── 3. El filtro de pertinencia decia que si a todo ────────────────────────────

def test_contexto_pertinente_discrimina():
    """Con el import roto devolvia True SIEMPRE (y de forma no determinista,
    segun quien hubiera importado antes cognia_v3.core.investigador)."""
    from cognia.language_engine import LanguageEngine
    le = LanguageEngine.__new__(LanguageEngine)
    assert le._contexto_pertinente(
        "como funciona la fotosintesis en las plantas",
        "el precio del bitcoin subio ayer tras la reserva federal") is False
    assert le._contexto_pertinente(
        "como funciona la fotosintesis en las plantas",
        "las plantas usan la luz solar para la fotosintesis") is True


# ── 4. Se culpaba al producto por un fallo del sistema operativo ───────────────

def test_fallo_del_so_no_se_le_carga_al_producto(tmp_path, monkeypatch):
    """Si el SO no puede crear el subproceso, el veredicto es INDETERMINADO
    (ok=None), no 'el producto falla'. Culparlo seria un veredicto falso y
    ademas volvia flaky a los tests que dependen de esta fase."""
    import cognia.autoprueba as ap

    prod = tmp_path / "p"
    prod.mkdir()
    (prod / "main.py").write_text("def f():\n    return 1\n", encoding="utf-8")

    monkeypatch.setattr(ap, "_correr", lambda *a, **k: (
        ap.RC_NO_LANZO, "", "[autoprueba] no se pudo lanzar: [Errno 1455] paging file too small", False))

    fase = ap._fase_importa({"entrypoint": str(prod / "main.py"),
                             "directorio": str(prod)}, 6)
    assert fase["ok"] is None                 # ni True ni False: indeterminado
    assert fase.get("entorno") is True
    assert "no pudo lanzar" in fase["detalle"]


def test_codigos_de_retorno_nombrados():
    """Los -3/-4 magicos fueron justo lo que dejo pasar el bug."""
    import cognia.autoprueba as ap
    assert ap.RC_TIMEOUT == -3 and ap.RC_NO_LANZO == -4
