# -*- coding: utf-8 -*-
"""Tests del panel de analíticas agregado (cognia/analytics/panel.py)."""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from cognia.analytics import panel as P


def _escribir_bon(path, filas):
    path.write_text("\n".join(json.dumps(f) for f in filas) + "\n",
                    encoding="utf-8")


def test_resumen_codigo_agrega_bien(tmp_path):
    bon = tmp_path / "bon.jsonl"
    _escribir_bon(bon, [
        {"difficulty": 0.2, "rank_mode": "tests_greedy_early", "score": 2,
         "total": 2, "secs": 10.0},
        {"difficulty": 0.8, "rank_mode": "7b_greedy", "score": 1, "total": 3,
         "secs": 40.0, "escalado_7b": True},
        {"difficulty": 0.6, "rank_mode": "superorganismo", "score": 5,
         "total": 5, "secs": 300.0, "superorganismo": True},
    ])
    r = P.resumen_codigo(path=bon)
    assert r["n"] == 3
    assert r["escalado_7b"] == 1 and r["superorganismo"] == 1
    assert r["dificultad_media"] == pytest.approx(0.533, abs=0.01)
    assert r["secs_medio"] == pytest.approx(116.7, abs=0.1)
    # exito = score>=total en las que tienen total: fila1 (2/2) y fila3 (5/5)
    assert r["exito_tests_visibles"] == "2/3"
    assert r["rank_mode"]["superorganismo"] == 1


def test_resumen_codigo_vacio_y_lineas_rotas(tmp_path):
    assert P.resumen_codigo(path=tmp_path / "no_existe.jsonl") == {"n": 0}
    bon = tmp_path / "roto.jsonl"
    bon.write_text('{"difficulty": 0.5, "total": 1, "score": 1}\n'
                   'ESTO NO ES JSON\n'
                   '{"difficulty": 0.5, "total": 0}\n', encoding="utf-8")
    r = P.resumen_codigo(path=bon)
    assert r["n"] == 2                 # la línea rota se ignora, no rompe


def test_resumen_eventos_desglosa_sentinel_y_tools():
    from cognia.events import emit, get_bus
    get_bus().limpiar()
    emit("tool.ejecutada", nombre="git", ok=True)
    emit("tool.ejecutada", nombre="x", ok=False)
    emit("sentinel.evaluada", veredicto="allow")
    emit("sentinel.evaluada", veredicto="block")
    r = P.resumen_eventos()
    get_bus().limpiar()
    assert r["total"] == 4
    assert r["por_tipo"]["tool.ejecutada"] == 2
    assert r["sentinel"] == {"allow": 1, "block": 1}
    assert r["tools_ok"]["True"] == 1 and r["tools_ok"]["False"] == 1


def test_resumen_features_con_fake():
    class _FakeAnalytics:
        def get_top_features(self, user_id, days, limit):
            return [{"feature": "hacer", "total": 12},
                    {"feature": "buscar", "total": 5}]

        def get_stats(self, user_id):
            return {"total_events": 17, "active_days": 3, "streak": 2}

    r = P.resumen_features(analytics=_FakeAnalytics())
    assert r["top"][0]["feature"] == "hacer"
    assert r["stats"]["streak"] == 2


def test_render_texto_no_rompe_con_todo_vacio(monkeypatch):
    monkeypatch.setattr(P, "resumen_codigo", lambda *a, **k: {"n": 0})
    monkeypatch.setattr(P, "resumen_features",
                        lambda *a, **k: {"top": [], "stats": {}})
    monkeypatch.setattr(P, "resumen_eventos",
                        lambda *a, **k: {"total": 0, "por_tipo": {}})
    txt = P.render_texto()
    assert "ANALITICAS COGNIA" in txt
    assert "sin registros" in txt and "sin datos" in txt


def test_render_texto_con_datos(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "resumen_codigo", lambda *a, **k: {
        "n": 5, "dificultad_media": 0.5, "secs_medio": 30.0,
        "exito_tests_visibles": "3/5", "escalado_7b": 1, "escalado_q35": 0,
        "mesa_redonda": 0, "superorganismo": 1,
        "rank_mode": {"7b_greedy": 2, "superorganismo": 1}})
    monkeypatch.setattr(P, "resumen_features", lambda *a, **k: {
        "top": [{"feature": "hacer", "total": 9}],
        "stats": {"total_events": 9, "active_days": 2, "streak": 1}})
    monkeypatch.setattr(P, "resumen_eventos", lambda *a, **k: {
        "total": 3, "por_tipo": {"tool.ejecutada": 3},
        "sentinel": {"allow": 3}})
    txt = P.render_texto()
    assert "superorg=1" in txt and "hacer(9)" in txt and "racha: 1" in txt
