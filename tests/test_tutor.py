# -*- coding: utf-8 -*-
"""Tests del modo tutor (sin red, sin LLM, sin servidor real).

Contrato que fijan: la leccion NUNCA sale vacia, el modo se declara
siempre, el material envenenado que descarta el centinela llega como
'descartadas' (visible, no en silencio), y sin LLM se degrada con aviso en
vez de inventar. La API se prueba con TestClient contra fakes inyectados.
"""
import json

import pytest
from fastapi.testclient import TestClient

from cognia.tutor import motor
from cognia.tutor.motor import (Leccion, estudiar_tema, evaluar_respuesta,
                                responder_duda)


def _buscar_fake(consulta, max_resultados=3):
    return {
        "resultados": [
            {"titulo": "Guía de asyncio", "url": "https://ej.test/a",
             "via": "chromium",
             "texto": "asyncio gestiona corrutinas con un event loop. "
                      "Una corrutina se define con async def."},
            {"titulo": "Tasks", "url": "https://ej.test/b", "via": "chromium",
             "texto": "Las tasks programan corrutinas concurrentes."},
        ],
        "descartados": [{"url": "https://malo.test/x",
                         "razon": "centinela: patrón de inyección"}],
        "aviso": "1 candidato(s) descartados por el centinela",
    }


def _buscar_vacio(consulta, max_resultados=3):
    return {"resultados": [], "descartados": [], "aviso": "sin candidatos"}


def _infer_leccion(system, user):
    return json.dumps({
        "resumen": "asyncio permite concurrencia con corrutinas.",
        "puntos": [{"titulo": "Event loop", "explicacion": "Coordina tareas."},
                   {"titulo": "async def", "explicacion": "Define corrutinas."}],
        "preguntas": [{"pregunta": "¿Qué hace el event loop?",
                       "respuesta_esperada": "Coordina la ejecución de tareas."}],
    }, ensure_ascii=False)


# ── estudiar_tema ──────────────────────────────────────────────────────

def test_estudiar_con_llm_y_material(monkeypatch):
    monkeypatch.setattr(motor, "_guardar_tarjetas", lambda lec: [])
    lec = estudiar_tema("python asyncio", infer_fn=_infer_leccion,
                        buscar_fn=_buscar_fake)
    assert lec.modo == "llm+web"
    assert "corrutinas" in lec.resumen
    assert len(lec.puntos) == 2 and len(lec.preguntas) == 1
    assert [f["url"] for f in lec.fuentes] == ["https://ej.test/a",
                                               "https://ej.test/b"]
    # el descarte del centinela viaja hasta el alumno: nunca en silencio
    assert lec.descartadas and "inyección" in lec.descartadas[0]["razon"]


def test_estudiar_sin_llm_degrada_con_material_real(monkeypatch):
    monkeypatch.setattr(motor, "_guardar_tarjetas", lambda lec: [])
    lec = estudiar_tema("python asyncio", infer_fn=None,
                        buscar_fn=_buscar_fake)
    assert lec.modo == "sin-llm"
    assert "SIN LLM" in lec.aviso
    assert lec.puntos and "event loop" in lec.puntos[0]["explicacion"].lower()
    assert lec.resumen.strip()          # nunca vacio


def test_estudiar_sin_material_no_inventa(monkeypatch):
    monkeypatch.setattr(motor, "_guardar_tarjetas", lambda lec: [])
    lec = estudiar_tema("tema inexistente", infer_fn=_infer_leccion,
                        buscar_fn=_buscar_vacio)
    # sin material NO se llama al modelo: no se fabrica autoridad
    assert lec.modo == "sin-llm"
    assert lec.fuentes == []
    assert lec.resumen.strip()


def test_estudiar_modelo_devuelve_basura_degrada(monkeypatch):
    monkeypatch.setattr(motor, "_guardar_tarjetas", lambda lec: [])
    lec = estudiar_tema("python asyncio", buscar_fn=_buscar_fake,
                        infer_fn=lambda s, u: "lo siento, no puedo")
    assert lec.modo == "degradado"
    assert "no devolvio una leccion utilizable" in lec.aviso
    assert lec.puntos                    # cae al material real


def test_estudiar_modelo_explota_no_tumba_la_leccion(monkeypatch):
    monkeypatch.setattr(motor, "_guardar_tarjetas", lambda lec: [])

    def _boom(s, u):
        raise RuntimeError("backend caido")
    lec = estudiar_tema("python asyncio", buscar_fn=_buscar_fake,
                        infer_fn=_boom)
    assert lec.puntos and "el modelo fallo" in lec.aviso


def test_estudiar_tema_vacio():
    with pytest.raises(ValueError):
        estudiar_tema("   ", buscar_fn=_buscar_fake)


def test_buscador_roto_no_lanza(monkeypatch):
    monkeypatch.setattr(motor, "_guardar_tarjetas", lambda lec: [])

    def _boom(c, max_resultados=3):
        raise RuntimeError("sin red")
    lec = estudiar_tema("algo", infer_fn=_infer_leccion, buscar_fn=_boom)
    assert "sin material web" in lec.aviso and lec.resumen.strip()


# ── JSON del modelo ────────────────────────────────────────────────────

def test_json_del_modelo_tolera_prosa_y_fences():
    d = motor._json_del_modelo(
        'Claro, aquí tienes:\n```json\n{"resumen": "x", "puntos": []}\n```\nsaludos')
    assert d["resumen"] == "x"
    assert motor._json_del_modelo("sin json aqui") == {}
    # llaves dentro de una cadena no rompen el balanceo
    assert motor._json_del_modelo('{"a": "llave } dentro", "b": 1}')["b"] == 1


