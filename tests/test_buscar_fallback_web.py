# -*- coding: utf-8 -*-
"""Regresion 2026-07-25 (sesion 20260725-112753): "busca que es undertale".

El dueno pidio informacion del MUNDO y Cognia grepeo README.md ->
"sin coincidencias en 'README.md'". cognia/busqueda_web.py (wikipedia +
hackernews + arxiv) existia desde hacia tiempo y el agente no la alcanzaba:
capacidad construida y desconectada, el modo de fallo de la casa.

El fallback vive DENTRO de `buscar` y NO como tool nueva a proposito: el A/B
del 2026-07-25 midio que sumar tools al catalogo degrada al modelo chico
(camino feliz 4.25/5 -> 2.5/5), por eso las tools de imagen son opt-in.
"""
from cognia.agent.tools import _parece_pregunta_del_mundo, run_tool


def test_distingue_pregunta_del_mundo_de_patron_de_codigo():
    for p in ("que es undertale y quien lo desarrollo",
              "quien desarrollo undertale",
              "busca en internet que es undertale",
              "quien invento la penicilina"):
        assert _parece_pregunta_del_mundo(p), p
    # exige senal POSITIVA de pregunta: un grep legitimo de varias palabras
    # ("archivo config settings") NO puede irse a Wikipedia
    for p in ("def procesar_datos", "class VectorCache", "import numpy",
              "README.md", "cognia/cli.py", "x", "self._matrix[0]",
              "archivo config settings", "undertale desarrollo GitHub"):
        assert not _parece_pregunta_del_mundo(p), p


def test_grep_normal_no_se_va_a_la_web(tmp_path):
    """Lo que SI esta en los archivos se responde con los archivos."""
    f = tmp_path / "codigo.py"
    f.write_text("def procesar_datos():\n    return 42\n", encoding="utf-8")
    r = run_tool("buscar", f"procesar_datos | {tmp_path}", {})
    assert "codigo.py" in r
    assert "WEB" not in r


def test_sin_coincidencias_y_patron_tecnico_no_dispara_web(tmp_path):
    r = run_tool("buscar", f"def_que_no_existe_jamas | {tmp_path}", {})
    assert "sin coincidencias" in r
    assert "WEB" not in r


def test_pregunta_del_mundo_consulta_la_web(tmp_path, monkeypatch):
    """El caso del dueno. Con la web simulada: el contrato es que se consulte
    y que el resultado llegue al agente, no que Wikipedia diga X hoy."""
    llamadas = {}

    def _fake_buscar(consulta, max_resultados=5, fuentes=None):
        llamadas["consulta"] = consulta
        llamadas["fuentes"] = fuentes
        return [{"titulo": "Undertale", "fuente": "wikipedia",
                 "fragmento": "videojuego de rol de 2015 creado por Toby Fox",
                 "url": "https://es.wikipedia.org/wiki/Undertale"}]

    import cognia.busqueda_web as bw
    monkeypatch.setattr(bw, "buscar", _fake_buscar)

    r = run_tool("buscar", f"que es undertale y quien lo desarrollo | {tmp_path}", {})
    assert "Toby Fox" in r and "wikipedia" in r
    assert "nada en los archivos" in r
    assert llamadas["consulta"] == "que es undertale y quien lo desarrollo"
    # arxiv fuera: en una pregunta general mete ruido (medido: un paper de
    # charmonium entre los resultados de "que es undertale")
    assert llamadas["fuentes"] == ("wikipedia", "hackernews")


def test_si_la_web_falla_no_rompe_la_tool(tmp_path, monkeypatch):
    """Sin red, `buscar` tiene que seguir contestando su mensaje de siempre."""
    import cognia.busqueda_web as bw

    def _explota(*a, **k):
        raise RuntimeError("sin red")

    monkeypatch.setattr(bw, "buscar", _explota)
    r = run_tool("buscar", f"que es undertale y quien lo desarrollo | {tmp_path}", {})
    assert "sin coincidencias" in r