# ── dudas y evaluacion ─────────────────────────────────────────────────

def _lec_demo():
    return Leccion(tema="asyncio", resumen="r",
                   puntos=[{"titulo": "Event loop",
                            "explicacion": "coordina corrutinas y tareas"},
                           {"titulo": "Sockets", "explicacion": "red"}],
                   fuentes=[{"titulo": "t", "url": "u", "via": "chromium"}])


def test_responder_duda_sin_llm_usa_lo_mas_relacionado():
    r = responder_duda("que hace el event loop con las corrutinas",
                       _lec_demo(), infer_fn=None)
    assert r["modo"] == "sin-llm"
    assert "Event loop" in r["respuesta"]
    assert "Sin modelo disponible" in r["respuesta"]   # honesto


def test_responder_duda_con_llm():
    r = responder_duda("y eso?", _lec_demo(), infer_fn=lambda s, u: "porque si")
    assert r["modo"] == "llm" and r["respuesta"] == "porque si"


def test_responder_duda_llm_vacio_cae_al_deterministico():
    r = responder_duda("event loop", _lec_demo(), infer_fn=lambda s, u: "   ")
    assert r["modo"] == "sin-llm"


def test_evaluar_respuesta_vacia_es_cero():
    r = evaluar_respuesta("p", "esperada", "", infer_fn=lambda s, u: "x")
    assert r["calidad"] == 0 and r["correcto"] is False


def test_evaluar_con_llm_parsea_json():
    r = evaluar_respuesta(
        "p", "e", "mi respuesta",
        infer_fn=lambda s, u: '{"calidad": 4, "correcto": true, "retro": "bien"}')
    assert r["calidad"] == 4 and r["correcto"] and r["retro"] == "bien"


def test_evaluar_llm_basura_cae_a_solape():
    r = evaluar_respuesta("p", "el event loop coordina corrutinas",
                          "el event loop coordina corrutinas",
                          infer_fn=lambda s, u: "no se")
    assert r["modo"] == "solape" and r["calidad"] == 5


def test_evaluar_calidad_se_acota():
    r = evaluar_respuesta("p", "e", "r",
                          infer_fn=lambda s, u: '{"calidad": 99}')
    assert r["calidad"] == 5


# ── API HTTP ───────────────────────────────────────────────────────────

@pytest.fixture
def cliente(monkeypatch):
    from cognia.tutor import servidor
    monkeypatch.setattr(motor, "_guardar_tarjetas", lambda lec: [])
    monkeypatch.setattr(servidor, "_infer_fn", lambda: _infer_leccion)
    monkeypatch.setattr("cognia.knowledge.navegador.buscar_en_web",
                        _buscar_fake)
    servidor._ESTADO["leccion"] = None
    servidor._ESTADO["backend"] = "test"
    return TestClient(servidor.crear_app())


def test_api_flujo_completo(cliente):
    assert cliente.get("/api/estado").json()["tema"] is None

    r = cliente.post("/api/estudiar", json={"tema": "python asyncio"})
    assert r.status_code == 200
    lec = r.json()
    assert lec["modo"] == "llm+web" and lec["puntos"]
    assert cliente.get("/api/estado").json()["tema"] == "python asyncio"

    r = cliente.post("/api/preguntar", json={"duda": "¿y el event loop?"})
    assert r.status_code == 200 and r.json()["respuesta"]

    r = cliente.post("/api/responder",
                     json={"indice": 0, "respuesta": "coordina tareas"})
    assert r.status_code == 200 and "calidad" in r.json()


def test_api_preguntar_sin_leccion_da_400(cliente):
    r = cliente.post("/api/preguntar", json={"duda": "x"})
    assert r.status_code == 400 and "estudia un tema" in r.json()["error"]


def test_api_tema_vacio_da_400(cliente):
    r = cliente.post("/api/estudiar", json={"tema": "  "})
    assert r.status_code == 400


def test_api_pregunta_inexistente_da_400(cliente):
    cliente.post("/api/estudiar", json={"tema": "python asyncio"})
    r = cliente.post("/api/responder", json={"indice": 99, "respuesta": "x"})
    assert r.status_code == 400


def test_index_se_sirve(cliente):
    r = cliente.get("/")
    assert r.status_code == 200 and "Cognia Tutor" in r.text


# ── binding: loopback por defecto, LAN solo con --lan ──────────────────

def test_main_loopback_por_defecto(monkeypatch):
    from cognia.tutor import servidor
    visto = {}
    monkeypatch.setattr(servidor, "_arrancar_backend", lambda: "test")
    monkeypatch.setattr(servidor, "crear_app", lambda: object())
    import uvicorn
    monkeypatch.setattr(uvicorn, "run",
                        lambda app, **kw: visto.update(kw))
    servidor.main([])
    assert visto["host"] == "127.0.0.1" and visto["port"] == servidor.PUERTO


def test_main_lan_expone_con_aviso(monkeypatch, capsys):
    from cognia.tutor import servidor
    visto = {}
    monkeypatch.setattr(servidor, "_arrancar_backend", lambda: "test")
    monkeypatch.setattr(servidor, "crear_app", lambda: object())
    import uvicorn
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: visto.update(kw))
    servidor.main(["--lan"])
    assert visto["host"] == "0.0.0.0"
    salida = capsys.readouterr().out
    assert "SIN autenticacion" in salida        # el riesgo se declara
